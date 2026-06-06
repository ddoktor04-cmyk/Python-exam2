"""Star Wars ETL -> MSSQL (Starwars DB) — interactive menu + CLI.

Examples:
    python swapi_etl.py                 # interactive nested menu
    python swapi_etl.py init
    python swapi_etl.py import all
    python swapi_etl.py import people
    python swapi_etl.py show films --limit 0
    python swapi_etl.py show people --format csv
    python swapi_etl.py stats

The business logic lives in `src.functions` and `src.etl_core`.
This file is a thin CLI/menu wrapper.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src import etl_core as _c
from src import functions as _f


IMPORT_SUBMENU = """
--- Імпорт ---
1. Films
2. People
3. Planets
4. Starships
5. Species
6. Vehicles
7. Все (all)
0. Назад
"""

SHOW_SUBMENU = """
--- Показати ---
1. Films
2. People
3. Planets
4. Starships
5. Species
6. Vehicles
7. Статистика
0. Назад
"""

MAIN_MENU = """
=== ГОЛОВНЕ МЕНЮ ===
1. Імпорт даних
2. Показати дані
0. Вихід
"""

IMPORT_MAP = {
    "1": ("films",     _f.import_films),
    "2": ("people",    _f.import_people),
    "3": ("planets",   _f.import_planets),
    "4": ("starships", _f.import_starships),
    "5": ("species",   _f.import_species),
    "6": ("vehicles",  _f.import_vehicles),
}

SHOW_MAP = {
    "1": ("films",     _f.show_films),
    "2": ("people",    _f.show_people),
    "3": ("planets",   _f.show_planets),
    "4": ("starships", _f.show_starships),
    "5": ("species",   _f.show_species),
    "6": ("vehicles",  _f.show_vehicles),
    "7": ("stats",     _f.show_stats),
}


def _prompt(label: str) -> str:
    try:
        return input(label).strip()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return "0"


def _import_submenu(env, db, kw) -> None:
    while True:
        print(IMPORT_SUBMENU, file=sys.stderr)
        sub = _prompt("Ваш вибір: ")
        if sub in ("0", "q"):
            return
        if sub == "7":
            try:
                _f.import_all(env, db, **kw)
            except Exception as exc:
                print(f"import_all failed: {exc}", file=sys.stderr)
            return
        action = IMPORT_MAP.get(sub)
        if action is None:
            print(f"невідомий вибір: {sub!r}", file=sys.stderr)
            continue
        name, fn = action
        try:
            fn(env, db, **kw)
        except Exception as exc:
            print(f"{name} import failed: {exc}", file=sys.stderr)


def _show_submenu(env, db) -> None:
    while True:
        print(SHOW_SUBMENU, file=sys.stderr)
        sub = _prompt("Ваш вибір: ")
        if sub in ("0", "q"):
            return
        action = SHOW_MAP.get(sub)
        if action is None:
            print(f"невідомий вибір: {sub!r}", file=sys.stderr)
            continue
        _name, fn = action
        try:
            fn(env, db)
        except Exception as exc:
            print(f"show failed: {exc}", file=sys.stderr)


def run_menu(env, db, kw) -> int:
    running = True
    while running:
        print(MAIN_MENU, file=sys.stderr)
        choice = _prompt("Ваш вибір: ")
        if choice == "1":
            _import_submenu(env, db, kw)
        elif choice == "2":
            _show_submenu(env, db)
        elif choice in ("0", "q", "quit", "exit"):
            print("До побачення!", file=sys.stderr)
            running = False
        else:
            print(f"невідомий вибір: {choice!r}", file=sys.stderr)
    return _c.EXIT_OK


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="swapi_etl.py",
        description="ETL SWAPI data into a MSSQL Starwars database.",
    )
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("init", help="create database + tables (idempotent)")

    imp = sub.add_parser("import", help="import one or all resources")
    imp.add_argument(
        "resource",
        choices=["all", "planets", "films", "species",
                 "people", "vehicles", "starships"],
    )

    sub.add_parser("stats", help="show row counts per table")

    show = sub.add_parser("show", help="show rows from a main table")
    show.add_argument(
        "resource",
        choices=["planets", "films", "species",
                 "people", "vehicles", "starships"],
    )
    show.add_argument("--limit", type=int, default=20,
                      help="rows to show (0 = all, default 20)")
    show.add_argument("--format", dest="fmt", default="md",
                      choices=["text", "md", "csv", "json"],
                      help="output format (default md)")
    show.add_argument("--select", default=None,
                      help="comma-separated columns (default: curated)")

    p.add_argument("--db", default="Starwars")
    p.add_argument("--cache-dir", default=".cache/swapi", type=Path)
    p.add_argument("--cache-ttl", default=3600, type=int)
    p.add_argument("--timeout", default=30, type=int)
    p.add_argument("--batch", default=500, type=int)
    p.add_argument("--atomic", action="store_true")
    return p.parse_args(argv)


def _import_kwargs(args) -> dict:
    return dict(
        cache_dir=args.cache_dir,
        cache_ttl=args.cache_ttl,
        timeout=args.timeout,
        batch=args.batch,
        atomic=args.atomic,
    )


def main(argv=None) -> int:
    _c.configure_logging()
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    args = parse_args(argv)
    try:
        env = _f.load_env()
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return _c.EXIT_ENV

    kw = _import_kwargs(args)

    if args.cmd is None:
        return run_menu(env, args.db, kw)
    if args.cmd == "init":
        return _f.init_db(env, args.db)
    if args.cmd == "stats":
        return _f.show_stats(env, args.db)
    if args.cmd == "show":
        cols = ([s.strip() for s in args.select.split(",") if s.strip()]
                if args.select else None)
        return _f.show_resource(env, args.db, args.resource,
                                limit=args.limit, fmt=args.fmt, select=cols)
    if args.cmd == "import":
        if args.resource == "all":
            return _f.import_all(env, args.db, **kw)
        return _f.import_resource(env, args.db, args.resource, **kw) and _c.EXIT_OK \
               or _c.EXIT_OK
    print(f"unknown subcommand: {args.cmd}", file=sys.stderr)
    return _c.EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
