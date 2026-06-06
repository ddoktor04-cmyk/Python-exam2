---
name: swapi-fetch
description: Fetch data from the Star Wars API (swapi.info) — full collections, single resources, with optional URL expansion (resolve homeworld/films/species references to names) and export to JSON, CSV, or Markdown. Use when the user asks to "get all people", "list characters", "show me Luke Skywalker", "fetch planets from SWAPI", "expand the homeworld field", "give me a CSV of all starships", or any read-only pull from the Star Wars API.
license: MIT
compatibility: Requires Python 3.10+ and httpx installed. No auth, no API key. Reads/writes under the project root (cache/ + --out).
allowed-tools: Bash(python:*) Read
---

# Fetch data from the Star Wars API (SWAPI)

This skill is the canonical way to pull data from `https://swapi.info/api`.
It handles the three common patterns: full collection, single resource,
and **expansion** of HATEOAS-style URL references into denormalized
records (e.g., `homeworld: <url>` → `homeworld: "Tatooine"`).

## When to use
- The user wants a list of people, planets, films, species, vehicles, or
  starships.
- The user wants a single character/planet/etc. by ID.
- The user wants the data exported to a file (JSON / CSV / Markdown).
- The user wants URLs in the result replaced by their referent names —
  e.g., resolve `homeworld`, `films`, `species` into readable strings.
- The user is seeding `swapi_db` in MSSQL or any other destination and
  needs the raw JSON first.

## When NOT to use
- The user wants to **mutate** SWAPI → impossible, the API is read-only.
- The user wants to load data into MSSQL → use `mssql-bulk-seed` after
  saving the JSON with this skill and pointing the seed at a `--source`
  URL/file.
- The user wants a **custom query** that SWAPI doesn't support (filter,
  join, aggregate) → fetch everything with this skill, then process the
  JSON locally with Python, jq, or DuckDB.

## Workflow (plan-fetch-shape-export)

1. **Plan** the request:
   - Which resource: `people`, `planets`, `films`, `species`,
     `vehicles`, `starships`? (case-insensitive, singular OK)
   - Full collection or single record (`<resource>/<id>`)?
   - Which URL fields to expand? Common picks: `homeworld`, `films`,
     `species`, `residents`, `characters`, `planets`, `starships`,
     `vehicles`, `people`, `pilots`.
   - Which scalar fields to keep (`--select`)?
   - Output format and destination (`--format`, `--out`).
2. **Fetch**: open a connection, set a sane timeout, hit the API. Use
   the in-script cache (`--cache-ttl`) for repeated runs — SWAPI is
   static, no need to hammer it.
3. **Shape**:
   - If `--expand` is given, resolve each listed field by following the
     URL(s) and pulling the right name field. Films use `title`, all
     other resources use `name`. Results are merged in-memory; URLs
     remain accessible as the original `*_urls` field if you ask for
     `--keep-urls`.
   - If `--select` is given, drop everything else.
4. **Export**: render to JSON, CSV, or Markdown. CSV and Markdown
   require a flat record (no list-of-objects); use `--expand` to
   denormalize lists, or accept that lists become `;`-joined strings.

## Bundled script usage

```bash
# All 83 people, JSON to stdout
python scripts/swapi_fetch.py people

# All people, with homeworld resolved to planet name
python scripts/swapi_fetch.py people --expand homeworld

# Resolve multiple references, pick scalar fields, CSV
python scripts/swapi_fetch.py people \
  --expand homeworld,films --select name,height,mass,homeworld,films \
  --format csv --out people.csv

# A single person, expanded
python scripts/swapi_fetch.py people/1 --expand homeworld,films

# Markdown table for a report
python scripts/swapi_fetch.py planets --select name,climate,terrain,population --format md

# Cache responses for 1 hour to avoid re-fetching
python scripts/swapi_fetch.py species --cache-ttl 3600 --out species.json
```

Flags:
- `--base` (default `https://swapi.info/api`): the API root.
- `--expand` (repeat / comma-list): URL fields to resolve into names.
- `--select` (comma-list): scalar fields to keep.
- `--keep-urls` (default false): also keep `<field>_urls` next to the
  resolved `<field>` so you don't lose the original references.
- `--format` (default `json`): `json` | `csv` | `md`.
- `--out` (default stdout): output file path.
- `--cache-dir` (default `.cache/swapi`): where to store raw JSON.
- `--cache-ttl` (default 0 = disabled): seconds to reuse a cached
  response. Useful for ETL pipelines.
- `--timeout` (default 30 s): HTTP timeout.
- `--max-concurrency` (default 8): parallel requests when expanding.

## Expansion rules

| Resource whose URL appears | Field used as the resolved name |
| --- | --- |
| `films/...`                | `title` |
| `people/...`, `planets/...`, `species/...`, `vehicles/...`, `starships/...` | `name` |

For list fields (`films`, `species`, `people`, `pilots`, etc.),
expansion produces a list of names. For scalar fields (`homeworld`),
it produces a single name (or `None` for `null`, e.g., Droid → `None`).

A small URL → name cache is held in memory, so expanding both
`homeworld` and `films` for `people` only re-fetches each `planet`
once even if 80 people point to Tatooine.

## Gotchas

- **Numeric fields are strings** in SWAPI — `height`, `mass`, `diameter`,
  `population`, `cost_in_credits`, `crew`, `passengers`, `length`. CSV
  / MD export keeps them as-is; cast to int/float downstream.
- **Type-coercion text values**: many fields use `"unknown"`, `"n/a"`,
  or `""` for missing data. Don't treat empty string as null. Helper:
  - `mass: "unknown"` → `None` if you want to ETL
  - `population: "1,358"` → strip commas before `int()`
  - `birth_year: "19BBY"` → keep as string, parse later with regex
- **Trailing whitespace** in some strings (`length: "36.8 "`) — strip
  before storing.
- **No pagination** on the public collection endpoints — they return
  the full list in one call. The old `swapi.dev` had pagination; this
  one doesn't.
- **Caching is opt-in**. Without `--cache-ttl`, every run is a fresh
  fetch. Use cache for ETL loops.
- **CORS / TLS** is fine on the public host. If you hit it from a
  locked-down environment, the script supports `--base` for an
  internal mirror.
- **CSV / MD with nested lists**: `--format csv` joins list fields with
  `;` and URL fields with `;`. For real ETL, prefer JSON output and a
  downstream normalizer.

## Output expectations

- Exit 0 on success.
- Exit 2 on connection / DNS / TLS error.
- Exit 3 on HTTP 4xx/5xx (prints status + URL).
- Exit 4 on a malformed `--expand` field name.
- Exit 5 on a write / cache error.

Final stdout/stderr shape:

```
$ python swapi_fetch.py people --expand homeworld --format md
| name | height | homeworld |
| --- | --- | --- |
| Luke Skywalker | 172 | Tatooine |
| ... |

$ echo $?         # 0 on success
$ python swapi_fetch.py people/9999
FAILED: HTTP 404 at https://swapi.info/api/people/9999
$ echo $?         # 3
```
