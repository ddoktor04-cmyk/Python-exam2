# NetDevOps Python Project

Automation toolkit for network engineering and Microsoft SQL Server, built around
the [Agent Skills](https://agentskills.io/specification) format. Each skill is a
self-contained workflow with `SKILL.md` (YAML frontmatter + instructions) plus
optional `scripts/` and `references/`.

## Skills

| Skill | Purpose |
| --- | --- |
| `netdevops-connect` | Connect to network devices (SSH / NETCONF / RESTCONF) |
| `netdevops-config-render` | Render configs from Jinja2 + pydantic validation |
| `netdevops-config-backup` | Archive device configs to Git (daily snapshot) |
| `mssql-schema-inspect` | Browse databases / tables / columns / keys / indexes |
| `mssql-query` | Run SELECT with `text` / `json` / `csv` / `md` output (read-only) |
| `mssql-bulk-seed` | Generate and bulk-insert N synthetic rows (faker) |
| `swapi-fetch` | Query Star Wars API (swapi.info) with URL resolution and disk cache |
| `swapi-etl` | Idempotent ETL of SWAPI into MSSQL `Starwars` DB (6 main + 10 junction tables) |

## Project Layout

```
.
├── AGENTS.md                # System prompt for the agent
├── README.md                # this file
├── .env.example             # Template for env vars (DB_*, NETDEV_*)
├── .gitignore               # Excludes .env, backups/, logs/, __pycache__/
├── requirements.txt         # Python dependencies
├── inventories/             # YAML host_vars for netdevops-config-render
├── templates/               # Jinja2 config templates
└── .agents/skills/          # All skills (agentskills.io format)
    └── <skill-name>/
        ├── SKILL.md
        ├── scripts/         # Executable scripts the skill calls
        └── references/      # Additional documentation
```

## Quick Start

```powershell
# 1. Clone and set up
git clone https://github.com/ddoktor04-cmyk/Python-exam2.git
cd Python-exam2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Configure environment (real values; never committed)
Copy-Item .env.example .env
notepad .env   # set DB_IP, DB_USER, DB_PASSWORD, NETDEV_PASSWORD, ...

# 3. Try a skill
python .agents/skills/mssql-query/scripts/run_query.py `
    --query "SELECT @@VERSION AS version" --format text
```

## Working Principles

1. **Source of truth in Git** — configs and schemas live in the repo.
2. **Idempotency** — re-runs do not change the end state.
3. **Dry-run before apply** — diff, syntax check, smoke test.
4. **Rollback plan** — every change has a reverse path; golden config + pre/post snapshot.
5. **Canary** — one device/DB first, then pilot group, then prod.
6. **Secrets in vault / `.env` only** — never in code or committed files.
7. **Read-only by default** — DB / device writes need explicit `--allow-write` and confirmation.
8. **Structured JSON logging** with correlation IDs.

## Configuration

All runtime values come from environment variables (see `.env.example`):

| Variable | Used by | Example |
| --- | --- | --- |
| `DB_IP` | mssql-* skills | `<your-mssql-host>` |
| `DB_USER` | mssql-* skills | `sa` |
| `DB_PASSWORD` | mssql-* skills | (do not commit) |
| `DB_NAME` | mssql-* skills | `master` |
| `NETDEV_USER` | netdevops-connect | `netops` |
| `NETDEV_PASSWORD` | netdevops-connect | (do not commit) |
| `NETDEV_ENABLE` | netdevops-connect (Cisco) | (do not commit) |
| `NETDEV_API_TOKEN` | netdevops-connect (RESTCONF/eAPI) | (do not commit) |
| `NETDEV_INVENTORY` | netdevops-config-render | `inventories/devices.yaml` |
| `NETDEV_BACKUP_ROOT` | netdevops-config-backup | `backups` |

`DB_*` is loaded by mssql-* and swapi-etl scripts that walk upward from CWD
and from the script's own location to find `.env`. This means a script works
the same whether called from the project root or a nested directory.

## Code Standards

- PEP 8, `ruff` / `black` for formatting, `mypy` for types.
- Type hints on all public functions and methods.
- Google or NumPy-style docstrings on modules, classes, public functions.
- `logging` (never `print` in production code); final CLI report may use `print`.
- Configuration via env vars or YAML/JSON; no hardcoded IPs / credentials / timeouts.
- Specific exceptions + correlation IDs + exponential backoff for transient errors.
  `except Exception` only in the top-level CLI handler.
- Exit codes: `0` ok, `2` env/auth, `3` schema, `4` usage/not-found, `5` runtime.
- Comments only where they explain *why*, never *what*.
- No emojis, no extra courtesy; concise technical output.

## Adding a New Skill

1. Pick a verb-based, lowercase name that matches the parent folder.
2. Write `SKILL.md` (YAML frontmatter with `name` + `description` ≤ 1024 chars,
   then Markdown instructions). Keep it under 500 lines; put details in
   `references/`.
3. Add `scripts/` for the executables the skill calls.
4. Document *when to use* and *when NOT to use* in `SKILL.md`.
5. Capture environment-specific gotchas.
6. Validate: `python -c "import ast; ast.parse(open(p).read())"` for all `.py`.
7. Run a smoke test against the live target (DB / API / device).

## License

Internal use.
