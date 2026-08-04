"""Async wrapper for Hisense TV MQTT client.

Provides asyncio-compatible interface for controlling Hisense/Vidaa TVs.
Uses executor to run sync operations in a thread pool.

For Home Assistant integration, use AsyncVidaaTV with hass.async_add_executor_job().
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, Optional, List

from .client import VidaaTV
from .config import (
    DEFAULT_PORT,
    DEFAULT_MQTT_USERNAME,
    DEFAULT_MQTT_PASSWORD,
    DEFAULT_CLIENT_ID,
    TokenStorage,
    get_storage,
)
from .protocol import AuthMethod

_LOGGER = logging.getLogger(__name__)

# Default thread pool for blocking operations
_DEFAULT_EXECUTOR: Optional[ThreadPoolExecutor] = None


def _get_executor() -> ThreadPoolExecutor:
    """Get or create the default thread pool executor."""
    global _DEFAULT_EXECUTOR
    if _DEFAULT_EXECUTOR is None:
        _DEFAULT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pyvidaa")
    return _DEFAULT_EXECUTOR


class AsyncVidaaTV:
    """Async wrapper for VidaaTV client.

    Provides asyncio-compatible methods for TV control.
    All blocking operations are run in a thread pool executor.

    Example usage:
        async with AsyncVidaaTV("192.168.1.50") as tv:
            await tv.power()
            volume = await tv.get_volume()

    For Home Assistant, you can also use with executor_job:
        tv = AsyncVidaaTV("192.168.1.50")
        await tv.async_connect()
        await tv.async_power()
    """

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
        allow_static_auth: bool = True,
        executor: Optional[ThreadPoolExecutor] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        """Initialize async Hisense TV client.

        Args:
            host: TV IP address
            port: MQTT port (default 36669)
            username: MQTT username
            password: MQTT password
            client_id: Client identifier
            use_ssl: Enable SSL/TLS
            verify_ssl: Verify SSL certificate
            certfile: Client certificate path
            keyfile: Client private key path
            enable_persistence: Save/load auth tokens
            storage: Custom TokenStorage instance
            on_state_change: Callback for state updates (called in executor thread)
            on_auth_required: Callback when PIN required (called in executor thread)
            mac_address: Device MAC address for dynamic auth
            use_dynamic_auth: Use dynamic credential generation
            brand: TV brand identifier
            auth_method: Authentication method (STATIC, LEGACY, MIDDLE, MODERN)
            auto_detect_protocol: Auto-detect protocol version
            allow_static_auth: Whether STATIC may be selected automatically
            executor: Custom ThreadPoolExecutor (uses default if None)
            loop: Event loop (uses current if None)
        """
        self._executor = executor or _get_executor()
        self._loop = loop

        # Store init params for lazy client creation
        # Client is NOT created here to avoid blocking SSL calls in event loop
        self._init_kwargs = {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "client_id": client_id,
            "use_ssl": use_ssl,
            "verify_ssl": verify_ssl,
            "certfile": certfile,
            "keyfile": keyfile,
            "enable_persistence": enable_persistence,
            "storage": storage,
            "on_state_change": on_state_change,
            "on_auth_required": on_auth_required,
            "mac_address": mac_address,
            "use_dynamic_auth": use_dynamic_auth,
            "brand": brand,
            "auth_method": auth_method,
            "auto_detect_protocol": auto_detect_protocol,
            "allow_static_auth": allow_static_auth,
        }

        # Client is created lazily in _ensure_client() to avoid blocking event loop
        self._client: Optional[VidaaTV] = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Get event loop."""
        if self._loop is not None:
            return self._loop
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.get_event_loop()

    def _ensure_client(self) -> VidaaTV:
        """Ensure the sync client is created (for use in executor).

        This must be called from within an executor thread, not the event loop,
        because VidaaTV.__init__ performs blocking SSL operations.
        """
        if self._client is None:
            self._client = VidaaTV(**self._init_kwargs)
        return self._client

    async def _async_ensure_client(self) -> None:
        """Ensure client is created, running in executor to avoid blocking."""
        if self._client is None:
            await self._run_in_executor(self._ensure_client)

    async def _run_in_executor(self, func: Callable, *args, **kwargs) -> Any:
        """Run a sync function in the executor.

        Args:
            func: Sync function to run
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result
        """
        loop = self._get_loop()
        if kwargs:
            func = partial(func, **kwargs)
        return await loop.run_in_executor(self._executor, func, *args)

    async def _call(self, method_name: str, *args, **kwargs) -> Any:
        """Call a sync client method in the executor, building the client if needed.

        Resolving the client inside the executor (rather than reading
        self._client on the event loop) avoids an AttributeError when a command
        is issued before async_connect() or after async_reset() dropped it.
        """
        def _run():
            return getattr(self._ensure_client(), method_name)(*args, **kwargs)

        return await self._run_in_executor(_run)

    # Properties (sync access is safe)
    @property
    def host(self) -> str:
        """TV IP address."""
        return self._init_kwargs["host"]

    @property
    def port(self) -> int:
        """MQTT port."""
        return self._init_kwargs["port"]

    @property
    def is_connected(self) -> bool:
        """Check if connected to TV."""
        return self._client.is_connected if self._client else False

    @property
    def auth_method(self) -> Optional[AuthMethod]:
        """The auth method in use - after connecting, the one that worked."""
        return self._client.auth_method if self._client else None

    @property
    def auth_mode(self) -> Optional[str]:
        """The auth method in use, as a user-facing mode string."""
        return self._client.auth_mode if self._client else None

    @property
    def is_authenticated(self) -> bool:
        """Check if authenticated."""
        return self._client.is_authenticated() if self._client else False

    @property
    def state(self) -> dict:
        """Get last known TV state."""
        return self._client.state if self._client else {}

    @property
    def is_muted(self) -> bool:
        """Get mute status from broadcasts."""
        return self._client.is_muted if self._client else False

    @property
    def cached_volume(self) -> Optional[int]:
        """Get last known volume from broadcasts."""
        return self._client.cached_volume if self._client else None

    # Connection methods
    async def async_connect(
        self,
        timeout: float = 10.0,
        auto_auth: bool = True,
        auto_refresh: bool = True,
        try_fallback: bool = True,
    ) -> bool:
        """Connect to the TV asynchronously.

        Args:
            timeout: Connection timeout in seconds
            auto_auth: Use saved auth token if available
            auto_refresh: Refresh expired access token
            try_fallback: Try other auth methods if initial fails

        Returns:
            True if connected successfully
        """
        def _connect():
            client = self._ensure_client()
            return client.connect(
                timeout=timeout,
                auto_auth=auto_auth,
                auto_refresh=auto_refresh,
                try_fallback=try_fallback,
            )

        return await self._run_in_executor(_connect)

    async def async_disconnect(self) -> None:
        """Disconnect from the TV asynchronously."""
        if self._client:
            await self._run_in_executor(self._client.disconnect)

    # Authentication
    async def async_start_pairing(self, wait_for_pin: float = 0.0) -> bool:
        """Start pairing process to show PIN on TV.

        Args:
            wait_for_pin: Seconds to wait for the TV to confirm the PIN dialog
                is on screen. 0 sends the request and returns immediately.

        Returns:
            True if pairing request sent (and confirmed, when wait_for_pin set)
        """
        def _start_pairing():
            client = self._ensure_client()
            return client.start_pairing(wait_for_pin=wait_for_pin)

        return await self._run_in_executor(_start_pairing)

    async def async_authenticate(
        self,
        pin: str,
        wait_for_response: bool = True,
        timeout: float = 10.0,
    ) -> bool:
        """Send authentication PIN.

        Args:
            pin: 4-digit PIN from TV screen
            wait_for_response: Wait for confirmation
            timeout: Auth timeout

        Returns:
            True if authentication successful
        """
        if not self._client:
            return False
        return await self._run_in_executor(
            self._client.authenticate,
            pin,
            wait_for_response=wait_for_response,
            timeout=timeout,
        )

    async def async_refresh_token(self, timeout: float = 10.0) -> bool:
        """Refresh access token.

        Returns:
            True if token refreshed successfully
        """
        if not self._client:
            return False
        return await self._run_in_executor(
            self._client.refresh_token,
            timeout=timeout,
        )

    async def async_reset(self) -> None:
        """Drop the underlying client so the next connect rebuilds it.

        Rebuilding re-reads saved-token status from storage, so an expired
        access token is refreshed from the still-valid refresh token instead
        of being replayed on reconnect.
        """
        def _reset():
            if self._client is not None:
                try:
                    self._client.disconnect()
                except Exception:
                    pass
                self._client = None

        await self._run_in_executor(_reset)

    async def async_token_status(self) -> dict:
        """Return saved-token status for this TV, read from storage.

        Keys include has_token, access_valid, access_expires_in, needs_refresh
        and needs_reauth.
        """
        def _status():
            from .config import get_storage

            return get_storage().get_token_status(
                host=self._init_kwargs["host"],
                port=self._init_kwargs["port"],
            )

        return await self._run_in_executor(_status)

    def needs_authentication(self) -> bool:
        """Check if TV is requesting authentication."""
        return self._client.needs_authentication() if self._client else False

    def clear_saved_token(self) -> None:
        """Clear saved authentication token."""
        if self._client:
            self._client.clear_saved_token()

    def get_saved_token_info(self) -> Optional[dict]:
        """Get saved token info."""
        return self._client.get_saved_token_info() if self._client else None

    # Remote keys
    async def async_send_key(self, key: str, check_state: bool = False) -> bool:
        """Send a remote key press.

        Args:
            key: Key constant (e.g., KEY_POWER)
            check_state: Check TV is on first

        Returns:
            True if sent successfully
        """
        return await self._call("send_key", key, check_state=check_state)

    async def async_power(self) -> bool:
        """Toggle power."""
        return await self._call("power")

    async def async_power_on(self) -> bool:
        """Turn TV on (only if off)."""
        return await self._call("power_on")

    async def async_power_off(self) -> bool:
        """Turn TV off (only if on)."""
        return await self._call("power_off")

    async def async_volume_up(self) -> bool:
        """Increase volume."""
        return await self._call("volume_up")

    async def async_volume_down(self) -> bool:
        """Decrease volume."""
        return await self._call("volume_down")

    async def async_mute(self) -> bool:
        """Toggle mute."""
        return await self._call("mute")

    async def async_up(self) -> bool:
        """Navigate up."""
        return await self._call("up")

    async def async_down(self) -> bool:
        """Navigate down."""
        return await self._call("down")

    async def async_left(self) -> bool:
        """Navigate left."""
        return await self._call("left")

    async def async_right(self) -> bool:
        """Navigate right."""
        return await self._call("right")

    async def async_ok(self) -> bool:
        """Press OK/Enter."""
        return await self._call("ok")

    async def async_back(self) -> bool:
        """Go back."""
        return await self._call("back")

    async def async_menu(self) -> bool:
        """Open menu."""
        return await self._call("menu")

    async def async_home(self) -> bool:
        """Go to home screen."""
        return await self._call("home")

    async def async_exit(self) -> bool:
        """Exit current screen."""
        return await self._call("exit")

    async def async_play(self) -> bool:
        """Play."""
        return await self._call("play")

    async def async_pause(self) -> bool:
        """Pause."""
        return await self._call("pause")

    async def async_stop(self) -> bool:
        """Stop."""
        return await self._call("stop")

    # Volume control
    async def async_get_volume(self, timeout: float = 5.0) -> Optional[int]:
        """Get current volume level.

        Returns:
            Volume (0-100) or None if failed
        """
        return await self._call("get_volume", timeout=timeout)

    async def async_set_volume(
        self, level: int, check_state: bool = False
    ) -> bool:
        """Set volume level.

        Args:
            level: Volume (0-100)
            check_state: Check TV is on first

        Returns:
            True if sent successfully
        """
        return await self._call("set_volume", level, check_state=check_state)

    # Source control
    async def async_get_sources(self, timeout: float = 5.0) -> Optional[List[dict]]:
        """Get available input sources.

        Returns:
            List of source dicts or None
        """
        return await self._call("get_sources", timeout=timeout)

    async def async_set_source(
        self, source: str, check_state: bool = False
    ) -> bool:
        """Set input source.

        Args:
            source: Source name (hdmi1, hdmi2, tv, av) or ID
            check_state: Check TV is on first

        Returns:
            True if sent successfully
        """
        return await self._call("set_source", source, check_state=check_state)

    # State
    async def async_get_state(self, timeout: float = 5.0) -> Optional[dict]:
        """Get TV state information.

        Returns:
            State dict or None
        """
        return await self._call("get_state", timeout=timeout)

    async def async_is_on(self) -> bool:
        """Check if TV is powered on.

        Returns:
            True if TV is on
        """
        return await self._call("is_on")

    # Device info
    async def async_get_tv_info(self, timeout: float = 5.0) -> Optional[dict]:
        """Get TV info (chipplatform, brand, etc).

        Returns:
            TV info dict or None
        """
        return await self._call("get_tv_info", timeout=timeout)

    async def async_get_device_info(self, timeout: float = 5.0) -> Optional[dict]:
        """Get device info (model, name, version, etc).

        Returns:
            Device info dict or None
        """
        return await self._call("get_device_info", timeout=timeout)

    async def async_get_capability(self, timeout: float = 5.0) -> Optional[dict]:
        """Get TV capabilities.

        Returns:
            Capability dict or None
        """
        return await self._call("get_capability", timeout=timeout)

    # Apps
    async def async_get_apps(self, timeout: float = 5.0) -> Optional[List[dict]]:
        """Get list of available apps.

        Returns:
            List of app dicts or None
        """
        return await self._call("get_apps", timeout=timeout)

    async def async_launch_app(
        self, app_name: str, check_state: bool = False
    ) -> bool:
        """Launch an app.

        Args:
            app_name: App name (netflix, youtube, etc) or app dict
            check_state: Check TV is on first

        Returns:
            True if sent successfully
        """
        return await self._call("launch_app", app_name, check_state=check_state)

    # Async context manager
    async def __aenter__(self) -> "AsyncVidaaTV":
        """Async context manager entry."""
        await self.async_connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.async_disconnect()

    # Sync method aliases (for backwards compatibility or when blocking is OK)
    def connect(self, *args, **kwargs) -> bool:
        """Sync connect (blocking)."""
        return self._ensure_client().connect(*args, **kwargs)

    def disconnect(self) -> None:
        """Sync disconnect (blocking)."""
        if self._client:
            return self._client.disconnect()

    def send_key(self, *args, **kwargs) -> bool:
        """Sync send_key (blocking)."""
        return self._ensure_client().send_key(*args, **kwargs)

    def power(self) -> bool:
        """Sync power toggle (blocking)."""
        return self._ensure_client().power()

    def get_volume(self, *args, **kwargs) -> Optional[int]:
        """Sync get_volume (blocking)."""
        return self._ensure_client().get_volume(*args, **kwargs)

    def set_volume(self, *args, **kwargs) -> bool:
        """Sync set_volume (blocking)."""
        return self._ensure_client().set_volume(*args, **kwargs)

    def get_state(self, *args, **kwargs) -> Optional[dict]:
        """Sync get_state (blocking)."""
        return self._ensure_client().get_state(*args, **kwargs)

    def get_apps(self, *args, **kwargs) -> Optional[List[dict]]:
        """Sync get_apps (blocking)."""
        return self._ensure_client().get_apps(*args, **kwargs)

    def launch_app(self, *args, **kwargs) -> bool:
        """Sync launch_app (blocking)."""
        return self._ensure_client().launch_app(*args, **kwargs)


# Async discovery functions
async def async_discover_ssdp(
    timeout: float = 5.0,
    interface: Optional[str] = None,
    executor: Optional[ThreadPoolExecutor] = None,
) -> dict:
    """Discover devices via SSDP M-SEARCH (async).

    Args:
        timeout: Discovery timeout in seconds
        interface: Interface IP to bind to
        executor: Custom executor (uses default if None)

    Returns:
        Dict mapping IP addresses to DiscoveredTV objects
    """
    from .discovery import discover_ssdp

    loop = asyncio.get_running_loop()
    exec = executor or _get_executor()
    return await loop.run_in_executor(
        exec,
        partial(discover_ssdp, timeout=timeout, interface=interface),
    )


async def async_discover_udp(
    timeout: float = 5.0,
    retries: int = 3,
    interface: Optional[str] = None,
    executor: Optional[ThreadPoolExecutor] = None,
) -> dict:
    """Discover devices via UDP broadcast (async).

    Args:
        timeout: Discovery timeout in seconds
        retries: Number of discovery attempts
        interface: Interface IP to bind to
        executor: Custom executor (uses default if None)

    Returns:
        Dict mapping IP addresses to DiscoveredTV objects
    """
    from .discovery import discover_udp

    loop = asyncio.get_running_loop()
    exec = executor or _get_executor()
    return await loop.run_in_executor(
        exec,
        partial(discover_udp, timeout=timeout, retries=retries, interface=interface),
    )


async def async_probe_ip(
    ip: str,
    port: Optional[int] = None,
    timeout: float = 3.0,
    executor: Optional[ThreadPoolExecutor] = None,
) -> Optional[Any]:
    """Probe a specific IP for a TV (async).

    Args:
        ip: Target IP address
        port: UPnP port. If None (default), each candidate in UPNP_PORTS is
            tried in order (some VIDAA OS versions use 18400 instead of 38400).
        timeout: Probe timeout
        executor: Custom executor

    Returns:
        DiscoveredTV if found, None otherwise
    """
    from .discovery import probe_ip

    loop = asyncio.get_running_loop()
    exec = executor or _get_executor()
    return await loop.run_in_executor(
        exec,
        partial(probe_ip, ip, port=port, timeout=timeout),
    )


async def async_discover_all(
    timeout: float = 5.0,
    interface: Optional[str] = None,
    methods: Optional[list] = None,
    executor: Optional[ThreadPoolExecutor] = None,
) -> dict:
    """Run multiple discovery methods (async).

    Args:
        timeout: Timeout per method in seconds
        interface: Interface IP to bind to
        methods: List of methods ["ssdp", "ssdp_listen", "udp"]
        executor: Custom executor

    Returns:
        Dict mapping IP addresses to DiscoveredTV objects
    """
    from .discovery import discover_all

    loop = asyncio.get_running_loop()
    exec = executor or _get_executor()
    return await loop.run_in_executor(
        exec,
        partial(discover_all, timeout=timeout, interface=interface, methods=methods),
    )


async def async_detect_protocol(
    host: str,
    port: Optional[int] = None,
    timeout: float = 5.0,
    executor: Optional[ThreadPoolExecutor] = None,
) -> Optional[int]:
    """Detect TV protocol version (async).

    Args:
        host: TV IP address
        port: HTTP port. If None (default), each candidate in UPNP_PORTS is
            tried in order (some VIDAA OS versions use 18400 instead of 38400).
        timeout: Request timeout

    Returns:
        Protocol version integer or None
    """
    from .protocol import detect_protocol

    loop = asyncio.get_running_loop()
    exec = executor or _get_executor()
    return await loop.run_in_executor(
        exec,
        partial(detect_protocol, host, port=port, timeout=timeout),
    )


# Backwards-compatible alias (renamed from AsyncHisenseTV in 2.1.0). Deprecated.
AsyncHisenseTV = AsyncVidaaTV
