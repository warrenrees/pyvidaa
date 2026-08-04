"""Configuration schema, defaults, and validation."""

from typing import Any, Dict, List, Optional

from .constants import (
    AUTH_MODE_AUTO,
    DEFAULT_PORT,
    DEFAULT_BRAND,
    DEFAULT_CLIENT_ID,
)


# Default configuration for a single TV
DEFAULT_TV_CONFIG: Dict[str, Any] = {
    "host": None,                # Required - TV IP address
    "port": DEFAULT_PORT,        # 36669
    "alias": None,               # Friendly name for CLI (--tv alias)
    "name": None,                # Display name (auto-populated from TV)
    "brand": DEFAULT_BRAND,      # "his"
    "auth_mode": AUTH_MODE_AUTO,  # auto | dynamic | static
    # Auto-populated during pairing:
    # "model": None,
    # "sw_version": None,
}


# Full config structure with multi-TV support
DEFAULT_CONFIG: Dict[str, Any] = {
    # MQTT broker settings (for hisense2mqtt bridge)
    "mqtt": {
        "host": None,                # Required for bridge
        "port": 1883,
        "username": None,
        "password": None,
        "discovery_prefix": "homeassistant",
        "client_id": "hisense2mqtt",
    },

    # Multiple TVs - keyed by device_id
    "tvs": {},

    # Default TV for CLI when --tv not specified (device_id or alias)
    "default_tv": None,

    # Bridge operation options
    "options": {
        "poll_interval": 30,
        "wake_on_lan": True,
        "discovery": True,
        "reconnect_interval": 30,
        "log_level": "INFO",
    },
}


def deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge two dictionaries, override takes precedence.

    Args:
        base: Base dictionary
        override: Override dictionary (values take precedence)

    Returns:
        Merged dictionary
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif value is not None:  # Don't override with None
            result[key] = value
    return result


def validate_config(config: Dict, for_bridge: bool = False) -> List[str]:
    """Validate configuration and return list of errors.

    Args:
        config: Configuration dictionary
        for_bridge: If True, also validate MQTT settings

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    tvs = config.get("tvs", {})

    if not tvs:
        errors.append("No TVs configured in 'tvs' section")
    else:
        for tv_id, tv_config in tvs.items():
            if not tv_config.get("host"):
                errors.append(f"tvs.{tv_id}.host is required")

    if for_bridge:
        mqtt = config.get("mqtt", {})
        if not mqtt.get("host"):
            errors.append("mqtt.host is required for bridge mode")

        # For bridge, need at least one TV with host
        if tvs:
            has_valid_tv = any(tv.get("host") for tv in tvs.values())
            if not has_valid_tv:
                errors.append("At least one TV must have a host configured")

    return errors


def get_tv_by_id_or_alias(config: Dict, id_or_alias: str) -> Optional[Dict]:
    """Get TV config by device_id or alias.

    Args:
        config: Full configuration dictionary
        id_or_alias: Device ID or alias to find

    Returns:
        TV config dict if found, None otherwise
    """
    tvs = config.get("tvs", {})

    # Direct match by device_id
    if id_or_alias in tvs:
        return tvs[id_or_alias]

    # Search by alias
    for device_id, tv_config in tvs.items():
        if tv_config.get("alias") == id_or_alias:
            return tv_config

    return None


def get_device_id_by_alias(config: Dict, alias: str) -> Optional[str]:
    """Get device_id for a given alias.

    Args:
        config: Full configuration dictionary
        alias: Alias to find

    Returns:
        Device ID if found, None otherwise
    """
    tvs = config.get("tvs", {})

    for device_id, tv_config in tvs.items():
        if tv_config.get("alias") == alias:
            return device_id

    return None


def device_id_to_mac(device_id: str) -> str:
    """Convert device_id (network_type) to MAC address format.

    Args:
        device_id: Device ID without colons (e.g., "84c8a0c0ce8f")

    Returns:
        MAC address with colons (e.g., "84:C8:A0:C0:CE:8F")
    """
    # Remove any existing separators and convert to uppercase
    clean_id = device_id.replace(":", "").replace("-", "").upper()

    if len(clean_id) != 12:
        return device_id  # Return as-is if not valid MAC length

    return ":".join(clean_id[i:i+2] for i in range(0, 12, 2))
