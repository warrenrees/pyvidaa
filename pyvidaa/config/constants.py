"""All constants for Hisense TV control - single source of truth.

Consolidates hardcoded values from:
- client.py (ports, credentials, cert paths)
- credentials.py (crypto constants)
- discovery.py (network addresses/ports)
- protocol.py (version thresholds)
- topics.py (client ID)
"""

# === Network Ports ===
DEFAULT_PORT = 36669           # TV MQTT broker port
DISCOVERY_PORT = 36671         # Hisense UDP discovery port
SSDP_PORT = 1900              # Standard SSDP port
UPNP_PORT = 38400             # UPnP XML descriptor port
# Some VIDAA OS versions serve the UPnP descriptor on 18400 instead of 38400.
# Tried in order, so the common 38400 case is attempted first.
UPNP_PORTS = (38400, 18400)   # Candidate UPnP XML descriptor ports

# === Network Addresses ===
SSDP_ADDR = "239.255.255.250"  # SSDP multicast address
BROADCAST_ADDR = "255.255.255.255"

# === MQTT Authentication ===
# Static credentials for older TVs or fallback
DEFAULT_MQTT_USERNAME = "hisenseservice"
DEFAULT_MQTT_PASSWORD = "multimqttservice"

# === Client Identification ===
# Identifies this library to the TV. Deliberately NOT "HomeAssistant": that is
# what the widely-used Mosquitto-bridge setups send, and a TV drops the older
# session whenever a client id is reused, so sharing it would make the two fight
# over the connection. Existing pairings keep whatever id they were authorized
# with - it is restored from storage - so this only affects new ones.
DEFAULT_CLIENT_ID = "pyvidaa"
DEFAULT_BRAND = "his"

# === Protocol Version Thresholds ===
# Determines which authentication algorithm to use
PROTOCOL_MODERN_THRESHOLD = 3290  # >= uses modern auth
PROTOCOL_MIDDLE_THRESHOLD = 3000  # >= uses middle, < 3290
                                  # below this: pre-dynamic, static auth

# === Authentication Mode (user-facing selector) ===
AUTH_MODE_AUTO = "auto"        # detect the protocol, then fall back as needed
AUTH_MODE_DYNAMIC = "dynamic"  # force the timestamp-hash algorithm
AUTH_MODE_STATIC = "static"    # force the fixed pre-dynamic firmware login
AUTH_MODES = (AUTH_MODE_AUTO, AUTH_MODE_DYNAMIC, AUTH_MODE_STATIC)

# === Credential Generation Constants ===
# From libmqttcrypt.so reverse engineering
PATTERN = "38D65DC30F45109A369A86FCE866A85B"
VALUE_SUFFIX_MODERN = "h!i@s#$v%i^d&a*a"  # Protocol >= 3290
VALUE_SUFFIX_LEGACY = "h*i&s%e!r^v0i1c9"  # Protocol < 3290
TIME_XOR_CONSTANT = 0x5698_1477_2b03_a968

# === Token Durations ===
DEFAULT_ACCESS_TOKEN_DAYS = 7
DEFAULT_REFRESH_TOKEN_DAYS = 30

# === Certificate Paths (relative to package) ===
DEFAULT_CERT_FILENAME = "vidaa_client.pem"
DEFAULT_KEY_FILENAME = "vidaa_client.key"
