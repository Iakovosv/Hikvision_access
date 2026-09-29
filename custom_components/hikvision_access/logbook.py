"""Describe access events in the Home Assistant logbook."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
    LazyEventPartialState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.translation import async_get_cached_translations

from .const import DOMAIN, EVENT_TYPE_ACCESS

_MISSING = "?"


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[
        [str, str, Callable[[LazyEventPartialState], dict[str, str]]], None
    ],
) -> None:
    """Teach the logbook how to render an access event."""

    language = hass.config.language or "en"

    def _translate(key: str, values: dict[str, str]) -> str:
        """Look a template up in the integration's translations and fill it in.

        The string is read from the same translation files the rest of the integration
        uses, so a logbook line follows the Home Assistant language. Placeholders are
        substituted by hand because these strings are not entity names.
        """

        line = async_get_cached_translations(hass, language, "logbook", DOMAIN).get(
            f"component.{DOMAIN}.logbook.{key}", key
        )
        for name, value in values.items():
            line = line.replace(f"{{{name}}}", value)
        return line

    @callback
    def async_describe_access(event: LazyEventPartialState) -> dict[str, str]:
        """Describe one access event for the logbook."""

        data = event.data
        name = data.get("name") or data.get("employee_no")
        method = data.get("method") or "access"
        card = data.get("card_no")
        door = data.get("door_no")

        if not data.get("granted", True):
            key = "denied"
        elif card:
            key = "granted_with_card"
        else:
            key = "granted"

        message = _translate(
            key,
            {
                "name": str(name or _MISSING),
                "method": str(method),
                "card": str(card or _MISSING),
                "door": str(door if door is not None else _MISSING),
            },
        )
        return {
            LOGBOOK_ENTRY_NAME: str(name or _MISSING),
            LOGBOOK_ENTRY_MESSAGE: message,
        }

    async_describe_event(DOMAIN, EVENT_TYPE_ACCESS, async_describe_access)
