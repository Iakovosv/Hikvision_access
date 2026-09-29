"""End to end tests: set up the integration and exercise entities and services."""

from __future__ import annotations

import httpx
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


async def _setup(hass: HomeAssistant, monkeypatch, events=None, **handler_kwargs):
    """Set up the integration against the fake terminal and return the entry."""

    captured: list[httpx.Request] = []
    session = httpx.AsyncClient(
        transport=httpx.MockTransport(make_handler(events or [], captured, **handler_kwargs))
    )

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


async def _setup_expecting_failure(hass: HomeAssistant, monkeypatch, **handler_kwargs):
    """Add an entry that is expected to fail setup, and return it."""

    captured: list[httpx.Request] = []
    session = httpx.AsyncClient(
        transport=httpx.MockTransport(make_handler([], captured, **handler_kwargs))
    )
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
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_exposes_one_door_when_the_device_is_silent(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A terminal that does not report a door count gets a single door button."""

    entry, _ = await _setup(hass, monkeypatch, [ACCESS_EVENT])
    await hass.async_block_till_done()

    door_buttons = [
        state for state in hass.states.async_all("button") if "open_door" in state.entity_id
    ]
    assert {state.entity_id for state in door_buttons} == {"button.front_door_open_door_1"}

    last_access = [
        state for state in hass.states.async_all("sensor") if "last_access" in state.entity_id
    ]
    assert len(last_access) == 1
    state = last_access[0]
    assert state.state == "2026-09-28T06:15:00+00:00"
    assert state.attributes["name"] == "Maria"
    assert state.attributes["employee_no"] == "900001"
    assert state.attributes["door_no"] == 1
    assert state.attributes["granted"] is True


async def test_setup_follows_the_door_count_of_the_device(
    hass: HomeAssistant, monkeypatch
) -> None:
    """The terminal reports how many doors it has, and one button is added per door."""

    entry, _ = await _setup(
        hass, monkeypatch, [ACCESS_EVENT], door_count=4, users=[{"employeeNo": "1001", "name": "Maria"}]
    )
    await hass.async_block_till_done()

    door_buttons = {
        state.entity_id
        for state in hass.states.async_all("button")
        if "open_door" in state.entity_id
    }
    assert door_buttons == {
        "button.front_door_open_door_1",
        "button.front_door_open_door_2",
        "button.front_door_open_door_3",
        "button.front_door_open_door_4",
    }

    refresh = [
        state for state in hass.states.async_all("button") if "refresh_people" in state.entity_id
    ]
    assert len(refresh) == 1

    enrolled = [
        state
        for state in hass.states.async_all("sensor")
        if "persons_enrolled" in state.entity_id
    ]
    assert len(enrolled) == 1
    assert enrolled[0].state == "1"


async def test_open_door_button_presses(hass: HomeAssistant, monkeypatch) -> None:
    """Pressing a door button sends the unlock command to the device."""

    entry, captured = await _setup(hass, monkeypatch, [ACCESS_EVENT])
    await hass.async_block_till_done()

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.front_door_open_door_1"},
        blocking=True,
    )

    door = [r for r in captured if "RemoteControl/door/1" in str(r.url)][-1]
    assert b"<cmd>open</cmd>" in door.content


async def test_last_access_sensor_is_unknown_before_any_event(
    hass: HomeAssistant, monkeypatch
) -> None:
    """With no event yet the timestamp sensor has no value instead of a fake one."""

    entry, _ = await _setup(hass, monkeypatch, [])
    await hass.async_block_till_done()

    state = hass.states.get("sensor.front_door_last_access_time")
    assert state is not None
    assert state.state == "unknown"


async def test_entities_survive_without_event_permission(hass: HomeAssistant, monkeypatch) -> None:
    """Denied events leave the door buttons usable and explain the sensor."""

    entry, _ = await _setup(
        hass,
        monkeypatch,
        denied_paths={"AccessControl/AcsEvent"},
        users=[{"employeeNo": "1001", "name": "Maria"}],
    )
    await hass.async_block_till_done()

    assert hass.states.get("button.front_door_open_door_1") is not None

    state = hass.states.get("sensor.front_door_last_access_time")
    assert state is not None
    assert "reason" in state.attributes

    # The person count does not depend on the event permission.
    enrolled = hass.states.get("sensor.front_door_persons_enrolled")
    assert enrolled is not None
    assert enrolled.state == "1"


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


async def test_setup_without_event_permission_stays_loaded(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A valid account missing event permission loads and keeps the other features.

    Failing setup here would hide person management, the services and the door control
    behind a permission that only the access event sensor needs.
    """

    entry, _ = await _setup(hass, monkeypatch, denied_paths={"AccessControl/AcsEvent"})

    from homeassistant.config_entries import ConfigEntryState

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.event_access_denied is True
    # Event polling slows down instead of hammering a device that will keep refusing.
    assert entry.runtime_data.update_interval.total_seconds() == 300
    # The features that do not need events are available.
    assert hass.services.has_service(DOMAIN, "open_door")


async def test_setup_recovers_when_permission_is_granted(
    hass: HomeAssistant, monkeypatch
) -> None:
    """The entry starts polling normally again once events are allowed."""

    entry, _ = await _setup(hass, monkeypatch, denied_paths={"AccessControl/AcsEvent"})
    coordinator = entry.runtime_data
    assert coordinator.event_access_denied

    # Grant the permission and poll once more, the way a later refresh would.
    client = coordinator.client
    original = client.get_all_access_events

    async def allowed(start, end):
        return [ACCESS_EVENT]

    monkeypatch.setattr(client, "get_all_access_events", allowed)
    await coordinator.async_refresh()

    assert coordinator.event_access_denied is False
    assert coordinator.update_interval.total_seconds() == 30
    assert coordinator.last_event is not None


async def test_setup_retries_on_transport_error(hass: HomeAssistant, monkeypatch) -> None:
    """A device that cannot be reached keeps retrying instead of loading."""

    entry = await _setup_expecting_failure(hass, monkeypatch, error_paths={"AccessControl/AcsEvent"})

    from homeassistant.config_entries import ConfigEntryState

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics_redact_credentials(hass: HomeAssistant, monkeypatch) -> None:
    """Diagnostics hide the host and credentials and report the probe result."""

    entry, _ = await _setup(hass, monkeypatch, [ACCESS_EVENT])

    from custom_components.hikvision_access.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["probe"]["access_events"] == "ok"
    assert diagnostics["probe"]["device_info"] == "ok"
    dumped = str(diagnostics["entry"])
    assert "secret" not in dumped
    assert "192.0.2.10" not in dumped


async def test_diagnostics_probe_when_setup_failed(hass: HomeAssistant, monkeypatch) -> None:
    """Diagnostics run the endpoint probes even when the entry did not load.

    Setup failure is the case where the probe matters most: it is the only way to tell a
    missing Log Search permission from a wrong password from the support report.
    """

    entry = await _setup_expecting_failure(
        hass, monkeypatch, error_paths={"AccessControl/AcsEvent"}
    )

    session = httpx.AsyncClient(
        transport=httpx.MockTransport(make_handler([], [], denied_paths={"AccessControl/AcsEvent"}))
    )
    monkeypatch.setattr(
        "custom_components.hikvision_access.diagnostics.get_async_client",
        lambda *a, **k: session,
    )

    from custom_components.hikvision_access.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["probe"]["device_info"] == "ok"
    assert "HikvisionAccessPermissionError" in diagnostics["probe"]["access_events"]
    dumped = str(diagnostics["entry"])
    assert "secret" not in dumped
    assert "192.0.2.10" not in dumped


async def test_diagnostics_report_denied_events_while_loaded(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A loaded entry with denied events reports the probe failure and the flag."""

    entry, _ = await _setup(hass, monkeypatch, denied_paths={"AccessControl/AcsEvent"})

    from custom_components.hikvision_access.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "HikvisionAccessPermissionError" in diagnostics["probe"]["access_events"]
    assert diagnostics["event_access_denied"] is True
