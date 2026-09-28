"""Binary sensor for the last access event on a terminal."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HikvisionAccessEntity
from .const import DOMAIN
from .coordinator import HikvisionAccessCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the last-access binary sensor."""

    coordinator: HikvisionAccessCoordinator = entry.runtime_data
    async_add_entities([LastAccessSensor(coordinator)])


class LastAccessSensor(HikvisionAccessEntity, CoordinatorEntity, BinarySensorEntity):
    """Turn on for a moment when someone authenticates."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_translation_key = "last_access"

    def __init__(self, coordinator: HikvisionAccessCoordinator) -> None:
        """Initialize the sensor."""

        HikvisionAccessEntity.__init__(self, coordinator)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = f"{coordinator.serial_no}_last_access"

    @property
    def is_on(self) -> bool:
        """Whether the last event was a granted access."""

        return self.coordinator.is_entry_granted

    @property
    def extra_state_attributes(self) -> dict:
        """Expose who last authenticated."""

        event = self.coordinator.last_event
        if event is None:
            return {}
        return {
            "name": event.name,
            "employee_no": event.employee_no,
            "card_no": event.card_no,
            "door_no": event.door_no,
            "time": event.time.isoformat(),
        }
