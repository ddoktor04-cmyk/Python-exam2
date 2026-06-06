# Output formats for `mssql-query`

The `--format` flag picks a renderer. Pick by consumer:

| Format  | Best for                                         | Truncates? | Streams? |
| ------- | ------------------------------------------------ | ---------- | -------- |
| `text`  | Quick interactive read, terminal-friendly table  | No         | No       |
| `json`  | Piping into another script or `jq`               | No         | No       |
| `csv`   | Spreadsheet / pandas / Excel                     | No         | No       |
| `md`    | Markdown reports, PR comments                    | Yes (cells escaped) | No |

Default is `text`.

## text

Fixed-width, left-aligned, no truncation. Long values push the table
wide. Suitable for `head -n 20` style eyeballing.

```
UsersID  name       surname    email                    country   salary
-------  ---------  ---------  -----------------------  --------  ------
1        Danielle   Johnson    danielle.johnson@...     Ecuador   164000
```

NULLs render as empty. Dates and decimals are stringified.

## json

```json
[
  {
    "UsersID": 1,
    "name": "Danielle",
    "surname": "Johnson",
    "email": "danielle.johnson@yahoo.com",
    "country": "Ecuador",
    "salary": 164000
  }
]
```

- `datetime` / `date` → ISO 8601 strings.
- `Decimal` → float.
- `bytes` → hex string.
- `None` → `null`.

Pipe into `jq`:
```bash
python scripts/run_query.py --database SuperCompany \
  --query "SELECT * FROM dbo.Users" --format json \
  | jq '.[] | select(.salary > 100000) | {name, salary}'
```

## csv

RFC 4180 with `\n` line endings (Excel-friendly on Windows).

- First row is the header.
- NULLs become empty fields.
- No quoting unless the field contains a comma, quote, or newline.
- Dates and decimals are stringified.

```csv
UsersID,name,surname,email,country,city,salary
1,Danielle,Johnson,danielle.johnson@yahoo.com,Ecuador,...
```

Use `csv.DictReader` to consume:
```python
import csv, sys
for row in csv.DictReader(sys.stdin):
    print(row["name"], row["salary"])
```

## md

GitHub-flavored Markdown table.

- `|` inside cell values is escaped as `\|`.
- Newlines inside cell values are replaced with a space.
- Suitable for pasting into PR comments or reports.

```markdown
| UsersID | name      | surname | email                       | country | salary |
| ------- | --------- | ------- | --------------------------- | ------- | ------ |
| 1       | Danielle  | Johnson | danielle.johnson@yahoo.com  | Ecuador | 164000 |
```

## When to pick what

- Ad-hoc inspection → `text`.
- Programmatic use → `json` (typed) or `csv` (flat).
- Reporting / documentation → `md`.
- Wide result sets (30+ columns) → `csv` or `json`, not `text`.
