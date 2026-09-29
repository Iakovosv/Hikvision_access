# Changelog

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
