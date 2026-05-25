"""Tests for the Hisense TV media player entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.vidaa_tv.const import DOMAIN
from custom_components.vidaa_tv.media_player import PARALLEL_UPDATES

from .conftest import MOCK_CONFIG_ENTRY_DATA, create_mock_config_entry


def test_parallel_updates_is_set() -> None:
    """Test that PARALLEL_UPDATES is properly defined."""
    assert PARALLEL_UPDATES == 1


async def test_media_player_setup(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test media player entity setup."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Check runtime_data was set
    assert entry.runtime_data is not None


async def test_media_player_state_on(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test media player state when TV is on."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    assert coordinator.data["is_on"] is True


async def test_media_player_state_off(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test media player state when TV is off."""
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


async def test_media_player_volume(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test media player volume level."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    assert coordinator.data["volume"] == 50


async def test_media_player_turn_on(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
    mock_wake_tv: MagicMock,
) -> None:
    """Test media player turn on command."""
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

    mock_vidaa_tv.async_power_on.assert_called_once()


async def test_media_player_turn_off(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test media player turn off command."""
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

    mock_vidaa_tv.async_power_off.assert_called_once()


async def test_media_player_select_source(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test media player source selection."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    await coordinator.async_select_source("HDMI1")

    mock_vidaa_tv.async_set_source.assert_called_once_with("HDMI1")


async def test_media_player_launch_app(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test media player app launch."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    await coordinator.async_launch_app("netflix")

    mock_vidaa_tv.async_launch_app.assert_called_once_with("netflix")


async def test_media_player_send_key(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test media player send key."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    await coordinator.async_send_key("KEY_PLAY")

    mock_vidaa_tv.async_send_key.assert_called_once_with("KEY_PLAY")
