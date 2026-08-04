# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.2.4] - 2026-08-04

### Fixed

- **`get_state()` could not report that the TV had gone away.** It waited for
  the payload to *change* rather than for the TV to *respond*, and returned the
  last known state on timeout - so a TV that had been switched off kept
  reporting whatever it was last doing. Home Assistant showed such a TV as on
  for around two minutes, until the MQTT keepalive expired and a reconnect
  finally failed. It now returns `None` when the TV does not answer, which is
  distinct from an empty state.
- **Every poll against a healthy but idle TV cost the full timeout.** An idle
  TV reports an identical payload each time, which the change-detection above
  could not tell apart from silence. Polls drop from ~3s to ~0.1s.
- **The TV's own standby announcement was ignored.** Pre-dynamic firmware
  publishes to `/remoteapp/mobile/broadcast/platform_service/actions/tvsleep`
  the instant it powers off - including from the physical remote - and sends
  nothing else to say so. That topic was never subscribed to; it now is, and is
  surfaced as a `fake_sleep_0` state through the usual `on_state_change`
  callback.
- The cached state is dropped on disconnect, so a reconnect cannot resurrect a
  stale "on".
- `clear_saved_token()` (and `tv auth clear`) passed host/port positionally into
  `delete_token`, whose first parameter is `device_id` - so they matched nothing
  and silently deleted nothing while reporting success. `delete_token()` now
  returns whether it removed a record, and the CLI reports accordingly.
- The MQTT keepalive drops from 60s to 20s (`DEFAULT_KEEPALIVE`), so a TV that
  vanishes without closing its connection is noticed in ~30s rather than ~90s.
- An unexpected disconnect now names the actual reason. Code 16 is a keepalive
  timeout - a TV switched off without closing the socket - and was being
  reported as a probable client-id collision.
- Removed a duplicate subscription to the state broadcast topic.

## [2.2.3] - 2026-08-04

### Added

- `DiscoveredTV` now exposes `mac_ethernet` and `mac_wifi` alongside the
  preferred `mac`. The descriptor does not say which interface the TV is
  actually connected on, and Wake-on-LAN only reaches that one, so callers need
  both to offer a choice rather than guessing.

## [2.2.2] - 2026-08-04

### Changed

- `DEFAULT_CLIENT_ID` is now `pyvidaa`, not `HomeAssistant`, for both the MQTT
  client id and the topics. `HomeAssistant` is what the widely-used
  Mosquitto-bridge setups send, and a TV drops the older session whenever a
  client id is reused, so sharing it meant fighting them for the connection.
  **Existing pairings are unaffected**: the authorized id is restored from
  storage, so only newly-paired TVs use the new value.

### Fixed

- `get_token_status()` now reports `tokenless: True` for a static-auth pairing.
  Its zero expiry otherwise read as "overdue for renewal", so callers retried a
  token refresh on every poll against firmware that issues no tokens at all.

## [2.2.1] - 2026-08-04

### Fixed

- **Static auth reused one MQTT client id for every client, causing an endless
  reconnect loop.** MQTT requires a broker to drop the older session whenever a
  client id is reused, so two live pyvidaa clients - a retried config flow, or
  a user's existing Mosquitto bridge on the same id - kicked each other roughly
  once a second, and pairing never survived long enough for the TV to show its
  PIN. The MQTT client id is now unique per connection, while the *topic*
  client id (the identity the TV actually authorizes after a PIN, and what gets
  persisted) stays stable. 2.2.0 collapsed the two into one value.
- **The TV's "PIN is on screen" notification was discarded.** It arrives as an
  empty payload on `.../ui_service/data/authentication`, so it fell through to
  JSON parsing and was dropped - leaving no way to distinguish a displayed PIN
  from a TV that ignored the request. It now sets `needs_authentication()`,
  fires the `on_auth_required` callback, and can be awaited via
  `start_pairing(wait_for_pin=<seconds>)`, which still defaults to the previous
  non-blocking behaviour.
- **Discovery rejected the very TVs this release added support for.** Older
  firmware omits `vidaa_support` from its UPnP descriptor entirely, so
  `probe_ip()` skipped it and no MAC, brand or protocol version was resolved. A
  descriptor carrying `transport_protocol` now counts as proof it is a VIDAA
  TV; unrelated MediaRenderers answering the same SSDP search (Sonos, DLNA
  speakers) publish no such field and are still ignored.
- An unexpected disconnect is now logged with its return code. Previously a TV
  that accepted a connection and immediately closed it produced nothing but a
  stream of successful "Connected to TV" lines with no hint as to why.

## [2.2.0] - 2026-08-04

### Added

- **Support for pre-dynamic firmware** (`transport_protocol` below 3000, e.g.
  1140). These TVs predate the dynamic credential algorithm and expect the
  fixed `hisenseservice`/`multimqttservice` login with a stable client_id -
  the configuration a Mosquitto bridge uses successfully on that firmware.
  They were previously rejected with MQTT CONNACK 5 on every attempt.
  - New `AuthMethod.STATIC`, selected automatically for those protocol versions.
  - Such TVs issue no token: they answer the PIN with `result: 1` and authorize
    the client_id itself. `authenticate()` now accepts that as success (for
    STATIC/LEGACY only) and persists the pairing so reconnects reuse the same
    client_id. `start_pairing()` triggers their PIN dialog with `gettvstate`,
    since they have no `vidaa_app_connect` action.
- **Auth mode selector**: `auth_mode_kwargs()`, the `tv --auth-mode
  {auto,dynamic,static}` CLI flag (persisted by `tv config add`), and an
  `auth_mode` key for bridge TV configs. `auto` is the default and behaves as
  before plus the new fallback.
- `allow_static_auth` on `VidaaTV`/`AsyncVidaaTV`, to force the dynamic
  algorithm on a TV that misreports its protocol version.

### Fixed

- **Auth-method fallback never ran when protocol detection succeeded.** It was
  gated on the protocol being *unknown*, so a TV that reported its version and
  then rejected the resulting credentials failed outright, without trying any
  other method. Fallback now runs whenever the TV actually rejects the
  credentials (CONNACK 4/5).
- Fallback is now skipped for failures that are not authorization rejections,
  so an unreachable TV still fails after one timeout instead of walking the
  whole method chain.
- Fallback is also skipped for credentials loaded from storage: a rejection
  there means the pairing was dropped, and switching methods would discard the
  client_id the TV authorized.
- A rejected connection no longer leaves paho auto-reconnecting with the same
  (already stale) credentials, which logged the same CONNACK 5 every few
  seconds.
- Credential selection and TLS setup are no longer duplicated between the
  constructor and the fallback path, which had drifted: the fallback copy
  ignored `verify_ssl` and never used the bundled RemoteCA.

### Changed

- `get_auth_method()` returns `AuthMethod.STATIC` (was `LEGACY`) for protocol
  versions below 3000. `LEGACY` remains, immediately behind it in the fallback
  order.
- `get_auth_method_order()` now takes an optional protocol version and returns
  *all* methods, ordered by likelihood, so a misreported version can no longer
  make a method unreachable.
- `generate_credentials_static()` returns the client_id it is given (default
  `HomeAssistant`) rather than a MAC-derived `{uuid}$vidaa_common`, which no
  observed TV accepts. With `use_dynamic_auth=False`, the MQTT client_id is now
  that stable id instead of `hisense_{client_id}_{timestamp}` - a per-run id
  can never stay paired with firmware that authorizes by client_id.
- `generate_credentials()` raises `ValueError` for a missing MAC on the dynamic
  methods instead of failing later with a `TypeError`.
- Renamed the Home Assistant integration domain `hisense_tv` → `vidaa_tv` and the
  display name to "Vidaa TV" (existing installs must be removed and re-added).
- The Home Assistant integration now lives in its own repository, `ha_vidaatv`;
  this repository is now the `pyvidaa` library and the `hisense2mqtt` bridge.

## [2.1.0] - 2026-05-25

### Changed

- Standardized class names on the Vidaa naming: `HisenseTV` → `VidaaTV`,
  `AsyncHisenseTV` → `AsyncVidaaTV` (and the internal Home Assistant entity/
  coordinator and bridge classes likewise renamed from `HisenseTV*` /
  `HisenseMQTT*` to `VidaaTV*` / `VidaaMQTT*`).
- `HisenseTV` and `AsyncHisenseTV` remain available as **deprecated aliases**
  so code written against 2.0.x keeps working; prefer the new names.

## [2.0.1] - 2026-05-25

### Fixed

- CLI: when the client certificate is missing and the TV requires mutual TLS,
  print a single clean error instead of dumping paho's background-thread
  SSLError traceback. Other thread exceptions are unaffected.

## [2.0.0] - 2026-05-25

### Changed

- **Renamed the library `myhisense-tv` → `pyvidaa`** to reflect that it supports
  any Vidaa-OS TV (Hisense, Toshiba, etc.), not just Hisense.
  - **BREAKING (library users):** the import package is now `pyvidaa` — update
    `from hisense_tv import ...` to `from pyvidaa import ...`. The PyPI package
    is now `pyvidaa` (`pip install pyvidaa`).
  - The Home Assistant integration **domain is unchanged (`hisense_tv`)**, so
    existing config entries, entities, and automations keep working. The
    integration now requires `pyvidaa==2.0.0`.
  - CLI: the `tv` command is unchanged; the secondary `myhisense-tv` command is
    now `pyvidaa`.
  - CLI config files at `~/.config/hisense_tv/` and `/etc/hisense_tv/` are still
    read as legacy fallbacks; the new primary locations are `~/.config/pyvidaa/`
    and `/etc/pyvidaa/`.
- Marked the package **Production/Stable**.

### Added

- VIDAA brand images (icon/logo) for the Home Assistant integration via the
  local `brand/` folder (HA 2026.3+).

## [1.7.0] - 2026-05-25

### Added

- **Multi-TV support in the hisense2mqtt bridge** — the bridge now runs one
  worker per TV defined in the `tvs:` config (each its own Home Assistant
  device), in addition to the legacy singular `tv:` section. Bridge versioned
  separately at 1.1.0.
- **Automatic access-token renewal** in both the bridge and the Home Assistant
  integration: proactive refresh before expiry while connected, and a client
  rebuild on reconnect so an expired access token is refreshed from the
  refresh token instead of being replayed.
- Core-library unit test suite (credentials, protocol detection, message
  handling, pairing/token persistence) where there was previously none.

### Fixed

- Pairing on the `--ip` path no longer drops the TV MAC (which degraded
  dynamic auth to empty static credentials and was rejected as MQTT code 5).
- `tv config add` now persists the discovered MAC/name/protocol and reports
  the default TV; commands echo their target IP.
- MQTT code 5 errors now hint at clock/timezone/DST skew (time-based
  credentials are rejected when the TV's clock is wrong).
- Non-dict MQTT payloads no longer crash the client's message loop.
- Pairing waits for the access token to be received and persisted instead of
  returning on PIN-accept and racing disconnect.
- `save_token()` is called with the required device id; saved tokens are
  looked up by keyword host/port (previously positional, so they were never
  found and reconnects silently re-authenticated).
- `detect_protocol()` retries on transient network errors.
- Home Assistant `config_flow` compatibility (friendlyName lookup, dropped
  deprecated `OptionsFlow.__init__`).

## [1.3.0] - 2024-12-30

### Added

- **Network Discovery Module** (`hisense_tv.discovery`)
  - SSDP M-SEARCH active discovery
  - SSDP NOTIFY passive listener
  - UDP broadcast discovery on port 36671
  - Direct IP probe functionality
  - `DiscoveredTV` dataclass for structured results

- **Protocol Auto-Detection**
  - Automatic detection of transport protocol version from TV's UPnP descriptor
  - Three authentication methods: LEGACY (< 3000), MIDDLE (3000-3285), MODERN (>= 3290)
  - Automatic fallback through authentication methods if detection fails

- **Token Persistence**
  - Save and restore authentication tokens
  - Automatic token refresh when access token expires
  - Support for storing multiple device credentials

### Changed

- Replaced `print()` statements with proper `logging` in library code
- Improved type hints for Python 3.8 compatibility
- Updated configuration to use empty defaults (user must configure)

### Fixed

- Protocol detection now correctly parses `transport_protocol` from XML text content
- Type hints now compatible with Python 3.8+

## [1.2.0] - 2024-12-28

### Added

- Dynamic credential generation based on protocol analysis
- XOR-based username obfuscation for modern protocol
- MD5 password hashing with protocol-specific suffixes
- Wake-on-LAN support

### Changed

- Improved MQTT connection handling
- Better error messages for authentication failures

## [1.1.0] - 2024-12-27

### Added

- Home Assistant MQTT auto-discovery
- Source selection (HDMI, TV, AV inputs)
- App launching functionality
- Volume control with get/set

### Changed

- Improved SSL/TLS handling for self-signed certificates

## [1.0.0] - 2024-12-26

### Added

- Initial release
- MQTT client for Hisense/Vidaa TV control
- Remote key sending (50+ keys)
- Power control
- Basic authentication flow
- CLI interface
- Docker support
