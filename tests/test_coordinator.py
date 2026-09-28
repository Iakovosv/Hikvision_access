"""Tests for the access event coordinator."""

from __future__ import annotations

import httpx
import pytest

from custom_components.hikvision_access.const import EVENT_TYPE_ACCESS
from custom_components.hikvision_access.coordinator import HikvisionAccessCoordinator
from custom_components.hikvision_access.isapi import HikvisionAccessClient

from .conftest import DEVICE_INFO, make_handler

HOST = "http://192.0.2.10"

ACCESS_EVENT = {
    "major": 5,
    "minor": 75,
    "time": "2026-09-28T09:15:00+03:00",
    "name": "Maria",
    "employeeNoString": "900001",
    "cardNo": "",
    "doorNo": 1,
    "eventId": "evt-1",
}


def _coordinator(hass, events: list[dict]) -> HikvisionAccessCoordinator:
    session = httpx.AsyncClient(transport=httpx.MockTransport(make_handler(events=events)))
    client = HikvisionAccessClient(HOST, "admin", "secret", session=session)
    return HikvisionAccessCoordinator(hass, None, client, DEVICE_INFO["DeviceInfo"])


async def test_access_event_is_parsed_and_fired(hass) -> None:
    """A successful access event updates the state and fires a bus event."""

    coordinator = _coordinator(hass, [ACCESS_EVENT])
    received = []
    hass.bus.async_listen(EVENT_TYPE_ACCESS, lambda event: received.append(event))

    await coordinator.async_refresh()

    assert coordinator.last_event is not None
    assert coordinator.last_event.name == "Maria"
    assert coordinator.last_event.employee_no == "900001"
    assert coordinator.last_event.door_no == 1
    assert coordinator.is_entry_granted is True
    assert len(received) == 1
    assert received[0].data["employee_no"] == "900001"
    assert received[0].data["device_id"] == "DSK1T805TEST0001"


async def test_duplicate_events_fire_once(hass) -> None:
    """Polling the same window twice does not repeat the same event."""

    coordinator = _coordinator(hass, [ACCESS_EVENT])
    received = []
    hass.bus.async_listen(EVENT_TYPE_ACCESS, lambda event: received.append(event))

    await coordinator.async_refresh()
    await coordinator.async_refresh()

    assert len(received) == 1


async def test_non_access_events_are_ignored(hass) -> None:
    """Alarm events on the same endpoint are ignored."""

    other = {**ACCESS_EVENT, "major": 3, "minor": 1}
    coordinator = _coordinator(hass, [other])
    received = []
    hass.bus.async_listen(EVENT_TYPE_ACCESS, lambda event: received.append(event))

    await coordinator.async_refresh()

    assert coordinator.last_event is None
    assert received == []


def _coordinator_with(hass, **kwargs) -> HikvisionAccessCoordinator:
    """Coordinator wired to a terminal with the given behaviour."""

    session = httpx.AsyncClient(transport=httpx.MockTransport(make_handler(**kwargs)))
    client = HikvisionAccessClient(HOST, "admin", "secret", session=session)
    return HikvisionAccessCoordinator(hass, None, client, DEVICE_INFO["DeviceInfo"])


async def test_permission_error_is_not_a_reauth(hass) -> None:
    """A 401 from an authenticated account keeps the entry loaded.

    Asking for a new password would loop forever with the correct one, so a missing
    permission becomes an update failure instead of an authentication failure.
    """

    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = _coordinator_with(hass, denied_paths={"AccessControl/AcsEvent"})
    await coordinator.client.get_device_info()

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_lockout_is_an_update_failure(hass) -> None:
    """A locked account is retried later, it does not trigger reauthentication."""

    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = _coordinator_with(hass, lockout_paths={"AccessControl/AcsEvent"})

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
