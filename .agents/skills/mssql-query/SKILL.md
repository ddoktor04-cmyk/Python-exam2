---
name: mssql-query
description: Run a SQL Server query and return results in text, JSON, CSV, or Markdown table format. Use when the user asks to "run a query", "show me rows from X", "select Y", "how many Z", "group by", "give me a sample of", or any other request that needs actual data out of MSSQL. Read-only by default; INSERT/UPDATE/DELETE/DDL require explicit --allow-write.
license: MIT
compatibility: Requires Python 3.10+ and pymssql installed. Reads DB_IP, DB_USER, DB_PASSWORD from .env in the project root.
allowed-tools: Bash(python:*) Read
---

# Run a SQL Server query

This skill executes a single SQL statement against MSSQL and prints (or
saves) the result in a chosen format. It is the canonical way to fetch
data with this agent.

## When to use
- The user wants data from a specific table or a custom query result.
- The user wants results exported to a file (JSON / CSV / Markdown).
- The user wants to sanity-check a query before putting it in code.
- The user wants a quick aggregation (`SELECT COUNT(*) ... GROUP BY ...`).

## When NOT to use
- The user wants to **browse schema** (databases, tables, columns) → `mssql-schema-inspect`.
- The user wants to **insert synthetic seed data** → `mssql-bulk-seed`.
- The user wants to **change data** (INSERT/UPDATE/DELETE) and the
  intent is durable state — confirm with the user, then use
  `--allow-write` only after explicit approval.

## Workflow (plan-validate-execute)

1. **Plan** the query. Identify the target database, the tables, and
   whether the query is read-only.
2. **Validate**:
   - Strip leading whitespace and comments.
   - Take the first keyword.
   - Allow list: `SELECT`, `WITH` (CTE), `PRINT`, `EXEC`/`EXECUTE` of
     a stored procedure that returns rows, `SET` for `SET IDENTITY_INSERT`
     only when `--allow-write` is also passed.
   - Reject if first keyword is `INSERT`, `UPDATE`, `DELETE`, `MERGE`,
     `DROP`, `CREATE`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`, `BULK`,
     `OPENROWSET`, `OPENDATASOURCE` — unless `--allow-write` is given.
3. **Execute**: open a connection to `--database` (default `master`),
   set a query timeout, run the statement, fetch all rows.
4. **Format**: render to the chosen `--format` and either print to
   stdout or write to `--save`.

## Bundled script usage

```bash
# Inline query
python scripts/run_query.py --database SuperCompany \
  --query "SELECT TOP 5 name, surname, salary FROM dbo.Users ORDER BY salary DESC"

# With explicit format
python scripts/run_query.py --database SuperCompany --format json --max-rows 100 \
  --query "SELECT country, COUNT(*) AS n FROM dbo.Users GROUP BY country"

# Save to file
python scripts/run_query.py --database SuperCompany --format csv \
  --query "SELECT * FROM dbo.Users" \
  --save out.csv

# Markdown table for a report
python scripts/run_query.py --database SuperCompany --format md \
  --query "SELECT TOP 20 * FROM dbo.Users ORDER BY UsersID"
```

Flags:
- `--query` (required): the SQL statement.
- `--database` (default `master`): target database.
- `--format` (default `text`): `text` | `json` | `csv` | `md`.
- `--max-rows` (default 10000): hard cap on rows returned; truncates
  output and prints a warning.
- `--timeout` (default 30 s): query timeout.
- `--save` (default none): write to this file instead of stdout.
- `--allow-write`: required to run any non-read-only statement.
- `--show-affected`: print the rowcount for write statements (only
  meaningful with `--allow-write`).

## Gotchas

- **`TOP` vs `OFFSET ... FETCH`**: prefer `OFFSET 0 ROWS FETCH NEXT N ROWS ONLY`
  for paging; `TOP` is fine for ad-hoc.
- **NULLs** in print rendering show as `None` (Python repr). In CSV
  output they are empty strings; in JSON they are `null`.
- **Date / datetime values** are converted to ISO 8601 in JSON output
  via the `default=str` hook.
- **DECIMAL / NUMERIC** come back as `Decimal` — pymssql handles this.
  In `text` output they are stringified; in `csv` they are stringified.
- **Wide rows** in `text` mode: the renderer left-aligns and does NOT
  truncate. If your row has 30 columns, expect long output. Use `md`
  or `csv` for wide rows.
- **Comments** in SQL: `--` and `/* */` are stripped before the
  read-only check.
- **`SET NOCOUNT ON`** is sent at the start of every connection to
  suppress rowcount chatter from intermediate statements.
- **GO batch separators** are not supported — this skill runs a single
  statement. If the user supplies multiple statements, only the first
  runs and the rest are silently ignored. Use the SQL Server client
  for batched scripts.

## Output expectations

- Exit 0 on success.
- Exit 1 on a SQL syntax or runtime error (the message is printed to
  stderr).
- Exit 2 on connection / auth / .env failure.
- Exit 3 on a read-only violation without `--allow-write`.
- Exit 4 on timeout (row limit or query timeout).

Always print the row count and the elapsed time after the result.
