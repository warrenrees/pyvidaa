"""Hisense TV MQTT client.

Provides control of Hisense/Vidaa TVs via MQTT over SSL/TLS.
Supports authentication, remote control, volume, sources, and apps.
"""

import json
import logging
import ssl
import threading
import time
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

from .config import (
    DEFAULT_PORT,
    DEFAULT_MQTT_USERNAME,
    DEFAULT_MQTT_PASSWORD,
    DEFAULT_CLIENT_ID,
    TokenStorage,
    get_storage,
)
from .certs import MISSING_CERT_HELP, bundled_ca_path, resolve_client_certs
from .credentials import generate_credentials, generate_credentials_static
from .keys import ALL_KEYS
from .protocol import AuthMethod, detect_protocol, get_auth_method, get_auth_method_order
from .topics import (
    APPS,
    CLIENT_ID,
    SOURCE_MAP,
    TOPIC_AUTH,
    TOPIC_AUTH_CLOSE,
    TOPIC_GET_TOKEN,
    TOPIC_VIDAA_CONNECT,
    TOPIC_GET_APPS,
    TOPIC_GET_SOURCES,
    TOPIC_GET_STATE,
    TOPIC_GET_VOLUME,
    TOPIC_GET_TV_INFO,
    TOPIC_GET_DEVICE_INFO,
    TOPIC_GET_CAPABILITY,
    TOPIC_LAUNCH_APP,
    TOPIC_SEND_KEY,
    TOPIC_SET_SOURCE,
    TOPIC_SET_VOLUME,
    TOPIC_APPS_RESPONSE,
    TOPIC_SOURCES_RESPONSE,
    TOPIC_STATE_RESPONSE,
    TOPIC_VOLUME_RESPONSE,
    TOPIC_AUTH_RESPONSE,
    TOPIC_AUTH_CODE_RESPONSE,
    TOPIC_TOKEN_RESPONSE,
    TOPIC_TV_INFO_RESPONSE,
    TOPIC_DEVICE_INFO_RESPONSE,
    TOPIC_CAPABILITY_RESPONSE,
    get_topic,
)


class HisenseTV:
    """Client to control Hisense TV via MQTT."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        username: str = DEFAULT_MQTT_USERNAME,
        password: str = DEFAULT_MQTT_PASSWORD,
        client_id: str = DEFAULT_CLIENT_ID,
        use_ssl: bool = True,
        verify_ssl: bool = False,
        certfile: Optional[str] = None,
        keyfile: Optional[str] = None,
        enable_persistence: bool = True,
        storage: Optional[TokenStorage] = None,
        on_state_change: Optional[Callable[[dict], None]] = None,
        on_auth_required: Optional[Callable[[], None]] = None,
        mac_address: Optional[str] = None,
        use_dynamic_auth: bool = False,
        brand: str = "his",
        auth_method: Optional[AuthMethod] = None,
        auto_detect_protocol: bool = True,
    ):
        """Initialize the Hisense TV client.

        Args:
            host: TV IP address
            port: MQTT port (default 36669)
            username: MQTT username (default 'hisenseservice')
            password: MQTT password (default 'multimqttservice')
            client_id: Client identifier for MQTT topics
            use_ssl: Enable SSL/TLS connection
            verify_ssl: When True, validate the TV's server certificate against
                the bundled RemoteCA root (hostname check is always skipped, as
                the cert CN is "RemoteCA"). Default False keeps the historic
                no-verification behavior for these self-signed, on-LAN certs.
            certfile: Path to client certificate file (PEM format)
            keyfile: Path to client private key file (PKCS8 format)
            enable_persistence: Save/load auth tokens for automatic reconnection
            storage: Custom TokenStorage instance (uses default if None)
            on_state_change: Callback for state updates
            on_auth_required: Callback when TV requires PIN authentication
            mac_address: Device MAC address (required for dynamic auth)
            use_dynamic_auth: Use dynamic credential generation algorithm
            brand: TV brand identifier (default 'his' for Hisense)
            auth_method: Authentication method (LEGACY, MIDDLE, MODERN).
                        If None and auto_detect_protocol is True, will auto-detect.
            auto_detect_protocol: Automatically detect protocol version from TV.
                                 Only used when auth_method is None.
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.use_ssl = use_ssl
        self.verify_ssl = verify_ssl
        self.enable_persistence = enable_persistence
        self.on_state_change = on_state_change
        self.on_auth_required = on_auth_required
        self.mac_address = mac_address
        self.use_dynamic_auth = use_dynamic_auth
        self.brand = brand

        # Protocol detection and auth method
        self._auth_method = auth_method
        self._protocol_version: Optional[int] = None
        self._auto_detect_protocol = auto_detect_protocol

        # Auto-detect protocol if needed and dynamic auth is enabled
        if use_dynamic_auth and auth_method is None and auto_detect_protocol:
            self._protocol_version = detect_protocol(host)
            self._auth_method = get_auth_method(self._protocol_version)
            if self._protocol_version is not None:
                _LOGGER.info("Detected protocol version: %s -> %s", self._protocol_version, self._auth_method.value)
            else:
                _LOGGER.warning("Could not detect protocol. Using %s auth (will try fallback if fails)", self._auth_method.value)

        # Token storage
        self._storage = storage or (get_storage() if enable_persistence else None)
        self._access_token: Optional[str] = None
        self._authenticated = False
        self._auth_required = False

        self._connected = False
        self._response_event = threading.Event()
        self._auth_event = threading.Event()
        # Set once the access token has actually been received and saved, so
        # pairing can wait for persistence instead of returning on PIN-accept.
        self._token_event = threading.Event()
        self._last_response: Optional[dict] = None
        self._state: dict = {}
        self._cached_volume: Optional[int] = None  # Cache volume from broadcasts
        self._cached_muted: bool = False  # Cache mute status from broadcasts

        # Track if we need to refresh token after connecting
        self._pending_token_refresh = False
        self._refresh_token: Optional[str] = None

        # Check for saved credentials first (after successful pairing)
        saved_creds = self._load_saved_credentials()
        if saved_creds:
            if saved_creds.get("needs_reauth"):
                # Both tokens expired - need fresh pairing
                _LOGGER.info("Stored tokens expired. Need to re-authenticate.")
                if use_dynamic_auth and mac_address:
                    # Fall through to generate fresh credentials
                    saved_creds = None
                else:
                    _LOGGER.warning("Cannot generate fresh credentials without mac_address")

            elif saved_creds.get("needs_refresh"):
                # Access token expired but refresh token valid
                # Connect with refresh token, then refresh
                self._mqtt_client_id = saved_creds["client_id"]
                self._username = saved_creds["mqtt_username"]
                # Use refresh token as password for initial connection
                self._password = saved_creds["refresh_token"]
                self._refresh_token = saved_creds["refresh_token"]
                self._pending_token_refresh = True
                self.client_id = saved_creds["client_id"]
                # Restore auth method from saved credentials
                if saved_creds.get("auth_method"):
                    self._auth_method = AuthMethod(saved_creds["auth_method"])
                if saved_creds.get("protocol_version"):
                    self._protocol_version = saved_creds["protocol_version"]
                hours_left = saved_creds.get("refresh_expires_in", 0) // 3600
                _LOGGER.info("Access token expired. Will refresh (refresh token valid for %dh)...", hours_left)

            elif saved_creds.get("access_token"):
                # Valid access token - use it
                self._mqtt_client_id = saved_creds["client_id"]
                self._username = saved_creds["mqtt_username"]
                self._password = saved_creds["access_token"]  # KEY: accesstoken as password!
                self._access_token = saved_creds["access_token"]
                self._refresh_token = saved_creds.get("refresh_token")
                self._authenticated = True
                self.client_id = saved_creds["client_id"]
                # Restore auth method from saved credentials
                if saved_creds.get("auth_method"):
                    self._auth_method = AuthMethod(saved_creds["auth_method"])
                if saved_creds.get("protocol_version"):
                    self._protocol_version = saved_creds["protocol_version"]
                hours_left = saved_creds.get("access_expires_in", 0) // 3600
                _LOGGER.debug("Using saved credentials (valid for %dh): client_id=%s...", hours_left, self._mqtt_client_id[:30])

        if not saved_creds:
            # No saved credentials - need to generate or use static
            if use_dynamic_auth and mac_address:
                # Generate fresh credentials for new pairing
                creds = generate_credentials(
                    mac_address=mac_address,
                    brand=brand,
                    auth_method=self._auth_method,
                )
                self._mqtt_client_id = creds.client_id
                self._username = creds.username
                self._password = creds.password
                # Use MQTT client_id for topics during pairing as well
                self.client_id = creds.client_id
                auth_label = self._auth_method.value if self._auth_method else "auto"
                _LOGGER.debug("Using dynamic auth (%s): client_id=%s...", auth_label, creds.client_id[:30])
            else:
                if use_dynamic_auth and not mac_address:
                    _LOGGER.warning(
                        "Dynamic auth requested but no MAC address available; "
                        "falling back to static credentials. The TV will likely "
                        "reject this (MQTT code 5). Provide the TV's MAC so a valid "
                        "client_id can be generated."
                    )
                # Use static credentials
                self._mqtt_client_id = f"hisense_{client_id}_{int(time.time())}"
                self._username = username
                self._password = password

        # Create MQTT client with explicit configuration
        self._client = mqtt.Client(
            client_id=self._mqtt_client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
            transport="tcp"
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Resolve the client certificate/key pair once, so the initial connect
        # and any later reconnect use the same source (explicit args, env var,
        # ~/.config/pyvidaa/certs, or a repo-local ./certs).
        self._certs = resolve_client_certs(certfile, keyfile)

        # Configure SSL with client certificate for mutual TLS
        if use_ssl:
            if self._certs:
                cert, key = self._certs
                # Using client certs - also need username/password
                self._client.username_pw_set(self._username, self._password)
                ca_certs, cert_reqs = self._server_verify_args()
                self._client.tls_set(
                    ca_certs=ca_certs,
                    certfile=cert,
                    keyfile=key,
                    cert_reqs=cert_reqs,
                    tls_version=ssl.PROTOCOL_TLS,
                )
                # Always skip hostname checking: the TV's cert CN is "RemoteCA",
                # not its IP. When verifying, the chain is still validated.
                self._client.tls_insecure_set(True)
            else:
                # No client cert found. Mutual TLS is required by some protocol
                # versions, so warn (with guidance) and fall back to plain TLS.
                _LOGGER.warning("%s", MISSING_CERT_HELP)
                self._client.username_pw_set(self._username, self._password)
                context = ssl.create_default_context()
                if not verify_ssl:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                self._client.tls_set_context(context)
        else:
            # No SSL - use username/password
            self._client.username_pw_set(self._username, self._password)

    def _server_verify_args(self):
        """Return (ca_certs, cert_reqs) for the mutual-TLS handshake.

        When verify_ssl is set, validate the TV's server certificate against the
        bundled RemoteCA root; otherwise skip server verification (the historic
        default, since these certs are self-signed and on the local network).
        """
        if self.verify_ssl:
            ca = bundled_ca_path()
            if ca:
                return ca, ssl.CERT_REQUIRED
            _LOGGER.warning(
                "verify_ssl=True but bundled RemoteCA was not found; "
                "falling back to no server verification."
            )
        return None, ssl.CERT_NONE

    def _load_saved_credentials(self) -> Optional[dict]:
        """Load saved credentials from storage for reconnection.

        Returns:
            Dict with client_id, mqtt_username, access_token, and status info
            if valid creds exist, None otherwise
        """
        if not self._storage:
            return None

        token_data = self._storage.get_token(host=self.host, port=self.port)
        if not token_data:
            return None

        # Need all three to use saved credentials
        client_id = token_data.get("client_id")
        mqtt_username = token_data.get("mqtt_username")
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if not (client_id and mqtt_username):
            return None

        # Get token status
        status = self._storage.get_token_status(host=self.host, port=self.port)

        return {
            "client_id": client_id,
            "mqtt_username": mqtt_username,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "uuid": token_data.get("uuid"),
            "needs_refresh": status.get("needs_refresh", False),
            "needs_reauth": status.get("needs_reauth", False),
            "access_expires_in": status.get("access_expires_in", 0),
            "refresh_expires_in": status.get("refresh_expires_in", 0),
            "auth_method": token_data.get("auth_method"),
            "protocol_version": token_data.get("protocol_version"),
        }

    def _load_saved_token(self) -> bool:
        """Load saved token from storage.

        Returns:
            True if valid token was loaded
        """
        if not self._storage:
            return False

        token_data = self._storage.get_token(host=self.host, port=self.port)
        if token_data and not token_data.get("needs_refresh"):
            self._access_token = token_data.get("access_token")
            self._authenticated = True
            return True

        return False

    def connect(self, timeout: float = 10.0, auto_auth: bool = True, auto_refresh: bool = True, try_fallback: bool = True) -> bool:
        """Connect to the TV.

        Args:
            timeout: Connection timeout in seconds
            auto_auth: Automatically use saved auth token if available
            auto_refresh: Automatically refresh expired access token
            try_fallback: If connection fails and protocol was not detected,
                         try other auth methods sequentially

        Returns:
            True if connected successfully
        """
        try:
            # Clean up any existing connection first
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._connected = False

            self._client.connect(self.host, self.port, keepalive=60)
            self._client.loop_start()

            # Wait for connection
            start = time.time()
            while not self._connected and (time.time() - start) < timeout:
                time.sleep(0.1)

            if not self._connected:
                # Connection failed - stop loop and try fallback if enabled
                self._client.loop_stop()
                if try_fallback and self._protocol_version is None and self.use_dynamic_auth and self.mac_address:
                    return self._connect_with_fallback(timeout=timeout, auto_refresh=auto_refresh)
                return False

            # If we have a pending token refresh, do it now
            if auto_refresh and self._pending_token_refresh:
                if not self.refresh_token(timeout=timeout):
                    _LOGGER.warning("Token refresh failed, connection may not work")
                    # Don't disconnect - let caller decide what to do

            return self._connected
        except Exception as e:
            _LOGGER.debug("Connection failed: %s", e)
            # Stop loop on failure
            try:
                self._client.loop_stop()
            except Exception:
                pass
            # Try fallback on exception too
            if try_fallback and self._protocol_version is None and self.use_dynamic_auth and self.mac_address:
                return self._connect_with_fallback(timeout=timeout, auto_refresh=auto_refresh)
            return False

    def _connect_with_fallback(self, timeout: float = 10.0, auto_refresh: bool = True) -> bool:
        """Try connecting with different auth methods until one works.

        Called when initial connection fails and protocol was not auto-detected.

        Args:
            timeout: Connection timeout in seconds per attempt
            auto_refresh: Automatically refresh expired access token

        Returns:
            True if connected successfully with any auth method
        """
        auth_methods = get_auth_method_order()

        # Skip the method we already tried
        if self._auth_method in auth_methods:
            auth_methods = [m for m in auth_methods if m != self._auth_method]

        for method in auth_methods:
            _LOGGER.info("Trying %s authentication...", method.value)
            self._auth_method = method

            # Regenerate credentials with new auth method
            creds = generate_credentials(
                mac_address=self.mac_address,
                brand=self.brand,
                auth_method=method,
            )

            # Create new MQTT client with new credentials
            self._mqtt_client_id = creds.client_id
            self._username = creds.username
            self._password = creds.password
            self.client_id = creds.client_id

            self._client = mqtt.Client(
                client_id=self._mqtt_client_id,
                clean_session=True,
                protocol=mqtt.MQTTv311,
                transport="tcp"
            )
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            # Reconfigure SSL (reuse the cert pair resolved at init)
            if self.use_ssl:
                if self._certs:
                    cert, key = self._certs
                    self._client.username_pw_set(self._username, self._password)
                    ca_certs, cert_reqs = self._server_verify_args()
                    self._client.tls_set(
                        ca_certs=ca_certs,
                        certfile=cert,
                        keyfile=key,
                        cert_reqs=cert_reqs,
                        tls_version=ssl.PROTOCOL_TLS,
                    )
                    self._client.tls_insecure_set(True)
                else:
                    self._client.username_pw_set(self._username, self._password)
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    self._client.tls_set_context(context)
            else:
                self._client.username_pw_set(self._username, self._password)

            # Try connecting
            try:
                self._client.connect(self.host, self.port, keepalive=60)
                self._client.loop_start()

                start = time.time()
                while not self._connected and (time.time() - start) < timeout:
                    time.sleep(0.1)

                if self._connected:
                    _LOGGER.info("Connected successfully with %s authentication!", method.value)
                    if auto_refresh and self._pending_token_refresh:
                        if not self.refresh_token(timeout=timeout):
                            _LOGGER.warning("Token refresh failed")
                    return True
                else:
                    self._client.loop_stop()
                    self._client.disconnect()
            except Exception as e:
                _LOGGER.debug("  %s auth failed: %s", method.value, e)
                try:
                    self._client.loop_stop()
                    self._client.disconnect()
                except Exception:
                    pass

        _LOGGER.error("All authentication methods failed")
        return False

    def disconnect(self):
        """Disconnect from the TV."""
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False

    def _on_connect(self, client, userdata, flags, rc):
        """Handle connection callback."""
        if rc == 0:
            self._connected = True
            _LOGGER.info("Connected to TV at %s:%s", self.host, self.port)
            # Subscribe to response topics
            self._client.subscribe(TOPIC_STATE_RESPONSE)
            self._client.subscribe(TOPIC_VOLUME_RESPONSE)
            # Volume change broadcasts (platform_service path)
            self._client.subscribe("/remoteapp/mobile/broadcast/platform_service/actions/volumechange")
            self._client.subscribe(get_topic(TOPIC_SOURCES_RESPONSE, self.client_id))
            self._client.subscribe(get_topic(TOPIC_APPS_RESPONSE, self.client_id))

            # Subscribe to authentication and token topics
            self._client.subscribe(get_topic(TOPIC_AUTH_RESPONSE, self.client_id))
            self._client.subscribe(get_topic(TOPIC_AUTH_CODE_RESPONSE, self.client_id))
            self._client.subscribe(get_topic(TOPIC_TOKEN_RESPONSE, self.client_id))
            self._client.subscribe(f"/remoteapp/mobile/broadcast/ui_service/state")

            # Subscribe to device info topics
            self._client.subscribe(get_topic(TOPIC_TV_INFO_RESPONSE, self.client_id))
            self._client.subscribe(get_topic(TOPIC_DEVICE_INFO_RESPONSE, self.client_id))
            self._client.subscribe(get_topic(TOPIC_CAPABILITY_RESPONSE, self.client_id))

            # If we have a saved token, we're already authenticated
            if self._access_token:
                self._authenticated = True
        else:
            # Map common MQTT CONNACK codes to actionable messages.
            reasons = {
                1: "unacceptable protocol version",
                2: "client_id rejected",
                3: "server unavailable",
                4: "bad username or password",
                5: "not authorized - check the TV clock (date/time, timezone, DST); "
                   "time-based credentials are rejected when clocks disagree, and "
                   "stale saved tokens can also cause this (try 'tv auth clear')",
            }
            detail = reasons.get(rc, "unknown error")
            _LOGGER.error("Connection to %s:%s failed with code %s (%s)",
                          self.host, self.port, rc, detail)

    def _on_disconnect(self, client, userdata, rc):
        """Handle disconnection callback."""
        self._connected = False

    def _on_message(self, client, userdata, msg):
        """Handle incoming messages."""
        try:
            payload = json.loads(msg.payload.decode())

            # The TV occasionally publishes bare JSON scalars (e.g. a string)
            # instead of an object. Record it and unblock any waiter, but never
            # pass it to the dict-expecting handlers below (they call .get()).
            if not isinstance(payload, dict):
                _LOGGER.debug("Non-dict payload on %s: %r", msg.topic, payload)
                self._last_response = payload
                self._response_event.set()
                return

            # Handle token issuance response
            if "tokenissuance" in msg.topic:
                self._last_response = payload
                self._response_event.set()
                self._handle_token_response(payload)
            # Handle authentication responses (PIN verification)
            elif "authentication" in msg.topic:
                self._last_response = payload
                self._response_event.set()
                self._handle_auth_response(payload)
            # Handle volume response (broadcast topic but needs response event)
            elif "/volume" in msg.topic or "volumechange" in msg.topic:
                _LOGGER.debug("Volume response on %s: %s", msg.topic, payload)
                volume_type = payload.get("volume_type", 0)
                if volume_type == 0:  # Main speaker volume
                    for field in ["volume_value", "volume", "value"]:
                        if field in payload:
                            try:
                                self._cached_volume = int(payload[field])
                                break
                            except (ValueError, TypeError):
                                pass
                elif volume_type == 2:  # Mute status (0=unmuted, 1=muted)
                    mute_val = payload.get("volume_value", 0)
                    self._cached_muted = (mute_val == 1)
                self._last_response = payload
                self._response_event.set()
            # Handle broadcast state updates (don't trigger response event)
            elif "broadcast" in msg.topic:
                self._state = payload
                # Check if auth is required from state
                if payload.get("statetype") == "authentication":
                    self._auth_required = True
                    if self.on_auth_required:
                        self.on_auth_required()
                if self.on_state_change:
                    self.on_state_change(payload)
            # All other responses (device info, sources, apps, etc)
            else:
                self._last_response = payload
                self._response_event.set()
        except json.JSONDecodeError:
            self._last_response = {"raw": msg.payload.decode()}
            self._response_event.set()

    def _handle_auth_response(self, payload: dict):
        """Handle authentication response from TV.

        Args:
            payload: Authentication response payload
        """
        if not isinstance(payload, dict):
            return
        # Check for PIN accepted (result: 1 from authenticationcode)
        if payload.get("result") == 1:
            # PIN was accepted, mark as authenticated
            # Token will come separately on tokenissuance topic
            self._authenticated = True
            self._auth_required = False
            self._auth_event.set()

        # Check if auth is required
        elif payload.get("statetype") == "authenticationcode":
            self._auth_required = True
            if self.on_auth_required:
                self.on_auth_required()

    def _handle_token_response(self, payload: dict):
        """Handle token issuance response from TV.

        Args:
            payload: Token response payload with accesstoken/refreshtoken
        """
        if not isinstance(payload, dict):
            return
        access_token = payload.get("accesstoken")
        refresh_token = payload.get("refreshtoken")

        if access_token:
            self._access_token = access_token
            self._authenticated = True
            self._auth_required = False

            # Save full credentials if persistence enabled
            # Important: mqtt_username and client_id are needed for reconnection
            if self._storage:
                self._storage.save_token(
                    # Key by host:port to match the legacy format the CLI
                    # lookups fall back to (storage matches by key, not by the
                    # host field inside entries).
                    device_id=f"{self.host}:{self.port}",
                    host=self.host,
                    port=self.port,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    access_token_duration_days=payload.get("accesstoken_duration_day", 7),
                    refresh_token_duration_days=payload.get("refreshtoken_duration_day", 30),
                    client_id=self._mqtt_client_id,  # Full MQTT client ID
                    mqtt_username=self._username,    # MQTT username for reconnection
                    uuid=self.mac_address,           # Store UUID for reference
                    auth_method=self._auth_method.value if self._auth_method else None,
                    protocol_version=self._protocol_version,
                )

            _LOGGER.info("Token received and saved!")
            self._auth_event.set()
            self._token_event.set()

    def _publish(self, topic: str, payload: Any = "") -> bool:
        """Publish a message to the TV.

        Args:
            topic: MQTT topic
            payload: Message payload (will be JSON encoded if dict)

        Returns:
            True if published successfully
        """
        if not self._connected:
            _LOGGER.warning("Not connected to TV")
            return False

        if isinstance(payload, dict):
            payload = json.dumps(payload)

        result = self._client.publish(topic, payload)
        return result.rc == mqtt.MQTT_ERR_SUCCESS

    def _request(self, topic: str, payload: Any = "", timeout: float = 5.0) -> Optional[dict]:
        """Send a request and wait for response.

        Args:
            topic: MQTT topic
            payload: Message payload
            timeout: Response timeout in seconds

        Returns:
            Response dict or None if timeout
        """
        self._response_event.clear()
        self._last_response = None

        if not self._publish(topic, payload):
            return None

        if self._response_event.wait(timeout):
            return self._last_response
        return None

    # Authentication
    def authenticate(self, pin: str, wait_for_response: bool = True, timeout: float = 10.0) -> bool:
        """Send authentication PIN displayed on TV.

        Args:
            pin: 4-digit PIN shown on TV screen
            wait_for_response: Wait for auth confirmation
            timeout: Timeout for auth response

        Returns:
            True if authentication successful (or sent if not waiting)
        """
        self._auth_event.clear()
        self._token_event.clear()
        topic = get_topic(TOPIC_AUTH, self.client_id)

        # PIN must be sent as integer, not string!
        try:
            pin_int = int(pin)
        except ValueError:
            _LOGGER.error("Invalid PIN: %s", pin)
            return False

        # Send PIN as integer in JSON (critical for auth to work)
        if not self._publish(topic, {"authNum": pin_int}):
            return False

        if not wait_for_response:
            return True

        # Wait for PIN acceptance
        if not self._auth_event.wait(timeout):
            return False
        if not self._authenticated:
            return self._authenticated

        # PIN accepted - request the token and wait for it to actually arrive
        # and be persisted before reporting success (the token issuance is a
        # separate message; returning early raced with disconnect() and lost it).
        self._request_token()
        if self._access_token or self._token_event.wait(timeout):
            return self._access_token is not None

        _LOGGER.warning("PIN accepted but no access token received within %ss", timeout)
        return False

    def _request_token(self, refresh_token: str = ""):
        """Request access token (new or refreshed).

        Args:
            refresh_token: If provided, requests a refreshed token.
                          If empty, requests initial token after PIN auth.
        """
        topic = get_topic(TOPIC_GET_TOKEN, self.client_id)
        self._publish(topic, {"refreshtoken": refresh_token})

        if not refresh_token:
            # Close authentication dialog (only for initial auth)
            close_topic = get_topic(TOPIC_AUTH_CLOSE, self.client_id)
            self._publish(close_topic, "")

    def refresh_token(self, timeout: float = 10.0) -> bool:
        """Refresh the access token using the refresh token.

        Returns:
            True if token was successfully refreshed
        """
        if not self._refresh_token:
            _LOGGER.warning("No refresh token available")
            return False

        if not self._connected:
            _LOGGER.warning("Must be connected to refresh token")
            return False

        self._auth_event.clear()
        _LOGGER.info("Refreshing access token...")
        self._request_token(self._refresh_token)

        # Wait for new token
        if self._auth_event.wait(timeout):
            if self._access_token:
                _LOGGER.info("Token refreshed successfully!")
                # Update password for future reconnections
                self._password = self._access_token
                self._pending_token_refresh = False
                return True

        _LOGGER.warning("Token refresh failed")
        return False

    def start_pairing(self) -> bool:
        """Start the pairing process to show PIN on TV.

        Call this to initiate pairing, then call authenticate() with the PIN.

        Returns:
            True if pairing request sent successfully
        """
        # Subscribe to auth topics
        self._client.subscribe(get_topic(TOPIC_AUTH_RESPONSE, self.client_id))
        self._client.subscribe(get_topic(TOPIC_AUTH_CODE_RESPONSE, self.client_id))
        self._client.subscribe(get_topic(TOPIC_TOKEN_RESPONSE, self.client_id))

        # Send vidaa_app_connect to trigger PIN dialog
        topic = get_topic(TOPIC_VIDAA_CONNECT, self.client_id)
        return self._publish(topic, {
            "app_version": 2,
            "connect_result": 0,
            "device_type": "Mobile App"
        })

    def is_authenticated(self) -> bool:
        """Check if currently authenticated with the TV."""
        return self._authenticated

    def needs_authentication(self) -> bool:
        """Check if TV is requesting authentication."""
        return self._auth_required

    def clear_saved_token(self):
        """Clear saved authentication token for this TV."""
        if self._storage:
            self._storage.delete_token(self.host, self.port)
        self._access_token = None
        self._authenticated = False

    def get_saved_token_info(self) -> Optional[dict]:
        """Get information about saved token for this TV.

        Returns:
            Token info dict or None if no token saved
        """
        if self._storage:
            return self._storage.get_token(host=self.host, port=self.port)
        return None

    # State checking
    def _is_tv_on(self, timeout: float = 3.0) -> bool:
        """Check if TV is powered on (not in fake_sleep state).

        Args:
            timeout: Timeout for state query

        Returns:
            True if TV is on, False if off or unreachable
        """
        state = self.get_state(timeout=timeout)
        if state and state.get("statetype") == "fake_sleep_0":
            return False
        return state is not None

    def is_on(self) -> bool:
        """Check if TV is currently powered on.

        Returns:
            True if TV is on, False if off
        """
        return self._is_tv_on()

    # Remote keys
    def send_key(self, key: str, check_state: bool = False) -> bool:
        """Send a remote key press.

        Args:
            key: Key constant (e.g., KEY_POWER, KEY_UP)
            check_state: If True, check TV is on before sending (except power key)

        Returns:
            True if sent successfully
        """
        # Skip state check for power key
        if check_state and key != "KEY_POWER":
            if not self._is_tv_on():
                _LOGGER.debug("TV is off. Command not sent.")
                return False

        topic = get_topic(TOPIC_SEND_KEY, self.client_id)
        return self._publish(topic, key)

    def power(self) -> bool:
        """Toggle power."""
        return self.send_key("KEY_POWER")

    def power_on(self) -> bool:
        """Turn TV on (only if it's off).

        Returns:
            True if command sent or TV already on
        """
        state = self.get_state(timeout=3.0)
        if state and state.get("statetype") == "fake_sleep_0":
            return self.send_key("KEY_POWER")
        elif state:
            _LOGGER.debug("TV is already on.")
            return True
        else:
            # Couldn't get state, try power anyway
            return self.send_key("KEY_POWER")

    def power_off(self) -> bool:
        """Turn TV off (only if it's on).

        Returns:
            True if command sent or TV already off
        """
        state = self.get_state(timeout=3.0)
        if state and state.get("statetype") != "fake_sleep_0":
            return self.send_key("KEY_POWER")
        elif state:
            _LOGGER.debug("TV is already off.")
            return True
        else:
            # Couldn't get state, don't send power (might turn it on)
            _LOGGER.warning("Could not determine TV state.")
            return False

    def volume_up(self) -> bool:
        """Increase volume."""
        return self.send_key("KEY_VOLUMEUP")

    def volume_down(self) -> bool:
        """Decrease volume."""
        return self.send_key("KEY_VOLUMEDOWN")

    def mute(self) -> bool:
        """Toggle mute."""
        return self.send_key("KEY_MUTE")

    def up(self) -> bool:
        """Navigate up."""
        return self.send_key("KEY_UP")

    def down(self) -> bool:
        """Navigate down."""
        return self.send_key("KEY_DOWN")

    def left(self) -> bool:
        """Navigate left."""
        return self.send_key("KEY_LEFT")

    def right(self) -> bool:
        """Navigate right."""
        return self.send_key("KEY_RIGHT")

    def ok(self) -> bool:
        """Press OK/Enter."""
        return self.send_key("KEY_OK")

    def back(self) -> bool:
        """Go back."""
        return self.send_key("KEY_RETURNS")

    def menu(self) -> bool:
        """Open menu."""
        return self.send_key("KEY_MENU")

    def home(self) -> bool:
        """Go to home screen."""
        return self.send_key("KEY_HOME")

    def exit(self) -> bool:
        """Exit current screen."""
        return self.send_key("KEY_EXIT")

    def play(self) -> bool:
        """Play."""
        return self.send_key("KEY_PLAY")

    def pause(self) -> bool:
        """Pause."""
        return self.send_key("KEY_PAUSE")

    def stop(self) -> bool:
        """Stop."""
        return self.send_key("KEY_STOP")

    # Volume control
    def get_volume(self, timeout: float = 5.0) -> Optional[int]:
        """Get current volume level.

        Returns:
            Volume level (0-100) or None if failed
        """
        topic = get_topic(TOPIC_GET_VOLUME, self.client_id)
        response = self._request(topic, timeout=timeout)
        if response:
            # Only use main speaker volume (volume_type 0)
            volume_type = response.get("volume_type", 0)
            if volume_type == 0:
                for field in ["volume_value", "volume", "value"]:
                    if field in response:
                        try:
                            vol = int(response[field])
                            self._cached_volume = vol
                            return vol
                        except (ValueError, TypeError):
                            pass
            _LOGGER.debug("Volume response: type=%s, data=%s", volume_type, response)
        # Return cached volume if direct request failed or wrong type
        if self._cached_volume is not None:
            _LOGGER.debug("Using cached volume: %s", self._cached_volume)
            return self._cached_volume
        return None

    @property
    def cached_volume(self) -> Optional[int]:
        """Get last known volume from broadcasts."""
        return self._cached_volume

    @property
    def is_muted(self) -> bool:
        """Get mute status from broadcasts."""
        return self._cached_muted

    def set_volume(self, level: int, check_state: bool = False) -> bool:
        """Set volume level.

        Args:
            level: Volume level (0-100)
            check_state: If True, check TV is on before sending

        Returns:
            True if sent successfully
        """
        if check_state and not self._is_tv_on():
            print("TV is off. Command not sent.")
            return False

        level = max(0, min(100, level))
        topic = get_topic(TOPIC_SET_VOLUME, self.client_id)
        return self._publish(topic, str(level))

    # Source control
    def get_sources(self, timeout: float = 5.0) -> Optional[list]:
        """Get available input sources.

        Returns:
            List of source dicts or None if failed
        """
        topic = get_topic(TOPIC_GET_SOURCES, self.client_id)
        return self._request(topic, timeout=timeout)

    def set_source(self, source: str, check_state: bool = False) -> bool:
        """Set input source.

        Args:
            source: Source name (hdmi1, hdmi2, tv, av) or source ID
            check_state: If True, check TV is on before sending

        Returns:
            True if sent successfully
        """
        if check_state and not self._is_tv_on():
            print("TV is off. Command not sent.")
            return False

        source_id = SOURCE_MAP.get(source.lower(), source)
        topic = get_topic(TOPIC_SET_SOURCE, self.client_id)
        return self._publish(topic, {"sourceid": source_id})

    # State
    def get_state(self, timeout: float = 5.0) -> Optional[dict]:
        """Get TV state information.

        Note: State comes on broadcast topic, so we trigger a refresh
        and return the cached state.

        Returns:
            State dict or None if failed
        """
        # Clear current state to detect fresh update
        old_state = self._state

        # Send request to trigger state broadcast
        topic = get_topic(TOPIC_GET_STATE, self.client_id)
        self._publish(topic, "")

        # Wait for state to be updated via broadcast
        start = time.time()
        while time.time() - start < timeout:
            if self._state and self._state != old_state:
                return self._state
            time.sleep(0.1)

        # Return whatever state we have (might be stale)
        return self._state

    # Device Info
    def get_tv_info(self, timeout: float = 5.0) -> Optional[dict]:
        """Get TV info (chipplatform, brand, features, etc).

        Returns:
            Dict with: brand, chipplatform, deviceid, fake_sleep, uVersion, etc.
        """
        topic = get_topic(TOPIC_GET_TV_INFO, self.client_id)
        return self._request(topic, timeout=timeout)

    def get_device_info(self, timeout: float = 5.0) -> Optional[dict]:
        """Get device info (model, name, version, etc).

        Returns:
            Dict with: model_name, tv_name, tv_version, country, ip, etc.
        """
        topic = get_topic(TOPIC_GET_DEVICE_INFO, self.client_id)
        return self._request(topic, timeout=timeout)

    def get_capability(self, timeout: float = 5.0) -> Optional[dict]:
        """Get TV capabilities and software versions.

        Returns:
            Dict with: softwareVersion, devicemsg, resolution, etc.
        """
        topic = get_topic(TOPIC_GET_CAPABILITY, self.client_id)
        return self._request(topic, timeout=timeout)

    # Apps
    def get_apps(self, timeout: float = 5.0) -> Optional[list]:
        """Get list of available apps.

        Returns:
            List of app dicts or None if failed
        """
        # Use a dedicated response capture for apps since broadcast messages
        # can interfere with the generic _request() method
        apps_response = []
        apps_received = threading.Event()

        def on_apps_message(client, userdata, msg):
            nonlocal apps_response
            if "applist" in msg.topic:
                try:
                    apps_response = json.loads(msg.payload.decode())
                    apps_received.set()
                except json.JSONDecodeError:
                    pass

        # Temporarily add callback for app list
        apps_topic = get_topic(TOPIC_APPS_RESPONSE, self.client_id)
        self._client.message_callback_add(apps_topic, on_apps_message)

        try:
            topic = get_topic(TOPIC_GET_APPS, self.client_id)
            self._publish(topic, "")

            if apps_received.wait(timeout):
                return apps_response if isinstance(apps_response, list) else None
            return None
        finally:
            self._client.message_callback_remove(apps_topic)

    def launch_app(self, app_name: str, check_state: bool = False) -> bool:
        """Launch an app.

        Args:
            app_name: App name (netflix, youtube, amazon, disney, hulu, or any installed app)
                      or custom app dict with appId, name, url
            check_state: If True, check TV is on before sending

        Returns:
            True if sent successfully
        """
        if check_state and not self._is_tv_on():
            print("TV is off. Command not sent.")
            return False

        # If passed a dict, use it directly
        if isinstance(app_name, dict):
            app_data = app_name
        # Check hardcoded common apps first (faster)
        elif app_name.lower() in APPS:
            app_data = APPS[app_name.lower()]
        else:
            # Query TV for app list and find by name
            app_list = self.get_apps()
            if app_list:
                for app in app_list:
                    if app.get("name", "").upper() == app_name.upper():
                        app_data = {
                            "appId": app.get("appId"),
                            "name": app.get("name"),
                            "url": app.get("url")
                        }
                        break
                else:
                    _LOGGER.warning("App '%s' not found. Use get_apps() to see available apps.", app_name)
                    return False
            else:
                _LOGGER.warning("Could not get app list. Try one of: netflix, youtube, amazon, disney, hulu")
                return False

        topic = get_topic(TOPIC_LAUNCH_APP, self.client_id)
        return self._publish(topic, app_data)

    @property
    def is_connected(self) -> bool:
        """Check if connected to TV."""
        return self._connected

    @property
    def state(self) -> dict:
        """Get last known TV state."""
        return self._state

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
