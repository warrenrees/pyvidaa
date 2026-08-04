"""Dynamic credential generation for Hisense TV MQTT connection.

Reverse engineered from libmqttcrypt.so in the Vidaa mobile app.

The CORRECT algorithm (discovered via logcat capture):
- pattern: Constant "38D65DC30F45109A369A86FCE866A85B" from getInfo()/getSalt()
- race: pattern$uuid -> MD5 -> first 6 chars uppercase
- client_id: uuid$brand$race_md5_operation_001
- username: brand$XOR(timestamp) or brand$timestamp (legacy)
- value: brand + remainder + VALUE_SUFFIX (depends on protocol)
- password: MD5(timestamp$value_md5[:6])

Where:
- timestamp is Unix timestamp in SECONDS
- remainder = sum_of_digits(timestamp) % 10
- XOR constant = 0x5698_1477_2b03_a968

Authentication methods by transport protocol:
- STATIC (< 3000): no dynamic credentials at all - fixed hisenseservice login
- LEGACY (< 3000): no XOR username, VALUE_SUFFIX_LEGACY
- MIDDLE (3000-3285): XOR username, VALUE_SUFFIX_LEGACY
- MODERN (>= 3290): XOR username, VALUE_SUFFIX_MODERN
"""

import hashlib
import time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from .config import (
    PATTERN,
    VALUE_SUFFIX_MODERN,
    VALUE_SUFFIX_LEGACY,
    TIME_XOR_CONSTANT,
    DEFAULT_CLIENT_ID,
    DEFAULT_MQTT_USERNAME,
    DEFAULT_MQTT_PASSWORD,
)

if TYPE_CHECKING:
    from .protocol import AuthMethod


@dataclass
class MQTTCredentials:
    """MQTT connection credentials."""
    client_id: str
    username: str
    password: str


# Backwards compatibility alias
VALUE_SUFFIX = VALUE_SUFFIX_MODERN


def _md5(s: str) -> str:
    """Calculate MD5 hash of string and return UPPERCASE hex digest."""
    return hashlib.md5(s.encode('utf-8')).hexdigest().upper()


def _sum_digits(n: int) -> int:
    """Sum all digits of a number."""
    return sum(int(d) for d in str(abs(n)))


def generate_credentials(
    mac_address: Optional[str] = None,
    brand: str = "his",
    operation: str = "vidaacommon",
    timestamp: Optional[int] = None,
    auth_method: Optional["AuthMethod"] = None,
    client_id: str = DEFAULT_CLIENT_ID,
) -> MQTTCredentials:
    """Generate MQTT credentials for Hisense VIDAA TV connection.

    Args:
        mac_address: Device MAC address or UUID (format: "AA:BB:CC:DD:EE:FF").
                     Required for every method except STATIC, which does not
                     derive anything from it.
        brand: Brand identifier (default: "his" for Hisense)
        operation: Operation mode ("vidaacommon" or "vidaavoice")
        timestamp: Unix timestamp in SECONDS (default: current time)
        auth_method: Authentication method (STATIC, LEGACY, MIDDLE, or MODERN).
                     Default: MODERN for backwards compatibility.
        client_id: MQTT/topic client id, used by STATIC only

    Returns:
        MQTTCredentials with client_id, username, and password
    """
    # Import here to avoid circular dependency
    from .protocol import AuthMethod

    if auth_method is None:
        auth_method = AuthMethod.MODERN

    # Pre-dynamic firmware: a fixed login, nothing derived from MAC or clock.
    if auth_method == AuthMethod.STATIC:
        return generate_credentials_static(client_id=client_id)

    if not mac_address:
        raise ValueError(
            f"{auth_method.value} auth needs a MAC address to build a client_id"
        )

    if timestamp is None:
        timestamp = int(time.time())

    # UUID should keep original case - the race hash is case-sensitive!
    uuid = mac_address
    if ":" not in uuid and "-" not in uuid and len(uuid) == 12:
        # Convert flat MAC to colon format
        uuid = ":".join(uuid[i:i+2] for i in range(0, 12, 2))

    # Step 1: Calculate race = pattern$uuid, then MD5
    race = f"{PATTERN}${uuid}"
    race_md5 = _md5(race)[:6]  # First 6 chars, uppercase

    # Step 2: Build client_id: uuid$brand$race_md5_operation_001
    client_id = f"{uuid}${brand}${race_md5}_{operation}_001"

    # Step 3: Build username
    # LEGACY: brand$timestamp (no XOR)
    # MIDDLE/MODERN: brand$XOR(timestamp)
    if auth_method == AuthMethod.LEGACY:
        username = f"{brand}${timestamp}"
    else:
        xor_time = timestamp ^ TIME_XOR_CONSTANT
        username = f"{brand}${xor_time}"

    # Step 4: Build value for password hash
    # MODERN: uses VALUE_SUFFIX_MODERN
    # LEGACY/MIDDLE: uses VALUE_SUFFIX_LEGACY
    if auth_method == AuthMethod.MODERN:
        value_suffix = VALUE_SUFFIX_MODERN
    else:
        value_suffix = VALUE_SUFFIX_LEGACY

    remainder = _sum_digits(timestamp) % 10
    value = f"{brand}{remainder}{value_suffix}"
    value_md5 = _md5(value)[:6]  # First 6 chars

    # Step 5: Password = MD5(timestamp$value_md5)
    password = _md5(f"{timestamp}${value_md5}")

    return MQTTCredentials(
        client_id=client_id,
        username=username,
        password=password
    )


def generate_credentials_static(
    mac_address: Optional[str] = None,
    client_id: str = DEFAULT_CLIENT_ID,
) -> MQTTCredentials:
    """Generate static credentials for pre-dynamic Hisense firmware.

    TVs whose transport_protocol is below PROTOCOL_MIDDLE_THRESHOLD predate the
    dynamic credential algorithm and authorize by client_id after a PIN, using
    the fixed login baked into libmqttcrypt.so. These are the same values a
    Mosquitto bridge sends, which is the configuration known to work on that
    firmware:

        username hisenseservice
        password multimqttservice
        clientid HomeAssistant

    Args:
        mac_address: Ignored; accepted so callers can pass it uniformly
        client_id: MQTT client id, which is also the topic client id the TV
                   authorizes. Must stay stable across reconnects.

    Returns:
        MQTTCredentials with client_id, username, and password
    """
    return MQTTCredentials(
        client_id=client_id,
        username=DEFAULT_MQTT_USERNAME,
        password=DEFAULT_MQTT_PASSWORD
    )


if __name__ == "__main__":
    # Test with the exact values from logcat to verify algorithm
    print("=== Verifying Algorithm Against Known Logcat Values ===\n")

    # From logcat: uuid: 56:b8:88:4e:f7:19, time: 1766974704
    known_uuid = "56:b8:88:4e:f7:19"
    known_time = 1766974704

    # Expected values from logcat:
    # race_md5[:6]: 256DBF
    # client_id: 56:b8:88:4e:f7:19$his$256DBF_vidaacommon_001
    # username: his$6239759786168176024
    # password: C3BA44782E18ABF4892AC44D79A622D2

    creds = generate_credentials(known_uuid, timestamp=known_time)

    print(f"Input UUID: {known_uuid}")
    print(f"Input Time: {known_time}")
    print()

    # Verify each component
    expected_client_id = "56:b8:88:4e:f7:19$his$256DBF_vidaacommon_001"
    expected_username = "his$6239759786168176024"
    expected_password = "C3BA44782E18ABF4892AC44D79A622D2"

    print("Verification:")
    print(f"  Client ID: {creds.client_id}")
    print(f"    Expected: {expected_client_id}")
    print(f"    Match: {'✓' if creds.client_id == expected_client_id else '✗'}")
    print()
    print(f"  Username: {creds.username}")
    print(f"    Expected: {expected_username}")
    print(f"    Match: {'✓' if creds.username == expected_username else '✗'}")
    print()
    print(f"  Password: {creds.password}")
    print(f"    Expected: {expected_password}")
    print(f"    Match: {'✓' if creds.password == expected_password else '✗'}")
    print()

    # Show intermediate values
    print("=== Intermediate Values ===")
    race = f"{PATTERN}${known_uuid}"
    race_md5 = _md5(race)
    remainder = _sum_digits(known_time) % 10
    value = f"his{remainder}{VALUE_SUFFIX_MODERN}"
    value_md5 = _md5(value)

    print(f"  Pattern: {PATTERN}")
    print(f"  Race: {race}")
    print(f"  Race MD5: {race_md5}")
    print(f"  Race MD5[:6]: {race_md5[:6]}")
    print(f"  Time sum: {_sum_digits(known_time)}, Remainder: {remainder}")
    print(f"  Value: {value}")
    print(f"  Value MD5[:6]: {value_md5[:6]}")
    print(f"  XOR time: {known_time ^ TIME_XOR_CONSTANT}")
    print()

    # Test with current time
    print("=== Current Time Credentials ===")
    test_mac = "AA:BB:CC:DD:EE:FF"
    now = int(time.time())
    creds_now = generate_credentials(test_mac, timestamp=now)
    print(f"UUID: {test_mac}")
    print(f"Timestamp: {now}")
    print(f"  Client ID: {creds_now.client_id}")
    print(f"  Username:  {creds_now.username}")
    print(f"  Password:  {creds_now.password}")
