"""Hisense TV control library via MQTT.

Protocol details discovered from Vidaa APK decompilation.
"""

from .client import HisenseTV
from .keys import (
    # Power
    KEY_POWER,
    # Navigation
    KEY_UP,
    KEY_DOWN,
    KEY_LEFT,
    KEY_RIGHT,
    KEY_OK,
    KEY_ENTER,
    KEY_OK_LONG_PRESS,
    # Menu/Back
    KEY_MENU,
    KEY_BACK,
    KEY_RETURNS,
    KEY_EXIT,
    KEY_HOME,
    # Volume
    KEY_VOLUME_UP,
    KEY_VOLUME_DOWN,
    KEY_MUTE,
    KEY_MUTE_LONG_PRESS,
    # Voice
    KEY_VOICE_UP,
    KEY_VOICE_DOWN,
    # Playback
    KEY_PLAY,
    KEY_PAUSE,
    KEY_STOP,
    KEY_FAST_FORWARD,
    KEY_REWIND,
    # Numbers
    KEY_0,
    KEY_1,
    KEY_2,
    KEY_3,
    KEY_4,
    KEY_5,
    KEY_6,
    KEY_7,
    KEY_8,
    KEY_9,
    # Channel
    KEY_CHANNEL_UP,
    KEY_CHANNEL_DOWN,
    KEY_CHANNEL_DOT,
    # Color buttons
    KEY_RED,
    KEY_GREEN,
    KEY_YELLOW,
    KEY_BLUE,
    # Extras
    KEY_SUBTITLE,
    KEY_INFO,
    # Mouse/Pointer
    KEY_LEFT_MOUSE,
    KEY_UDD_LEFT_MOUSE,
    KEY_UDU_LEFT_MOUSE,
    KEY_ZOOM_IN,
    KEY_ZOOM_OUT,
    # Utilities
    ALL_KEYS,
    KEY_NAME_MAP,
    get_key,
)
from .topics import (
    SOURCE_TV,
    SOURCE_HDMI1,
    SOURCE_HDMI2,
    SOURCE_HDMI3,
    SOURCE_HDMI4,
    SOURCE_AV,
    SOURCE_COMPONENT,
    SOURCE_MAP,
    APPS,
)
from .protocol import (
    AuthMethod,
    detect_protocol,
    get_auth_method,
    get_auth_method_order,
)
from .config import (
    # Config loading
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
    # Backwards compatibility
    get_tv_ip,
    get_tv_port,
    get_tv_mac,
    set_tv_ip,
    set_tv_mac,
    # Token storage
    TokenStorage,
    get_storage,
    get_token,
    save_token,
    delete_token,
    get_token_status,
    # Constants
    DEFAULT_PORT,
    DISCOVERY_PORT,
    SSDP_ADDR,
    SSDP_PORT,
    UPNP_PORT,
    UPNP_PORTS,
    BROADCAST_ADDR,
    DEFAULT_MQTT_USERNAME,
    DEFAULT_MQTT_PASSWORD,
    DEFAULT_CLIENT_ID,
    DEFAULT_BRAND,
    PROTOCOL_MODERN_THRESHOLD,
    PROTOCOL_MIDDLE_THRESHOLD,
)
from .discovery import (
    DiscoveredTV,
    discover_ssdp,
    listen_ssdp,
    discover_udp,
    probe_ip,
    discover_all,
)
from .async_client import (
    AsyncHisenseTV,
    async_discover_ssdp,
    async_discover_udp,
    async_probe_ip,
    async_discover_all,
    async_detect_protocol,
)

__version__ = "1.7.0"
__all__ = [
    "HisenseTV",
    # Power
    "KEY_POWER",
    # Navigation
    "KEY_UP",
    "KEY_DOWN",
    "KEY_LEFT",
    "KEY_RIGHT",
    "KEY_OK",
    "KEY_ENTER",
    "KEY_OK_LONG_PRESS",
    # Menu/Back
    "KEY_MENU",
    "KEY_BACK",
    "KEY_RETURNS",
    "KEY_EXIT",
    "KEY_HOME",
    # Volume
    "KEY_VOLUME_UP",
    "KEY_VOLUME_DOWN",
    "KEY_MUTE",
    "KEY_MUTE_LONG_PRESS",
    # Voice
    "KEY_VOICE_UP",
    "KEY_VOICE_DOWN",
    # Playback
    "KEY_PLAY",
    "KEY_PAUSE",
    "KEY_STOP",
    "KEY_FAST_FORWARD",
    "KEY_REWIND",
    # Numbers
    "KEY_0",
    "KEY_1",
    "KEY_2",
    "KEY_3",
    "KEY_4",
    "KEY_5",
    "KEY_6",
    "KEY_7",
    "KEY_8",
    "KEY_9",
    # Channel
    "KEY_CHANNEL_UP",
    "KEY_CHANNEL_DOWN",
    "KEY_CHANNEL_DOT",
    # Color buttons
    "KEY_RED",
    "KEY_GREEN",
    "KEY_YELLOW",
    "KEY_BLUE",
    # Extras
    "KEY_SUBTITLE",
    "KEY_INFO",
    # Mouse/Pointer
    "KEY_LEFT_MOUSE",
    "KEY_UDD_LEFT_MOUSE",
    "KEY_UDU_LEFT_MOUSE",
    "KEY_ZOOM_IN",
    "KEY_ZOOM_OUT",
    # Utilities
    "ALL_KEYS",
    "KEY_NAME_MAP",
    "get_key",
    # Sources
    "SOURCE_TV",
    "SOURCE_HDMI1",
    "SOURCE_HDMI2",
    "SOURCE_HDMI3",
    "SOURCE_HDMI4",
    "SOURCE_AV",
    "SOURCE_COMPONENT",
    "SOURCE_MAP",
    "APPS",
    # Storage
    "TokenStorage",
    "get_storage",
    # Protocol detection
    "AuthMethod",
    "detect_protocol",
    "get_auth_method",
    "get_auth_method_order",
    "PROTOCOL_MODERN_THRESHOLD",
    "PROTOCOL_MIDDLE_THRESHOLD",
    # Config
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
    # Backwards compatibility
    "get_tv_ip",
    "get_tv_port",
    "get_tv_mac",
    "set_tv_ip",
    "set_tv_mac",
    # Token storage
    "TokenStorage",
    "get_storage",
    "get_token",
    "save_token",
    "delete_token",
    "get_token_status",
    # Constants
    "DEFAULT_PORT",
    "DEFAULT_MQTT_USERNAME",
    "DEFAULT_MQTT_PASSWORD",
    "DEFAULT_CLIENT_ID",
    "DEFAULT_BRAND",
    # Discovery
    "DiscoveredTV",
    "discover_ssdp",
    "listen_ssdp",
    "discover_udp",
    "probe_ip",
    "discover_all",
    "DISCOVERY_PORT",
    "SSDP_ADDR",
    "SSDP_PORT",
    # Async
    "AsyncHisenseTV",
    "async_discover_ssdp",
    "async_discover_udp",
    "async_probe_ip",
    "async_discover_all",
    "async_detect_protocol",
]
