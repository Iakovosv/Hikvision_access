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


def make_handler(events: list[dict[str, Any]] | None = None, captured: list[httpx.Request] | None = None):
    """Build a transport handler that mimics an access control terminal."""

    events = events if events is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)

        if "Authorization" not in request.headers:
            return httpx.Response(
                401,
                headers={"WWW-Authenticate": 'Digest realm="DS-1", qop="auth", nonce="abc", opaque="xyz"'},
            )

        path = request.url.path
        if path.endswith("System/deviceInfo"):
            return httpx.Response(200, json=DEVICE_INFO)
        if path.endswith("System/capabilities"):
            return httpx.Response(200, json={"DeviceCap": {}})
        if path.endswith("AccessControl/AcsEvent"):
            return httpx.Response(
                200,
                json={"AcsEvent": {"searchID": "hikvision-access", "numOfMatches": len(events), "InfoList": events}},
            )
        if path.endswith("AccessControl/UserInfo/Record"):
            return httpx.Response(200, json={"statusCode": 1, "statusString": "OK"})
        if path.endswith("AccessControl/UserInfo/Delete"):
            return httpx.Response(200, json={"statusCode": 1, "statusString": "OK"})
        if path.endswith("RemoteControl/door/1"):
            return httpx.Response(200, text="<ResponseStatus><statusCode>1</statusCode></ResponseStatus>")
        return httpx.Response(404, json={"statusCode": 4, "statusString": "Invalid Operation"})

    return handler


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
