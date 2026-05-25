"""Configuration management for hisense2mqtt."""

import os
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_CONFIG = {
    "mqtt": {
        "host": "localhost",
        "port": 1883,
        "username": None,
        "password": None,
        "discovery_prefix": "homeassistant",
        "client_id": "hisense2mqtt",
    },
    "tv": {
        "host": None,  # Required
        "port": 36669,
        "mac": None,  # For WoL
        "uuid": None,  # Required - paired UUID
        "name": "Hisense TV",
        "brand": "his",
    },
    "options": {
        "poll_interval": 30,
        "wake_on_lan": True,
        "discovery": True,
        "reconnect_interval": 30,
        "log_level": "INFO",
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_uuid(entry: dict, host: Optional[str], port: int) -> Optional[str]:
    """Resolve the credential UUID for a TV.

    Order: explicit `uuid`, the entry `mac`, then the uuid persisted in
    tokens.json when the TV was paired via the CLI / Vidaa app.
    """
    uuid = entry.get("uuid") or entry.get("mac")
    if uuid or not host:
        return uuid
    try:
        from hisense_tv.config import get_storage

        token = get_storage().get_token(host=host, port=port)
        if token:
            return token.get("uuid")
    except Exception:
        pass
    return None


def _scoped_tv(entry: dict, key: Optional[str] = None) -> dict:
    """Build a singular `tv:` section from a multi-TV entry (or singular dict)."""
    host = entry.get("host") or key
    port = entry.get("port", 36669)
    return {
        "host": host,
        "port": port,
        "mac": entry.get("mac"),
        "uuid": _resolve_uuid(entry, host, port),
        "name": entry.get("name") or entry.get("alias") or "Hisense TV",
        # Leave unset (None) when not explicitly configured so the bridge can
        # auto-discover the brand from the TV's UPnP descriptor.
        "brand": entry.get("brand"),
    }


def expand_tv_configs(config: dict) -> list[dict]:
    """Expand a loaded config into one scoped single-TV config per TV.

    Supports both the multi-TV schema (`tvs:` mapping, used by the CLI/library
    and config.example.yaml) and the legacy singular `tv:` section. Each result
    is a self-contained config of shape {mqtt, options, tv, _config_path} that
    the bridge and discovery code can consume unchanged.
    """
    base = {
        "mqtt": config.get("mqtt", {}),
        "options": config.get("options", {}),
        "_config_path": config.get("_config_path"),
    }

    tvs = config.get("tvs")
    scoped: list[dict] = []
    if isinstance(tvs, dict) and tvs:
        for key, entry in tvs.items():
            if isinstance(entry, dict):
                scoped.append({**base, "tv": _scoped_tv(entry, key)})
    elif config.get("tv", {}).get("host"):
        # Legacy singular tv: section - use as-is.
        scoped.append({**base, "tv": config.get("tv", {})})

    return scoped


def load_config(config_path: Optional[str] = None) -> dict:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, searches default locations.

    Returns:
        Merged configuration dict
    """
    # Search paths in order
    search_paths = []
    if config_path:
        search_paths.append(Path(config_path))
    search_paths.extend([
        Path("config.yaml"),
        Path("/app/config.yaml"),
        Path.home() / ".config" / "hisense2mqtt" / "config.yaml",
        Path("/etc/hisense2mqtt/config.yaml"),
    ])

    config = DEFAULT_CONFIG.copy()

    for path in search_paths:
        if path.exists():
            with open(path) as f:
                user_config = yaml.safe_load(f) or {}
            config = deep_merge(config, user_config)
            config["_config_path"] = str(path)
            break

    # Environment variable overrides
    env_mappings = {
        "MQTT_HOST": ("mqtt", "host"),
        "MQTT_PORT": ("mqtt", "port"),
        "MQTT_USERNAME": ("mqtt", "username"),
        "MQTT_PASSWORD": ("mqtt", "password"),
        "TV_HOST": ("tv", "host"),
        "TV_PORT": ("tv", "port"),
        "TV_MAC": ("tv", "mac"),
        "TV_UUID": ("tv", "uuid"),
        "TV_NAME": ("tv", "name"),
        "POLL_INTERVAL": ("options", "poll_interval"),
        "LOG_LEVEL": ("options", "log_level"),
    }

    for env_var, (section, key) in env_mappings.items():
        value = os.environ.get(env_var)
        if value is not None:
            # Convert port to int
            if key == "port":
                value = int(value)
            elif key == "poll_interval":
                value = int(value)
            config[section][key] = value

    return config


def validate_config(config: dict) -> list[str]:
    """Validate configuration and return list of errors."""
    errors = []

    if not config.get("tv", {}).get("host"):
        errors.append("tv.host is required")

    if not config.get("tv", {}).get("uuid"):
        errors.append("tv.uuid is required (use UUID paired via Vidaa app)")

    if not config.get("mqtt", {}).get("host"):
        errors.append("mqtt.host is required")

    return errors


def get_device_id(config: dict) -> str:
    """Generate a unique device ID from config."""
    tv_host = config.get("tv", {}).get("host", "unknown")
    # Use last octet of IP or full host
    if "." in tv_host:
        return tv_host.replace(".", "_")
    return tv_host.replace("-", "_").replace(".", "_")
