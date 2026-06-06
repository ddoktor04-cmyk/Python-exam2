# SWAPI resources — fields and gotchas

## Endpoints (case-insensitive, singular or plural)

| Resource    | Collection | Count | Key field for expansion |
| ----------- | ---------- | ----- | ----------------------- |
| `people`    | `/api/people`    | 83  | `name`     |
| `planets`   | `/api/planets`   | 60  | `name`     |
| `films`     | `/api/films`     | 6   | `title`    |
| `species`   | `/api/species`   | 37  | `name`     |
| `vehicles`  | `/api/vehicles`  | 39  | `name`     |
| `starships` | `/api/starships` | 37  | `name`     |

Single resource: `<resource>/<id>` (e.g., `people/1`).

## Field reference

### `people`
- `name`, `birth_year` (e.g., `"19BBY"`), `gender` (`male` / `female` / `n/a` / `hermaphrodite` / `none` / `unknown`)
- `height`, `mass` — strings, may be `"unknown"`
- `hair_color`, `skin_color`, `eye_color` — comma-separated lists or `"n/a"` / `"none"` / `"unknown"`
- `homeworld` — single URL
- `films`, `species`, `vehicles`, `starships` — URL arrays

### `planets`
- `name`, `climate`, `terrain` (comma-separated)
- `gravity` (e.g., `"1 standard"`, `"0.9 standard"`, `"1.5 (surface), 1 standard (Cloud City)"`, `"N/A"`)
- `rotation_period`, `orbital_period`, `diameter`, `surface_water`, `population` — strings
- `residents`, `films` — URL arrays

### `films`
- `title`, `episode_id` (int), `director`, `producer` (comma-separated)
- `release_date` — ISO date
- `opening_crawl` — multi-line text
- `characters`, `planets`, `starships`, `vehicles`, `species` — URL arrays

### `species`
- `name`, `classification`, `designation`
- `average_height`, `average_lifespan` — strings, may be `"n/a"` or `"indefinite"`
- `skin_colors`, `hair_colors`, `eye_colors` — comma-separated
- `homeworld` — URL or `null` (Droid)
- `language` — may be `"unknown"`; note typo `"Galatic Basic"` (Human) — that's a data quirk, not a fix
- `people`, `films` — URL arrays

### `vehicles` and `starships`
- `name`, `model`, `manufacturer`
- `cost_in_credits` — string, may be `"unknown"`
- `length` — string with possible trailing whitespace
- `max_atmosphering_speed`, `crew`, `passengers`, `cargo_capacity` — strings
- `consumables` — e.g., `"2 months"`, `"1 year"`
- `vehicle_class` / `starship_class` — string
- `hyperdrive_rating`, `MGLT` (starships only) — strings
- `pilots`, `films` — URL arrays

## Type quirks cheat sheet

| Field                    | Source value            | ETL advice |
| ------------------------ | ----------------------- | ---------- |
| `height`, `mass`         | `"172"`, `"77"`, `"unknown"` | `int_or_none(x)` |
| `population`             | `"200000"`, `"1,358"`, `"unknown"` | strip commas, then `int_or_none` |
| `diameter`               | `"0"` for missing, otherwise int-able | `int_or_none`, treat `0` as missing |
| `cost_in_credits`        | `"150000"`, `"unknown"` | strip commas, then `int_or_none` |
| `birth_year`             | `"19BBY"`, `"unknown"`  | keep as string; parse with regex if needed |
| `gravity`                | `"1 standard"`, `"0.9 standard"`, `"1.5 (surface), 1 standard (Cloud City)"` | not reliably numeric — keep as string or extract first float |
| `length`                 | `"36.8 "` (trailing space) | `strip()` first |
| `average_lifespan`       | `"120"`, `"indefinite"`, `"unknown"` | `int_or_none` |
| `homeworld` (Droid)      | `null`                  | `None` → MSSQL `NULL` |
| `language`               | `"Galatic Basic"` (typo), `"n/a"`, `"unknown"` | keep as-is |
| `gender`                 | `male`, `female`, `n/a`, `hermaphrodite`, `none`, `unknown` | keep as string or map to enum |

## Cross-resource relationships (quick view)

```
people.homeworld      → planets
people.films          → films
people.species        → species
people.vehicles       → vehicles
people.starships      → starships
planets.residents     → people
planets.films         → films
species.homeworld     → planets
species.people        → people
species.films         → films
films.characters      → people
films.planets         → planets
films.species         → species
films.starships       → starships
films.vehicles        → vehicles
vehicles.pilots       → people
starships.pilots      → people
```

## ETL recipe for `swapi_db` (MSSQL)

```sql
-- After fetching all 6 collections to JSON, normalize into:

Planets        (id, name, climate, terrain, gravity,
                diameter INT NULL, population BIGINT NULL,
                surface_water VARCHAR(20) NULL,
                created DATETIME2, edited DATETIME2)
Species        (id, name, classification, designation,
                avg_height INT NULL, avg_lifespan INT NULL,
                language, homeworld_id INT NULL)
People         (id, name, height INT NULL, mass INT NULL,
                hair_color, skin_color, eye_color,
                birth_year, gender,
                homeworld_id INT NULL)
Starships      (id, name, model, manufacturer,
                cost_credits BIGINT NULL, length DECIMAL(10,2) NULL,
                hyperdrive_rating VARCHAR(10) NULL,
                MGLT VARCHAR(10) NULL, starship_class)
Vehicles       (id, name, model, manufacturer,
                cost_credits BIGINT NULL, length DECIMAL(10,2) NULL,
                vehicle_class)
Films          (id, title, episode_id, director, producer,
                release_date DATE, opening_crawl NVARCHAR(MAX))

-- M2M bridges
FilmPeople       (film_id, person_id)
FilmPlanets      (film_id, planet_id)
FilmSpecies      (film_id, species_id)
FilmStarships    (film_id, starship_id)
FilmVehicles     (film_id, vehicle_id)
PersonStarships  (person_id, starship_id)
PersonVehicles   (person_id, vehicle_id)
PersonSpecies    (person_id, species_id)
```

The `id` column is the numeric tail of the URL (`https://swapi.info/api/people/1` → `1`).
