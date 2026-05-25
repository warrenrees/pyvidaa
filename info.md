# Hisense TV Integration

Control your Hisense/Vidaa Smart TV from Home Assistant!

## Features

- **Auto-discovery** - TVs automatically detected via SSDP
- **PIN Pairing** - Secure setup via PIN on TV screen
- **Media Player** - Power, volume, sources, and apps
- **Remote Control** - Send any remote button command
- **Custom Services** - `send_key` and `launch_app`

## Quick Start

1. Install via HACS
2. Restart Home Assistant
3. Go to Settings → Devices & Services
4. Your TV should appear as discovered, or click "Add Integration" and search for "Hisense TV"
5. Enter the PIN shown on your TV
6. Done!

## Supported TVs

- Hisense Smart TVs (2018+)
- Vidaa U platform TVs
- Some Toshiba TVs with Vidaa OS

## Example Usage

**Launch Netflix:**
```yaml
service: vidaa_tv.launch_app
data:
  app: netflix
```

**Send remote command:**
```yaml
service: remote.send_command
target:
  entity_id: remote.living_room_tv_remote
data:
  command: home
```

## Documentation

See the [full documentation](https://github.com/warrenrees/pyvidaa/blob/main/custom_components/vidaa_tv/README.md) for detailed setup and configuration options.
