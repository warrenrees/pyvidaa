"""Tests for the Hisense TV coordinator."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.vidaa_tv.coordinator import VidaaTVDataUpdateCoordinator
from custom_components.vidaa_tv.const import DOMAIN, SCAN_INTERVAL

from .conftest import MOCK_CONFIG_ENTRY_DATA, MOCK_DEVICE_INFO, MOCK_TV_STATE, create_mock_config_entry


async def test_coordinator_update_success(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test coordinator successful update via proper entry setup."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator

    assert coordinator.data is not None
    assert coordinator.data["is_on"] is True
    assert coordinator.data["volume"] == 50
    assert coordinator.available is True


async def test_coordinator_update_tv_off(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test coordinator when TV is off."""
    mock_vidaa_tv.async_get_state = AsyncMock(
        return_value={"statetype": "fake_sleep_0"}
    )

    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    assert coordinator.data["is_on"] is False


async def test_coordinator_custom_scan_interval(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test coordinator respects custom scan interval from options."""
    entry = create_mock_config_entry(hass, options={"scan_interval": 60})
    entry.add_to_hass(hass)

    coordinator = VidaaTVDataUpdateCoordinator(hass, mock_vidaa_tv, entry)

    assert coordinator.update_interval == timedelta(seconds=60)


async def test_coordinator_default_scan_interval(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test coordinator uses default scan interval when not configured."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    coordinator = VidaaTVDataUpdateCoordinator(hass, mock_vidaa_tv, entry)

    assert coordinator.update_interval == timedelta(seconds=SCAN_INTERVAL)


async def test_coordinator_reconnect(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test coordinator reconnects when disconnected."""
    mock_vidaa_tv.is_connected = False

    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Should have rebuilt the client (reset) then reconnected
    mock_vidaa_tv.async_reset.assert_called()
    mock_vidaa_tv.async_connect.assert_called()


async def test_coordinator_refreshes_token_near_expiry(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """An access token within a day of expiry is refreshed during update."""
    mock_vidaa_tv.async_token_status = AsyncMock(
        return_value={
            "has_token": True,
            "access_valid": True,
            "access_expires_in": 3600,  # < 1 day
            "needs_refresh": False,
            "needs_reauth": False,
        }
    )

    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    mock_vidaa_tv.async_refresh_token.assert_called()


async def test_coordinator_no_refresh_when_token_fresh(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """A token with plenty of life left is not refreshed."""
    # Fixture default: access_expires_in = 7 days
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    mock_vidaa_tv.async_refresh_token.assert_not_called()


async def test_coordinator_no_refresh_when_needs_reauth(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """When both tokens are expired, don't attempt a doomed refresh."""
    mock_vidaa_tv.async_token_status = AsyncMock(
        return_value={
            "has_token": True,
            "access_valid": False,
            "access_expires_in": 0,
            "needs_refresh": False,
            "needs_reauth": True,
        }
    )

    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    mock_vidaa_tv.async_refresh_token.assert_not_called()


async def test_coordinator_turn_on_with_wol(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
    mock_wake_tv: MagicMock,
) -> None:
    """Test coordinator turn_on sends WoL and power command."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    await coordinator.async_turn_on()

    # Should send WoL
    mock_wake_tv.assert_called()
    # Should send power on command
    mock_vidaa_tv.async_power_on.assert_called()


async def test_coordinator_turn_off(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test coordinator turn_off."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    await coordinator.async_turn_off()

    mock_vidaa_tv.async_power_off.assert_called()


async def test_coordinator_volume_controls(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test coordinator volume controls."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator

    await coordinator.async_volume_up()
    mock_vidaa_tv.async_volume_up.assert_called()

    await coordinator.async_volume_down()
    mock_vidaa_tv.async_volume_down.assert_called()

    await coordinator.async_mute()
    mock_vidaa_tv.async_mute.assert_called()

    await coordinator.async_set_volume(75)
    mock_vidaa_tv.async_set_volume.assert_called_with(75)


async def test_coordinator_auth_failure_triggers_reauth(
    hass: HomeAssistant,
) -> None:
    """Test that multiple auth failures trigger reauth."""
    mock_tv = MagicMock()
    mock_tv.is_connected = True
    mock_tv.async_get_state = AsyncMock(side_effect=Exception("authentication failed"))
    mock_tv.async_disconnect = AsyncMock()

    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    coordinator = VidaaTVDataUpdateCoordinator(hass, mock_tv, entry)

    # Simulate 3 auth failures
    for _ in range(3):
        with pytest.raises((UpdateFailed, ConfigEntryAuthFailed)):
            await coordinator._async_update_data()

    # Third failure should be ConfigEntryAuthFailed
    assert coordinator._auth_failures >= 3
