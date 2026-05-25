"""Config flow for Hisense TV integration."""

from __future__ import annotations

import logging
import os
import random
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import ssdp
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    DOMAIN,
    CONF_DEVICE_ID,
    CONF_MAC,
    CONF_MODEL,
    CONF_BRAND,
    CONF_SW_VERSION,
    CONF_CERTFILE,
    CONF_KEYFILE,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_CERT_DIR,
    DEFAULT_CERT_FILENAME,
    DEFAULT_KEY_FILENAME,
    TIMEOUT_CONNECT,
    SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def generate_random_mac() -> str:
    """Generate a random MAC address."""
    return ":".join(f"{random.randint(0, 255):02x}" for _ in range(6))

# Import library
import sys
from pathlib import Path

lib_path = Path(__file__).parent.parent.parent
if str(lib_path) not in sys.path:
    sys.path.insert(0, str(lib_path))

from hisense_tv import AsyncHisenseTV
from hisense_tv.discovery import probe_ip


def get_default_cert_paths(hass: HomeAssistant) -> tuple[str, str]:
    """Get default certificate paths in HA config directory."""
    config_dir = Path(hass.config.config_dir)
    cert_dir = config_dir / DEFAULT_CERT_DIR
    certfile = cert_dir / DEFAULT_CERT_FILENAME
    keyfile = cert_dir / DEFAULT_KEY_FILENAME
    return str(certfile), str(keyfile)


def check_certs_exist(certfile: str, keyfile: str) -> bool:
    """Check if certificate files exist and are readable."""
    return (
        os.path.isfile(certfile)
        and os.path.isfile(keyfile)
        and os.access(certfile, os.R_OK)
        and os.access(keyfile, os.R_OK)
    )


async def validate_connection(
    hass: HomeAssistant,
    host: str,
    port: int,
    certfile: str | None = None,
    keyfile: str | None = None,
    mac_address: str | None = None,
    brand: str = "his",
) -> dict[str, Any]:
    """Validate we can connect to the TV."""
    # Use provided MAC or generate a random one for dynamic auth
    mac = mac_address or generate_random_mac()

    tv = AsyncHisenseTV(
        host=host,
        port=port,
        certfile=certfile,
        keyfile=keyfile,
        use_dynamic_auth=True,
        mac_address=mac,
        brand=brand,
        enable_persistence=False,
    )

    try:
        connected = await tv.async_connect(timeout=TIMEOUT_CONNECT)
        if not connected:
            raise CannotConnect("Failed to connect")

        # Get device info
        device_info = await tv.async_get_device_info(timeout=5)
        tv_info = await tv.async_get_tv_info(timeout=5)

        await tv.async_disconnect()

        result = {
            "name": DEFAULT_NAME,
            "model": None,
            "device_id": None,
            "sw_version": None,
        }

        if device_info:
            result["name"] = device_info.get("tv_name", DEFAULT_NAME)
            result["model"] = device_info.get("model_name")
            result["device_id"] = device_info.get("network_type")
            result["sw_version"] = device_info.get("tv_version")

        if tv_info:
            result["device_id"] = result["device_id"] or tv_info.get("deviceid")

        return result

    except Exception as err:
        _LOGGER.error("Error validating connection: %s", err)
        try:
            await tv.async_disconnect()
        except Exception:
            pass
        raise CannotConnect(str(err)) from err


class HisenseTVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hisense TV."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._name: str = DEFAULT_NAME
        self._device_id: str | None = None
        self._mac: str = generate_random_mac()  # Random MAC for dynamic auth
        self._model: str | None = None
        self._brand: str | None = None
        self._sw_version: str | None = None
        self._discovery_info: ssdp.SsdpServiceInfo | None = None
        self._certfile: str | None = None
        self._keyfile: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step (manual IP entry)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._port = user_input.get(CONF_PORT, DEFAULT_PORT)

            # Check for certificates before connecting
            return await self.async_step_certs()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    async def async_step_certs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle certificate configuration step."""
        errors: dict[str, str] = {}

        # Get default paths
        default_certfile, default_keyfile = get_default_cert_paths(self.hass)

        if user_input is not None:
            self._certfile = user_input.get(CONF_CERTFILE) or default_certfile
            self._keyfile = user_input.get(CONF_KEYFILE) or default_keyfile

            # Validate cert paths
            if not check_certs_exist(self._certfile, self._keyfile):
                errors["base"] = "certs_not_found"
            else:
                # Try to connect with certs
                try:
                    info = await validate_connection(
                        self.hass,
                        self._host,
                        self._port,
                        certfile=self._certfile,
                        keyfile=self._keyfile,
                    )
                    self._name = info.get("name", DEFAULT_NAME)
                    self._device_id = info.get("device_id")
                    self._model = info.get("model")
                    self._sw_version = info.get("sw_version")

                    # Set unique ID if we got device_id
                    if self._device_id:
                        await self.async_set_unique_id(self._device_id)
                        self._abort_if_unique_id_configured(
                            updates={CONF_HOST: self._host, CONF_PORT: self._port}
                        )

                    return await self.async_step_pair()

                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"
        else:
            # First time - check if default certs exist
            if check_certs_exist(default_certfile, default_keyfile):
                # Default certs found, use them automatically
                self._certfile = default_certfile
                self._keyfile = default_keyfile
                try:
                    info = await validate_connection(
                        self.hass,
                        self._host,
                        self._port,
                        certfile=self._certfile,
                        keyfile=self._keyfile,
                    )
                    self._name = info.get("name", DEFAULT_NAME)
                    self._device_id = info.get("device_id")
                    self._model = info.get("model")
                    self._sw_version = info.get("sw_version")

                    if self._device_id:
                        await self.async_set_unique_id(self._device_id)
                        self._abort_if_unique_id_configured(
                            updates={CONF_HOST: self._host, CONF_PORT: self._port}
                        )

                    return await self.async_step_pair()
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"

        # Show certificate configuration form
        cert_dir = Path(self.hass.config.config_dir) / DEFAULT_CERT_DIR
        return self.async_show_form(
            step_id="certs",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_CERTFILE, default=default_certfile): str,
                    vol.Optional(CONF_KEYFILE, default=default_keyfile): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "cert_dir": str(cert_dir),
                "cert_file": DEFAULT_CERT_FILENAME,
                "key_file": DEFAULT_KEY_FILENAME,
            },
        )

    async def async_step_ssdp(
        self, discovery_info: ssdp.SsdpServiceInfo
    ) -> FlowResult:
        """Handle SSDP discovery."""
        _LOGGER.debug("SSDP discovery: %s", discovery_info)

        # Check for vidaa_support=1 in modelDescription to filter non-Hisense devices
        model_desc = discovery_info.upnp.get("modelDescription", "")
        vidaa_support = False
        for line in model_desc.split('\n'):
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                if key == 'vidaa_support' and value == '1':
                    vidaa_support = True
                elif key == 'brand' and value:
                    # brand is an auth input (part of client_id/credentials)
                    self._brand = value

        if not vidaa_support:
            _LOGGER.debug("SSDP device does not have vidaa_support=1, ignoring: %s",
                         discovery_info.ssdp_headers.get("_host"))
            return self.async_abort(reason="not_hisense_tv")

        # Extract host from discovery
        self._host = discovery_info.ssdp_headers.get("_host") or discovery_info.ssdp_location
        if self._host and "://" in self._host:
            # Extract host from URL
            from urllib.parse import urlparse
            parsed = urlparse(self._host)
            self._host = parsed.hostname

        if not self._host:
            return self.async_abort(reason="no_host")

        self._discovery_info = discovery_info
        self._name = discovery_info.upnp.get("friendlyName", DEFAULT_NAME)

        # Try to get unique ID from USN
        usn = discovery_info.ssdp_usn
        if usn:
            # USN format: uuid:XXXX::urn:schemas-upnp-org:...
            if "::" in usn:
                unique_id = usn.split("::")[0].replace("uuid:", "")
            else:
                unique_id = usn.replace("uuid:", "")
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})

        # Check for certificates
        default_certfile, default_keyfile = get_default_cert_paths(self.hass)
        if not check_certs_exist(default_certfile, default_keyfile):
            # No certs found, show cert config form
            return await self.async_step_certs()

        self._certfile = default_certfile
        self._keyfile = default_keyfile

        # Validate connection and get device info
        try:
            info = await validate_connection(
                self.hass,
                self._host,
                self._port,
                certfile=self._certfile,
                keyfile=self._keyfile,
                brand=self._brand or "his",
            )
            self._name = info.get("name", self._name)
            self._device_id = info.get("device_id")
            self._model = info.get("model")
            self._sw_version = info.get("sw_version")

            if self._device_id:
                await self.async_set_unique_id(self._device_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})

        except CannotConnect:
            return self.async_abort(reason="cannot_connect")

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm the discovered device."""
        if user_input is not None:
            return await self.async_step_pair()

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._name,
                "host": self._host,
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> FlowResult:
        """Handle reauthentication."""
        self._host = entry_data[CONF_HOST]
        self._port = entry_data.get(CONF_PORT, DEFAULT_PORT)
        self._certfile = entry_data.get(CONF_CERTFILE)
        self._keyfile = entry_data.get(CONF_KEYFILE)
        self._device_id = entry_data.get(CONF_DEVICE_ID)
        self._mac = generate_random_mac()  # New MAC for new auth
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm reauth and trigger pairing."""
        if user_input is not None:
            return await self.async_step_pair()

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"host": self._host},
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle pairing step (PIN entry)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pin = user_input.get("pin", "")

            # brand is an auth input. SSDP discovery already captured it from the
            # descriptor; for the manual entry path, probe the TV's UPnP descriptor.
            if not self._brand and self._host:
                try:
                    device = await self.hass.async_add_executor_job(
                        probe_ip, self._host
                    )
                    if device and device.brand:
                        self._brand = device.brand
                except Exception as err:  # noqa: BLE001 - best effort, falls back to "his"
                    _LOGGER.debug("Could not probe brand for %s: %s", self._host, err)

            # Create TV client for pairing
            tv = AsyncHisenseTV(
                host=self._host,
                port=self._port,
                certfile=self._certfile,
                keyfile=self._keyfile,
                use_dynamic_auth=True,
                mac_address=self._mac,
                brand=self._brand or "his",
                enable_persistence=True,
            )

            try:
                connected = await tv.async_connect(timeout=TIMEOUT_CONNECT)
                if not connected:
                    errors["base"] = "cannot_connect"
                else:
                    # Authenticate with PIN
                    success = await tv.async_authenticate(pin, timeout=10)

                    if success:
                        # Verify we're actually authenticated by getting device info
                        device_info = await tv.async_get_device_info(timeout=5)
                        await tv.async_disconnect()

                        if device_info:
                            # Update device info from successful connection
                            self._device_id = device_info.get("network_type") or self._device_id
                            self._model = device_info.get("model_name") or self._model
                            self._sw_version = device_info.get("tv_version") or self._sw_version
                            if device_info.get("tv_name"):
                                self._name = device_info.get("tv_name")

                            new_data = {
                                CONF_HOST: self._host,
                                CONF_PORT: self._port,
                                CONF_NAME: self._name,
                                CONF_DEVICE_ID: self._device_id,
                                CONF_MAC: self._mac,  # New MAC used for auth
                                CONF_MODEL: self._model,
                                CONF_BRAND: self._brand or "his",
                                CONF_SW_VERSION: self._sw_version,
                                CONF_CERTFILE: self._certfile,
                                CONF_KEYFILE: self._keyfile,
                            }

                            # Handle reauth - update existing entry
                            if self.source == config_entries.SOURCE_REAUTH:
                                return self.async_update_reload_and_abort(
                                    self._get_reauth_entry(),
                                    data=new_data,
                                )

                            # Set unique ID to prevent duplicates
                            if self._device_id:
                                await self.async_set_unique_id(self._device_id)
                                self._abort_if_unique_id_configured(
                                    updates={CONF_HOST: self._host, CONF_PORT: self._port}
                                )

                            # Create the config entry
                            return self.async_create_entry(
                                title=self._name,
                                data=new_data,
                            )
                        else:
                            # Auth seemed to succeed but can't verify
                            _LOGGER.warning("Auth succeeded but could not get device info")
                            errors["base"] = "auth_verify_failed"
                    else:
                        await tv.async_disconnect()
                        errors["base"] = "invalid_pin"

            except Exception as err:
                _LOGGER.exception("Error during pairing: %s", err)
                errors["base"] = "pairing_failed"
                try:
                    await tv.async_disconnect()
                except Exception:
                    pass

        # Show PIN dialog on TV
        tv = AsyncHisenseTV(
            host=self._host,
            port=self._port,
            certfile=self._certfile,
            keyfile=self._keyfile,
            use_dynamic_auth=True,
            mac_address=self._mac,
            enable_persistence=False,
        )

        pin_shown = False
        try:
            connected = await tv.async_connect(timeout=TIMEOUT_CONNECT)
            if connected:
                await tv.async_start_pairing()
                # Keep connection open briefly for PIN to appear
                import asyncio
                await asyncio.sleep(1)
                await tv.async_disconnect()
                pin_shown = True
            else:
                errors["base"] = "cannot_connect"
        except Exception as err:
            _LOGGER.warning("Could not trigger PIN dialog: %s", err)
            errors["base"] = "cannot_connect"

        # Only show PIN form if we successfully triggered the dialog
        if not pin_shown and not user_input:
            # Can't show PIN on TV - abort with helpful message
            return self.async_abort(reason="tv_not_responding")

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema(
                {
                    vol.Required("pin"): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "name": self._name,
                "host": self._host,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return HisenseTVOptionsFlow()


class HisenseTVOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Hisense TV."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get("scan_interval", SCAN_INTERVAL)
        current_mac = self.config_entry.data.get(CONF_MAC, "")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "scan_interval",
                        default=current_interval,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=10,
                            max=300,
                            step=5,
                            mode=NumberSelectorMode.SLIDER,
                            unit_of_measurement="seconds",
                        )
                    ),
                    vol.Optional(
                        "wol_mac",
                        default=current_mac,
                    ): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                }
            ),
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""
