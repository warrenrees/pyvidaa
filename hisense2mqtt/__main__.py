#!/usr/bin/env python3
"""Entry point for hisense2mqtt."""

import argparse
import logging
import sys

from . import __version__
from .bridge import HisenseMQTTMultiBridge
from .config import expand_tv_configs, load_config


def validate_all(config: dict, scoped: list[dict]) -> list[str]:
    """Validate the broker and every configured TV with actionable messages."""
    errors = []
    if not config.get("mqtt", {}).get("host"):
        errors.append("mqtt.host is required")
    if not scoped:
        errors.append(
            "No TVs configured - add a 'tvs:' mapping (or legacy 'tv:' section)"
        )
    for sc in scoped:
        tv = sc.get("tv", {})
        host = tv.get("host")
        if not host:
            errors.append("A TV entry is missing 'host'")
        elif not tv.get("uuid"):
            errors.append(
                f"{host}: no paired UUID - pair it first with "
                f"'tv --ip {host} auth pair'"
            )
    return errors


def setup_logging(level: str = "INFO"):
    """Set up logging configuration."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Reduce noise from paho-mqtt
    logging.getLogger("paho").setLevel(logging.WARNING)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="hisense2mqtt",
        description="MQTT bridge for Hisense/Vidaa TV control",
    )
    parser.add_argument(
        "-c", "--config",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"hisense2mqtt {__version__}",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate config and exit",
    )

    args = parser.parse_args()

    # Load config
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Set up logging
    log_level = "DEBUG" if args.debug else config.get("options", {}).get("log_level", "INFO")
    setup_logging(log_level)

    logger = logging.getLogger(__name__)

    # Log config location
    config_path = config.get("_config_path", "defaults")
    logger.info(f"Loaded config from: {config_path}")

    # Expand to one scoped config per TV (supports multi-TV 'tvs:' and legacy 'tv:')
    scoped = expand_tv_configs(config)

    # Validate config
    errors = validate_all(config, scoped)
    if errors:
        for error in errors:
            logger.error(f"Config error: {error}")
        if args.validate:
            print("Configuration is INVALID")
        sys.exit(1)

    if args.validate:
        print("Configuration is valid")
        print(f"  MQTT Broker: {config['mqtt']['host']}:{config['mqtt']['port']}")
        print(f"  TVs: {len(scoped)}")
        for sc in scoped:
            tv = sc["tv"]
            print(f"    - {tv.get('name', 'Hisense TV')} @ {tv['host']}:{tv.get('port', 36669)}")
            print(f"        UUID: {tv.get('uuid')}  MAC: {tv.get('mac', 'not set')}")
        opts = config.get("options", {})
        print(f"  Poll Interval: {opts.get('poll_interval', 30)}s")
        print(f"  Discovery: {opts.get('discovery', True)}")
        print(f"  Wake-on-LAN: {opts.get('wake_on_lan', True)}")
        sys.exit(0)

    # Start bridge(s)
    logger.info(f"hisense2mqtt v{__version__} starting ({len(scoped)} TV(s))...")

    bridge = HisenseMQTTMultiBridge(config)

    try:
        bridge.run_forever()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
