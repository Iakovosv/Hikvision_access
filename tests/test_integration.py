"""End to end tests: set up the integration and exercise entities and services."""

from __future__ import annotations

import httpx
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.hikvision_access.const import (
    DOMAIN,
    EVENT_TYPE_ACCESS,
    EVENT_VISITOR_CREATED,
    SERVICE_CREATE_VISITOR,
    SERVICE_DELETE_USER,
    SERVICE_OPEN_DOOR,
)

from .conftest import DEVICE_INFO, decoder, make_handler

ACCESS_EVENT = {
    "major": 5,
    "minor": 75,
    "time": "2026-09-28T09:15:00+03:00",
    "name": "Maria",
    "employeeNoString": "900001",
    "doorNo": 1,
    "eventId": "evt-1",
}


async def _setup(hass: HomeAssistant, monkeypatch, events=None):
    """Set up the integration against the fake terminal and return the entry."""

    captured: list[httpx.Request] = []
    session = httpx.AsyncClient(transport=httpx.MockTransport(make_handler(events or [], captured)))

    monkeypatch.setattr("custom_components.hikvision_access.get_async_client", lambda *a, **k: session)

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        data={
            "host": "http://192.0.2.10",
            "username": "admin",
            "password": "secret",
            "verify_ssl": True,
        },
        unique_id=DEVICE_INFO["DeviceInfo"]["serialNumber"],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, captured


async def test_setup_registers_device_and_binary_sensor(hass: HomeAssistant, monkeypatch) -> None:
    """Setup creates the device and the last access binary sensor."""

    entry, _ = await _setup(hass, monkeypatch, [ACCESS_EVENT])

    from homeassistant.helpers import device_registry as dr

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "DSK1T805TEST0001"), entry.entry_id
    )
    assert device is not None
    assert device.model == "DS-K1T805MBFWX"

    states = [s for s in hass.states.async_all("binary_sensor") if s.entity_id.startswith("binary_sensor.")]
    assert states
    state = states[0]
    assert state.attributes["name"] == "Maria"
    assert state.attributes["employee_no"] == "900001"


async def test_access_event_fires_ha_event(hass: HomeAssistant, monkeypatch) -> None:
    """A granted access fires on the event bus with the person details."""

    received = []
    hass.bus.async_listen(EVENT_TYPE_ACCESS, lambda event: received.append(event))
    entry, _ = await _setup(hass, monkeypatch, [ACCESS_EVENT])

    assert len(received) == 1
    assert received[0].data["name"] == "Maria"
    assert received[0].data["device_id"] == "DSK1T805TEST0001"


async def test_create_visitor_service_generates_pin(hass: HomeAssistant, monkeypatch) -> None:
    """The service creates a person and publishes the generated PIN."""

    entry, captured = await _setup(hass, monkeypatch)
    created = []
    hass.bus.async_listen(EVENT_VISITOR_CREATED, lambda event: created.append(event))

    begin = dt_util.parse_datetime("2026-10-01T09:00:00+03:00")
    end = dt_util.parse_datetime("2026-10-01T21:00:00+03:00")
    await hass.services.async_call(
        DOMAIN,
        SERVICE_CREATE_VISITOR,
        {"name": "Visitor One", "begin_time": begin, "end_time": end},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(created) == 1
    assert created[0].data["pin"].isdigit()
    assert len(created[0].data["pin"]) == 6
    assert created[0].data["employee_no"].startswith("90000")

    record = [r for r in captured if r.url.path.endswith("UserInfo/Record")][-1]
    user = decoder(record)["UserInfo"]
    assert user["name"] == "Visitor One"
    assert user["password"] == created[0].data["pin"]
    # The device expects its own local clock time, so the service converts to HA local time.
    assert user["Valid"]["beginTime"] == dt_util.as_local(begin).strftime("%Y-%m-%dT%H:%M:%S")
    assert user["Valid"]["endTime"] == dt_util.as_local(end).strftime("%Y-%m-%dT%H:%M:%S")


async def test_delete_user_service(hass: HomeAssistant, monkeypatch) -> None:
    """The delete service sends the employee number."""

    entry, captured = await _setup(hass, monkeypatch)

    await hass.services.async_call(DOMAIN, SERVICE_DELETE_USER, {"employee_no": "900001"}, blocking=True)
    await hass.async_block_till_done()

    delete = [r for r in captured if r.url.path.endswith("UserInfo/Delete")][-1]
    assert decoder(delete)["UserInfoDelCond"]["EmployeeNoList"] == [{"employeeNo": "900001"}]


async def test_open_door_service(hass: HomeAssistant, monkeypatch) -> None:
    """The open door service sends the RemoteControlDoor command."""

    entry, captured = await _setup(hass, monkeypatch)

    await hass.services.async_call(DOMAIN, SERVICE_OPEN_DOOR, {"door_no": 1}, blocking=True)
    await hass.async_block_till_done()

    door = [r for r in captured if r.url.path.endswith("RemoteControl/door/1")][-1]
    assert b"<cmd>open</cmd>" in door.content
