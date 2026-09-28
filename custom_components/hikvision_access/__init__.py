"""The Hikvision Access Control integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.httpx_client import get_async_client

from .const import CONF_VERIFY_SSL, DOMAIN
from .coordinator import AccessEvent, HikvisionAccessCoordinator
from .isapi import HikvisionAccessAuthError, HikvisionAccessClient, HikvisionAccessError
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
    await coordinator.async_config_entry_first_refresh()

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
