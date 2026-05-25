"""Main bridge class for hisense2mqtt."""

import json
import logging
import signal
import sys
import threading
import time
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

# Import from sibling package
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])
from hisense_tv.client import HisenseTV
from hisense_tv.wol import wake_tv
from hisense_tv.keys import ALL_KEYS

from .config import expand_tv_configs, get_device_id, load_config, validate_config
from .discovery import generate_all_discoveries, remove_all_discoveries

logger = logging.getLogger(__name__)


class HisenseMQTTBridge:
    """Bridge between MQTT broker and Hisense TV."""

    def __init__(self, config: dict):
        """Initialize the bridge.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.device_id = get_device_id(config)
        self.running = False

        # State tracking
        self._power_state = "OFF"
        self._volume = 0
        self._mute = False
        self._source = "unknown"
        self._available = False
        self._tv_info: Optional[dict] = None  # Device info from TV
        self._app_list: list[dict] = []  # Apps from TV
        self._app_names: dict[str, str] = {}  # Map lowercase -> pretty name

        # MQTT client for broker (Home Assistant)
        self._broker_client: Optional[mqtt.Client] = None

        # Hisense TV client
        self._tv: Optional[HisenseTV] = None

        # Threading
        self._poll_thread: Optional[threading.Thread] = None
        self._reconnect_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _setup_broker_client(self):
        """Set up MQTT broker client."""
        mqtt_config = self.config.get("mqtt", {})
        # Make client_id unique by including device_id
        base_id = mqtt_config.get("client_id", "hisense2mqtt")
        client_id = f"{base_id}_{self.device_id}"

        self._broker_client = mqtt.Client(client_id=client_id, clean_session=True)

        # Auth
        username = mqtt_config.get("username")
        password = mqtt_config.get("password")
        if username:
            self._broker_client.username_pw_set(username, password)

        # Callbacks
        self._broker_client.on_connect = self._on_broker_connect
        self._broker_client.on_disconnect = self._on_broker_disconnect
        self._broker_client.on_message = self._on_broker_message

        # Last Will and Testament
        self._broker_client.will_set(
            f"hisense2mqtt/{self.device_id}/state/available",
            payload="offline",
            qos=1,
            retain=True,
        )

    def _setup_tv_client(self):
        """Set up (or rebuild) the Hisense TV client.

        Rebuilding re-reads saved-token status from storage, so a reconnect
        after the access token expires picks up the refresh path instead of
        reusing a stale token.
        """
        if self._tv is not None:
            try:
                self._tv.disconnect()
            except Exception:
                pass

        tv_config = self.config.get("tv", {})

        self._tv = HisenseTV(
            host=tv_config["host"],
            port=tv_config.get("port", 36669),
            mac_address=tv_config.get("uuid"),
            use_dynamic_auth=True,
            brand=self._resolve_brand(tv_config),
            on_state_change=self._on_tv_state_change,
        )

    def _resolve_brand(self, tv_config: dict) -> str:
        """Resolve the TV brand for dynamic-auth credentials.

        brand is part of the MQTT client_id and credential hashes, so a
        non-Hisense VIDAA OEM needs its own brand string or auth fails. An
        explicitly configured brand wins; otherwise (unset or the "his" default)
        we probe the TV's UPnP descriptor, falling back to "his".
        """
        brand = tv_config.get("brand")
        if brand and brand != "his":
            return brand

        try:
            from hisense_tv.discovery import probe_ip

            device = probe_ip(tv_config["host"], timeout=3.0)
            if device and device.brand:
                logger.info("Discovered TV brand via UPnP: %s", device.brand)
                return device.brand
        except Exception as err:
            logger.debug("Could not probe brand for %s: %s", tv_config.get("host"), err)

        return brand or "his"

    def _on_broker_connect(self, client, userdata, flags, rc):
        """Handle broker connection."""
        if rc == 0:
            logger.info("Connected to MQTT broker")

            # Subscribe to command topics
            base = f"hisense2mqtt/{self.device_id}/set"
            topics = [
                (f"{base}/power", 0),
                (f"{base}/volume", 0),
                (f"{base}/mute", 0),
                (f"{base}/source", 0),
                (f"{base}/key", 0),
                (f"{base}/app", 0),
            ]
            client.subscribe(topics)
            logger.info(f"Subscribed to command topics: {base}/#")

            # Publish discovery
            if self.config.get("options", {}).get("discovery", True):
                self._publish_discovery()

            # Publish availability
            self._publish_availability(True)

        else:
            logger.error(f"Failed to connect to MQTT broker: {rc}")

    def _on_broker_disconnect(self, client, userdata, rc):
        """Handle broker disconnection."""
        logger.warning(f"Disconnected from MQTT broker: {rc}")

    def _on_broker_message(self, client, userdata, msg):
        """Handle incoming MQTT messages."""
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8").strip()
        except Exception:
            payload = str(msg.payload)

        logger.debug(f"Received: {topic} = {payload}")

        # Parse topic
        parts = topic.split("/")
        if len(parts) >= 4 and parts[2] == "set":
            command = parts[3]
            self._handle_command(command, payload)

    def _handle_command(self, command: str, payload: str):
        """Handle a command from MQTT."""
        logger.info(f"Command: {command} = {payload}")

        if command == "power":
            self._handle_power(payload)
        elif command == "volume":
            self._handle_volume(payload)
        elif command == "mute":
            self._handle_mute(payload)
        elif command == "source":
            self._handle_source(payload)
        elif command == "key":
            self._handle_key(payload)
        elif command == "app":
            self._handle_app(payload)

    def _handle_power(self, payload: str):
        """Handle power command."""
        payload = payload.upper()

        if payload == "ON":
            # Try Wake-on-LAN first if configured
            mac = self.config.get("tv", {}).get("mac")
            if mac and self.config.get("options", {}).get("wake_on_lan", True):
                logger.info(f"Sending Wake-on-LAN to {mac}")
                tv_host = self.config.get("tv", {}).get("host", "")
                subnet = ".".join(tv_host.split(".")[:3]) if "." in tv_host else None
                wake_tv(mac, subnet)
                time.sleep(3)

            # Connect to TV
            if not self._tv.is_connected:
                self._connect_tv()

            if self._tv.is_connected:
                # Send power on (some TVs need this after WoL)
                self._tv.power()
                self._power_state = "ON"
                self._publish_state("power", "ON")

        elif payload == "OFF":
            if self._ensure_tv_connected():
                self._tv.power()
                self._power_state = "OFF"
                self._publish_state("power", "OFF")

    def _handle_volume(self, payload: str):
        """Handle volume command."""
        try:
            volume = int(float(payload))
            volume = max(0, min(100, volume))
        except ValueError:
            logger.error(f"Invalid volume value: {payload}")
            return

        if self._ensure_tv_connected():
            self._tv.set_volume(volume)
            self._volume = volume
            self._publish_state("volume", str(volume))

    def _handle_mute(self, payload: str):
        """Handle mute command."""
        if self._ensure_tv_connected():
            self._tv.mute()
            # Toggle mute state
            self._mute = not self._mute
            self._publish_state("mute", "ON" if self._mute else "OFF")

    def _handle_source(self, payload: str):
        """Handle source command."""
        source = payload.lower().replace(" ", "")

        if self._ensure_tv_connected():
            self._tv.set_source(source)
            self._source = payload
            self._publish_state("source", payload)

    def _handle_key(self, payload: str):
        """Handle key command."""
        key = payload.upper()
        if not key.startswith("KEY_"):
            key = f"KEY_{key}"

        if key not in ALL_KEYS:
            logger.warning(f"Unknown key: {payload}")
            return

        if self._ensure_tv_connected():
            self._tv.send_key(key)
            logger.info(f"Sent key: {key}")

    def _handle_app(self, payload: str):
        """Handle app launch command."""
        app_name = payload.lower()

        if self._ensure_tv_connected():
            if self._tv.launch_app(app_name):
                logger.info(f"Launched app: {app_name}")
            else:
                logger.warning(f"Failed to launch app: {app_name}")

    def _ensure_tv_connected(self) -> bool:
        """Ensure TV is connected, attempt reconnect if not."""
        if self._tv and self._tv.is_connected:
            return True

        logger.info("TV not connected, attempting to connect...")
        return self._connect_tv()

    def _connect_tv(self) -> bool:
        """Connect to TV.

        Rebuilds the client first so an expired access token is refreshed from
        the still-valid refresh token instead of being replayed and rejected.
        """
        try:
            self._setup_tv_client()
            if self._tv.connect(timeout=10):
                logger.info("Connected to TV")
                self._available = True
                self._publish_availability(True)

                # Fetch device info from TV
                self._fetch_device_info()

                # Fetch app list from TV
                self._fetch_app_list()

                return True
            else:
                logger.warning("Failed to connect to TV")
                self._available = False
                self._publish_availability(False)
                return False
        except Exception as e:
            logger.error(f"Error connecting to TV: {e}")
            self._available = False
            self._publish_availability(False)
            return False

    def _fetch_device_info(self):
        """Fetch device info from TV and update config."""
        try:
            device_info = self._tv.get_device_info(timeout=5)
            if device_info:
                logger.info(f"Got device info: {device_info.get('tv_name')} - {device_info.get('model_name')}")
                self._tv_info = device_info

                # Update config with TV info (for discovery)
                tv_config = self.config.get("tv", {})
                if device_info.get("tv_name"):
                    tv_config["name"] = device_info["tv_name"]
                if device_info.get("model_name"):
                    tv_config["model"] = device_info["model_name"]
                if device_info.get("tv_version"):
                    tv_config["sw_version"] = device_info["tv_version"]

                # Re-publish discovery with updated info
                if self._broker_client and self._broker_client.is_connected():
                    self._publish_discovery()
        except Exception as e:
            logger.warning(f"Failed to fetch device info: {e}")

    def _fetch_app_list(self):
        """Fetch app list from TV and build name mappings."""
        try:
            apps = self._tv.get_apps(timeout=5)
            if apps:
                self._app_list = apps
                # Build lowercase -> pretty name mapping
                self._app_names = {}
                app_names = []
                for app in apps:
                    name = app.get("name", "")
                    if name:
                        self._app_names[name.lower()] = name
                        app_names.append(name)

                logger.info(f"Got {len(app_names)} apps from TV")

                # Re-publish discovery with app list
                if self._broker_client and self._broker_client.is_connected():
                    self._publish_discovery()

                # Re-query state to publish current app with pretty name
                state = self._tv.get_state(timeout=3)
                if state and state.get("statetype") == "app":
                    app_name = state.get("name", "")
                    if app_name:
                        pretty_name = self._app_names.get(app_name.lower(), app_name)
                        self._publish_state("app", pretty_name)
                        self._publish_state("source", pretty_name)
                        logger.debug(f"Re-published current app: {pretty_name}")
        except Exception as e:
            logger.warning(f"Failed to fetch app list: {e}")

    def _on_tv_state_change(self, state: dict):
        """Handle TV state changes (callback from TV client)."""
        logger.debug(f"TV state change: {state}")
        self._process_state(state)

    def _process_state(self, state: dict):
        """Process TV state and publish updates."""
        if "statetype" not in state:
            return

        state_type = state.get("statetype")

        # Detect power state from TV broadcasts
        if state_type == "fake_sleep_0":
            # TV is off (standby)
            if self._power_state != "OFF":
                self._power_state = "OFF"
                self._publish_state("power", "OFF")
                logger.info("TV power state: OFF (standby)")
        elif state_type in ("app", "livetv", "remote_launcher", "sourceswitch", "hdmi"):
            # TV is on
            if self._power_state != "ON":
                self._power_state = "ON"
                self._publish_state("power", "ON")
                logger.info(f"TV power state: ON ({state_type})")

        # Handle source changes
        if state_type == "sourceswitch":
            self._source = state.get("sourcename", self._source)
            self._publish_state("source", self._source)

        # Handle app state - publish current app
        if state_type == "app":
            app_name = state.get("name", "")
            if app_name:
                # Use pretty name from app list if available
                pretty_name = self._app_names.get(app_name.lower())
                if pretty_name:
                    logger.debug(f"App '{app_name}' -> pretty name '{pretty_name}'")
                else:
                    pretty_name = app_name
                    logger.debug(f"App '{app_name}' (no pretty name mapping)")
                self._publish_state("app", pretty_name)
                self._publish_state("source", pretty_name)
        elif state_type == "remote_launcher":
            self._publish_state("app", "Home")
        elif state_type == "livetv":
            self._publish_state("app", "Live TV")
            self._publish_state("source", "TV")
        elif state_type == "fake_sleep_0":
            self._publish_state("app", "Off")

    def _publish_state(self, state_type: str, value: str):
        """Publish state to MQTT broker."""
        if self._broker_client and self._broker_client.is_connected():
            topic = f"hisense2mqtt/{self.device_id}/state/{state_type}"
            self._broker_client.publish(topic, value, qos=0, retain=True)
            logger.debug(f"Published: {topic} = {value}")

    def _publish_availability(self, available: bool):
        """Publish availability to MQTT broker."""
        if self._broker_client and self._broker_client.is_connected():
            topic = f"hisense2mqtt/{self.device_id}/state/available"
            value = "online" if available else "offline"
            self._broker_client.publish(topic, value, qos=1, retain=True)
            logger.info(f"Availability: {value}")

    def _publish_discovery(self):
        """Publish Home Assistant discovery messages."""
        logger.info("Publishing Home Assistant discovery...")

        # Get app names list (use pretty names from TV if available)
        app_names = None
        if self._app_list:
            app_names = [app.get("name") for app in self._app_list if app.get("name")]

        discoveries = generate_all_discoveries(self.config, self.device_id, apps=app_names)

        for topic, payload in discoveries:
            self._broker_client.publish(topic, json.dumps(payload), qos=0, retain=True)
            logger.debug(f"Discovery: {topic}")

        logger.info(f"Published {len(discoveries)} discovery messages")

    def _remove_discovery(self):
        """Remove Home Assistant discovery messages."""
        logger.info("Removing Home Assistant discovery...")

        topics = remove_all_discoveries(self.config, self.device_id)

        for topic in topics:
            self._broker_client.publish(topic, "", qos=0, retain=True)

    # Refresh the access token when it has less than this long until expiry.
    _TOKEN_REFRESH_THRESHOLD = 24 * 60 * 60  # 1 day

    def _maybe_refresh_token(self):
        """Proactively refresh the access token while connected.

        The access token lasts ~7 days; refreshing before it expires keeps a
        long-running, continuously-connected bridge authenticated without a
        restart. A successful refresh persists a new token to storage, so the
        expiry check naturally stops firing afterwards.
        """
        try:
            from hisense_tv.config import get_storage

            tv_config = self.config.get("tv", {})
            host = tv_config.get("host")
            port = tv_config.get("port", 36669)
            if not host:
                return

            status = get_storage().get_token_status(host=host, port=port)
            if not status.get("has_token"):
                return

            if status.get("needs_reauth"):
                logger.warning(
                    "%s: both tokens expired - re-pair with 'tv --ip %s auth pair'",
                    host, host,
                )
                return

            near_expiry = (
                status.get("access_valid")
                and status.get("access_expires_in", 0) < self._TOKEN_REFRESH_THRESHOLD
            )
            if status.get("needs_refresh") or near_expiry:
                logger.info(
                    "Access token near expiry (%ss left), refreshing...",
                    status.get("access_expires_in", 0),
                )
                if self._tv.refresh_token():
                    logger.info("Access token refreshed")
                else:
                    logger.warning("Proactive token refresh failed")
        except Exception as e:
            logger.debug("Token refresh check failed: %s", e)

    def _poll_state(self):
        """Poll TV state periodically."""
        interval = self.config.get("options", {}).get("poll_interval", 30)
        logger.info(f"Poll thread started (interval: {interval}s)")

        while self.running:
            try:
                if self._tv and self._tv.is_connected:
                    # Renew the access token before it lapses while connected.
                    self._maybe_refresh_token()

                    logger.info("Polling TV state...")

                    # Get current state (statetype, app, etc)
                    state = self._tv.get_state(timeout=3)
                    if state:
                        logger.info(f"Poll: statetype={state.get('statetype')}, name={state.get('name', 'N/A')}")
                        self._process_state(state)
                    else:
                        logger.warning("Poll: get_state returned None")

                    # Get volume
                    volume = self._tv.get_volume(timeout=3)
                    if volume is not None and volume != self._volume:
                        self._volume = volume
                        self._publish_state("volume", str(volume))

                else:
                    logger.debug(f"TV not connected (tv={self._tv is not None}, connected={self._tv.is_connected if self._tv else False})")
                    # Try to reconnect
                    if self._power_state == "ON":
                        # TV might have turned off
                        self._power_state = "OFF"
                        self._publish_state("power", "OFF")
                        self._publish_state("app", "Off")

                    if not self._available:
                        logger.info("Attempting to reconnect to TV...")
                        self._connect_tv()

            except Exception as e:
                logger.error(f"Poll error: {e}", exc_info=True)

            # Sleep in intervals for responsive shutdown
            for _ in range(interval):
                if not self.running:
                    break
                time.sleep(1)

    def start(self):
        """Start the bridge."""
        logger.info("Starting hisense2mqtt bridge...")

        # Validate config
        errors = validate_config(self.config)
        if errors:
            for error in errors:
                logger.error(f"Config error: {error}")
            raise ValueError("Invalid configuration")

        self.running = True

        # Set up broker client (the TV client is built on each _connect_tv,
        # so token status is re-evaluated from storage every reconnect).
        self._setup_broker_client()

        # Connect to MQTT broker with retry
        mqtt_config = self.config.get("mqtt", {})
        host = mqtt_config.get("host", "localhost")
        port = mqtt_config.get("port", 1883)
        reconnect_interval = self.config.get("options", {}).get("reconnect_interval", 30)

        logger.info(f"Connecting to MQTT broker at {host}:{port}")
        broker_connected = False
        while self.running and not broker_connected:
            try:
                self._broker_client.connect(host, port, keepalive=60)
                self._broker_client.loop_start()
                broker_connected = True
            except Exception as e:
                logger.error(f"Failed to connect to MQTT broker: {e}")
                logger.info(f"Retrying in {reconnect_interval} seconds...")
                for _ in range(reconnect_interval):
                    if not self.running:
                        return
                    time.sleep(1)

        if not broker_connected:
            return

        # Connect to TV
        self._connect_tv()

        # Start polling thread
        self._poll_thread = threading.Thread(target=self._poll_state, daemon=True)
        self._poll_thread.start()

        logger.info("hisense2mqtt bridge started")

    def stop(self):
        """Stop the bridge."""
        logger.info("Stopping hisense2mqtt bridge...")
        self.running = False

        # Publish offline status
        self._publish_availability(False)

        # Disconnect TV
        if self._tv:
            try:
                self._tv.disconnect()
            except Exception:
                pass

        # Disconnect broker
        if self._broker_client:
            try:
                self._broker_client.loop_stop()
                self._broker_client.disconnect()
            except Exception:
                pass

        # Wait for threads
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5)

        logger.info("hisense2mqtt bridge stopped")

    def run_forever(self):
        """Run the bridge until interrupted."""
        # Set up signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        self.start()

        # Keep running
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


class HisenseMQTTMultiBridge:
    """Run one HisenseMQTTBridge per configured TV.

    Each TV gets its own scoped config (unique device_id, broker client_id,
    LWT and topic namespace), so a single broker can expose several TVs as
    separate Home Assistant devices.
    """

    def __init__(self, config: dict):
        """Initialize a bridge per TV found in the config."""
        self.scoped_configs = expand_tv_configs(config)
        self.bridges = [HisenseMQTTBridge(cfg) for cfg in self.scoped_configs]
        self.running = False
        self._threads: list[threading.Thread] = []

    def _tv_host(self, bridge: HisenseMQTTBridge) -> str:
        return bridge.config.get("tv", {}).get("host", "?")

    def _start_bridge(self, bridge: HisenseMQTTBridge):
        """Start one bridge, isolating failures so one TV can't stop the rest."""
        try:
            bridge.start()
        except Exception as e:
            logger.error("Failed to start bridge for %s: %s", self._tv_host(bridge), e)

    def start(self):
        """Start all bridges concurrently (each may block on broker/TV connect)."""
        logger.info("Starting %d TV bridge(s)...", len(self.bridges))
        self.running = True
        for bridge in self.bridges:
            thread = threading.Thread(
                target=self._start_bridge, args=(bridge,), daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def stop(self):
        """Stop all bridges."""
        logger.info("Stopping all TV bridges...")
        self.running = False
        for bridge in self.bridges:
            try:
                bridge.stop()
            except Exception:
                pass

    def run_forever(self):
        """Run all bridges until interrupted."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        self.start()

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
