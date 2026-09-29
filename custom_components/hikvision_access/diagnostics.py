"""Diagnostics support for the hikvision_access integration."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

from .isapi import HikvisionAccessClient, HikvisionAccessError

TO_REDACT = {CONF_HOST, CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    The endpoint probe shows which ISAPI calls the account may use, which is what
    distinguishes a wrong password from a missing permission. Host and credentials are
    redacted; probe results only carry status codes and error strings.
    """

    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        # Setup failed before a coordinator existed, which is exactly when the probe is
        # most useful: the entry fields alone say nothing about which call was refused.
        return {
            "entry": async_redact_data(entry.as_dict(), TO_REDACT),
            "probe": await _probe_endpoints(hass, entry),
            "note": "The integration is not set up, so these probes were run directly.",
        }

    client = coordinator.client
    diagnostics: dict[str, Any] = {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "device": {
            "serial_number": coordinator.serial_no,
            "model": coordinator.device_info.get("model"),
            "firmware": coordinator.device_info.get("firmwareVersion"),
        },
        "last_update_success": coordinator.last_update_success,
        "event_access_denied": coordinator.event_access_denied,
        "door_numbers": coordinator.door_numbers,
        "persons_enrolled": coordinator.persons_enrolled,
        "last_exception": type(coordinator.last_exception).__name__ if coordinator.last_exception else None,
        "probe": await _probe_endpoints(hass, entry, client=client),
    }

    return diagnostics


async def _probe_endpoints(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: HikvisionAccessClient | None = None,
) -> dict[str, str]:
    """Report which ISAPI calls the configured account is allowed to use."""

    if client is None:
        verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
        client = HikvisionAccessClient(
            host=entry.data[CONF_HOST],
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            verify_ssl=verify_ssl,
            session=get_async_client(hass, verify_ssl),
        )

    probes: tuple[tuple[str, str, str, str | None], ...] = (
        ("device_info", "GET", "System/deviceInfo", None),
        (
            "access_events",
            "POST",
            "AccessControl/AcsEvent?format=json",
            json.dumps(
                {
                    "AcsEventCond": {
                        "searchID": "hikvision-access-diagnostics",
                        "searchResultPosition": 0,
                        "maxResults": 1,
                        "major": 5,
                        "minor": 75,
                        "startTime": "1970-01-01T00:00:00",
                        "endTime": "1970-01-01T00:00:01",
                    }
                }
            ),
        ),
        (
            "person_list",
            "POST",
            "AccessControl/UserInfo/Search?format=json",
            json.dumps(
                {
                    "UserInfoSearchCond": {
                        "searchID": "hikvision-access-diagnostics",
                        "searchResultPosition": 0,
                        "maxResults": 1,
                    }
                }
            ),
        ),
        (
            "person_count",
            "GET",
            "AccessControl/UserInfo/Count?format=json",
            None,
        ),
        (
            "door_count",
            "GET",
            "AccessControl/Door/Count?format=json",
            None,
        ),
    )

    result: dict[str, str] = {}
    for name, method, path, data in probes:
        try:
            await client.request(method, path, data=data)
        except HikvisionAccessError as ex:
            result[name] = f"{type(ex).__name__}: {ex}"
        else:
            result[name] = "ok"

    return result

