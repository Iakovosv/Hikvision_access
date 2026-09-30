# Hikvision Access Control

A Home Assistant integration for Hikvision access control terminals (door stations / face
terminals), talking to the device directly over ISAPI. No cloud.

## Everything is done from the UI

Nothing here needs YAML. You set the integration up, manage people, and configure the
notifications all from the Home Assistant interface:

- **Adding the device** — `Settings / Devices & Services / + Add Integration`, then the host,
  username and password. That is the whole setup.
- **People and cards** — on `Settings / Devices & Services`, open `Hikvision Access Control`
  and press `Configure`. Add, edit and delete people, set a PIN, a card and a validity window,
  all from one form.
- **Devices on the dashboard** — the entities (last access, person count, one button per door)
  appear by themselves; put them on a dashboard with the normal UI editor.
- **Notifications and announcements** — same `Configure` button, `Notifications & announcements`.
- **Turning on a light when the door opens** — a ready-made blueprint is installed for you
  under `Settings / Automations & Scenes / Blueprints`.

The YAML further down is **optional**. It is for two cases only: reacting to an event in an
automation you write yourself, and the visitor/delete/open-door services, if you would rather
call them from a script than from the `Configure` menu. If you do not need those, you never
have to open a text editor.

## What you get

### Entities

| Entity | What it is | Use it for |
| --- | --- | --- |
| `binary_sensor.last_access` | Turns on when someone authenticates. Attributes: `name`, `employee_no`, `card_no`, `door_no`, `method`, `granted` | A trigger that fires the moment someone enters |
| `sensor.last_access_person` | The name of the person who last opened the door, so the device page and a card can read it directly. Attributes: `employee_no`, `card_no`, `door_no`, `method`, `granted`, `time` | A dashboard card: who entered |
| `sensor.last_access_time` | The timestamp of the last authentication, with the same attributes plus `granted` and the exact `date`, `time` and `datetime` | A dashboard card: who entered, and exactly when |
| `sensor.persons_enrolled` | How many people are on the terminal. Read from `UserInfo/Count`, with a search fallback for older firmware | A quick count, no access-event permission needed |
| `button.open_door_N` | One button per door. The number of doors is read from the terminal, so a single-door model shows one button, not a fixed pair | Unlocking a door from a dashboard or an automation |
| `button.refresh_people` | Re-reads the door and person details from the terminal | After granting the account its permissions, instead of restarting Home Assistant |

The names follow the Home Assistant language, so a Greek interface shows `Τελευταία πρόσβαση`,
`Τελευταίο πρόσωπο`, `Ώρα τελευταίας πρόσβασης`, `Καταχωρημένα πρόσωπα`, `Άνοιγμα πόρτας`
and `Ανανέωση προσώπων`.

### The Configure menu

Everything under `Configure` is a point-and-click form. The choices are:

- **Add person** — employee ID, name, gender, person type, PIN, card, door, an optional
  validity window and an optional maximum number of uses. Leave the employee ID empty for an
  automatic one and the PIN empty for a random 6-digit one. Leave the usage limit empty (or 0)
  for no limit.
- **Edit person** — pick a person from the list. The form shows what the device currently holds
  (type, gender, validity, cards, fingerprints and the visitor visit counters) and lets you
  change everything in one place: name, PIN, validity, door, card and usage limit. The PIN,
  validity dates and card fields are prefilled with what the person already has, so submitting
  the form untouched changes nothing; type a new value to replace it. Leave the PIN empty to keep
  the current one, and leave the usage limit empty (or 0) to keep the current limit or leave it
  unlimited. Fingerprints can only be enrolled on the device itself.
- **Delete person** — pick a person and confirm.
- **Open door** — unlock a door once.
- **Notifications & announcements** — the optional alerts described below.

### Notifications and announcements

Open `Configure`, then `Notifications & announcements`. Every switch is off until you turn it
on.

**Send a notification.**

- Turn on `Enable notifications` and pick the `Notify service` — the entity of the device you
  want to reach (your phone, Telegram, e-mail).
- Choose **who** to report. Turn on `Notify me for every entry` to be told about everyone, or
  leave it off and list names under `Names to watch` (comma separated) to be told only about
  them. A watched name can have its own `Watched-name title` and `Watched-name message`.
- Turn on `Also notify when access is refused` to hear about a failed authentication too.

**Say it out loud.**

- Turn on `Enable announcements`, pick a `Text-to-speech engine` and the `Speaker` (a Google
  Nest, for example), and type the `Announcement text`. Turn on `Announce every entry` to speak
  for everyone, or leave it off to speak only for the names under `Names to watch` (the same
  list the notification uses).

A word of warning: a notification is only sent once you have picked at least one of `every
entry`, `Names to watch` or `refused access`. Turning on `Enable notifications` with all three
empty deliberately sends nothing, so an unfilled page cannot spam you.

**Placeholders.** Both the notification and the announcement take these, filled from the event:
`{name}`, `{employee_no}`, `{card_no}`, `{door}`, `{method}`, `{time}`, `{date}` and `{device}`
(the Home Assistant device name). A placeholder that is not in the list is left as it is, so a
stray brace cannot break the flow. The defaults are `{name} opened the door ({method}, door
{door}) at {time}` for the message and `Welcome {name}` for the announcement.

### Blueprint: lights when the door opens

The integration writes the blueprint `Hikvision - turn on lights when the door opens` into your
configuration on first setup, so it shows up under `Settings / Automations & Scenes /
Blueprints`. Pick the lights, the brightness and how long to keep them on, and optionally
restrict it to one person. The file is written once and never overwritten, so your own edits to
it are kept.

### Events (for automations you write yourself)

Two events are fired on the Home Assistant event bus:

- `hikvision_access_event` — for every granted access. Data: `device_id` (the serial number),
  `name`, `employee_no`, `card_no`, `door_no`, `time` (ISO), `minor`, `method`, `granted`.
- `hikvision_access_visitor_created` — after `create_visitor`. Data: `device_id`, `name`,
  `employee_no`, `pin`, `begin_time`, `end_time`.

### Services (optional, YAML)

The same actions are available as services if you prefer them in a script:

| Service | Fields |
| --- | --- |
| `hikvision_access.create_visitor` | `name`, `begin_time`, `end_time`, and optionally `pin`, `employee_no`, `gender`, `user_type`, `card_no`, `door_no` |
| `hikvision_access.delete_user` | `employee_no` |
| `hikvision_access.open_door` | `door_no`, and optionally `dry_run` |

### Checking the door command without opening the door

There is no way to make a terminal unlock a door as a test, but there is a read-only way
to ask whether it would accept the command. Three things let you check from a distance.

Download the **diagnostics** from the integration page. The `door_control` section is a
read-only `GET` to the terminal's door capability endpoint, and it reports which doors it
can control and which commands it accepts:

```yaml
door_control:
  supported: true
  doors: [1]
  commands: [open, close, alwaysOpen, alwaysClose]
```

If `open` is in `commands`, the button sends a command the device accepts. If the section
carries an `error`, the account most likely lacks door-control permission. Downloading the
report sends no door command.

The command list is the terminal's own, so it can be shorter than the ISAPI documentation.
A DS-K1T805MBFWX, for instance, does not list `resume`. That difference is worth knowing:
the integration will still build a `resume` request if asked, but the terminal would
refuse it. The report is the only place the difference is visible.

The same report shows the exact request that would be sent, per door:

```yaml
door_commands:
  door_1:
    method: PUT
    path: AccessControl/RemoteControl/door/1
    body: <RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>
```

### Did the door really open?

The `door_status` section is a second read-only `GET`, to the terminal's work status. It
reports the lock state and the magnet contact per door, and the magnet is the physical
door:

```yaml
door_status:
  supported: true
  doors:
    - door_no: 1
      locked: true
      magnet_open: false
```

Open the door, then download the diagnostics again. If `magnet_open` becomes `true`, the
door physically opened. If it stays `false`, the command reached the terminal and the
terminal accepted it, but the relay or the lock did not move, which is a wiring or power
problem rather than a command problem. If `locked` turns `false` while `magnet_open` stays
`false`, the relay fired and the magnet or its wiring is the suspect.

Call the service with **`dry_run: true`** to build the command and log it without sending
it. The log line names the request that would go out, and the terminal is not touched:

```yaml
action: hikvision_access.open_door
data:
  door_no: 1
  dry_run: true
```

If the terminal reports more than one door, pressing a button for a door with no relay
wired is the only end-to-end test that is completely safe: the whole path is exercised
and no door opens.

On Windows, `scripts/check-door-command.ps1` does the first two checks for you over the
Home Assistant REST API. Set `HA_URL` and an admin `HA_TOKEN`, run it, and it prints the
command that would be sent without sending it.

`scripts/open-door.ps1` goes one step further and opens the door through the integration's
own service, so the request that reaches the terminal is built by the integration:

```powershell
$env:HA_URL   = "http://homeassistant.local:8123"
$env:HA_TOKEN = "<long lived access token>"

.\open-door.ps1 -DryRun     # print the request, send nothing
.\open-door.ps1             # send it for door 1
.\open-door.ps1 -DoorNo 2   # send it for door 2
```

It prints the exact request first, then sends it, then reads the door status back from the
terminal. `-DryRun` stops after printing, which is the safe way to confirm the command
before a door moves.

## Requirements

- Home Assistant 2026.8 or newer
- A device user with the permissions `Remote: Parameters Settings`, `Remote: Log Search /
  Interrogate Working Status` and `Remote: Live View` (for the picture that comes with an event)
- ISAPI access enabled on the device (enabled by default on current firmware)
- The terminal must be reachable from Home Assistant on port 80 (or 443 with HTTPS)

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

The event poll asks the terminal for **all** minor types of access event (`major=5, minor=0`)
and then keeps the events that carry a name, an employee number or a card number. This is
deliberate: firmware disagrees on the minor code for a successful authentication (the
reference terminal reports a card read as `minor=1` where the ISAPI guide documents `38`,
and never reports the documented face code `75`), and a query restricted to one method
answers `NO MATCH` while other methods have events. Selecting on the event's identity instead
of on a per-method code sees every card, fingerprint, face and PIN open on every firmware that
follows the same ISAPI shape.

## Activity log

Every opening also appears in the **Activity** log of the device page, one line naming the
person and the door, e.g. *"House cleaner opened the door with card 2673003718 (door 1)"*. The
line follows the Home Assistant language. Card, fingerprint, face and PIN opens are all
reported; a query the terminal cannot answer for one method no longer hides the rest.

## Permissions, and the "Unauthorized" message

The device answers `401 Unauthorized` in more than one situation: a wrong password, a locked
account, and an account that is signed in but missing a permission. The error message alone
cannot tell them apart, so the integration checks which case applies.

The account used by this integration needs two permissions on the terminal:

- **Remote: Parameters Settings** — the person list, the person count and creating or
  editing people (`/ISAPI/AccessControl/UserInfo/*`). Without it, "Edit person" and
  "Delete person" abort with the device's own answer, and "Add person" reports a refused
  request.
- **Remote: Log Search** — the access events behind `sensor.last_access_time` and
  `binary_sensor.last_access` (`/ISAPI/AccessControl/AcsEvent`). Without it, `System/deviceInfo`
  succeeds (which is why the config flow accepts the credentials) while `AcsEvent` returns 401.
  Grant Remote: Log Search; do not change the password, it is already correct.

If the account cannot read the person list, the `Configure` menu says so instead of failing, and
an entry without the event permission still works — only the last-access entities report the
reason.

After granting a permission, press the **Refresh people** button on the device page, or reload
the config entry. A full restart is not needed.

Another case is the lockout that follows repeated failed logins. The device then returns
401 for every request, including the ones that worked before, for about 30 minutes. Wait
for it to expire; the integration will not keep trying and extend it.

To see which endpoint the account may use, download the diagnostics from the integration
page. The `probe` section reports `ok` or an error for `System/deviceInfo`,
`AccessControl/AcsEvent`, `AccessControl/UserInfo/Search`, `AccessControl/UserInfo/Count`,
`AccessControl/Door/Count`, `AccessControl/RemoteControl/door/capabilities` and
`AccessControl/AcsWorkStatus`; the host and credentials are redacted. The last two are
read-only and are what tell you whether the account may control a door and whether a door
is actually open, without a door being opened.

If the terminal clock drifts more than a minute from Home Assistant, a warning is logged
at startup. The device filters events by its own clock, so a large drift means entries
happen but no event is returned. Enable NTP on the device to keep the clocks aligned.

## Device safety

The integration is read-only unless you call a service. It never locks or unlocks a
door on its own: it polls events and only `open_door` sends a door command.
`create_visitor` and `delete_user` only run when you invoke them, and an automatically
assigned visitor number is checked against the people already enrolled so an existing
person is never overwritten.

The device rate limits failed logins, so authentication is negotiated once and reused.
If the password is wrong, the integration backs off instead of retrying in a loop.

## Why a separate integration

An access terminal is its own kind of device: it has its own endpoints (`AccessControl/...`),
its own event model and its own services. This integration talks to those endpoints directly,
so it stays focused on the terminal and can be installed on its own.

## Reporting issues

Set the log level to debug and attach the log to your report. It may contain names and employee
numbers of people enrolled on the terminal, so redact as needed.

```yaml
logger:
  logs:
    custom_components.hikvision_access: debug
```

## Examples (optional)

React to an entry on the event bus, instead of using the built-in notification:

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

Create a visitor PIN valid for a few hours (the same as `Add person`, if you prefer a script):

```yaml
actions:
  - action: hikvision_access.create_visitor
    data:
      name: Maria Papadopoulou
      begin_time: "2026-10-01 09:00:00"
      end_time: "2026-10-01 21:00:00"
      max_times: 2
```

`max_times` is optional: leave it out for a visitor who may enter any number of
times inside the window, or set a positive number to allow only that many entries.

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

## Commercial use, and support

At home it is free: install it, run it, report bugs, ask questions. Nothing is behind a
paywall, and private users get the same code as everyone else.

If you are an installer or a company and you use it **for a client**, or ship it as part of
a product or a managed service, that needs a licence. A licence is also the way to get
support: a direct channel, priority on bugs, and help during installation.

The details are in [COMMERCIAL.md](COMMERCIAL.md). To ask for one, open a discussion in
[GitHub Discussions](https://github.com/Iakovosv/Hikvision_access/discussions) titled
"Commercial licence", or use the issue tracker. There is no price list: quotes are given per
request, based on the number of sites and whether support is included.

If the integration is useful to you personally, you can also support the work with a
one-off donation — the **Sponsor** button at the top of the repository.

## License

Source-available, all rights reserved, see [LICENSE](LICENSE). Free to install and run for
personal use, but copying, redistributing, modifying or using it commercially requires
written permission from the author. Not affiliated with Hikvision.
