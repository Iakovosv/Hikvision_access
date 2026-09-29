"""Person management for the Hikvision Access Control integration.

Everything a person needs is edited from the Home Assistant UI instead of a YAML
service call: add, edit, delete, PINs, cards and the validity window. The flow talks
to the device through the coordinator's client, so no options are stored on the entry.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, OptionsFlow
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BEGIN_TIME,
    ATTR_CARD_NO,
    ATTR_DOOR_NO,
    ATTR_EMPLOYEE_NO,
    ATTR_END_TIME,
    ATTR_GENDER,
    ATTR_NAME,
    ATTR_PIN,
    ATTR_USER_TYPE,
    ATTR_VALIDITY_ENABLED,
    CONF_NOTIFY_ALL,
    CONF_NOTIFY_DENIED,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_MESSAGE,
    CONF_NOTIFY_NAMES,
    CONF_NOTIFY_NAMED_MESSAGE,
    CONF_NOTIFY_NAMED_TITLE,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TITLE,
    CONF_TTS_ENABLED,
    CONF_TTS_ALL,
    CONF_TTS_ENTITY,
    CONF_TTS_MESSAGE,
    CONF_TTS_MEDIA_PLAYER,
    DEFAULT_NOTIFY_MESSAGE,
    DEFAULT_NOTIFY_NAMED_MESSAGE,
    DEFAULT_NOTIFY_NAMED_TITLE,
    DEFAULT_NOTIFY_TITLE,
    DEFAULT_TTS_MESSAGE,
    DOMAIN,
    GENDERS,
    NOTIFICATION_PLACEHOLDERS,
    USER_TYPES,
    VISIT_TIMES_REMAINING_KEYS,
    VISIT_TIMES_TOTAL_KEYS,
    VISIT_TIMES_USED_KEYS,
)
from .isapi import HikvisionAccessError, HikvisionAccessForbiddenError

_LOGGER = logging.getLogger(__name__)

MENU_ADD = "add"
MENU_EDIT = "edit"
MENU_DELETE = "delete"
MENU_OPEN_DOOR = "open_door"
MENU_NOTIFICATIONS = "notifications"

# A generated PIN is six digits; the device accepts four to eight.
GENERATED_PIN_DIGITS = 6


def _door_number(value: Any, default: int = 1) -> int:
    """Coerce a door number, falling back to the default instead of raising."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _person_label(person: dict[str, Any]) -> str:
    """Return a readable label for a device person."""

    name = person.get("name") or "(no name)"
    return f"{name} - {person.get('employeeNo')}"


class HikvisionAccessOptionsFlow(OptionsFlow):
    """Manage persons on the terminal from the Home Assistant UI."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Store the entry the flow belongs to."""

        self._entry = config_entry
        self._employee_no: str | None = None
        self._list_error: str | None = None

    @property
    def _client(self):
        """Return the ISAPI client, or raise when the entry is not loaded."""

        coordinator = getattr(self._entry, "runtime_data", None)
        if coordinator is None:
            raise HomeAssistantError(
                "The device is not set up. Fix the setup error on the integration page first."
            )
        return coordinator.client

    @property
    def _door_numbers(self) -> list[int]:
        """Return the doors the terminal reports, defaulting to one."""

        coordinator = getattr(self._entry, "runtime_data", None)
        return list(getattr(coordinator, "door_numbers", None) or [1])

    async def _async_persons(self) -> list[dict[str, Any]] | None:
        """Return every person enrolled on the device, or None when it cannot be read.

        A device whose account may not read the enrolment list answers 401. Returning None
        lets each step explain that instead of raising out of the flow, which would show
        the user a bare "unknown error".
        """

        persons: list[dict[str, Any]] = []
        position = 0
        while True:
            try:
                body = await self._client.get_users(position=position, max_results=100)
            except HikvisionAccessError as ex:
                _LOGGER.warning("Could not read the persons from the device: %s", ex)
                self._list_error = str(ex)
                return None
            info = body.get("UserInfoSearch", {})
            page = info.get("UserInfo") or []
            if isinstance(page, dict):
                page = [page]
            persons.extend(page)
            if info.get("responseStatusStrg") != "MORE" or not page:
                break
            position += len(page)
        return persons

    async def _load_person(self, employee_no: str) -> dict[str, Any] | None:
        """Return one person, or None when the device cannot be asked."""

        try:
            return await self._client.get_person(employee_no)
        except HikvisionAccessError as ex:
            _LOGGER.warning("Could not read person %s from the device: %s", employee_no, ex)
            self._list_error = str(ex)
            return None

    def _cannot_list(self):
        """Abort because the person list could not be read, showing the device's answer."""

        return self.async_abort(
            reason="cannot_list",
            description_placeholders={"error": self._list_error or "no answer from the device"},
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Show the person management menu."""

        if self._entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")

        return self.async_show_menu(
            step_id="init",
            menu_options=[MENU_ADD, MENU_EDIT, MENU_DELETE, MENU_OPEN_DOOR, MENU_NOTIFICATIONS],
        )

    async def async_step_add(self, user_input: dict[str, Any] | None = None):
        """Create a person."""

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._create(user_input)
            except HikvisionAccessForbiddenError as ex:
                errors["base"] = "insufficient_permission"
                _LOGGER.warning("Could not create the person: %s", ex)
            except HikvisionAccessError as ex:
                errors["base"] = "device_error"
                _LOGGER.error("Could not create the person: %s", ex)
            except HomeAssistantError as ex:
                errors["base"] = str(ex)
            else:
                return self.async_create_entry(title="", data=dict(self._entry.options))

        return self.async_show_form(
            step_id="add",
            data_schema=self._person_schema(include_card=True),
            errors=errors,
        )

    async def async_step_edit(self, user_input: dict[str, Any] | None = None):
        """Pick a person to edit."""

        if user_input is not None:
            self._employee_no = user_input[ATTR_EMPLOYEE_NO]
            return await self.async_step_edit_form()

        persons = await self._async_persons()
        if persons is None:
            return self._cannot_list()
        if not persons:
            return self.async_abort(reason="no_persons")

        return self.async_show_form(
            step_id="edit",
            data_schema=vol.Schema(
                {vol.Required(ATTR_EMPLOYEE_NO): self._person_selector(persons)}
            ),
        )

    async def async_step_edit_form(self, user_input: dict[str, Any] | None = None):
        """Edit the chosen person, including the card, prefilled from the device."""

        employee_no = self._employee_no
        if employee_no is None:  # pragma: no cover - only reachable out of order
            return await self.async_step_edit()

        person = await self._load_person(employee_no)
        if person is None:
            return self._cannot_list()

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._modify(employee_no, user_input)
                await self._sync_card(employee_no, person, user_input)
            except HikvisionAccessForbiddenError as ex:
                errors["base"] = "insufficient_permission"
                _LOGGER.warning("Could not update the person: %s", ex)
            except HikvisionAccessError as ex:
                errors["base"] = "device_error"
                _LOGGER.error("Could not update the person: %s", ex)
            except HomeAssistantError as ex:
                errors["base"] = str(ex)
            else:
                return self.async_create_entry(title="", data=dict(self._entry.options))

        return self.async_show_form(
            step_id="edit_form",
            data_schema=self._person_schema(defaults=person, include_card=True),
            description_placeholders=self._person_summary(person),
            errors=errors,
        )

    async def async_step_delete(self, user_input: dict[str, Any] | None = None):
        """Pick a person to delete."""

        if user_input is not None:
            self._employee_no = user_input[ATTR_EMPLOYEE_NO]
            return await self.async_step_delete_confirm()

        persons = await self._async_persons()
        if persons is None:
            return self._cannot_list()
        if not persons:
            return self.async_abort(reason="no_persons")

        return self.async_show_form(
            step_id="delete",
            data_schema=vol.Schema(
                {vol.Required(ATTR_EMPLOYEE_NO): self._person_selector(persons)}
            ),
        )

    async def async_step_delete_confirm(self, user_input: dict[str, Any] | None = None):
        """Confirm and delete the chosen person."""

        employee_no = self._employee_no
        if employee_no is None:  # pragma: no cover - only reachable out of order
            return await self.async_step_delete()

        if user_input is not None:
            if not user_input.get("confirm"):
                return self.async_abort(reason="delete_cancelled")
            try:
                await self._client.delete_person(employee_no)
            except HikvisionAccessForbiddenError as ex:
                _LOGGER.warning("Could not delete the person: %s", ex)
                return self.async_show_form(
                    step_id="delete_confirm",
                    data_schema=self._confirm_schema(),
                    errors={"base": "insufficient_permission"},
                )
            except HikvisionAccessError as ex:
                _LOGGER.error("Could not delete the person: %s", ex)
                return self.async_show_form(
                    step_id="delete_confirm",
                    data_schema=self._confirm_schema(),
                    errors={"base": "device_error"},
                )
            return self.async_create_entry(title="", data=dict(self._entry.options))

        return self.async_show_form(
            step_id="delete_confirm",
            data_schema=self._confirm_schema(),
            description_placeholders={"employee_no": employee_no},
        )

    async def async_step_open_door(self, user_input: dict[str, Any] | None = None):
        """Unlock a door once."""

        if user_input is not None:
            try:
                door_no = _door_number(user_input.get(ATTR_DOOR_NO))
                await self._client.open_door(door_no)
            except HikvisionAccessError as ex:
                _LOGGER.error("Could not open the door: %s", ex)
                return self.async_show_form(
                    step_id="open_door",
                    data_schema=self._door_schema(),
                    errors={"base": "device_error"},
                )
            return self.async_create_entry(title="", data=dict(self._entry.options))

        return self.async_show_form(step_id="open_door", data_schema=self._door_schema())

    async def async_step_notifications(self, user_input: dict[str, Any] | None = None):
        """Configure the optional phone notification and the spoken announcement."""

        if self._entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")

        if user_input is not None:
            options = dict(self._entry.options)
            options.update(user_input)
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="notifications",
            data_schema=self._notifications_schema(),
            description_placeholders={
                "placeholders": ", ".join(f"{{{name}}}" for name in NOTIFICATION_PLACEHOLDERS)
            },
        )

    def _notifications_schema(self) -> vol.Schema:
        """Build the notification settings form from the current options."""

        options = self._entry.options
        return vol.Schema(
            {
                vol.Optional(
                    CONF_NOTIFY_ENABLED, default=bool(options.get(CONF_NOTIFY_ENABLED, False))
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NOTIFY_SERVICE, default=str(options.get(CONF_NOTIFY_SERVICE) or "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="notify", multiple=False)
                ),
                vol.Optional(
                    CONF_NOTIFY_TITLE,
                    default=str(options.get(CONF_NOTIFY_TITLE) or DEFAULT_NOTIFY_TITLE),
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_NOTIFY_MESSAGE,
                    default=str(
                        options.get(CONF_NOTIFY_MESSAGE) or DEFAULT_NOTIFY_MESSAGE
                    ),
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Optional(
                    CONF_NOTIFY_ALL, default=bool(options.get(CONF_NOTIFY_ALL, False))
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NOTIFY_NAMES, default=str(options.get(CONF_NOTIFY_NAMES) or "")
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_NOTIFY_NAMED_TITLE,
                    default=str(options.get(CONF_NOTIFY_NAMED_TITLE) or DEFAULT_NOTIFY_NAMED_TITLE),
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_NOTIFY_NAMED_MESSAGE,
                    default=str(
                        options.get(CONF_NOTIFY_NAMED_MESSAGE) or DEFAULT_NOTIFY_NAMED_MESSAGE
                    ),
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Optional(
                    CONF_NOTIFY_DENIED, default=bool(options.get(CONF_NOTIFY_DENIED, False))
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_TTS_ENABLED, default=bool(options.get(CONF_TTS_ENABLED, False))
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_TTS_ALL, default=bool(options.get(CONF_TTS_ALL, False))
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_TTS_ENTITY, default=str(options.get(CONF_TTS_ENTITY) or "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="tts", multiple=False)
                ),
                vol.Optional(
                    CONF_TTS_MEDIA_PLAYER, default=str(options.get(CONF_TTS_MEDIA_PLAYER) or "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player", multiple=False)
                ),
                vol.Optional(
                    CONF_TTS_MESSAGE,
                    default=str(options.get(CONF_TTS_MESSAGE) or DEFAULT_TTS_MESSAGE),
                ): selector.TextSelector(),
            }
        )

    async def _create(self, user_input: dict[str, Any]) -> None:
        """Create a person, allocating an employee number and PIN when omitted."""

        employee_no = (user_input.get(ATTR_EMPLOYEE_NO) or "").strip()
        if not employee_no:
            employee_no = await self._next_employee_no()

        pin = (user_input.get(ATTR_PIN) or "").strip()
        if not pin:
            pin = f"{secrets.randbelow(10**GENERATED_PIN_DIGITS):0{GENERATED_PIN_DIGITS}d}"

        begin, end = self._validity(user_input)
        await self._client.create_person(
            employee_no=employee_no,
            name=user_input[ATTR_NAME],
            begin_time=begin,
            end_time=end,
            pin=pin,
            door_no=_door_number(user_input.get(ATTR_DOOR_NO)),
            gender=user_input.get(ATTR_GENDER),
            user_type=user_input.get(ATTR_USER_TYPE, "normal"),
            card_no=(user_input.get(ATTR_CARD_NO) or "").strip() or None,
        )

    async def _modify(self, employee_no: str, user_input: dict[str, Any]) -> None:
        """Update a person, leaving credentials that were not filled in untouched."""

        begin, end = self._validity(user_input)
        await self._client.modify_person(
            employee_no=employee_no,
            name=user_input.get(ATTR_NAME),
            begin_time=begin,
            end_time=end,
            pin=(user_input.get(ATTR_PIN) or "").strip() or None,
            door_no=_door_number(user_input.get(ATTR_DOOR_NO)),
            gender=user_input.get(ATTR_GENDER),
            user_type=user_input.get(ATTR_USER_TYPE, "normal"),
        )

    async def _sync_card(
        self, employee_no: str, person: dict[str, Any], user_input: dict[str, Any]
    ) -> None:
        """Apply the card field from the edit form, which holds one card number.

        An empty field means "keep the current card", so editing a person never silently
        removes a card. A filled field replaces the card the person holds.
        """

        card_no = (user_input.get(ATTR_CARD_NO) or "").strip()
        current = self._card_numbers(person)
        if not card_no:
            return
        if card_no in current:
            return
        await self._clear_cards(person)
        await self._client.set_card(employee_no, card_no)

    def _validity(self, user_input: dict[str, Any]) -> tuple[Any, Any]:
        """Return the validity window, or (None, None) when it is not enabled."""

        if not user_input.get(ATTR_VALIDITY_ENABLED):
            return None, None
        begin_raw = user_input.get(ATTR_BEGIN_TIME)
        end_raw = user_input.get(ATTR_END_TIME)
        if not begin_raw or not end_raw:
            raise HomeAssistantError("invalid_validity")
        begin = dt_util.as_local(cv.datetime(begin_raw))
        end = dt_util.as_local(cv.datetime(end_raw))
        if end <= begin:
            raise HomeAssistantError("invalid_validity")
        return begin, end

    async def _clear_cards(self, person: dict[str, Any]) -> None:
        """Remove every card the person currently holds."""

        for card in self._card_numbers(person):
            await self._client.delete_card(card)

    @staticmethod
    def _card_numbers(person: dict[str, Any]) -> list[str]:
        """Return the card numbers the device reports for a person."""

        cards = person.get("CardInfo") or person.get("cardList") or []
        if isinstance(cards, dict):
            cards = [cards]
        numbers = []
        for card in cards:
            if isinstance(card, dict) and card.get("cardNo"):
                numbers.append(str(card["cardNo"]))
        return numbers

    def _current_cards(self, person: dict[str, Any]) -> str:
        """Return the card numbers as a display string."""

        return ", ".join(self._card_numbers(person))

    @staticmethod
    def _person_summary(person: dict[str, Any]) -> dict[str, str]:
        """Return the read-only details shown above the edit form."""

        valid = person.get("Valid") or {}
        validity = "-"
        if valid.get("enable"):
            validity = f"{valid.get('beginTime', '?')} - {valid.get('endTime', '?')}"

        return {
            "employee_no": str(person.get("employeeNo", "")),
            "name": person.get("name") or "-",
            "user_type": person.get("userType") or "-",
            "gender": person.get("gender") or "-",
            "pin": str(person.get("localPassword") or person.get("password") or "-"),
            "validity": validity,
            "cards": f"{person.get('numOfCard', 0)}",
            "fingerprints": f"{person.get('numOfFP', 0)}",
            "visits": HikvisionAccessOptionsFlow._visit_summary(person),
        }

    @staticmethod
    def _visit_summary(person: dict[str, Any]) -> str:
        """Return the visitor visit counters when the device reports them."""

        def _first(keys: tuple[str, ...]) -> Any:
            for key in keys:
                if person.get(key) is not None:
                    return person[key]
            return None

        total = _first(VISIT_TIMES_TOTAL_KEYS)
        used = _first(VISIT_TIMES_USED_KEYS)
        remaining = _first(VISIT_TIMES_REMAINING_KEYS)
        if total is None and used is None and remaining is None:
            return "-"
        return f"remaining {remaining if remaining is not None else '?'} / used {used if used is not None else '?'} / total {total if total is not None else '?'}"

    def _person_schema(self, defaults: dict[str, Any] | None = None, include_card: bool = False) -> vol.Schema:
        """Return the add/edit form schema, optionally prefilled from the device."""

        defaults = defaults or {}
        valid = defaults.get("Valid") or {}

        employee_default = str(defaults.get("employeeNo", ""))
        name_default = defaults.get("name") or ""
        gender_default = defaults.get("gender")
        type_default = defaults.get("userType")
        validity_enabled = bool(valid.get("enable"))

        schema: dict[Any, Any] = {
            vol.Optional(ATTR_EMPLOYEE_NO, default=employee_default): selector.TextSelector(),
            vol.Required(ATTR_NAME, default=name_default): selector.TextSelector(),
        }
        if gender_default in GENDERS:
            schema[vol.Optional(ATTR_GENDER, default=gender_default)] = self._gender_selector()
        else:
            schema[vol.Optional(ATTR_GENDER)] = self._gender_selector()
        if type_default in USER_TYPES:
            schema[vol.Optional(ATTR_USER_TYPE, default=type_default)] = self._type_selector()
        else:
            schema[vol.Optional(ATTR_USER_TYPE, default="normal")] = self._type_selector()
        pin_default = str(defaults.get("localPassword") or defaults.get("password") or "")
        schema[vol.Optional(ATTR_PIN, default=pin_default)] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        schema[vol.Optional(ATTR_VALIDITY_ENABLED, default=validity_enabled)] = selector.BooleanSelector()
        schema[vol.Optional(ATTR_BEGIN_TIME)] = selector.DateTimeSelector()
        schema[vol.Optional(ATTR_END_TIME)] = selector.DateTimeSelector()
        if include_card:
            # On edit the field shows the card the person already holds; on add it starts
            # empty. Submitting the shown card again is a no-op.
            current_card = ""
            if defaults:
                cards = HikvisionAccessOptionsFlow._card_numbers(defaults)
                current_card = cards[0] if cards else ""
            schema[vol.Optional(ATTR_CARD_NO, default=current_card)] = selector.TextSelector()
        doors = self._door_numbers
        door_default = self._door_default(defaults)
        # A person may hold rights to a door the terminal did not advertise; never silently
        # move them to another door, just widen the range to cover it.
        highest = max([*doors, door_default])
        schema[vol.Optional(ATTR_DOOR_NO, default=door_default)] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=highest, mode=selector.NumberSelectorMode.BOX)
        )
        return vol.Schema(schema)

    @staticmethod
    def _door_default(person: dict[str, Any]) -> int:
        """Return the first door the person is allowed to open, defaulting to 1."""

        plans = person.get("RightPlan") or []
        if isinstance(plans, dict):
            plans = [plans]
        for plan in plans:
            if isinstance(plan, dict) and plan.get("doorNo") is not None:
                try:
                    return int(plan["doorNo"])
                except (TypeError, ValueError):
                    return 1
        return 1

    @staticmethod
    def _gender_selector() -> selector.SelectSelector:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(GENDERS), mode=selector.SelectSelectorMode.DROPDOWN
            )
        )

    @staticmethod
    def _type_selector() -> selector.SelectSelector:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(USER_TYPES), mode=selector.SelectSelectorMode.DROPDOWN
            )
        )

    @staticmethod
    def _person_selector(persons: list[dict[str, Any]]) -> selector.SelectSelector:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=str(person.get("employeeNo")), label=_person_label(person)
                    )
                    for person in persons
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    def _door_schema(self) -> vol.Schema:
        """Return the door picker, limited to the doors the terminal reports."""

        doors = self._door_numbers
        if len(doors) > 1:
            return vol.Schema(
                {
                    vol.Optional(ATTR_DOOR_NO, default=doors[0]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[str(door) for door in doors],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            )
        return vol.Schema(
            {
                vol.Optional(ATTR_DOOR_NO, default=doors[0]): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=max(doors), mode=selector.NumberSelectorMode.BOX
                    )
                )
            }
        )

    @staticmethod
    def _confirm_schema() -> vol.Schema:
        return vol.Schema({vol.Required("confirm", default=False): selector.BooleanSelector()})

    async def _next_employee_no(self) -> str:
        """Allocate a free employee number, keeping visitors away from staff numbers."""

        persons = await self._async_persons() or []
        existing = {str(person.get("employeeNo")) for person in persons}
        number = 900001
        while str(number) in existing:
            number += 1
        return str(number)


@callback
def async_get_options_flow(config_entry: ConfigEntry) -> HikvisionAccessOptionsFlow:
    """Return the options flow for a config entry."""

    return HikvisionAccessOptionsFlow(config_entry)
