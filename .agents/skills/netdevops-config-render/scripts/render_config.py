"""Render a Jinja2 network config template using a YAML vars file.

StrictUndefined is on by default — missing vars fail loudly.

Usage:
    python render_config.py \\
        --templates templates \\
        --vars inventories/r1.yaml \\
        --template bgp.j2 \\
        --out rendered/r1/bgp.conf
"""

from __future__ import annotations

import argparse
import difflib
import importlib
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateError,
    UndefinedError,
)


def load_vars(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected mapping at top level, got {type(data).__name__}")
    return data


def maybe_validate(vars_data: dict[str, Any], spec: str) -> None:
    """Validate vars against a pydantic model. spec format: 'module:ModelName'."""
    if not spec:
        return
    module_name, model_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    model = getattr(module, model_name)
    model.model_validate(vars_data)


def render_template(
    templates_dir: Path,
    template_name: str,
    vars_data: dict[str, Any],
    strict: bool,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined if strict else None,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_name)
    return template.render(**vars_data)


def unified_diff(expected: str, actual: str, label: str) -> str:
    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile=f"current/{label}",
        tofile=f"rendered/{label}",
    )
    return "".join(diff)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", required=True, type=Path)
    parser.add_argument("--vars", required=True, type=Path)
    parser.add_argument("--template", required=True, help="Template name relative to --templates")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--diff", type=Path, default=None, help="Compare rendered output to this file")
    parser.add_argument("--strict-diff", action="store_true", help="Exit 4 if diff is non-empty")
    parser.add_argument("--validate", default=None, help="pydantic spec: 'module:ModelName'")
    parser.add_argument("--no-strict", action="store_true", help="Disable StrictUndefined (not recommended)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        vars_data = load_vars(args.vars)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"vars load error: {exc}", file=sys.stderr)
        return 2

    try:
        maybe_validate(vars_data, args.validate)
    except Exception as exc:  # pydantic.ValidationError and friends
        print(f"validation error: {exc}", file=sys.stderr)
        return 2

    try:
        rendered = render_template(
            templates_dir=args.templates,
            template_name=args.template,
            vars_data=vars_data,
            strict=not args.no_strict,
        )
    except UndefinedError as exc:
        print(f"render error (undefined var): {exc}", file=sys.stderr)
        return 3
    except TemplateError as exc:
        print(f"render error: {exc}", file=sys.stderr)
        return 3

    if args.diff:
        current = args.diff.read_text(encoding="utf-8")
        diff_text = unified_diff(current, rendered, label=args.template)
        if diff_text:
            sys.stdout.write(diff_text)
            if args.strict_diff:
                return 4
        else:
            print("no diff", file=sys.stderr)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
