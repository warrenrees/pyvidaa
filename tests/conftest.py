"""Fixtures for Hisense TV tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

# Enable pytest-homeassistant-custom-component
pytest_plugins = ["pytest_homeassistant_custom_component"]

from custom_components.vidaa_tv.const import (
    CONF_CERTFILE,
    CONF_DEVICE_ID,
    CONF_KEYFILE,
    CONF_MAC,
    CONF_MODEL,
    CONF_SW_VERSION,
    DEFAULT_PORT,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield


def create_mock_config_entry(
    hass: HomeAssistant,
    data: dict | None = None,
    options: dict | None = None,
    entry_id: str = "test_entry_id",
    unique_id: str | None = "001122334455",
    title: str = "Living Room TV",
) -> "MockConfigEntry":
    """Create a mock config entry for testing."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data=data or MOCK_CONFIG_ENTRY_DATA,
        options=options or {},
        entry_id=entry_id,
        unique_id=unique_id,
    )


# Mock device info returned by TV
MOCK_DEVICE_INFO = {
    "tv_name": "Living Room TV",
    "model_name": "H55A6500",
    "network_type": "001122334455",
    "tv_version": "V0000.01.00a.N0816",
    "eth0": "001122334455",
    "wlan0": "665544332211",
}

# Mock TV state
MOCK_TV_STATE = {
    "statetype": "app",
    "name": "netflix",
    "url": "netflix://",
}

MOCK_TV_STATE_OFF = {
    "statetype": "fake_sleep_0",
}

# Default config entry data
MOCK_CONFIG_ENTRY_DATA = {
    CONF_HOST: "192.168.1.100",
    CONF_PORT: DEFAULT_PORT,
    CONF_NAME: "Living Room TV",
    CONF_DEVICE_ID: "001122334455",
    CONF_MAC: "aa:bb:cc:dd:ee:ff",
    CONF_MODEL: "H55A6500",
    CONF_SW_VERSION: "V0000.01.00a.N0816",
    CONF_CERTFILE: "/config/certs/vidaa_client.pem",
    CONF_KEYFILE: "/config/certs/vidaa_client.key",
}


@pytest.fixture
def mock_vidaa_tv() -> Generator[MagicMock, None, None]:
    """Create a mock AsyncVidaaTV client instance."""
    mock_instance = MagicMock()

    # Connection methods
    mock_instance.async_connect = AsyncMock(return_value=True)
    mock_instance.async_disconnect = AsyncMock()
    mock_instance.async_reset = AsyncMock()
    mock_instance.is_connected = True

    # Token lifecycle
    mock_instance.async_token_status = AsyncMock(
        return_value={
            "has_token": True,
            "access_valid": True,
            "access_expires_in": 7 * 24 * 3600,
            "needs_refresh": False,
            "needs_reauth": False,
        }
    )
    mock_instance.async_refresh_token = AsyncMock(return_value=True)

    # Device info methods
    mock_instance.async_get_device_info = AsyncMock(return_value=MOCK_DEVICE_INFO)
    mock_instance.async_get_tv_info = AsyncMock(
        return_value={"deviceid": "001122334455"}
    )

    # State methods
    mock_instance.async_get_state = AsyncMock(return_value=MOCK_TV_STATE)
    mock_instance.async_get_volume = AsyncMock(return_value=50)
    mock_instance.is_muted = False

    # Control methods
    mock_instance.async_power_on = AsyncMock()
    mock_instance.async_power_off = AsyncMock()
    mock_instance.async_volume_up = AsyncMock()
    mock_instance.async_volume_down = AsyncMock()
    mock_instance.async_mute = AsyncMock()
    mock_instance.async_set_volume = AsyncMock()
    mock_instance.async_set_source = AsyncMock()
    mock_instance.async_send_key = AsyncMock()
    mock_instance.async_launch_app = AsyncMock()

    # App/source methods
    mock_instance.async_get_apps = AsyncMock(
        return_value=[
            {"name": "Netflix", "appId": "netflix"},
            {"name": "YouTube", "appId": "youtube"},
        ]
    )
    mock_instance.async_get_sources = AsyncMock(
        return_value=[
            {"sourceid": 1, "sourcename": "HDMI1", "displayname": "HDMI 1"},
            {"sourceid": 2, "sourcename": "HDMI2", "displayname": "HDMI 2"},
        ]
    )

    # Pairing methods
    mock_instance.async_start_pairing = AsyncMock()
    mock_instance.async_authenticate = AsyncMock(return_value=True)

    yield mock_instance


@pytest.fixture
def mock_vidaa_tv_offline() -> Generator[MagicMock, None, None]:
    """Create a mock AsyncVidaaTV client that fails to connect."""
    mock_instance = MagicMock()
    mock_instance.async_connect = AsyncMock(return_value=False)
    mock_instance.async_disconnect = AsyncMock()
    mock_instance.is_connected = False

    yield mock_instance


@pytest.fixture
def mock_config_flow_tv() -> Generator[MagicMock, None, None]:
    """Mock AsyncVidaaTV for config flow tests."""
    probe_device = MagicMock()
    probe_device.brand = "his"
    probe_device.mac = "00:11:22:33:44:55"
    with patch(
        "custom_components.vidaa_tv.config_flow.AsyncVidaaTV", autospec=True
    ) as mock_class, patch(
        "custom_components.vidaa_tv.config_flow.probe_ip",
        return_value=probe_device,
    ):
        mock_instance = mock_class.return_value

        mock_instance.async_connect = AsyncMock(return_value=True)
        mock_instance.async_disconnect = AsyncMock()
        mock_instance.async_get_device_info = AsyncMock(return_value=MOCK_DEVICE_INFO)
        mock_instance.async_get_tv_info = AsyncMock(
            return_value={"deviceid": "001122334455"}
        )
        mock_instance.async_start_pairing = AsyncMock()
        mock_instance.async_authenticate = AsyncMock(return_value=True)

        yield mock_instance


@pytest.fixture
def mock_certs_exist() -> Generator[MagicMock, None, None]:
    """Mock certificate files existing."""
    with patch(
        "custom_components.vidaa_tv.config_flow.check_certs_exist",
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def mock_certs_not_exist() -> Generator[MagicMock, None, None]:
    """Mock certificate files not existing."""
    with patch(
        "custom_components.vidaa_tv.config_flow.check_certs_exist",
        return_value=False,
    ) as mock:
        yield mock


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock, None, None]:
    """Mock async_setup_entry."""
    with patch(
        "custom_components.vidaa_tv.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def mock_wake_tv() -> Generator[MagicMock, None, None]:
    """Mock wake_tv WoL function."""
    with patch("custom_components.vidaa_tv.coordinator.wake_tv") as mock:
        yield mock
