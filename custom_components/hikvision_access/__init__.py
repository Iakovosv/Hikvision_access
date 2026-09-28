"""The Hikvision Access Control integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.util import dt as dt_util

from .const import CLOCK_DRIFT_WARNING_SECONDS, DOMAIN
from .coordinator import HikvisionAccessCoordinator
from .isapi import (
    HikvisionAccessAuthError,
    HikvisionAccessClient,
    HikvisionAccessError,
    HikvisionAccessForbiddenError,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR]

type HikvisionAccessConfigEntry = ConfigEntry[HikvisionAccessCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HikvisionAccessConfigEntry) -> bool:
    """Set up an access control terminal from a config entry."""

    verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
    session = get_async_client(hass, verify_ssl)
    client = HikvisionAccessClient(
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        verify_ssl=verify_ssl,
        session=session,
    )

    try:
        device_info = await client.get_device_info()
    except HikvisionAccessAuthError as ex:
        raise ConfigEntryAuthFailed from ex
    except HikvisionAccessError as ex:
        raise ConfigEntryNotReady(str(ex)) from ex
    except Exception as ex:  # pylint: disable=broad-except
        raise ConfigEntryNotReady(f"Cannot connect to {entry.data[CONF_HOST]}: {ex}") from ex

    coordinator = HikvisionAccessCoordinator(hass, entry, client, device_info)
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        error = coordinator.last_client_error or coordinator.last_exception
        if isinstance(error, HikvisionAccessForbiddenError):
            # Without event access the integration has nothing to do, and the credentials
            # are not the problem. Stop retrying so the entry shows one actionable error
            # instead of looping, and do not ask for a new password.
            raise ConfigEntryError(str(error)) from error
        if isinstance(error, HikvisionAccessAuthError):
            raise ConfigEntryAuthFailed(str(error)) from error
        raise ConfigEntryNotReady(str(error)) from error
    await _warn_on_clock_drift(client)

    entry.runtime_data = coordinator

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, coordinator.serial_no)},
        manufacturer=device_info.get("manufacturer", "Hikvision"),
        model=device_info.get("model"),
        name=device_info.get("deviceName") or entry.title,
        sw_version=device_info.get("firmwareVersion"),
        configuration_url=entry.data[CONF_HOST],
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HikvisionAccessConfigEntry) -> bool:
    """Unload a config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _warn_on_clock_drift(client: HikvisionAccessClient) -> None:
    """Log a warning when the device clock differs enough to hide events."""

    try:
        device_time = await client.get_device_time()
    except HikvisionAccessError as ex:
        _LOGGER.debug("Could not read the device clock: %s", ex)
        return
    if device_time is None:
        return
    drift = abs((dt_util.utcnow() - dt_util.as_utc(device_time)).total_seconds())
    if drift > CLOCK_DRIFT_WARNING_SECONDS:
        _LOGGER.warning(
            "The access control device clock differs from Home Assistant by %.0f seconds. "
            "Access events may be missed until the clocks match (enable NTP on the device)",
            drift,
        )


class HikvisionAccessEntity(Entity):
    """Base entity bound to the access control device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HikvisionAccessCoordinator) -> None:
        """Initialize the entity."""

        self.coordinator = coordinator
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.serial_no)})

    @property
    def available(self) -> bool:
        """Return whether the coordinator has data."""

        return self.coordinator.last_update_success
