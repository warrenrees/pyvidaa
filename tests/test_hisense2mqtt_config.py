"""Tests for the hisense2mqtt bridge config expansion (multi-TV support)."""

from __future__ import annotations

from hisense2mqtt.config import expand_tv_configs


def _base():
    return {
        "mqtt": {"host": "broker.local", "port": 1883},
        "options": {"poll_interval": 30},
        "_config_path": "config.yaml",
    }


def test_expands_multiple_tvs():
    config = {
        **_base(),
        "tvs": {
            "10.0.0.10": {
                "host": "10.0.0.10",
                "mac": "AA:BB:CC:DD:EE:01",
                "name": "Living Room",
            },
            "10.0.0.11": {
                "host": "10.0.0.11",
                "uuid": "11:22:33:44:55:66",
                "alias": "bedroom",
            },
        },
        "default_tv": "10.0.0.10",
    }
    scoped = expand_tv_configs(config)
    assert len(scoped) == 2

    by_host = {s["tv"]["host"]: s["tv"] for s in scoped}
    # uuid falls back to mac when not given explicitly
    assert by_host["10.0.0.10"]["uuid"] == "AA:BB:CC:DD:EE:01"
    assert by_host["10.0.0.10"]["name"] == "Living Room"
    # explicit uuid is preferred; alias becomes the name fallback
    assert by_host["10.0.0.11"]["uuid"] == "11:22:33:44:55:66"
    assert by_host["10.0.0.11"]["name"] == "bedroom"

    # Shared sections are carried into each scoped config
    for s in scoped:
        assert s["mqtt"]["host"] == "broker.local"
        assert s["options"]["poll_interval"] == 30


def test_host_falls_back_to_tvs_key():
    config = {**_base(), "tvs": {"10.0.0.20": {"mac": "AA:BB:CC:DD:EE:02"}}}
    scoped = expand_tv_configs(config)
    assert len(scoped) == 1
    assert scoped[0]["tv"]["host"] == "10.0.0.20"


def test_legacy_singular_tv_still_works():
    config = {
        **_base(),
        "tv": {"host": "10.0.0.30", "uuid": "DE:AD:BE:EF:00:01", "name": "Old"},
    }
    scoped = expand_tv_configs(config)
    assert len(scoped) == 1
    assert scoped[0]["tv"]["host"] == "10.0.0.30"
    assert scoped[0]["tv"]["uuid"] == "DE:AD:BE:EF:00:01"


def test_no_tvs_returns_empty():
    assert expand_tv_configs(_base()) == []
