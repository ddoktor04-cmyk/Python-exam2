# Naming and directory conventions for config backups

## Directory layout

```
backups/
├── .git/                          # the backup repo
├── r1/
│   ├── 2025-01-15T030000Z/
│   │   ├── running.conf
│   │   └── startup.conf
│   └── 2025-01-16T030000Z/
│       ├── running.conf
│       └── startup.conf
├── r2/
│   └── ...
└── sw1/
    └── ...
```

- One folder per device, named with the device's `hostname` (not the IP).
- Inside, one subfolder per backup run, named with the **UTC** timestamp
  in `YYYY-MM-DDTHHMMSSZ` form (sortable, no spaces).
- Inside the timestamp folder, one file per config type:
  `running.conf`, `startup.conf`, optionally `candidate.conf` or
  `previous.conf` for pre-change baselines.

## Filename conventions

| Filename          | Meaning                                               |
| ----------------- | ----------------------------------------------------- |
| `running.conf`    | `show running-config` (or `show configuration`)       |
| `startup.conf`    | `show startup-config` (or `show startup-configuration`) |
| `candidate.conf`  | NETCONF `candidate` datastore (Juniper)               |
| `previous.conf`   | Pre-change baseline                                   |
| `ERROR.txt`       | Marker file with the exception text on failure        |
| `meta.json`       | Per-run metadata: software version, uptime, who ran   |

## File-level normalization

Always normalize before writing so diffs reflect only real config changes:

1. Strip the trailing terminator (`end` for IOS/IOS-XE/NX-OS, `}` for
   Nokia SR OS, `</configuration>` for Junos XML if you captured XML).
2. `rstrip()` each line — eliminates trailing whitespace drift.
3. Ensure exactly one trailing newline.
4. Convert CRLF to LF (Git handles this anyway, but be explicit).

## Commit messages

```
backup: 2025-01-15T030000Z r1 r2 r3
backup: 2025-01-15T030000Z r1 (pre-change: BGP MD5 rotation)
```

The first form is the daily cron run. The second form is for ad-hoc
pre-change snapshots — the change reason goes in parentheses.

## What NOT to commit

- Live decrypted credentials (enable secrets, RADIUS keys, SNMPv3 keys).
  Mask them with `9 "$1$" ...` placeholders in the YAML source of truth,
  or use `sed` redaction at backup time:
  ```bash
  sed -E -i 's/(secret|password|key) [^ \n]+/***REDACTED***/g' running.conf
  ```
- ACL hits / accounting data — out of scope for config backup.
- Core dumps, packet captures, tech-support output.

## Retention

- Keep daily snapshots for 30 days.
- Keep weekly snapshots for 6 months.
- Keep monthly snapshots for 5 years.
- Implement via `git gc` + a `cron` script that prunes old timestamp
  directories before re-pushing.

## Git hygiene

- One backup repo per region / site, not one global repo with
  thousands of devices (keeps clone/push fast).
- Use a dedicated SSH key with read-write access only to the backup repo.
- Restrict the repo to a small group of operators.
- If using GitHub/GitLab, enable signed commits and branch protection.
