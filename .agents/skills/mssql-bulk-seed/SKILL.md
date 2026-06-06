---
name: mssql-bulk-seed
description: Generate and insert N synthetic rows into a SQL Server table. Use when the user asks to "seed", "populate", "fill", "generate test data for", "load fake users into", "create 1000 rows of demo data", or wants to backfill a table with realistic but obviously fake records. Triggers on any "bulk insert synthetic data" workflow that combines a target table name with a row count.
license: MIT
compatibility: Requires Python 3.10+, pymssql, and faker installed. Reads DB_IP, DB_USER, DB_PASSWORD from .env in the project root.
allowed-tools: Bash(python:*) Read
---

# Seed a SQL Server table with synthetic data

This skill introspects a target table, maps each column to a faker
provider by name and SQL type, and inserts N rows in batched executemany
calls. It is the fast path for creating demo / dev / test data.

## When to use
- The user wants N synthetic rows in a specific table for testing,
  demos, or development.
- The user wants to repopulate a table that has gone stale.
- The user is benchmarking a query or load-testing a pipeline.

## When NOT to use
- The user wants **real** data — refuse. Generate fake data only.
- The user wants to update existing rows → not what this skill does;
  redirect to a manual `UPDATE` via `mssql-query --allow-write`.
- The user wants to copy data between tables → also not this skill;
  use `INSERT ... SELECT` via `mssql-query --allow-write`.

## Workflow (plan-validate-execute)

1. **Plan**:
   - Confirm the target table (`--database`, `--schema`, `--table`).
   - Confirm `--rows` count.
   - Decide on `--truncate` (default off; refuse if the user didn't
     explicitly ask, since TRUNCATE is destructive).
2. **Validate**:
   - Introspect columns via `sys.columns` + `sys.types`.
   - For each column, resolve a generator:
     - identity columns → skipped (auto-fill).
     - computed columns → skipped.
     - explicit `NOT NULL` columns must map to a generator; warn if
       no mapping is found.
   - Refuse to seed a table with no identity / PK unless the user
     passed `--allow-no-pk`.
3. **Execute**:
   - If `--dry-run`, print the resolved column map and exit 0.
   - Open the connection, optionally `TRUNCATE`, then batched
     `executemany` insert with the column list in order.
   - Report progress every batch and a final summary.

## Bundled script usage

```bash
# Seed 1000 rows into a Users table
python scripts/bulk_seed.py \
  --database SuperCompany --schema dbo --table Users --rows 1000

# Truncate first (destructive — confirm with the user)
python scripts/bulk_seed.py \
  --database SuperCompany --table Users --rows 5000 --truncate

# Dry-run: show what generators would be used, do not insert
python scripts/bulk_seed.py --database SuperCompany --table Users --rows 100 --dry-run

# Reproducible: same seed → same data
python scripts/bulk_seed.py --database SuperCompany --table Users --rows 100 --seed 42
```

Flags:
- `--database` (required)
- `--schema` (default `dbo`)
- `--table` (required)
- `--rows` (default 1000)
- `--batch-size` (default 200)
- `--truncate` (action): empty the table first
- `--dry-run` (action): print the plan and exit
- `--seed` (default 42): reproducible random data
- `--column-map` (default none): YAML overriding the auto-mapping
- `--allow-no-pk` (action): allow seeding tables without a primary key

## Column-mapping logic

Each column is resolved by (a) name heuristics, then (b) SQL type.

| Column name pattern (regex, case-insensitive) | Faker provider           |
| --------------------------------------------- | ------------------------ |
| `^id$` and SQL type `uniqueidentifier`       | `uuid4`                  |
| `name\|first_name\|fname`                     | `first_name`             |
| `surname\|last_name\|lname\|family_name`      | `last_name`              |
| `full_name`                                   | `name`                   |
| `email\|e_mail\|mail`                         | `email`                  |
| `phone\|tel\|mobile`                          | `phone_number`           |
| `country`                                     | `country`                |
| `city\|town`                                  | `city`                   |
| `street\|address`                             | `street_address`         |
| `zip\|postcode\|postal_code`                  | `postcode`               |
| `company\|organization\|org`                  | `company`                |
| `username\|login\|user_name`                  | `user_name`              |
| `salary\|amount\|price\|cost`                 | random int 25k–180k      |
| `age`                                         | random int 18–80         |
| `created_at\|updated_at\|date` (datetime)     | `date_time_this_decade`  |
| `dob\|birth_date\|birthday`                   | `date_of_birth`          |

Type fallback (when no name match):

| SQL type                                  | Generator                       |
| ----------------------------------------- | ------------------------------- |
| `uniqueidentifier`                        | `uuid4`                         |
| `int`, `bigint`, `smallint`, `tinyint`    | random int 1–100_000            |
| `decimal`, `numeric`, `money`, `smallmoney` | `pydecimal` 0–10000, 2 places  |
| `float`, `real`                           | `pyfloat` 0–10000               |
| `bit`                                     | `boolean`                       |
| `date`                                    | `date_object`                   |
| `datetime`, `datetime2`, `smalldatetime`  | `date_time_this_decade`         |
| `time`                                    | `time_object`                   |
| `varchar`, `nvarchar`, `char`, `nchar`    | `text` (max_length truncated)   |
| `text`, `ntext`                           | `text`                          |
| `binary`, `varbinary`                     | `binary`                        |
| `xml`, `json`                             | SKIP with warning               |

`NOT NULL` columns with no mapping → the script aborts with a clear
error listing the unmapped columns.

## Gotchas

- **Identity columns**: never inserted explicitly; the script skips
  any column with `is_identity = 1`.
- **Computed columns**: also skipped.
- **`MAX` length columns**: `varchar(MAX)` is fine — the script
  generates a faker text of reasonable length (≤ 200 chars).
- **Truncating `text` to fit**: faker text is truncated to
  `min(max_length, 200)` to avoid rejected inserts.
- **NULLs**: if a column is nullable, the script inserts `NULL` for
  ~10% of rows to make the data more realistic. Toggle with
  `--null-rate 0.0` to disable.
- **FK references**: the script does NOT resolve foreign keys. It
  generates independent fake values. If a column is a FK to a
  `Users` table, the inserted IDs will be invalid — use
  `--column-map` to override or pre-load the referenced table.
- **Transactions**: the script uses autocommit OFF and commits after
  every batch. If a batch fails, only that batch is rolled back; the
  table is left partially populated. Re-running with `--truncate`
  cleans up.
- **Performance**: ~1k rows/s on a typical LAN. For >100k rows,
  raise `--batch-size` to 1000.

## Output expectations

- Exit 0 on success (and `--dry-run`).
- Exit 2 on connection / auth / .env failure.
- Exit 3 on a missing or ambiguous table.
- Exit 4 on an unmapped `NOT NULL` column.
- Exit 5 on an insert error (prints the failing batch and SQL state).

Print a summary: rows requested, rows inserted, elapsed time, batches.
