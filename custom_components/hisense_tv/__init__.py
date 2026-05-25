"""The Hisense TV integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_MAC,
    CONF_DEVICE_ID,
    CONF_BRAND,
    CONF_CERTFILE,
    CONF_KEYFILE,
    DEFAULT_PORT,
    PLATFORMS,
    SERVICE_SEND_KEY,
    SERVICE_LAUNCH_APP,
    ATTR_KEY,
    ATTR_APP,
)
from .coordinator import HisenseTVDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Import from PyPI package (myhisense-tv)
from hisense_tv import AsyncHisenseTV
from hisense_tv.config import get_storage


@dataclass
class HisenseTVRuntimeData:
    """Runtime data for Hisense TV integration."""

    coordinator: HisenseTVDataUpdateCoordinator
    tv: AsyncHisenseTV


type HisenseTVConfigEntry = ConfigEntry[HisenseTVRuntimeData]

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Hisense TV integration."""
    await _async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HisenseTVConfigEntry) -> bool:
    """Set up Hisense TV from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    mac = entry.data.get(CONF_MAC)
    device_id = entry.data.get(CONF_DEVICE_ID)
    brand = entry.data.get(CONF_BRAND, "his")
    certfile = entry.data.get(CONF_CERTFILE)
    keyfile = entry.data.get(CONF_KEYFILE)

    _LOGGER.debug("Setting up Hisense TV at %s:%s", host, port)

    # Create the async TV client
    tv = AsyncHisenseTV(
        host=host,
        port=port,
        certfile=certfile,
        keyfile=keyfile,
        mac_address=mac or device_id,
        use_dynamic_auth=True,
        brand=brand,
        enable_persistence=True,
    )

    # Try to connect
    try:
        connected = await tv.async_connect(timeout=10)
        if not connected:
            raise ConfigEntryNotReady(f"Failed to connect to TV at {host}")
    except Exception as err:
        _LOGGER.error("Error connecting to TV: %s", err)
        raise ConfigEntryNotReady(f"Error connecting to TV: {err}") from err

    # Create coordinator for data updates
    coordinator = HisenseTVDataUpdateCoordinator(hass, tv, entry)
    await coordinator.async_config_entry_first_refresh()

    # Store runtime data using the modern pattern
    entry.runtime_data = HisenseTVRuntimeData(coordinator=coordinator, tv=tv)

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def _async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for the integration."""

    async def async_send_key(call: ServiceCall) -> None:
        """Handle send_key service call."""
        key = call.data[ATTR_KEY]

        # Get all loaded config entries for this domain
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_tvs_configured",
            )

        for entry in entries:
            if entry.state.recoverable:
                continue
            runtime_data: HisenseTVRuntimeData = entry.runtime_data
            try:
                await runtime_data.coordinator.async_send_key(key)
            except Exception as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="command_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

    async def async_launch_app(call: ServiceCall) -> None:
        """Handle launch_app service call."""
        app = call.data[ATTR_APP]

        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_tvs_configured",
            )

        for entry in entries:
            if entry.state.recoverable:
                continue
            runtime_data: HisenseTVRuntimeData = entry.runtime_data
            try:
                await runtime_data.coordinator.async_launch_app(app)
            except Exception as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="command_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

    # Only register services once
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_KEY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_KEY,
            async_send_key,
            schema=vol.Schema({
                vol.Required(ATTR_KEY): cv.string,
            }),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_LAUNCH_APP):
        hass.services.async_register(
            DOMAIN,
            SERVICE_LAUNCH_APP,
            async_launch_app,
            schema=vol.Schema({
                vol.Required(ATTR_APP): cv.string,
            }),
        )


async def async_unload_entry(hass: HomeAssistant, entry: HisenseTVConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        runtime_data = entry.runtime_data
        if runtime_data.tv:
            await runtime_data.tv.async_disconnect()

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: HisenseTVConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
