"""Tests for hisense2mqtt bridge credential renewal behaviour."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hisense2mqtt.bridge import HisenseMQTTBridge


def _bridge():
    config = {
        "mqtt": {"host": "broker.local", "port": 1883},
        "options": {"poll_interval": 30},
        "tv": {"host": "10.0.0.50", "port": 36669, "uuid": "AA:BB:CC:DD:EE:01"},
    }
    return HisenseMQTTBridge(config)


def test_connect_tv_rebuilds_client(monkeypatch):
    """Each connect rebuilds the TV client so token status is re-read."""
    bridge = _bridge()
    calls = {"setup": 0}

    def fake_setup():
        calls["setup"] += 1
        bridge._tv = MagicMock()
        bridge._tv.connect.return_value = False  # stop early, no side effects

    monkeypatch.setattr(bridge, "_setup_tv_client", fake_setup)
    bridge._connect_tv()
    assert calls["setup"] == 1
    bridge._tv.connect.assert_called_once()


def _status(**over):
    base = {
        "has_token": True,
        "access_valid": True,
        "refresh_valid": True,
        "access_expires_in": 7 * 24 * 3600,
        "needs_refresh": False,
        "needs_reauth": False,
    }
    base.update(over)
    return base


def test_resolve_brand_prefers_explicit_config(monkeypatch):
    """An explicitly configured non-Hisense brand is used without probing."""
    bridge = _bridge()
    called = {"probe": False}

    def fake_probe(*a, **k):
        called["probe"] = True
        return MagicMock(brand="his")

    monkeypatch.setattr("hisense_tv.discovery.probe_ip", fake_probe)
    brand = bridge._resolve_brand({"host": "10.0.0.50", "brand": "tpv"})
    assert brand == "tpv"
    assert called["probe"] is False


def test_resolve_brand_autodiscovers_when_unset(monkeypatch):
    """When brand is unset/default, it is discovered via the UPnP probe."""
    bridge = _bridge()
    monkeypatch.setattr(
        "hisense_tv.discovery.probe_ip",
        lambda *a, **k: MagicMock(brand="tpv"),
    )
    assert bridge._resolve_brand({"host": "10.0.0.50"}) == "tpv"
    assert bridge._resolve_brand({"host": "10.0.0.50", "brand": "his"}) == "tpv"


def test_resolve_brand_falls_back_to_his(monkeypatch):
    """A failed probe falls back to the 'his' default."""
    bridge = _bridge()

    def boom(*a, **k):
        raise OSError("unreachable")

    monkeypatch.setattr("hisense_tv.discovery.probe_ip", boom)
    assert bridge._resolve_brand({"host": "10.0.0.50"}) == "his"


@pytest.mark.parametrize(
    "status,expect_refresh",
    [
        (_status(access_expires_in=7 * 24 * 3600), False),  # fresh -> no refresh
        (_status(access_expires_in=3600), True),            # <1 day -> refresh
        (_status(access_valid=False, needs_refresh=True), True),  # expired, refresh valid
        (_status(has_token=False), False),                  # nothing stored
        (_status(access_valid=False, refresh_valid=False, needs_reauth=True), False),
    ],
)
def test_maybe_refresh_token(monkeypatch, status, expect_refresh):
    bridge = _bridge()
    bridge._tv = MagicMock()
    bridge._tv.refresh_token.return_value = True

    fake_storage = MagicMock()
    fake_storage.get_token_status.return_value = status
    monkeypatch.setattr("hisense_tv.config.get_storage", lambda: fake_storage)

    bridge._maybe_refresh_token()

    assert bridge._tv.refresh_token.called is expect_refresh
