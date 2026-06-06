"""Read-only SQL Server schema inspector.

Sub-commands:
    databases
    tables    --database <name> [--schema dbo] [--exact]
    columns   --database <name> --table <name> [--schema dbo]
    keys      --database <name> --table <name> [--schema dbo]
    indexes   --database <name> --table <name> [--schema dbo]

Reads DB_IP / DB_USER / DB_PASSWORD from .env in the project root.
Output: fixed-width table by default; --json for machine-readable JSON.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

import pymssql

logger = logging.getLogger("netdevops.mssql")
QUOTE_RE = re.compile(r'^\s*([A-Z0-9_]+)\s*=\s*"?([^"\n]*)"?\s*$', re.IGNORECASE)

SYSTEM_SCHEMAS = ("sys", "INFORMATION_SCHEMA", "guest")


def find_env() -> Path:
    cwd = Path.cwd().resolve()
    for start in (Path(__file__).resolve().parent, cwd):
        for parent in (start, *start.parents):
            candidate = parent / ".env"
            if candidate.exists():
                return candidate
    raise SystemExit(".env not found in script dir, cwd, or any parent")


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


def connect(env: dict[str, str], database: str | None = None) -> pymssql.Connection:
    return pymssql.connect(
        server=env["DB_IP"],
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
        database=database or env.get("DB_NAME", "master"),
        login_timeout=10,
        timeout=10,
    )


def fetch_all(conn: pymssql.Connection, sql: str, params: tuple = ()) -> tuple[list[str], list[tuple]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
    return cols, rows


def print_table(cols: list[str], rows: list[tuple], col_widths: dict[str, int] | None = None) -> None:
    if not rows:
        print("(no rows)")
        return
    widths = {}
    for c in cols:
        cell_widths = [len(str(c))] + [len(str(r[cols.index(c)])) for r in rows]
        widths[c] = max(cell_widths)
    if col_widths:
        widths.update(col_widths)
    header = "  ".join(f"{c:<{widths[c]}}" for c in cols)
    print(header)
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(f"{str(r[cols.index(c)]):<{widths[c]}}" for c in cols))


def cmd_databases(args: argparse.Namespace, env: dict[str, str]) -> int:
    with connect(env, "master") as conn:
        cols, rows = fetch_all(conn, """
            SELECT
                d.name,
                d.database_id,
                d.state_desc,
                d.recovery_model_desc,
                d.create_date
            FROM sys.databases d
            ORDER BY d.database_id
        """)
    if args.json:
        json.dump([dict(zip(cols, r)) for r in rows], sys.stdout, indent=2, default=str)
        print()
        return 0
    print_table(
        cols,
        [(r[0], r[1], r[2], r[3], r[4].strftime("%Y-%m-%d %H:%M:%S")) for r in rows],
        col_widths={cols[1]: 4},
    )
    print(f"\n{len(rows)} database(s)")
    return 0


def cmd_tables(args: argparse.Namespace, env: dict[str, str]) -> int:
    with connect(env, args.database) as conn:
        schema_filter = "" if args.include_system else (
            "AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')"
        )
        exact_clause = "" if args.exact else "p.rows"
        cols, rows = fetch_all(conn, f"""
            SELECT
                s.name          AS [schema],
                t.name          AS [table],
                {exact_clause} AS [rows],
                t.type_desc     AS [type],
                t.create_date   AS [created]
            FROM sys.tables t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            {"LEFT JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0,1)" if not args.exact else ""}
            WHERE 1=1 {schema_filter}
            ORDER BY s.name, t.name
        """)
    if args.exact:
        with connect(env, args.database) as conn:
            for i, r in enumerate(rows):
                with conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM "{r[0]}"."{r[1]}"')
                    (count,) = cur.fetchone()
                rows[i] = (r[0], r[1], count, r[2], r[3])
    if args.json:
        json.dump([dict(zip(cols, r)) for r in rows], sys.stdout, indent=2, default=str)
        print()
        return 0
    print_table(
        cols,
        [(r[0], r[1], r[2], r[3], r[4].strftime("%Y-%m-%d %H:%M:%S")) for r in rows],
        col_widths={cols[0]: 8, cols[2]: 10, cols[3]: 12},
    )
    print(f"\n{len(rows)} table(s)")
    return 0


def cmd_columns(args: argparse.Namespace, env: dict[str, str]) -> int:
    with connect(env, args.database) as conn:
        cols, rows = fetch_all(conn, """
            SELECT
                c.column_id        AS [#],
                c.name             AS [column],
                tp.name            AS [type],
                c.max_length       AS [length],
                c.precision        AS [prec],
                c.scale            AS [scale],
                c.is_nullable      AS [null],
                c.is_identity      AS [identity],
                ISNULL(dc.definition, '') AS [default],
                c.collation_name   AS [collation]
            FROM sys.columns c
            JOIN sys.types tp ON c.user_type_id = tp.user_type_id
            LEFT JOIN sys.default_constraints dc
                ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
            WHERE c.object_id = OBJECT_ID(%s)
            ORDER BY c.column_id
        """, (f"[{args.schema}].[{args.table}]",))
    if not rows:
        print(f"table not found: {args.schema}.{args.table}")
        return 4
    if args.json:
        json.dump([dict(zip(cols, r)) for r in rows], sys.stdout, indent=2, default=str)
        print()
        return 0
    pretty = [
        (
            r[0], r[1], r[2],
            f"({r[4]},{r[5]})" if r[2] in ("decimal", "numeric") else (
                str(r[3]) if r[2] in ("varchar", "nvarchar", "char", "nchar", "binary", "varbinary") else ""
            ),
            "YES" if r[6] else "NO",
            "IDX" if r[7] else "",
            r[8][:30],
            r[9] or "",
        )
        for r in rows
    ]
    pretty_cols = ["#", "column", "type", "len/prec", "null", "id", "default", "collation"]
    print_table(pretty_cols, pretty, col_widths={"#": 3, "type": 12, "len/prec": 10, "id": 4, "default": 30})
    return 0


def cmd_keys(args: argparse.Namespace, env: dict[str, str]) -> int:
    with connect(env, args.database) as conn:
        cols, rows = fetch_all(conn, """
            SELECT
                kc.type_desc      AS [key_type],
                c.name            AS [column],
                i.is_primary_key  AS [pk],
                i.is_unique       AS [unique],
                OBJECT_NAME(fk.referenced_object_id) AS [ref_table],
                COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS [ref_column]
            FROM sys.key_constraints kc
            JOIN sys.indexes i ON kc.parent_object_id = i.object_id AND kc.unique_index_id = i.index_id
            JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
            JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            LEFT JOIN sys.foreign_key_columns fkc
                ON fkc.parent_object_id = c.object_id AND fkc.parent_column_id = c.column_id
            LEFT JOIN sys.foreign_keys fk
                ON fk.object_id = fkc.constraint_object_id
            WHERE kc.parent_object_id = OBJECT_ID(%s)
            ORDER BY i.is_primary_key DESC, kc.name, ic.key_ordinal
        """, (f"[{args.schema}].[{args.table}]",))
    if not rows:
        print(f"table not found or has no keys: {args.schema}.{args.table}")
        return 0
    if args.json:
        json.dump([dict(zip(cols, r)) for r in rows], sys.stdout, indent=2, default=str)
        print()
        return 0
    pretty_cols = ["key_type", "column", "pk", "unique", "ref_table", "ref_column"]
    print_table(pretty_cols, rows)
    return 0


def cmd_indexes(args: argparse.Namespace, env: dict[str, str]) -> int:
    with connect(env, args.database) as conn:
        cols, rows = fetch_all(conn, """
            SELECT
                i.name                 AS [index],
                i.type_desc            AS [type],
                i.is_unique            AS [unique],
                i.is_primary_key       AS [pk],
                STUFF((
                    SELECT ', ' + c.name + CASE WHEN ic.is_included_column = 1 THEN ' (inc)' ELSE '' END
                    FROM sys.index_columns ic
                    JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                    WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id
                    ORDER BY ic.key_ordinal
                    FOR XML PATH(''), TYPE
                ).value('.', 'nvarchar(max)'), 1, 2, '') AS [columns]
            FROM sys.indexes i
            WHERE i.object_id = OBJECT_ID(%s) AND i.is_hypothetical = 0
            ORDER BY i.is_primary_key DESC, i.name
        """, (f"[{args.schema}].[{args.table}]",))
    if not rows:
        print(f"table not found or has no indexes: {args.schema}.{args.table}")
        return 0
    if args.json:
        json.dump([dict(zip(cols, r)) for r in rows], sys.stdout, indent=2, default=str)
        print()
        return 0
    pretty_cols = ["index", "type", "unique", "pk", "columns"]
    print_table(pretty_cols, rows, col_widths={"type": 12, "unique": 7, "pk": 4})
    return 0


COMMANDS: dict[str, Callable[[argparse.Namespace, dict[str, str]], int]] = {
    "databases": cmd_databases,
    "tables": cmd_tables,
    "columns": cmd_columns,
    "keys": cmd_keys,
    "indexes": cmd_indexes,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-system", action="store_true", help="Include system schemas")
    parser.add_argument("--exact", action="store_true", help="Use exact row counts (slower)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_dbs = sub.add_parser("databases", help="List databases on the server")
    p_dbs.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    p_tables = sub.add_parser("tables", help="List tables in a database")
    p_tables.add_argument("--database", required=True)
    p_tables.add_argument("--schema", default="dbo")
    p_tables.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    p_columns = sub.add_parser("columns", help="List columns in a table")
    p_columns.add_argument("--database", required=True)
    p_columns.add_argument("--table", required=True)
    p_columns.add_argument("--schema", default="dbo")
    p_columns.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    p_keys = sub.add_parser("keys", help="List primary/foreign keys in a table")
    p_keys.add_argument("--database", required=True)
    p_keys.add_argument("--table", required=True)
    p_keys.add_argument("--schema", default="dbo")
    p_keys.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    p_idx = sub.add_parser("indexes", help="List indexes in a table")
    p_idx.add_argument("--database", required=True)
    p_idx.add_argument("--table", required=True)
    p_idx.add_argument("--schema", default="dbo")
    p_idx.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    return parser


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )


def main() -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    try:
        env = parse_env(find_env())
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    cmd = COMMANDS[args.command]
    try:
        return cmd(args, env)
    except pymssql.Error as exc:
        logger.exception("query failed")
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
