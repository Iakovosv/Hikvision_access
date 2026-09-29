"""Buttons for a Hikvision access control terminal."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HikvisionAccessEntity
from .coordinator import HikvisionAccessCoordinator
from .isapi import HikvisionAccessError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add one button per door the terminal reports."""

    coordinator: HikvisionAccessCoordinator = entry.runtime_data
    async_add_entities(
        OpenDoorButton(coordinator, door) for door in coordinator.door_numbers
    )


class OpenDoorButton(HikvisionAccessEntity, ButtonEntity):
    """Unlock a door once, straight from the device page."""

    _attr_translation_key = "open_door"

    def __init__(self, coordinator: HikvisionAccessCoordinator, door_no: int) -> None:
        """Initialize the button."""

        super().__init__(coordinator)
        self._door_no = door_no
        self._attr_unique_id = f"{coordinator.serial_no}_open_door_{door_no}"
        self._attr_translation_placeholders = {"door": str(door_no)}

    async def async_press(self) -> None:
        """Unlock the door."""

        try:
            await self.coordinator.client.open_door(self._door_no)
        except HikvisionAccessError as ex:
            raise HomeAssistantError(f"Could not open door {self._door_no}: {ex}") from ex
