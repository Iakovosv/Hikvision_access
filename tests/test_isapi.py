"""Tests for the ISAPI client."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from custom_components.hikvision_access.isapi import (
    HikvisionAccessClient,
    _isapi_time,
)

from .conftest import decoder, make_handler

HOST = "http://192.0.2.10"


@pytest.fixture
def client(session: httpx.AsyncClient) -> HikvisionAccessClient:
    """Client wired to the fake terminal."""

    return HikvisionAccessClient(HOST, "admin", "secret", session=session)


async def test_detects_digest_auth(client: HikvisionAccessClient) -> None:
    """The client negotiates digest authentication from the challenge."""

    await client.get_device_info()
    assert isinstance(client._auth, httpx.DigestAuth)


async def test_get_access_events_payload(session: httpx.AsyncClient) -> None:
    """Access events are requested with the access major type."""

    captured: list[httpx.Request] = []
    session = httpx.AsyncClient(transport=httpx.MockTransport(make_handler(captured=captured)))
    client = HikvisionAccessClient(HOST, "admin", "secret", session=session)

    start = dt.datetime(2026, 1, 1, 10, 0, 0)
    end = dt.datetime(2026, 1, 1, 10, 5, 0)
    await client.get_access_events(start, end)

    request = captured[-1]
    body = decoder(request)["AcsEventCond"]
    assert body["major"] == 5
    assert body["minor"] == 75
    assert body["startTime"] == "2026-01-01T10:00:00"
    assert body["endTime"] == "2026-01-01T10:05:00"
    assert request.headers["Content-Type"] == "application/json"


async def test_create_person_payload(session: httpx.AsyncClient) -> None:
    """A person is created with a PIN and a validity window."""

    captured: list[httpx.Request] = []
    session = httpx.AsyncClient(transport=httpx.MockTransport(make_handler(captured=captured)))
    client = HikvisionAccessClient(HOST, "admin", "secret", session=session)

    await client.create_person(
        employee_no="900001",
        name="Maria",
        begin_time=dt.datetime(2026, 3, 1, 8, 0, 0),
        end_time=dt.datetime(2026, 3, 1, 20, 0, 0),
        pin="123456",
    )

    request = captured[-1]
    assert request.method == "PUT"
    assert request.url.path.endswith("AccessControl/UserInfo/Record")
    user = decoder(request)["UserInfo"]
    assert user["employeeNo"] == "900001"
    assert user["name"] == "Maria"
    assert user["password"] == "123456"
    assert user["Valid"]["enable"] is True
    assert user["Valid"]["beginTime"] == "2026-03-01T08:00:00"
    assert user["Valid"]["endTime"] == "2026-03-01T20:00:00"


async def test_forbidden_raises(session: httpx.AsyncClient) -> None:
    """A 403 is surfaced as a permission error, not a generic transport error."""

    from custom_components.hikvision_access.isapi import HikvisionAccessForbiddenError

    def handler(request: httpx.Request) -> httpx.Response:
        if "Authorization" not in request.headers:
            return httpx.Response(401, headers={"WWW-Authenticate": 'Digest realm="DS-1", nonce="abc"'})
        return httpx.Response(403, json={"statusCode": 4, "statusString": "Invalid Operation"})

    session = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = HikvisionAccessClient(HOST, "admin", "secret", session=session)

    with pytest.raises(HikvisionAccessForbiddenError):
        await client.get_users()


def test_isapi_time_format() -> None:
    """Timestamps are formatted without an offset, as the device expects."""

    assert _isapi_time(dt.datetime(2026, 5, 5, 23, 59, 59, tzinfo=dt.timezone.utc)) == "2026-05-05T23:59:59"
