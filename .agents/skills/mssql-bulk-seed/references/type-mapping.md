# Column name → faker provider mapping

## Auto-mapping rules (regex, case-insensitive)

The seed skill tries column-name patterns first; if no pattern matches,
it falls back to a SQL-type-based generator. Use `--column-map` YAML to
override either layer.

| Column name pattern                       | Faker provider             | Notes                            |
| ----------------------------------------- | -------------------------- | -------------------------------- |
| `id` / `guid` / `uuid`                    | `uuid4`                    | Only when SQL type is `uniqueidentifier`; otherwise int fallback |
| `first_name` / `fname` / `given_name`     | `first_name`               |                                  |
| `last_name` / `lname` / `surname`         | `last_name`                |                                  |
| `full_name` / `display_name`              | `name`                     |                                  |
| `email` / `e_mail` / `mail`               | `email`                    |                                  |
| `phone` / `tel` / `mobile` / `msisdn`     | `phone_number`             |                                  |
| `country`                                 | `country`                  |                                  |
| `city` / `town` / `locality`              | `city`                     |                                  |
| `street` / `address` / `addr`             | `street_address`           |                                  |
| `zip` / `zipcode` / `postcode` / `postal_code` | `postcode`             |                                  |
| `company` / `organization` / `org`        | `company`                  |                                  |
| `username` / `login` / `user_name`        | `user_name`                |                                  |
| `salary` / `amount` / `price` / `cost`    | random int 25k–180k, step 1k | Currency-ish                     |
| `age`                                     | random int 18–80           |                                  |
| `created_at` / `updated_at` / `modified_at` | `date_time_this_decade`  |                                  |
| `dob` / `birth_date` / `birthday`         | `date_of_birth`            |                                  |

## Type fallback

| SQL Server type                          | Generator                                |
| ---------------------------------------- | ---------------------------------------- |
| `uniqueidentifier`                       | `uuid4()`                                |
| `int` / `bigint` / `smallint` / `tinyint` | random int 1–100 000                    |
| `decimal` / `numeric` / `money` / `smallmoney` | `pydecimal(0, 10 000, right_digits=scale)` |
| `float` / `real`                         | `pyfloat(0, 10 000)`                     |
| `bit`                                    | `boolean()`                              |
| `date`                                   | `date_object()`                          |
| `datetime` / `datetime2` / `smalldatetime` | `date_time_this_decade()`               |
| `time`                                   | `time_object()`                          |
| `varchar` / `nvarchar` / `char` / `nchar` | `text()` truncated to `min(max_length, 200)` |
| `text` / `ntext`                         | `text()` (≤ 200 chars)                   |
| `binary` / `varbinary`                   | `binary(length=16)`                      |
| `xml` / `json` / `geography` / `geometry` | SKIP with warning                       |

## Identity and computed columns

Both are detected from `sys.columns.is_identity` / `is_computed` and
always skipped — the database fills them.

## Custom mapping with `--column-map`

```yaml
# map.yaml
salary: salary
status: random_element
country: country
```

The right-hand side is the faker provider name. You can also pass
arguments inline by mapping to a specific generator — for that, fork
the script and add a `Faker` `add_provider` rule.

## Why heuristics, not LLM guessing

Real schemas are large. A name-based heuristic with a type fallback
covers > 90% of practical tables in seconds, with no per-call LLM cost.
For exotic schemas, the YAML override is the explicit escape hatch.
