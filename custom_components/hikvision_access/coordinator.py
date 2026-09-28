"""Coordinator polling access control events."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ACS_EVENT_INITIAL_LOOKBACK_SECONDS,
    ACS_EVENT_MAJOR,
    ACS_EVENT_MINOR_SUCCESS,
    ACS_EVENT_PAGE_SIZE,
    DOMAIN,
    EVENT_TYPE_ACCESS,
)
from .isapi import HikvisionAccessAuthError, HikvisionAccessClient, HikvisionAccessError

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL = dt.timedelta(seconds=30)


@dataclass
class AccessEvent:
    """A single authentication on the terminal."""

    serial_no: str
    time: dt.datetime
    name: str | None
    employee_no: str | None
    card_no: str | None
    door_no: int | None
    major: int
    minor: int
    event_id: str | None

    @property
    def unique_id(self) -> str:
        """Stable id used for deduplication."""

        return f"{self.serial_no}_{self.time.isoformat()}_{self.employee_no}_{self.minor}"


def _parse_time(value: str | None) -> dt.datetime:
    """Parse an ISAPI timestamp, falling back to now when absent."""

    if not value:
        return dt_util.utcnow()
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_utc(parsed)


class HikvisionAccessCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the terminal for access events and hold the last authentication."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: HikvisionAccessClient,
        device_info: dict[str, Any],
    ) -> None:
        """Initialize the coordinator."""

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=POLL_INTERVAL,
        )
        self.entry = entry
        self.client = client
        self.device_info = device_info
        self.serial_no: str = device_info.get("serialNumber") or entry.entry_id
        self.last_event: AccessEvent | None = None
        self._seen: set[str] = set()
        self._last_poll: dt.datetime | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch access events since the previous poll."""

        now = dt_util.utcnow()
        start = self._last_poll or (now - dt.timedelta(seconds=ACS_EVENT_INITIAL_LOOKBACK_SECONDS))

        try:
            body = await self.client.get_access_events(start, now, max_results=ACS_EVENT_PAGE_SIZE)
        except HikvisionAccessAuthError as ex:
            raise UpdateFailed(str(ex)) from ex
        except HikvisionAccessError as ex:
            raise UpdateFailed(str(ex)) from ex

        self._last_poll = now

        info = body.get("AcsEvent", {})
        events = info.get("InfoList") or []
        if isinstance(events, dict):
            # A single match is returned as an object, not a list.
            events = [events]

        for raw in events:
            event = self._build_event(raw)
            if event is None:
                continue
            if event.unique_id in self._seen:
                continue
            self._seen.add(event.unique_id)
            self.last_event = event
            self.hass.bus.async_fire(EVENT_TYPE_ACCESS, self._event_payload(event))

        # Keep the dedup set bounded on a long running instance.
        if len(self._seen) > 500:
            self._seen = set(list(self._seen)[-250:])

        return {"last_event": self.last_event, "count": len(events), "updated_at": now}

    def _build_event(self, raw: dict[str, Any]) -> AccessEvent | None:
        """Turn one ISAPI event into an AccessEvent, ignoring non-access entries."""

        try:
            major = int(raw.get("major", 0))
            minor = int(raw.get("minor", 0))
        except (TypeError, ValueError):
            return None

        if major != ACS_EVENT_MAJOR:
            return None

        return AccessEvent(
            serial_no=self.serial_no,
            time=_parse_time(raw.get("time")),
            name=raw.get("name") or None,
            employee_no=raw.get("employeeNoString") or raw.get("employeeNo") or None,
            card_no=raw.get("cardNo") or None,
            door_no=raw.get("doorNo"),
            major=major,
            minor=minor,
            event_id=raw.get("eventId") or raw.get("serialNo"),
        )

    def _event_payload(self, event: AccessEvent) -> dict[str, Any]:
        """Payload fired on the HA event bus."""

        return {
            "device_id": self.serial_no,
            "name": event.name,
            "employee_no": event.employee_no,
            "card_no": event.card_no,
            "door_no": event.door_no,
            "time": event.time.isoformat(),
            "minor": event.minor,
        }

    @property
    def is_entry_granted(self) -> bool:
        """Whether the last event was a successful authentication."""

        return self.last_event is not None and self.last_event.minor == ACS_EVENT_MINOR_SUCCESS
