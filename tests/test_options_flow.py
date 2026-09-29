"""Tests for the person management options flow."""

from __future__ import annotations

import json

import httpx
import pytest
import voluptuous as vol
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
    assert set(result["menu_options"]) == {"add", "edit", "delete", "open_door", "notifications"}


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


async def test_add_person_sends_the_usage_limit(hass: HomeAssistant, monkeypatch) -> None:
    """A positive maximum number of uses is sent to the device as maxTimes."""

    entry, captured = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    result = await flow.async_step_add({"name": "Visitor", "user_type": "visitor", "max_times": 3})
    assert result["type"] == "create_entry"

    record = [r for r in captured if r.url.path.endswith("UserInfo/Record")][-1]
    assert _body(record)["UserInfo"]["maxTimes"] == 3


async def test_add_person_omits_usage_limit_when_not_set(hass: HomeAssistant, monkeypatch) -> None:
    """Without a limit the field is left out, so firmware without it accepts the write."""

    entry, captured = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    result = await flow.async_step_add({"name": "Visitor", "user_type": "visitor"})
    assert result["type"] == "create_entry"

    record = [r for r in captured if r.url.path.endswith("UserInfo/Record")][-1]
    assert "maxTimes" not in _body(record)["UserInfo"]


async def test_edit_form_prefills_the_validity_window(hass: HomeAssistant, monkeypatch) -> None:
    """The enabled validity window is shown with the dates already filled in."""

    entry, _ = await _setup(hass, monkeypatch, users=[PERSON])
    flow = await _flow(hass, entry)
    await flow.async_step_edit({"employee_no": "1001"})
    form = await flow.async_step_edit_form()

    schema = form["data_schema"].schema
    begin_key = next(k for k in schema if getattr(k, "schema", k) == "begin_time")
    end_key = next(k for k in schema if getattr(k, "schema", k) == "end_time")
    assert begin_key.default() == "2026-01-01T00:00:00"
    assert end_key.default() == "2030-01-01T00:00:00"


async def test_edit_form_leaves_validity_empty_when_disabled(hass: HomeAssistant, monkeypatch) -> None:
    """A person without a validity window leaves both fields blank."""

    person = {**PERSON, "Valid": {"enable": False}}
    entry, _ = await _setup(hass, monkeypatch, users=[person])
    flow = await _flow(hass, entry)
    await flow.async_step_edit({"employee_no": "1001"})
    form = await flow.async_step_edit_form()

    schema = form["data_schema"].schema
    begin_key = next(k for k in schema if getattr(k, "schema", k) == "begin_time")
    end_key = next(k for k in schema if getattr(k, "schema", k) == "end_time")
    assert begin_key.default is vol.UNDEFINED
    assert end_key.default is vol.UNDEFINED


async def test_edit_form_prefills_the_usage_limit(hass: HomeAssistant, monkeypatch) -> None:
    """A device-reported maxTimes is shown in the usage-limit field."""

    entry, _ = await _setup(hass, monkeypatch, users=[{**PERSON, "maxTimes": 5}])
    flow = await _flow(hass, entry)
    await flow.async_step_edit({"employee_no": "1001"})
    form = await flow.async_step_edit_form()

    schema = form["data_schema"].schema
    limit_key = next(k for k in schema if getattr(k, "schema", k) == "max_times")
    assert limit_key.default() == 5


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


async def test_edit_form_changes_the_card(hass: HomeAssistant, monkeypatch) -> None:
    """The card field in the edit form replaces the card the person holds."""

    entry, captured = await _setup(hass, monkeypatch, users=[PERSON])
    flow = await _flow(hass, entry)

    await flow.async_step_edit({"employee_no": "1001"})
    result = await flow.async_step_edit_form(
        {"name": "Maria", "card_no": "12345678", "door_no": 1}
    )
    assert result["type"] == "create_entry"

    record = [r for r in captured if r.url.path.endswith("CardInfo/Record")][-1]
    assert _body(record)["CardInfo"]["cardNo"] == "12345678"
    # The old card is removed so the person does not end up with two.
    delete = [r for r in captured if r.url.path.endswith("CardInfo/Delete")][-1]
    assert _body(delete)["CardInfoDelCond"]["CardNoList"] == [{"cardNo": "55512345"}]


async def test_edit_form_keeps_the_card_when_unchanged(hass: HomeAssistant, monkeypatch) -> None:
    """Submitting the edit form without touching the card leaves it alone."""

    entry, captured = await _setup(hass, monkeypatch, users=[PERSON])
    flow = await _flow(hass, entry)

    await flow.async_step_edit({"employee_no": "1001"})
    result = await flow.async_step_edit_form(
        {"name": "Maria", "card_no": "55512345", "door_no": 1}
    )
    assert result["type"] == "create_entry"
    assert not [r for r in captured if r.url.path.endswith("CardInfo/Record")]


async def test_edit_form_keeps_the_card_when_field_is_empty(hass: HomeAssistant, monkeypatch) -> None:
    """An empty card field on edit keeps the card, it does not delete it."""

    entry, captured = await _setup(hass, monkeypatch, users=[PERSON])
    flow = await _flow(hass, entry)

    await flow.async_step_edit({"employee_no": "1001"})
    result = await flow.async_step_edit_form({"name": "Maria", "card_no": "", "door_no": 1})
    assert result["type"] == "create_entry"
    assert not [r for r in captured if r.url.path.endswith("CardInfo/Delete")]


async def test_edit_with_no_persons_aborts(hass: HomeAssistant, monkeypatch) -> None:
    """With an empty device the edit flow aborts cleanly."""

    entry, _ = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    result = await flow.async_step_edit()
    assert result["type"] == "abort"
    assert result["reason"] == "no_persons"


async def test_listing_without_permission_aborts_with_reason(hass: HomeAssistant, monkeypatch) -> None:
    """A device that refuses the user list explains it instead of crashing.

    The account may be missing Remote: Parameters Settings, so the 401 must turn into a
    readable message rather than an exception out of the flow.
    """

    entry, _ = await _setup(
        hass, monkeypatch, denied_paths={"AccessControl/UserInfo/Search"}
    )
    flow = await _flow(hass, entry)

    for step in ("async_step_edit", "async_step_delete"):
        result = await getattr(flow, step)()
        assert result["type"] == "abort"
        assert result["reason"] == "cannot_list"


async def test_open_door_step_unlocks(hass: HomeAssistant, monkeypatch) -> None:
    """The open door step sends the ISAPI unlock command."""

    entry, captured = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    result = await flow.async_step_open_door({"door_no": 2})
    assert result["type"] == "create_entry"
    door = [r for r in captured if "RemoteControl/door/2" in str(r.url)][-1]
    assert b"<cmd>open</cmd>" in door.content


async def test_edit_form_reports_invalid_validity(hass: HomeAssistant, monkeypatch) -> None:
    """A bad validity window shows a form error instead of raising."""

    entry, _ = await _setup(hass, monkeypatch, users=[PERSON])
    flow = await _flow(hass, entry)

    await flow.async_step_edit({"employee_no": "1001"})
    result = await flow.async_step_edit_form(
        {
            "name": "Maria",
            "validity_enabled": True,
            "begin_time": "2030-01-01T00:00:00+00:00",
            "end_time": "2020-01-01T00:00:00+00:00",
        }
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_validity"}


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


async def test_get_person_falls_back_to_full_scan(hass: HomeAssistant, monkeypatch) -> None:
    """A device that ignores the employee filter is still searched by number."""

    entry, _ = await _setup(hass, monkeypatch, users=[PERSON])
    client = entry.runtime_data.client

    original = client.request
    calls = {"n": 0}

    async def request(method, path, **kwargs):
        if "UserInfo/Search" in path:
            calls["n"] += 1
            data = kwargs.get("data") or "{}"
            if "EmployeeNoList" in data:
                # Mimic firmware that ignores the employee filter: answer empty.
                return {"UserInfoSearch": {"responseStatusStrg": "OK", "UserInfo": []}}
        return await original(method, path, **kwargs)

    monkeypatch.setattr(client, "request", request)
    person = await client.get_person("1001")
    assert calls["n"] >= 2
    assert person is not None
    assert person["employeeNo"] == "1001"


async def test_edit_form_prefills_the_pin_from_the_device(hass: HomeAssistant, monkeypatch) -> None:
    """The device returns the PIN as localPassword; the form shows it so it is not lost."""

    entry, _ = await _setup(hass, monkeypatch, users=[{**PERSON, "localPassword": "0288"}])
    flow = await _flow(hass, entry)
    flow._employee_no = "1001"

    async def _person(employee_no: str) -> dict:
        return {**PERSON, "localPassword": "0288"}

    monkeypatch.setattr(flow, "_load_person", _person)
    form = await flow.async_step_edit_form()
    schema = form["data_schema"].schema

    pin_key = next(k for k in schema if getattr(k, "schema", k) == "pin")
    assert pin_key.default() == "0288"
    assert form["description_placeholders"]["pin"] == "0288"


async def test_edit_form_pin_defaults_to_empty_when_device_hides_it(hass: HomeAssistant, monkeypatch) -> None:
    """A device that does not return the PIN leaves the field empty, not broken."""

    entry, _ = await _setup(hass, monkeypatch, users=[{**PERSON, "localPassword": ""}])
    flow = await _flow(hass, entry)
    flow._employee_no = "1001"

    async def _person(employee_no: str) -> dict:
        return {**PERSON, "localPassword": ""}

    monkeypatch.setattr(flow, "_load_person", _person)
    form = await flow.async_step_edit_form()
    schema = form["data_schema"].schema

    pin_key = next(k for k in schema if getattr(k, "schema", k) == "pin")
    assert pin_key.default() == ""
    assert form["description_placeholders"]["pin"] == "-"


async def test_edit_form_prefills_door_from_person(hass: HomeAssistant, monkeypatch) -> None:
    """The door field defaults to the door the person already has rights to."""

    entry, _ = await _setup(
        hass, monkeypatch, users=[{**PERSON, "RightPlan": [{"doorNo": 3, "planTemplateNo": "1"}]}]
    )
    flow = await _flow(hass, entry)
    await flow.async_step_edit({"employee_no": "1001"})
    form = await flow.async_step_edit_form()

    schema = form["data_schema"].schema
    door_key = next(k for k in schema if getattr(k, "schema", k) == "door_no")
    assert door_key.default() == 3


async def test_add_person_without_permission_names_the_permission(hass: HomeAssistant, monkeypatch) -> None:
    """A refused create shows the permission error, not a generic failure."""

    entry, _ = await _setup(
        hass, monkeypatch, users=[PERSON], denied_paths={"AccessControl/UserInfo/Record"}
    )
    flow = await _flow(hass, entry)

    result = await flow.async_step_add(
        {"employee_no": "2002", "name": "Nikos", "gender": "male", "user_type": "normal"}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "insufficient_permission"


async def test_edit_person_without_permission_names_the_permission(hass: HomeAssistant, monkeypatch) -> None:
    """A refused update shows the permission error too, not the generic one.

    Add already said which permission is missing; edit fell through to the generic
    "the device refused" text, so the two steps disagreed about the same 401.
    """

    entry, _ = await _setup(
        hass, monkeypatch, users=[PERSON], denied_paths={"AccessControl/UserInfo/Modify"}
    )
    flow = await _flow(hass, entry)
    await flow.async_step_edit({"employee_no": "1001"})

    result = await flow.async_step_edit_form({"name": "Maria"})
    assert result["type"] == "form"
    assert result["errors"]["base"] == "insufficient_permission"


NOTIFY_OPTIONS = {
    "notify_enabled": True,
    "notify_service": "notify.mobile_app_me",
    "notify_title": "Door",
    "notify_message": "{name} came in",
    "notify_all": True,
    "notify_names": "Maria",
    "notify_named_title": "Watched",
    "notify_named_message": "{name} is here",
    "notify_denied": True,
    "tts_enabled": True,
    "tts_all": True,
    "tts_entity": "tts.google_translate_el",
    "tts_media_player": "media_player.nest",
    "tts_message": "Καλώς ήρθες {name}",
}


async def test_notifications_step_shows_every_setting(hass: HomeAssistant, monkeypatch) -> None:
    """The notifications page offers both the phone alert and the spoken announcement."""

    entry, _ = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    result = await flow.async_step_notifications()
    assert result["type"] == "form"
    keys = {key.schema for key in result["data_schema"].schema}
    assert keys == set(NOTIFY_OPTIONS)


async def test_notifications_step_saves_the_settings(hass: HomeAssistant, monkeypatch) -> None:
    """Submitting the page writes the options."""

    entry, _ = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    result = await flow.async_step_notifications(
        {"notify_enabled": True, "notify_service": "notify.mobile_app_me", "notify_all": True}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["notify_enabled"] is True
    assert result["data"]["notify_service"] == "notify.mobile_app_me"
    assert result["data"]["notify_all"] is True


async def test_notifications_step_accepts_empty_entity_fields(hass: HomeAssistant, monkeypatch) -> None:
    """An untouched page submits, with the announcement and notify entities left empty.

    The fields start empty and the stock entity selector rejects an empty string, so
    submitting the page unchanged failed with "Entity is neither a valid entity ID nor a
    valid UUID" and nothing was saved, even with announcements turned off.
    """

    entry, _ = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)

    form = await flow.async_step_notifications()
    schema = form["data_schema"]

    submitted = {
        "notify_service": "",
        "tts_entity": "",
        "tts_media_player": "",
    }
    result = schema(submitted)
    assert result["notify_service"] == ""
    assert result["tts_entity"] == ""
    assert result["tts_media_player"] == ""

    assert (await flow.async_step_notifications(submitted))["type"] == "create_entry"


async def test_notifications_schema_serializes_for_the_frontend(hass: HomeAssistant, monkeypatch) -> None:
    """The form schema must convert to the JSON the frontend renders."""

    from homeassistant.helpers import config_validation as cv
    from probatio import to_field_list

    entry, _ = await _setup(hass, monkeypatch)
    flow = await _flow(hass, entry)
    form = await flow.async_step_notifications()

    fields = to_field_list(form["data_schema"], custom_serializer=cv.custom_serializer)
    names = {field["name"] for field in fields}
    assert {"notify_service", "tts_entity", "tts_media_player"} <= names
    for field in fields:
        if field["name"] in {"notify_service", "tts_entity", "tts_media_player"}:
            assert field["default"] == ""


async def test_person_action_keeps_the_notification_settings(
    hass: HomeAssistant, monkeypatch
) -> None:
    """Deleting a person must not wipe the notification options."""

    entry, _ = await _setup(hass, monkeypatch)
    hass.config_entries.async_update_entry(entry, options=dict(NOTIFY_OPTIONS))
    flow = await _flow(hass, entry)

    await flow.async_step_delete({"employee_no": "1001"})
    result = await flow.async_step_delete_confirm({"confirm": True})
    assert result["type"] == "create_entry"
    for key, value in NOTIFY_OPTIONS.items():
        assert result["data"][key] == value

