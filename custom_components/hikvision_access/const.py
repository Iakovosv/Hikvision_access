"""Constants for the hikvision_access integration."""

from typing import Final

DOMAIN: Final = "hikvision_access"

CONF_VERIFY_SSL: Final = "verify_ssl"

# Access event major type and the minor type for a successful authentication.
ACS_EVENT_MAJOR: Final = 5
ACS_EVENT_MINOR_SUCCESS: Final = 75

# The device reports a photo per access event only when this URL is requested.
ACS_EVENT_PIC_URL_PREFIX: Final = "/ISAPI/AccessControl/AcsEvent?"

# How many access events to request per poll, and how far back the first poll looks.
ACS_EVENT_PAGE_SIZE: Final = 30
ACS_EVENT_INITIAL_LOOKBACK_SECONDS: Final = 3600

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

# The result of a create_visitor call is published on this event, so an automation
# that creates a visitor can read back the generated PIN and validity.
EVENT_VISITOR_CREATED: Final = f"{DOMAIN}_visitor_created"

EVENT_TYPE_ACCESS: Final = "access"
