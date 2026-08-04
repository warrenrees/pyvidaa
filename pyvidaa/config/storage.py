"""Token storage for persistent authentication.

Stores authentication tokens keyed by device_id (network_type from TV).
Supports backwards compatibility with host:port keys from legacy storage.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import DEFAULT_ACCESS_TOKEN_DAYS, DEFAULT_REFRESH_TOKEN_DAYS, DEFAULT_PORT

_LOGGER = logging.getLogger(__name__)


class TokenStorage:
    """Manages persistent storage of authentication tokens per device."""

    DEFAULT_STORAGE_PATH = Path.cwd() / "tokens.json"

    def __init__(self, storage_path: Optional[Path] = None):
        """Initialize token storage.

        Args:
            storage_path: Path to token storage file. Defaults to ./tokens.json
        """
        self.storage_path = storage_path or self.DEFAULT_STORAGE_PATH
        self._ensure_storage_dir()

    def _ensure_storage_dir(self):
        """Create storage directory if it doesn't exist."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> Dict[str, Any]:
        """Load all stored tokens."""
        if not self.storage_path.exists():
            return {}
        try:
            with open(self.storage_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save_all(self, data: Dict[str, Any]):
        """Save all tokens to storage."""
        self._ensure_storage_dir()
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def _find_token(self, device_id: Optional[str] = None, host: Optional[str] = None, port: int = DEFAULT_PORT) -> tuple:
        """Find token by device_id or host:port.

        Args:
            device_id: Device ID (network_type from TV)
            host: TV IP address (fallback for legacy)
            port: TV MQTT port

        Returns:
            Tuple of (key, token_data) or (None, None) if not found
        """
        data = self._load_all()

        # First try device_id
        if device_id and device_id in data:
            return device_id, data[device_id]

        # Then try host:port (legacy format)
        if host:
            legacy_key = f"{host}:{port}"
            if legacy_key in data:
                return legacy_key, data[legacy_key]

            # Also try just host as key
            if host in data:
                return host, data[host]

        return None, None

    def get_token(
        self,
        device_id: Optional[str] = None,
        host: Optional[str] = None,
        port: int = DEFAULT_PORT,
    ) -> Optional[Dict[str, Any]]:
        """Get stored token for a device.

        Args:
            device_id: Device ID (network_type from TV)
            host: TV IP address (fallback for legacy lookup)
            port: TV MQTT port

        Returns:
            Token dict with 'access_token', 'refresh_token', 'expires_at', etc.
            or None if no token stored or token expired.
        """
        key, token_data = self._find_token(device_id, host, port)

        if token_data is None:
            return None

        # Static-auth pairings carry no token to expire: the TV authorizes the
        # client_id itself, and the record only exists to reuse it.
        if self._is_tokenless(token_data):
            token_data["needs_refresh"] = False
            return token_data

        # Check if access token expired
        if self._is_expired(token_data.get("access_token_expires_at")):
            # Check if refresh token is still valid
            if not self._is_expired(token_data.get("refresh_token_expires_at")):
                # Return with flag indicating refresh needed
                token_data["needs_refresh"] = True
                return token_data
            else:
                # Both tokens expired, need re-auth
                return None

        token_data["needs_refresh"] = False
        return token_data

    def save_token(
        self,
        device_id: str,
        host: str,
        port: int = DEFAULT_PORT,
        access_token: str = None,
        refresh_token: Optional[str] = None,
        access_token_duration_days: int = DEFAULT_ACCESS_TOKEN_DAYS,
        refresh_token_duration_days: int = DEFAULT_REFRESH_TOKEN_DAYS,
        client_id: Optional[str] = None,
        mqtt_username: Optional[str] = None,
        uuid: Optional[str] = None,
        auth_method: Optional[str] = None,
        protocol_version: Optional[int] = None,
        model: Optional[str] = None,
        sw_version: Optional[str] = None,
        name: Optional[str] = None,
    ):
        """Save authentication token for a device.

        Args:
            device_id: Device ID (network_type from TV) - used as storage key
            host: TV IP address
            port: TV MQTT port
            access_token: The access token from authentication
            refresh_token: Optional refresh token
            access_token_duration_days: Days until access token expires
            refresh_token_duration_days: Days until refresh token expires
            client_id: MQTT client ID used for this connection
            mqtt_username: MQTT username used during pairing
            uuid: Device UUID (MAC address format)
            auth_method: Authentication method used (legacy, middle, modern)
            protocol_version: Detected transport protocol version
            model: TV model name (from getdeviceinfo)
            sw_version: TV software version (from getdeviceinfo)
            name: TV display name (from getdeviceinfo)
        """
        data = self._load_all()

        # Remove any legacy host:port entry for this device
        legacy_key = f"{host}:{port}"
        if legacy_key in data and legacy_key != device_id:
            del data[legacy_key]

        now = time.time()
        token_data = {
            "device_id": device_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "access_token_time": now if access_token else None,
            "access_token_expires_at": (
                now + (access_token_duration_days * 24 * 60 * 60)
                if access_token
                else None
            ),
            "refresh_token_time": now if refresh_token else None,
            "refresh_token_expires_at": now + (refresh_token_duration_days * 24 * 60 * 60) if refresh_token else None,
            "client_id": client_id,
            "mqtt_username": mqtt_username,
            "uuid": uuid,
            "host": host,
            "port": port,
            "auth_method": auth_method,
            "protocol_version": protocol_version,
            "model": model,
            "sw_version": sw_version,
            "name": name,
        }

        data[device_id] = token_data
        self._save_all(data)

    def update_token(self, device_id: str, **updates):
        """Update fields in an existing token.

        Args:
            device_id: Device ID to update
            **updates: Fields to update
        """
        data = self._load_all()

        if device_id in data:
            data[device_id].update(updates)
            self._save_all(data)

    def delete_token(
        self,
        device_id: Optional[str] = None,
        host: Optional[str] = None,
        port: int = DEFAULT_PORT,
    ):
        """Delete stored token for a device.

        Args:
            device_id: Device ID (network_type from TV)
            host: TV IP address (fallback for legacy lookup)
            port: TV MQTT port
        """
        data = self._load_all()
        key, _ = self._find_token(device_id, host, port)

        if key and key in data:
            del data[key]
            self._save_all(data)

    @staticmethod
    def _is_tokenless(token_data: Dict[str, Any]) -> bool:
        """Whether this record is a static-auth pairing (no token involved)."""
        return token_data.get("auth_method") == "static"

    def _is_expired(self, expires_at: Optional[float], buffer_seconds: int = 300) -> bool:
        """Check if a timestamp has expired (with buffer).

        Args:
            expires_at: Expiration timestamp
            buffer_seconds: Consider expired this many seconds early (default 5 min)
        """
        if expires_at is None:
            return True
        return time.time() > (expires_at - buffer_seconds)

    def get_token_status(
        self,
        device_id: Optional[str] = None,
        host: Optional[str] = None,
        port: int = DEFAULT_PORT,
    ) -> dict:
        """Get detailed token status for a device.

        Returns:
            Dict with:
                - has_token: bool - whether any token exists
                - access_valid: bool - access token is valid
                - refresh_valid: bool - refresh token is valid
                - access_expires_in: int - seconds until access token expires (or 0)
                - refresh_expires_in: int - seconds until refresh token expires (or 0)
                - needs_refresh: bool - access expired but refresh valid
                - needs_reauth: bool - both tokens expired
        """
        key, token_data = self._find_token(device_id, host, port)

        if token_data is None:
            return {
                "has_token": False,
                "access_valid": False,
                "refresh_valid": False,
                "access_expires_in": 0,
                "refresh_expires_in": 0,
                "needs_refresh": False,
                "needs_reauth": True,
            }

        if self._is_tokenless(token_data):
            # A static-auth pairing never expires or needs refreshing; only the
            # TV forgetting the client_id invalidates it, which we cannot see.
            # `tokenless` tells callers not to treat the zero expiry as "due for
            # renewal" - there is no token to renew.
            return {
                "has_token": True,
                "tokenless": True,
                "access_valid": True,
                "refresh_valid": False,
                "access_expires_in": 0,
                "refresh_expires_in": 0,
                "needs_refresh": False,
                "needs_reauth": False,
            }

        now = time.time()

        access_expires = token_data.get("access_token_expires_at", 0)
        refresh_expires = token_data.get("refresh_token_expires_at", 0)

        access_valid = not self._is_expired(access_expires)
        refresh_valid = not self._is_expired(refresh_expires)

        return {
            "has_token": True,
            "access_valid": access_valid,
            "refresh_valid": refresh_valid,
            "access_expires_in": max(0, int(access_expires - now)),
            "refresh_expires_in": max(0, int(refresh_expires - now)),
            "needs_refresh": not access_valid and refresh_valid,
            "needs_reauth": not access_valid and not refresh_valid,
        }

    def list_devices(self) -> List[Dict[str, Any]]:
        """List all devices with stored tokens.

        Returns:
            List of device dicts with device_id, host, port, and expiration info.
        """
        data = self._load_all()
        devices = []

        for key, token_data in data.items():
            devices.append({
                "device_id": token_data.get("device_id", key),
                "host": token_data.get("host"),
                "port": token_data.get("port"),
                "name": token_data.get("name"),
                "model": token_data.get("model"),
                "client_id": token_data.get("client_id"),
                "access_token_valid": not self._is_expired(token_data.get("access_token_expires_at")),
                "refresh_token_valid": not self._is_expired(token_data.get("refresh_token_expires_at")),
            })

        return devices

    def clear_all(self):
        """Clear all stored tokens."""
        self._save_all({})

    def migrate_key(self, old_key: str, new_device_id: str):
        """Migrate a token from old key format to device_id.

        Args:
            old_key: Old key (e.g., "192.168.1.50:36669")
            new_device_id: New device_id (network_type from TV)
        """
        data = self._load_all()

        if old_key in data and old_key != new_device_id:
            token_data = data.pop(old_key)
            token_data["device_id"] = new_device_id
            data[new_device_id] = token_data
            self._save_all(data)
            _LOGGER.info("Migrated token key from %s to %s", old_key, new_device_id)


# Global default storage instance
_default_storage: Optional[TokenStorage] = None


def get_storage(storage_path: Optional[Path] = None) -> TokenStorage:
    """Get the default token storage instance."""
    global _default_storage
    if _default_storage is None or storage_path is not None:
        _default_storage = TokenStorage(storage_path)
    return _default_storage


# Convenience functions
def get_token(
    device_id: Optional[str] = None,
    host: Optional[str] = None,
    port: int = DEFAULT_PORT,
) -> Optional[Dict]:
    """Get token for device."""
    return get_storage().get_token(device_id, host, port)


def save_token(device_id: str, host: str, port: int = DEFAULT_PORT, **kwargs):
    """Save token for device."""
    get_storage().save_token(device_id, host, port, **kwargs)


def delete_token(
    device_id: Optional[str] = None,
    host: Optional[str] = None,
    port: int = DEFAULT_PORT,
):
    """Delete token for device."""
    get_storage().delete_token(device_id, host, port)


def get_token_status(
    device_id: Optional[str] = None,
    host: Optional[str] = None,
    port: int = DEFAULT_PORT,
) -> Dict:
    """Get token status for device."""
    return get_storage().get_token_status(device_id, host, port)
