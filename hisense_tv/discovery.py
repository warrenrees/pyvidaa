"""Network discovery for Hisense TVs.

Supports multiple discovery methods:
- SSDP M-SEARCH (active multicast query)
- SSDP NOTIFY listener (passive multicast)
- UDP broadcast on port 36671 (Hisense-specific)
- Direct IP probe
"""

import logging
import socket
import struct
import subprocess
import json
import time
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .config import (
    DISCOVERY_PORT,
    BROADCAST_ADDR,
    SSDP_ADDR,
    SSDP_PORT,
    UPNP_PORTS,
)

_LOGGER = logging.getLogger(__name__)

# Discovery message formats for UDP broadcast
DISCOVERY_MESSAGES = [
    json.dumps({"request": "discover"}).encode(),
    json.dumps({"request": "discover", "device": "phone", "version": "1.0"}).encode(),
    b"HiSmart:discover",
    b"{}",
]

# SSDP M-SEARCH request template
SSDP_MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 3\r\n"
    "ST: {st}\r\n"
    "\r\n"
)

# Search targets for SSDP M-SEARCH
SSDP_SEARCH_TARGETS = [
    "urn:schemas-upnp-org:device:MediaRenderer:1",
    "ssdp:all",
]


@dataclass
class DiscoveredTV:
    """Discovered Hisense TV device."""

    ip: str
    port: int = 36669
    name: Optional[str] = None
    model: Optional[str] = None
    brand: Optional[str] = None
    mac: Optional[str] = None
    protocol_version: Optional[str] = None
    location: Optional[str] = None
    usn: Optional[str] = None
    server: Optional[str] = None
    source: str = "unknown"  # ssdp_msearch, ssdp_notify, udp, probe
    discovery_method: Optional[str] = None
    raw_data: Dict = field(default_factory=dict)

    def __repr__(self) -> str:
        parts = [f"DiscoveredTV({self.ip}"]
        if self.name:
            parts.append(f", name={self.name!r}")
        if self.model:
            parts.append(f", model={self.model!r}")
        if self.mac:
            parts.append(f", mac={self.mac!r}")
        parts.append(f", source={self.source!r})")
        return "".join(parts)


def get_local_ips() -> Set[str]:
    """Get all local IP addresses to filter out self-broadcasts.

    Returns:
        Set of local IP address strings.
    """
    ips = set(["127.0.0.1"])
    try:
        hostname = socket.gethostname()
        ips.add(socket.gethostbyname(hostname))
    except Exception:
        pass
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
        for ip in result.stdout.strip().split():
            ips.add(ip)
    except Exception:
        pass
    return ips


def _parse_ssdp_headers(message: str) -> Dict[str, str]:
    """Parse SSDP message headers into a dictionary.

    Args:
        message: Raw SSDP message string.

    Returns:
        Dictionary of header name -> value.
    """
    headers = {}
    for line in message.split("\r\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().upper()] = value.strip()
    return headers


def discover_ssdp(
    timeout: float = 5.0,
    interface: Optional[str] = None,
) -> Dict[str, DiscoveredTV]:
    """Discover devices via SSDP M-SEARCH multicast query.

    Sends an M-SEARCH request to the SSDP multicast address and
    collects responses from devices on the network.

    Args:
        timeout: How long to wait for responses in seconds.
        interface: Interface IP to bind to (e.g., "10.0.0.50").

    Returns:
        Dictionary mapping IP addresses to DiscoveredTV objects.
    """
    _LOGGER.debug("Starting SSDP M-SEARCH discovery (timeout=%s)", timeout)

    found_devices: Dict[str, DiscoveredTV] = {}
    local_ips = get_local_ips()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)

    # Bind to specific interface or any
    bind_ip = interface if interface else ""
    try:
        sock.bind((bind_ip, 0))
    except OSError as e:
        _LOGGER.warning("Failed to bind socket: %s", e)
        sock.close()
        return found_devices

    # Set multicast TTL
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

    # If interface specified, set multicast interface
    if interface:
        sock.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_MULTICAST_IF,
            socket.inet_aton(interface),
        )

    start_time = time.time()

    # Send M-SEARCH for each search target
    for st in SSDP_SEARCH_TARGETS:
        msearch = SSDP_MSEARCH.format(st=st).encode()
        try:
            sock.sendto(msearch, (SSDP_ADDR, SSDP_PORT))
            _LOGGER.debug("Sent M-SEARCH for ST=%s", st)
        except OSError as e:
            _LOGGER.warning("Failed to send M-SEARCH: %s", e)

    # Collect responses
    while time.time() - start_time < timeout:
        try:
            data, addr = sock.recvfrom(4096)
            ip = addr[0]

            if ip in local_ips:
                continue

            message = data.decode("utf-8", errors="ignore")

            # Only process HTTP responses (not requests)
            if not message.startswith("HTTP"):
                continue

            headers = _parse_ssdp_headers(message)

            if ip not in found_devices:
                device = DiscoveredTV(
                    ip=ip,
                    location=headers.get("LOCATION"),
                    usn=headers.get("USN"),
                    server=headers.get("SERVER"),
                    source="ssdp_msearch",
                    raw_data=headers,
                )
                found_devices[ip] = device
                _LOGGER.info("Found device via SSDP M-SEARCH: %s", ip)

        except socket.timeout:
            continue
        except Exception as e:
            _LOGGER.debug("Error receiving SSDP response: %s", e)
            continue

    sock.close()
    _LOGGER.debug("SSDP M-SEARCH complete, found %d device(s)", len(found_devices))
    return found_devices


def listen_ssdp(
    timeout: float = 30.0,
    interface: Optional[str] = None,
) -> Dict[str, DiscoveredTV]:
    """Listen for SSDP NOTIFY announcements (passive discovery).

    Devices periodically announce themselves via multicast. This listens
    for those announcements instead of actively querying.

    Args:
        timeout: How long to listen in seconds.
        interface: Interface IP to bind to (e.g., "10.0.0.50").

    Returns:
        Dictionary mapping IP addresses to DiscoveredTV objects.
    """
    _LOGGER.debug("Starting SSDP NOTIFY listener (timeout=%s)", timeout)

    found_devices: Dict[str, DiscoveredTV] = {}
    local_ips = get_local_ips()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind(("", SSDP_PORT))
    except OSError as e:
        _LOGGER.warning("Failed to bind to SSDP port %d: %s", SSDP_PORT, e)
        sock.close()
        return found_devices

    # Join multicast group
    if interface:
        mreq = struct.pack(
            "4s4s",
            socket.inet_aton(SSDP_ADDR),
            socket.inet_aton(interface),
        )
    else:
        mreq = struct.pack("4sl", socket.inet_aton(SSDP_ADDR), socket.INADDR_ANY)

    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError as e:
        _LOGGER.warning("Failed to join multicast group: %s", e)
        sock.close()
        return found_devices

    sock.settimeout(1.0)
    start_time = time.time()

    try:
        while time.time() - start_time < timeout:
            try:
                data, addr = sock.recvfrom(4096)
                ip = addr[0]

                if ip in local_ips:
                    continue

                message = data.decode("utf-8", errors="ignore")

                # Only process NOTIFY messages
                if not message.startswith("NOTIFY"):
                    continue

                headers = _parse_ssdp_headers(message)

                if ip not in found_devices:
                    device = DiscoveredTV(
                        ip=ip,
                        location=headers.get("LOCATION"),
                        usn=headers.get("USN"),
                        server=headers.get("SERVER"),
                        source="ssdp_notify",
                        raw_data=headers,
                    )
                    found_devices[ip] = device
                    _LOGGER.info("Found device via SSDP NOTIFY: %s", ip)

            except socket.timeout:
                continue

    except KeyboardInterrupt:
        _LOGGER.debug("SSDP listener interrupted by user")

    finally:
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
        except Exception:
            pass
        sock.close()

    _LOGGER.debug("SSDP NOTIFY listener complete, found %d device(s)", len(found_devices))
    return found_devices


def discover_udp(
    timeout: float = 5.0,
    retries: int = 3,
    interface: Optional[str] = None,
) -> Dict[str, DiscoveredTV]:
    """Discover TVs via UDP broadcast on port 36671.

    Sends Hisense-specific discovery packets to the broadcast address
    and listens for responses.

    Args:
        timeout: Total time to wait for responses in seconds.
        retries: Number of times to send discovery packets.
        interface: Interface IP to bind to (e.g., "10.0.0.50").

    Returns:
        Dictionary mapping IP addresses to DiscoveredTV objects.
    """
    _LOGGER.debug(
        "Starting UDP broadcast discovery (timeout=%s, retries=%d)", timeout, retries
    )

    found_devices: Dict[str, DiscoveredTV] = {}
    local_ips = get_local_ips()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(1.0)

    bind_ip = interface if interface else ""

    try:
        sock.bind((bind_ip, DISCOVERY_PORT))
    except OSError:
        try:
            sock.bind((bind_ip, 0))
        except OSError as e:
            _LOGGER.warning("Failed to bind socket: %s", e)
            sock.close()
            return found_devices

    start_time = time.time()

    for i in range(retries):
        for msg in DISCOVERY_MESSAGES:
            try:
                sock.sendto(msg, (BROADCAST_ADDR, DISCOVERY_PORT))
            except OSError as e:
                _LOGGER.debug("Failed to send discovery packet: %s", e)

        _LOGGER.debug("Sent discovery packets (attempt %d/%d)", i + 1, retries)

        listen_until = time.time() + (timeout / retries)
        while time.time() < listen_until:
            try:
                data, addr = sock.recvfrom(4096)
                ip = addr[0]

                if ip in local_ips:
                    continue

                if ip not in found_devices:
                    try:
                        response = json.loads(data.decode())
                        device = DiscoveredTV(
                            ip=ip,
                            name=response.get(
                                "devicename",
                                response.get("name", response.get("device_name")),
                            ),
                            model=response.get("model", response.get("model_name")),
                            mac=response.get("mac", response.get("macaddress")),
                            source="udp",
                            raw_data=response,
                        )
                    except json.JSONDecodeError:
                        raw = data.decode() if data else ""
                        device = DiscoveredTV(
                            ip=ip,
                            source="udp",
                            raw_data={"raw": raw},
                        )

                    found_devices[ip] = device
                    _LOGGER.info("Found device via UDP broadcast: %s", ip)

            except socket.timeout:
                continue
            except Exception as e:
                _LOGGER.debug("Error receiving UDP response: %s", e)
                break

    sock.close()
    _LOGGER.debug("UDP broadcast discovery complete, found %d device(s)", len(found_devices))
    return found_devices


def probe_ip(
    ip: str,
    port: Optional[int] = None,
    timeout: float = 3.0,
) -> Optional[DiscoveredTV]:
    """Probe a specific IP address for a Hisense TV.

    Fetches the UPnP device description XML to get TV info.

    Args:
        ip: Target IP address.
        port: UPnP port. If None (default), each candidate in UPNP_PORTS is
            tried in order (some VIDAA OS versions use 18400 instead of 38400).
        timeout: How long to wait for response in seconds.

    Returns:
        DiscoveredTV if device responds, None otherwise.
    """
    candidate_ports = [port] if port is not None else list(UPNP_PORTS)
    for candidate in candidate_ports:
        device = _probe_ip_port(ip, candidate, timeout)
        if device is not None:
            return device
    return None


def _probe_ip_port(
    ip: str,
    port: int,
    timeout: float,
) -> Optional[DiscoveredTV]:
    """Probe a single IP:port for a Hisense TV's UPnP descriptor."""
    import urllib.request
    import xml.etree.ElementTree as ET

    url = f"http://{ip}:{port}/MediaServer/rendererdevicedesc.xml"
    _LOGGER.debug("Probing %s via UPnP: %s", ip, url)

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read().decode('utf-8')

        # Parse XML
        root = ET.fromstring(data)
        ns = 'urn:schemas-upnp-org:device-1-0'

        device_elem = root.find('.//{%s}device' % ns)

        name = None
        model = None
        mac = None
        mac_wifi = None
        mac_eth = None
        firmware = None
        raw_data = {}

        if device_elem is not None:
            # Get friendly name
            friendly = device_elem.find('{%s}friendlyName' % ns)
            if friendly is not None:
                name = friendly.text

            # Get model description (contains MAC, protocol version, etc.)
            model_desc = device_elem.find('{%s}modelDescription' % ns)
            if model_desc is not None and model_desc.text:
                desc_text = model_desc.text
                # Parse key=value pairs from description
                for line in desc_text.split('\n'):
                    if '=' in line:
                        key, _, value = line.partition('=')
                        key = key.strip()
                        value = value.strip()
                        raw_data[key] = value
                        if key == 'mac':
                            mac = value
                        elif key == 'macWifi':
                            mac_wifi = value
                        elif key == 'macEthernet':
                            mac_eth = value

            # Get model name (skip generic "Renderer")
            model_name = device_elem.find('{%s}modelName' % ns)
            if model_name is not None and model_name.text != "Renderer":
                model = model_name.text

        # Prefer ethernet MAC, fallback to wifi MAC
        if not mac:
            mac = mac_eth or mac_wifi

        # Format MAC address with colons if needed
        if mac and ':' not in mac and len(mac) == 12:
            mac = ':'.join(mac[i:i+2] for i in range(0, 12, 2))

        # Check for Vidaa support - only consider devices with vidaa_support=1
        vidaa_support = raw_data.get('vidaa_support', '0')
        if vidaa_support != '1':
            _LOGGER.debug("Device at %s does not have vidaa_support=1 (got %s), skipping",
                         ip, vidaa_support)
            return None

        device = DiscoveredTV(
            ip=ip,
            name=name,
            model=model,
            brand=raw_data.get('brand'),
            mac=mac,
            protocol_version=raw_data.get('transport_protocol'),
            source="probe",
            discovery_method="upnp_probe",
            raw_data=raw_data,
        )

        _LOGGER.info("Found Hisense TV at %s: %s (vidaa_support=%s)", ip, name, vidaa_support)
        return device

    except urllib.error.URLError as e:
        _LOGGER.debug("No response from %s: %s", ip, e)
    except ET.ParseError as e:
        _LOGGER.debug("Invalid XML from %s: %s", ip, e)
    except Exception as e:
        _LOGGER.debug("Error probing %s: %s", ip, e)

    return None


def discover_all(
    timeout: float = 5.0,
    interface: Optional[str] = None,
    methods: Optional[List[str]] = None,
) -> Dict[str, DiscoveredTV]:
    """Run multiple discovery methods and merge results.

    Args:
        timeout: Timeout for each discovery method in seconds.
        interface: Interface IP to bind to (e.g., "10.0.0.50").
        methods: List of methods to use: ["ssdp", "ssdp_listen", "udp"].
            If None, uses ["ssdp", "udp"] (active methods only).

    Returns:
        Dictionary mapping IP addresses to DiscoveredTV objects.
    """
    if methods is None:
        methods = ["ssdp", "udp"]

    _LOGGER.debug("Starting combined discovery with methods: %s", methods)

    found_devices: Dict[str, DiscoveredTV] = {}

    if "ssdp" in methods:
        devices = discover_ssdp(timeout=timeout, interface=interface)
        found_devices.update(devices)

    if "ssdp_listen" in methods:
        devices = listen_ssdp(timeout=timeout, interface=interface)
        # Merge, preferring existing entries
        for ip, device in devices.items():
            if ip not in found_devices:
                found_devices[ip] = device

    if "udp" in methods:
        devices = discover_udp(timeout=timeout, interface=interface)
        # Merge, preferring existing entries
        for ip, device in devices.items():
            if ip not in found_devices:
                found_devices[ip] = device

    _LOGGER.info("Combined discovery complete, found %d device(s)", len(found_devices))
    return found_devices
