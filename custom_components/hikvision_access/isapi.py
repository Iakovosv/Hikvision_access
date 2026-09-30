# Copyright (c) 2026 Iakovosv. All rights reserved.
# Personal use only. Commercial use requires written permission.
# See LICENSE and COMMERCIAL.md. Redistribution prohibited.
"""Hikvision ISAPI access control client."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Any, Final

import httpx
from homeassistant.util import dt as dt_util

from .const import ACS_EVENT_MAJOR

_LOGGER = logging.getLogger(__name__)

# The door commands the terminal accepts on the RemoteControl endpoint.
DOOR_COMMANDS: Final = ("open", "close", "alwaysOpen", "alwaysClose", "resume")


def door_command_path(door_no: int) -> str:
    """Return the RemoteControl path for a door.

    Both the button and the service build their request here, so the door number cannot
    drift apart between the two.
    """

    return f"AccessControl/RemoteControl/door/{door_no}"


def door_command_body(command: str = "open") -> str:
    """Return the XML body for a door command."""

    return f"<RemoteControlDoor><cmd>{command}</cmd></RemoteControlDoor>"



class HikvisionAccessError(Exception):
    """Base error for the access control client."""


class HikvisionAccessAuthError(HikvisionAccessError):
    """Authentication failed."""


class HikvisionAccessForbiddenError(HikvisionAccessError):
    """The device rejected the request, usually a permission problem."""


class HikvisionAccessLockedError(HikvisionAccessAuthError):
    """The device temporarily refuses authentication after repeated failures."""


class HikvisionAccessPermissionError(HikvisionAccessForbiddenError):
    """The credentials are valid but the account may not use this endpoint.

    ISAPI answers with 401, not 403, when an authenticated account is missing a
    permission, so a bare status code cannot be read as a credential problem.
    """


#: ISAPI groups its endpoints under permissions the terminal grants per user. Naming the
#: right one in a 401 avoids sending the user to enable both when only one is missing.
_PERMISSION_HINTS: tuple[tuple[str, str], ...] = (
    ("AccessControl/AcsEvent", "Remote: Log Search"),
    ("AccessControl/UserInfo", "Remote: Parameters Settings"),
    ("AccessControl/Door", "Remote: Parameters Settings"),
)


def _permission_hint(url: str) -> str:
    """Name the device permission that covers an endpoint."""

    for fragment, permission in _PERMISSION_HINTS:
        if fragment in url:
            return permission
    return "Remote: Log Search and Remote: Parameters Settings"


class HikvisionAccessClient:
    """Small async ISAPI client for Hikvision access control terminals.

    Only the endpoints needed for reading access events and managing persons are
    implemented. Authentication is negotiated once from the WWW-Authenticate header.
    """

    #: Names of the lockout fields the device puts in a 401 body when it is refusing
    #: further logins. Sent as XML even when the request asked for JSON.
    LOCKOUT_MARKERS = ("lockStatus", "unlockTime")

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
        self._auth_verified = False

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

    @staticmethod
    def _is_lockout(response: httpx.Response) -> bool:
        """Whether a 401 body says the account is locked out rather than wrong."""

        try:
            text = response.text
        except (httpx.ResponseNotRead, httpx.StreamError):  # pragma: no cover - defensive
            return False
        return any(marker in text for marker in HikvisionAccessClient.LOCKOUT_MARKERS)

    async def _unauthorized_error(self, url: str, response: httpx.Response) -> HikvisionAccessError:
        """Tell a wrong password apart from a valid account without permission.

        ISAPI returns 401 for both, so the status code alone would send the user into
        an endless reauthentication loop with the correct password. The identity is
        confirmed once against System/deviceInfo, which is the endpoint the config flow
        already proved works; after that a lone 401 is read as a permission problem.
        """

        if self._is_lockout(response):
            return HikvisionAccessLockedError(
                "The device locked the account after repeated failed logins. Wait for the "
                "lockout to expire before trying again."
            )

        if self._auth_verified or await self._verify_auth():
            return HikvisionAccessPermissionError(
                f"Authenticated, but the device refused {url} (401). The account is missing a "
                f"permission for this endpoint. On an access terminal, enable {_permission_hint(url)} "
                "for the user."
            )

        return HikvisionAccessAuthError(f"Unauthorized request {url}, check username and password")

    async def _verify_auth(self) -> bool:
        """Check once whether the negotiated credentials are accepted.

        Only called after a 401, so a correct password is never re-tried in a loop and
        a wrong one costs at most one extra attempt.
        """

        if self._auth_verified:
            return True
        if self._session is None:  # pragma: no cover - a client without a session cannot probe
            return False
        try:
            response = await self._session.get(
                f"{self.host}/ISAPI/System/deviceInfo", auth=self._auth, headers=None
            )
        except httpx.HTTPError:  # pragma: no cover - a transport failure is reported elsewhere
            return False
        if response.status_code == httpx.codes.OK:
            self._auth_verified = True
            return True
        return False

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
        response = await self._send(method, url, data, headers)

        if (
            response.status_code == httpx.codes.UNAUTHORIZED
            and self._auth_verified
            and not self._is_lockout(response)
        ):
            # The terminal accepts each digest nonce only once. httpx caches the
            # challenge and reuses it, so a later request carries a spent nonce and the
            # device refuses with a 401 that advertises no fresh challenge; httpx cannot
            # recover on its own. Negotiate a new nonce and send the request once more
            # before reading the 401 as a permission problem. Only done once the
            # credentials are known good, so a wrong password does not add logins.
            await self._refresh_auth()
            response = await self._send(method, url, data, headers)

        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise await self._unauthorized_error(url, response)

        self._auth_verified = True

        if response.status_code == httpx.codes.FORBIDDEN:
            raise HikvisionAccessForbiddenError(f"Forbidden request {url}, check user permissions")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as ex:
            raise HikvisionAccessError(
                f"Device returned {response.status_code} for {method} {url}"
                f" (sent {_masked_payload(data)}; device said {_device_error(response)})"
            ) from ex

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            # Command style endpoints answer with XML; the caller only needs success.
            return {"raw": response.text}

    async def _send(
        self,
        method: str,
        url: str,
        data: str | None,
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        """Send one request, turning a transport failure into a client error."""

        try:
            return await self._session.request(
                method, url, data=data, auth=self._auth, headers=headers
            )
        except httpx.HTTPError as ex:
            raise HikvisionAccessError(f"Cannot reach {url}: {ex}") from ex

    async def _refresh_auth(self) -> None:
        """Re-negotiate the digest challenge after the cached nonce was refused."""

        self._auth = None
        await self._detect_auth()

    async def _write(
        self,
        methods: tuple[str, ...],
        path: str,
        data: str | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Send a write, trying each verb until the device accepts one.

        Firmware disagrees on the verb for the same endpoint: the ISAPI guide documents
        POST for `UserInfo/Record` while other builds accept PUT. A wrong verb is answered
        with `400` and the unambiguous sub-status `methodNotAllowed`, so the alternate verb
        is tried rather than surfacing a failure the user cannot act on.
        """

        for index, method in enumerate(methods):
            try:
                return await self.request(method, path, data=data, headers=headers)
            except HikvisionAccessError as ex:
                if index + 1 == len(methods) or not _is_method_not_allowed(ex):
                    raise
                _LOGGER.debug("Device rejected %s %s; retrying with %s", method, path, methods[index + 1])

        raise HikvisionAccessError(f"No supported method for {path}")  # pragma: no cover

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

    async def get_door_count(self) -> int | None:
        """Return how many doors the terminal controls, or None when it cannot be told.

        Firmware differs: some answer `AccessControl/Door/Count`, others only carry the
        number inside `System/capabilities`. Reporting None instead of a guess keeps the
        caller from inventing doors a one-door terminal does not have.
        """

        try:
            body = await self.request("GET", "AccessControl/Door/Count")
        except HikvisionAccessError:
            pass
        else:
            for key in ("DoorCount", "doorCount", "Door"):
                value = body.get(key)
                if isinstance(value, dict):
                    value = value.get("doorNumber") or value.get("count")
                count = _as_positive_int(value)
                if count:
                    return count

        try:
            capabilities = await self.get_capabilities()
        except HikvisionAccessError:
            return None
        count = _find_door_count(capabilities)
        return count

    async def get_access_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        position: int = 0,
        max_results: int = 30,
        minor: int = 0,
    ) -> dict[str, Any]:
        """Return access events in the given time window.

        `major=5` selects access events and `minor=0` asks for every minor type. The
        device this integration targets rejects a query without a `minor`, and pins its
        successful authentications to `minor=1`, not the documented `minor=75`, so asking
        for everything and picking the entries that carry an identity is the only approach
        that sees every card, fingerprint and face read. The device compares these
        timestamps against its own clock, so the values are converted to this Home
        Assistant instance's local time.
        """

        payload = {
            "AcsEventCond": {
                "searchID": "hikvision-access",
                "searchResultPosition": position,
                "maxResults": max_results,
                "major": ACS_EVENT_MAJOR,
                "minor": minor,
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
        gender: str | None = None,
        user_type: str = "normal",
        card_no: str | None = None,
        max_times: int | None = None,
    ) -> dict[str, Any]:
        """Create or replace a person, optionally with a PIN, a card and a validity window."""

        user_info = self._person_payload(
            employee_no=employee_no,
            name=name,
            begin_time=begin_time,
            end_time=end_time,
            pin=pin,
            door_no=door_no,
            gender=gender,
            user_type=user_type,
            max_times=max_times,
        )

        result = await self._write(
            ("POST", "PUT"),
            "AccessControl/UserInfo/Record?format=json",
            data=_json({"UserInfo": user_info}),
            headers={"Content-Type": "application/json"},
        )

        if card_no:
            await self.set_card(employee_no, card_no)

        return result

    async def modify_person(
        self,
        employee_no: str,
        name: str | None = None,
        begin_time: dt.datetime | None = None,
        end_time: dt.datetime | None = None,
        pin: str | None = None,
        door_no: int = 1,
        gender: str | None = None,
        user_type: str = "normal",
        max_times: int | None = None,
    ) -> dict[str, Any]:
        """Update an existing person without dropping its cards or fingerprints.

        The device's UserInfo/Modify merges the supplied fields into the stored record,
        so credentials that are not part of this call are left alone.
        """

        user_info = self._person_payload(
            employee_no=employee_no,
            name=name,
            begin_time=begin_time,
            end_time=end_time,
            pin=pin,
            door_no=door_no,
            gender=gender,
            user_type=user_type,
            max_times=max_times,
        )
        return await self._write(
            ("PUT", "POST"),
            "AccessControl/UserInfo/Modify?format=json",
            data=_json({"UserInfo": user_info}),
            headers={"Content-Type": "application/json"},
        )

    @staticmethod
    def _person_payload(
        employee_no: str,
        name: str | None,
        begin_time: dt.datetime | None,
        end_time: dt.datetime | None,
        pin: str | None,
        door_no: int,
        gender: str | None,
        user_type: str,
        max_times: int | None = None,
    ) -> dict[str, Any]:
        """Build the UserInfo body shared by create and modify."""

        user_info: dict[str, Any] = {
            "employeeNo": str(employee_no),
            "userType": user_type,
            "doorRight": "1",
            "RightPlan": [{"doorNo": door_no, "planTemplateNo": "1"}],
        }
        if name:
            user_info["name"] = name
        if gender:
            user_info["gender"] = gender
        if pin:
            user_info["password"] = str(pin)
        if begin_time and end_time:
            user_info["Valid"] = {
                "enable": True,
                "beginTime": _isapi_time(begin_time),
                "endTime": _isapi_time(end_time),
                "timeType": "local",
            }
        # How many times the credential may be used. Only sent when the user asked for a
        # limit: firmware that predates the field refuses the whole write when it is
        # present, and a device that supports it reads 0 as "no entry allowed".
        if max_times is not None:
            user_info["maxTimes"] = int(max_times)
        return user_info

    async def get_person(self, employee_no: str) -> dict[str, Any] | None:
        """Return one person by employee number, or None when the device has no match.

        The EmployeeNoList filter is not honoured by every firmware, so a miss falls back
        to paging the enrolment list rather than reporting the person as gone.
        """

        payload = {
            "UserInfoSearchCond": {
                "searchID": "hikvision-access",
                "searchResultPosition": 0,
                "maxResults": 1,
                "EmployeeNoList": [{"employeeNo": str(employee_no)}],
            }
        }
        body = await self.request(
            "POST",
            "AccessControl/UserInfo/Search?format=json",
            data=_json(payload),
            headers={"Content-Type": "application/json"},
        )
        users = body.get("UserInfoSearch", {}).get("UserInfo") or []
        if isinstance(users, dict):
            users = [users]
        if users:
            return users[0]

        position = 0
        while True:
            page_body = await self.get_users(position=position, max_results=100)
            info = page_body.get("UserInfoSearch", {})
            page = info.get("UserInfo") or []
            if isinstance(page, dict):
                page = [page]
            for person in page:
                if str(person.get("employeeNo")) == str(employee_no):
                    return person
            if info.get("responseStatusStrg") != "MORE" or not page:
                return None
            position += len(page)

    async def get_person_count(self) -> int:
        """Return the number of persons enrolled on the device.

        The count endpoint is what readiness checks ask first, so it is used when the
        firmware has it. Older firmware answers the search instead, and the total is
        read from there. Returns 0 when neither answers.
        """

        try:
            body = await self.request("GET", "AccessControl/UserInfo/Count?format=json")
        except HikvisionAccessError:
            body = None
        if body:
            try:
                return int(body.get("UserInfoCount", {}).get("userNumber", 0))
            except (TypeError, ValueError):  # pragma: no cover - defensive against odd firmware
                return 0

        body = await self.request(
            "POST",
            "AccessControl/UserInfo/Search?format=json",
            data=_json({"UserInfoSearchCond": {"searchID": "1", "maxResults": 1, "searchResultPosition": 0}}),
            headers={"Content-Type": "application/json"},
        )
        try:
            return int(body.get("UserInfoSearch", {}).get("totalMatches", 0))
        except (TypeError, ValueError):  # pragma: no cover - defensive against odd firmware
            return 0

    async def set_card(self, employee_no: str, card_no: str) -> dict[str, Any]:
        """Attach a card number to a person."""

        payload = {"CardInfo": {"employeeNo": str(employee_no), "cardNo": str(card_no), "cardType": "normalCard"}}
        return await self._write(
            ("POST", "PUT"),
            "AccessControl/CardInfo/Record?format=json",
            data=_json(payload),
            headers={"Content-Type": "application/json"},
        )

    async def delete_card(self, card_no: str) -> dict[str, Any]:
        """Remove a card by its number."""

        payload = {"CardInfoDelCond": {"CardNoList": [{"cardNo": str(card_no)}]}}
        return await self._write(
            ("PUT", "POST"),
            "AccessControl/CardInfo/Delete?format=json",
            data=_json(payload),
            headers={"Content-Type": "application/json"},
        )

    async def delete_person(self, employee_no: str) -> dict[str, Any]:
        """Delete a person by employee number."""

        payload = {"UserInfoDelCond": {"EmployeeNoList": [{"employeeNo": str(employee_no)}]}}
        return await self._write(
            ("PUT", "POST"),
            "AccessControl/UserInfo/Delete?format=json",
            data=_json(payload),
            headers={"Content-Type": "application/json"},
        )

    async def open_door(self, door_no: int = 1, *, command: str = "open", dry_run: bool = False) -> dict[str, Any]:
        """Send a door command to the terminal.

        With `dry_run` the request is built and logged but never sent, which lets the
        command be verified from a distance without unlocking anything.
        """

        if command not in DOOR_COMMANDS:
            raise HikvisionAccessError(f"Unsupported door command: {command}")

        path = door_command_path(door_no)
        body = door_command_body(command)

        if dry_run:
            _LOGGER.warning(
                "Dry run: would send PUT %s with body %s (nothing was sent to the device)",
                path,
                body,
            )
            return {"dry_run": True, "method": "PUT", "path": path, "body": body}

        return await self.request(
            "PUT",
            path,
            data=body,
            headers={"Content-Type": "application/xml"},
        )

    def event_picture_url(self, event_id: str) -> str:
        """Return the URL of the snapshot attached to an access event."""

        return f"{self.host}/ISAPI/AccessControl/AcsEvent?format=json&picType=url&eventId={event_id}"


def _as_positive_int(value: Any) -> int | None:
    """Return value as a positive int, or None when it is not one."""

    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count > 0 else None


def _find_door_count(capabilities: Any) -> int | None:
    """Look for a door count anywhere in the capabilities tree.

    ISAPI nests capabilities differently between firmware versions, so the tree is walked
    and any key that names a door number is read, rather than assuming one path.
    """

    if isinstance(capabilities, dict):
        for key, value in capabilities.items():
            if key.lower() in ("doornumber", "doorcount", "numberofdoors", "dooramount"):
                count = _as_positive_int(value)
                if count:
                    return count
        for value in capabilities.values():
            count = _find_door_count(value)
            if count:
                return count
    elif isinstance(capabilities, list):
        for item in capabilities:
            count = _find_door_count(item)
            if count:
                return count
    return None


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


#: Fields whose values must never reach the log, whatever the device answered.
_SECRET_FIELDS: Final = ("password", "pin")


def _masked_payload(data: str | None) -> str:
    """Return the request body with credentials blanked, for an error message."""

    if not data:
        return "-"
    try:
        payload = json.loads(data)
    except ValueError:
        return data

    def _mask(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: ("***" if key.lower() in _SECRET_FIELDS else _mask(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [_mask(item) for item in value]
        return value

    return json.dumps(_mask(payload))


def _device_error(response: httpx.Response) -> str:
    """Extract the device's own status code and message from an error reply.

    ISAPI answers a rejected write with a body such as
    `{"statusCode":4,"statusString":"Invalid Operation","subStatusCode":"badJsonContent"}`.
    That sub-status is the only thing that says *why* the write was refused, so it is
    surfaced instead of being swallowed by a bare status line.
    """

    if not response.content:
        return "no detail"
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip().replace("\n", " ")
        return text[:200] if text else "no detail"

    if not isinstance(body, dict):
        return str(body)[:200]
    status = body.get("statusString") or body.get("statusCode") or "unknown"
    sub = body.get("subStatusCode")
    return f"{status} ({sub})" if sub else str(status)


def _is_method_not_allowed(ex: Exception) -> bool:
    """Whether a rejected request was refused because the verb was wrong.

    The client raises a plain error carrying the device sub-status, so the marker is
    matched in the message rather than needing a dedicated exception type.
    """

    return "methodNotAllowed" in str(ex)


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
