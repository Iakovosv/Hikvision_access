# Copyright (c) 2026 Iakovosv. All rights reserved.
# Personal use only. Commercial use requires written permission.
# See LICENSE and COMMERCIAL.md. Redistribution prohibited.
"""Coordinator polling access control events."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ACS_EVENT_INITIAL_LOOKBACK_SECONDS,
    ACS_EVENT_MAJOR,
    ACS_EVENT_SUCCESS_MINORS,
    DOMAIN,
    EVENT_DEDUP_WINDOW_SECONDS,
    EVENT_TYPE_ACCESS,
    POLL_INTERVAL_DEGRADED_SECONDS,
    POLL_INTERVAL_SECONDS,
)
from .isapi import (
    HikvisionAccessAuthError,
    HikvisionAccessClient,
    HikvisionAccessError,
    HikvisionAccessForbiddenError,
    HikvisionAccessLockedError,
)

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL = dt.timedelta(seconds=POLL_INTERVAL_SECONDS)
POLL_INTERVAL_DEGRADED = dt.timedelta(seconds=POLL_INTERVAL_DEGRADED_SECONDS)


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
    verify_mode: str | None = None

    @property
    def granted(self) -> bool:
        """Whether the event is a granted authentication.

        Firmware numbers the success codes differently (the reference terminal reports a
        card read as `minor=1` where the guide says `38`), so a present card number counts
        as a grant on its own, and the documented success codes are accepted as well.
        """

        return bool(self.card_no) or self.minor in ACS_EVENT_SUCCESS_MINORS

    @property
    def method(self) -> str:
        """Return the verify mode the device reported for this access.

        This is the raw mode key (e.g. `cardOrFpOrPw`), which the logbook translates. The
        device reports the combination it accepts rather than the method actually used, so
        the card number is what tells whether a card was involved.
        """

        return self.verify_mode or "access"

    @property
    def unique_id(self) -> str:
        """Stable id used for deduplication.

        The device reports seconds but may repeat an event with a slightly shifted
        timestamp, so events are bucketed into a fixed window instead of comparing
        the exact instant.
        """

        bucket = int(self.time.timestamp()) // EVENT_DEDUP_WINDOW_SECONDS
        return f"{self.serial_no}_{bucket}_{self.employee_no}_{self.card_no}_{self.minor}"


def _parse_time(value: str | None) -> dt.datetime:
    """Parse an ISAPI timestamp, falling back to now when absent.

    A timestamp without an offset is the device's own local clock, which is assumed
    to match this Home Assistant instance.
    """

    if not value:
        return dt_util.utcnow()
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
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
            config_entry=entry,
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
        #: The last client error before it was wrapped for the coordinator. Setup uses it
        #: to tell a permission problem from a transport failure and choose the right
        #: config entry error.
        self.last_client_error: HikvisionAccessError | None = None
        #: True when the last poll was refused because the account may not read events.
        #: Setup keeps the entry loaded in that case, and the poll slows down until the
        #: permission is granted.
        self.event_access_denied = False
        #: Door numbers the terminal controls, filled on the first refresh. Defaults to a
        #: single door so a terminal that cannot be asked is never shown doors it lacks.
        self.door_numbers: list[int] = [1]
        #: Number of persons enrolled, or None when the account cannot read the count.
        self.persons_enrolled: int | None = None
        self._device_probed = False

    async def async_probe(self) -> None:
        """Read the door count and the person count, tolerating a refusal of either."""

        try:
            count = await self.client.get_door_count()
        except HikvisionAccessError as ex:
            _LOGGER.debug("Could not read the door count from %s: %s", self.serial_no, ex)
        else:
            if count:
                self.door_numbers = list(range(1, count + 1))

        try:
            self.persons_enrolled = await self.client.get_person_count()
        except HikvisionAccessError as ex:
            _LOGGER.debug("Could not read the person count from %s: %s", self.serial_no, ex)
        self._device_probed = True

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch access events since the previous poll."""

        # Ask the terminal about itself once, before touching events. Both calls are best
        # effort and independent of the event permission, so a terminal whose account may
        # not read events still reports its doors and its person count.
        if not self._device_probed:
            await self.async_probe()

        now = dt_util.utcnow()
        start = self._last_poll or (now - dt.timedelta(seconds=ACS_EVENT_INITIAL_LOOKBACK_SECONDS))

        try:
            events = await self.client.get_all_access_events(start, now)
        except HikvisionAccessLockedError as ex:
            # The account is temporarily blocked; retrying immediately would only extend
            # the lockout, so it is reported as an update failure rather than asking for
            # credentials that are in fact correct.
            self.last_client_error = ex
            self._poll_interval_update(POLL_INTERVAL_DEGRADED)
            raise UpdateFailed(str(ex)) from ex
        except HikvisionAccessAuthError as ex:
            self.last_client_error = ex
            raise ConfigEntryAuthFailed(str(ex)) from ex
        except HikvisionAccessForbiddenError as ex:
            # 401/403 from an authenticated account is a permission problem. Asking for a
            # new password would loop forever with the right one, and raising UpdateFailed
            # would log an ERROR on every poll. Instead the poll slows down, the entities
            # go unavailable and every other feature keeps working. The permission is
            # checked again on the next poll, so granting it needs no restart.
            self.last_client_error = ex
            if not self.event_access_denied:
                _LOGGER.warning("Access events are disabled for %s: %s", self.serial_no, ex)
            self.event_access_denied = True
            self._poll_interval_update(POLL_INTERVAL_DEGRADED)
            return self.data or {}                    # noqa: RET504 - keep the last data
        except HikvisionAccessError as ex:
            self.last_client_error = ex
            raise UpdateFailed(str(ex)) from ex

        self.last_client_error = None
        if self.event_access_denied:
            _LOGGER.info("Access events are working again for %s", self.serial_no)
        self.event_access_denied = False
        self._poll_interval_update(POLL_INTERVAL)
        self._last_poll = now

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

    def _poll_interval_update(self, interval: dt.timedelta) -> None:
        """Change the poll pace without waking the coordinator."""

        if self.update_interval != interval:
            self.update_interval = interval

    def _build_event(self, raw: dict[str, Any]) -> AccessEvent | None:
        """Turn one ISAPI event into an AccessEvent, ignoring non-access entries.

        `minor=0` returns every access event, including the door-state pairs (open/close)
        that carry no identity. Only entries that name a person, an employee number or a
        card are kept, so the last-access entities always answer "who", and a real
        authentication is never mistaken for the door simply opening.
        """

        try:
            major = int(raw.get("major", 0))
            minor = int(raw.get("minor", 0))
        except (TypeError, ValueError):
            return None

        if major != ACS_EVENT_MAJOR:
            return None

        name = raw.get("name") or None
        employee_no = raw.get("employeeNoString") or raw.get("employeeNo") or None
        card_no = raw.get("cardNo") or None
        if not (name or employee_no or card_no):
            return None

        return AccessEvent(
            serial_no=self.serial_no,
            time=_parse_time(raw.get("time")),
            name=name,
            employee_no=employee_no,
            card_no=card_no,
            door_no=raw.get("doorNo"),
            major=major,
            minor=minor,
            event_id=raw.get("eventId") or raw.get("serialNo"),
            verify_mode=raw.get("currentVerifyMode") or None,
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
            "method": event.method,
            "granted": event.granted,
        }

    @property
    def is_entry_granted(self) -> bool:
        """Whether the last event was a successful authentication."""

        return self.last_event is not None and self.last_event.granted
