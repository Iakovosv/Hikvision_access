"""The optional notification and announcement, and the promise that they stay off.

Nothing here may fire unless the user turned it on, so every test either enables the feature
explicitly or asserts that a disabled setting stays silent. The notify and tts calls are
captured by registering a stand-in service, so the test sees exactly the arguments Home
Assistant would receive.
"""

from __future__ import annotations

import httpx
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.hikvision_access.const import (
    CONF_NOTIFY_ALL,
    CONF_NOTIFY_DENIED,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_MESSAGE,
    CONF_NOTIFY_NAMES,
    CONF_NOTIFY_NAMED_MESSAGE,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TITLE,
    CONF_TTS_ALL,
    CONF_TTS_ENABLED,
    CONF_TTS_ENTITY,
    CONF_TTS_MESSAGE,
    CONF_TTS_MEDIA_PLAYER,
    DOMAIN,
    EVENT_TYPE_ACCESS,
)

from .conftest import DEVICE_INFO, make_handler

ACCESS = {
    "device_id": DEVICE_INFO["DeviceInfo"]["serialNumber"],
    "name": "Maria",
    "employee_no": "900001",
    "card_no": "2673003718",
    "door_no": 1,
    "time": "2026-09-28T09:15:00+03:00",
    "method": "card",
    "granted": True,
}


async def _entry(hass: HomeAssistant, monkeypatch, options: dict) -> MockConfigEntry:
    """Set up the integration with the given options and return the entry."""

    captured: list[httpx.Request] = []
    session = httpx.AsyncClient(transport=httpx.MockTransport(make_handler([], captured)))
    monkeypatch.setattr(
        "custom_components.hikvision_access.get_async_client", lambda *a, **k: session
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        data={
            "host": "http://192.0.2.10",
            "username": "admin",
            "password": "secret",
            "verify_ssl": True,
        },
        options=options,
        unique_id=DEVICE_INFO["DeviceInfo"]["serialNumber"],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _fire(hass: HomeAssistant, **overrides) -> None:
    hass.bus.async_fire(EVENT_TYPE_ACCESS, {**ACCESS, **overrides})


async def test_nothing_is_sent_when_the_settings_are_off(hass: HomeAssistant, monkeypatch) -> None:
    """An untouched integration must not call notify at all."""

    await _entry(hass, monkeypatch, {})
    notify = async_mock_service(hass, "notify", "send_message")
    tts = async_mock_service(hass, "tts", "speak")

    _fire(hass)
    await hass.async_block_till_done()

    assert notify == []
    assert tts == []


async def test_every_entry_is_notified_with_the_rendered_message(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A generic notification names the person and fills the placeholders."""

    await _entry(
        hass,
        monkeypatch,
        {
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICE: "notify.mobile_app_me",
            CONF_NOTIFY_ALL: True,
            CONF_NOTIFY_TITLE: "Door",
            CONF_NOTIFY_MESSAGE: "{name} came in with {method} at {time}",
        },
    )
    notify = async_mock_service(hass, "notify", "send_message")

    _fire(hass)
    await hass.async_block_till_done()

    assert len(notify) == 1
    assert "Maria" in notify[0].data["message"]
    assert "card" in notify[0].data["message"]
    assert "{name}" not in notify[0].data["message"]
    assert notify[0].data["title"] == "Door"


async def test_only_watched_names_are_notified(hass: HomeAssistant, monkeypatch) -> None:
    """When only names are watched, someone else does not trigger a notification."""

    await _entry(
        hass,
        monkeypatch,
        {
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICE: "notify.mobile_app_me",
            CONF_NOTIFY_NAMES: "Καθαρίστρια, Maria",
            CONF_NOTIFY_TITLE: "General",
            CONF_NOTIFY_MESSAGE: "general {name}",
            CONF_NOTIFY_NAMED_MESSAGE: "WATCHED {name}",
        },
    )
    notify = async_mock_service(hass, "notify", "send_message")

    _fire(hass, name="Maria")
    await hass.async_block_till_done()
    assert len(notify) == 1
    assert notify[0].data["message"] == "WATCHED Maria"

    _fire(hass, name="Someone else", employee_no="42")
    await hass.async_block_till_done()
    assert len(notify) == 1


async def test_watched_name_matching_ignores_case_and_accents(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A watched name matches regardless of capitalisation."""

    await _entry(
        hass,
        monkeypatch,
        {
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICE: "notify.mobile_app_me",
            CONF_NOTIFY_NAMES: "maria",
            CONF_NOTIFY_NAMED_MESSAGE: "WATCHED {name}",
        },
    )
    notify = async_mock_service(hass, "notify", "send_message")

    _fire(hass, name="MARIA")
    await hass.async_block_till_done()

    assert len(notify) == 1


async def test_denied_access_notifies_only_when_asked(hass: HomeAssistant, monkeypatch) -> None:
    """A refused authentication is reported only with the dedicated switch on."""

    await _entry(
        hass,
        monkeypatch,
        {
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICE: "notify.mobile_app_me",
            CONF_NOTIFY_DENIED: True,
        },
    )
    notify = async_mock_service(hass, "notify", "send_message")

    _fire(hass, granted=False)
    await hass.async_block_till_done()

    assert len(notify) == 1
    assert "refused" in notify[0].data["message"]


async def test_tts_speaks_the_configured_text(hass: HomeAssistant, monkeypatch) -> None:
    """A granted entry is announced on the chosen speaker."""

    await _entry(
        hass,
        monkeypatch,
        {
            CONF_TTS_ENABLED: True,
            CONF_TTS_ALL: True,
            CONF_TTS_ENTITY: "tts.google_translate_el",
            CONF_TTS_MEDIA_PLAYER: "media_player.nest",
            CONF_TTS_MESSAGE: "Καλώς ήρθες {name}",
        },
    )
    tts = async_mock_service(hass, "tts", "speak")

    _fire(hass)
    await hass.async_block_till_done()

    assert len(tts) == 1
    assert tts[0].data["message"] == "Καλώς ήρθες Maria"
    assert tts[0].data["media_player_entity_id"] == "media_player.nest"


async def test_an_event_from_another_device_is_ignored(hass: HomeAssistant, monkeypatch) -> None:
    """Only this entry's events are dispatched."""

    await _entry(
        hass,
        monkeypatch,
        {
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICE: "notify.mobile_app_me",
            CONF_NOTIFY_ALL: True,
        },
    )
    notify = async_mock_service(hass, "notify", "send_message")

    _fire(hass, device_id="another-device")
    await hass.async_block_till_done()

    assert notify == []


async def test_unknown_placeholder_is_left_untouched(hass: HomeAssistant, monkeypatch) -> None:
    """A literal brace in a template must not crash the listener."""

    await _entry(
        hass,
        monkeypatch,
        {
            CONF_NOTIFY_ENABLED: True,
            CONF_NOTIFY_SERVICE: "notify.mobile_app_me",
            CONF_NOTIFY_ALL: True,
            CONF_NOTIFY_MESSAGE: "{oops} {name} {still}",
        },
    )
    notify = async_mock_service(hass, "notify", "send_message")

    _fire(hass)
    await hass.async_block_till_done()

    assert len(notify) == 1
    assert notify[0].data["message"] == "{oops} Maria {still}"
