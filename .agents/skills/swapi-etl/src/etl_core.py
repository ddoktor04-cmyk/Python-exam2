"""Building blocks for swapi-etl: env, DB, schema, fetch, transform, merge, render.

This module holds the layer that knows how to talk to MSSQL and SWAPI.
The high-level discrete functions (import_films, show_people, ...) live in
`src.functions` and call into this module.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import pymssql

LOGGER_NAME = "netdevops.swapi_etl"
SWAPI_BASE = "https://swapi.info/api"
QUOTE_RE = re.compile(r'^\s*([A-Z0-9_]+)\s*=\s*"?([^"\n]*)"?\s*$', re.IGNORECASE)
ID_FROM_URL = re.compile(r"/(\d+)/?$")

EXIT_OK = 0
EXIT_ENV = 2
EXIT_SCHEMA = 3
EXIT_USAGE = 4
EXIT_RUNTIME = 5

RESOURCES = ("planets", "films", "species", "people", "vehicles", "starships")
IMPORT_ORDER = ("planets", "films", "species", "people", "vehicles", "starships")

logger = logging.getLogger(LOGGER_NAME)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )


def find_env() -> Path:
    cwd = Path.cwd().resolve()
    for start in (Path(__file__).resolve().parent, cwd):
        for parent in (start, *start.parents):
            candidate = parent / ".env"
            if candidate.exists():
                return candidate
    raise SystemExit(".env not found (expected DB_IP, DB_USER, DB_PASSWORD)")


def load_env(path: Path | None = None) -> dict[str, str]:
    p = path or find_env()
    return {
        m.group(1).upper(): m.group(2)
        for line in p.read_text(encoding="utf-8").splitlines()
        if (m := QUOTE_RE.match(line)) and not line.lstrip().startswith("#")
    }


def connect(env: dict[str, str], database: str, *, autocommit: bool = False) -> pymssql.Connection:
    return pymssql.connect(
        server=env["DB_IP"],
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
        database=database,
        login_timeout=10,
        timeout=10,
        autocommit=autocommit,
    )


def exec_script(conn: pymssql.Connection, sql: str) -> None:
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


DDL: dict[str, str] = {
    "sw_planets": """
        IF OBJECT_ID('sw_planets', 'U') IS NULL
        CREATE TABLE sw_planets (
            swapi_url      NVARCHAR(500) NOT NULL PRIMARY KEY,
            id             INT           NOT NULL UNIQUE,
            name           NVARCHAR(200) NOT NULL,
            rotation_period NVARCHAR(50) NULL,
            orbital_period  NVARCHAR(50) NULL,
            diameter        NVARCHAR(50) NULL,
            climate         NVARCHAR(200) NULL,
            gravity         NVARCHAR(100) NULL,
            terrain         NVARCHAR(500) NULL,
            surface_water   NVARCHAR(50) NULL,
            population      NVARCHAR(50) NULL,
            residents_count INT           NOT NULL DEFAULT 0,
            films_count     INT           NOT NULL DEFAULT 0,
            created         DATETIME2 NULL,
            edited          DATETIME2 NULL,
            fetched_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
        );
    """,
    "sw_films": """
        IF OBJECT_ID('sw_films', 'U') IS NULL
        CREATE TABLE sw_films (
            swapi_url        NVARCHAR(500) NOT NULL PRIMARY KEY,
            id               INT           NOT NULL UNIQUE,
            title            NVARCHAR(200) NOT NULL,
            episode_id       INT           NULL,
            opening_crawl    NVARCHAR(MAX) NULL,
            director         NVARCHAR(200) NULL,
            producer         NVARCHAR(500) NULL,
            release_date     DATE          NULL,
            characters_count INT           NOT NULL DEFAULT 0,
            planets_count    INT           NOT NULL DEFAULT 0,
            starships_count  INT           NOT NULL DEFAULT 0,
            vehicles_count   INT           NOT NULL DEFAULT 0,
            species_count    INT           NOT NULL DEFAULT 0,
            created          DATETIME2 NULL,
            edited           DATETIME2 NULL,
            fetched_at       DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
        );
    """,
    "sw_species": """
        IF OBJECT_ID('sw_species', 'U') IS NULL
        CREATE TABLE sw_species (
            swapi_url        NVARCHAR(500) NOT NULL PRIMARY KEY,
            id               INT           NOT NULL UNIQUE,
            name             NVARCHAR(200) NOT NULL,
            classification   NVARCHAR(200) NULL,
            designation      NVARCHAR(200) NULL,
            average_height   NVARCHAR(50) NULL,
            average_lifespan NVARCHAR(50) NULL,
            eye_colors       NVARCHAR(500) NULL,
            hair_colors      NVARCHAR(500) NULL,
            skin_colors      NVARCHAR(500) NULL,
            language         NVARCHAR(200) NULL,
            homeworld_url    NVARCHAR(500) NULL,
            people_count     INT           NOT NULL DEFAULT 0,
            films_count      INT           NOT NULL DEFAULT 0,
            created          DATETIME2 NULL,
            edited           DATETIME2 NULL,
            fetched_at       DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
        );
    """,
    "sw_people": """
        IF OBJECT_ID('sw_people', 'U') IS NULL
        CREATE TABLE sw_people (
            swapi_url       NVARCHAR(500) NOT NULL PRIMARY KEY,
            id              INT           NOT NULL UNIQUE,
            name            NVARCHAR(200) NOT NULL,
            birth_year      NVARCHAR(50) NULL,
            eye_color       NVARCHAR(200) NULL,
            gender          NVARCHAR(50) NULL,
            hair_color      NVARCHAR(200) NULL,
            height          NVARCHAR(50) NULL,
            mass            NVARCHAR(50) NULL,
            skin_color      NVARCHAR(200) NULL,
            homeworld_url   NVARCHAR(500) NULL,
            species_count   INT           NOT NULL DEFAULT 0,
            films_count     INT           NOT NULL DEFAULT 0,
            vehicles_count  INT           NOT NULL DEFAULT 0,
            starships_count INT           NOT NULL DEFAULT 0,
            created         DATETIME2 NULL,
            edited          DATETIME2 NULL,
            fetched_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
        );
    """,
    "sw_vehicles": """
        IF OBJECT_ID('sw_vehicles', 'U') IS NULL
        CREATE TABLE sw_vehicles (
            swapi_url             NVARCHAR(500) NOT NULL PRIMARY KEY,
            id                    INT           NOT NULL UNIQUE,
            name                  NVARCHAR(200) NOT NULL,
            model                 NVARCHAR(200) NULL,
            manufacturer          NVARCHAR(500) NULL,
            cost_in_credits       NVARCHAR(50) NULL,
            length                NVARCHAR(50) NULL,
            max_atmosphering_speed NVARCHAR(50) NULL,
            crew                  NVARCHAR(50) NULL,
            passengers            NVARCHAR(50) NULL,
            cargo_capacity        NVARCHAR(50) NULL,
            consumables           NVARCHAR(100) NULL,
            vehicle_class         NVARCHAR(200) NULL,
            pilots_count          INT           NOT NULL DEFAULT 0,
            films_count           INT           NOT NULL DEFAULT 0,
            created               DATETIME2 NULL,
            edited                DATETIME2 NULL,
            fetched_at            DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
        );
    """,
    "sw_starships": """
        IF OBJECT_ID('sw_starships', 'U') IS NULL
        CREATE TABLE sw_starships (
            swapi_url              NVARCHAR(500) NOT NULL PRIMARY KEY,
            id                     INT           NOT NULL UNIQUE,
            name                   NVARCHAR(200) NOT NULL,
            model                  NVARCHAR(200) NULL,
            manufacturer           NVARCHAR(500) NULL,
            cost_in_credits        NVARCHAR(50) NULL,
            length                 NVARCHAR(50) NULL,
            max_atmosphering_speed NVARCHAR(50) NULL,
            crew                   NVARCHAR(50) NULL,
            passengers             NVARCHAR(50) NULL,
            cargo_capacity         NVARCHAR(50) NULL,
            consumables            NVARCHAR(100) NULL,
            hyperdrive_rating      NVARCHAR(50) NULL,
            MGLT                   NVARCHAR(50) NULL,
            starship_class         NVARCHAR(200) NULL,
            pilots_count           INT           NOT NULL DEFAULT 0,
            films_count            INT           NOT NULL DEFAULT 0,
            created                DATETIME2 NULL,
            edited                 DATETIME2 NULL,
            fetched_at             DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
        );
    """,
    "sw_junction_person_films": """
        IF OBJECT_ID('sw_junction_person_films', 'U') IS NULL
        CREATE TABLE sw_junction_person_films (
            person_url NVARCHAR(500) NOT NULL,
            film_url   NVARCHAR(500) NOT NULL,
            PRIMARY KEY (person_url, film_url)
        );
    """,
    "sw_junction_person_species": """
        IF OBJECT_ID('sw_junction_person_species', 'U') IS NULL
        CREATE TABLE sw_junction_person_species (
            person_url  NVARCHAR(500) NOT NULL,
            species_url NVARCHAR(500) NOT NULL,
            PRIMARY KEY (person_url, species_url)
        );
    """,
    "sw_junction_person_vehicles": """
        IF OBJECT_ID('sw_junction_person_vehicles', 'U') IS NULL
        CREATE TABLE sw_junction_person_vehicles (
            person_url  NVARCHAR(500) NOT NULL,
            vehicle_url NVARCHAR(500) NOT NULL,
            PRIMARY KEY (person_url, vehicle_url)
        );
    """,
    "sw_junction_person_starships": """
        IF OBJECT_ID('sw_junction_person_starships', 'U') IS NULL
        CREATE TABLE sw_junction_person_starships (
            person_url   NVARCHAR(500) NOT NULL,
            starship_url NVARCHAR(500) NOT NULL,
            PRIMARY KEY (person_url, starship_url)
        );
    """,
    "sw_junction_film_planets": """
        IF OBJECT_ID('sw_junction_film_planets', 'U') IS NULL
        CREATE TABLE sw_junction_film_planets (
            film_url   NVARCHAR(500) NOT NULL,
            planet_url NVARCHAR(500) NOT NULL,
            PRIMARY KEY (film_url, planet_url)
        );
    """,
    "sw_junction_film_species": """
        IF OBJECT_ID('sw_junction_film_species', 'U') IS NULL
        CREATE TABLE sw_junction_film_species (
            film_url    NVARCHAR(500) NOT NULL,
            species_url NVARCHAR(500) NOT NULL,
            PRIMARY KEY (film_url, species_url)
        );
    """,
    "sw_junction_film_vehicles": """
        IF OBJECT_ID('sw_junction_film_vehicles', 'U') IS NULL
        CREATE TABLE sw_junction_film_vehicles (
            film_url    NVARCHAR(500) NOT NULL,
            vehicle_url NVARCHAR(500) NOT NULL,
            PRIMARY KEY (film_url, vehicle_url)
        );
    """,
    "sw_junction_film_starships": """
        IF OBJECT_ID('sw_junction_film_starships', 'U') IS NULL
        CREATE TABLE sw_junction_film_starships (
            film_url     NVARCHAR(500) NOT NULL,
            starship_url NVARCHAR(500) NOT NULL,
            PRIMARY KEY (film_url, starship_url)
        );
    """,
    "sw_junction_vehicle_pilots": """
        IF OBJECT_ID('sw_junction_vehicle_pilots', 'U') IS NULL
        CREATE TABLE sw_junction_vehicle_pilots (
            vehicle_url NVARCHAR(500) NOT NULL,
            pilot_url   NVARCHAR(500) NOT NULL,
            PRIMARY KEY (vehicle_url, pilot_url)
        );
    """,
    "sw_junction_starship_pilots": """
        IF OBJECT_ID('sw_junction_starship_pilots', 'U') IS NULL
        CREATE TABLE sw_junction_starship_pilots (
            starship_url NVARCHAR(500) NOT NULL,
            pilot_url    NVARCHAR(500) NOT NULL,
            PRIMARY KEY (starship_url, pilot_url)
        );
    """,
}


def _cache_path(cache_dir: Path, url: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", url)
    return cache_dir / f"{safe}.json"


def cached_get(client: httpx.Client, url: str, cache_dir: Path, ttl: int) -> Any:
    path = _cache_path(cache_dir, url)
    if ttl > 0 and path.exists() and (time.time() - path.stat().st_mtime) < ttl:
        return json.loads(path.read_text(encoding="utf-8"))
    logger.info("fetch url=%s", url)
    resp = client.get(url, timeout=client.timeout)
    resp.raise_for_status()
    payload = resp.json()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def fetch_collection(client: httpx.Client, resource: str, base: str,
                     cache_dir: Path, ttl: int) -> list[dict[str, Any]]:
    url = f"{base.rstrip('/')}/{resource}"
    payload = cached_get(client, url, cache_dir, ttl)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "results" in payload:
        return payload["results"]
    return [payload]


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def safe_str(v: Any, max_len: int = 500) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("n/a", "none"):
        return None
    return s[:max_len] if len(s) > max_len else s


def url_id(url: str) -> int:
    m = ID_FROM_URL.search(url or "")
    return int(m.group(1)) if m else 0


def _row_planet(r: dict[str, Any], ts: datetime) -> tuple:
    return (
        r["url"], url_id(r["url"]), r.get("name"),
        safe_str(r.get("rotation_period"), 50),
        safe_str(r.get("orbital_period"), 50),
        safe_str(r.get("diameter"), 50),
        safe_str(r.get("climate"), 200),
        safe_str(r.get("gravity"), 100),
        safe_str(r.get("terrain"), 500),
        safe_str(r.get("surface_water"), 50),
        safe_str(r.get("population"), 50),
        len(r.get("residents") or []),
        len(r.get("films") or []),
        parse_dt(r.get("created")),
        parse_dt(r.get("edited")),
        ts,
    )


def _row_film(r: dict[str, Any], ts: datetime) -> tuple:
    return (
        r["url"], url_id(r["url"]), r.get("title"),
        r.get("episode_id"),
        r.get("opening_crawl"),
        safe_str(r.get("director"), 200),
        safe_str(r.get("producer"), 500),
        parse_date(r.get("release_date")),
        len(r.get("characters") or []),
        len(r.get("planets") or []),
        len(r.get("starships") or []),
        len(r.get("vehicles") or []),
        len(r.get("species") or []),
        parse_dt(r.get("created")),
        parse_dt(r.get("edited")),
        ts,
    )


def _row_species(r: dict[str, Any], ts: datetime) -> tuple:
    return (
        r["url"], url_id(r["url"]), r.get("name"),
        safe_str(r.get("classification"), 200),
        safe_str(r.get("designation"), 200),
        safe_str(r.get("average_height"), 50),
        safe_str(r.get("average_lifespan"), 50),
        safe_str(r.get("eye_colors"), 500),
        safe_str(r.get("hair_colors"), 500),
        safe_str(r.get("skin_colors"), 500),
        safe_str(r.get("language"), 200),
        r.get("homeworld"),
        len(r.get("people") or []),
        len(r.get("films") or []),
        parse_dt(r.get("created")),
        parse_dt(r.get("edited")),
        ts,
    )


def _row_person(r: dict[str, Any], ts: datetime) -> tuple:
    return (
        r["url"], url_id(r["url"]), r.get("name"),
        safe_str(r.get("birth_year"), 50),
        safe_str(r.get("eye_color"), 200),
        safe_str(r.get("gender"), 50),
        safe_str(r.get("hair_color"), 200),
        safe_str(r.get("height"), 50),
        safe_str(r.get("mass"), 50),
        safe_str(r.get("skin_color"), 200),
        r.get("homeworld"),
        len(r.get("species") or []),
        len(r.get("films") or []),
        len(r.get("vehicles") or []),
        len(r.get("starships") or []),
        parse_dt(r.get("created")),
        parse_dt(r.get("edited")),
        ts,
    )


def _row_vehicle(r: dict[str, Any], ts: datetime) -> tuple:
    return (
        r["url"], url_id(r["url"]), r.get("name"),
        safe_str(r.get("model"), 200),
        safe_str(r.get("manufacturer"), 500),
        safe_str(r.get("cost_in_credits"), 50),
        safe_str(r.get("length"), 50),
        safe_str(r.get("max_atmosphering_speed"), 50),
        safe_str(r.get("crew"), 50),
        safe_str(r.get("passengers"), 50),
        safe_str(r.get("cargo_capacity"), 50),
        safe_str(r.get("consumables"), 100),
        safe_str(r.get("vehicle_class"), 200),
        len(r.get("pilots") or []),
        len(r.get("films") or []),
        parse_dt(r.get("created")),
        parse_dt(r.get("edited")),
        ts,
    )


def _row_starship(r: dict[str, Any], ts: datetime) -> tuple:
    return (
        r["url"], url_id(r["url"]), r.get("name"),
        safe_str(r.get("model"), 200),
        safe_str(r.get("manufacturer"), 500),
        safe_str(r.get("cost_in_credits"), 50),
        safe_str(r.get("length"), 50),
        safe_str(r.get("max_atmosphering_speed"), 50),
        safe_str(r.get("crew"), 50),
        safe_str(r.get("passengers"), 50),
        safe_str(r.get("cargo_capacity"), 50),
        safe_str(r.get("consumables"), 100),
        safe_str(r.get("hyperdrive_rating"), 50),
        safe_str(r.get("MGLT"), 50),
        safe_str(r.get("starship_class"), 200),
        len(r.get("pilots") or []),
        len(r.get("films") or []),
        parse_dt(r.get("created")),
        parse_dt(r.get("edited")),
        ts,
    )


MAIN_COLUMNS: dict[str, list[str]] = {
    "sw_planets":   ["swapi_url", "id", "name", "rotation_period", "orbital_period",
                     "diameter", "climate", "gravity", "terrain", "surface_water",
                     "population", "residents_count", "films_count",
                     "created", "edited", "fetched_at"],
    "sw_films":     ["swapi_url", "id", "title", "episode_id", "opening_crawl",
                     "director", "producer", "release_date",
                     "characters_count", "planets_count", "starships_count",
                     "vehicles_count", "species_count", "created", "edited", "fetched_at"],
    "sw_species":   ["swapi_url", "id", "name", "classification", "designation",
                     "average_height", "average_lifespan", "eye_colors", "hair_colors",
                     "skin_colors", "language", "homeworld_url",
                     "people_count", "films_count", "created", "edited", "fetched_at"],
    "sw_people":    ["swapi_url", "id", "name", "birth_year", "eye_color", "gender",
                     "hair_color", "height", "mass", "skin_color", "homeworld_url",
                     "species_count", "films_count", "vehicles_count", "starships_count",
                     "created", "edited", "fetched_at"],
    "sw_vehicles":  ["swapi_url", "id", "name", "model", "manufacturer",
                     "cost_in_credits", "length", "max_atmosphering_speed",
                     "crew", "passengers", "cargo_capacity", "consumables",
                     "vehicle_class", "pilots_count", "films_count",
                     "created", "edited", "fetched_at"],
    "sw_starships": ["swapi_url", "id", "name", "model", "manufacturer",
                     "cost_in_credits", "length", "max_atmosphering_speed",
                     "crew", "passengers", "cargo_capacity", "consumables",
                     "hyperdrive_rating", "MGLT", "starship_class",
                     "pilots_count", "films_count", "created", "edited", "fetched_at"],
}

ROW_BUILDERS: dict[str, Callable[[dict[str, Any], datetime], tuple]] = {
    "sw_planets":   _row_planet,
    "sw_films":     _row_film,
    "sw_species":   _row_species,
    "sw_people":    _row_person,
    "sw_vehicles":  _row_vehicle,
    "sw_starships": _row_starship,
}


def merge_main_table(conn: pymssql.Connection, table: str, rows: list[tuple]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    cols = MAIN_COLUMNS[table]
    row_placeholder = "(" + ",".join(["%s"] * len(cols)) + ")"
    placeholders = ",".join([row_placeholder] * len(rows))
    src_cols = ",".join(cols)
    update_set = ",".join(f"{c} = src.{c}" for c in cols if c not in ("swapi_url", "fetched_at"))
    update_set = f"{update_set}, fetched_at = src.fetched_at" if update_set else "fetched_at = src.fetched_at"
    insert_cols = ",".join(cols)
    insert_vals = ",".join(f"src.{c}" for c in cols)
    sql = f"""
        MERGE INTO {table} AS tgt
        USING (VALUES {placeholders}) AS src ({src_cols})
        ON tgt.swapi_url = src.swapi_url
        WHEN MATCHED THEN UPDATE SET {update_set}
        WHEN NOT MATCHED BY TARGET THEN
            INSERT ({insert_cols}) VALUES ({insert_vals});
    """
    inserted_before = _count(conn, table)
    flat: list[Any] = []
    for r in rows:
        flat.extend(r)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(flat))
    inserted_after = _count(conn, table)
    inserted = max(inserted_after - inserted_before, 0)
    updated = len(rows) - inserted
    conn.commit()
    return inserted, updated


JUNCTION_PK: dict[str, tuple[str, str]] = {
    "sw_junction_person_films":     ("person_url", "film_url"),
    "sw_junction_person_species":   ("person_url", "species_url"),
    "sw_junction_person_vehicles":  ("person_url", "vehicle_url"),
    "sw_junction_person_starships": ("person_url", "starship_url"),
    "sw_junction_film_planets":     ("film_url",   "planet_url"),
    "sw_junction_film_species":     ("film_url",   "species_url"),
    "sw_junction_film_vehicles":    ("film_url",   "vehicle_url"),
    "sw_junction_film_starships":   ("film_url",   "starship_url"),
    "sw_junction_vehicle_pilots":   ("vehicle_url","pilot_url"),
    "sw_junction_starship_pilots":  ("starship_url","pilot_url"),
}

JUNCTION_MAP: dict[str, list[tuple[str, str, str]]] = {
    "people": [
        ("films",     "sw_junction_person_films",     "L"),
        ("species",   "sw_junction_person_species",   "L"),
        ("vehicles",  "sw_junction_person_vehicles",  "L"),
        ("starships", "sw_junction_person_starships", "L"),
    ],
    "planets": [
        ("films",     "sw_junction_film_planets",     "R"),
    ],
    "films": [
        ("characters","sw_junction_person_films",     "R"),
        ("planets",   "sw_junction_film_planets",     "L"),
        ("starships", "sw_junction_film_starships",   "L"),
        ("vehicles",  "sw_junction_film_vehicles",    "L"),
        ("species",   "sw_junction_film_species",     "L"),
    ],
    "species": [
        ("people",    "sw_junction_person_species",   "R"),
        ("films",     "sw_junction_film_species",     "R"),
    ],
    "vehicles": [
        ("pilots",    "sw_junction_vehicle_pilots",   "L"),
        ("films",     "sw_junction_film_vehicles",    "R"),
    ],
    "starships": [
        ("pilots",    "sw_junction_starship_pilots",  "L"),
        ("films",     "sw_junction_film_starships",   "R"),
    ],
}


def merge_junction(conn: pymssql.Connection, table: str, pairs: set[tuple[str, str]]) -> int:
    if not pairs:
        return 0
    left_col, right_col = JUNCTION_PK[table]
    rows = [tuple(p) for p in pairs]
    placeholders = ",".join(["(%s, %s)"] * len(rows))
    sql = f"""
        MERGE INTO {table} AS tgt
        USING (VALUES {placeholders}) AS src ({left_col}, {right_col})
        ON tgt.{left_col} = src.{left_col}
           AND tgt.{right_col} = src.{right_col}
        WHEN NOT MATCHED BY TARGET THEN
            INSERT ({left_col}, {right_col}) VALUES (src.{left_col}, src.{right_col});
    """
    flat: list[Any] = []
    for p in rows:
        flat.extend(p)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(flat))
    conn.commit()
    return len(rows)


def collect_junctions(records: list[dict[str, Any]],
                      resource: str) -> dict[str, set[tuple[str, str]]]:
    pairs: dict[str, set[tuple[str, str]]] = {t: set() for t in JUNCTION_PK}
    for r in records:
        url = r.get("url")
        if not url:
            continue
        for field, table, side in JUNCTION_MAP.get(resource, []):
            for ref in (r.get(field) or []):
                if side == "L":
                    pairs[table].add((url, ref))
                else:
                    pairs[table].add((ref, url))
    return pairs


def _count(conn: pymssql.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return int(cur.fetchone()[0])


def ensure_database(env: dict[str, str], db: str) -> None:
    master = connect(env, "master", autocommit=True)
    try:
        with master.cursor() as cur:
            cur.execute(
                f"IF DB_ID('{db}') IS NULL CREATE DATABASE [{db}];"
            )
    finally:
        master.close()


def ensure_schema(conn: pymssql.Connection) -> None:
    for name, ddl in DDL.items():
        logger.info("ensure table=%s", name)
        exec_script(conn, ddl)


DEFAULT_SELECT: dict[str, list[str]] = {
    "planets":   ["id", "name", "climate", "terrain", "population", "films_count"],
    "films":     ["id", "title", "episode_id", "director", "release_date",
                 "characters_count", "planets_count"],
    "species":   ["id", "name", "classification", "language", "homeworld_url",
                 "people_count"],
    "people":    ["id", "name", "birth_year", "gender", "height", "mass",
                 "homeworld_url", "films_count"],
    "vehicles":  ["id", "name", "model", "manufacturer", "vehicle_class",
                 "films_count", "pilots_count"],
    "starships": ["id", "name", "model", "manufacturer", "starship_class",
                 "hyperdrive_rating", "films_count", "pilots_count"],
}


def _query_rows(conn: pymssql.Connection, table: str, select: list[str],
                limit: int) -> tuple[list[str], list[tuple]]:
    available = MAIN_COLUMNS[table]
    unknown = [c for c in select if c not in available]
    if unknown:
        raise SystemExit(f"unknown column(s) for {table}: {', '.join(unknown)}")
    cols = ", ".join(select)
    top = f"TOP ({limit}) " if limit > 0 else ""
    sql = f"SELECT {top}{cols} FROM {table} ORDER BY id"
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return select, rows


def _render_csv(columns: list[str], rows: list[tuple]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([("" if v is None else v) for v in row])
    return buf.getvalue()


def _render_json(columns: list[str], rows: list[tuple]) -> str:
    return json.dumps(
        [dict(zip(columns, row, strict=True)) for row in rows],
        ensure_ascii=False, indent=2, default=str,
    )


def _short_url(url: str | None) -> str:
    """Return the short form of a SWAPI URL: '/resource/id' or empty string."""
    if not url:
        return ""
    m = re.search(r"/api/([^/]+)/(\d+)/?$", url)
    return f"/{m.group(1)}/{m.group(2)}" if m else url


def _is_url_column(name: str) -> bool:
    return name.endswith("_url") or name == "url"


def _format_cell(value: Any, column: str, max_len: int) -> str:
    """Format a cell for display: shorten URLs, truncate long values."""
    if value is None:
        return ""
    s = str(value)
    if _is_url_column(column):
        s = _short_url(s) if s else ""
    s = s.replace("\n", " ").replace("|", "\\|")
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _render_text(columns: list[str], rows: list[tuple],
                 max_cell: int = 30, max_total: int = 120) -> str:
    formatted = [[_format_cell(v, c, max_cell) for v, c in zip(row, columns)]
                 for row in rows]
    natural_widths = [max(len(c), 4) for c in columns]
    for row in formatted:
        for i, v in enumerate(row):
            natural_widths[i] = max(natural_widths[i], len(v))
    widths = [min(w, max_cell) for w in natural_widths]
    total = sum(widths) + 3 * (len(columns) - 1)
    if total > max_total:
        scale = (max_total - 3 * (len(columns) - 1)) / sum(widths)
        widths = [max(4, int(w * scale)) for w in widths]
    for row in formatted:
        for i in range(len(row)):
            row[i] = row[i][: widths[i]].ljust(widths[i])
    out = []
    out.append(" | ".join(c.ljust(widths[i]) for i, c in enumerate(columns)))
    out.append("-+-".join("-" * w for w in widths))
    for row in formatted:
        out.append(" | ".join(row))
    return "\n".join(out)


def _render_md(columns: list[str], rows: list[tuple],
               max_cell: int = 40) -> str:
    out = io.StringIO()
    formatted = [[_format_cell(v, c, max_cell) for v, c in zip(row, columns)]
                 for row in rows]
    out.write("| " + " | ".join(columns) + " |\n")
    out.write("|" + "|".join("---" for _ in columns) + "|\n")
    for row in formatted:
        out.write("| " + " | ".join(row) + " |\n")
    return out.getvalue()


RENDERERS = {
    "text": _render_text,
    "md":   _render_md,
    "csv":  _render_csv,
    "json": _render_json,
}
