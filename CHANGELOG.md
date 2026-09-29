# Changelog

## 0.6.1

- Fixed a raw `insufficient_permission` shown at the top of "Add person": the key was added to
  the config-flow errors in 0.6.0, but the options flow reads its errors from `options.error`.
  Both tables now carry it.
- The 401 message now names the one permission the refused endpoint needs instead of always
  listing both. `AccessControl/UserInfo/*` asks for Remote: Parameters Settings and
  `AccessControl/AcsEvent` for Remote: Log Search, so the user is not sent looking for a
  setting that is already enabled.
- `tests/test_translations.py` now reads the visible keys back from the flow source and asserts
  every `reason=` and `errors["base"] =` literal resolves in every shipped language. The old
  test only listed the aborts by hand, which is why `insufficient_permission` shipped raw.

## 0.6.0

- Added a Greek translation (`translations/el.json`). Before this, a Home Assistant running in
  Greek showed the raw reason for a refused person list ("cannot_list") instead of the sentence
  that names the missing device permission.
- "Add person" now distinguishes a refused request from a missing permission: a 401 from the
  device shows "The device refused the request. Check the user permissions." rather than a
  generic failure.
- Diagnostics probe the person list, the person count and the door count as well, so the report
  shows exactly which endpoint the device account may use.
- `tests/test_translations.py` fails the suite if a shipped language misses a key or drifts a
  placeholder from English, which is what silently produced the raw "cannot_list".

## 0.5.0

- Added `sensor.persons_enrolled` — how many people are enrolled on the terminal. Read from
  `AccessControl/UserInfo/Count`, falling back to the search total on older firmware. It does
  not need the event permission, so it also appears on a terminal whose account may not read
  access events. When the account cannot read the count, the sensor is empty with the reason
  in its attributes.
- Added `button.refresh_people` — re-reads the door count and the person count from the
  terminal. Press it after granting the account its permissions instead of restarting. It can
  also be called from an automation.
- The door count and the person count are read once at setup, before the event poll, so a
  device whose events are refused still reports them.
- Diagnostics report `persons_enrolled`.

Note on door open/closed: a real door status is not available over ISAPI unless the terminal
has a wired magnetic contact, and even then it arrives as an alarm input. It is deliberately
not exposed rather than guessed.

## 0.4.1

- Fixed: the door buttons were a fixed pair. A one-door terminal showed a second door that
  does nothing. The number of doors is now asked from the device
  (`AccessControl/Door/Count`, falling back to `System/capabilities`) and one button is added
  per door. A device that will not say gets a single door, not a guess.
- Fixed: the `cannot_list` message on Edit person and Delete person hid the reason. It now
  shows the device's own answer, so a 401 permission problem reads as such instead of a
  bare `cannot_list`.
- The door picker in Add/Edit person is limited to the doors the terminal reports.
- Diagnostics report `door_numbers`.

## 0.4.0

- The device page now has the entities that were missing, instead of everything hiding behind
  the gear menu:
  - `sensor.last_access_time` — a timestamp entity for the last authentication, with the name,
    employee number, card number and door as attributes. Answers "who entered and when".
  - `button.open_door_1` and `button.open_door_2` — unlock a door from a dashboard or an
    automation.
- `Edit person` shows a single form with everything about the person, including the card. The
  card field is prefilled with the current card, so submitting the form untouched changes
  nothing; typing a new number replaces the card. The separate `Manage card` menu entry is gone.
- Fixed: `Edit person` and the card menu raised an exception and showed nothing when the
  device refused the person list (an account without `Remote: Parameters Settings` answers
  401 on `UserInfo/Search`). The flow now explains the missing permission.
- Fixed: an invalid validity window on the edit form raised out of the flow instead of showing
  a form error.
- A door number that cannot be parsed no longer raises; it falls back to door 1.

## 0.3.1

- A missing `Remote: Log Search` permission no longer fails setup. Before, if the account
  could not read access events, the whole entry went to `Setup failed` and the `Configure`
  button (person management), the services, diagnostics and the door control were all
  unreachable even though none of them need access events.
  Now the entry loads, the account permission is reported once as a warning, the
  last-access sensor shows as unavailable with the reason, and the event poll slows to
  every 5 minutes. Granting the permission on the device recovers automatically on the
  next poll, with no restart.
- A transport error (device unreachable, HTTP 500) still keeps retrying, and a wrong
  password still asks for reauthentication, so those cases are unchanged.

## 0.3.0

- Manage people from the Home Assistant UI. The integration's `Configure` button now opens a
  person management menu: add a person, edit one, delete one, change a card, or open a door.
  No YAML service call is needed.
  - `Add person` covers employee ID, name, gender, person type, PIN, card and the validity
    window. An empty employee ID is allocated automatically and an empty PIN is generated.
  - `Edit person` lists the people enrolled on the device and prefills the form with what the
    device holds, including the read-only details (person type, gender, validity, card and
    fingerprint counts, and the visitor visit counters when the device reports them).
    The PIN is only changed when a new one is entered.
  - `Delete person` asks for confirmation first.
  - `Manage card` adds a card number, or removes the person's cards when submitted empty.
- `create_visitor` gained the `gender`, `user_type` and `card_no` fields.
- The ISAPI client gained `modify_person`, `get_person`, `get_person_count`, `set_card` and
  `delete_card`.

## 0.2.2

- Diagnostics now run the endpoint probes even when setup failed. That is the case where
  they matter most: with the integration not set up there is no coordinator, and the
  previous version returned only the entry fields, so the report could not say whether
  `AccessControl/AcsEvent` was refused for a permission, a lockout or a wrong password.

## 0.2.1

- Stop reporting a permission problem as a wrong password. ISAPI answers 401 both when
  the password is wrong and when the account may not read access events, so the two are
  now told apart: a valid account that is refused an endpoint raises a permission error
  and the entry stays loaded instead of looping through reauthentication with the
  correct password.
- Detect the device lockout that follows repeated failed logins (its 401 body carries
  `lockStatus`/`unlockTime`) and report it as a temporary condition instead of asking
  for credentials.
- Add diagnostics, with host and credentials redacted, that probe both `System/deviceInfo`
  and `AccessControl/AcsEvent` so a support report shows which call the account may use.

## 0.2.0

- Follow AcsEvent pagination so busy periods no longer drop entries.
- Convert event and validity timestamps to local time, and warn when the device clock
  drifts from Home Assistant by more than a minute.
- Negotiate authentication once under a lock, so a wrong password cannot trip the
  device login lockout.
- Allocate visitor numbers by checking who is already enrolled, so an existing person
  is never overwritten.
- Turn device HTTP and connection failures into proper update errors instead of raising
  raw httpx exceptions.
- Deduplicate events inside a time window, so a repeat across two polls fires once.
- Reject a visitor whose end time is not after its start time.

## 0.1.0

- Initial release: config flow, access event polling, `last_access` binary sensor,
  `create_visitor`, `delete_user` and `open_door` services.
