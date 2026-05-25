"""Unified configuration management for Hisense TV control.

Provides:
- YAML-based configuration with environment variable overrides
- Multi-TV support with device_id (network_type) as unique identifier
- Unified token storage
- Automatic migration from legacy JSON config
- Single source of truth for all constants
"""

# Constants - single source of truth
from .constants import (
    # Network
    DEFAULT_PORT,
    DISCOVERY_PORT,
    SSDP_ADDR,
    SSDP_PORT,
    UPNP_PORT,
    UPNP_PORTS,
    BROADCAST_ADDR,
    # Authentication
    DEFAULT_MQTT_USERNAME,
    DEFAULT_MQTT_PASSWORD,
    # Client identification
    DEFAULT_CLIENT_ID,
    DEFAULT_BRAND,
    # Protocol thresholds
    PROTOCOL_MODERN_THRESHOLD,
    PROTOCOL_MIDDLE_THRESHOLD,
    # Credential generation
    PATTERN,
    VALUE_SUFFIX_MODERN,
    VALUE_SUFFIX_LEGACY,
    TIME_XOR_CONSTANT,
    # Token durations
    DEFAULT_ACCESS_TOKEN_DAYS,
    DEFAULT_REFRESH_TOKEN_DAYS,
    # Certificate paths
    DEFAULT_CERT_FILENAME,
    DEFAULT_KEY_FILENAME,
)

# Schema and validation
from .schema import (
    DEFAULT_CONFIG,
    DEFAULT_TV_CONFIG,
    deep_merge,
    validate_config,
    get_tv_by_id_or_alias,
    get_device_id_by_alias,
    device_id_to_mac,
)

# Configuration loading
from .loader import (
    load_config,
    save_config,
    get_config,
    reload_config,
    get_config_path,
    get_tv_config,
    get_default_tv,
    list_tvs,
    resolve_tv_id,
    update_tv_config,
    add_tv,
    set_default_tv,
    CONFIG_SEARCH_PATHS,
    # Backwards compatibility
    get_tv_ip,
    get_tv_port,
    get_tv_mac,
    set_tv_ip,
    set_tv_mac,
)

# Token storage
from .storage import (
    TokenStorage,
    get_storage,
    get_token,
    save_token,
    delete_token,
    get_token_status,
)


__all__ = [
    # Constants
    "DEFAULT_PORT",
    "DISCOVERY_PORT",
    "SSDP_ADDR",
    "SSDP_PORT",
    "UPNP_PORT",
    "UPNP_PORTS",
    "BROADCAST_ADDR",
    "DEFAULT_MQTT_USERNAME",
    "DEFAULT_MQTT_PASSWORD",
    "DEFAULT_CLIENT_ID",
    "DEFAULT_BRAND",
    "PROTOCOL_MODERN_THRESHOLD",
    "PROTOCOL_MIDDLE_THRESHOLD",
    "PATTERN",
    "VALUE_SUFFIX_MODERN",
    "VALUE_SUFFIX_LEGACY",
    "TIME_XOR_CONSTANT",
    "DEFAULT_ACCESS_TOKEN_DAYS",
    "DEFAULT_REFRESH_TOKEN_DAYS",
    "DEFAULT_CERT_FILENAME",
    "DEFAULT_KEY_FILENAME",
    # Schema
    "DEFAULT_CONFIG",
    "DEFAULT_TV_CONFIG",
    "deep_merge",
    "validate_config",
    "get_tv_by_id_or_alias",
    "get_device_id_by_alias",
    "device_id_to_mac",
    # Loader
    "load_config",
    "save_config",
    "get_config",
    "reload_config",
    "get_config_path",
    "get_tv_config",
    "get_default_tv",
    "list_tvs",
    "resolve_tv_id",
    "update_tv_config",
    "add_tv",
    "set_default_tv",
    "CONFIG_SEARCH_PATHS",
    "get_tv_ip",
    "get_tv_port",
    "get_tv_mac",
    "set_tv_ip",
    "set_tv_mac",
    # Storage
    "TokenStorage",
    "get_storage",
    "get_token",
    "save_token",
    "delete_token",
    "get_token_status",
]
