"""Generate and bulk-insert synthetic rows into a SQL Server table.

Introspects the target table's columns and maps each to a faker
provider by column name + SQL type. See SKILL.md for the mapping rules.

Usage:
    python bulk_seed.py --database SuperCompany --table Users --rows 1000
    python bulk_seed.py --database SuperCompany --table Users --rows 5000 --truncate
    python bulk_seed.py --database SuperCompany --table Users --rows 100 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import pymssql
import yaml
from faker import Faker

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

NAME_PROVIDERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'^(id|guid|uuid)$', re.I), "uuid"),
    (re.compile(r'^(first_?name|fname|given_?name)$', re.I), "first_name"),
    (re.compile(r'^(last_?name|lname|surname|family_?name)$', re.I), "last_name"),
    (re.compile(r'^(full_?name|display_?name)$', re.I), "name"),
    (re.compile(r'^name$', re.I), "first_name"),
    (re.compile(r'^(e?_?mail|email)$', re.I), "email"),
    (re.compile(r'^(phone|tel|mobile|msisdn)$', re.I), "phone_number"),
    (re.compile(r'^country$', re.I), "country"),
    (re.compile(r'^(city|town|locality)$', re.I), "city"),
    (re.compile(r'^(street|address|addr)$', re.I), "street_address"),
    (re.compile(r'^(zip|zipcode|postcode|postal_?code)$', re.I), "postcode"),
    (re.compile(r'^(company|organization|org)$', re.I), "company"),
    (re.compile(r'^(username|login|user_?name)$', re.I), "user_name"),
    (re.compile(r'^(salary|amount|price|cost)$', re.I), "salary"),
    (re.compile(r'^age$', re.I), "age"),
    (re.compile(r'^(created_?at|updated_?at|modified_?at)$', re.I), "datetime"),
    (re.compile(r'^(dob|birth_?date|birthday)$', re.I), "date_of_birth"),
]

INT_RANGE: dict[str, tuple[int, int]] = {
    "salary": (25_000, 180_000),
    "age": (18, 80),
}
DEFAULT_INT_RANGE = (1, 100_000)


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


def introspect(conn: pymssql.Connection, schema: str, table: str) -> list[dict[str, Any]]:
    full = f"[{schema}].[{table}]"
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                c.column_id, c.name, tp.name AS type, c.max_length, c.precision,
                c.scale, c.is_nullable, c.is_identity, c.is_computed
            FROM sys.columns c
            JOIN sys.types tp ON c.user_type_id = tp.user_type_id
            WHERE c.object_id = OBJECT_ID(%s)
            ORDER BY c.column_id
        """, (full,))
        rows = cur.fetchall()
    if not rows:
        raise SystemExit(f"table not found: {full}")
    cols = ["column_id", "name", "type", "max_length", "precision", "scale",
            "is_nullable", "is_identity", "is_computed"]
    return [dict(zip(cols, r)) for r in rows]


def resolve_provider(
    col: dict[str, Any],
    fake: Faker,
    custom: dict[str, str] | None = None,
) -> tuple[Callable[[], Any] | None, str]:
    """Return (generator, label). generator is None if column should be skipped."""
    if col["is_identity"] or col["is_computed"]:
        return None, "skip"
    name = col["name"]
    sql_type = col["type"].lower()
    if custom and name in custom:
        return _provider_from_name(custom[name], fake), f"custom:{custom[name]}"

    for pattern, provider in NAME_PROVIDERS:
        if pattern.match(name):
            return _provider_from_name(provider, fake), f"name:{provider}"

    return _provider_from_type(sql_type, col, fake), f"type:{sql_type}"


def _provider_from_name(provider: str, fake: Faker) -> Callable[[], Any]:
    if provider == "uuid":
        return lambda: fake.uuid4()
    if provider == "salary":
        lo, hi = INT_RANGE["salary"]
        return lambda: fake.random_int(min=lo, max=hi, step=1_000)
    if provider == "age":
        lo, hi = INT_RANGE["age"]
        return lambda: fake.random_int(min=lo, max=hi)
    method = getattr(fake, provider, None)
    if method is None:
        return lambda: fake.word()
    return method


def _provider_from_type(
    sql_type: str,
    col: dict[str, Any],
    fake: Faker,
) -> Callable[[], Any]:
    if sql_type == "uniqueidentifier":
        return lambda: fake.uuid4()
    if sql_type in {"int", "bigint", "smallint", "tinyint"}:
        lo, hi = DEFAULT_INT_RANGE
        return lambda: fake.random_int(min=lo, max=hi)
    if sql_type in {"decimal", "numeric", "money", "smallmoney"}:
        return lambda: fake.pydecimal(
            min_value=0, max_value=10_000,
            right_digits=min(col.get("scale") or 2, 6),
        )
    if sql_type in {"float", "real"}:
        return lambda: fake.pyfloat(min_value=0, max_value=10_000)
    if sql_type == "bit":
        return lambda: fake.boolean()
    if sql_type == "date":
        return lambda: fake.date_object()
    if sql_type in {"datetime", "datetime2", "smalldatetime"}:
        return lambda: fake.date_time_this_decade()
    if sql_type in {"time"}:
        return lambda: fake.time_object()
    if sql_type in {"varchar", "nvarchar", "char", "nchar"}:
        max_len = col.get("max_length") or -1
        cap = min(max_len, 200) if max_len > 0 else 200
        return lambda c=cap: fake.text(max_nb_chars=c).replace("\n", " ")[:c]
    if sql_type in {"text", "ntext"}:
        return lambda: fake.text(max_nb_chars=200).replace("\n", " ")
    if sql_type in {"binary", "varbinary"}:
        return lambda: fake.binary(length=16)
    return None


def generate_rows(
    n: int,
    plan: list[tuple[dict[str, Any], Callable[[], Any] | None, str]],
    fake: Faker,
    null_rate: float,
) -> list[tuple]:
    rows: list[tuple] = []
    for _ in range(n):
        values: list[Any] = []
        for col, gen, _label in plan:
            if gen is None:
                values.append(None)
            elif col["is_nullable"] and fake.random.random() < null_rate:
                values.append(None)
            else:
                values.append(gen())
        rows.append(tuple(values))
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--schema", default="dbo")
    parser.add_argument("--table", required=True)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--truncate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--column-map", type=Path, default=None,
                        help="YAML mapping {column: faker_provider}")
    parser.add_argument("--null-rate", type=float, default=0.1)
    parser.add_argument("--allow-no-pk", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )


def main() -> int:
    configure_logging()
    args = parse_args()
    if args.rows <= 0:
        print("--rows must be > 0", file=sys.stderr)
        return 2

    env = parse_env(find_env())
    fake = Faker()
    Faker.seed(args.seed)

    custom: dict[str, str] = {}
    if args.column_map:
        custom = yaml.safe_load(args.column_map.read_text(encoding="utf-8")) or {}

    conn = pymssql.connect(
        server=env["DB_IP"],
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
        database=args.database,
        login_timeout=10,
        timeout=args.timeout,
    )
    try:
        cols_meta = introspect(conn, args.schema, args.table)
        plan: list[tuple[dict[str, Any], Callable[[], Any] | None, str]] = []
        unmapped: list[str] = []
        for col in cols_meta:
            gen, label = resolve_provider(col, fake, custom)
            plan.append((col, gen, label))
            if gen is None and not (col["is_identity"] or col["is_computed"]):
                if not col["is_nullable"]:
                    unmapped.append(col["name"])

        insertable = [p for p in plan if p[1] is not None]
        insert_cols = [p[0]["name"] for p in insertable]
        logger.info(
            "resolved plan",
            extra={
                "table": f"{args.schema}.{args.table}",
                "rows": args.rows,
                "skip": [p[0]["name"] for p in plan if p[1] is None],
                "insert": insert_cols,
            },
        )
        print("Plan:")
        for col, _, label in plan:
            print(f"  {col['name']:<24}  {col['type']:<18}  {label}")

        if unmapped:
            print(f"\nUnmapped NOT NULL columns: {unmapped}", file=sys.stderr)
            print("Provide a --column-map YAML or mark the columns nullable.", file=sys.stderr)
            return 4

        has_pk = any(
            col_meta.get("is_identity")
            for col_meta, _, _ in plan[:1]
        ) or _has_primary_key(conn, args.schema, args.table)
        if not has_pk and not args.allow_no_pk:
            print("table has no primary key / identity; pass --allow-no-pk to override", file=sys.stderr)
            return 4

        if args.dry_run:
            print("\nDRY RUN — no inserts")
            return 0

        if args.truncate:
            logger.info("truncating", extra={"table": f"{args.schema}.{args.table}"})
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE [{args.schema}].[{args.table}]")
            conn.commit()

        placeholders = ", ".join(["%s"] * len(insert_cols))
        col_list = ", ".join(f"[{c}]" for c in insert_cols)
        insert_sql = f"INSERT INTO [{args.schema}].[{args.table}] ({col_list}) VALUES ({placeholders})"

        logger.info("generating rows", extra={"count": args.rows})
        start = time.monotonic()
        inserted = 0
        for offset in range(0, args.rows, args.batch_size):
            batch_n = min(args.batch_size, args.rows - offset)
            batch_rows = generate_rows(batch_n, insertable, fake, args.null_rate)
            with conn.cursor() as cur:
                cur.executemany(insert_sql, batch_rows)
            conn.commit()
            inserted += batch_n
            logger.info("inserted", extra={"progress": inserted, "total": args.rows})
        elapsed = time.monotonic() - start
        print(f"\nDone. {inserted} rows in {elapsed:.2f}s ({(inserted / max(elapsed, 0.01)):.0f} rows/s)")
        return 0
    except pymssql.Error as exc:
        logger.exception("seed failed")
        print(f"FAILED: {exc}", file=sys.stderr)
        return 5
    finally:
        conn.close()


def _has_primary_key(conn: pymssql.Connection, schema: str, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1
            FROM sys.key_constraints
            WHERE parent_object_id = OBJECT_ID(%s) AND type = 'PK'
        """, (f"[{schema}].[{table}]",))
        return cur.fetchone() is not None


if __name__ == "__main__":
    raise SystemExit(main())
