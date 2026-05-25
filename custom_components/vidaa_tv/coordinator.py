"""Data update coordinator for Hisense TV."""

from __future__ import annotations

import ipaddress
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from pyvidaa import APPS
from pyvidaa.wol import wake_tv
from .const import DOMAIN, SCAN_INTERVAL, STATE_FAKE_SLEEP, CONF_DEVICE_ID, CONF_HOST

_LOGGER = logging.getLogger(__name__)


def _ipv4_broadcast_subnet(host: str) -> str | None:
    """Return the /24 subnet prefix (e.g. "10.0.0") for an IPv4 host.

    Returns None for hostnames or IPv6 addresses; wake_tv then falls back to
    the global broadcast address.
    """
    try:
        if isinstance(ipaddress.ip_address(host), ipaddress.IPv4Address):
            return host.rsplit(".", 1)[0]
    except ValueError:
        pass
    return None


class VidaaTVDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage data updates from Hisense TV."""

    def __init__(
        self,
        hass: HomeAssistant,
        tv,  # AsyncVidaaTV
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        # Get scan interval from options, with fallback to default
        scan_interval = entry.options.get("scan_interval", SCAN_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.tv = tv
        self.entry = entry
        self._available = True
        self._device_info_fetched = False
        self._auth_failures = 0

    @property
    def available(self) -> bool:
        """Return if TV is available."""
        return self._available

    async def _async_update_device_info(self) -> None:
        """Fetch and update device info in the device registry."""
        if self._device_info_fetched:
            return

        try:
            device_info = await self.tv.async_get_device_info(timeout=5)
            _LOGGER.debug("Got device info: %s", device_info)

            if not device_info:
                _LOGGER.warning("No device info returned from TV")
                return

            device_id = self.entry.data.get(CONF_DEVICE_ID)
            _LOGGER.debug("Config entry device_id: %s", device_id)

            if not device_id:
                # Use MAC address based on network_type
                network_type = device_info.get("network_type", "")
                if network_type == "wlan":
                    device_id = device_info.get("wlan0")
                else:
                    device_id = device_info.get("eth0")
                # Fallback if primary not found
                if not device_id:
                    device_id = device_info.get("eth0") or device_info.get("wlan0")
                _LOGGER.debug("Using %s MAC as device_id: %s", network_type or "fallback", device_id)

            # Update device registry - try device_id first, then entry_id as fallback
            device_registry = dr.async_get(self.hass)
            device_entry = None

            # Try with device_id from device info
            if device_id:
                device_entry = device_registry.async_get_device(
                    identifiers={(DOMAIN, device_id)}
                )
                _LOGGER.debug("Lookup by device_id %s: found=%s", device_id, device_entry is not None)

            # Fallback to entry_id (used when device_id was None during setup)
            if not device_entry:
                device_entry = device_registry.async_get_device(
                    identifiers={(DOMAIN, self.entry.entry_id)}
                )
                _LOGGER.debug("Lookup by entry_id %s: found=%s", self.entry.entry_id, device_entry is not None)

            if device_entry:
                updates = {}
                model = device_info.get("model_name")
                sw_version = device_info.get("tv_version")
                name = device_info.get("tv_name")

                _LOGGER.debug("Device info - model: %s, sw_version: %s, name: %s",
                             model, sw_version, name)

                if model and model != device_entry.model:
                    updates["model"] = model
                if sw_version and sw_version != device_entry.sw_version:
                    updates["sw_version"] = sw_version
                if name and name != device_entry.name:
                    updates["name"] = name

                if updates:
                    # Update the device in the registry
                    device_registry.async_update_device(device_entry.id, **updates)
                    _LOGGER.info("Updated device info for %s: %s", device_entry.id, updates)

                    # Schedule a save to persist changes
                    device_registry.async_schedule_save()

                    # Also update the config entry data for future loads
                    new_data = dict(self.entry.data)
                    if model:
                        new_data["model"] = model
                    if sw_version:
                        new_data["sw_version"] = sw_version
                    if device_id:
                        new_data["device_id"] = device_id
                    self.hass.config_entries.async_update_entry(self.entry, data=new_data)
                    _LOGGER.debug("Updated config entry data with device info")
                else:
                    _LOGGER.debug("No device info updates needed")
            else:
                _LOGGER.warning("Device not found in registry with id: %s", device_id)

            self._device_info_fetched = True

        except Exception as err:
            _LOGGER.warning("Error fetching device info: %s", err)

    # Refresh the access token when it has less than this until expiry.
    _TOKEN_REFRESH_THRESHOLD = 24 * 60 * 60  # 1 day

    async def _async_maybe_refresh_token(self) -> None:
        """Proactively refresh the access token while connected.

        The access token lasts ~7 days; refreshing before it expires keeps a
        continuously-loaded integration authenticated without an HA restart or
        reload. A successful refresh persists a new token, so the expiry check
        stops firing afterwards.
        """
        try:
            status = await self.tv.async_token_status()
            if not status.get("has_token") or status.get("needs_reauth"):
                return
            near_expiry = (
                status.get("access_valid")
                and status.get("access_expires_in", 0) < self._TOKEN_REFRESH_THRESHOLD
            )
            if status.get("needs_refresh") or near_expiry:
                _LOGGER.debug(
                    "Access token near expiry (%ss left), refreshing",
                    status.get("access_expires_in", 0),
                )
                if not await self.tv.async_refresh_token():
                    _LOGGER.debug("Proactive token refresh failed")
        except Exception as err:
            _LOGGER.debug("Token refresh check failed: %s", err)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from TV."""
        import time
        start = time.monotonic()

        try:
            # Check connection
            if not self.tv.is_connected:
                _LOGGER.debug("TV disconnected, rebuilding client and reconnecting")
                # Rebuild the client so saved-token status is re-evaluated; an
                # expired access token is then refreshed from the refresh token
                # rather than being replayed and rejected.
                try:
                    await self.tv.async_reset()
                except Exception:
                    pass
                # Try to connect with longer timeout for wake-up scenarios
                connected = await self.tv.async_connect(timeout=5)
                if not connected:
                    self._available = False
                    raise UpdateFailed("Failed to connect to TV")
                _LOGGER.debug("Reconnect took %.2fs", time.monotonic() - start)

            self._available = True

            # Renew the access token before it lapses while connected.
            await self._async_maybe_refresh_token()

            # Update device info on first successful connection
            await self._async_update_device_info()

            # Get current state
            state_start = time.monotonic()
            state = await self.tv.async_get_state(timeout=3)
            _LOGGER.debug("get_state took %.2fs, raw state: %s", time.monotonic() - state_start, state)

            # Determine power state
            is_on = True
            if state:
                if state.get("statetype") == STATE_FAKE_SLEEP:
                    is_on = False
            else:
                # No state response - TV might be off or unreachable
                is_on = False

            # Get volume and mute status (only if TV is on)
            # Note: getvolume request may not work on all TVs, but volume is cached
            # from volumechange broadcasts when user changes volume
            volume = None
            is_muted = False
            if is_on:
                try:
                    vol_start = time.monotonic()
                    # Short timeout since TV may not respond to direct volume query
                    volume = await self.tv.async_get_volume(timeout=1)
                    is_muted = self.tv.is_muted
                    _LOGGER.debug("get_volume took %.2fs, volume=%s, muted=%s",
                                 time.monotonic() - vol_start, volume, is_muted)
                except Exception as err:
                    _LOGGER.debug("get_volume failed: %s", err)

            # Build data dict
            # State contains 'statetype' which indicates current activity:
            # - 'app': running an app (has 'name', 'url', 'appId' fields)
            # - 'sourceswitch': watching a source (has 'sourceid', 'sourcename' fields)
            # - 'remote_launcher': at home screen
            # - 'fake_sleep_0': TV is off/sleeping
            statetype = state.get("statetype") if state else None

            # Extract current app or source based on statetype
            app = None
            source = None
            if state:
                if statetype == "app":
                    app_key = state.get("name", "").lower()
                    # Get human-readable name from library's APPS dict
                    if app_key in APPS:
                        app = APPS[app_key].get("name", app_key)
                    else:
                        # Fallback: capitalize first letter
                        app = state.get("name", "").capitalize()
                elif statetype == "sourceswitch":
                    source = state.get("displayname") or state.get("sourcename")

            data = {
                "is_on": is_on,
                "state": state,
                "statetype": statetype,
                "volume": volume,
                "is_muted": is_muted,
                "app": app,
                "source": source,
            }

            _LOGGER.debug("State data: is_on=%s, statetype=%s, volume=%s, app=%s, source=%s",
                         is_on, statetype, volume, app, source)
            _LOGGER.debug("Total update took %.2fs", time.monotonic() - start)
            return data

        except Exception as err:
            self._available = False
            # Check for auth-related errors that should trigger reauth
            error_str = str(err).lower()
            if "auth" in error_str or "unauthorized" in error_str or "forbidden" in error_str:
                self._auth_failures += 1
                if self._auth_failures >= 3:
                    _LOGGER.warning("Multiple auth failures, triggering reauthentication")
                    raise ConfigEntryAuthFailed(
                        "Authentication failed. Please re-pair with the TV."
                    ) from err
            raise UpdateFailed(f"Error communicating with TV: {err}") from err

    async def async_turn_on(self) -> None:
        """Turn TV on using WoL and power command."""
        # Resolve the WoL target MAC: explicit wol_mac option wins, else the
        # TV's hardware MAC stored as device_id. Normalize to bare hex so a
        # colon/dash-formatted value still works.
        raw_mac = self.entry.options.get("wol_mac") or self.entry.data.get(CONF_DEVICE_ID)
        normalized = (raw_mac or "").replace(":", "").replace("-", "").lower()
        if len(normalized) == 12 and all(c in "0123456789abcdef" for c in normalized):
            mac = ":".join(normalized[i:i+2] for i in range(0, 12, 2))
            # Derive a /24 broadcast subnet only for a real IPv4 host.
            host = self.entry.data.get(CONF_HOST, "")
            subnet = _ipv4_broadcast_subnet(host)
            _LOGGER.debug("Sending WoL to %s", mac)
            await self.hass.async_add_executor_job(wake_tv, mac, subnet)
        else:
            _LOGGER.warning(
                "Skipping Wake-on-LAN: no valid MAC (got %r). Set a 'wol_mac' in the "
                "integration options to enable wake-on-LAN.",
                raw_mac,
            )

        # Also send power on command
        await self.tv.async_power_on()
        await self.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn TV off."""
        await self.tv.async_power_off()
        await self.async_request_refresh()

    async def async_volume_up(self) -> None:
        """Increase volume."""
        await self.tv.async_volume_up()
        await self.async_request_refresh()

    async def async_volume_down(self) -> None:
        """Decrease volume."""
        await self.tv.async_volume_down()
        await self.async_request_refresh()

    async def async_mute(self) -> None:
        """Toggle mute."""
        await self.tv.async_mute()
        await self.async_request_refresh()

    async def async_set_volume(self, volume: int) -> None:
        """Set volume level."""
        await self.tv.async_set_volume(volume)
        await self.async_request_refresh()

    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        await self.tv.async_set_source(source)
        await self.async_request_refresh()

    async def async_send_key(self, key: str) -> None:
        """Send remote key."""
        await self.tv.async_send_key(key)

    async def async_launch_app(self, app_name: str) -> None:
        """Launch app."""
        await self.tv.async_launch_app(app_name)
        await self.async_request_refresh()

    async def async_get_apps(self) -> list[dict] | None:
        """Get available apps."""
        return await self.tv.async_get_apps()

    async def async_get_sources(self) -> list[dict] | None:
        """Get available sources."""
        return await self.tv.async_get_sources()
