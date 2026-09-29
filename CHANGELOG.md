# Changelog

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
