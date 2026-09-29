"""Describe an access in the Home Assistant Activity log.

`hassfest` rejects a `logbook` translation category, and no core integration ships one, so the
strings live here. They are keyed by language to match how the rest of the integration reads
its translations, and every other language falls back to English.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
    LazyEventPartialState,
)
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, EVENT_TYPE_ACCESS

_MISSING = "?"

_LINES: dict[str, dict[str, str]] = {
    "en": {
        "granted": "{name} opened the door ({method}, door {door})",
        "granted_with_card": "{name} opened the door with card {card} (door {door})",
        "denied": "Access refused for {name} (door {door})",
    },
    "el": {
        "granted": "Ο/Η {name} άνοιξε την πόρτα ({method}, πόρτα {door})",
        "granted_with_card": "Ο/Η {name} άνοιξε την πόρτα με κάρτα {card} (πόρτα {door})",
        "denied": "Απορρίφθηκε η πρόσβαση για {name} (πόρτα {door})",
    },
}

_METHODS: dict[str, dict[str, str]] = {
    "en": {
        "access": "access",
        "card": "card",
        "fp": "fingerprint",
        "cardAndPw": "card + PIN",
        "fpAndPw": "fingerprint + PIN",
        "fpOrCard": "fingerprint or card",
        "fpAndCard": "fingerprint + card",
        "fpAndCardAndPw": "fingerprint + card + PIN",
        "fpOrPw": "fingerprint or PIN",
        "cardOrPw": "card or PIN",
        "cardOrFpOrPw": "card, fingerprint or PIN",
    },
    "el": {
        "access": "πρόσβαση",
        "card": "κάρτα",
        "fp": "δακτυλικό αποτύπωμα",
        "cardAndPw": "κάρτα + PIN",
        "fpAndPw": "δακτυλικό + PIN",
        "fpOrCard": "δακτυλικό ή κάρτα",
        "fpAndCard": "δακτυλικό + κάρτα",
        "fpAndCardAndPw": "δακτυλικό + κάρτα + PIN",
        "fpOrPw": "δακτυλικό ή PIN",
        "cardOrPw": "κάρτα ή PIN",
        "cardOrFpOrPw": "κάρτα, δακτυλικό ή PIN",
    },
}


def _fill(template: str, values: dict[str, str]) -> str:
    """Substitute the placeholders by hand; these strings are not entity names."""

    for name, value in values.items():
        template = template.replace(f"{{{name}}}", value)
    return template


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[
        [str, str, Callable[[LazyEventPartialState], dict[str, str]]], None
    ],
) -> None:
    """Teach the logbook how to render an access event."""

    language = hass.config.language if hass.config.language in _LINES else "en"
    lines = _LINES[language]
    methods = _METHODS[language]

    @callback
    def async_describe_access(event: LazyEventPartialState) -> dict[str, str]:
        """Describe one access event for the logbook."""

        data = event.data
        name = data.get("name") or data.get("employee_no") or _MISSING
        method = methods.get(data.get("method") or "access", data.get("method") or "access")
        card = data.get("card_no")
        door = data.get("door_no")

        if not data.get("granted", True):
            key = "denied"
        elif card:
            key = "granted_with_card"
        else:
            key = "granted"

        message = _fill(
            lines[key],
            {
                "name": str(name),
                "method": method,
                "card": str(card or _MISSING),
                "door": str(door if door is not None else _MISSING),
            },
        )
        return {
            LOGBOOK_ENTRY_NAME: str(name),
            LOGBOOK_ENTRY_MESSAGE: message,
        }

    async_describe_event(DOMAIN, EVENT_TYPE_ACCESS, async_describe_access)
