# Copyright (c) 2026 Iakovosv. All rights reserved.
# Personal use only. Commercial use requires written permission.
# See LICENSE and COMMERCIAL.md. Redistribution prohibited.
"""Services for the hikvision_access integration."""

from __future__ import annotations

import logging
import secrets

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BEGIN_TIME,
    ATTR_CARD_NO,
    ATTR_DOOR_NO,
    ATTR_EMPLOYEE_NO,
    ATTR_END_TIME,
    ATTR_GENDER,
    ATTR_MAX_TIMES,
    ATTR_NAME,
    ATTR_PIN,
    ATTR_USER_TYPE,
    DOMAIN,
    EVENT_VISITOR_CREATED,
    GENDERS,
    SERVICE_CREATE_VISITOR,
    SERVICE_DELETE_USER,
    SERVICE_OPEN_DOOR,
    USER_TYPES,
)
from .coordinator import HikvisionAccessCoordinator
from .isapi import HikvisionAccessError

_LOGGER = logging.getLogger(__name__)

CREATE_VISITOR_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): cv.string,
        vol.Required(ATTR_BEGIN_TIME): cv.datetime,
        vol.Required(ATTR_END_TIME): cv.datetime,
        vol.Optional(ATTR_EMPLOYEE_NO): vol.All(cv.string, vol.Length(min=1, max=32)),
        vol.Optional(ATTR_PIN): vol.All(cv.string, vol.Length(min=4, max=8)),
        vol.Optional(ATTR_DOOR_NO, default=1): vol.Coerce(int),
        vol.Optional(ATTR_GENDER): vol.In(GENDERS),
        vol.Optional(ATTR_USER_TYPE, default="visitor"): vol.In(USER_TYPES),
        vol.Optional(ATTR_CARD_NO): cv.string,
        vol.Optional(ATTR_MAX_TIMES): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

DELETE_USER_SCHEMA = vol.Schema({vol.Required(ATTR_EMPLOYEE_NO): cv.string})

OPEN_DOOR_SCHEMA = vol.Schema({vol.Optional(ATTR_DOOR_NO, default=1): vol.Coerce(int)})


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register services once."""

    if hass.services.has_service(DOMAIN, SERVICE_CREATE_VISITOR):
        return

    async def _coordinator_for(call: ServiceCall) -> HikvisionAccessCoordinator:
        entries = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
        if not entries:
            raise HomeAssistantError("No Hikvision access control device is configured")
        return entries[0].runtime_data

    async def handle_create_visitor(call: ServiceCall) -> None:
        """Create a visitor with a validity window and a PIN."""

        coordinator = await _coordinator_for(call)
        name = call.data[ATTR_NAME]
        begin = dt_util.as_local(call.data[ATTR_BEGIN_TIME])
        end = dt_util.as_local(call.data[ATTR_END_TIME])
        pin = call.data.get(ATTR_PIN)
        employee_no = call.data.get(ATTR_EMPLOYEE_NO)

        if end <= begin:
            raise HomeAssistantError("end_time must be later than begin_time")

        if employee_no is None:
            employee_no = await _next_employee_no(coordinator)
        if pin is None:
            pin = f"{secrets.randbelow(10**6):06d}"

        await coordinator.client.create_person(
            employee_no=employee_no,
            name=name,
            begin_time=begin,
            end_time=end,
            pin=pin,
            door_no=call.data[ATTR_DOOR_NO],
            gender=call.data.get(ATTR_GENDER),
            user_type=call.data.get(ATTR_USER_TYPE, "visitor"),
            card_no=(call.data.get(ATTR_CARD_NO) or "").strip() or None,
            max_times=call.data.get(ATTR_MAX_TIMES),
        )

        hass.bus.async_fire(
            EVENT_VISITOR_CREATED,
            {
                "device_id": coordinator.serial_no,
                "name": name,
                "employee_no": employee_no,
                "pin": pin,
                "begin_time": begin.isoformat(),
                "end_time": end.isoformat(),
                "max_times": call.data.get(ATTR_MAX_TIMES),
            },
        )

    async def handle_delete_user(call: ServiceCall) -> None:
        """Delete a person from the terminal."""

        coordinator = await _coordinator_for(call)
        await coordinator.client.delete_person(call.data[ATTR_EMPLOYEE_NO])

    async def handle_open_door(call: ServiceCall) -> None:
        """Unlock a door once."""

        coordinator = await _coordinator_for(call)
        door_no = call.data[ATTR_DOOR_NO]
        await coordinator.client.request(
            "PUT",
            "AccessControl/RemoteControl/door/1" if door_no == 1 else f"AccessControl/RemoteControl/door/{door_no}",
            data="<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>",
            headers={"Content-Type": "application/xml"},
        )

    hass.services.async_register(DOMAIN, SERVICE_CREATE_VISITOR, handle_create_visitor, schema=CREATE_VISITOR_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DELETE_USER, handle_delete_user, schema=DELETE_USER_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_OPEN_DOOR, handle_open_door, schema=OPEN_DOOR_SCHEMA)


async def _next_employee_no(coordinator: HikvisionAccessCoordinator) -> str:
    """Allocate a free employee number for a visitor.

    Visitor numbers start at 900000 so they do not overlap staff, but any number
    already in use on the device is skipped so an existing person is never overwritten.
    """

    existing = await _existing_employee_nos(coordinator)
    number = 900001
    while str(number) in existing:
        number += 1
    return str(number)


async def _existing_employee_nos(coordinator: HikvisionAccessCoordinator) -> set[str]:
    """Return the employee numbers currently enrolled on the device."""

    numbers: set[str] = set()
    position = 0
    while True:
        try:
            body = await coordinator.client.get_users(position=position, max_results=100)
        except HikvisionAccessError as ex:
            _LOGGER.debug("Could not read the user list, using a fresh visitor number: %s", ex)
            break

        info = body.get("UserInfoSearch", {})
        users = info.get("UserInfo") or []
        if isinstance(users, dict):
            users = [users]
        for user in users:
            if user.get("employeeNo") is not None:
                numbers.add(str(user["employeeNo"]))

        if info.get("responseStatusStrg") != "MORE" or not users:
            break
        position += len(users)

    return numbers
