# Copyright (c) 2026 Iakovosv. All rights reserved.
# Personal use only. Commercial use requires written permission.
# See LICENSE and COMMERCIAL.md. Redistribution prohibited.
"""Optional notification and announcement for an access event.

Every setting here is off by default: the listener is cheap while nothing is enabled, and it
does nothing until the user turns it on from the integration's settings page.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import (
    CONF_NOTIFY_ALL,
    CONF_NOTIFY_DENIED,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_MESSAGE,
    CONF_NOTIFY_NAMES,
    CONF_NOTIFY_NAMED_MESSAGE,
    CONF_NOTIFY_NAMED_TITLE,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TITLE,
    CONF_TTS_ENABLED,
    CONF_TTS_ALL,
    CONF_TTS_ENTITY,
    CONF_TTS_MESSAGE,
    CONF_TTS_MEDIA_PLAYER,
    DEFAULT_NOTIFY_MESSAGE,
    DEFAULT_NOTIFY_NAMED_MESSAGE,
    DEFAULT_NOTIFY_NAMED_TITLE,
    DEFAULT_NOTIFY_TITLE,
    DEFAULT_TTS_MESSAGE,
    DOMAIN,
    EVENT_TYPE_ACCESS,
)
from .methods import method_label

_LOGGER = logging.getLogger(__name__)

# Service domains and names are used as plain strings: importing `homeassistant.components.tts`
# pulls in `mutagen`, and notify/tts are optional companion components anyway.
DOMAIN_NOTIFY: Final = "notify"
SERVICE_SEND_MESSAGE: Final = "send_message"
DOMAIN_TTS: Final = "tts"
SERVICE_SPEAK: Final = "speak"

DEFAULT_NOTIFY_DENIED_MESSAGE: Final = "{name} was refused access (door {door}) at {time}"


def _as_template(value: Any, default: str) -> str:
    """Return a non-empty template, falling back to the default."""

    if isinstance(value, str) and value.strip():
        return value
    return default


def _split_names(value: Any) -> list[str]:
    """Split the watched-names setting into lowercase names."""

    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        return []
    return [str(part).strip().casefold() for part in parts if str(part).strip()]


def _render(template: str, values: dict[str, str]) -> str:
    """Fill a message template, leaving unknown placeholders untouched.

    A literal `{` or `}` in a template must not raise, so this is a plain substitution rather
    than `str.format`.
    """

    result = template
    for key, value in values.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def _values(hass: HomeAssistant, data: dict[str, Any], serial_no: str) -> dict[str, str]:
    """Build the placeholder values for one event."""

    when = dt_util.parse_datetime(data.get("time") or "") or dt_util.utcnow()
    local = dt_util.as_local(when)
    device_name = ""
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, serial_no)})
    if device is not None:
        device_name = device.name_by_user or device.name or ""
    return {
        "name": str(data.get("name") or data.get("employee_no") or ""),
        "employee_no": str(data.get("employee_no") or ""),
        "card_no": str(data.get("card_no") or ""),
        "door": str(data.get("door_no") if data.get("door_no") is not None else ""),
        "method": method_label(hass.config.language, data.get("method")),
        "time": local.strftime("%H:%M:%S"),
        "date": local.strftime("%Y-%m-%d"),
        "device": device_name,
    }


@callback
def async_setup_notifications(hass: HomeAssistant, entry) -> None:
    """Listen for the entry's access events and dispatch what the options enable."""

    options = entry.options or {}

    watch_all = bool(options.get(CONF_NOTIFY_ALL, False))
    watched_names = _split_names(options.get(CONF_NOTIFY_NAMES))
    notify_enabled = bool(options.get(CONF_NOTIFY_ENABLED, False))
    notify_service = str(options.get(CONF_NOTIFY_SERVICE) or "").strip()
    notify_denied = bool(options.get(CONF_NOTIFY_DENIED, False))
    tts_enabled = bool(options.get(CONF_TTS_ENABLED, False))
    tts_all = bool(options.get(CONF_TTS_ALL, False))
    tts_entity = str(options.get(CONF_TTS_ENTITY) or "").strip()
    tts_media_player = str(options.get(CONF_TTS_MEDIA_PLAYER) or "").strip()

    wants_notify = notify_enabled and bool(notify_service) and (watch_all or watched_names or notify_denied)
    wants_tts = (
        tts_enabled
        and bool(tts_entity)
        and bool(tts_media_player)
        and (tts_all or watched_names)
    )

    if not wants_notify and not wants_tts:
        return

    @callback
    def async_handle_event(event: Event) -> None:
        data = event.data
        if data.get("device_id") != entry.runtime_data.serial_no:
            return

        name = str(data.get("name") or data.get("employee_no") or "")
        fold = name.casefold()
        named = bool(fold) and fold in watched_names
        granted = bool(data.get("granted", True))

        # Notify and announce have their own "every entry" switch, so one may be silent
        # while the other still fires.
        if granted:
            do_notify = wants_notify and (watch_all or named)
            do_tts = wants_tts and (tts_all or named)
        else:
            do_notify = wants_notify and notify_denied
            do_tts = False

        if not do_notify and not do_tts:
            return

        values = _values(hass, data, entry.runtime_data.serial_no)

        if do_notify and granted:
            title = _as_template(
                options.get(CONF_NOTIFY_NAMED_TITLE) if named else options.get(CONF_NOTIFY_TITLE),
                DEFAULT_NOTIFY_NAMED_TITLE if named else DEFAULT_NOTIFY_TITLE,
            )
            message = _as_template(
                options.get(CONF_NOTIFY_NAMED_MESSAGE) if named else options.get(CONF_NOTIFY_MESSAGE),
                DEFAULT_NOTIFY_NAMED_MESSAGE if named else DEFAULT_NOTIFY_MESSAGE,
            )
            hass.async_create_task(
                hass.services.async_call(
                    DOMAIN_NOTIFY,
                    SERVICE_SEND_MESSAGE,
                    {"message": _render(message, values), "title": _render(title, values)},
                    target={"entity_id": notify_service},
                    blocking=False,
                )
            )
        elif do_notify:
            title = _as_template(options.get(CONF_NOTIFY_TITLE), DEFAULT_NOTIFY_TITLE)
            hass.async_create_task(
                hass.services.async_call(
                    DOMAIN_NOTIFY,
                    SERVICE_SEND_MESSAGE,
                    {
                        "message": _render(DEFAULT_NOTIFY_DENIED_MESSAGE, values),
                        "title": _render(title, values),
                    },
                    target={"entity_id": notify_service},
                    blocking=False,
                )
            )

        if do_tts:
            message = _as_template(options.get(CONF_TTS_MESSAGE), DEFAULT_TTS_MESSAGE)
            hass.async_create_task(
                hass.services.async_call(
                    DOMAIN_TTS,
                    SERVICE_SPEAK,
                    {
                        "media_player_entity_id": tts_media_player,
                        "message": _render(message, values),
                    },
                    target={"entity_id": tts_entity},
                    blocking=False,
                )
            )

    entry.async_on_unload(hass.bus.async_listen(EVENT_TYPE_ACCESS, async_handle_event))
