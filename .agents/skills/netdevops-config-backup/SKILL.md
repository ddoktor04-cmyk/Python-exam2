---
name: netdevops-config-backup
description: Archive network device running and startup configs to local files and optionally commit them to a Git repository. Use when the user asks to "back up", "snapshot", "archive", or "save" device configurations, run a daily backup job, capture pre-change and post-change snapshots, or build a config history in Git. Triggers on requests to fetch and persist a config, generate a tarball of device configs, or wire up a cron/Task Scheduler job for nightly backups.
license: MIT
compatibility: Requires Python 3.10+ and netmiko installed. Git operations require the git CLI on PATH.
allowed-tools: Bash(python:*) Bash(git:*) Read
---

# Back up device configs to disk and Git

This skill fetches `show running-config` (and optionally `show startup-config`)
from each device in an inventory, writes a normalized file per device, and
optionally commits the changes to Git. Use it as a daily cron / Task
Scheduler job, or as a pre-change snapshot before any push.

## When to use
- The user wants a snapshot of one or many devices' running configs.
- The user wants a pre-change / post-change baseline.
- The user wants nightly backups committed to a Git repo (config history).

## When NOT to use
- The user wants to render a config locally with no device contact → `netdevops-config-render`.
- The user wants to push a config change → `netdevops-connect` + manual
  `send_config_set` (no auto-push without explicit approval).

## Workflow

1. **Load inventory.** Read a YAML inventory file. Each entry has at least
   `host`, `device_type`. Credentials come from env vars.
2. **Connect and fetch.** For each device, open a netmiko session (use the
   `netdevops-connect` skill) and run:
   - `show running-config` (always)
   - `show startup-config` (optional, `--with-startup`)
3. **Normalize.** Strip the build-specific trailing line (`end`, `}`) and
   trim trailing whitespace per line so diffs are meaningful.
4. **Write.** Save to `backups/<hostname>/running.conf` (and `startup.conf`).
   Create the directory if it doesn't exist.
5. **Git commit** (optional). If `--git` is set, stage the changed files
   and commit with a message like `backup: 2025-01-15T08:00:00Z r1 r2 r3`.
6. **Report.** Print a summary table: hostname, status, byte count, git
   commit SHA (if any).

## Inventory shape

```yaml
# inventories/devices.yaml
hosts:
  - host: 10.0.0.1
    hostname: r1
    device_type: cisco_ios
    site: dc1
  - host: 10.0.0.2
    hostname: r2
    device_type: cisco_ios
    site: dc1
  - host: 10.0.0.3
    hostname: sw1
    device_type: arista_eos
    site: dc1
```

A bare host list is also accepted (positional `host:device_type`).

## Bundled script usage

```bash
python scripts/backup_config.py \
  --inventory inventories/devices.yaml \
  --out backups \
  --with-startup \
  --git --git-remote origin
```

Flags:
- `--inventory` (required): YAML file with hosts.
- `--out` (default `backups`): root output directory.
- `--with-startup`: also fetch `show startup-config`.
- `--git`: stage and commit changed files in `--out`.
- `--git-remote` (default `origin`): remote used for `git push` (if `--push`).
- `--push`: also `git push` after committing (requires credentials).
- `--concurrency 10`: max parallel devices (uses a thread pool).

## Gotchas

- **Trailing `end` / `}`** — some platforms emit a config terminator that
  changes between software versions. Strip it before storing so diffs
  reflect only real changes.
- **Sensitive data** — running configs may contain community strings,
  keys, passwords. Treat the backups directory as sensitive: git-crypt or
  a private repo only.
- **Write memory** on Cisco IOS — `show running-config` is fine; `write
  memory` is a write op, never call it from a backup script.
- **Timeouts** — `show running-config` on big devices can take 30+ s.
  Set `read_timeout=120` in the device dict.
- **Idempotence** — if the running config didn't change, do not commit.
  Compute a SHA-256 of the normalized output and skip the commit.
- **Time zone** — always use UTC in the commit message and the directory
  name (`backups/2025-01-15T080000Z/`).

## Scheduling

### Linux / cron
```cron
0 3 * * *  cd /opt/netdevops && /usr/bin/python .agents/skills/netdevops-config-backup/scripts/backup_config.py \
  --inventory inventories/devices.yaml --out backups --with-startup --git --push
```

### Windows Task Scheduler
```powershell
$Action = New-ScheduledTaskAction `
  -Execute "python.exe" `
  -Argument '.agents\skills\netdevops-config-backup\scripts\backup_config.py --inventory inventories\devices.yaml --out backups --with-startup --git'
$Trigger = New-ScheduledTaskTrigger -Daily -At 03:00
Register-ScheduledTask -TaskName "netdevops-backup" -Action $Action -Trigger $Trigger
```

## Failure handling

- If a device times out, log the failure, write a `.error` marker file
  with the exception, and continue with the rest of the inventory.
- The script returns exit 0 if at least one device succeeded; non-zero
  only on a global failure (inventory load, git, IO).
