# Repository notes

## What this is

`hikvision_access` is a Home Assistant custom integration for Hikvision access control
terminals (door stations), talking to the device over ISAPI. Reference device:
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
- `sensor.py` — `last_access_time`, the who-entered-and-when timestamp sensor (its state
  is a timestamp, so the UI shows it relatively; `date`, `time` and `datetime` attributes
  carry the exact values), `last_access_person`, whose **state is the name** of the last
  person (the binary sensor can only read `on`/`off` and HA labels those itself, so a name
  cannot live there), and `persons_enrolled`, the person count that does not depend on the
  event permission.
- `button.py` — `open_door_N` per door, so a door is reachable from a dashboard, not only the
  gear menu, plus `refresh_people` to re-probe the device without a restart. Any user-facing
  capability must have an entity; the gear menu is not the only UI.
- `services.py` / `services.yaml` — YAML equivalents (`create_visitor`, `delete_user`,
  `open_door`).
- `diagnostics.py` — redacted report; probes endpoints directly when setup failed (there
  is no coordinator then).

## Device facts that matter

- **The terminal accepts each digest nonce only once.** httpx caches the digest challenge
  and reuses it (encode/httpx PR #2463), so from the second request on the client sends a
  spent nonce. The device refuses with a bare 401 that advertises **no** fresh
  `WWW-Authenticate`, so httpx cannot re-negotiate; the request just fails. This looked
  exactly like a missing permission and shipped wrong guidance for weeks (`System/deviceInfo`
  passes, every `AccessControl/*` call 401s, even for `admin`). `request()` now re-negotiates
  and retries once on a 401 before the permission logic runs, and only when `_auth_verified`
  is set so a wrong password does not add login attempts. Verify any similar 401 with a plain
  `curl --digest` against the device: if curl returns 200 with the same credentials, it is
  this bug, not a permission.
- A 401 on `AccessControl/AcsEvent` **after** the nonce fix really is a permission problem:
  the account lacks `Remote: Log Search / Interrogate Working Status`. But confirm it with
  curl first — do not trust the status code alone.
- The two permissions map to different features, so name both when a user is stuck:
  `Remote: Parameters Settings` covers `/AccessControl/UserInfo/*` (the person list, the
  person count, add/edit/delete), `Remote: Log Search` covers `/AccessControl/AcsEvent`
  (the last-access sensor and binary sensor). A 401 on UserInfo is why "Edit person" and
  "Delete person" abort and "Add person" is refused while everything else works.
- **Access events are not `minor=75`.** The ISAPI guide calls 75 "face authentication
  success", but the reference terminal never reports it: it numbers a **card read as
  `minor=1`** (with `name`, `employeeNoString`, `cardNo`, `currentVerifyMode`), and reports
  the door open/close pair as `minor=21`/`22` with **no** identity. A `minor=75` query answers
  `NO MATCH` while real events exist, which is why the last-access entities looked broken.
  The poll therefore asks for `minor=0`, which this firmware supports and means "every minor
  type", and `_build_event` keeps only the events carrying a name, an employee number or a
  card. Do not narrow this back to a per-method code: firmware disagrees on them.
  `AccessControl/AcsEvent/capabilities` lists the minors a device accepts, and the device
  **rejects a query with no `minor` at all** (`MessageParametersLack`).
- A successful access is shown in the device page's Activity log through `logbook.py`. It
  reads its strings from `translations/*.json` under `logbook.*` (and `logbook.method.*` for
  the verify mode), because the logbook has no entity translation to fall back on. The
  `after_dependencies` in `manifest.json` names `logbook` so the platform is imported when
  the logbook is loaded.
- The reference firmware reports `maxResults` up to 30 on `AcsEvent`; ask for no more.
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
- An optional entity field uses `OptionalEntitySelector` (`entity_selector.py`), not the
  stock `EntitySelector`: the stock one rejects an empty string, so a settings page with
  an untouched optional entity field fails to save with "Entity is neither a valid entity
  ID nor a valid UUID" and writes nothing at all.
- Never write `[%key:common::...%]` in this integration's translations. That syntax is expanded
  by `script.translations` while Core is built; a custom component is loaded from disk as-is, so
  the reference reaches the browser untouched and the UI shows it literally (this shipped for
  the config-flow field labels in 0.6.1). Copy the English text in, or translate it.
