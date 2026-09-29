"""Timestamp sensor for the last access event on a terminal."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HikvisionAccessEntity
from .coordinator import HikvisionAccessCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the last-access sensor."""

    coordinator: HikvisionAccessCoordinator = entry.runtime_data
    async_add_entities([LastAccessSensor(coordinator)])


class LastAccessSensor(HikvisionAccessEntity, CoordinatorEntity, SensorEntity):
    """Show when someone last authenticated, and who it was."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_access"

    def __init__(self, coordinator: HikvisionAccessCoordinator) -> None:
        """Initialize the sensor."""

        HikvisionAccessEntity.__init__(self, coordinator)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = f"{coordinator.serial_no}_last_access_time"

    @property
    def native_value(self):
        """Return the time of the last authentication."""

        event = self.coordinator.last_event
        return event.time if event is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        """Expose who authenticated and through which door."""

        if self.coordinator.event_access_denied:
            return {"reason": "The device account may not read access events"}

        event = self.coordinator.last_event
        if event is None:
            return {}
        return {
            "name": event.name,
            "employee_no": event.employee_no,
            "card_no": event.card_no,
            "door_no": event.door_no,
            "granted": event.minor == 75,
        }
