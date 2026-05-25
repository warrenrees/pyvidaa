"""Constants for the Hisense TV integration."""

from typing import Final

DOMAIN: Final = "hisense_tv"

# Configuration keys
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_MAC: Final = "mac"
CONF_NAME: Final = "name"
CONF_DEVICE_ID: Final = "device_id"
CONF_MODEL: Final = "model"
CONF_BRAND: Final = "brand"
CONF_SW_VERSION: Final = "sw_version"
CONF_CERTFILE: Final = "certfile"
CONF_KEYFILE: Final = "keyfile"

# Default values
DEFAULT_PORT: Final = 36669
DEFAULT_NAME: Final = "Hisense TV"

# Default certificate paths (relative to HA config directory)
DEFAULT_CERT_DIR: Final = "certs"
DEFAULT_CERT_FILENAME: Final = "vidaa_client.pem"
DEFAULT_KEY_FILENAME: Final = "vidaa_client.key"

# Timeouts
TIMEOUT_CONNECT: Final = 10
TIMEOUT_COMMAND: Final = 5
TIMEOUT_DISCOVERY: Final = 5

# Scan interval for polling
SCAN_INTERVAL: Final = 30

# Services
SERVICE_SEND_KEY: Final = "send_key"
SERVICE_LAUNCH_APP: Final = "launch_app"

# Attributes
ATTR_KEY: Final = "key"
ATTR_APP: Final = "app"

# States
STATE_FAKE_SLEEP: Final = "fake_sleep_0"

# Platform types
PLATFORMS: Final = ["media_player", "remote"]
