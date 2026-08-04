"""Unit tests for the core pyvidaa library (no Home Assistant, no network).

These cover the logic that previously had zero test coverage and that directly
caused the live pairing failures we debugged:
  * credential generation (time-based username/password, MAC-based client_id)
  * protocol detection / auth-method selection and its retry behaviour
"""

from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from pyvidaa.client import VidaaTV
from pyvidaa.config.constants import (
    DEFAULT_CLIENT_ID,
    DEFAULT_MQTT_PASSWORD,
    DEFAULT_MQTT_USERNAME,
)
from pyvidaa.config.storage import TokenStorage
from pyvidaa.credentials import generate_credentials, generate_credentials_static
from pyvidaa.protocol import (
    AuthMethod,
    auth_mode_kwargs,
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


def test_static_credentials_match_the_working_bridge_config():
    """These are the values a Mosquitto bridge sends to pre-dynamic firmware.

    A TV on that firmware rejects anything else with CONNACK 5, so they must
    stay byte-exact.
    """
    creds = generate_credentials_static()
    assert creds.username == "hisenseservice"
    assert creds.password == "multimqttservice"
    assert creds.client_id == DEFAULT_CLIENT_ID


def test_static_credentials_are_stable_across_calls():
    """The TV authorizes the client_id itself, so it cannot vary per run."""
    assert generate_credentials_static().client_id == generate_credentials_static().client_id


def test_static_auth_needs_no_mac():
    """Nothing in the static login derives from the MAC."""
    creds = generate_credentials(mac_address=None, auth_method=AuthMethod.STATIC)
    assert creds == generate_credentials_static()


def test_dynamic_auth_without_a_mac_is_an_error():
    """It cannot build a client_id, and silently guessing produces CONNACK 5."""
    with pytest.raises(ValueError):
        generate_credentials(mac_address=None, auth_method=AuthMethod.MODERN)


def test_flat_mac_is_normalised_to_colon_form():
    flat = generate_credentials("56b8884ef719", timestamp=KNOWN_TIME)
    coloned = generate_credentials(KNOWN_UUID, timestamp=KNOWN_TIME)
    assert flat.client_id == coloned.client_id


# --- auth-method selection -------------------------------------------------

@pytest.mark.parametrize(
    "version,expected",
    [
        (None, AuthMethod.MODERN),  # unknown -> modern, then fallback
        (1140, AuthMethod.STATIC),  # reported by real pre-dynamic firmware
        (2999, AuthMethod.STATIC),
        (3000, AuthMethod.MIDDLE),
        (3285, AuthMethod.MIDDLE),
        (3290, AuthMethod.MODERN),
        (4000, AuthMethod.MODERN),
    ],
)
def test_get_auth_method_thresholds(version, expected):
    assert get_auth_method(version) == expected


def test_auth_method_fallback_order():
    """Unknown protocol: modern first, but every method stays reachable."""
    assert get_auth_method_order() == [
        AuthMethod.MODERN,
        AuthMethod.MIDDLE,
        AuthMethod.LEGACY,
        AuthMethod.STATIC,
    ]


@pytest.mark.parametrize("version", [None, 1140, 2999, 3000, 3290])
def test_auth_method_order_always_covers_every_method(version):
    """A misreported version must never make a method unreachable."""
    assert set(get_auth_method_order(version)) == set(AuthMethod)


def test_legacy_protocol_tries_static_first():
    """Pre-dynamic firmware (like the 1140 TV) leads with static credentials."""
    assert get_auth_method_order(1140)[0] == AuthMethod.STATIC


# --- auth mode (user-facing selector) --------------------------------------

def test_auth_mode_static_skips_detection():
    """Forcing static must not probe the TV or leave room for a dynamic guess."""
    kwargs = auth_mode_kwargs("static")
    assert kwargs["auth_method"] == AuthMethod.STATIC
    assert kwargs["use_dynamic_auth"] is False
    assert kwargs["auto_detect_protocol"] is False


def test_auth_mode_dynamic_never_selects_static():
    kwargs = auth_mode_kwargs("dynamic")
    assert kwargs["use_dynamic_auth"] is True
    assert kwargs["allow_static_auth"] is False


def test_auth_mode_auto_is_the_default():
    assert auth_mode_kwargs(None) == auth_mode_kwargs("auto")
    assert auth_mode_kwargs("auto")["use_dynamic_auth"] is True


def test_unknown_auth_mode_is_rejected():
    with pytest.raises(ValueError):
        auth_mode_kwargs("magic")


def test_dynamic_mode_downgrades_a_static_detection_to_legacy(monkeypatch):
    """auth_mode=dynamic on a 1140 TV must still use a dynamic method."""
    monkeypatch.setattr("pyvidaa.client.detect_protocol", lambda *a, **k: 1140)

    client = VidaaTV(
        host="10.0.0.1",
        mac_address=KNOWN_UUID,
        use_ssl=False,
        enable_persistence=False,
        **auth_mode_kwargs("dynamic"),
    )

    assert client._auth_method == AuthMethod.LEGACY
    assert client._username.startswith("his$")


def test_static_mode_builds_the_fixed_login_without_probing(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("static mode must not probe the TV")

    monkeypatch.setattr("pyvidaa.client.detect_protocol", _boom)

    client = VidaaTV(
        host="10.0.0.1",
        use_ssl=False,
        enable_persistence=False,
        **auth_mode_kwargs("static"),
    )

    assert client._auth_method == AuthMethod.STATIC
    assert client._username == DEFAULT_MQTT_USERNAME
    assert client._password == DEFAULT_MQTT_PASSWORD
    assert client.client_id == DEFAULT_CLIENT_ID
    assert client._mqtt_client_id.startswith(f"{DEFAULT_CLIENT_ID}_")


def test_static_mqtt_client_id_is_unique_but_topic_id_is_stable():
    """Two live clients must not share an MQTT client id.

    Regression: they did, and MQTT 3.1.1 s3.1.4 makes the broker drop the older
    session whenever a client id is reused - so two pyvidaa clients (a retried
    config flow, or a user's existing Mosquitto bridge) kicked each other in a
    ~1s loop and pairing never survived long enough to show a PIN. The topic id
    is the identity the TV authorizes, so that one has to stay stable.
    """
    a = VidaaTV(host="10.0.0.1", use_ssl=False, enable_persistence=False,
                **auth_mode_kwargs("static"))
    b = VidaaTV(host="10.0.0.1", use_ssl=False, enable_persistence=False,
                **auth_mode_kwargs("static"))

    assert a._mqtt_client_id != b._mqtt_client_id
    assert a.client_id == b.client_id == DEFAULT_CLIENT_ID


def test_static_pairing_persists_the_topic_id_not_the_mqtt_id(tmp_path):
    """The saved client_id must be the one the TV authorized."""
    storage = TokenStorage(tmp_path / "tokens.json")
    client = VidaaTV(host="10.0.0.50", use_ssl=False, storage=storage,
                     enable_persistence=True, **auth_mode_kwargs("static"))
    client._connected = True

    def fake_publish(topic, payload=""):
        client._authenticated = True
        client._auth_event.set()
        return True

    client._publish = fake_publish
    assert client.authenticate("1234", timeout=0.2) is True

    saved = storage.get_token(host="10.0.0.50", port=36669)
    assert saved["client_id"] == DEFAULT_CLIENT_ID
    assert saved["client_id"] != client._mqtt_client_id


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
            patch("pyvidaa.protocol.time.sleep"):
        assert detect_protocol("10.0.0.1", retries=2, retry_delay=0) == 3290
    assert calls["n"] == 2  # failed once, succeeded on retry


def test_detect_protocol_returns_none_after_exhausting_retries():
    err = urllib.error.URLError(OSError(113, "No route to host"))
    with patch("urllib.request.urlopen", side_effect=err), \
            patch("pyvidaa.protocol.time.sleep"):
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
            patch("pyvidaa.protocol.time.sleep"):
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
            patch("pyvidaa.protocol.time.sleep"):
        assert detect_protocol("10.0.0.1", port=38400, retries=0) is None
    assert seen_ports == ["38400"]


# --- message handling (non-dict payloads must not crash) -------------------

def _make_client(auth_method=AuthMethod.MODERN, **kwargs):
    return VidaaTV(
        host="10.0.0.1",
        mac_address=KNOWN_UUID,
        use_ssl=False,
        enable_persistence=False,
        auth_method=auth_method,
        **kwargs,
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
    token persisted. Token-issuing firmware only; see the static case below.
    """
    client = _make_client(auth_method=AuthMethod.MODERN)
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


def test_static_authenticate_succeeds_without_a_token(tmp_path):
    """Pre-dynamic firmware answers the PIN with result=1 and issues no token.

    Regression for the 1140-protocol TV: requiring a token made pairing report
    failure on firmware that authorizes the client_id instead.
    """
    storage = TokenStorage(tmp_path / "tokens.json")
    client = VidaaTV(
        host="10.0.0.50",
        use_ssl=False,
        auth_method=AuthMethod.STATIC,
        storage=storage,
        enable_persistence=True,
    )
    client._connected = True

    def fake_publish(topic, payload=""):
        client._authenticated = True
        client._auth_event.set()  # PIN accepted; no tokenissuance follows
        return True

    client._publish = fake_publish
    assert client.authenticate("1234", timeout=0.2) is True
    assert client._access_token is None

    # The pairing is persisted so the next connect reuses the same client_id.
    saved = storage.get_token(host="10.0.0.50", port=36669)
    assert saved is not None
    assert saved["auth_method"] == "static"
    assert saved["client_id"] == DEFAULT_CLIENT_ID
    assert saved["access_token"] is None


def test_saved_static_pairing_is_reused_with_the_fixed_login(tmp_path):
    """A tokenless pairing must reload without a None password."""
    storage = TokenStorage(tmp_path / "tokens.json")
    storage.save_token(
        device_id="10.0.0.50:36669",
        host="10.0.0.50",
        port=36669,
        client_id=DEFAULT_CLIENT_ID,
        mqtt_username=DEFAULT_MQTT_USERNAME,
        auth_method="static",
    )

    client = VidaaTV(
        host="10.0.0.50",
        use_ssl=False,
        storage=storage,
        enable_persistence=True,
    )

    assert client._auth_method == AuthMethod.STATIC
    # The authorized identity is the topic client id, restored verbatim.
    assert client.client_id == DEFAULT_CLIENT_ID
    # The MQTT client id is per-connection and must NOT be the saved one.
    assert client._mqtt_client_id != client.client_id
    assert client._mqtt_client_id.startswith(f"{DEFAULT_CLIENT_ID}_")
    assert client._username == DEFAULT_MQTT_USERNAME
    assert client._password == DEFAULT_MQTT_PASSWORD
    assert client._authenticated is True


def test_static_pairing_never_expires(tmp_path):
    """It carries no token, so it must not be aged out like one."""
    storage = TokenStorage(tmp_path / "tokens.json")
    storage.save_token(
        device_id="10.0.0.50:36669",
        host="10.0.0.50",
        port=36669,
        client_id=DEFAULT_CLIENT_ID,
        mqtt_username=DEFAULT_MQTT_USERNAME,
        auth_method="static",
    )

    assert storage.get_token(host="10.0.0.50", port=36669) is not None
    status = storage.get_token_status(host="10.0.0.50", port=36669)
    assert status["needs_reauth"] is False
    assert status["needs_refresh"] is False


def test_handle_token_response_persists_and_is_retrievable(tmp_path):
    """The saved token must be written with the right key so the CLI can find it.

    Regression: save_token() was called without the required device_id, which
    crashed the MQTT loop thread; lookups also fall back to the host:port key.
    """
    storage = TokenStorage(tmp_path / "tokens.json")
    client = VidaaTV(
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


# --- the TV telling us the PIN is on screen --------------------------------

def test_empty_authentication_push_signals_the_pin_is_showing():
    """The TV announces the PIN dialog with an EMPTY payload on that topic.

    Regression: it fell through to JSON parsing and was discarded, so there was
    no way to tell a displayed PIN from a TV that ignored the request - the
    config flow asked for a code the user could not see.
    """
    client = _make_client(auth_method=AuthMethod.STATIC)
    seen = []
    client.on_auth_required = lambda: seen.append(True)

    msg = MagicMock()
    msg.topic = f"/remoteapp/mobile/{DEFAULT_CLIENT_ID}/ui_service/data/authentication"
    msg.payload = b""

    client._on_message(None, None, msg)

    assert client._pin_event.is_set()
    assert client.needs_authentication() is True
    assert seen == [True]


def test_start_pairing_can_wait_for_the_tv_to_confirm():
    client = _make_client(auth_method=AuthMethod.STATIC)
    client._connected = True
    client._client = MagicMock()

    def fake_publish(topic, payload=""):
        # Simulate the TV pushing the "PIN is up" notification.
        msg = MagicMock()
        msg.topic = f"/remoteapp/mobile/{DEFAULT_CLIENT_ID}/ui_service/data/authentication"
        msg.payload = b""
        client._on_message(None, None, msg)
        return True

    client._publish = fake_publish
    assert client.start_pairing(wait_for_pin=2) is True


def test_start_pairing_reports_failure_when_the_tv_stays_silent():
    """A TV that never shows the dialog must not look like a success."""
    client = _make_client(auth_method=AuthMethod.STATIC)
    client._connected = True
    client._client = MagicMock()
    client._publish = lambda topic, payload="": True

    assert client.start_pairing(wait_for_pin=0.2) is False
    # Default stays non-blocking for callers that don't opt in.
    assert client.start_pairing() is True


def test_legacy_pairing_is_triggered_with_gettvstate():
    """Pre-dynamic firmware has no vidaa_app_connect action."""
    client = _make_client(auth_method=AuthMethod.STATIC)
    client._connected = True
    client._client = MagicMock()
    published = []
    client._publish = lambda topic, payload="": published.append(topic) or True

    client.start_pairing()
    assert published == [
        f"/remoteapp/tv/ui_service/{DEFAULT_CLIENT_ID}/actions/gettvstate"
    ]


# --- auth-method fallback --------------------------------------------------

class _FakePaho:
    """Stand-in for paho's Client that reports a scripted CONNACK code.

    `results` maps the MQTT username it is given to the CONNACK rc to report,
    so a test can say "static works, everything else is rejected".
    """

    def __init__(self, client, results):
        self._owner = client
        self._results = results
        self._username = None

    # -- configuration paho would do --
    def username_pw_set(self, username, password=None):
        self._username = username

    def tls_set(self, **kwargs):
        pass

    def tls_set_context(self, context=None):
        pass

    def tls_insecure_set(self, value):
        pass

    def subscribe(self, topic):
        pass

    # -- connection lifecycle --
    def connect(self, host, port, keepalive=60):
        pass

    def loop_start(self):
        rc = self._results.get(self._username, 5)
        self._owner._on_connect(self, None, {}, rc)

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


def _patch_paho(client, results):
    """Route this client's paho usage through _FakePaho, including rebuilds."""
    def build(self=client):
        self._client = _FakePaho(self, results)
        self._client.username_pw_set(self._username, self._password)

    client._build_mqtt_client = build
    build()


def test_connect_falls_back_after_a_detected_protocol_is_rejected():
    """The reported bug: detection succeeded, so no fallback was ever tried.

    A 1140 TV leads with static; if that were rejected the client must still
    walk the remaining methods instead of giving up on the first CONNACK 5.
    """
    client = _make_client(auth_method=AuthMethod.LEGACY)
    client.use_dynamic_auth = True
    client._protocol_version = 1140  # detection succeeded - used to block fallback

    # Only the static login is accepted by this TV.
    _patch_paho(client, {DEFAULT_MQTT_USERNAME: 0})

    assert client.connect(timeout=0.3) is True
    assert client._auth_method == AuthMethod.STATIC
    assert client._username == DEFAULT_MQTT_USERNAME
    assert client._password == DEFAULT_MQTT_PASSWORD
    assert client.client_id == DEFAULT_CLIENT_ID


def test_connect_does_not_fall_back_when_the_tv_is_unreachable():
    """An offline TV must fail fast, not walk the whole method chain.

    Otherwise every poll against a sleeping TV costs 4x the connect timeout.
    """
    client = _make_client(auth_method=AuthMethod.MODERN)
    client.use_dynamic_auth = True

    attempts = {"n": 0}

    def build(self=client):
        attempts["n"] += 1
        fake = _FakePaho(self, {})
        fake.connect = lambda *a, **k: (_ for _ in ()).throw(OSError("unreachable"))
        self._client = fake

    client._build_mqtt_client = build
    build()

    assert client.connect(timeout=0.3) is False
    assert attempts["n"] == 1  # no rebuild == no fallback attempt


def test_connect_does_not_fall_back_for_saved_credentials():
    """A rejected saved pairing needs re-pairing, not a different algorithm.

    Switching methods would also discard the client_id the TV authorized.
    """
    client = _make_client(auth_method=AuthMethod.MODERN)
    client.use_dynamic_auth = True
    client._using_saved_creds = True

    rebuilds = {"n": 0}
    original_username = client._username

    def build(self=client):
        rebuilds["n"] += 1
        self._client = _FakePaho(self, {})  # everything rejected with rc 5
        self._client.username_pw_set(self._username, self._password)

    client._build_mqtt_client = build
    build()

    assert client.connect(timeout=0.3) is False
    assert rebuilds["n"] == 1
    assert client._username == original_username


def test_bundled_remote_ca_is_loadable_public_cert():
    """The shipped RemoteCA must exist and be a usable CA cert (no private key)."""
    import ssl

    from pyvidaa.certs import bundled_ca_path

    ca = bundled_ca_path()
    assert ca is not None, "remote_ca.pem should be bundled with the package"

    text = open(ca, encoding="utf-8").read()
    assert "BEGIN CERTIFICATE" in text
    assert "PRIVATE KEY" not in text  # must never ship a private key

    # A real SSL context can load it as a trust anchor.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(ca)


def test_server_verify_args_opt_in(monkeypatch):
    """verify_ssl gates whether the RemoteCA is used for server verification."""
    import ssl

    from pyvidaa.certs import bundled_ca_path

    # Avoid any real network/protocol detection during construction.
    monkeypatch.setattr("pyvidaa.client.detect_protocol", lambda *a, **k: None)

    off = VidaaTV("10.0.0.50", use_ssl=False, enable_persistence=False, verify_ssl=False)
    assert off._server_verify_args() == (None, ssl.CERT_NONE)

    on = VidaaTV("10.0.0.50", use_ssl=False, enable_persistence=False, verify_ssl=True)
    assert on._server_verify_args() == (bundled_ca_path(), ssl.CERT_REQUIRED)


def test_cli_quiet_excepthook_handles_cert_required(monkeypatch, capsys):
    """The CLI thread excepthook turns a cert-required SSLError into a clean
    message, and defers unrelated exceptions to the default hook."""
    import ssl as _ssl

    from pyvidaa import cli

    monkeypatch.setattr(cli, "resolve_client_certs", lambda *a, **k: None)

    class CertArgs:
        exc_value = _ssl.SSLError(
            "[SSL: TLSV13_ALERT_CERTIFICATE_REQUIRED] tlsv13 alert certificate required"
        )
        exc_type = _ssl.SSLError
        exc_traceback = None
        thread = None

    cli._quiet_mqtt_thread_excepthook(CertArgs())
    err = capsys.readouterr().err
    assert "requires a client certificate" in err
    assert "Traceback" not in err

    # Unrelated errors fall through to the default hook.
    seen = []
    monkeypatch.setattr(cli, "_DEFAULT_THREAD_EXCEPTHOOK", lambda a: seen.append(a))

    class OtherArgs:
        exc_value = ValueError("boom")
        exc_type = ValueError
        exc_traceback = None
        thread = None

    cli._quiet_mqtt_thread_excepthook(OtherArgs())
    assert len(seen) == 1


# --- discovery must not reject older firmware ------------------------------

# The real descriptor from a HE58A6100FUWTS on protocol 1140: no vidaa_support
# key at all, but transport_protocol is present.
LEGACY_DESCRIPTOR = (
    '<?xml version="1.0"?>'
    '<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
    "<friendlyName>Studio TV</friendlyName><modelName>Renderer</modelName>"
    "<modelDescription>#CAP#\nmac=a062fb6677ca\nmacWifi=f03575295ae0\n"
    "macEthernet=a062fb6677ca\nip=192.168.67.28\nregion=4\ncountry=CZE\n"
    "model_name=HE58A6100FUWTS_0100\ntv_version=V0000.01.00F.P0220\n"
    "language=eng\ntransport_protocol=1140\nemanual=0\nnetwork_wakeup=1\n"
    "voice=1\ncap=0\nmqttport=36669</modelDescription>"
    "</device></root>"
)

# A non-VIDAA MediaRenderer answering the same SSDP search must still be
# rejected - it has no transport_protocol.
SONOS_DESCRIPTOR = (
    '<?xml version="1.0"?>'
    '<root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
    "<friendlyName>Sonos Era 300</friendlyName>"
    "<modelDescription>Sonos Era 300</modelDescription>"
    "</device></root>"
)


def test_probe_accepts_older_firmware_without_vidaa_support():
    """Regression: these TVs omit vidaa_support, so discovery skipped them."""
    from pyvidaa.discovery import probe_ip

    with patch("urllib.request.urlopen",
               return_value=_mock_urlopen_returning(LEGACY_DESCRIPTOR)):
        device = probe_ip("192.168.67.28", timeout=1)

    assert device is not None
    assert device.protocol_version == "1140"
    assert device.mac == "a0:62:fb:66:77:ca"


def test_probe_still_rejects_non_vidaa_media_renderers():
    from pyvidaa.discovery import probe_ip

    with patch("urllib.request.urlopen",
               return_value=_mock_urlopen_returning(SONOS_DESCRIPTOR)):
        assert probe_ip("192.168.67.248", timeout=1) is None
