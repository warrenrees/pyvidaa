"""Protocol detection and authentication method selection for Hisense TVs.

Detects the transport protocol version from the TV's UPnP XML descriptor
and selects the appropriate authentication method.
"""

import logging
import re
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from enum import Enum
from typing import List, Optional

from .config import (
    PROTOCOL_MODERN_THRESHOLD,
    PROTOCOL_MIDDLE_THRESHOLD,
    UPNP_PORT,
    UPNP_PORTS,
)

_LOGGER = logging.getLogger(__name__)


class AuthMethod(Enum):
    """Authentication method based on transport protocol version."""
    LEGACY = "legacy"    # < 3000: no XOR username, old suffix
    MIDDLE = "middle"    # 3000-3285: XOR username, old suffix
    MODERN = "modern"    # >= 3290: XOR username, new suffix


def detect_protocol(
    host: str,
    port: Optional[int] = None,
    timeout: float = 5.0,
    retries: int = 2,
    retry_delay: float = 0.5,
) -> Optional[int]:
    """Detect transport protocol version from TV's UPnP XML descriptor.

    Fetches http://{host}:{port}/MediaServer/rendererdevicedesc.xml and
    extracts the transport_protocol value.

    Args:
        host: TV IP address or hostname
        port: HTTP port. If None (default), each candidate in UPNP_PORTS is
            tried in order (some VIDAA OS versions use 18400 instead of 38400).
        timeout: Request timeout in seconds
        retries: Extra attempts on transient network errors (these TVs
            intermittently drop off the network, e.g. EHOSTUNREACH)
        retry_delay: Seconds to wait between attempts

    Returns:
        Transport protocol version as integer, or None if detection fails
    """
    candidate_ports = [port] if port is not None else list(UPNP_PORTS)
    for candidate in candidate_ports:
        version = _detect_protocol_port(
            host, candidate, timeout, retries, retry_delay
        )
        if version is not None:
            return version
    return None


def _detect_protocol_port(
    host: str,
    port: int,
    timeout: float,
    retries: int,
    retry_delay: float,
) -> Optional[int]:
    """Detect the transport protocol from a single host:port descriptor."""
    url = f"http://{host}:{port}/MediaServer/rendererdevicedesc.xml"

    xml_content = None
    for attempt in range(retries + 1):
        try:
            _LOGGER.debug("Fetching protocol info from %s (attempt %d/%d)",
                          url, attempt + 1, retries + 1)
            request = urllib.request.Request(url)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                xml_content = response.read().decode('utf-8')
            break
        except urllib.error.URLError as e:
            if attempt < retries:
                _LOGGER.debug("Protocol fetch failed (%s), retrying...", e)
                time.sleep(retry_delay)
                continue
            _LOGGER.warning("Failed to fetch protocol info: %s", e)
            return None

    if xml_content is None:
        return None

    try:
        # Parse XML and find transport_protocol
        root = ET.fromstring(xml_content)

        # Method 1: Look for transport_protocol as XML element
        for elem in root.iter():
            if 'transport_protocol' in elem.tag.lower() or elem.tag.endswith('transport_protocol'):
                try:
                    protocol_version = int(elem.text.strip())
                    _LOGGER.info("Detected transport protocol: %d", protocol_version)
                    return protocol_version
                except (ValueError, AttributeError):
                    pass

        # Method 2: Look for transport_protocol in element text content (key=value format)
        # This handles the case where transport_protocol=XXXX is in modelDescription text
        for elem in root.iter():
            if elem.text:
                match = re.search(r'transport_protocol[=:]\s*(\d+)', elem.text, re.IGNORECASE)
                if match:
                    protocol_version = int(match.group(1))
                    _LOGGER.info("Detected transport protocol: %d (from text)", protocol_version)
                    return protocol_version

        # Method 3: Search raw XML content as fallback
        match = re.search(r'transport_protocol[=:]\s*(\d+)', xml_content, re.IGNORECASE)
        if match:
            protocol_version = int(match.group(1))
            _LOGGER.info("Detected transport protocol: %d (from raw XML)", protocol_version)
            return protocol_version

        _LOGGER.warning("transport_protocol not found in XML response")
        return None

    except ET.ParseError as e:
        _LOGGER.warning("Failed to parse XML response: %s", e)
        return None
    except Exception as e:
        _LOGGER.warning("Unexpected error detecting protocol: %s", e)
        return None


def get_auth_method(protocol_version: Optional[int]) -> AuthMethod:
    """Determine authentication method based on protocol version.

    Args:
        protocol_version: Transport protocol version, or None if unknown

    Returns:
        AuthMethod enum value
    """
    if protocol_version is None:
        # Default to modern when unknown (will fallback if needed)
        return AuthMethod.MODERN

    if protocol_version >= PROTOCOL_MODERN_THRESHOLD:
        return AuthMethod.MODERN
    elif protocol_version >= PROTOCOL_MIDDLE_THRESHOLD:
        return AuthMethod.MIDDLE
    else:
        return AuthMethod.LEGACY


def get_auth_method_order() -> List[AuthMethod]:
    """Get the order of authentication methods to try during fallback.

    Returns:
        List of AuthMethod values in order: MODERN, MIDDLE, LEGACY
    """
    return [AuthMethod.MODERN, AuthMethod.MIDDLE, AuthMethod.LEGACY]
