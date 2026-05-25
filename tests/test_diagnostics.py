"""Tests for the Hisense TV diagnostics."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.vidaa_tv.const import DOMAIN
from custom_components.vidaa_tv.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)

from .conftest import MOCK_CONFIG_ENTRY_DATA, MOCK_DEVICE_INFO, create_mock_config_entry


async def test_diagnostics(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test diagnostics output."""
    entry = create_mock_config_entry(hass, options={"scan_interval": 30})
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    # Check structure matches diagnostics.py output
    assert "config_entry" in diagnostics
    assert "coordinator" in diagnostics
    assert "tv_connection" in diagnostics

    # Check config_entry section
    assert "data" in diagnostics["config_entry"]
    assert "options" in diagnostics["config_entry"]

    # Check redaction of sensitive fields
    config_data = diagnostics["config_entry"]["data"]
    for key in TO_REDACT:
        if key in config_data:
            assert config_data[key] == "**REDACTED**"

    # Check coordinator info
    assert diagnostics["coordinator"]["available"] is True
    assert diagnostics["coordinator"]["last_update_success"] is True

    # Check TV connection
    assert diagnostics["tv_connection"]["connected"] is True


async def test_diagnostics_tv_offline(
    hass: HomeAssistant,
    mock_vidaa_tv: MagicMock,
) -> None:
    """Test diagnostics when TV is offline."""
    mock_vidaa_tv.is_connected = False

    entry = create_mock_config_entry(hass)
    entry.add_to_hass(hass)

    with patch(
        "custom_components.vidaa_tv.AsyncVidaaTV",
        return_value=mock_vidaa_tv,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["tv_connection"]["connected"] is False
    assert diagnostics["tv_connection"]["device_info"] is None


def test_redaction_keys() -> None:
    """Test that all sensitive keys are in TO_REDACT."""
    expected_redact_keys = {
        "mac",
        "device_id",
        "certfile",
        "keyfile",
        "host",
        "network_type",
        "eth0",
        "wlan0",
    }
    assert TO_REDACT == expected_redact_keys
