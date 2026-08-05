"""MQTT topic definitions for Hisense TV."""

from .config import DEFAULT_CLIENT_ID

# Client ID used in topics (exported for backwards compatibility)
CLIENT_ID = DEFAULT_CLIENT_ID

# Command topics (publish to these)
TOPIC_SEND_KEY = "/remoteapp/tv/remote_service/{client}/actions/sendkey"
TOPIC_AUTH = "/remoteapp/tv/ui_service/{client}/actions/authenticationcode"
TOPIC_AUTH_CLOSE = "/remoteapp/tv/ui_service/{client}/actions/authenticationcodeclose"
TOPIC_VIDAA_CONNECT = "/remoteapp/tv/ui_service/{client}/actions/vidaa_app_connect"
TOPIC_GET_TOKEN = "/remoteapp/tv/platform_service/{client}/data/gettoken"
TOPIC_GET_STATE = "/remoteapp/tv/ui_service/{client}/actions/gettvstate"
TOPIC_GET_VOLUME = "/remoteapp/tv/platform_service/{client}/actions/getvolume"
TOPIC_SET_VOLUME = "/remoteapp/tv/platform_service/{client}/actions/changevolume"
TOPIC_GET_SOURCES = "/remoteapp/tv/ui_service/{client}/actions/sourcelist"
TOPIC_SET_SOURCE = "/remoteapp/tv/ui_service/{client}/actions/changesource"
TOPIC_GET_APPS = "/remoteapp/tv/ui_service/{client}/actions/applist"
TOPIC_LAUNCH_APP = "/remoteapp/tv/ui_service/{client}/actions/launchapp"
TOPIC_GET_TV_INFO = "/remoteapp/tv/platform_service/{client}/actions/gettvinfo"
TOPIC_GET_DEVICE_INFO = "/remoteapp/tv/platform_service/{client}/actions/getdeviceinfo"
TOPIC_GET_CAPABILITY = "/remoteapp/tv/ui_service/{client}/actions/capability"

# Response topics (subscribe to these)
TOPIC_STATE_RESPONSE = "/remoteapp/mobile/broadcast/ui_service/state"
# The TV announces standby here the instant it powers off, including from its
# own remote. Pre-dynamic firmware sends nothing else to say it is going away:
# it does not broadcast a fake_sleep_0 state, it simply stops answering.
TOPIC_TV_SLEEP = "/remoteapp/mobile/broadcast/platform_service/actions/tvsleep"
# Some firmware answers gettvstate here, addressed to the asking client,
# instead of (or as well as) re-broadcasting it.
TOPIC_STATE_DIRECT = "/remoteapp/mobile/{client}/ui_service/data/state"
TOPIC_VOLUME_RESPONSE = "/remoteapp/mobile/broadcast/ui_service/volume"
TOPIC_SOURCES_RESPONSE = "/remoteapp/mobile/{client}/ui_service/data/sourcelist"
TOPIC_APPS_RESPONSE = "/remoteapp/mobile/{client}/ui_service/data/applist"
TOPIC_AUTH_RESPONSE = "/remoteapp/mobile/{client}/ui_service/data/authentication"
TOPIC_AUTH_CODE_RESPONSE = "/remoteapp/mobile/{client}/ui_service/data/authenticationcode"
TOPIC_TOKEN_RESPONSE = "/remoteapp/mobile/{client}/platform_service/data/tokenissuance"
TOPIC_TV_INFO_RESPONSE = "/remoteapp/mobile/{client}/platform_service/data/gettvinfo"
TOPIC_DEVICE_INFO_RESPONSE = "/remoteapp/mobile/{client}/platform_service/data/getdeviceinfo"
TOPIC_CAPABILITY_RESPONSE = "/remoteapp/mobile/{client}/ui_service/data/capability"
# The TV's acknowledgement of a vidaa_app_connect request: {"connect_result": 1}.
# Confirmed by direct probe of a 32A35HUV (MTK9602, V0002.09.01O.P0814).
# It means the request was ACCEPTED, not that a PIN is on screen: an already
# authorized client gets the same reply with no dialog. The definitive
# "PIN is showing" signal remains the push to .../ui_service/data/authentication.
TOPIC_VIDAA_CONNECT_RESPONSE = "/remoteapp/mobile/{client}/ui_service/data/vidaa_app_connect"
# Hotel mode changes, broadcast to every client: {"hotel_mode": "off"}. In hotel
# mode the TV restricts source switching and app launches, so commands can be
# accepted and then silently ignored.
TOPIC_HOTEL_MODE = "/remoteapp/mobile/broadcast/ui_service/data/hotelmodechange"

# Source IDs
SOURCE_TV = "0"
SOURCE_AV = "1"
SOURCE_COMPONENT = "2"
SOURCE_HDMI1 = "3"
SOURCE_HDMI2 = "4"
SOURCE_HDMI3 = "5"
SOURCE_HDMI4 = "6"

SOURCE_MAP = {
    "tv": SOURCE_TV,
    "av": SOURCE_AV,
    "component": SOURCE_COMPONENT,
    "hdmi1": SOURCE_HDMI1,
    "hdmi2": SOURCE_HDMI2,
    "hdmi3": SOURCE_HDMI3,
    "hdmi4": SOURCE_HDMI4,
}

# App definitions (appId values from TV's app list)
# Note: appId values may vary by TV model/region - these are common defaults
APPS = {
    "netflix": {"appId": "1", "name": "Netflix", "url": "netflix"},
    "youtube": {"appId": "3", "name": "YouTube", "url": "youtube"},
    "amazon": {"appId": "2", "name": "Prime Video", "url": "amazon"},
    "prime": {"appId": "2", "name": "Prime Video", "url": "amazon"},
    "disney": {"appId": "295", "name": "Disney+", "url": "https://cd-dmgz.bamgrid.com/bbd/hisense_tv/index.html"},
    "disney+": {"appId": "295", "name": "Disney+", "url": "https://cd-dmgz.bamgrid.com/bbd/hisense_tv/index.html"},
    "tubi": {"appId": "216", "name": "tubi", "url": "https://ott-hisense.tubitv.com"},
}


def get_topic(topic_template: str, client_id: str = CLIENT_ID) -> str:
    """Format a topic template with the client ID."""
    return topic_template.format(client=client_id)
