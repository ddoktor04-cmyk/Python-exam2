"""Run a single SQL statement on SQL Server and return the result.

Read-only by default. INSERT/UPDATE/DELETE/DDL require --allow-write.

Usage:
    python run_query.py --database SuperCompany \\
        --query "SELECT TOP 5 * FROM dbo.Users"
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pymssql

logger = logging.getLogger("netdevops.mssql")
QUOTE_RE = re.compile(r'^\s*([A-Z0-9_]+)\s*=\s*"?([^"\n]*)"?\s*$', re.IGNORECASE)


def find_env() -> Path:
    cwd = Path.cwd().resolve()
    for start in (Path(__file__).resolve().parent, cwd):
        for parent in (start, *start.parents):
            candidate = parent / ".env"
            if candidate.exists():
                return candidate
    raise SystemExit(".env not found in script dir, cwd, or any parent")
READ_ONLY_KEYWORDS = {"SELECT", "WITH", "PRINT"}
WRITE_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "MERGE",
    "DROP", "CREATE", "ALTER", "TRUNCATE",
    "GRANT", "REVOKE", "BULK",
    "OPENROWSET", "OPENDATASOURCE",
    "EXEC", "EXECUTE",
}


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        raise SystemExit(f".env not found at {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = QUOTE_RE.match(line)
        if m:
            out[m.group(1).upper()] = m.group(2)
    for key in ("DB_IP", "DB_USER", "DB_PASSWORD"):
        if key not in out:
            raise SystemExit(f"missing {key} in {path}")
    return out


def first_keyword(sql: str) -> str:
    cleaned = re.sub(r'--[^\n]*', '', sql)
    cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
    m = re.search(r'[A-Za-z_]+', cleaned.lstrip())
    return m.group(0).upper() if m else ""


def check_read_only(sql: str, allow_write: bool) -> int:
    kw = first_keyword(sql)
    if not kw:
        return 0
    if kw in READ_ONLY_KEYWORDS:
        return 0
    if kw in WRITE_KEYWORDS and not allow_write:
        print(
            f"refusing: {kw} is a write operation; pass --allow-write to run it",
            file=sys.stderr,
        )
        return 3
    return 0


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def render_json(cols: list[str], rows: list[tuple]) -> str:
    data = [dict(zip(cols, r)) for r in rows]
    return json.dumps(data, indent=2, ensure_ascii=False, default=json_default)


def render_csv(cols: list[str], rows: list[tuple]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(cols)
    for r in rows:
        writer.writerow([
            "" if v is None else (
                v.isoformat() if isinstance(v, (datetime, date)) else
                float(v) if isinstance(v, Decimal) else
                v
            )
            for v in r
        ])
    return buf.getvalue()


def render_md(cols: list[str], rows: list[tuple]) -> str:
    out = io.StringIO()
    out.write("| " + " | ".join(cols) + " |\n")
    out.write("|" + "|".join("---" for _ in cols) + "|\n")
    for r in rows:
        cells = []
        for v in r:
            if v is None:
                cells.append("")
            elif isinstance(v, (datetime, date)):
                cells.append(v.isoformat())
            elif isinstance(v, Decimal):
                cells.append(f"{float(v):g}")
            else:
                cells.append(str(v).replace("|", "\\|").replace("\n", " "))
        out.write("| " + " | ".join(cells) + " |\n")
    return out.getvalue()


def render_text(cols: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "(no rows)\n"
    widths = [len(c) for c in cols]
    str_rows = []
    for r in rows:
        cells = []
        for v in r:
            if v is None:
                s = ""
            elif isinstance(v, (datetime, date)):
                s = v.isoformat()
            elif isinstance(v, Decimal):
                s = f"{float(v):g}"
            else:
                s = str(v)
            cells.append(s)
        for i, c in enumerate(cells):
            widths[i] = max(widths[i], len(c))
        str_rows.append(cells)
    header = "  ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
    sep = "  ".join("-" * w for w in widths)
    lines = [header, sep]
    for cells in str_rows:
        lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(cells)))
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="SQL statement to run")
    parser.add_argument("--database", default="master")
    parser.add_argument("--format", choices=["text", "json", "csv", "md"], default="text")
    parser.add_argument("--max-rows", type=int, default=10_000)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--save", type=Path, default=None)
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--show-affected", action="store_true")
    return parser.parse_args()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )


def main() -> int:
    configure_logging()
    args = parse_args()
    if rc := check_read_only(args.query, args.allow_write):
        return rc
    env = parse_env(find_env())
    start = time.monotonic()
    conn = pymssql.connect(
        server=env["DB_IP"],
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
        database=args.database,
        login_timeout=10,
        timeout=args.timeout,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SET NOCOUNT ON")
            cur.execute(args.query)
            if cur.description is None:
                if args.show_affected:
                    print(f"affected rows: {cur.rowcount}", file=sys.stderr)
                elapsed = time.monotonic() - start
                print(f"ok ({elapsed:.2f}s, {cur.rowcount} row(s) affected)", file=sys.stderr)
                return 0
            cols = [c[0] for c in cur.description]
            rows = cur.fetchmany(args.max_rows + 1)
    except pymssql.Error as exc:
        logger.exception("query failed")
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    truncated = len(rows) > args.max_rows
    if truncated:
        rows = rows[: args.max_rows]

    renderers = {
        "text": render_text,
        "json": render_json,
        "csv": render_csv,
        "md": render_md,
    }
    output = renderers[args.format](cols, rows)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(output, encoding="utf-8")
        print(f"saved to {args.save}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    elapsed = time.monotonic() - start
    note = f"{len(rows)} row(s) in {elapsed:.2f}s"
    if truncated:
        note += f" (truncated to {args.max_rows})"
    print(f"\n{note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
