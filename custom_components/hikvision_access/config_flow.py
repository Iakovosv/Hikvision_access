"""Config flow for the hikvision_access integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.helpers.httpx_client import get_async_client

from .const import CONF_VERIFY_SSL, DOMAIN
from .isapi import HikvisionAccessAuthError, HikvisionAccessClient, HikvisionAccessError

_LOGGER = logging.getLogger(__name__)


class HikvisionAccessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Hikvision access control terminal."""

    VERSION = 1
    _entry: Any

    async def get_schema(self, user_input: dict[str, Any]):
        """Return the configuration schema."""

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="http://"): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_VERIFY_SSL, default=True): bool,
            }
        )
        if self.source in (SOURCE_RECONFIGURE, SOURCE_REAUTH):
            return self.add_suggested_values_to_schema(schema, {**self._entry.data, **(user_input or {})})
        return schema

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""

        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST].rstrip("/")
            validated = {**user_input, CONF_HOST: host}

            try:
                session = get_async_client(self.hass, user_input[CONF_VERIFY_SSL])
                client = HikvisionAccessClient(
                    host=host,
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    verify_ssl=user_input[CONF_VERIFY_SSL],
                    session=session,
                )
                device_info = await client.get_device_info()
            except HikvisionAccessAuthError:
                errors["base"] = "invalid_auth"
            except HikvisionAccessError:
                errors["base"] = "insufficient_permission"
            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.error("Unexpected %s: %s", type(ex).__name__, ex)
                errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(device_info.get("serialNumber"), raise_on_progress=False)
                self._abort_if_unique_id_configured()

                if self.source in (SOURCE_RECONFIGURE, SOURCE_REAUTH):
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(self._entry, data_updates=validated)

                return self.async_create_entry(
                    title=device_info.get("deviceName") or device_info.get("model") or host,
                    data=validated,
                )

        return self.async_show_form(step_id="user", data_schema=await self.get_schema(user_input), errors=errors)

    async def async_step_reconfigure(self, user_input: Mapping[str, Any] | None = None) -> ConfigFlowResult:
        """Handle device re-configuration."""

        self._entry = self._get_reconfigure_entry()
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle reauthentication."""

        self._entry = self._get_reauth_entry()
        return await self.async_step_user()
