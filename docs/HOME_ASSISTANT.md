# Home Assistant Integration

Guide for integrating hisense2mqtt with Home Assistant.

## Prerequisites

1. **MQTT Integration** enabled in Home Assistant
2. **MQTT Broker** (Mosquitto add-on or standalone)
3. **hisense2mqtt** running and connected

## Automatic Discovery

When `options.discovery: true` (default), entities are automatically created in Home Assistant:

### Entities Created

| Entity Type | Entity ID | Description |
|-------------|-----------|-------------|
| Media Player | `media_player.hisense_10_0_0_194` | Main TV control |
| Button | `button.hisense_10_0_0_194_up` | Navigate up |
| Button | `button.hisense_10_0_0_194_down` | Navigate down |
| Button | `button.hisense_10_0_0_194_left` | Navigate left |
| Button | `button.hisense_10_0_0_194_right` | Navigate right |
| Button | `button.hisense_10_0_0_194_ok` | Select/Enter |
| Button | `button.hisense_10_0_0_194_back` | Go back |
| Button | `button.hisense_10_0_0_194_home` | Home screen |
| Button | `button.hisense_10_0_0_194_menu` | Open menu |
| Select | `select.hisense_10_0_0_194_app` | App launcher |

## Media Player Card

Add a media player card to your dashboard:

```yaml
type: media-control
entity: media_player.hisense_10_0_0_194
```

## Custom Remote Card

Create a TV remote using buttons:

```yaml
type: grid
columns: 3
square: false
cards:
  - type: button
    entity: button.hisense_10_0_0_194_home
    icon: mdi:home
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.hisense_10_0_0_194_home

  - type: button
    entity: button.hisense_10_0_0_194_up
    icon: mdi:chevron-up
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.hisense_10_0_0_194_up

  - type: button
    entity: button.hisense_10_0_0_194_menu
    icon: mdi:menu
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.hisense_10_0_0_194_menu

  - type: button
    entity: button.hisense_10_0_0_194_left
    icon: mdi:chevron-left
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.hisense_10_0_0_194_left

  - type: button
    entity: button.hisense_10_0_0_194_ok
    icon: mdi:checkbox-marked-circle
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.hisense_10_0_0_194_ok

  - type: button
    entity: button.hisense_10_0_0_194_right
    icon: mdi:chevron-right
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.hisense_10_0_0_194_right

  - type: button
    entity: button.hisense_10_0_0_194_back
    icon: mdi:arrow-left
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.hisense_10_0_0_194_back

  - type: button
    entity: button.hisense_10_0_0_194_down
    icon: mdi:chevron-down
    tap_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.hisense_10_0_0_194_down

  - type: button
    icon: mdi:power
    tap_action:
      action: call-service
      service: media_player.toggle
      target:
        entity_id: media_player.hisense_10_0_0_194
```

## Automation Examples

### Turn Off TV at Midnight

```yaml
automation:
  - alias: "Turn off TV at midnight"
    trigger:
      - platform: time
        at: "00:00:00"
    condition:
      - condition: state
        entity_id: media_player.hisense_10_0_0_194
        state: "on"
    action:
      - service: media_player.turn_off
        target:
          entity_id: media_player.hisense_10_0_0_194
```

### Turn On TV When Coming Home

```yaml
automation:
  - alias: "Turn on TV when arriving home"
    trigger:
      - platform: state
        entity_id: person.your_name
        to: "home"
    condition:
      - condition: time
        after: "17:00:00"
        before: "23:00:00"
    action:
      - service: media_player.turn_on
        target:
          entity_id: media_player.hisense_10_0_0_194
```

### Launch Netflix When Movie Night

```yaml
automation:
  - alias: "Movie night - Launch Netflix"
    trigger:
      - platform: state
        entity_id: input_boolean.movie_night
        to: "on"
    action:
      - service: media_player.turn_on
        target:
          entity_id: media_player.hisense_10_0_0_194
      - delay: "00:00:10"
      - service: select.select_option
        target:
          entity_id: select.hisense_10_0_0_194_app
        data:
          option: "Netflix"
```

### Mute TV During Phone Call

```yaml
automation:
  - alias: "Mute TV during phone call"
    trigger:
      - platform: state
        entity_id: sensor.phone_state
        to: "ringing"
    action:
      - service: media_player.volume_mute
        target:
          entity_id: media_player.hisense_10_0_0_194
        data:
          is_volume_muted: true
```

## Script Examples

### Switch to HDMI 1

```yaml
script:
  tv_hdmi1:
    alias: "TV - HDMI 1"
    sequence:
      - service: mqtt.publish
        data:
          topic: "hisense2mqtt/10_0_0_194/set/source"
          payload: "hdmi1"
```

### Volume Preset

```yaml
script:
  tv_volume_50:
    alias: "TV - Volume 50%"
    sequence:
      - service: media_player.volume_set
        target:
          entity_id: media_player.hisense_10_0_0_194
        data:
          volume_level: 0.5
```

### Send Any Remote Key

```yaml
script:
  tv_send_key:
    alias: "TV - Send Key"
    fields:
      key:
        description: "Key to send"
        example: "KEY_INFO"
    sequence:
      - service: mqtt.publish
        data:
          topic: "hisense2mqtt/10_0_0_194/set/key"
          payload: "{{ key }}"
```

## Manual MQTT Configuration

If auto-discovery is disabled, configure entities manually:

### Media Player

```yaml
# configuration.yaml
mqtt:
  media_player:
    - name: "Hisense TV"
      unique_id: "vidaa_tv_living_room"
      state_topic: "hisense2mqtt/10_0_0_194/state/power"
      command_topic: "hisense2mqtt/10_0_0_194/set/power"
      volume_level_topic: "hisense2mqtt/10_0_0_194/state/volume"
      volume_level_template: "{{ value | float / 100 }}"
      set_volume_topic: "hisense2mqtt/10_0_0_194/set/volume"
      mute_state_topic: "hisense2mqtt/10_0_0_194/state/mute"
      mute_command_topic: "hisense2mqtt/10_0_0_194/set/mute"
      availability_topic: "hisense2mqtt/10_0_0_194/state/available"
      payload_available: "online"
      payload_not_available: "offline"
      payload_on: "ON"
      payload_off: "OFF"
```

## Troubleshooting

### Entity Not Appearing

1. Check MQTT integration is connected
2. Verify discovery_prefix matches HA settings
3. Check hisense2mqtt logs for errors
4. Restart Home Assistant

### Entity Shows Unavailable

1. Check hisense2mqtt is running
2. Verify TV is powered on
3. Check network connectivity
4. View logs: `docker compose logs hisense2mqtt`

### Commands Not Working

1. Verify UUID is from paired device
2. Check TV accepts MQTT connections
3. Try toggling power from the TV physically first
4. Enable debug logging: `LOG_LEVEL=DEBUG`
