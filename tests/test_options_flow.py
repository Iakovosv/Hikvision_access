"""Tests for the person management options flow."""

from __future__ import annotations

import json

import httpx
import pytest
from homeassistant.core import HomeAssistant

from custom_components.hikvision_access.const import DOMAIN

from .test_integration import _setup


PERSON = {
    "employeeNo": "1001",
    "name": "Maria",
    "userType": "normal",
    "gender": "female",
    "numOfCard": 1,
    "numOfFP": 0,
    "Valid": {"enable": True, "beginTime": "2026-01-01T00:00:00", "endTime": "2030-01-01T00:00:00"},
    "CardInfo": [{"cardNo": "55512345"}],
}


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


async def _flow(hass: HomeAssistant, entry) -> "object":
    from custom_components.hikvision_access.options_flow import HikvisionAccessOptionsFlow

    return HikvisionAccessOptionsFlow(entry)


async def test_menu_is_shown(hass: HomeAssistant, monkeypatch) -> None:
    """The configure button offers the person management menu."""

    entry, _ = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    result = await flow.async_step_init()
    assert result["type"] == "menu"
    assert set(result["menu_options"]) == {"add", "edit", "delete", "cards", "open_door"}


async def test_add_person_sends_all_fields(hass: HomeAssistant, monkeypatch) -> None:
    """Adding a person sends the name, PIN, gender, type, validity and card."""

    entry, captured = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    result = await flow.async_step_add(
        {
            "employee_no": "2002",
            "name": "Nikos",
            "gender": "male",
            "user_type": "normal",
            "pin": "4321",
            "validity_enabled": True,
            "begin_time": "2026-09-01T00:00:00+00:00",
            "end_time": "2026-12-01T00:00:00+00:00",
            "card_no": "99887766",
        }
    )
    assert result["type"] == "create_entry"

    record = [r for r in captured if r.url.path.endswith("UserInfo/Record")][-1]
    user = _body(record)["UserInfo"]
    assert user["employeeNo"] == "2002"
    assert user["name"] == "Nikos"
    assert user["gender"] == "male"
    assert user["userType"] == "normal"
    assert user["password"] == "4321"
    assert user["Valid"]["enable"] is True
    assert user["Valid"]["timeType"] == "local"

    card = [r for r in captured if r.url.path.endswith("CardInfo/Record")][-1]
    assert _body(card)["CardInfo"]["cardNo"] == "99887766"
    assert _body(card)["CardInfo"]["employeeNo"] == "2002"


async def test_add_person_auto_allocates_number_and_pin(hass: HomeAssistant, monkeypatch) -> None:
    """An empty employee number and PIN are generated."""

    entry, captured = await _setup(hass, monkeypatch, users=[{"employeeNo": "900001"}])
    flow = await _flow(hass, entry)

    result = await flow.async_step_add({"name": "Visitor", "user_type": "visitor"})
    assert result["type"] == "create_entry"

    record = [r for r in captured if r.url.path.endswith("UserInfo/Record")][-1]
    user = _body(record)["UserInfo"]
    assert user["employeeNo"] == "900002"
    assert len(user["password"]) == 6
    assert user["password"].isdigit()


async def test_add_person_rejects_bad_validity(hass: HomeAssistant, monkeypatch) -> None:
    """A validity window that ends before it begins is refused with a form error."""

    entry, _ = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    result = await flow.async_step_add(
        {
            "name": "Nikos",
            "validity_enabled": True,
            "begin_time": "2026-12-01T00:00:00+00:00",
            "end_time": "2026-09-01T00:00:00+00:00",
        }
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_validity"


async def test_edit_flow_prefills_and_modifies(hass: HomeAssistant, monkeypatch) -> None:
    """Editing shows the person and sends a Modify request."""

    entry, captured = await _setup(hass, monkeypatch, users=[PERSON])
    flow = await _flow(hass, entry)

    chosen = await flow.async_step_edit({"employee_no": "1001"})
    assert chosen["type"] == "form"

    result = await flow.async_step_edit_form({"name": "Maria P.", "gender": "female"})
    assert result["type"] == "create_entry"

    modify = [r for r in captured if r.url.path.endswith("UserInfo/Modify")][-1]
    user = _body(modify)["UserInfo"]
    assert user["employeeNo"] == "1001"
    assert user["name"] == "Maria P."
    assert "password" not in user


async def test_delete_requires_confirmation(hass: HomeAssistant, monkeypatch) -> None:
    """Deleting a person only happens after the confirmation box is ticked."""

    entry, captured = await _setup(hass, monkeypatch, users=[PERSON])
    flow = await _flow(hass, entry)

    await flow.async_step_delete({"employee_no": "1001"})
    cancel = await flow.async_step_delete_confirm({"confirm": False})
    assert cancel["type"] == "abort"
    assert not [r for r in captured if r.url.path.endswith("UserInfo/Delete")]

    result = await flow.async_step_delete_confirm({"confirm": True})
    assert result["type"] == "create_entry"
    delete = [r for r in captured if r.url.path.endswith("UserInfo/Delete")][-1]
    assert _body(delete)["UserInfoDelCond"]["EmployeeNoList"] == [{"employeeNo": "1001"}]


async def test_card_form_adds_and_clears(hass: HomeAssistant, monkeypatch) -> None:
    """A card number is added, and an empty field removes the existing card."""

    entry, captured = await _setup(hass, monkeypatch, users=[PERSON])
    flow = await _flow(hass, entry)

    await flow.async_step_cards({"employee_no": "1001"})
    await flow.async_step_card_form({"card_no": "12345678"})
    record = [r for r in captured if r.url.path.endswith("CardInfo/Record")][-1]
    assert _body(record)["CardInfo"]["cardNo"] == "12345678"

    flow2 = await _flow(hass, entry)
    await flow2.async_step_cards({"employee_no": "1001"})
    await flow2.async_step_card_form({"card_no": ""})
    delete = [r for r in captured if r.url.path.endswith("CardInfo/Delete")][-1]
    assert _body(delete)["CardInfoDelCond"]["CardNoList"] == [{"cardNo": "55512345"}]


async def test_edit_with_no_persons_aborts(hass: HomeAssistant, monkeypatch) -> None:
    """With an empty device the edit flow aborts cleanly."""

    entry, _ = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    result = await flow.async_step_edit()
    assert result["type"] == "abort"
    assert result["reason"] == "no_persons"


async def test_methods_on_isapi_client(hass: HomeAssistant, monkeypatch) -> None:
    """The client exposes person lookup, count and card removal."""

    entry, captured = await _setup(hass, monkeypatch, users=[PERSON])
    client = entry.runtime_data.client

    person = await client.get_person("1001")
    assert person["name"] == "Maria"

    count = await client.get_person_count()
    assert count == 1

    await client.delete_card("55512345")
    delete = [r for r in captured if r.url.path.endswith("CardInfo/Delete")][-1]
    assert _body(delete)["CardInfoDelCond"]["CardNoList"] == [{"cardNo": "55512345"}]
