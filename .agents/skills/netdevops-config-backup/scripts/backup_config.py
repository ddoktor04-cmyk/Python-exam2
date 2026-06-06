"""Back up running and (optionally) startup configs from a list of devices.

Usage:
    python backup_config.py --inventory inventories/devices.yaml --out backups \\
        --with-startup --git
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoException

logger = logging.getLogger("netdevops.backup")


def load_inventory(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "hosts" in data:
        hosts = data["hosts"]
    elif isinstance(data, list):
        hosts = data
    else:
        raise ValueError("inventory must be a list or {'hosts': [...]}")
    for entry in hosts:
        if "host" not in entry or "device_type" not in entry:
            raise ValueError(f"inventory entry missing host/device_type: {entry}")
    return hosts


def build_device_dict(entry: dict[str, Any]) -> dict[str, Any]:
    password = os.environ.get("NETDEV_PASSWORD")
    if not password:
        raise SystemExit("NETDEV_PASSWORD env var is required")
    return {
        "host": entry["host"],
        "hostname": entry.get("hostname", entry["host"]),
        "device_type": entry["device_type"],
        "username": os.environ.get("NETDEV_USER", "netops"),
        "password": password,
        "port": entry.get("port", 22),
        "timeout": entry.get("timeout", 60),
        "session_timeout": 120,
    }


def normalize_config(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and lines[-1].strip() in {"end", "}", "EOF"}:
        lines.pop()
    return "\n".join(lines).rstrip() + "\n"


def fetch_config(device: dict[str, Any], with_startup: bool) -> dict[str, str]:
    out: dict[str, str] = {}
    commands = ["show running-config"]
    if with_startup:
        commands.append("show startup-config")
    try:
        with ConnectHandler(**device) as conn:
            for cmd in commands:
                label = "startup" if "startup" in cmd else "running"
                out[label] = normalize_config(conn.send_command(cmd, read_timeout=120))
    except NetmikoException as exc:
        logger.exception("fetch failed", extra={"host": device["host"]})
        out["_error"] = str(exc)
    return out


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_outputs(
    out_root: Path,
    device: dict[str, Any],
    configs: dict[str, str],
    timestamp: str,
) -> dict[str, str]:
    host_dir = out_root / device["hostname"] / timestamp
    host_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    if "_error" in configs:
        (host_dir / "ERROR.txt").write_text(configs["_error"], encoding="utf-8")
        return written
    for label, text in configs.items():
        path = host_dir / f"{label}.conf"
        path.write_text(text, encoding="utf-8")
        written[str(path)] = sha256_text(text)
    return written


def git_commit(out_root: Path, message: str, push: bool, remote: str) -> str | None:
    if not (out_root / ".git").exists():
        logger.warning("no git repo at %s, skipping commit", out_root)
        return None
    subprocess.run(["git", "-C", str(out_root), "add", "-A"], check=True)
    diff = subprocess.run(
        ["git", "-C", str(out_root), "diff", "--cached", "--quiet"],
        check=False,
    )
    if diff.returncode == 0:
        logger.info("no changes to commit")
        return None
    subprocess.run(["git", "-C", str(out_root), "commit", "-m", message], check=True)
    sha = subprocess.run(
        ["git", "-C", str(out_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if push:
        subprocess.run(["git", "-C", str(out_root), "push", remote], check=True)
    return sha


def run_inventory(
    inventory: list[dict[str, Any]],
    out_root: Path,
    with_startup: bool,
    concurrency: int,
) -> list[tuple[str, str, dict[str, str]]]:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    results: list[tuple[str, str, dict[str, str]]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(
                lambda e=entry: (
                    e.get("hostname", e["host"]),
                    timestamp,
                    fetch_config(build_device_dict(e), with_startup),
                )
            ): entry
            for entry in inventory
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                hostname, ts, configs = fut.result()
            except Exception as exc:
                logger.exception("worker failed: %s", exc)
                continue
            device = futures[fut]
            written = write_outputs(out_root, device, configs, ts)
            results.append((hostname, ts, written))
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("backups"))
    parser.add_argument("--with-startup", action="store_true")
    parser.add_argument("--git", action="store_true")
    parser.add_argument("--git-remote", default="origin")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--concurrency", type=int, default=10)
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
    try:
        inventory = load_inventory(args.inventory)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"inventory error: {exc}", file=sys.stderr)
        return 2

    results = run_inventory(
        inventory=inventory,
        out_root=args.out,
        with_startup=args.with_startup,
        concurrency=args.concurrency,
    )

    if not results:
        print("no devices backed up", file=sys.stderr)
        return 1

    print(f"backed up {len(results)} devices at {results[0][1]}")
    for hostname, _, _ in sorted(results):
        print(f"  - {hostname}")

    if args.git:
        hostnames = ",".join(sorted({h for h, _, _ in results}))
        sha = git_commit(
            out_root=args.out,
            message=f"backup: {results[0][1]} {hostnames}",
            push=args.push,
            remote=args.git_remote,
        )
        if sha:
            print(f"committed {sha[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
