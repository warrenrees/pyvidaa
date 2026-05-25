# pyvidaa

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Python library and Home Assistant integration for Hisense/Vidaa Smart TV control. Two integration options available:

1. **Custom Component** (Recommended) - Native Home Assistant integration with SSDP auto-discovery
2. **MQTT Bridge** - Docker-based bridge for MQTT-based home automation setups

> **Disclaimer:** pyvidaa is an independent, community-maintained project and is not affiliated with, endorsed by, or sponsored by Hisense or VIDAA. "VIDAA" and "Hisense" are trademarks of their respective owners; their use here is purely descriptive.

## Features

- **Home Assistant Custom Component** with config flow UI
- **SSDP Auto-Discovery** - TVs automatically detected on network
- **PIN Pairing** - Secure authentication via TV screen
- Control Hisense/Vidaa TVs via MQTT (optional bridge mode)
- Power on/off (with Wake-on-LAN support)
- Volume control and mute
- Input source switching
- App launching (Netflix, YouTube, etc.)
- Navigation keys (up, down, left, right, ok, back, home, menu)
- Multi-TV support
- Docker deployment ready (MQTT bridge)

## Obtaining the client certificate

Modern Vidaa TVs require **mutual TLS** — the client must present a certificate and
private key that are built into the official Vidaa mobile app. For legal reasons
**pyvidaa does not ship this certificate**; you supply your own copy. (Older,
legacy-protocol TVs may connect without it; when it is missing pyvidaa logs a
warning and falls back to plain TLS.)

### Where pyvidaa looks for it

pyvidaa searches for `vidaa_client.pem` (certificate) and `vidaa_client.key`
(private key), in this order:

1. Paths passed explicitly — `certfile=` / `keyfile=` in the library, or the
   certificate step of the Home Assistant config flow.
2. `$PYVIDAA_CERT_DIR`
3. `~/.config/pyvidaa/certs/`  ← recommended for CLI / bridge installs
4. `./certs/` next to a source checkout (development only)

```bash
mkdir -p ~/.config/pyvidaa/certs
cp vidaa_client.pem vidaa_client.key ~/.config/pyvidaa/certs/
```

For the Home Assistant integration, place the files under your HA config directory
as prompted by the setup flow.

### Extracting it from the Vidaa app

The certificate ships inside the Vidaa Android app as a PKCS#12 keystore
(`client_mobile_android.p12`):

1. Obtain the Vidaa app APK and unzip it (`unzip vidaa.apk`).
2. Locate `client_mobile_android.p12` among the app's assets.
3. Convert it to the PEM certificate + unencrypted key pyvidaa expects:

   ```bash
   # certificate
   openssl pkcs12 -in client_mobile_android.p12 -clcerts -nokeys -out vidaa_client.pem
   # private key (unencrypted PKCS#8)
   openssl pkcs12 -in client_mobile_android.p12 -nocerts -nodes -out vidaa_client.key
   ```

The keystore password and further APK details are documented in
[`VIDAA_PROTOCOL_ANALYSIS.md`](VIDAA_PROTOCOL_ANALYSIS.md). The certificate remains
the property of its owner and is not redistributed by this project.

### Server certificate verification (optional)

The TV's own (self-signed) server certificate is issued by the same private
`RemoteCA` root. That root is a public certificate with no private key, so it
**is** shipped with pyvidaa. By default server verification is off (`verify_ssl=False`),
matching the official app's behavior. Pass `verify_ssl=True` to validate the TV's
certificate against the bundled RemoteCA (the hostname check is always skipped,
since the certificate's CN is `RemoteCA` rather than the TV's IP):

```python
tv = HisenseTV("192.168.1.50", certfile=..., keyfile=..., verify_ssl=True)
```

## Quick Start

### 1. Prerequisites

- **Paired UUID**: You must first pair a device with your TV using the official Vidaa app
- **TV IP Address**: Your TV's IP address (static IP recommended)
- **MQTT Broker**: Mosquitto or Home Assistant's built-in broker
- **Docker** (recommended) or Python 3.8+

### 2. Configure

Copy the example config and edit:

```bash
cp config.example.yaml config.yaml
nano config.yaml
```

Minimum required settings:

```yaml
mqtt:
  host: "192.168.1.100"    # Your MQTT broker IP

tv:
  host: "YOUR_TV_IP"       # Your TV's IP address
  uuid: "xx:xx:xx:xx:xx:xx" # UUID from Vidaa app pairing
  mac: "XX:XX:XX:XX:XX:XX"  # TV MAC for Wake-on-LAN
  name: "Living Room TV"
```

### 3. Run with Docker

```bash
docker compose up -d
```

View logs:

```bash
docker compose logs -f
```

### 4. Home Assistant

The TV will automatically appear in Home Assistant via MQTT discovery. You'll get:

- **Media Player** entity with power, volume, source controls
- **Navigation Buttons** for remote control
- **App Launcher** select for streaming apps

## Manual Installation

If not using Docker:

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python -m hisense2mqtt --config config.yaml
```

## Configuration

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for full configuration reference.

### Environment Variables

Override config via environment:

| Variable | Description |
|----------|-------------|
| `MQTT_HOST` | MQTT broker hostname |
| `MQTT_PORT` | MQTT broker port |
| `MQTT_USERNAME` | MQTT username |
| `MQTT_PASSWORD` | MQTT password |
| `TV_HOST` | TV IP address |
| `TV_UUID` | Paired UUID |
| `TV_MAC` | TV MAC address |
| `LOG_LEVEL` | Logging level |

## MQTT Topics

### Commands (publish to these)

| Topic | Payload | Description |
|-------|---------|-------------|
| `hisense2mqtt/{id}/set/power` | `ON` / `OFF` | Power control |
| `hisense2mqtt/{id}/set/volume` | `0-100` | Set volume |
| `hisense2mqtt/{id}/set/mute` | `ON` / `OFF` | Toggle mute |
| `hisense2mqtt/{id}/set/source` | `hdmi1`, `hdmi2`, etc. | Change input |
| `hisense2mqtt/{id}/set/key` | `up`, `down`, `ok`, etc. | Send remote key |
| `hisense2mqtt/{id}/set/app` | `netflix`, `youtube`, etc. | Launch app |

### State (subscribe to these)

| Topic | Payload | Description |
|-------|---------|-------------|
| `hisense2mqtt/{id}/state/power` | `ON` / `OFF` | Power state |
| `hisense2mqtt/{id}/state/volume` | `0-100` | Current volume |
| `hisense2mqtt/{id}/state/mute` | `ON` / `OFF` | Mute state |
| `hisense2mqtt/{id}/state/source` | Source name | Current input |
| `hisense2mqtt/{id}/state/available` | `online` / `offline` | Availability |

## Getting the UUID

The UUID is required for authentication. To get it:

1. Install the official **Vidaa** app on your phone
2. Pair the app with your TV (enter the PIN shown on TV)
3. The UUID is your phone's Bluetooth/WiFi MAC address
4. Check your phone's settings or use `adb logcat` to find it

Alternatively, if you have a working UUID from previous pairing, use that.

## Wake-on-LAN

To turn on the TV when it's off:

1. Enable "Wake on LAN" or "Network Standby" in TV settings
2. Set `tv.mac` in config to your TV's MAC address
3. Connect TV via Ethernet (WiFi WoL is unreliable)
4. Set `options.wake_on_lan: true`

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for common issues.

### Quick Fixes

**TV not responding:**
- Ensure TV is on the same network
- Check TV IP address is correct
- Verify UUID is from a paired device

**Discovery not appearing in HA:**
- Check MQTT broker connection in HA
- Verify discovery_prefix matches HA config
- Check logs: `docker compose logs hisense2mqtt`

**Wake-on-LAN not working:**
- TV must be connected via Ethernet
- Enable WoL in TV settings
- Verify MAC address is correct

## Library Usage

Install the library:

```bash
pip install pyvidaa
```

Basic usage:

```python
from pyvidaa import HisenseTV, discover_all

# Discover TVs on network
devices = discover_all(timeout=5.0)
for ip, device in devices.items():
    print(f"Found: {ip} - {device.name}")

# Connect to TV
tv = HisenseTV(
    host="YOUR_TV_IP",
    mac_address="XX:XX:XX:XX:XX:XX",
    use_dynamic_auth=True,
)

if tv.connect():
    # Control TV
    tv.power_on()
    tv.volume_up()
    tv.launch_app("netflix")

    tv.disconnect()
```

See [docs/API.md](docs/API.md) for full API reference.

## Documentation

- [API Reference](docs/API.md)
- [Configuration Reference](docs/CONFIGURATION.md)
- [Home Assistant Integration](docs/HOME_ASSISTANT.md)
- [MQTT Topics](docs/MQTT_TOPICS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Protocol Analysis](VIDAA_PROTOCOL_ANALYSIS.md)

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Credits

Protocol reverse-engineered from the Vidaa Android app.
