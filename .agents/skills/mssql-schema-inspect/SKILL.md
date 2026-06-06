---
name: mssql-schema-inspect
description: Browse a Microsoft SQL Server instance — list databases, tables, columns, primary keys, foreign keys, and indexes. Use when the user asks to "show databases", "list tables", "describe a table", "show schema", "what columns does X have", "what indexes are on Y", or wants to understand the structure of a database before writing a query. Triggers on any read-only exploration of MSSQL metadata.
license: MIT
compatibility: Requires Python 3.10+ and pymssql installed. Reads DB_IP, DB_USER, DB_PASSWORD from .env in the project root.
allowed-tools: Bash(python:*) Read
---

# Inspect a SQL Server schema

This skill gives a read-only, structured view of a SQL Server instance:
databases → schemas → tables → columns, keys, indexes. Use it to understand
a database before writing a query, designing a migration, or seeding data.

## When to use
- The user wants to know what databases exist on a server.
- The user wants to know what tables are in a specific database.
- The user wants column types, nullability, defaults, primary/foreign keys,
  or indexes for a specific table.
- The user wants row counts for one or all tables.

## When NOT to use
- The user wants to **run a query** for data → `mssql-query`.
- The user wants to **insert / update / DDL** → no MSSQL skill allows
  writes; refuse and ask the user to run the statement manually with
  explicit confirmation.
- The user wants to seed bulk data → `mssql-bulk-seed`.

## Workflow (escalating scope)

The script supports four sub-commands. Start at the top and drill down:

1. **`databases`** — list all databases (uses `sys.databases`).
2. **`tables --database X`** — list user tables in `X` with row counts.
3. **`columns --database X --table Y`** — list columns with type, length,
   nullability, default, identity, and primary-key flag.
4. **`keys --database X --table Y`** — list primary + foreign keys.
5. **`indexes --database X --table Y`** — list indexes (clustered,
   nonclustered, unique, included columns).

For most questions, run `databases` first to confirm the target, then
`tables` to pick the table, then `columns` / `keys` / `indexes` as needed.

## Bundled script usage

```bash
# Top-level: list databases
python scripts/inspect_schema.py databases

# Tables in a database
python scripts/inspect_schema.py tables --database SuperCompany

# Column details
python scripts/inspect_schema.py columns --database SuperCompany --table Users

# Keys
python scripts/inspect_schema.py keys --database SuperCompany --table Users

# Indexes
python scripts/inspect_schema.py indexes --database SuperCompany --table Users
```

The default output is a compact, fixed-width table. Add `--json` to get
machine-readable JSON instead — useful when piping into another script.

## Gotchas

- **Schemas other than `dbo`** — by default the script scopes to `dbo`.
  Use `--schema` to look at another schema (e.g., `--schema sales`).
- **`sys.columns` vs `INFORMATION_SCHEMA.COLUMNS`** — `INFORMATION_SCHEMA`
  is portable, `sys.*` is richer. This skill uses `sys.*` for identity,
  computed-column, and collation details.
- **Case-sensitive collations** — filter values in your flags
  (`--table Users` not `--table users`) match the database collation
  case-sensitivity. The default `SQL_Latin1_General_CP1_CI_AS` is
  case-insensitive so the script is forgiving.
- **Hidden / system tables** — the script filters out `sys`, `INFORMATION_SCHEMA`,
  and `guest`. If the user explicitly asks for system tables, pass `--include-system`.
- **Row counts** for very large tables use `sys.partitions` (fast, approximate)
  rather than `SELECT COUNT(*)` (exact, slow). The script uses the fast
  path by default. Add `--exact` to force a true count.
- **Quoting identifiers** — the script uses `[brackets]` to handle names
  with spaces or reserved words safely. Never use single quotes for
  identifiers.

## Output expectations

- Exit 0 on success.
- Exit 2 on a connection or auth failure.
- Exit 3 on a missing target (e.g., `--database` flag not given for
  `tables`).
- Exit 4 on an invalid identifier (database or table not found).

The script never modifies server state. It is safe to run repeatedly.
