"""Diagnostics support for the hikvision_access integration."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .isapi import HikvisionAccessError

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
        # Setup failed before a coordinator existed; the entry fields are all we can show.
        return {
            "entry": async_redact_data(entry.as_dict(), TO_REDACT),
            "note": "The integration is not set up, so no endpoint probe could be run.",
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
        "last_exception": type(coordinator.last_exception).__name__ if coordinator.last_exception else None,
        "probe": {},
    }

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
    )

    for name, method, path, data in probes:
        try:
            await client.request(method, path, data=data)
        except HikvisionAccessError as ex:
            diagnostics["probe"][name] = f"{type(ex).__name__}: {ex}"
        else:
            diagnostics["probe"][name] = "ok"

    return diagnostics

