"""Shared fixtures for the hikvision_access tests."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hikvision_access.const import DOMAIN

DEVICE_INFO = {
    "DeviceInfo": {
        "deviceName": "Front Door",
        "manufacturer": "Hikvision",
        "model": "DS-K1T805MBFWX",
        "serialNumber": "DSK1T805TEST0001",
        "firmwareVersion": "V1.9.1 build 240909",
        "macAddress": "aa:bb:cc:dd:ee:ff",
    }
}


def make_handler(
    events: list[dict[str, Any]] | None = None,
    captured: list[httpx.Request] | None = None,
    users: list[dict[str, Any]] | None = None,
    page_size: int | None = None,
    device_time: str | None = None,
    denied_paths: set[str] | None = None,
    lockout_paths: set[str] | None = None,
    error_paths: set[str] | None = None,
):
    """Build a transport handler that mimics an access control terminal.

    `page_size` makes the event endpoint paginate like the real device does, and
    `users` answers the enrollment search used to pick a free employee number.
    `denied_paths` answers 401 even after a valid login, the way ISAPI reports a
    missing permission, and `lockout_paths` answers the 401 lockout body.
    `error_paths` answers 500, which makes setup fail as a transport error.
    """

    events = events if events is not None else []
    users = users if users is not None else []
    denied_paths = denied_paths or set()
    lockout_paths = lockout_paths or set()
    error_paths = error_paths or set()

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)

        path = request.url.path
        suffix = path.rsplit("/ISAPI/", 1)[-1]

        if "Authorization" not in request.headers:
            return httpx.Response(
                401,
                headers={"WWW-Authenticate": 'Digest realm="DS-1", qop="auth", nonce="abc", opaque="xyz"'},
            )

        # A lockout is answered before the permission check: the device refuses every
        # request, including the ones that used to work.
        if any(suffix.endswith(p) for p in lockout_paths):
            return httpx.Response(
                401,
                text=(
                    "<?xml version=\"1.0\"?><ResponseStatus><statusCode>4</statusCode>"
                    "<statusString>Invalid Operation</statusString><lockStatus>locked</lockStatus>"
                    "<unlockTime>1800</unlockTime></ResponseStatus>"
                ),
            )

        # A missing permission is a 401 as well, with a normal digest challenge.
        if any(suffix.endswith(p) for p in denied_paths):
            return httpx.Response(
                401,
                headers={"WWW-Authenticate": 'Digest realm="DS-1", qop="auth", nonce="abc", opaque="xyz"'},
            )

        # A transport failure, used to check that setup retries instead of loading.
        if any(suffix.endswith(p) for p in error_paths):
            return httpx.Response(500, text="internal error")

        if suffix.endswith("System/deviceInfo"):
            return httpx.Response(200, json=DEVICE_INFO)
        if suffix.endswith("System/capabilities"):
            return httpx.Response(200, json={"DeviceCap": {}})
        if suffix.endswith("System/time"):
            if device_time is None:
                return httpx.Response(404, json={"statusCode": 4, "statusString": "Invalid Operation"})
            return httpx.Response(200, json={"Time": {"localTime": device_time, "timeZone": "CST-2:00:00"}})
        if suffix.endswith("AccessControl/AcsEvent"):
            return httpx.Response(200, json={"AcsEvent": _event_page(request, events, page_size)})
        if suffix.endswith("AccessControl/UserInfo/Search"):
            return httpx.Response(200, json={"UserInfoSearch": _user_page(request, users, page_size)})
        if suffix.endswith("AccessControl/UserInfo/Count"):
            return httpx.Response(200, json={"UserInfoCount": {"userNumber": len(users)}})
        if suffix.endswith("AccessControl/UserInfo/Record"):
            return httpx.Response(200, json={"statusCode": 1, "statusString": "OK"})
        if suffix.endswith("AccessControl/UserInfo/Modify"):
            return httpx.Response(200, json={"statusCode": 1, "statusString": "OK"})
        if suffix.endswith("AccessControl/UserInfo/Delete"):
            return httpx.Response(200, json={"statusCode": 1, "statusString": "OK"})
        if suffix.endswith("AccessControl/CardInfo/Record"):
            return httpx.Response(200, json={"statusCode": 1, "statusString": "OK"})
        if suffix.endswith("AccessControl/CardInfo/Delete"):
            return httpx.Response(200, json={"statusCode": 1, "statusString": "OK"})
        if suffix.endswith("RemoteControl/door/1"):
            return httpx.Response(200, text="<ResponseStatus><statusCode>1</statusCode></ResponseStatus>")
        return httpx.Response(404, json={"statusCode": 4, "statusString": "Invalid Operation"})

    return handler


def _requested_position(request: httpx.Request) -> int:
    try:
        body = json.loads(request.content)
    except (ValueError, AttributeError):
        return 0
    for key in ("AcsEventCond", "UserInfoSearchCond"):
        if key in body and "searchResultPosition" in body[key]:
            return int(body[key]["searchResultPosition"])
    return 0


def _page(items: list[dict[str, Any]], position: int, page_size: int | None) -> tuple[list[dict[str, Any]], str]:
    if page_size is None:
        return items, "OK"
    chunk = items[position : position + page_size]
    more = position + page_size < len(items)
    return chunk, "MORE" if more else "OK"


def _event_page(request: httpx.Request, events: list[dict[str, Any]], page_size: int | None) -> dict[str, Any]:
    page, status = _page(events, _requested_position(request), page_size)
    return {
        "searchID": "hikvision-access",
        "numOfMatches": len(page),
        "responseStatusStrg": status,
        "InfoList": page,
    }


def _user_page(request: httpx.Request, users: list[dict[str, Any]], page_size: int | None) -> dict[str, Any]:
    page, status = _page(users, _requested_position(request), page_size)
    return {
        "searchID": "hikvision-access",
        "numOfMatches": len(page),
        "responseStatusStrg": status,
        "UserInfo": page,
    }


@pytest.fixture
def captured_requests() -> list[httpx.Request]:
    """Collect requests sent by the client."""

    return []


@pytest.fixture
def session(captured_requests: list[httpx.Request]) -> httpx.AsyncClient:
    """An httpx session backed by the fake terminal."""

    return httpx.AsyncClient(transport=httpx.MockTransport(make_handler(captured=captured_requests)))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in tests."""

    yield


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """A config entry pointing at the fake terminal."""

    return MockConfigEntry(
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


def decoder(request: httpx.Request) -> dict[str, Any]:
    """Return the JSON body of a request, for assertions in tests."""

    return json.loads(request.content)
