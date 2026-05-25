"""Repairs for Hisense TV integration."""

from __future__ import annotations

import os
from pathlib import Path

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import (
    DOMAIN,
    CONF_CERTFILE,
    CONF_KEYFILE,
    DEFAULT_CERT_DIR,
    DEFAULT_CERT_FILENAME,
    DEFAULT_KEY_FILENAME,
)


class CertificateMissingRepairFlow(RepairsFlow):
    """Handler for certificate missing repair flow."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of a fix flow."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step of a fix flow."""
        if user_input is not None:
            # Check if certificates exist now
            config_dir = Path(self.hass.config.config_dir)
            cert_dir = config_dir / DEFAULT_CERT_DIR
            certfile = cert_dir / DEFAULT_CERT_FILENAME
            keyfile = cert_dir / DEFAULT_KEY_FILENAME

            if certfile.exists() and keyfile.exists():
                return self.async_create_entry(data={})

            return self.async_abort(reason="certificates_still_missing")

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "cert_dir": str(Path(self.hass.config.config_dir) / DEFAULT_CERT_DIR),
                "cert_file": DEFAULT_CERT_FILENAME,
                "key_file": DEFAULT_KEY_FILENAME,
            },
        )


class ConnectionFailedRepairFlow(ConfirmRepairFlow):
    """Handler for connection failed repair flow."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of a fix flow."""
        if user_input is not None:
            return self.async_create_entry(data={})

        return self.async_show_form(step_id="init")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str] | None,
) -> RepairsFlow:
    """Create flow."""
    if issue_id.startswith("certificate_missing"):
        return CertificateMissingRepairFlow()
    if issue_id.startswith("connection_failed"):
        return ConnectionFailedRepairFlow()

    # Default to a simple confirm flow
    return ConfirmRepairFlow()


def create_certificate_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Create a repair issue for missing certificates."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"certificate_missing_{entry_id}",
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="certificate_missing",
        translation_placeholders={
            "cert_dir": str(Path(hass.config.config_dir) / DEFAULT_CERT_DIR),
        },
    )


def create_connection_issue(hass: HomeAssistant, entry_id: str, host: str) -> None:
    """Create a repair issue for connection failures."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"connection_failed_{entry_id}",
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="connection_failed",
        translation_placeholders={"host": host},
    )


def delete_issue(hass: HomeAssistant, issue_id: str) -> None:
    """Delete a repair issue."""
    ir.async_delete_issue(hass, DOMAIN, issue_id)
