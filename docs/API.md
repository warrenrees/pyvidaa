# API Reference

This document provides a reference for the `pyvidaa` Python library.

## Installation

```bash
pip install pyvidaa
```

## Quick Start

```python
from pyvidaa import VidaaTV, discover_all

# Discover TVs
devices = discover_all()
print(devices)

# Connect and control
tv = VidaaTV(host="10.0.0.125", mac_address="84:C8:A0:C0:CE:8F")
if tv.connect():
    tv.power_on()
    tv.disconnect()
```

---

## Discovery Module

### `discover_all(timeout, interface, methods)`

Run multiple discovery methods and merge results.

```python
from pyvidaa import discover_all

devices = discover_all(timeout=5.0)
for ip, device in devices.items():
    print(f"{ip}: {device.name} ({device.model})")
```

**Parameters:**
- `timeout` (float): Timeout per method in seconds. Default: 5.0
- `interface` (str, optional): Network interface IP to bind to
- `methods` (list, optional): List of methods: `["ssdp", "ssdp_listen", "udp"]`

**Returns:** `Dict[str, DiscoveredTV]`

### `discover_ssdp(timeout, interface)`

Discover devices via SSDP M-SEARCH multicast query.

```python
from pyvidaa import discover_ssdp

devices = discover_ssdp(timeout=5.0)
```

### `listen_ssdp(timeout, interface)`

Listen for SSDP NOTIFY announcements (passive discovery).

```python
from pyvidaa import listen_ssdp

# Listen for 30 seconds
devices = listen_ssdp(timeout=30.0)
```

### `discover_udp(timeout, retries, interface)`

Discover TVs via UDP broadcast on port 36671.

```python
from pyvidaa import discover_udp

devices = discover_udp(timeout=5.0, retries=3)
```

### `probe_ip(ip, port, timeout)`

Send discovery directly to a specific IP.

```python
from pyvidaa import probe_ip

device = probe_ip("10.0.0.125")
if device:
    print(f"Found: {device.name}")
```

### `DiscoveredTV`

Dataclass representing a discovered TV.

```python
@dataclass
class DiscoveredTV:
    ip: str
    port: int = 36669
    name: Optional[str] = None
    model: Optional[str] = None
    mac: Optional[str] = None
    location: Optional[str] = None
    source: str = "unknown"  # ssdp_msearch, ssdp_notify, udp, probe
```

---

## VidaaTV Client

### Constructor

```python
from pyvidaa import VidaaTV

tv = VidaaTV(
    host="10.0.0.125",
    port=36669,
    mac_address="84:C8:A0:C0:CE:8F",
    use_dynamic_auth=True,
    auto_detect_protocol=True,
    enable_persistence=True,
)
```

**Parameters:**
- `host` (str): TV IP address
- `port` (int): MQTT port. Default: 36669
- `mac_address` (str, optional): TV MAC for credential generation
- `use_dynamic_auth` (bool): Use dynamic credentials. Default: True
- `auto_detect_protocol` (bool): Detect protocol version. Default: True
- `enable_persistence` (bool): Save tokens to file. Default: True
- `verify_ssl` (bool): Verify SSL certificate. Default: False (TV uses self-signed)

### Connection Methods

#### `connect(timeout, auto_auth, try_fallback, auto_refresh)`

Connect to the TV.

```python
if tv.connect(timeout=10.0):
    print("Connected!")
```

**Returns:** `bool` - True if connected successfully

#### `disconnect()`

Disconnect from the TV.

```python
tv.disconnect()
```

#### `is_connected`

Check if connected.

```python
if tv.is_connected:
    print("Still connected")
```

### Authentication

#### `start_pairing()`

Start pairing to show PIN on TV screen.

```python
tv.start_pairing()
# TV will display a 4-digit PIN
```

#### `authenticate(pin, wait_for_response, timeout)`

Send PIN to complete authentication.

```python
if tv.authenticate("1234"):
    print("Authenticated!")
```

#### `refresh_token(timeout)`

Refresh the access token using stored refresh token.

```python
tv.refresh_token()
```

### Power Control

#### `power()`

Toggle power state.

```python
tv.power()
```

#### `power_on()`

Turn TV on (uses Wake-on-LAN if TV is off).

```python
tv.power_on()
```

#### `power_off()`

Turn TV off.

```python
tv.power_off()
```

#### `is_on()`

Check if TV is on.

```python
if tv.is_on():
    print("TV is on")
```

### Volume Control

#### `volume_up()`

Increase volume.

```python
tv.volume_up()
```

#### `volume_down()`

Decrease volume.

```python
tv.volume_down()
```

#### `mute()`

Toggle mute.

```python
tv.mute()
```

#### `get_volume(timeout)`

Get current volume level.

```python
volume = tv.get_volume()
print(f"Volume: {volume}")
```

**Returns:** `Optional[int]` - Volume 0-100 or None

#### `set_volume(level)`

Set volume level.

```python
tv.set_volume(50)
```

### Remote Keys

#### `send_key(key, check_state)`

Send a remote control key.

```python
from pyvidaa import KEY_UP, KEY_OK, KEY_BACK

tv.send_key(KEY_UP)
tv.send_key(KEY_OK)
tv.send_key("KEY_HOME")  # String also works
```

**Available Keys:**
- Navigation: `KEY_UP`, `KEY_DOWN`, `KEY_LEFT`, `KEY_RIGHT`, `KEY_OK`, `KEY_BACK`, `KEY_HOME`, `KEY_MENU`
- Power: `KEY_POWER`
- Volume: `KEY_VOLUME_UP`, `KEY_VOLUME_DOWN`, `KEY_MUTE`
- Playback: `KEY_PLAY`, `KEY_PAUSE`, `KEY_STOP`, `KEY_FAST_FORWARD`, `KEY_REWIND`
- Numbers: `KEY_0` through `KEY_9`
- Colors: `KEY_RED`, `KEY_GREEN`, `KEY_YELLOW`, `KEY_BLUE`
- Channel: `KEY_CHANNEL_UP`, `KEY_CHANNEL_DOWN`

### Sources

#### `get_sources(timeout)`

Get available input sources.

```python
sources = tv.get_sources()
for source in sources:
    print(source["sourcename"])
```

#### `set_source(source)`

Change input source.

```python
from pyvidaa import SOURCE_HDMI1

tv.set_source(SOURCE_HDMI1)
# or
tv.set_source("hdmi1")
```

**Source Constants:**
- `SOURCE_TV`, `SOURCE_HDMI1`, `SOURCE_HDMI2`, `SOURCE_HDMI3`, `SOURCE_HDMI4`
- `SOURCE_AV`, `SOURCE_COMPONENT`

### Apps

#### `get_apps(timeout)`

Get list of installed apps.

```python
apps = tv.get_apps()
for app in apps:
    print(app["name"])
```

#### `launch_app(app_name)`

Launch an app by name.

```python
tv.launch_app("netflix")
tv.launch_app("youtube")
```

### State & Info

#### `get_state(timeout)`

Get current TV state.

```python
state = tv.get_state()
print(state)
# {'statetype': 'livetv', 'source': 'tv', ...}
```

#### `get_tv_info(timeout)`

Get TV information.

```python
info = tv.get_tv_info()
print(info)
```

#### `get_device_info(timeout)`

Get device information.

```python
info = tv.get_device_info()
print(info)
```

---

## Protocol Detection

### `detect_protocol(host, port, timeout)`

Detect transport protocol version from TV's UPnP descriptor.

```python
from pyvidaa import detect_protocol, get_auth_method

version = detect_protocol("10.0.0.125")
print(f"Protocol version: {version}")  # e.g., 3290

auth = get_auth_method(version)
print(f"Auth method: {auth.value}")  # modern, middle, or legacy
```

### `AuthMethod`

Enum for authentication methods.

```python
from pyvidaa import AuthMethod

AuthMethod.LEGACY   # Protocol < 3000
AuthMethod.MIDDLE   # Protocol 3000-3285
AuthMethod.MODERN   # Protocol >= 3290
```

---

## Configuration

### `load_config()` / `save_config(config)`

Load/save configuration from `~/.config/pyvidaa/config.json`.

```python
from pyvidaa import load_config, save_config, set_tv_ip

config = load_config()
set_tv_ip("10.0.0.125")
```

### `get_tv_ip()` / `set_tv_ip(ip)`

Get/set configured TV IP address.

### `get_default_uuid()` / `set_default_uuid(uuid)`

Get/set default UUID for authentication.

---

## Token Storage

### `TokenStorage`

Manages persistent storage of authentication tokens.

```python
from pyvidaa import get_storage

storage = get_storage()

# Check token status
status = storage.get_token_status("10.0.0.125", 36669)
print(status)
# {'has_token': True, 'access_valid': True, ...}

# List stored devices
devices = storage.list_devices()
```

---

## Logging

The library uses Python's `logging` module. Configure logging to see debug output:

```python
import logging

logging.basicConfig(level=logging.DEBUG)

# Or configure specific logger
logging.getLogger("pyvidaa").setLevel(logging.DEBUG)
```
