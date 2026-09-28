# Hikvision Access Control

A Home Assistant integration for Hikvision access control terminals (door stations / face
terminals), talking to the device directly over ISAPI. No cloud.

It complements the [Hikvision Next](https://github.com/Iakovosv/Hikvision_next) integration,
which covers NVRs and IP cameras. Install both if you have cameras and an access terminal.

## Features

- Discover the terminal by host, username and password, over HTTP with digest or basic auth
- A `binary_sensor.last_access` entity that turns on when someone authenticates, with
  attributes for the name, employee number, card number, door and time
- A `hikvision_access_event` event fired on the Home Assistant event bus for every granted access, so
  automations can react to who entered
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
