"""The logbook line for an access event names the person and how they opened the door."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.hikvision_access import logbook
from custom_components.hikvision_access.const import DOMAIN, EVENT_TYPE_ACCESS

from tests.test_integration import _setup


class _Event:
    """Stand-in for the logbook's lazy event, which only exposes `.data`."""

    def __init__(self, data: dict) -> None:
        self.data = data


async def _describe(hass: HomeAssistant, monkeypatch):
    """Set the integration up and return the callback the logbook would call."""

    await _setup(hass, monkeypatch)
    captured: dict = {}
    logbook.async_describe_events(hass, lambda domain, event, cb: captured.update(cb=cb))
    return captured["cb"]


async def test_granted_event_shows_the_person_the_card_and_the_door(hass, monkeypatch) -> None:
    """A card read names the person, the card and the door."""

    describe = await _describe(hass, monkeypatch)
    result = describe(
        _Event(
            {
                "name": "House cleaner",
                "employee_no": "Housecleaner",
                "card_no": "2673003718",
                "door_no": 1,
                "method": "cardOrFpOrPw",
                "granted": True,
            }
        )
    )

    assert result["name"] == "House cleaner"
    assert "House cleaner" in result["message"]
    assert "2673003718" in result["message"]


async def test_granted_event_without_a_card_has_no_card_in_the_line(hass, monkeypatch) -> None:
    """A fingerprint or face read has no card number to show."""

    describe = await _describe(hass, monkeypatch)
    result = describe(
        _Event({"name": "Maria", "card_no": None, "door_no": 1, "method": "fp", "granted": True})
    )

    assert result["name"] == "Maria"
    assert "Maria" in result["message"]


async def test_denied_event_is_reported_as_denied(hass, monkeypatch) -> None:
    """A refused authentication must not read as an opening."""

    describe = await _describe(hass, monkeypatch)
    result = describe(
        _Event({"name": "Maria", "card_no": None, "door_no": 1, "method": "fp", "granted": False})
    )

    assert result["name"] == "Maria"
    assert result["message"] != ""


async def test_name_falls_back_to_the_employee_number(hass, monkeypatch) -> None:
    """A person the device knows only by number still gets a readable line."""

    describe = await _describe(hass, monkeypatch)
    result = describe(
        _Event({"name": None, "employee_no": "900001", "card_no": "5", "door_no": 1, "granted": True})
    )

    assert result["name"] == "900001"


async def test_greek_line_is_translated(hass, monkeypatch) -> None:
    """The line follows the Home Assistant language, here Greek."""

    hass.config.language = "el"
    describe = await _describe(hass, monkeypatch)
    result = describe(
        _Event(
            {
                "name": "Καθαρίστρια",
                "card_no": "2673003718",
                "door_no": 1,
                "method": "card",
                "granted": True,
            }
        )
    )

    assert result["message"] != "granted_with_card"
    assert "Καθαρίστρια" in result["message"]


async def test_event_type_is_the_one_the_coordinator_fires(hass, monkeypatch) -> None:
    """The logbook listens on the same event the coordinator publishes."""

    await _setup(hass, monkeypatch)
    registered: dict = {}
    logbook.async_describe_events(hass, lambda domain, event, cb: registered.update({domain: event}))
    assert registered[DOMAIN] == EVENT_TYPE_ACCESS
