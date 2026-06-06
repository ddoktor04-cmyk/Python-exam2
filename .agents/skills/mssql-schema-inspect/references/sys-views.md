# Useful system views and DMVs in SQL Server

## Schema metadata

| View                                  | Scope                       | Notes                              |
| ------------------------------------- | --------------------------- | ---------------------------------- |
| `sys.databases`                       | Server                      | All DBs incl. state, recovery, ID  |
| `sys.tables`                          | Database                    | User + system tables               |
| `sys.columns` + `sys.types`           | Database                    | Type, length, nullability, identity|
| `sys.indexes` + `sys.index_columns`   | Database                    | PK, unique, included columns       |
| `sys.key_constraints`                 | Database                    | PK, UNIQUE constraints             |
| `sys.foreign_keys` + `_columns`       | Database                    | FK definitions                     |
| `sys.default_constraints`             | Database                    | Column defaults                    |
| `sys.schemas`                         | Database                    | Schema list (dbo, sys, guest, ...) |
| `INFORMATION_SCHEMA.*`                | Database                    | Portable; less rich than `sys.*`   |

## Sizes and storage

| View                      | Notes                                                |
| ------------------------- | ---------------------------------------------------- |
| `sys.master_files`        | One row per file (mdf/ndf/ldf), size in 8 KB pages   |
| `sys.database_files`      | Same, scoped to the current DB                       |
| `sys.partitions`          | `rows` column gives fast approximate row count       |
| `sys.dm_db_partition_stats` | More accurate row counts per partition              |
| `sp_spaceused`            | Stored proc, returns size + row count for a table   |

Row count rule of thumb: `sys.partitions` for a quick number, true
`COUNT(*)` only when you need exact.

## Activity and performance

| View                              | Notes                                 |
| --------------------------------- | ------------------------------------- |
| `sys.dm_exec_sessions`            | Active sessions                       |
| `sys.dm_exec_requests`            | Currently running requests            |
| `sys.dm_exec_query_stats`         | Aggregated query stats                |
| `sys.dm_tran_active_transactions` | Open transactions                     |
| `sys.dm_os_wait_stats`            | Wait stats since server start         |

## Useful one-liners

### Total size per database (MB)
```sql
SELECT
    d.name,
    CAST(SUM(mf.size) * 8.0 / 1024 AS DECIMAL(10,2)) AS size_mb
FROM sys.databases d
JOIN sys.master_files mf ON mf.database_id = d.database_id
GROUP BY d.name
ORDER BY size_mb DESC;
```

### Tables by row count
```sql
SELECT TOP 20
    s.name + '.' + t.name AS [table],
    p.rows AS [rows]
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
WHERE s.name = 'dbo'
ORDER BY p.rows DESC;
```

### Unused indexes (no seeks, many updates)
```sql
SELECT
    OBJECT_NAME(i.object_id) AS [table],
    i.name AS [index],
    s.user_seeks, s.user_scans, s.user_lookups, s.user_updates
FROM sys.indexes i
LEFT JOIN sys.dm_db_index_usage_stats s
    ON s.object_id = i.object_id AND s.index_id = i.index_id
WHERE OBJECTPROPERTY(i.object_id, 'IsUserTable') = 1
  AND s.user_updates > 100
  AND COALESCE(s.user_seeks, 0) + COALESCE(s.user_scans, 0) = 0
ORDER BY s.user_updates DESC;
```

## Identifier quoting

Always use `[brackets]` for identifiers — single quotes are for string
literals, double quotes are non-standard.

```sql
SELECT * FROM [dbo].[Users] WHERE [name] = 'alice';
```

If a name contains `]` itself, double it: `[[a]]b]` selects the literal
column `[a]b`.
