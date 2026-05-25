"""Unit tests for the core hisense_tv library (no Home Assistant, no network).

These cover the logic that previously had zero test coverage and that directly
caused the live pairing failures we debugged:
  * credential generation (time-based username/password, MAC-based client_id)
  * protocol detection / auth-method selection and its retry behaviour
"""

from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from hisense_tv.client import HisenseTV
from hisense_tv.config.storage import TokenStorage
from hisense_tv.credentials import generate_credentials
from hisense_tv.protocol import (
    AuthMethod,
    detect_protocol,
    get_auth_method,
    get_auth_method_order,
)


# --- credentials -----------------------------------------------------------

# Known-good vector captured from the Vidaa app logcat (see credentials.py).
KNOWN_UUID = "56:b8:88:4e:f7:19"
KNOWN_TIME = 1766974704
EXPECTED_CLIENT_ID = "56:b8:88:4e:f7:19$his$256DBF_vidaacommon_001"
EXPECTED_USERNAME = "his$6239759786168176024"
EXPECTED_PASSWORD = "C3BA44782E18ABF4892AC44D79A622D2"


def test_modern_credentials_match_known_logcat_vector():
    creds = generate_credentials(
        KNOWN_UUID, timestamp=KNOWN_TIME, auth_method=AuthMethod.MODERN
    )
    assert creds.client_id == EXPECTED_CLIENT_ID
    assert creds.username == EXPECTED_USERNAME
    assert creds.password == EXPECTED_PASSWORD


def test_username_password_are_independent_of_mac():
    """Only client_id embeds the MAC; username/password are time-based.

    This is why a missing MAC does not (by itself) change the username/password,
    and why a clock skew - not the MAC - is the usual cause of MQTT code 5.
    """
    a = generate_credentials("AA:BB:CC:DD:EE:FF", timestamp=KNOWN_TIME)
    b = generate_credentials("11:22:33:44:55:66", timestamp=KNOWN_TIME)
    assert a.username == b.username
    assert a.password == b.password
    assert a.client_id != b.client_id


def test_credentials_change_with_timestamp():
    a = generate_credentials(KNOWN_UUID, timestamp=KNOWN_TIME)
    b = generate_credentials(KNOWN_UUID, timestamp=KNOWN_TIME + 1)
    assert a.username != b.username
    assert a.password != b.password


def test_legacy_username_has_no_xor():
    creds = generate_credentials(
        KNOWN_UUID, timestamp=KNOWN_TIME, auth_method=AuthMethod.LEGACY
    )
    assert creds.username == f"his${KNOWN_TIME}"


def test_flat_mac_is_normalised_to_colon_form():
    flat = generate_credentials("56b8884ef719", timestamp=KNOWN_TIME)
    coloned = generate_credentials(KNOWN_UUID, timestamp=KNOWN_TIME)
    assert flat.client_id == coloned.client_id


# --- auth-method selection -------------------------------------------------

@pytest.mark.parametrize(
    "version,expected",
    [
        (None, AuthMethod.MODERN),  # unknown -> modern, then fallback
        (2999, AuthMethod.LEGACY),
        (3000, AuthMethod.MIDDLE),
        (3285, AuthMethod.MIDDLE),
        (3290, AuthMethod.MODERN),
        (4000, AuthMethod.MODERN),
    ],
)
def test_get_auth_method_thresholds(version, expected):
    assert get_auth_method(version) == expected


def test_auth_method_fallback_order():
    assert get_auth_method_order() == [
        AuthMethod.MODERN,
        AuthMethod.MIDDLE,
        AuthMethod.LEGACY,
    ]


# --- protocol detection (network mocked) -----------------------------------

XML_DESCRIPTOR = (
    '<?xml version="1.0"?>'
    '<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
    "<friendlyName>Test TV</friendlyName>"
    "<modelDescription>mac=001122334455\ntransport_protocol=3290\n"
    "vidaa_support=1</modelDescription>"
    "</device></root>"
)


def _mock_urlopen_returning(xml: str):
    cm = MagicMock()
    cm.read.return_value = xml.encode("utf-8")
    cm.__enter__.return_value = cm
    cm.__exit__.return_value = False
    return cm


def test_detect_protocol_parses_version_from_descriptor():
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_returning(XML_DESCRIPTOR)):
        assert detect_protocol("10.0.0.1") == 3290


def test_detect_protocol_retries_on_transient_error_then_succeeds():
    """A single EHOSTUNREACH should not abort detection (these TVs blip)."""
    err = urllib.error.URLError(OSError(113, "No route to host"))
    calls = {"n": 0}

    def side_effect(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise err
        return _mock_urlopen_returning(XML_DESCRIPTOR)

    with patch("urllib.request.urlopen", side_effect=side_effect), \
            patch("hisense_tv.protocol.time.sleep"):
        assert detect_protocol("10.0.0.1", retries=2, retry_delay=0) == 3290
    assert calls["n"] == 2  # failed once, succeeded on retry


def test_detect_protocol_returns_none_after_exhausting_retries():
    err = urllib.error.URLError(OSError(113, "No route to host"))
    with patch("urllib.request.urlopen", side_effect=err), \
            patch("hisense_tv.protocol.time.sleep"):
        assert detect_protocol("10.0.0.1", retries=2, retry_delay=0) is None


def test_detect_protocol_falls_back_to_second_port():
    """When 38400 is unreachable, the 18400 fallback should be tried."""
    err = urllib.error.URLError(OSError(111, "Connection refused"))
    seen_ports = []

    def side_effect(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else request
        seen_ports.append(url.split(":")[2].split("/")[0])
        if ":38400/" in url:
            raise err
        return _mock_urlopen_returning(XML_DESCRIPTOR)

    with patch("urllib.request.urlopen", side_effect=side_effect), \
            patch("hisense_tv.protocol.time.sleep"):
        assert detect_protocol("10.0.0.1", retries=0) == 3290
    assert "38400" in seen_ports and "18400" in seen_ports


def test_detect_protocol_explicit_port_skips_fallback():
    """An explicit port disables the multi-port fallback."""
    err = urllib.error.URLError(OSError(111, "Connection refused"))
    seen_ports = []

    def side_effect(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else request
        seen_ports.append(url.split(":")[2].split("/")[0])
        raise err

    with patch("urllib.request.urlopen", side_effect=side_effect), \
            patch("hisense_tv.protocol.time.sleep"):
        assert detect_protocol("10.0.0.1", port=38400, retries=0) is None
    assert seen_ports == ["38400"]


# --- message handling (non-dict payloads must not crash) -------------------

def _make_client():
    return HisenseTV(
        host="10.0.0.1",
        mac_address=KNOWN_UUID,
        use_ssl=False,
        enable_persistence=False,
    )


@pytest.mark.parametrize("raw", [b'"0509"', b"42", b"true", b'"some string"'])
def test_on_message_tolerates_non_dict_payload(raw):
    """The TV sometimes publishes bare JSON scalars on the auth topic.

    Regression for: AttributeError: 'str' object has no attribute 'get'.
    """
    client = _make_client()
    msg = MagicMock()
    msg.topic = "/remoteapp/mobile/auth/authentication"
    msg.payload = raw

    client._on_message(None, None, msg)  # must not raise

    import json as _json
    assert client._last_response == _json.loads(raw.decode())
    assert client._response_event.is_set()


def test_handle_auth_response_ignores_non_dict():
    client = _make_client()
    client._handle_auth_response("not a dict")  # must not raise
    assert client._authenticated is False


# --- pairing must wait for the token, not just PIN-accept ------------------

def test_authenticate_returns_false_when_token_never_arrives():
    """PIN accepted but no token issued must NOT report success.

    Regression: authenticate() returned on PIN-accept and disconnect() then
    killed the loop before the token was saved -> 'Credentials saved' but no
    token persisted.
    """
    client = _make_client()
    client._connected = True

    def fake_publish(topic, payload=""):
        client._authenticated = True
        client._auth_event.set()  # simulate PIN accepted, but no token follows
        return True

    client._publish = fake_publish
    assert client.authenticate("1234", timeout=0.2) is False
    assert client._access_token is None


def test_authenticate_returns_true_only_after_token_received():
    client = _make_client()
    client._connected = True

    def fake_publish(topic, payload=""):
        client._authenticated = True
        client._auth_event.set()
        # The token-request publish carries {"refreshtoken": ...}
        if isinstance(payload, dict) and "refreshtoken" in payload:
            client._handle_token_response({
                "accesstoken": "ACCESS",
                "refreshtoken": "REFRESH",
                "accesstoken_duration_day": 7,
                "refreshtoken_duration_day": 30,
            })
        return True

    client._publish = fake_publish
    assert client.authenticate("1234", timeout=2) is True
    assert client._access_token == "ACCESS"


def test_handle_token_response_persists_and_is_retrievable(tmp_path):
    """The saved token must be written with the right key so the CLI can find it.

    Regression: save_token() was called without the required device_id, which
    crashed the MQTT loop thread; lookups also fall back to the host:port key.
    """
    storage = TokenStorage(tmp_path / "tokens.json")
    client = HisenseTV(
        host="10.0.0.50",
        port=36669,
        mac_address=KNOWN_UUID,
        use_ssl=False,
        storage=storage,
        enable_persistence=True,
    )
    client._handle_token_response({
        "accesstoken": "ACCESS",
        "refreshtoken": "REFRESH",
        "accesstoken_duration_day": 7,
        "refreshtoken_duration_day": 30,
    })

    # Retrievable both by the host:port the CLI uses and verifiably persisted.
    saved = storage.get_token(host="10.0.0.50", port=36669)
    assert saved is not None
    assert saved["access_token"] == "ACCESS"
    assert saved["refresh_token"] == "REFRESH"
    assert client._token_event.is_set()


def test_get_token_requires_keyword_host_port(tmp_path):
    """Looking up by host/port must use keywords.

    Regression: callers used get_token(host, port) positionally, binding
    host -> device_id and port -> host, so the host:port key never matched
    and 'monitor'/reconnect reported 'No stored credentials'.
    """
    storage = TokenStorage(tmp_path / "tokens.json")
    storage.save_token(
        device_id="10.0.0.50:36669",
        host="10.0.0.50",
        port=36669,
        access_token="ACCESS",
        refresh_token="REFRESH",
    )

    # Correct (keyword) lookup finds it.
    assert storage.get_token(host="10.0.0.50", port=36669) is not None
    # The old positional bug (host lands in device_id slot) finds nothing.
    assert storage.get_token("10.0.0.50", 36669) is None
