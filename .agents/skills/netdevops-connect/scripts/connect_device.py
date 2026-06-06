"""Open a session to a network device, run a command, return structured output.

Usage:
    python connect_device.py --host 10.0.0.1 --device-type cisco_ios \\
        --command "show version" --use-textfsm

Reads credentials from NETDEV_USER / NETDEV_PASSWORD env vars.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

logger = logging.getLogger("netdevops.connect")


def build_device_dict(args: argparse.Namespace) -> dict[str, Any]:
    """Compose the device dict netmiko expects."""
    password = os.environ.get("NETDEV_PASSWORD")
    if not password:
        raise SystemExit("NETDEV_PASSWORD env var is required")

    return {
        "host": args.host,
        "device_type": args.device_type,
        "username": os.environ.get("NETDEV_USER", "netops"),
        "password": password,
        "port": args.port,
        "timeout": args.timeout,
        "banner_timeout": args.banner_timeout,
        "auth_timeout": args.auth_timeout,
        "session_log": args.session_log,
    }


def run_command(
    device: dict[str, Any],
    command: str,
    use_textfsm: bool,
    read_timeout: int,
) -> Any:
    """Open a session, run a command, close it. Return parsed result."""
    try:
        with ConnectHandler(**device) as conn:
            logger.info("connected", extra={"host": device["host"]})
            return conn.send_command(
                command_string=command,
                use_textfsm=use_textfsm,
                read_timeout=read_timeout,
            )
    except (NetmikoTimeoutException, NetmikoAuthenticationException):
        logger.exception("connection failure", extra={"host": device["host"]})
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Device IP or FQDN")
    parser.add_argument(
        "--device-type",
        required=True,
        help="netmiko device_type (e.g. cisco_ios, arista_eos, juniper_junos)",
    )
    parser.add_argument("--command", required=True, help="Command to execute")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--banner-timeout", type=int, default=15)
    parser.add_argument("--auth-timeout", type=int, default=10)
    parser.add_argument("--read-timeout", type=int, default=60)
    parser.add_argument("--use-textfsm", action="store_true")
    parser.add_argument("--session-log", default=None)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )


def main() -> int:
    args = parse_args()
    configure_logging(args.log_level)
    device = build_device_dict(args)
    result = run_command(
        device=device,
        command=args.command,
        use_textfsm=args.use_textfsm,
        read_timeout=args.read_timeout,
    )
    if isinstance(result, list):
        json.dump(result, sys.stdout, indent=2, default=str)
    else:
        sys.stdout.write(str(result))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
