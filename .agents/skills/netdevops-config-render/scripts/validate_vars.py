"""Standalone validator: run a pydantic model against a YAML vars file.

Useful in CI before any render step.

Usage:
    python validate_vars.py --vars inventories/r1.yaml --spec schemas.r1:HostVars
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vars", required=True, type=Path)
    parser.add_argument("--spec", required=True, help="'module.path:ModelName'")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if ":" not in args.spec:
        print(f"invalid --spec, expected 'module:Model': {args.spec}", file=sys.stderr)
        return 2

    module_name, model_name = args.spec.split(":", 1)
    try:
        data = yaml.safe_load(args.vars.read_text(encoding="utf-8"))
        module = importlib.import_module(module_name)
        model = getattr(module, model_name)
        model.model_validate(data)
    except Exception as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
