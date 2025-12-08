"""Constants for the Daelim Smart Home integration."""
from typing import Final

DOMAIN: Final = "daelim_smarthome"

# Configuration keys
CONF_APART_ID: Final = "apart_id"
CONF_DONG: Final = "dong"
CONF_HO: Final = "ho"
CONF_CONTROL_INFO: Final = "control_info"  # Stored device configuration
CONF_DEVICE_UUID: Final = "device_uuid"  # Device UUID for protocol authentication
CONF_CERT_PIN: Final = "cert_pin"  # Saved cert pin for session reuse
CONF_LOGIN_PIN: Final = "login_pin"  # Saved login pin for session reuse

# API Constants
DEFAULT_HOST: Final = "smarthome.daelim.co.kr"
DEFAULT_INTERNAL_PORT: Final = 25301

# Message Types (from daelim_const.js)
TYPE_SYSTEM: Final = "0"
TYPE_LOGIN: Final = "1"
TYPE_GUARD: Final = "2"
TYPE_DEVICE: Final = "3"
TYPE_EMS: Final = "4"
TYPE_INFO: Final = "5"
TYPE_SETTING: Final = "7"
TYPE_EVCALL: Final = "8"
TYPE_ETC: Final = "9"

# Login subtypes
LOGIN_CERTPIN_REQ: Final = "1"
LOGIN_CERTPIN_RES: Final = "2"
LOGIN_LOGINPIN_REQ: Final = "3"
LOGIN_LOGINPIN_RES: Final = "4"
LOGIN_CERTPIN_CHK_REQ: Final = "5"
LOGIN_CERTPIN_CHK_RES: Final = "6"
LOGIN_UIINFO_REQ: Final = "7"
LOGIN_UIINFO_RES: Final = "8"  # Contains controlinfo with device list

# Device subtypes
DEVICE_QUERY_REQ: Final = "1"
DEVICE_QUERY_RES: Final = "2"
DEVICE_INVOKE_REQ: Final = "3"
DEVICE_INVOKE_RES: Final = "4"

# Guard (Security) subtypes
SEC_QRY_REQ: Final = "1"
SEC_QRY_RES: Final = "2"
SEC_ACT_REQ: Final = "3"
SEC_ACT_RES: Final = "4"

# EV Call subtypes
EVCALL_CALL_REQ: Final = "1"
EVCALL_CALL_RES: Final = "2"

# Device types
DEVICE_LIGHT: Final = "light"
DEVICE_HEATING: Final = "heating"
DEVICE_GAS: Final = "gas"
DEVICE_FAN: Final = "fan"
DEVICE_WALLSOCKET: Final = "wallsocket"
DEVICE_ALL: Final = "all"

# Device states
STATE_ON: Final = "on"
STATE_OFF: Final = "off"

# Guard modes
GUARD_MODE_OFF: Final = "0"
GUARD_MODE_AWAY: Final = "1"

# Update interval in seconds
UPDATE_INTERVAL: Final = 30
