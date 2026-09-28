# Changelog

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
