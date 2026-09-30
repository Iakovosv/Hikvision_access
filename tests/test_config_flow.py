# Copyright (c) 2026 Iakovosv. All rights reserved.
# Personal use only. Commercial use requires written permission.
# See LICENSE and COMMERCIAL.md. Redistribution prohibited.

"""Tests for the config flow."""

from __future__ import annotations

import httpx
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant

from custom_components.hikvision_access.const import DOMAIN

from .conftest import make_handler


async def test_user_flow_creates_entry(hass: HomeAssistant, monkeypatch) -> None:
    """A valid device creates a config entry keyed by serial number."""

    session = httpx.AsyncClient(transport=httpx.MockTransport(make_handler()))

    def fake_get_async_client(*args, **kwargs):
        return session

    monkeypatch.setattr("custom_components.hikvision_access.config_flow.get_async_client", fake_get_async_client)
    monkeypatch.setattr("custom_components.hikvision_access.get_async_client", fake_get_async_client)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is data_entry_flow.FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "http://192.0.2.10",
            "username": "admin",
            "password": "secret",
            "verify_ssl": True,
        },
    )
    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Front Door"
    assert result["result"].unique_id == "DSK1T805TEST0001"


async def test_user_flow_invalid_auth(hass: HomeAssistant, monkeypatch) -> None:
    """A device rejecting the credentials reports invalid_auth."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"WWW-Authenticate": 'Digest realm="DS-1", nonce="abc"'})

    session = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "custom_components.hikvision_access.config_flow.get_async_client", lambda *a, **k: session
    )

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "http://192.0.2.10",
            "username": "admin",
            "password": "wrong",
            "verify_ssl": True,
        },
    )
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"
