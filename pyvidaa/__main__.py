"""Entry point for ``python -m pyvidaa``.

Lets the CLI run straight from a source checkout - no install, no console
script - so edits take effect immediately:

    cd /path/to/pyvidaa
    .venv/bin/python -m pyvidaa --ip 192.168.1.50 sniff --seconds 60
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
