#!/usr/bin/env python3
"""Command-line interface for Hisense TV control."""

import argparse
import json
import sys
import time
from typing import Optional

from .client import HisenseTV
from .discovery import discover_all, discover_ssdp, discover_udp, probe_ip
from .config import (
    load_config,
    get_tv_config,
    get_default_tv,
    list_tvs,
    resolve_tv_id,
    update_tv_config,
    add_tv,
    set_default_tv,
    get_storage,
    DEFAULT_PORT,
)
from .keys import KEY_NAME_MAP, ALL_KEYS
from .wol import wake_tv, get_mac_from_ip


def _looks_like_mac(value: Optional[str]) -> bool:
    """Return True if value looks like a MAC/UUID rather than an IP address."""
    if not value:
        return False
    # IPs contain dots; MACs use colons/dashes or are 12 hex chars
    if "." in value:
        return False
    return ":" in value or "-" in value or len(value) == 12


def _resolve_mac_for_ip(ip: str) -> Optional[str]:
    """Resolve a TV's MAC address for dynamic-auth credentials.

    Looks for a matching host in config first, then falls back to a live UPnP
    probe. The MAC is needed to build a stable client_id; without it the client
    silently degrades to static credentials and the TV rejects the connection
    (MQTT CONNACK code 5).
    """
    # Check existing config for a TV at this IP with a stored MAC.
    # list_tvs() returns dicts with device_id + config fields merged in.
    for cfg in list_tvs():
        if cfg.get("host") == ip:
            mac = cfg.get("mac") or cfg.get("device_id")
            if _looks_like_mac(mac):
                return mac

    # Fall back to a live probe of the UPnP descriptor
    try:
        device = probe_ip(ip, timeout=3.0)
        if device and device.mac:
            return device.mac
    except Exception:
        pass
    return None


def _resolve_brand_for_ip(ip: str) -> str:
    """Resolve a TV's brand for dynamic-auth credentials.

    brand is part of the MQTT client_id and credential hashes, so a non-Hisense
    VIDAA OEM needs its own brand string or auth fails. Checks config first, then
    a live UPnP probe, defaulting to "his" (Hisense) like the Vidaa app does.
    """
    for cfg in list_tvs():
        if cfg.get("host") == ip and cfg.get("brand"):
            return cfg["brand"]

    try:
        device = probe_ip(ip, timeout=3.0)
        if device and device.brand:
            return device.brand
    except Exception:
        pass
    return "his"


def create_tv_client(tv_id: Optional[str] = None, ip: Optional[str] = None) -> HisenseTV:
    """Create TV client with config settings.

    Args:
        tv_id: TV identifier (device_id or alias). Uses default TV if not provided.
        ip: Override IP address (takes precedence over tv_id)

    Returns:
        Configured HisenseTV client
    """
    if ip:
        # Direct IP override - still resolve the MAC so dynamic auth can build a
        # valid client_id (otherwise we silently fall back to static creds -> rc=5).
        mac_address = _resolve_mac_for_ip(ip)
        return HisenseTV(
            host=ip,
            port=DEFAULT_PORT,
            mac_address=mac_address,
            use_dynamic_auth=True,
            brand=_resolve_brand_for_ip(ip),
        )

    # Get TV config by ID or use default
    tv_config = get_tv_config(tv_id) if tv_id else get_default_tv()

    if not tv_config:
        if tv_id:
            raise ValueError(f"TV '{tv_id}' not found. Use 'tv config list' to see available TVs.")
        raise ValueError("No default TV configured. Use 'tv config add' to add a TV.")

    host = tv_config.get("host")
    port = tv_config.get("port", DEFAULT_PORT)
    brand = tv_config.get("brand", "his")
    # MAC/UUID for dynamic auth - prefer a real MAC over the device_id, which may
    # just be the IP placeholder set by 'config add' before pairing.
    mac_address = tv_config.get("mac") or tv_config.get("device_id")
    if not _looks_like_mac(mac_address) and host:
        # device_id is the IP placeholder - try to resolve a real MAC
        resolved = _resolve_mac_for_ip(host)
        if resolved:
            mac_address = resolved

    if not host:
        raise ValueError(f"TV '{tv_id or 'default'}' has no host configured.")

    return HisenseTV(
        host=host,
        port=port,
        mac_address=mac_address,
        use_dynamic_auth=True,
        brand=brand,
    )


def cmd_power(args):
    """Toggle TV power."""
    tv = create_tv_client(getattr(args, 'tv', None), args.ip)
    if tv.connect(timeout=5):
        tv.power()
        time.sleep(0.5)
        tv.disconnect()
        print("Power command sent")
    else:
        print("Failed to connect to TV", file=sys.stderr)
        return 1
    return 0


def cmd_volume(args):
    """Control volume."""
    tv = create_tv_client(getattr(args, 'tv', None), args.ip)
    if tv.connect(timeout=5):
        if args.action == "up":
            for _ in range(args.amount):
                tv.volume_up()
                time.sleep(0.1)
            print(f"Volume up x{args.amount}")
        elif args.action == "down":
            for _ in range(args.amount):
                tv.volume_down()
                time.sleep(0.1)
            print(f"Volume down x{args.amount}")
        elif args.action == "mute":
            tv.mute()
            print("Mute toggled")
        elif args.action == "set":
            tv.set_volume(args.amount)
            print(f"Volume set to {args.amount}")
        elif args.action == "get":
            vol = tv.get_volume()
            if vol is not None:
                print(f"Volume: {vol}")
            else:
                print("Could not get volume")
        time.sleep(0.3)
        tv.disconnect()
    else:
        print("Failed to connect to TV", file=sys.stderr)
        return 1
    return 0


def cmd_key(args):
    """Send a key press."""
    key = args.key.upper()
    if not key.startswith("KEY_"):
        key = f"KEY_{key}"

    if key not in ALL_KEYS:
        # Try to find closest match
        matches = [k for k in ALL_KEYS if args.key.upper() in k]
        if matches:
            print(f"Unknown key '{args.key}'. Did you mean: {', '.join(matches)}", file=sys.stderr)
        else:
            print(f"Unknown key '{args.key}'. Use 'tv keys' to list available keys.", file=sys.stderr)
        return 1

    tv = create_tv_client(getattr(args, 'tv', None), args.ip)
    if tv.connect(timeout=5):
        tv.send_key(key)
        time.sleep(0.3)
        tv.disconnect()
        print(f"Sent: {key}")
    else:
        print("Failed to connect to TV", file=sys.stderr)
        return 1
    return 0


def cmd_keys(args):
    """List available keys."""
    print("Available keys:")
    print()

    categories = {
        "Power": ["KEY_POWER"],
        "Navigation": ["KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_OK", "KEY_ENTER"],
        "Menu": ["KEY_MENU", "KEY_HOME", "KEY_BACK", "KEY_RETURNS", "KEY_EXIT"],
        "Volume": ["KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE"],
        "Playback": ["KEY_PLAY", "KEY_PAUSE", "KEY_STOP", "KEY_FAST_FORWARD", "KEY_REWIND"],
        "Numbers": ["KEY_0", "KEY_1", "KEY_2", "KEY_3", "KEY_4", "KEY_5", "KEY_6", "KEY_7", "KEY_8", "KEY_9"],
        "Channels": ["KEY_CHANNELUP", "KEY_CHANNELDOWN"],
        "Colors": ["KEY_RED", "KEY_GREEN", "KEY_YELLOW", "KEY_BLUE"],
    }

    for cat, keys in categories.items():
        available = [k for k in keys if k in ALL_KEYS]
        if available:
            print(f"  {cat}:")
            for k in available:
                short = k.replace("KEY_", "").lower()
                print(f"    {short:20} ({k})")

    # Show other keys
    shown = set(k for keys in categories.values() for k in keys)
    others = sorted([k for k in ALL_KEYS if k not in shown])
    if others:
        print(f"  Other:")
        for k in others:
            short = k.replace("KEY_", "").lower()
            print(f"    {short:20} ({k})")
    return 0


def cmd_nav(args):
    """Navigation shortcuts."""
    tv = create_tv_client(getattr(args, 'tv', None), args.ip)
    if tv.connect(timeout=5):
        action = args.action
        if action == "up":
            tv.up()
        elif action == "down":
            tv.down()
        elif action == "left":
            tv.left()
        elif action == "right":
            tv.right()
        elif action == "ok":
            tv.ok()
        elif action == "back":
            tv.back()
        elif action == "home":
            tv.home()
        elif action == "menu":
            tv.menu()
        time.sleep(0.3)
        tv.disconnect()
        print(f"Navigation: {action}")
    else:
        print("Failed to connect to TV", file=sys.stderr)
        return 1
    return 0


def cmd_app(args):
    """Launch an app."""
    tv = create_tv_client(getattr(args, 'tv', None), args.ip)
    if tv.connect(timeout=5):
        if args.name == "list":
            apps = tv.get_apps()
            if apps:
                print("Available apps:")
                for app in apps:
                    name = app.get("name", "Unknown")
                    print(f"  {name}")
            else:
                print("Could not get app list")
        else:
            if tv.launch_app(args.name):
                print(f"Launching: {args.name}")
            else:
                print(f"Failed to launch: {args.name}", file=sys.stderr)
        time.sleep(0.5)
        tv.disconnect()
    else:
        print("Failed to connect to TV", file=sys.stderr)
        return 1
    return 0


def cmd_source(args):
    """Change input source."""
    tv = create_tv_client(getattr(args, 'tv', None), args.ip)
    if tv.connect(timeout=5):
        if args.source == "list":
            sources = tv.get_sources()
            if sources:
                print("Available sources:")
                for src in sources:
                    name = src.get("sourcename", src.get("name", "Unknown"))
                    sid = src.get("sourceid", "?")
                    print(f"  {name} (id: {sid})")
            else:
                print("Could not get source list")
        else:
            tv.set_source(args.source)
            print(f"Switching to: {args.source}")
        time.sleep(0.5)
        tv.disconnect()
    else:
        print("Failed to connect to TV", file=sys.stderr)
        return 1
    return 0


def cmd_config(args):
    """View or set configuration."""
    if args.action == "show":
        config = load_config()
        tvs = list_tvs()
        default_tv_id = config.get("default_tv")

        if not tvs:
            print("No TVs configured. Use 'tv config add <ip>' to add a TV.")
            return 0

        print("Configured TVs:")
        for tv_id in tvs:
            tv_config = get_tv_config(tv_id)
            if not tv_config:
                continue

            is_default = " (default)" if tv_id == default_tv_id else ""
            alias = tv_config.get("alias", "")
            alias_str = f" [{alias}]" if alias else ""
            name = tv_config.get("name", "")
            name_str = f" - {name}" if name else ""

            print(f"\n  {tv_id}{alias_str}{is_default}{name_str}")
            print(f"    Host:  {tv_config.get('host', '(not set)')}")
            print(f"    Port:  {tv_config.get('port', DEFAULT_PORT)}")

            device_id = tv_config.get("device_id")
            if device_id:
                print(f"    Device ID: {device_id}")

    elif args.action == "list":
        tvs = list_tvs()
        if not tvs:
            print("No TVs configured.")
            return 0
        print("Configured TVs:")
        for tv_id in tvs:
            tv_config = get_tv_config(tv_id)
            alias = tv_config.get("alias", "") if tv_config else ""
            alias_str = f" ({alias})" if alias else ""
            print(f"  {tv_id}{alias_str}")

    elif args.action == "add":
        if not args.value:
            print("Please provide IP address: tv config add 192.168.1.100", file=sys.stderr)
            return 1
        ip = args.value
        alias = args.alias if hasattr(args, 'alias') and args.alias else None

        # Probe the TV so we can persist its MAC (needed for dynamic-auth
        # credentials), name and protocol version instead of just the IP.
        extra = {}
        try:
            device = probe_ip(ip, timeout=3.0)
        except Exception:
            device = None
        if device:
            if device.mac:
                extra["mac"] = device.mac
            if device.name:
                extra["name"] = device.name
            if device.brand:
                extra["brand"] = device.brand
            if device.protocol_version:
                extra["protocol_version"] = device.protocol_version

        add_tv(ip, ip, alias=alias, **extra)  # Use IP as device_id until paired
        print(f"Added TV at {ip}")
        if device and device.name:
            print(f"  Name:  {device.name}")
        if extra.get("mac"):
            print(f"  MAC:   {extra['mac']}")
        else:
            print("  MAC:   (not found - TV may be off; re-run when it is on)")
        if alias:
            print(f"  Alias: {alias}")

        # Make this the default if it's the only TV, and say so explicitly.
        config = load_config()
        if config.get("default_tv") == ip:
            print(f"  Default TV is now: {ip}")
        else:
            print(f"  Default TV remains: {config.get('default_tv')}")
            print(f"  (use 'tv --ip {ip} auth pair' to pair this TV specifically)")
        print("Use 'tv auth pair' to authenticate with the default TV.")

    elif args.action == "set-default":
        if not args.value:
            print("Please provide TV ID or alias: tv config set-default living_room", file=sys.stderr)
            return 1
        set_default_tv(args.value)
        print(f"Default TV set to: {args.value}")

    elif args.action == "set-alias":
        tv_id = getattr(args, 'tv', None)
        if not tv_id:
            print("Please specify TV with --tv: tv --tv 192.168.1.50 config set-alias bedroom", file=sys.stderr)
            return 1
        if not args.value:
            print("Please provide alias: tv config set-alias bedroom", file=sys.stderr)
            return 1
        update_tv_config(tv_id, {"alias": args.value})
        print(f"Alias set to: {args.value}")

    return 0


def cmd_status(args):
    """Get TV status."""
    tv_id = getattr(args, 'tv', None)
    tv = create_tv_client(tv_id, args.ip)
    tv_config = get_tv_config(tv_id) if tv_id else get_default_tv()
    host = args.ip or (tv_config.get("host") if tv_config else "unknown")
    print(f"Connecting to {host}...")
    if tv.connect(timeout=5):
        print("Connected!")
        state = tv.get_state()
        if state:
            print("TV State:")
            for k, v in state.items():
                print(f"  {k}: {v}")
        else:
            print("Could not get state (TV may be off)")
        tv.disconnect()
    else:
        print("Failed to connect to TV", file=sys.stderr)
        return 1
    return 0


def cmd_discover(args):
    """Discover Hisense TVs on the network."""
    timeout = getattr(args, 'timeout', 5.0)
    method = getattr(args, 'method', 'all')
    verbose = getattr(args, 'verbose', False)

    print(f"Scanning for Hisense TVs (timeout: {timeout}s)...")

    if method == 'ssdp':
        devices = discover_ssdp(timeout=timeout)
    elif method == 'udp':
        devices = discover_udp(timeout=timeout)
    elif method == 'probe' and args.ip:
        device = probe_ip(args.ip, timeout=timeout)
        devices = {args.ip: device} if device else {}
    else:
        devices = discover_all(timeout=timeout)

    if not devices:
        print("No TVs found.")
        print("\nTips:")
        print("  - Make sure the TV is powered on")
        print("  - Ensure TV and computer are on the same network")
        print("  - Try: tv discover --method ssdp")
        print("  - Try probing a specific IP: tv discover --ip 192.168.1.50")
        return 1

    print(f"\nFound {len(devices)} TV(s):\n")

    for ip, device in devices.items():
        print(f"  {ip}")
        if device.name:
            print(f"    Name:  {device.name}")
        if device.model:
            print(f"    Model: {device.model}")
        if device.brand:
            print(f"    Brand: {device.brand}")
        if device.mac:
            print(f"    MAC:   {device.mac}")
        if verbose:
            if device.protocol_version:
                print(f"    Protocol: {device.protocol_version}")
            if device.discovery_method:
                print(f"    Via:      {device.discovery_method}")
        print()

    print("To add a TV: tv config add <IP>")
    return 0


def cmd_wake(args):
    """Wake TV using Wake-on-LAN."""
    tv_id = getattr(args, 'tv', None)
    tv_config = get_tv_config(tv_id) if tv_id else get_default_tv()

    # Get MAC from command line or config
    mac = getattr(args, 'mac', None)
    host = getattr(args, 'ip', None)

    if not mac and tv_config:
        mac = tv_config.get("device_id") or tv_config.get("mac")
        host = host or tv_config.get("host")

    if not mac:
        print("No MAC address specified.", file=sys.stderr)
        print("Use: tv wake --mac AA:BB:CC:DD:EE:FF", file=sys.stderr)
        print("Or configure a TV first: tv config add <ip>", file=sys.stderr)
        return 1

    # Format MAC if it's a device_id (no colons)
    if ":" not in mac and len(mac) == 12:
        mac = ":".join(mac[i:i+2] for i in range(0, 12, 2))

    # Get subnet from IP for directed broadcast
    subnet = None
    if host:
        ip_parts = host.rsplit(".", 1)
        subnet = ip_parts[0] if len(ip_parts) == 2 else None

    print(f"Sending Wake-on-LAN to {mac}...")
    if wake_tv(mac, subnet):
        print("Magic packet sent!")
        print("TV should wake up in a few seconds...")
        return 0
    else:
        print("Failed to send wake packet", file=sys.stderr)
        return 1


def cmd_on(args):
    """Turn TV on (wake + smart power on)."""
    tv_id = getattr(args, 'tv', None)
    tv_config = get_tv_config(tv_id) if tv_id else get_default_tv()

    # First try to wake via WoL
    if tv_config:
        mac = tv_config.get("device_id") or tv_config.get("mac")
        host = tv_config.get("host")
        if mac:
            # Format MAC if it's a device_id
            if ":" not in mac and len(mac) == 12:
                mac = ":".join(mac[i:i+2] for i in range(0, 12, 2))

            subnet = None
            if host:
                ip_parts = host.rsplit(".", 1)
                subnet = ip_parts[0] if len(ip_parts) == 2 else None

            print(f"Sending Wake-on-LAN to {mac}...")
            wake_tv(mac, subnet)
            print("Waiting for TV to boot...")
            time.sleep(5)

    # Try to connect and use smart power on
    tv = create_tv_client(tv_id, args.ip)
    for attempt in range(6):
        if tv.connect(timeout=3):
            # Use smart power_on which checks state first
            if tv.power_on():
                print("TV is on!")
            tv.disconnect()
            return 0
        if attempt < 5:
            print(f"Waiting... ({attempt + 1}/6)")
            time.sleep(2)

    print("TV did not respond. It may need WoL enabled in settings.", file=sys.stderr)
    return 1


def cmd_off(args):
    """Turn TV off (smart power off with state check)."""
    tv = create_tv_client(getattr(args, 'tv', None), args.ip)
    if tv.connect(timeout=5):
        if tv.power_off():
            print("Power off command sent.")
        tv.disconnect()
        return 0
    else:
        print("Failed to connect to TV", file=sys.stderr)
        return 1


def cmd_monitor(args):
    """Monitor MQTT messages from TV."""
    import signal
    import ssl
    from datetime import datetime
    import paho.mqtt.client as mqtt

    tv_id = getattr(args, 'tv', None)
    tv_config = get_tv_config(tv_id) if tv_id else get_default_tv()
    storage = get_storage()

    if args.ip:
        host = args.ip
        port = DEFAULT_PORT
    elif tv_config:
        host = tv_config.get("host")
        port = tv_config.get("port", DEFAULT_PORT)
    else:
        print("No TV configured. Use 'tv config add <ip>' first.", file=sys.stderr)
        return 1

    # Try to get token by device_id first, then by host:port
    device_id = tv_config.get("device_id") if tv_config else None
    token_data = storage.get_token(device_id) if device_id else None
    if not token_data:
        token_data = storage.get_token(host=host, port=port)
    if not token_data:
        print("No stored credentials. Run './tv auth pair' first.")
        return 1

    client_id = token_data["client_id"]
    username = token_data["mqtt_username"]
    password = token_data["access_token"]

    # TV broker doesn't support wildcard (#) subscriptions
    # Subscribe to specific known response topics
    topics = [
        # Broadcast topics (all clients receive these)
        "/remoteapp/mobile/broadcast/ui_service/state",
        "/remoteapp/mobile/broadcast/platform_service/actions/volumechange",
        "/remoteapp/mobile/broadcast/ui_service/data/hotelmodechange",
        # Client-specific response topics
        f"/remoteapp/mobile/{client_id}/ui_service/data/sourcelist",
        f"/remoteapp/mobile/{client_id}/ui_service/data/applist",
        f"/remoteapp/mobile/{client_id}/platform_service/data/tokenissuance",
    ]

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print(f"Connected to {host}:{port}")
            print("Subscribing to topics:")
            for topic in topics:
                result, mid = client.subscribe(topic)
                print(f"  {topic}")
            print("\nMonitoring MQTT messages... (Ctrl+C to stop)\n")
        else:
            print(f"Connection failed: {rc}")

    def on_subscribe(client, userdata, mid, granted_qos):
        pass  # Subscription confirmed silently

    def on_message(client, userdata, msg):
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            topic_short = msg.topic.split("/")[-1]

            try:
                payload = json.loads(msg.payload.decode())
                payload_str = json.dumps(payload)
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload_str = msg.payload.decode()[:200]

            # Truncate long payloads
            if len(payload_str) > 100:
                payload_str = payload_str[:100] + "..."

            print(f"{timestamp} [{topic_short}] {payload_str}")
        except Exception as e:
            print(f"Error processing message: {e}")

    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    # Use absolute path for certs
    import os
    cert_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "certs")
    ssl_ctx.load_cert_chain(
        os.path.join(cert_dir, "vidaa_client.pem"),
        os.path.join(cert_dir, "vidaa_client.key")
    )
    client.tls_set_context(ssl_ctx)

    print(f"Connecting to TV at {host}...")
    try:
        client.connect(host, port, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nStopping monitor...")
    finally:
        client.disconnect()

    return 0


def cmd_auth(args):
    """View or manage authentication."""
    tv_id = getattr(args, 'tv', None)
    tv_config = get_tv_config(tv_id) if tv_id else get_default_tv()
    storage = get_storage()

    if args.ip:
        host = args.ip
        port = DEFAULT_PORT
    elif tv_config:
        host = tv_config.get("host")
        port = tv_config.get("port", DEFAULT_PORT)
    else:
        print("No TV configured. Use 'tv config add <ip>' first.", file=sys.stderr)
        return 1

    # Try to get token by device_id first, then by host:port
    device_id = tv_config.get("device_id") if tv_config else None

    if args.action == "status":
        status = storage.get_token_status(device_id) if device_id else None
        if not status or not status.get("has_token"):
            status = storage.get_token_status(host=host, port=port)

        if not status["has_token"]:
            print("No stored credentials. Run 'tv auth pair' to authenticate.")
            return 0

        print("Authentication status:")
        print(f"  Access token:  {'valid' if status['access_valid'] else 'EXPIRED'}", end="")
        if status["access_valid"]:
            hours = status["access_expires_in"] // 3600
            mins = (status["access_expires_in"] % 3600) // 60
            print(f" (expires in {hours}h {mins}m)")
        else:
            print()

        print(f"  Refresh token: {'valid' if status['refresh_valid'] else 'EXPIRED'}", end="")
        if status["refresh_valid"]:
            days = status["refresh_expires_in"] // 86400
            hours = (status["refresh_expires_in"] % 86400) // 3600
            print(f" (expires in {days}d {hours}h)")
        else:
            print()

        if status["needs_refresh"]:
            print("\n  Token will auto-refresh on next connection.")
        elif status["needs_reauth"]:
            print("\n  Both tokens expired. Run 'tv auth pair' to re-authenticate.")

    elif args.action == "pair":
        print(f"Starting pairing with {host}:{port} ...")
        tv = create_tv_client(tv_id, args.ip)

        if tv.connect(timeout=10):
            # Trigger PIN dialog
            tv.start_pairing()
            print("\nA PIN should appear on your TV screen.")
            print("Enter the PIN (or 'q' to cancel): ", end="", flush=True)

            pin = input().strip()
            if pin.lower() == 'q':
                print("Pairing cancelled.")
                tv.disconnect()
                return 1

            if tv.authenticate(pin):
                print("Pairing successful! Credentials saved.")
                tv.disconnect()
                return 0
            else:
                print("Pairing failed. Check the PIN and try again.", file=sys.stderr)
                tv.disconnect()
                return 1
        else:
            print(f"Failed to connect to {host}:{port}", file=sys.stderr)
            print(
                "If the TV is reachable but auth is refused (MQTT code 5), check "
                "that the TV's clock is correct (date/time, timezone and DST) - "
                "credentials are time-based and a clock skew is rejected.",
                file=sys.stderr,
            )
            return 1

    elif args.action == "clear":
        if device_id:
            storage.delete_token(device_id)
        else:
            storage.delete_token(host, port)
        print("Stored credentials cleared.")

    elif args.action == "refresh":
        tv = create_tv_client(tv_id, args.ip)
        if tv.connect(timeout=10):
            if tv.refresh_token():
                print("Token refreshed successfully!")
            else:
                print("Token refresh failed.", file=sys.stderr)
                tv.disconnect()
                return 1
            tv.disconnect()
        else:
            print("Failed to connect to TV", file=sys.stderr)
            return 1

    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="tv",
        description="Control your Hisense TV from the command line",
    )
    parser.add_argument("--tv", help="TV ID or alias (uses default TV if not specified)")
    parser.add_argument("--ip", help="TV IP address (overrides --tv and config)")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Power
    p_power = subparsers.add_parser("power", help="Toggle TV power")
    p_power.set_defaults(func=cmd_power)

    # Volume
    p_vol = subparsers.add_parser("volume", aliases=["vol"], help="Volume control")
    p_vol.add_argument("action", choices=["up", "down", "mute", "set", "get"], help="Volume action")
    p_vol.add_argument("amount", type=int, nargs="?", default=1, help="Amount (default: 1)")
    p_vol.set_defaults(func=cmd_volume)

    # Key
    p_key = subparsers.add_parser("key", help="Send a key press")
    p_key.add_argument("key", help="Key name (e.g., power, up, ok)")
    p_key.set_defaults(func=cmd_key)

    # Keys list
    p_keys = subparsers.add_parser("keys", help="List available keys")
    p_keys.set_defaults(func=cmd_keys)

    # Navigation shortcuts
    p_nav = subparsers.add_parser("nav", help="Navigation shortcuts")
    p_nav.add_argument("action", choices=["up", "down", "left", "right", "ok", "back", "home", "menu"])
    p_nav.set_defaults(func=cmd_nav)

    # Quick navigation aliases
    for nav_cmd in ["up", "down", "left", "right", "ok", "back", "home", "menu"]:
        p = subparsers.add_parser(nav_cmd, help=f"Navigate {nav_cmd}")
        p.set_defaults(func=cmd_nav, action=nav_cmd)

    # App
    p_app = subparsers.add_parser("app", help="Launch an app")
    p_app.add_argument("name", help="App name (netflix, youtube, amazon, disney, hulu) or 'list'")
    p_app.set_defaults(func=cmd_app)

    # Source
    p_src = subparsers.add_parser("source", aliases=["input"], help="Change input source")
    p_src.add_argument("source", help="Source name (hdmi1, hdmi2, tv, av) or 'list'")
    p_src.set_defaults(func=cmd_source)

    # Config
    p_cfg = subparsers.add_parser("config", help="View or set configuration")
    p_cfg.add_argument(
        "action",
        choices=["show", "list", "add", "set-default", "set-alias"],
        nargs="?",
        default="show",
        help="show: display all TVs, list: list TV IDs, add: add new TV, set-default: set default TV, set-alias: set TV alias"
    )
    p_cfg.add_argument("value", nargs="?", help="Value to set")
    p_cfg.add_argument("--alias", help="Alias when adding a TV")
    p_cfg.set_defaults(func=cmd_config)

    # Status
    p_status = subparsers.add_parser("status", help="Get TV status")
    p_status.set_defaults(func=cmd_status)

    # Discovery
    p_discover = subparsers.add_parser("discover", aliases=["scan"], help="Discover TVs on the network")
    p_discover.add_argument("--timeout", "-t", type=float, default=5.0, help="Discovery timeout in seconds")
    p_discover.add_argument("--method", "-m", choices=["all", "ssdp", "udp", "probe"], default="all",
                           help="Discovery method (default: all)")
    p_discover.add_argument("--verbose", "-v", action="store_true", help="Show more details")
    p_discover.set_defaults(func=cmd_discover)

    # Wake-on-LAN
    p_wake = subparsers.add_parser("wake", help="Wake TV using Wake-on-LAN")
    p_wake.add_argument("--mac", help="TV MAC address (e.g., AA:BB:CC:DD:EE:FF)")
    p_wake.set_defaults(func=cmd_wake)

    # Turn on (wake + verify)
    p_on = subparsers.add_parser("on", help="Turn TV on (wake + wait)")
    p_on.set_defaults(func=cmd_on)

    # Turn off (smart power off)
    p_off = subparsers.add_parser("off", help="Turn TV off (checks state first)")
    p_off.set_defaults(func=cmd_off)

    # Monitor MQTT messages
    p_monitor = subparsers.add_parser("monitor", help="Monitor MQTT messages from TV")
    p_monitor.set_defaults(func=cmd_monitor)

    # Authentication management
    p_auth = subparsers.add_parser("auth", help="Manage TV authentication")
    p_auth.add_argument(
        "action",
        choices=["status", "pair", "refresh", "clear"],
        nargs="?",
        default="status",
        help="status: show token status, pair: pair new device, refresh: refresh token, clear: remove credentials"
    )
    p_auth.set_defaults(func=cmd_auth)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
