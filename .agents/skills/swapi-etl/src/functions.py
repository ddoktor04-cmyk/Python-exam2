"""Discrete high-level functions for swapi-etl.

These are the public API of the swapi-etl skill: each function takes
`env` (a dict with DB_IP, DB_USER, DB_PASSWORD loaded from .env) plus
`db` (the target database name, default `Starwars`), and performs one
action end-to-end.

Used by:
  - the interactive menu in scripts/swapi_etl.py
  - the argparse CLI in scripts/swapi_etl.py
  - ad-hoc imports by other tools

Logging is emitted via the package logger (`etl_core.LOGGER_NAME`).
Stdout is reserved for data (rows, JSON, CSV); status lines go to
stderr.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pymssql

from . import etl_core as _c

# Re-export common bits so callers can `from src.functions import ...`
EXIT_OK = _c.EXIT_OK
EXIT_ENV = _c.EXIT_ENV
EXIT_SCHEMA = _c.EXIT_SCHEMA
EXIT_USAGE = _c.EXIT_USAGE
EXIT_RUNTIME = _c.EXIT_RUNTIME
RESOURCES = _c.RESOURCES
IMPORT_ORDER = _c.IMPORT_ORDER


def load_env() -> dict[str, str]:
    """Read .env from CWD or any parent directory."""
    return _c.load_env(_c.find_env())


def init_db(env: dict[str, str], db: str = "Starwars") -> int:
    """Create the database (if missing) and all 16 tables. Idempotent."""
    try:
        _c.ensure_database(env, db)
        conn = _c.connect(env, db)
    except (pymssql.Error, KeyError) as exc:
        print(f"init failed: {exc}", file=sys.stderr)
        return EXIT_ENV
    try:
        _c.ensure_schema(conn)
    finally:
        conn.close()
    print(f"OK database={db} tables={len(_c.DDL)}", file=sys.stderr)
    return EXIT_OK


def import_resource(env: dict[str, str], db: str, resource: str, *,
                    cache_dir: Path | str = ".cache/swapi",
                    cache_ttl: int = 3600, timeout: int = 30,
                    batch: int = 500, atomic: bool = False) -> dict[str, int]:
    """Import a single SWAPI resource into the Starwars DB.

    Returns a stats dict: inserted, updated, junctions, ok.
    Raises httpx.HTTPError or pymssql.Error on failure.
    """
    table = f"sw_{resource}"
    if table not in _c.MAIN_COLUMNS:
        raise ValueError(f"unknown resource: {resource}")
    cache_dir_p = Path(cache_dir)
    conn = _c.connect(env, db)
    try:
        with httpx.Client(timeout=timeout) as client:
            records = _c.fetch_collection(client, resource, _c.SWAPI_BASE,
                                           cache_dir_p, cache_ttl)
        if not records:
            _c.logger.warning("resource=%s returned 0 records", resource)
            return {"inserted": 0, "updated": 0, "junctions": 0, "ok": True}
        builder = _c.ROW_BUILDERS[table]
        ts = datetime.now(timezone.utc)
        rows = [builder(r, ts) for r in records]
        if atomic:
            conn.autocommit(False)
        inserted, updated = _c.merge_main_table(conn, table, rows)
        _c.logger.info("table=%s inserted=%d updated=%d",
                       table, inserted, updated)
        junctions: dict[str, set[tuple[str, str]]] = {}
        if resource in _c.JUNCTION_MAP:
            junctions = _c.collect_junctions(records, resource)
            for jt, pairs in junctions.items():
                if pairs:
                    _c.merge_junction(conn, jt, pairs)
                    _c.logger.info("junction=%s pairs=%d", jt, len(pairs))
        return {
            "inserted": inserted,
            "updated": updated,
            "junctions": sum(len(s) for s in junctions.values()),
            "ok": True,
        }
    finally:
        conn.close()


def _print_line(name: str, stats: dict[str, int]) -> None:
    print(
        f"{name:<10} inserted={stats['inserted']:>3}  "
        f"updated={stats['updated']:>3}  "
        f"junctions={stats['junctions']:>4}",
        file=sys.stderr,
    )


def import_planets(env, db="Starwars", **kwargs):
    s = import_resource(env, db, "planets", **kwargs); _print_line("planets", s); return s

def import_films(env, db="Starwars", **kwargs):
    s = import_resource(env, db, "films", **kwargs); _print_line("films", s); return s

def import_species(env, db="Starwars", **kwargs):
    s = import_resource(env, db, "species", **kwargs); _print_line("species", s); return s

def import_people(env, db="Starwars", **kwargs):
    s = import_resource(env, db, "people", **kwargs); _print_line("people", s); return s

def import_vehicles(env, db="Starwars", **kwargs):
    s = import_resource(env, db, "vehicles", **kwargs); _print_line("vehicles", s); return s

def import_starships(env, db="Starwars", **kwargs):
    s = import_resource(env, db, "starships", **kwargs); _print_line("starships", s); return s


def import_all(env, db: str = "Starwars", **kwargs) -> int:
    """Import all 6 resources in topological order."""
    for r in IMPORT_ORDER:
        try:
            import_resource(env, db, r, **kwargs)
        except (httpx.HTTPError, pymssql.Error) as exc:
            print(f"FAILED {r}: {exc}", file=sys.stderr)
            return EXIT_RUNTIME
    return EXIT_OK


def show_stats(env, db: str = "Starwars") -> int:
    conn = _c.connect(env, db)
    try:
        for table in _c.DDL.keys():
            n = _c._count(conn, table)
            print(f"{table:<40} {n:>6}", file=sys.stderr)
    finally:
        conn.close()
    return EXIT_OK


def show_resource(env, db: str, resource: str, *,
                  limit: int = 20, fmt: str = "md",
                  select: list[str] | None = None) -> int:
    """Print rows from a main table. Returns exit code."""
    table = f"sw_{resource}"
    if table not in _c.MAIN_COLUMNS:
        print(f"unknown resource: {resource}", file=sys.stderr)
        return EXIT_USAGE
    columns = select or _c.DEFAULT_SELECT.get(resource, _c.MAIN_COLUMNS[table])
    conn = _c.connect(env, db)
    try:
        cols, rows = _c._query_rows(conn, table, columns, limit)
        if not rows and fmt in ("csv", "md"):
            print(f"({table} is empty or no rows match)", file=sys.stderr)
            return EXIT_OK
        output = _c.RENDERERS[fmt](cols, rows)
        sys.stdout.write(output)
        if output and not output.endswith("\n"):
            sys.stdout.write("\n")
        print(
            f"({len(rows)} row(s) from {table}, format={fmt}, limit={limit})",
            file=sys.stderr,
        )
    finally:
        conn.close()
    return EXIT_OK


def show_planets(env, db="Starwars", **kwargs):
    return show_resource(env, db, "planets", **kwargs)

def show_films(env, db="Starwars", **kwargs):
    return show_resource(env, db, "films", **kwargs)

def show_species(env, db="Starwars", **kwargs):
    return show_resource(env, db, "species", **kwargs)

def show_people(env, db="Starwars", **kwargs):
    return show_resource(env, db, "people", **kwargs)

def show_vehicles(env, db="Starwars", **kwargs):
    return show_resource(env, db, "vehicles", **kwargs)

def show_starships(env, db="Starwars", **kwargs):
    return show_resource(env, db, "starships", **kwargs)
