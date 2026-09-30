# Copyright (c) 2026 Iakovosv. All rights reserved.
# Personal use only. Commercial use requires written permission.
# See LICENSE and COMMERCIAL.md. Redistribution prohibited.

"""Tests for event pagination and safe visitor number allocation."""

from __future__ import annotations

import datetime as dt

import httpx
from homeassistant.core import HomeAssistant

from custom_components.hikvision_access.const import DOMAIN, SERVICE_CREATE_VISITOR
from custom_components.hikvision_access.isapi import HikvisionAccessClient

from .conftest import decoder, make_handler

HOST = "http://192.0.2.10"


def _event(index: int) -> dict:
    return {
        "major": 5,
        "minor": 75,
        "time": f"2026-09-28T09:00:{index:02d}+03:00",
        "name": f"Person {index}",
        "employeeNoString": str(900000 + index),
        "doorNo": 1,
        "eventId": f"evt-{index}",
    }


async def test_access_events_are_paginated() -> None:
    """Every page of a paginated response is collected, not just the first."""

    events = [_event(i) for i in range(7)]
    session = httpx.AsyncClient(transport=httpx.MockTransport(make_handler(events=events, page_size=3)))
    client = HikvisionAccessClient(host=HOST, username="admin", password="secret", session=session)

    collected = await client.get_all_access_events(
        dt.datetime(2026, 9, 28, 0, 0, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 9, 29, 0, 0, tzinfo=dt.timezone.utc),
    )

    assert len(collected) == 7
    assert [e["eventId"] for e in collected] == [f"evt-{i}" for i in range(7)]


async def test_pagination_stops_on_the_last_page() -> None:
    """The loop ends as soon as the device no longer reports MORE."""

    captured: list[httpx.Request] = []
    events = [_event(i) for i in range(4)]
    session = httpx.AsyncClient(
        transport=httpx.MockTransport(make_handler(events=events, captured=captured, page_size=3))
    )
    client = HikvisionAccessClient(host=HOST, username="admin", password="secret", session=session)

    collected = await client.get_all_access_events(
        dt.datetime(2026, 9, 28, 0, 0, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 9, 29, 0, 0, tzinfo=dt.timezone.utc),
    )

    assert len(collected) == 4
    positions = []
    for request in captured:
        if "AccessControl/AcsEvent" not in request.url.path or "Authorization" not in request.headers:
            continue
        body = decoder(request)
        positions.append(body["AcsEventCond"]["searchResultPosition"])
    # Two pages: position 0 then position 3. The loop must not ask for position 6.
    assert sorted(set(positions)) == [0, 3]


async def _setup_with_users(hass: HomeAssistant, monkeypatch, users, events=None):
    """Set up the integration against a terminal that already has users."""

    captured: list[httpx.Request] = []
    session = httpx.AsyncClient(
        transport=httpx.MockTransport(make_handler(events=events or [], users=users, captured=captured))
    )
    monkeypatch.setattr("custom_components.hikvision_access.get_async_client", lambda *a, **k: session)

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from .conftest import DEVICE_INFO

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        data={"host": HOST, "username": "admin", "password": "secret", "verify_ssl": True},
        unique_id=DEVICE_INFO["DeviceInfo"]["serialNumber"],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, captured


async def test_visitor_number_skips_existing_people(hass: HomeAssistant, monkeypatch) -> None:
    """A visitor never overwrites an existing enrolled person."""

    users = [{"employeeNo": "900001", "name": "Existing visitor"}, {"employeeNo": "900002", "name": "Another"}]
    entry, captured = await _setup_with_users(hass, monkeypatch, users)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CREATE_VISITOR,
        {
            "name": "New Visitor",
            "begin_time": "2026-10-01 09:00:00",
            "end_time": "2026-10-01 21:00:00",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    record = [r for r in captured if r.url.path.endswith("UserInfo/Record")][-1]
    assert decoder(record)["UserInfo"]["employeeNo"] == "900003"


async def test_visitor_number_ignored_when_list_unavailable(hass: HomeAssistant, monkeypatch) -> None:
    """If the device refuses the user list, a visitor number is still produced.

    The service must not fail just because the enrollment search is unavailable.
    """

    entry, captured = await _setup_with_users(hass, monkeypatch, [], events=[])

    # The default handler has no UserInfo/Search route, so the search returns 404.
    await hass.services.async_call(
        DOMAIN,
        SERVICE_CREATE_VISITOR,
        {
            "name": "Fallback Visitor",
            "begin_time": "2026-10-01 09:00:00",
            "end_time": "2026-10-01 21:00:00",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    record = [r for r in captured if r.url.path.endswith("UserInfo/Record")][-1]
    assert decoder(record)["UserInfo"]["employeeNo"] == "900001"
