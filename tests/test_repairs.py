"""Tests for the Hisense TV repairs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir

from custom_components.vidaa_tv.const import (
    DEFAULT_CERT_DIR,
    DEFAULT_CERT_FILENAME,
    DEFAULT_KEY_FILENAME,
    DOMAIN,
)
from custom_components.vidaa_tv.repairs import (
    CertificateMissingRepairFlow,
    ConnectionFailedRepairFlow,
    async_create_fix_flow,
    create_certificate_issue,
    create_connection_issue,
    delete_issue,
)


async def test_async_create_fix_flow_certificate_missing(
    hass: HomeAssistant,
) -> None:
    """Test creating a certificate missing repair flow."""
    flow = await async_create_fix_flow(
        hass, "certificate_missing_test_entry", None
    )
    assert isinstance(flow, CertificateMissingRepairFlow)


async def test_async_create_fix_flow_connection_failed(
    hass: HomeAssistant,
) -> None:
    """Test creating a connection failed repair flow."""
    flow = await async_create_fix_flow(
        hass, "connection_failed_test_entry", None
    )
    assert isinstance(flow, ConnectionFailedRepairFlow)


async def test_async_create_fix_flow_default(
    hass: HomeAssistant,
) -> None:
    """Test creating a default repair flow for unknown issue types."""
    flow = await async_create_fix_flow(hass, "unknown_issue", None)
    assert isinstance(flow, ConfirmRepairFlow)


async def test_certificate_missing_flow_init(
    hass: HomeAssistant,
) -> None:
    """Test certificate missing repair flow init step."""
    flow = CertificateMissingRepairFlow()
    flow.hass = hass

    result = await flow.async_step_init()

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm"


async def test_certificate_missing_flow_confirm_show_form(
    hass: HomeAssistant,
) -> None:
    """Test certificate missing repair flow shows form."""
    flow = CertificateMissingRepairFlow()
    flow.hass = hass

    result = await flow.async_step_confirm()

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert "cert_dir" in result["description_placeholders"]
    assert "cert_file" in result["description_placeholders"]
    assert "key_file" in result["description_placeholders"]


async def test_certificate_missing_flow_confirm_certs_exist(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Test certificate missing repair flow when certs now exist."""
    # Create cert directory and files
    cert_dir = tmp_path / DEFAULT_CERT_DIR
    cert_dir.mkdir(parents=True)
    (cert_dir / DEFAULT_CERT_FILENAME).touch()
    (cert_dir / DEFAULT_KEY_FILENAME).touch()

    # Mock hass.config.config_dir to use tmp_path
    hass.config.config_dir = str(tmp_path)

    flow = CertificateMissingRepairFlow()
    flow.hass = hass

    result = await flow.async_step_confirm(user_input={})

    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_certificate_missing_flow_confirm_certs_still_missing(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Test certificate missing repair flow when certs still missing."""
    # Don't create cert files
    hass.config.config_dir = str(tmp_path)

    flow = CertificateMissingRepairFlow()
    flow.hass = hass

    result = await flow.async_step_confirm(user_input={})

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "certificates_still_missing"


async def test_connection_failed_flow_init_show_form(
    hass: HomeAssistant,
) -> None:
    """Test connection failed repair flow shows form."""
    flow = ConnectionFailedRepairFlow()
    flow.hass = hass

    result = await flow.async_step_init()

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_connection_failed_flow_init_confirm(
    hass: HomeAssistant,
) -> None:
    """Test connection failed repair flow confirmation."""
    flow = ConnectionFailedRepairFlow()
    flow.hass = hass

    result = await flow.async_step_init(user_input={})

    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_create_certificate_issue(
    hass: HomeAssistant,
) -> None:
    """Test creating a certificate missing issue."""
    entry_id = "test_entry_id"

    create_certificate_issue(hass, entry_id)

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, f"certificate_missing_{entry_id}")

    assert issue is not None
    assert issue.is_fixable is True
    assert issue.is_persistent is True
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.translation_key == "certificate_missing"


async def test_create_connection_issue(
    hass: HomeAssistant,
) -> None:
    """Test creating a connection failed issue."""
    entry_id = "test_entry_id"
    host = "192.168.1.100"

    create_connection_issue(hass, entry_id, host)

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, f"connection_failed_{entry_id}")

    assert issue is not None
    assert issue.is_fixable is True
    assert issue.is_persistent is False
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_key == "connection_failed"


async def test_delete_issue(
    hass: HomeAssistant,
) -> None:
    """Test deleting an issue."""
    entry_id = "test_entry_id"
    issue_id = f"connection_failed_{entry_id}"

    # First create an issue
    create_connection_issue(hass, entry_id, "192.168.1.100")

    # Verify it exists
    issue_reg = ir.async_get(hass)
    assert issue_reg.async_get_issue(DOMAIN, issue_id) is not None

    # Delete it
    delete_issue(hass, issue_id)

    # Verify it's gone
    assert issue_reg.async_get_issue(DOMAIN, issue_id) is None
