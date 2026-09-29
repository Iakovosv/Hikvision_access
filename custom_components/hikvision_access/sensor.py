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
    async_add_entities(
        [LastAccessSensor(coordinator), LastAccessPersonSensor(coordinator), PersonsEnrolledSensor(coordinator)]
    )


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
        """Expose who authenticated, through which door, and the exact date and time.

        The state itself is a timestamp, which the frontend shows as a relative time
        ("9 hours ago"). The precise date and time are added here so a dashboard card can
        show them, in the machine-readable attributes and as ready-made strings.
        """

        if self.coordinator.event_access_denied:
            return {"reason": "The device account may not read access events"}

        event = self.coordinator.last_event
        if event is None:
            return {}
        local = event.time.astimezone()
        return {
            "name": event.name,
            "employee_no": event.employee_no,
            "card_no": event.card_no,
            "door_no": event.door_no,
            "method": event.method,
            "granted": event.granted,
            "date": local.strftime("%Y-%m-%d"),
            "time": local.strftime("%H:%M:%S"),
            "datetime": local.isoformat(),
        }


class LastAccessPersonSensor(HikvisionAccessEntity, CoordinatorEntity, SensorEntity):
    """Name the person who last opened the door.

    The last-access binary sensor can only read `on`/`off`, which the frontend labels
    "Detected", so the person's name has no place there. This sensor carries the name as
    its state instead, which is what the device page and a dashboard card read.
    """

    _attr_translation_key = "last_access_person"
    _attr_icon = "mdi:account-check"

    def __init__(self, coordinator: HikvisionAccessCoordinator) -> None:
        """Initialize the sensor."""

        HikvisionAccessEntity.__init__(self, coordinator)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = f"{coordinator.serial_no}_last_access_person"

    @property
    def native_value(self) -> str | None:
        """Return the name of the last person, falling back to their employee number."""

        event = self.coordinator.last_event
        if event is None:
            return None
        return event.name or event.employee_no

    @property
    def available(self) -> bool:
        """Whether the coordinator has data and may read events."""

        if self.coordinator.event_access_denied:
            return False
        return super().available

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the details of that access."""

        if self.coordinator.event_access_denied:
            return {"reason": "The device account may not read access events"}

        event = self.coordinator.last_event
        if event is None:
            return {}
        return {
            "employee_no": event.employee_no,
            "card_no": event.card_no,
            "door_no": event.door_no,
            "method": event.method,
            "granted": event.granted,
            "time": event.time.isoformat(),
        }


class PersonsEnrolledSensor(HikvisionAccessEntity, CoordinatorEntity, SensorEntity):
    """Show how many people are enrolled on the terminal.

    Read once at setup. The count is only a convenience: a device account without the
    person permission answers 401 and the sensor shows nothing instead of failing.
    """

    _attr_icon = "mdi:account-multiple"
    _attr_translation_key = "persons_enrolled"
    _attr_native_unit_of_measurement = "persons"

    def __init__(self, coordinator: HikvisionAccessCoordinator) -> None:
        """Initialize the sensor."""

        HikvisionAccessEntity.__init__(self, coordinator)
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_unique_id = f"{coordinator.serial_no}_persons_enrolled"

    @property
    def native_value(self) -> int | None:
        """Return the number of enrolled persons, or nothing when it is unknown."""

        return self.coordinator.persons_enrolled

    @property
    def extra_state_attributes(self) -> dict:
        """Say why the count is missing, when it is."""

        if self.coordinator.persons_enrolled is None:
            return {
                "reason": (
                    "The device account could not read the person count. It needs "
                    "Remote: Parameters Settings."
                )
            }
        return {}
