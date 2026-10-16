from __future__ import annotations

import argparse
import logging
import sys

from . import __version__, config, logging_setup
from .app import Exporter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nifi-exporter", description="Prometheus exporter for Apache NiFi 2.x"
    )
    parser.add_argument("-c", "--config", help="path to YAML config (env overrides apply)")
    parser.add_argument("--check-config", action="store_true", help="validate config and exit")
    parser.add_argument("--version", action="version", version=f"nifi-exporter {__version__}")
    args = parser.parse_args(argv)

    try:
        cfg = config.load(args.config)
    except (config.ConfigError, OSError, ValueError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    if args.check_config:
        print("config ok")
        return 0

    srv = cfg.server
    logging_setup.configure(
        srv.log_level, srv.log_format, srv.log_file, srv.log_max_size, srv.log_backups
    )
    log = logging.getLogger("nifi_exporter")
    log.info("starting nifi-exporter", extra={"version": __version__})
    Exporter(cfg).run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
