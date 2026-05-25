"""Client-certificate resolution for mutual TLS.

The Vidaa client certificate and private key are **not** distributed with
pyvidaa — they are extracted from the official Vidaa mobile app and remain the
property of their owner. Users supply their own copy; see the "Obtaining the
client certificate" section of the README.

Resolution precedence (first existing pair wins):

1. Explicit ``certfile`` / ``keyfile`` arguments.
2. ``$PYVIDAA_CERT_DIR`` environment variable.
3. The standard user location ``~/.config/pyvidaa/certs/``.
4. A repo-local ``./certs/`` directory next to the package (editable installs).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

from .config.constants import DEFAULT_CERT_FILENAME, DEFAULT_KEY_FILENAME

ENV_CERT_DIR = "PYVIDAA_CERT_DIR"

# Standard per-user location, consistent with the config search paths.
USER_CERT_DIR = Path.home() / ".config" / "pyvidaa" / "certs"
# Legacy location for editable/source checkouts (repo_root/certs). Resolves to a
# non-existent site-packages/certs for installed wheels, where it simply misses.
_DEV_CERT_DIR = Path(__file__).resolve().parent.parent / "certs"

MISSING_CERT_HELP = (
    "Vidaa client certificate not found. pyvidaa does not ship the certificate; "
    f"place '{DEFAULT_CERT_FILENAME}' and '{DEFAULT_KEY_FILENAME}' in "
    f"{USER_CERT_DIR} (or set ${ENV_CERT_DIR}, or pass certfile/keyfile). "
    "See the README section 'Obtaining the client certificate'."
)


def cert_search_dirs() -> List[Path]:
    """Return the directories searched for the client cert, in priority order."""
    dirs: List[Path] = []
    env = os.environ.get(ENV_CERT_DIR)
    if env:
        dirs.append(Path(env).expanduser())
    dirs.append(USER_CERT_DIR)
    dirs.append(_DEV_CERT_DIR)
    return dirs


def resolve_client_certs(
    certfile: Optional[str] = None,
    keyfile: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """Locate the client certificate/key pair.

    Returns ``(certfile, keyfile)`` as strings if a readable pair is found,
    otherwise ``None``. Mutual TLS is required only by some protocol versions,
    so callers decide whether a missing pair is fatal.
    """
    if certfile and keyfile:
        if os.path.isfile(certfile) and os.path.isfile(keyfile):
            return str(certfile), str(keyfile)
        return None

    for directory in cert_search_dirs():
        cert = directory / DEFAULT_CERT_FILENAME
        key = directory / DEFAULT_KEY_FILENAME
        if cert.is_file() and key.is_file():
            return str(cert), str(key)
    return None
