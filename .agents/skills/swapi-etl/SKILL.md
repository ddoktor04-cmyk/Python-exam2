---
name: swapi-etl
description: Load Star Wars API data (swapi.info) into a Microsoft SQL Server database named Starwars. Provides an interactive menu and subcommands to (1) initialize the database and schema, (2) import people, planets, films, species, vehicles, and starships from SWAPI into MSSQL with idempotent upserts (no duplicates on re-run). Use when the user asks to "import Star Wars data into MSSQL", "create the Starwars database", "load SWAPI into SQL Server", "sync people/planets/films/species/vehicles/starships into a DB", "seed Starwars DB", or "ETL Star Wars API to MSSQL".
license: MIT
compatibility: Python 3.10+, httpx, pymssql. Reads DB credentials from .env (DB_IP, DB_USER, DB_PASSWORD). HTTP cache at .cache/swapi is shared with the swapi-fetch skill.
allowed-tools: Bash(python:*) Read
---

# ETL: Star Wars API → MSSQL (`Starwars` database)

Loads the six SWAPI resources (people, planets, films, species, vehicles,
starships) plus all many-to-many junctions into a SQL Server database
called **`Starwars`**, with **idempotent** imports — running the import
twice produces the same row counts (MERGE-based upsert keyed on
`swapi_url`).

## When to use
- The user wants to seed a `Starwars` database in MSSQL.
- The user wants to refresh the local Starwars DB from the API
  (sync, not a wipe).
- The user wants to inspect/audit what is already loaded (menu
  option `9`).
- The user wants a reproducible SWAPI→MSSQL pipeline that won't
  duplicate rows when run repeatedly.

## When NOT to use
- The user only wants ad-hoc JSON/CSV/Markdown output of SWAPI
  data — use `swapi-fetch`.
- The user wants to mutate SWAPI — impossible, the API is read-only.
- The user is targeting a non-MSSQL destination — this skill
  emits pymssql-flavored SQL and depends on `MERGE` (SQL Server
  2008+).
- The user wants to load into an existing third-party schema
  (NetBox/Nautobot) — out of scope.

## Workflow (init → import → verify)

1. **Init** (menu option `1` / subcommand `init`):
   - Connect to `master`, run
     `IF DB_ID('Starwars') IS NULL CREATE DATABASE Starwars;`.
   - Switch to `Starwars`, create 6 main tables and 10 junction
     tables (see `references/swapi-schema.md`). All DDL is
     `IF OBJECT_ID(...) IS NULL`-guarded.
2. **Import** (menu options `2..8` / subcommands `import <resource>`):
   - Fetch collection from `swapi-fetch` cache (or live API).
   - For each main table, batched `MERGE` keyed on `swapi_url` —
     on match, update all scalar columns and bump `fetched_at`;
     on no match, insert.
   - For each junction table, build a `set` of (left, right) URL
     pairs from the cached main-table records and `MERGE` them in.
   - Print a per-table diff: `inserted | updated | skipped`.
3. **Verify** (menu option `9` / subcommand `stats`):
   - `SELECT 'sw_planets' AS t, COUNT(*) AS n FROM sw_planets ...`
     for all 16 tables.

## Bundled script usage

```bash
# Interactive nested menu (default when no args)
python .agents/skills/swapi-etl/scripts/swapi_etl.py

# Or subcommands — scriptable for CI
python .agents/skills/swapi-etl/scripts/swapi_etl.py init
python .agents/skills/swapi-etl/scripts/swapi_etl.py import all
python .agents/skills/swapi-etl/scripts/swapi_etl.py import people
python .agents/skills/swapi-etl/scripts/swapi_etl.py import planets
python .agents/skills/swapi-etl/scripts/swapi_etl.py import films
python .agents/skills/swapi-etl/scripts/swapi_etl.py import species
python .agents/skills/swapi-etl/scripts/swapi_etl.py import vehicles
python .agents/skills/swapi-etl/scripts/swapi_etl.py import starships
python .agents/skills/swapi-etl/scripts/swapi_etl.py stats
python .agents/skills/swapi-etl/scripts/swapi_etl.py show people
python .agents/skills/swapi-etl/scripts/swapi_etl.py show films --limit 0
python .agents/skills/swapi-etl/scripts/swapi_etl.py show starships --format csv
python .agents/skills/swapi-etl/scripts/swapi_etl.py show people --select id,name,homeworld_url
```

Flags:
- `--db` (default `Starwars`): target database name.
- `--cache-dir` (default `.cache/swapi`): shared with `swapi-fetch`.
- `--cache-ttl` (default `3600`): seconds to reuse cached responses.
  Set to `0` to disable caching.
- `--timeout` (default `30`): HTTP timeout for live fetches.
- `--batch` (default `500`): rows per `MERGE` batch.
- `show` flags: `--limit N` (default `20`, `0` = all),
  `--format {text,md,csv,json}` (default `md`),
  `--select col1,col2,...` (default = curated for the resource).

## Menu

```
=== ГОЛОВНЕ МЕНЮ ===
1. Імпорт даних
2. Показати дані
0. Вихід
```

Top level → `1. Імпорт даних`:

```
--- Імпорт ---
1. Films
2. People
3. Planets
4. Starships
5. Species
6. Vehicles
7. Все (all)
0. Назад
```

Top level → `2. Показати дані`:

```
--- Показати ---
1. Films
2. People
3. Planets
4. Starships
5. Species
6. Vehicles
7. Статистика
0. Назад
```

The menu loops — choose `0. Назад` to return to the main menu,
`0. Вихід` to quit.

## Code layout

```
swapi-etl/
├── SKILL.md
├── references/swapi-schema.md
├── scripts/
│   └── swapi_etl.py        # CLI: argparse + nested menu, ~210 lines
└── src/
    ├── __init__.py
    ├── etl_core.py         # env, DB, schema, fetch, transform, merge, render
    └── functions.py        # discrete import_X / show_X / init_db wrappers
```

The `scripts/swapi_etl.py` is a thin wrapper. The discrete
per-resource functions are importable directly:

```python
import sys; sys.path.insert(0, "...")
from src.functions import (
    init_db,
    import_films, import_people, import_planets, import_starships,
    import_species, import_vehicles, import_all,
    show_films, show_people, show_planets, show_starships,
    show_species, show_vehicles, show_stats,
)

env = load_env()
init_db(env)
import_all(env)
show_films(env)
```

## Idempotency and dedup

- **Main tables** (`sw_planets`, `sw_people`, `sw_films`, `sw_species`,
  `sw_vehicles`, `sw_starships`): PK is the full `swapi_url`. Each
  import `MERGE` keyed on `swapi_url` → match updates all columns
  and stamps `fetched_at`; no-match inserts. Re-running the same
  import updates the same N rows in place — no growth.
- **Junction tables** (`sw_junction_*`): composite PK on
  `(left_url, right_url)`. Built from the freshly-loaded main-table
  data and `MERGE`d in. The set of pairs is a `set` in Python, so
  duplicates are dropped before reaching SQL.
- **`id` collisions**: `id` is the numeric tail of the URL
  (`/people/1` → `1`). It is `UNIQUE` but **not** the PK. If the
  source data ever returns the same `id` for different `swapi_url`s
  (it doesn't today, but SWAPI's URL scheme is the source of
  truth), the second insert fails on the `UNIQUE` constraint and is
  logged as a warning rather than crashing the import.
- **Junction rows that point to nothing** (orphan URLs) are skipped
  in Python, not silently dropped in SQL. They are counted in the
  per-table diff as `skipped`.

## Exit codes

- `0` — success.
- `2` — env / auth / network error.
- `3` — schema error (table missing after `init`).
- `4` — unknown resource / subcommand.
- `5` — runtime (SQL error, malformed payload).

## Gotchas

- **Database name is `Starwars`, not `swapi_db`**. The user asked
  for it explicitly; the `swapi-fetch` reference used `swapi_db` as
  an example only. Stay on `Starwars`.
- **Resource import order matters**: `planets` must be loaded
  before `people` and `species` (the latter reference the former
  via `homeworld_url`). The `import all` command runs them in the
  correct topological order. Importing a single resource skips
  cross-resource FK checks; if the main table's `homeworld_url`
  has no row in `sw_planets` yet, that's fine — we don't enforce
  FKs, we just record the URL.
- **Cache is shared with `swapi-fetch`**: same `cache_dir`. First
  ETL run after a long pause may pull live; subsequent runs hit
  the cache.
- **Windows cp1251 console**: stdout/stderr are reconfigured to
  utf-8 at the start of `main()` to avoid `UnicodeEncodeError` on
  the few `é` / `ü` characters in planet or species names.
- **Numeric fields stay `NVARCHAR`** in this schema (`height`,
  `mass`, `population`, etc.). SWAPI's `"unknown"` is preserved
  as-is; cast in views or downstream code. A future migration
  could add typed columns.
- **MERGE batching**: SQL Server has a 2100-parameter limit per
  statement. With ~20 columns × 500 rows that's 10 000 params —
  fine. With longer rows you may need to lower `--batch`.
- **No transactions across batches** by default. A power loss
  mid-`import` leaves the table partially updated. The
  `--atomic` flag wraps the whole import in a single transaction
  (slower, but fully recoverable on failure).

## Reference

- `references/swapi-schema.md` — full DDL, ER diagram, junction
  table matrix, dedup mechanics.
- The `swapi-fetch` skill shares the cache and the URL→resource
  conventions used here.
