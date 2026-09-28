"""Hikvision ISAPI access control client."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Any

import httpx
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


class HikvisionAccessError(Exception):
    """Base error for the access control client."""


class HikvisionAccessAuthError(HikvisionAccessError):
    """Authentication failed."""


class HikvisionAccessForbiddenError(HikvisionAccessError):
    """The device rejected the request, usually a permission problem."""


class HikvisionAccessClient:
    """Small async ISAPI client for Hikvision access control terminals.

    Only the endpoints needed for reading access events and managing persons are
    implemented. Authentication is negotiated once from the WWW-Authenticate header.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        session: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the client."""

        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._session = session
        self._auth: httpx.Auth | None = None
        self._auth_lock = asyncio.Lock()

    async def _detect_auth(self) -> None:
        """Negotiate basic or digest authentication once.

        The device counts every failed authentication and temporarily refuses further
        attempts, so the negotiation is done a single time and never per request.
        """

        if self._auth is not None:
            return
        async with self._auth_lock:
            if self._auth is not None:
                return
            try:
                response = await self._session.get(f"{self.host}/ISAPI/System/deviceInfo", auth=None)
            except httpx.HTTPError as ex:
                raise HikvisionAccessError(f"Cannot reach {self.host}: {ex}") from ex
            header = response.headers.get("WWW-Authenticate", "")
            if "Digest" in header:
                self._auth = httpx.DigestAuth(self.username, self.password)
            elif "Basic" in header:
                self._auth = httpx.BasicAuth(self.username, self.password)
            else:
                raise HikvisionAccessAuthError("Device did not advertise an authentication method")

    async def request(
        self,
        method: str,
        path: str,
        data: str | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Send an ISAPI request and return the parsed JSON body."""

        await self._detect_auth()

        url = f"{self.host}/ISAPI/{path}"
        try:
            response = await self._session.request(method, url, data=data, auth=self._auth, headers=headers)
        except httpx.HTTPError as ex:
            raise HikvisionAccessError(f"Cannot reach {url}: {ex}") from ex

        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise HikvisionAccessAuthError(f"Unauthorized request {url}, check username and password")
        if response.status_code == httpx.codes.FORBIDDEN:
            raise HikvisionAccessForbiddenError(f"Forbidden request {url}, check user permissions")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as ex:
            raise HikvisionAccessError(f"Device returned {response.status_code} for {url}") from ex

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            # Command style endpoints answer with XML; the caller only needs success.
            return {"raw": response.text}

    async def get_device_info(self) -> dict[str, Any]:
        """Return DeviceInfo from the device."""

        body = await self.request("GET", "System/deviceInfo")
        return body.get("DeviceInfo", {})

    async def get_device_time(self) -> dt.datetime | None:
        """Return the device clock, used to detect a clock mismatch.

        The device filters events by its own clock; if it drifts away from Home
        Assistant the event window silently returns nothing.
        """

        body = await self.request("GET", "System/time")
        value = body.get("Time", {}).get("localTime")
        if not value:
            return None
        try:
            return _parse_device_time(value)
        except ValueError:
            return None

    async def get_capabilities(self) -> dict[str, Any]:
        """Return the access control capabilities."""

        return await self.request("GET", "System/capabilities")

    async def get_access_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        position: int = 0,
        max_results: int = 30,
    ) -> dict[str, Any]:
        """Return access events in the given time window.

        `major=5` selects access events, `minor=75` a successful authentication.
        The device compares these timestamps against its own clock, so the values
        are converted to this Home Assistant instance's local time.
        """

        payload = {
            "AcsEventCond": {
                "searchID": "hikvision-access",
                "searchResultPosition": position,
                "maxResults": max_results,
                "major": 5,
                "minor": 75,
                "startTime": _isapi_time(start),
                "endTime": _isapi_time(end),
            }
        }
        return await self.request(
            "POST",
            "AccessControl/AcsEvent?format=json",
            data=_json(payload),
            headers={"Content-Type": "application/json"},
        )

    async def get_all_access_events(self, start: dt.datetime, end: dt.datetime) -> list[dict[str, Any]]:
        """Return every access event in the window, following pagination.

        A single response is capped by the device, so keep asking for the next page
        until the device reports that there is no more data.
        """

        events: list[dict[str, Any]] = []
        position = 0
        while True:
            body = await self.get_access_events(start, end, position=position)
            info = body.get("AcsEvent", {})
            page = info.get("InfoList") or []
            if isinstance(page, dict):
                page = [page]
            events.extend(page)

            status = info.get("responseStatusStrg")
            if status != "MORE" or not page:
                break
            position += len(page)

        return events

    async def get_users(self, position: int = 0, max_results: int = 30) -> dict[str, Any]:
        """Return persons enrolled on the device."""

        payload = {
            "UserInfoSearchCond": {
                "searchID": "hikvision-access",
                "searchResultPosition": position,
                "maxResults": max_results,
            }
        }
        return await self.request(
            "POST",
            "AccessControl/UserInfo/Search?format=json",
            data=_json(payload),
            headers={"Content-Type": "application/json"},
        )

    async def create_person(
        self,
        employee_no: str,
        name: str,
        begin_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        pin: str | None = None,
        door_no: int = 1,
    ) -> dict[str, Any]:
        """Create or update a person, optionally with a PIN and a validity window."""

        user_info: dict[str, Any] = {
            "employeeNo": str(employee_no),
            "name": name,
            "userType": "normal",
            "doorRight": "1",
            "RightPlan": [{"doorNo": door_no, "planTemplateNo": "1"}],
        }
        if pin:
            user_info["password"] = str(pin)
        if begin_time and end_time:
            user_info["Valid"] = {
                "enable": True,
                "beginTime": _isapi_time(begin_time),
                "endTime": _isapi_time(end_time),
                "timeType": "local",
            }

        return await self.request(
            "PUT",
            "AccessControl/UserInfo/Record?format=json",
            data=_json({"UserInfo": user_info}),
            headers={"Content-Type": "application/json"},
        )

    async def delete_person(self, employee_no: str) -> dict[str, Any]:
        """Delete a person by employee number."""

        payload = {"UserInfoDelCond": {"EmployeeNoList": [{"employeeNo": str(employee_no)}]}}
        return await self.request(
            "PUT",
            "AccessControl/UserInfo/Delete?format=json",
            data=_json(payload),
            headers={"Content-Type": "application/json"},
        )

    def event_picture_url(self, event_id: str) -> str:
        """Return the URL of the snapshot attached to an access event."""

        return f"{self.host}/ISAPI/AccessControl/AcsEvent?format=json&picType=url&eventId={event_id}"


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def _isapi_time(value: dt.datetime) -> str:
    """Format a datetime the way the device expects it.

    ISAPI timestamps carry no offset and the device matches them against its own
    clock, so anything we send is converted to this instance's local time first.
    """

    if value.tzinfo is not None:
        value = dt_util.as_local(value)
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_device_time(value: str) -> dt.datetime:
    """Parse the device clock, which is reported without an offset."""

    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return parsed
