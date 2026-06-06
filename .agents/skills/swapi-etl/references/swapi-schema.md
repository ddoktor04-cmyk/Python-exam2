# Starwars DB schema (SQL Server)

## Database

| Property | Value |
| --- | --- |
| Name | `Starwars` |
| Collation | server default |
| Recovery | server default |
| Created by | `init` subcommand / menu option `1` |

Creation is idempotent: `IF DB_ID('Starwars') IS NULL CREATE DATABASE Starwars;`
on the `master` connection, then `USE Starwars;` for the rest of the
session.

## Tables (16)

### Main resource tables (6)

Each main table is keyed on the full `swapi_url` (PK) plus the numeric
`id` extracted from the URL tail (`UNIQUE NOT NULL`). All other fields
are `NVARCHAR` to preserve SWAPI's `"unknown"` / `"n/a"` / `""`
sentinels — cast in views or downstream.

| Table | Rows expected | Notes |
| --- | --- | --- |
| `sw_planets`    | 60  | No FKs. Loaded first. |
| `sw_films`      | 6   | No FKs. `opening_crawl` is `NVARCHAR(MAX)`. |
| `sw_species`    | 37  | `homeworld_url` → `sw_planets.swapi_url` (not enforced). |
| `sw_people`     | 83  | `homeworld_url` → `sw_planets.swapi_url` (not enforced). |
| `sw_vehicles`   | 39  | No FKs. |
| `sw_starships`  | 37  | No FKs. |

Every main table has:

```sql
swapi_url      NVARCHAR(500)  NOT NULL PRIMARY KEY,
id             INT            NOT NULL UNIQUE,
...scalar columns from SWAPI...,
fetched_at     DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
```

### Junction tables (10)

All composite PKs on `(left_url, right_url)`. Both columns are
`NVARCHAR(500) NOT NULL`. The unique constraint on the composite
PK is the dedup mechanism.

| Table | left_url | right_url |
| --- | --- | --- |
| `sw_junction_person_films`      | person      | film      |
| `sw_junction_person_species`    | person      | species   |
| `sw_junction_person_vehicles`   | person      | vehicle   |
| `sw_junction_person_starships`  | person      | starship  |
| `sw_junction_film_planets`      | film        | planet    |
| `sw_junction_film_species`      | film        | species   |
| `sw_junction_film_vehicles`     | film        | vehicle   |
| `sw_junction_film_starships`    | film        | starship  |
| `sw_junction_vehicle_pilots`    | vehicle     | person    |
| `sw_junction_starship_pilots`   | starship    | person    |

## ER overview

```
                      ┌──────────────┐
        homeworld_url │  sw_planets  │  (referenced by people + species)
                      └──────┬───────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              │
       ┌──────────┐    ┌──────────┐        │
       │ sw_people│    │sw_species│        │
       └────┬─────┘    └────┬─────┘        │
            │               │              │
            │ (M2M via junction tables)   │
            ▼                              │
  ┌──────────┐  ┌──────────┐  ┌─────────┐  │
  │sw_films  │  │sw_vehicl.│  │sw_stars.│  │
  └──────────┘  └──────────┘  └─────────┘  │
                                          │
       (films reference all of the above via junction tables)
```

Note: FK relationships are **not enforced** with constraints. The
`swapi_url` columns are kept as plain `NVARCHAR(500)` so that loading
`sw_people` before `sw_planets` does not fail. This matches the
ETL's topological order (planets → everything else).

## Dedup mechanics

### Main tables — `MERGE` with `swapi_url`

```sql
MERGE INTO sw_planets AS tgt
USING (VALUES
    (?, ?, ?, ...),
    (?, ?, ?, ...),
    ...
) AS src (swapi_url, id, name, ..., fetched_at)
ON tgt.swapi_url = src.swapi_url
WHEN MATCHED THEN
    UPDATE SET
        id          = src.id,
        name        = src.name,
        ...
        fetched_at  = src.fetched_at
WHEN NOT MATCHED BY TARGET THEN
    INSERT (swapi_url, id, name, ..., fetched_at)
    VALUES (src.swapi_url, src.id, src.name, ..., src.fetched_at);
```

Running the same import twice: every row matches → all rows
updated in place, count unchanged.

### Junction tables — Python `set` + `MERGE`

```python
pairs = set()
for person in people:
    for film_url in person.get("films", []):
        pairs.add((person["url"], film_url))
```

```sql
MERGE INTO sw_junction_person_films AS tgt
USING (VALUES (?, ?), (?, ?), ...) AS src (person_url, film_url)
ON tgt.person_url = src.person_url AND tgt.film_url = src.film_url
WHEN NOT MATCHED BY TARGET THEN
    INSERT (person_url, film_url) VALUES (src.person_url, src.film_url);
```

Only `NOT MATCHED` is acted on; matched pairs are no-ops. Running
twice: every pair matches → no inserts, count unchanged.

## Field mappings

### `sw_planets`
`swapi_url, id, name, rotation_period, orbital_period, diameter,
climate, gravity, terrain, surface_water, population, residents_count,
films_count, created, edited, fetched_at`

### `sw_films`
`swapi_url, id, title, episode_id, opening_crawl, director, producer,
release_date, characters_count, planets_count, starships_count,
vehicles_count, species_count, created, edited, fetched_at`

### `sw_species`
`swapi_url, id, name, classification, designation, average_height,
average_lifespan, eye_colors, hair_colors, skin_colors, language,
homeworld_url, people_count, films_count, created, edited, fetched_at`

### `sw_people`
`swapi_url, id, name, birth_year, eye_color, gender, hair_color,
height, mass, skin_color, homeworld_url, species_count, films_count,
vehicles_count, starships_count, created, edited, fetched_at`

### `sw_vehicles`
`swapi_url, id, name, model, manufacturer, cost_in_credits, length,
max_atmosphering_speed, crew, passengers, cargo_capacity, consumables,
vehicle_class, pilots_count, films_count, created, edited, fetched_at`

### `sw_starships`
`swapi_url, id, name, model, manufacturer, cost_in_credits, length,
max_atmosphering_speed, crew, passengers, cargo_capacity, consumables,
hyperdrive_rating, MGLT, starship_class, pilots_count, films_count,
created, edited, fetched_at`

`created` / `edited` are SWAPI's audit timestamps; `fetched_at` is
when we wrote the row — `fetched_at` is the only column we always
update, the rest are stable for a given `swapi_url`.
