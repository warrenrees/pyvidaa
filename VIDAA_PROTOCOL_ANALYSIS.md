# Vidaa App MQTT Protocol Analysis

Analysis of the Hisense Vidaa remote app (APK) to understand TV communication protocol.

## Quick Reference

| Item | Value |
|------|-------|
| MQTT Port | `36669` |
| Protocol | MQTT v3.1.1 over TLS |
| P12 Password | `186e990688070325a1c4b0ce275d2388` |
| Client keystore | `res/3R.p12` (cert `CN=VidaaAppAndroidV01` + key) |
| Truststore | `res/dM.bks` (root `CN=RemoteCA`, alias `mykey`) |

## Connection Details

### MQTT Broker
- **Port:** 36669
- **Protocol:** MQTT v3.1.1 over TLS
- **TLS Version:** TLSv1.2+ (self-signed certificate, no hostname verification)

### Client Certificate (Required)

The TV requires mutual TLS (mTLS) with a client certificate.

**Certificate Details:**
```
Subject: C=CN, ST=shandong, O=hh, OU=multimedia, CN=VidaaAppAndroidV01
Issuer: C=CN, ST=shandong, L=qingdao, O=hh, OU=multimedia, CN=RemoteCA
Validity: Jun 27, 2024 - Jun 25, 2034
Serial: 12 (0xc)
```

**P12 Password:** `186e990688070325a1c4b0ce275d2388`

**Extract certificate from APK:**
```bash
# 1. Unzip APK and find the P12 file
unzip -l vidaa.apk | grep -i p12
# Usually at: assets/client_mobile_android.p12

# 2. Extract certificate and key
openssl pkcs12 -in client_mobile_android.p12 -out client_cert.pem -clcerts -nokeys \
    -passin pass:186e990688070325a1c4b0ce275d2388
openssl pkcs12 -in client_mobile_android.p12 -out client_key.pem -nocerts -nodes \
    -passin pass:186e990688070325a1c4b0ce275d2388
```

> **Note on keystore file names:** newer APK builds ship the keystores under
> obfuscated resource names, e.g. `res/3R.p12` (client keystore) and
> `res/dM.bks` (truststore), rather than `assets/client_mobile_android.p12`.
> The client cert/key and the P12 password are unchanged across these builds.

### Server Certificate Validation (Truststore)

The app validates the **TV's** server certificate against a bundled BouncyCastle
truststore (`res/dM.bks`, alias `mykey`). It contains a single self-signed root,
`RemoteCA`, which is also the issuer of the client certificate above — so both
sides of the mTLS handshake are anchored to the same private CA.

```
Subject = Issuer: C=CN, ST=shandong, L=qingdao, O=hh, OU=multimedia, CN=RemoteCA
Validity: Apr 19, 2018 - Apr 13, 2043   (CA:TRUE, self-signed)
Serial:   B925FCE67D5D45C3
```

The `RemoteCA` PEM is bundled at `certs/remote_ca.pem`. The client cert verifies
against it directly:
```bash
openssl verify -CAfile certs/remote_ca.pem certs/vidaa_client.pem   # => OK
```

The `.bks` is a BKS v1 store (SHA-1 HMAC, 1904 iterations). Its single entry is a
`BksTrustedCertEntry` (alias `mykey`, no private key), stored in cleartext, so the
truststore can be parsed without the JVM/BouncyCastle by locating the
`00 05 "X.509"` length-prefixed blocks. **Its integrity password is `multiscreen123`**
(`getClientKeyPass`), confirmed by opening it with `pyjks`:
```python
import jks
jks.bks.BksKeyStore.load("res/dM.bks", "multiscreen123")   # opens; entry alias "mykey"
```

### Credentials (from `libmqttcrypt.so`)

The native lib exposes these via JNI getters under
`com.universal.remote.multicomm.sdk.ConnectUtils`. The username/password are the
static MQTT login; the others are **TLS keystore passphrases**, not MQTT creds:

| JNI getter | Value | Role |
|------------|-------|------|
| `getUserName` | `hisenseservice` (b64 `aGlzZW5zZXNlcnZpY2U=`) | static MQTT username |
| `getUserPass` | `multimqttservice` (b64 `bXVsdGltcXR0c2VydmljZQ==`) | static MQTT password |
| `getClientKeyPass` | `multiscreen123` (b64 `bXVsdGlzY3JlZW4xMjM=`) | **BKS truststore password** (`dM.bks`) |
| `getNewClientKeyPass` | `ayd6afbj2huf3` (b64 `YXlkNmFmYmoyaHVmMw==`) | unused for shipped keystores |
| `getNewClientP12Password` | `186e990688070325a1c4b0ce275d2388` | **P12 store password** (`3R.p12`); opens store + key bag + MAC |
| `getNewClientKeyPassword` | `441a14046a67f604bb7cdb85b6783c0f` ⚠ reconstructed | intended client key-entry password; unused for shipped keystores |

#### Verified password → keystore matrix

Tested with `cryptography`/`openssl` (PKCS12) and `pyjks` (BKS):

| Getter / value | p12 store+MAC | p12 key bag | BKS truststore |
|----------------|:--:|:--:|:--:|
| `getClientKeyPass` = `multiscreen123` | ✗ | ✗ | ✓ |
| `getNewClientKeyPass` = `ayd6afbj2huf3` | ✗ | ✗ | ✗ |
| `getNewClientP12Password` = `186e99…` | ✓ | ✓ | ✗ |
| `getNewClientKeyPassword` = `441a…` | ✗ | ✗ | ✗ |

- The PKCS12 client keystore (`3R.p12`) uses a **single** password (`186e99…`) for the
  store, the shrouded key bag, and the MAC.
- The BKS truststore (`dM.bks`) uses `multiscreen123`.
- `ayd6afbj2huf3` and `441a…` unlock **nothing** in the shipped keystores — they appear
  vestigial (likely leftover from when store/key passwords were separate).

#### Note on the obfuscated getters and the `441a…` reconstruction

`getNewClientP12Password` and `getNewClientKeyPassword` are byte-identical functions
that each `NewStringUTF`-return a fixed 32-byte **obfuscated seed** from `.rodata`
(`GPB\x13OOHB…` and `DDG\x17GDHDB…` respectively); the seed→string transform runs in
the Baidu-packed Java.

- `186e99…` is **empirically confirmed** — it decrypts `3R.p12` (and was also seen via
  logcat). It is *not* a simple MD5/XOR of its seed.
- `441a14046a67f604bb7cdb85b6783c0f` is **reconstructed, not 100% confirmed.** Using the
  known (p12 seed → `186e99…`) pair, the transform is a bijection over a 16-symbol
  alphabet → the 16 hex digits. 15 of 16 symbols are observed directly; the key seed's
  one new symbol (`0x12`) maps to the one unassigned digit (`f`) by elimination.
  It reproduces `186e99…` exactly but cannot be ground-truth-verified because no shipped
  artifact is encrypted with it. **Definitive confirmation requires a runtime hook**
  (Frida/logcat) on `ConnectUtils.getNewClientKeyPassword()`.

**Dynamic Credentials (newer VIDAA TVs - REQUIRED):**

The native library generates dynamic credentials using the following algorithm:

```python
import hashlib
import time

# Constants from libmqttcrypt.so
PATTERN = "38D65DC30F45109A369A86FCE866A85B"  # From getInfo()/getSalt()
VALUE_SUFFIX = "h!i@s#$v%i^d&a*a"              # Obfuscated "hisvidaa"
XOR_CONST = 0x5698_1477_2b03_a968              # For username obfuscation

def md5(s):
    return hashlib.md5(s.encode()).hexdigest().upper()

def generate_credentials(uuid, brand="his", operation="vidaacommon", timestamp=None):
    """
    Generate MQTT credentials for Hisense VIDAA TV.

    Args:
        uuid: Device identifier (MAC format like "AA:BB:CC:DD:EE:FF")
        brand: "his" for Hisense
        operation: "vidaacommon" or "vidaavoice"
        timestamp: Unix timestamp in seconds (default: current time)

    Returns:
        (client_id, username, password)
    """
    if timestamp is None:
        timestamp = int(time.time())

    # Step 1: Calculate race = pattern$uuid, then MD5
    race = f"{PATTERN}${uuid}"
    race_md5 = md5(race)[:6]  # First 6 chars, uppercase

    # Step 2: Build client_id
    client_id = f"{uuid}${brand}${race_md5}_{operation}_001"

    # Step 3: Build username = brand$XOR(timestamp)
    xor_time = timestamp ^ XOR_CONST
    username = f"{brand}${xor_time}"

    # Step 4: Build value for password
    time_sum = sum(int(d) for d in str(timestamp))
    remainder = time_sum % 10
    value = f"{brand}{remainder}{VALUE_SUFFIX}"
    value_md5 = md5(value)[:6]

    # Step 5: Password = MD5(timestamp$value_md5)
    password = md5(f"{timestamp}${value_md5}")

    return client_id, username, password
```

**Example Generated Credentials:**
```
Input:
  UUID: 56:b8:88:4e:f7:19
  Timestamp: 1766974704

Output:
  Pattern: 38D65DC30F45109A369A86FCE866A85B
  Race: 38D65DC30F45109A369A86FCE866A85B$56:b8:88:4e:f7:19
  Race MD5[:6]: 256DBF
  Client ID: 56:b8:88:4e:f7:19$his$256DBF_vidaacommon_001
  Username: his$6239759786168176024
  Value: his1h!i@s#$v%i^d&a*a
  Value MD5[:6]: 56FAC6
  Password: C3BA44782E18ABF4892AC44D79A622D2
```

## Topic Structure

### Command Topics (Publish to TV)
Format: `/remoteapp/tv/{service}/{client_id}/actions/{action}`

| Service | Actions |
|---------|---------|
| `remote_service` | `sendkey` |
| `ui_service` | `sourcelist`, `gettvstate`, `changesource`, `launchapp`, `applist`, `authenticationcode`, `vidaa_app_connect`, `login_each_other_info` |
| `platform_service` | `getvolume`, `changevolume` |

### Response Topics (Subscribe)

**IMPORTANT:** Wildcard subscriptions (`#`, `+`) are **DENIED** by the TV. You must subscribe to specific topics.

Format: `/remoteapp/mobile/{client_id}/{service}/data/{data_type}`

| Topic | Data |
|-------|------|
| `{base}/ui_service/data/authentication` | PIN dialog shown (empty payload) |
| `{base}/ui_service/data/authenticationcodetoast` | PIN dialog toast |
| `{base}/ui_service/data/authenticationcodeclose` | PIN dialog closed |
| `{base}/ui_service/data/tokenissuance` | Auth tokens after PIN entry |
| `{base}/ui_service/data/state` | TV state info |
| `{base}/ui_service/data/sourcelist` | Available sources |
| `{base}/ui_service/data/applist` | Available apps |
| `{base}/platform_service/data/tokenissuance` | Alt token topic |

Where `{base}` = `/remoteapp/mobile/{client_id}`

**Broadcast topics** (also requires specific subscription):
- `/remoteapp/mobile/broadcast/ui_service/state` - TV state broadcasts

## Pairing Flow

### Overview
New devices must be paired with the TV before commands will work. Pairing involves displaying a PIN on the TV screen which the user enters in the app.

### Pairing Sequence

```
1. MQTT Connect     → Establish TLS connection with client cert
2. Subscribe        → Subscribe to response topics (NO wildcards!)
3. vidaa_app_connect → Trigger PIN dialog on TV
4. ← authentication → TV confirms PIN is displayed
5. User enters PIN  → Read 4-digit PIN from TV screen
6. authenticationcode → Send {"authNum": "XXXX"}
7. ← tokenissuance  → Receive access/refresh tokens
8. Commands work    → UUID is now authorized
```

### vidaa_app_connect Payload
```json
{
    "app_version": 2,
    "connect_result": 0,
    "device_type": "Mobile App"
}
```

### login_each_other_info Payload (Optional handshake)
```json
{
    "type": "login",
    "tvLogin": false,
    "tvDeviceId": "",
    "tvCountry": "",
    "mobileLogin": true,
    "mobileDeviceId": "aa:bb:cc:dd:ee:ff"
}
```

### authenticationcode Payload
```json
{"authNum": "1234"}
```

### tokenissuance Response
```json
{
    "accesstoken": "<token_string>",
    "accesstoken_duration_day": 30,
    "accesstoken_time": 1735432800,
    "refreshtoken": "<token_string>",
    "refreshtoken_duration_day": 365,
    "refreshtoken_time": 1735432800
}
```

### Pairing Notes
- PIN dialog timeout: ~60 seconds
- Enter PIN quickly before timeout
- TV may have maximum paired device limit
- Already-paired UUIDs skip PIN step (receive `authentication` message but no PIN shown)

## Remote Key Codes

### Navigation
- `KEY_UP`, `KEY_DOWN`, `KEY_LEFT`, `KEY_RIGHT`
- `KEY_OK` (Enter/Select)
- `KEY_RETURNS` (Back)
- `KEY_MENU`, `KEY_HOME`, `KEY_EXIT`

### Volume & Audio
- `KEY_VOLUMEUP`, `KEY_VOLUMEDOWN`
- `KEY_MUTE`, `KEY_MUTE_LONG_PRESS`
- `KEY_VOICEUP`, `KEY_VOICEDOWN`

### Playback
- `KEY_PLAY`, `KEY_PAUSE`, `KEY_STOP`
- `KEY_FORWARDS`, `KEY_BACK` (rewind)

### Numbers
- `KEY_0` through `KEY_9`
- `KEY_CHANNELDOT`

### Channel
- `KEY_CHANNELUP`, `KEY_CHANNELDOWN`

### Color Buttons
- `KEY_RED`, `KEY_GREEN`, `KEY_YELLOW`, `KEY_BLUE`

### Mouse/Pointer Mode
- `KEY_LEFTMOUSEKEYS`
- `KEY_UDDLEFTMOUSEKEYS`, `KEY_UDULEFTMOUSEKEYS`
- `KEY_ZOOMIN`, `KEY_ZOOMOUT`

### Special
- `KEY_POWER`
- `KEY_OK_LONG_PRESS`
- `KEY_SUBTITLE`

## Source Control

### Source IDs
| ID | Source |
|----|--------|
| 0 | TV |
| 1 | AV |
| 2 | Component |
| 3 | HDMI1 |
| 4 | HDMI2 |
| 5 | HDMI3 |
| 6 | HDMI4 |

### Change Source Payload
```json
{"sourceid": "3"}
```

## App Launch

### Topic
`/remoteapp/tv/ui_service/{client}/actions/launchapp`

### Payload Examples
```json
// Netflix
{"name":"Netflix","urlType":37,"storeType":0,"url":"netflix"}

// YouTube
{"name":"YouTube","urlType":37,"storeType":0,"url":"youtube"}

// Amazon Prime
{"name":"Amazon","urlType":37,"storeType":0,"url":"amazon"}

// Disney+
{"name":"Disney+","urlType":37,"storeType":0,"url":"disneyplus"}

// Plex
{"name":"Plex","urlType":37,"storeType":0,"url":"plex"}
```

## Native Library Functions

### `libmqttcrypt.so` - ConnectUtils Interface
```java
// Certificate passwords
getClientKeyPass()          // Client key password
getNewClientKeyPassword()   // New client key password
getNewClientP12Password()   // P12 password: 186e990688070325a1c4b0ce275d2388

// Credential generation
getConnectUser()            // Generate connection credentials
getConnectUserVidaaApp()    // VidaaApp-specific credentials
getUserName()               // Returns username
getUserPass()               // Returns password
getSalt()                   // Returns salt: 38D65DC30F45109A369A86FCE866A85B
getInfo()                   // Same as getSalt()
```

## Key Classes (Decompiled)

| Obfuscated | Original | Purpose |
|------------|----------|---------|
| `p4/a` | `BasicMqttManager.java` | Base MQTT management |
| `p4/b` | `MqttConnectCallBack.java` | Connection callbacks |
| `p4/c` | MQTT singleton manager | Main MQTT client |
| `p4/d` | Secondary MQTT manager | Voice/BLE connections |
| `x4/a` | `TopicToTvManager.java` | Topic path builder |
| `y3/b` | Main remote controller | Remote control logic |
| `ConnectUtils` | Native crypto interface | JNI to libmqttcrypt.so |
| `ConnectAccountBean` | Connection credentials | clientId, userName, passWord |
| `ConnectBean` | Connection payload | app_version, connect_result, device_type |
| `SdkConnectManager` | SDK connection manager | Handles auth flow, tokens |
| `SdkMqttPublishManager` | MQTT publish manager | Sends commands to TV |
| `LoginEachOtherInfoBean` | Login handshake | mType, mMobileDeviceId, etc. |

## Security Notes

1. **TLS with self-signed cert** - App uses `CERT_NONE` verification
2. **Credentials in native lib** - Base64 encoded but easily extractable
3. **P12 password hardcoded** - `186e990688070325a1c4b0ce275d2388`
4. **Dynamic client ID** - Generated with UUID + timestamp pattern
5. **No additional encryption** - Payloads sent as plain JSON
6. **Shared certificate** - All app instances use same VidaaAppAndroidV01 cert

## Example MQTT Commands

### Power Toggle
```
Topic: /remoteapp/tv/remote_service/{client_id}/actions/sendkey
Payload: KEY_POWER
```

### Get Volume
```
Topic: /remoteapp/tv/platform_service/{client_id}/actions/getvolume
Payload: (empty)
Response Topic: /remoteapp/mobile/{client_id}/platform_service/data/volume
```

### Set Volume to 50
```
Topic: /remoteapp/tv/platform_service/{client_id}/actions/changevolume
Payload: 50
```

### Get TV State
```
Topic: /remoteapp/tv/ui_service/{client_id}/actions/gettvstate
Payload: (empty)
Response: {"statetype":"remote_launcher"}
```

### Launch Netflix
```
Topic: /remoteapp/tv/ui_service/{client_id}/actions/launchapp
Payload: {"name":"Netflix","urlType":37,"storeType":0,"url":"netflix"}
```

### Trigger Pairing PIN
```
Topic: /remoteapp/tv/ui_service/{client_id}/actions/vidaa_app_connect
Payload: {"app_version":2,"connect_result":0,"device_type":"Mobile App"}
```

### Send Auth PIN
```
Topic: /remoteapp/tv/ui_service/{client_id}/actions/authenticationcode
Payload: {"authNum":"1234"}
```

## Files in This Project

| File | Purpose |
|------|---------|
| `tv_remote.py` | Main TV remote control client |
| `pair_new_client.py` | Pair new UUID with TV |
| `capture_pairing.py` | Debug/capture MQTT traffic |
| `test_connection.py` | Test TV connectivity |
| `pyvidaa/credentials.py` | Credential generation |
| `certs/fresh_cert.pem` | Client certificate |
| `certs/fresh_key.pem` | Client private key |

## Troubleshooting

### Connection Issues
- Ensure TV and client are on same network
- Check TV IP address hasn't changed
- Verify certificates are valid (not expired)

### Pairing Issues
- Enter PIN quickly (60 second timeout)
- Try restarting TV if PIN doesn't appear
- TV may have device limit - unpair old devices via TV settings
- Use working UUID (`56:b8:88:4e:f7:19`) if pairing fails

### Commands Not Working
- Verify UUID is paired (volume test)
- Check client_id format matches expected pattern
- Ensure subscriptions succeeded (no wildcard denial)

### Debugging
```bash
# Capture MQTT traffic
python capture_pairing.py sniff

# Test with working UUID interactively
python capture_pairing.py dual

# Verbose pairing attempt
python pair_new_client.py -v
```
