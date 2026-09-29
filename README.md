# Hikvision Access Control

A Home Assistant integration for Hikvision access control terminals (door stations / face
terminals), talking to the device directly over ISAPI. No cloud.

It complements the [Hikvision Next](https://github.com/Iakovosv/Hikvision_next) integration,
which covers NVRs and IP cameras. Install both if you have cameras and an access terminal.

## Features

- Discover the terminal by host, username and password, over HTTP with digest or basic auth
- A `binary_sensor.last_access` entity that turns on when someone authenticates, with
  attributes for the name, employee number, card number, door and time
- A `sensor.last_access_time` timestamp entity showing when someone last authenticated, with
  the name, employee number, card number and door as attributes. This is the "who entered and
  when" entity for a dashboard card.
- One `button.open_door_N` per door. The number of doors is read from the terminal, so a
  single-door model shows one button, not a fixed pair. A door can be unlocked from a
  dashboard or an automation, not only from the gear menu.
- A `sensor.persons_enrolled` entity showing how many people are on the terminal. It does not
  need the access event permission, and it is read from `UserInfo/Count` with a search
  fallback for older firmware.
- A `button.refresh_people` entity that re-reads the door and person details from the terminal.
  Use it after granting the account its permissions instead of restarting Home Assistant.
- A `hikvision_access_event` event fired on the Home Assistant event bus for every granted access, so
  automations can react to who entered
- Person management from the Home Assistant UI: open the integration's `Configure` button to
  add, edit and delete people. Everything about a person lives in one form: name, gender,
  person type, PIN, validity window, door and card. No YAML required.
- Services to manage visitors and doors:
  - `hikvision_access.create_visitor` — create a person with a validity window and a PIN
    (a random 6 digit PIN is generated when you omit it)
  - `hikvision_access.delete_user` — remove a person
  - `hikvision_access.open_door` — unlock a door once

## Requirements

- Home Assistant 2026.8 or newer
- A device user with the permissions `Remote: Parameters Settings`, `Remote: Log Search /
  Interrogate Working Status` and `Remote: Live View` (for the picture that comes with an event)
- ISAPI access enabled on the device (enabled by default on current firmware)
- The terminal must be reachable from Home Assistant on port 80 (or 443 with HTTPS)

## Compatibility

The ISAPI responses the integration relies on are modelled on this terminal:

| Model | Firmware | Status |
| --- | --- | --- |
| DS-K1T805MBFWX | V1.9.1 build 240909 | Reference device for the `AcsEvent` and `UserInfo` queries |

Access events are detected from the `major`/`minor` codes this firmware reports. A reader
that exposes the same `AccessControl` ISAPI endpoints is expected to work, and one that
numbers the codes differently still shows its events in the debug log, which is enough to
add support. When reporting a different model or firmware, include the model, the firmware
build and a debug log.

## Installation

### With HACS (custom repository)

1. On the `HACS / Integrations` page, open the menu and choose `Custom repositories`
2. Add `https://github.com/Iakovosv/Hikvision_access` with category `Integration`
3. Search for `Hikvision Access Control`, open it and press `Download`
4. Restart Home Assistant
5. On `Settings / Devices & Services` press `+ Add Integration`, search for
   `Hikvision Access Control` and enter the device host, username and password

### Manual

Copy `custom_components/hikvision_access` into your `config/custom_components` folder and restart
Home Assistant.

## Usage

### Managing people from the UI

On `Settings / Devices & Services` find `Hikvision Access Control`, press `Configure` and choose:

- `Add person` — employee ID, name, gender, person type, PIN, card and the validity window.
  Leave the employee ID empty for an automatic one and the PIN empty for a random one.
- `Edit person` — pick a person from the list. The form shows what the device currently holds
  (type, gender, validity, cards, fingerprints and the visitor visit counters) and lets you
  change everything in one place: name, PIN, validity, door and card. The card field is
  prefilled with the card the person already holds, so submitting the form untouched changes
  nothing; type a new number to replace the card. Leave the PIN empty to keep the current one.
  Fingerprints can only be enrolled on the device itself.
- `Delete person` — pick a person and confirm.
- `Open door` — unlock a door once. The same is available as a `button.open_door_N` entity on
  the device page.

A note on permissions: person management needs `Remote: Parameters Settings`. If the account
cannot read the person list, the menu says so instead of failing. Access events need
`Remote: Log Search`; when that is missing the entry still works and only the last-access
entities report the reason.

React to an entry on the event bus:

```yaml
automation:
  - alias: Notify when someone enters
    triggers:
      - trigger: event
        event_type: hikvision_access_event
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "{{ trigger.event.data.name }} entered at {{ trigger.event.data.time }}"
```

Create a visitor PIN valid for a few hours:

```yaml
actions:
  - action: hikvision_access.create_visitor
    data:
      name: Maria Papadopoulou
      begin_time: "2026-10-01 09:00:00"
      end_time: "2026-10-01 21:00:00"
```

The generated PIN and the assigned employee number are published on the
`hikvision_access_visitor_created` event:

```yaml
automation:
  - alias: Send the visitor PIN
    triggers:
      - trigger: event
        event_type: hikvision_access_visitor_created
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "PIN {{ trigger.event.data.pin }} valid until {{ trigger.event.data.end_time }}"
```

## Why a separate integration

The official `hikvision_next` integration groups NVRs and IP cameras. An access terminal is a
different kind of device with its own endpoints (`AccessControl/...`), its own event model and its
own services, so keeping it separate keeps each integration focused and independently installable.

## Device safety

The integration is read-only unless you call a service. It never locks or unlocks a
door on its own: it polls events and only `open_door` sends a door command.
`create_visitor` and `delete_user` only run when you invoke them, and an automatically
assigned visitor number is checked against the people already enrolled so an existing
person is never overwritten.

The device rate limits failed logins, so authentication is negotiated once and reused.
If the password is wrong, the integration backs off instead of retrying in a loop.

## "Unauthorized" on the access event endpoint

The device answers `401 Unauthorized` in more than one situation: a wrong password, a
locked account, and an account that is signed in but missing a permission. The error
message alone cannot tell them apart, so the integration checks which case applies.

The account used by this integration needs two permissions on the terminal:

- **Remote: Parameters Settings** — the person list, the person count and creating or
  editing people (`/ISAPI/AccessControl/UserInfo/*`). Without it, "Edit person" and
  "Delete person" abort with the device's own answer, and "Add person" reports a refused
  request.
- **Remote: Log Search** — the access events behind `sensor.last_access_time` and
  `binary_sensor.last_access` (`/ISAPI/AccessControl/AcsEvent`). Without it, `System/deviceInfo`
  succeeds (which is why the config flow accepts the credentials) while `AcsEvent` returns 401.
  Grant Remote: Log Search; do not change the password, it is already correct.

After granting a permission, press the **Refresh people** button on the device page, or reload
the config entry. A full restart is not needed.

Another case is the lockout that follows repeated failed logins. The device then returns
401 for every request, including the ones that worked before, for about 30 minutes. Wait
for it to expire; the integration will not keep trying and extend it.

To see which endpoint the account may use, download the diagnostics from the integration
page. The `probe` section reports `ok` or an error for `System/deviceInfo`,
`AccessControl/AcsEvent`, `AccessControl/UserInfo/Search`, `AccessControl/UserInfo/Count`
and `AccessControl/Door/Count`; the host and credentials are redacted.

If the terminal clock drifts more than a minute from Home Assistant, a warning is logged
at startup. The device filters events by its own clock, so a large drift means entries
happen but no event is returned. Enable NTP on the device to keep the clocks aligned.

## Reporting issues

Set the log level to debug and attach the log to your report. It may contain names and employee
numbers of people enrolled on the terminal, so redact as needed.

```yaml
logger:
  logs:
    custom_components.hikvision_access: debug
```

## License

MIT, see [LICENSE](LICENSE). Not affiliated with Hikvision.
