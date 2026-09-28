"""Hikvision ISAPI access control client."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import httpx

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

    async def _detect_auth(self) -> None:
        """Negotiate basic or digest authentication."""

        response = await self._session.get(f"{self.host}/ISAPI/System/deviceInfo", auth=None)
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

        if self._auth is None:
            await self._detect_auth()

        url = f"{self.host}/ISAPI/{path}"
        response = await self._session.request(method, url, data=data, auth=self._auth, headers=headers)

        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise HikvisionAccessAuthError(f"Unauthorized request {url}, check username and password")
        if response.status_code == httpx.codes.FORBIDDEN:
            raise HikvisionAccessForbiddenError(f"Forbidden request {url}, check user permissions")
        response.raise_for_status()

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
                "beginTime": _local_time(begin_time),
                "endTime": _local_time(end_time),
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
    import json

    return json.dumps(payload)


def _isapi_time(value: dt.datetime) -> str:
    """Format a datetime the way AcsEventCond expects it (local time, no offset)."""

    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _local_time(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")
