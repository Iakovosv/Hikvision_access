# Repository notes

## What this is

`hikvision_access` is a Home Assistant custom integration for Hikvision access control
terminals (door stations), talking to the device over ISAPI. It is the sibling of the
`Iakovosv/Hikvision_next` integration, which covers cameras and NVRs. Reference device:
DS-K1T805MBFWX, firmware V1.9.1 build 240909.

## Build and test

- Python 3.14 is required by `pytest-homeassistant-custom-component>=0.13.363`.
  A ready venv lives at `.venv`.
- Run the suite with `.venv/bin/python -m pytest -q`.
- Runtime deps: httpx, async-timeout. Test deps: pytest, pytest-asyncio, pytest-cov,
  pytest-homeassistant-custom-component. Managed with `uv`.

## Architecture

- `isapi.py` — async ISAPI client. Digest/basic auth, lockout and permission errors are
  told apart from a wrong password via `_auth_verified`. Person calls: `create_person`
  (UserInfo/Record), `modify_person` (UserInfo/Modify), `delete_person`,
  `get_users`, `get_person`, `get_person_count`, `set_card`, `delete_card`, `open_door`,
  `get_door_count`.
- `coordinator.py` — polls `AcsEvent` and fires `hikvision_access_event`. Holds
  `door_numbers`, filled at setup from the device; defaults to `[1]` so a terminal that
  cannot be asked is never shown doors it lacks.
- `config_flow.py` — setup, reconfigure, reauth. Exposes the options flow via
  `async_get_options_flow`.
- `options_flow.py` — **person management UI** (Configure button). Menu: add, edit, delete,
  open_door. Talks to the device through the coordinator client; stores no options on the
  entry. Everything about a person, including the card, lives in the edit form. Every device
  read is guarded: a 401 turns into an abort with a reason (`cannot_list`), never an
  exception out of the flow, because an uncaught error shows the user a bare "unknown error".
- `sensor.py` — `last_access_time`, the who-entered-and-when timestamp sensor, and
  `persons_enrolled`, the person count that does not depend on the event permission.
- `button.py` — `open_door_N` per door, so a door is reachable from a dashboard, not only the
  gear menu, plus `refresh_people` to re-probe the device without a restart. Any user-facing
  capability must have an entity; the gear menu is not the only UI.
- `services.py` / `services.yaml` — YAML equivalents (`create_visitor`, `delete_user`,
  `open_door`).
- `diagnostics.py` — redacted report; probes endpoints directly when setup failed (there
  is no coordinator then).

## Device facts that matter

- A 401 on `AccessControl/AcsEvent` after a successful `System/deviceInfo` means the
  device account lacks `Remote: Log Search / Interrogate Working Status`. It is not a
  password problem. Also enable `Remote: Parameters Settings`.
- The two permissions map to different features, so name both when a user is stuck:
  `Remote: Parameters Settings` covers `/AccessControl/UserInfo/*` (the person list, the
  person count, add/edit/delete), `Remote: Log Search` covers `/AccessControl/AcsEvent`
  (the last-access sensor and binary sensor). A 401 on UserInfo is why "Edit person" and
  "Delete person" abort and "Add person" is refused while everything else works.
- A missing event permission must never fail setup. Only the last-access sensor needs
  access events; person management, the services, diagnostics and the door control do
  not. `coordinator.event_access_denied` carries the state, the poll degrades to
  `POLL_INTERVAL_DEGRADED_SECONDS`, the sensor goes unavailable with a reason, and the
  permission is re-checked on every poll so it recovers without a restart. Never raise
  `ConfigEntryError` for this: it hides the whole UI behind one permission.
- `Calling Services` / NULL value: HA calls a service with an empty `{}` when a handler
  edits and resubmits without touching the PIN field — treat empty PIN as "keep".
- The reference firmware does not report visitor visit counters over ISAPI. Read them by
  name when present (`VISIT_TIMES_*_KEYS` in `const.py`); never write a guessed field name.
- Fingerprints cannot be enrolled remotely over ISAPI. Face needs a multipart upload to
  `Intelligent/FDLib/FaceDataRecord`; the target device has no camera, so it is skipped.
- `UserInfo Search` with `EmployeeNoList` is ignored by some firmware; `get_person` falls
  back to a full paged scan.
- Device probing (door count, person count) must run before the event poll and must not
  depend on the event permission: a terminal whose account may read people but not events
  still has to be described correctly. An entity that only needed the gear menu must gain a
  matching entity; `refresh_people` exists so a permission change needs no restart.
- The number of doors differs by model. Ask `AccessControl/Door/Count`, else walk
  `System/capabilities`, and expose only what is reported; some terminals are single door.
  A 404 on an endpoint is a normal "not supported", not an error to surface.

## Conventions

- Keep changes minimal and preserve working behaviour.
- Style: short docstrings, comments only for non-obvious invariants.
- Every change: bump `manifest.json` + `CHANGELOG.md`, run the suite, then PR + release.
- Tests patch the real client through the conftest transport handler; no mocks of the
  integration's own code.
- Every user-facing string lives in `translations/en.json`, and `strings.json` stays a copy
  of it. When a non-English locale is added, it must cover every English key with the same
  placeholders: Home Assistant shows the raw key (e.g. a bare `cannot_list`) when a
  translation is missing, and silently drops a localized string whose placeholders differ
  from the English one. `tests/test_translations.py` guards both, per language.
