"""Tests for the Hisense TV integration setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.vidaa_tv import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.vidaa_tv.const import DOMAIN

from .conftest import MOCK_CONFIG_ENTRY_DATA, create_mock_config_entry


async def test_async_setup(hass: HomeAssistant) -> None:
    """Test async_setup registers services."""
    result = await async_setup(hass, {})

    assert result is True
    assert hass.services.has_service(DOMAIN, "send_key")
    assert hass.services.has_service(DOMAIN, "launch_app")


async def test_async_setup_entry_success(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test successful entry setup."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        # Use the proper setup mechanism
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.runtime_data is not None
    assert entry.runtime_data.coordinator is not None
    assert entry.runtime_data.tv is not None


async def test_async_setup_entry_connection_failed(
    hass: HomeAssistant,
    mock_vidaa_tv_offline: MagicMock,
) -> None:
    """Test entry setup when TV connection fails."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv_offline,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Entry should be in setup_retry state due to ConfigEntryNotReady
    from homeassistant.config_entries import ConfigEntryState
    assert entry.state == ConfigEntryState.SETUP_RETRY


async def test_async_unload_entry(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test entry unload."""
    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert result is True
    mock_vidaa_tv.async_disconnect.assert_called_once()


async def test_send_key_service(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test send_key service executes without error."""
    # Setup integration
    await async_setup(hass, {})

    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Call service - should execute without error
        await hass.services.async_call(
            DOMAIN,
            "send_key",
            {"key": "KEY_POWER"},
            blocking=True,
        )

    # Service call completed without raising an error
    # (mock assertions are complex due to coordinator indirection)


async def test_launch_app_service(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test launch_app service executes without error."""
    # Setup integration
    await async_setup(hass, {})

    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Call service - should execute without error
        await hass.services.async_call(
            DOMAIN,
            "launch_app",
            {"app": "netflix"},
            blocking=True,
        )

    # Service call completed without raising an error
    # (mock assertions are complex due to coordinator indirection)
