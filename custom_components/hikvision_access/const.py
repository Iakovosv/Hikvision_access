"""Constants for the hikvision_access integration."""

from typing import Final

DOMAIN: Final = "hikvision_access"

# Access event major type. Minor 0 asks the device for every minor type; the reference
# firmware rejects a query without a minor, and reports a card read as minor 1, so the
# selection is done on the event's identity instead of on a per-method code.
ACS_EVENT_MAJOR: Final = 5

# Minor codes documented for a granted authentication. Firmware disagrees on these (the
# reference terminal uses 1 for a card), so an event carrying a card number also counts
# as granted regardless of its minor.
ACS_EVENT_SUCCESS_MINORS: Final = (1, 38, 75, 113)

# The device reports a photo per access event only when this URL is requested.
ACS_EVENT_PIC_URL_PREFIX: Final = "/ISAPI/AccessControl/AcsEvent?"

# How many access events to request per poll, and how far back the first poll looks. The
# first lookback spans a day so an access while Home Assistant was down is not lost, and
# an event from the visit window can be recalled after a restart.
ACS_EVENT_PAGE_SIZE: Final = 30
ACS_EVENT_INITIAL_LOOKBACK_SECONDS: Final = 86400

# Poll interval. The device does not push events over a plain HTTP connection.
POLL_INTERVAL_SECONDS: Final = 30

# While event access is denied the poll slows down instead of stopping, so the
# entry recovers on its own once the permission is granted.
POLL_INTERVAL_DEGRADED_SECONDS: Final = 300

# A single access can appear in two consecutive windows; ignore repeats inside this period.
EVENT_DEDUP_WINDOW_SECONDS: Final = 60

# Warn when the device clock differs from Home Assistant by more than this.
CLOCK_DRIFT_WARNING_SECONDS: Final = 60

# Services
SERVICE_CREATE_VISITOR: Final = "create_visitor"
SERVICE_DELETE_USER: Final = "delete_user"
SERVICE_OPEN_DOOR: Final = "open_door"

ATTR_NAME: Final = "name"
ATTR_EMPLOYEE_NO: Final = "employee_no"
ATTR_BEGIN_TIME: Final = "begin_time"
ATTR_END_TIME: Final = "end_time"
ATTR_PIN: Final = "pin"
ATTR_DOOR_NO: Final = "door_no"
ATTR_DEVICE_ID: Final = "device_id"

# Person management, used by the options flow and the services.
ATTR_GENDER: Final = "gender"
ATTR_USER_TYPE: Final = "user_type"
ATTR_CARD_NO: Final = "card_no"
ATTR_VALIDITY_ENABLED: Final = "validity_enabled"
ATTR_AUTO_PIN: Final = "auto_pin"

GENDERS: Final = ("male", "female", "unknown")
USER_TYPES: Final = ("normal", "visitor")

# Person types the device reports that mean a temporary visitor.
VISITOR_USER_TYPES: Final = ("visitor",)

# Keys a device may use for the visitor "visit times" counters. The device the
# integration was modelled on does not return them over ISAPI, so the value is read
# back by name when present and never written blindly under a guessed name.
VISIT_TIMES_TOTAL_KEYS: Final = ("visitTimes", "maxVisitTimes", "maxVisitCount")
VISIT_TIMES_USED_KEYS: Final = ("currentVisitTimes", "visitTimesUsed", "usedVisitTimes")
VISIT_TIMES_REMAINING_KEYS: Final = ("remainingVisitTimes", "leftVisitTimes")

# The result of a create_visitor call is published on this event, so an automation
# that creates a visitor can read back the generated PIN and validity.
EVENT_VISITOR_CREATED: Final = f"{DOMAIN}_visitor_created"

# Fired for every granted authentication, with the person details.
EVENT_TYPE_ACCESS: Final = f"{DOMAIN}_event"

# Options for the optional notification and announcements. They are stored on the config
# entry, are all off by default, and only a user who opens the settings page turns them on.
CONF_NOTIFY_ENABLED: Final = "notify_enabled"
CONF_NOTIFY_SERVICE: Final = "notify_service"
CONF_NOTIFY_TITLE: Final = "notify_title"
CONF_NOTIFY_MESSAGE: Final = "notify_message"
CONF_NOTIFY_ALL: Final = "notify_all"
CONF_NOTIFY_NAMES: Final = "notify_names"
CONF_NOTIFY_NAMED_TITLE: Final = "notify_named_title"
CONF_NOTIFY_NAMED_MESSAGE: Final = "notify_named_message"
CONF_NOTIFY_DENIED: Final = "notify_denied"
CONF_TTS_ENABLED: Final = "tts_enabled"
CONF_TTS_ALL: Final = "tts_all"
CONF_TTS_ENTITY: Final = "tts_entity"
CONF_TTS_MEDIA_PLAYER: Final = "tts_media_player"
CONF_TTS_MESSAGE: Final = "tts_message"

DEFAULT_NOTIFY_TITLE: Final = "Hikvision"
DEFAULT_NOTIFY_MESSAGE: Final = "{name} opened the door ({method}, door {door}) at {time}"
DEFAULT_NOTIFY_NAMED_TITLE: Final = "Hikvision"
DEFAULT_NOTIFY_NAMED_MESSAGE: Final = "{name} opened the door at {time}"
DEFAULT_TTS_MESSAGE: Final = "Welcome {name}"

# Placeholders a message template may use, offered in the settings form.
NOTIFICATION_PLACEHOLDERS: Final = (
    "name",
    "employee_no",
    "card_no",
    "door",
    "method",
    "time",
    "date",
    "device",
)
