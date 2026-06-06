---
name: netdevops-config-render
description: Render network device configurations from Jinja2 templates using a YAML data source. Use when the user asks to generate, build, template, or render a router or switch config, prepare a BGP/OSPF/VLAN/interface stanza, or build a dry-run diff against a target config. Triggers on "render", "template", "generate config", "dry run", "show me the config for", or any request that combines a Jinja2 template with per-host YAML vars.
license: MIT
compatibility: Requires Python 3.10+ and jinja2, pyyaml, pydantic installed.
allowed-tools: Bash(python:*) Read
---

# Render a network config from a Jinja2 template

This skill produces a deterministic, validated config string from a Jinja2
template plus a YAML data file. It is the safe "left half" of any config
push — combine it with `netdevops-connect` to actually deploy.

## When to use
- The user provides a Jinja2 template (`.j2`) and a YAML vars file and
  wants the rendered config printed or written to disk.
- The user wants a **dry-run diff** between the rendered config and the
  current running config fetched from a device.
- The user wants per-host config generation (loop over an inventory).

## When NOT to use
- The user just wants to "show" something on a live device → `netdevops-connect`.
- The user wants to archive configs to Git → `netdevops-config-backup`.

## Workflow (plan-validate-render-diff)

1. **Plan**: locate the template and the vars file. If the user didn't
   specify, ask which template and which host vars to use.
2. **Validate**: run `scripts/validate_vars.py` against a pydantic model
   if the template has an associated schema. Refuse to render on validation
   failure.
3. **Render**: run `scripts/render_config.py` with
   `StrictUndefined` so missing variables fail loudly.
4. **Diff** (optional): if a current config is available, run a unified
   diff with `--diff current.txt`. Do not deploy if the diff contains
   unexpected sections — confirm with the user first.
5. **Write** (optional): if the user approves, write to
   `rendered/<host>/<template>.conf`.

## Input shapes

### Template directory layout
```
templates/
├── bgp.j2
├── interfaces/
│   ├── loopback.j2
│   └── physical.j2
└── _macros.j2         # imported with {% import ... %}
```

### Vars file shape (per host)
```yaml
# inventories/r1.yaml
hostname: r1
loopback:
  ip: 10.255.0.1
  mask: 32
bgp:
  asn: 65001
  neighbors:
    - ip: 10.0.0.2
      remote_as: 65002
      description: "to r2"
```

### Schema (optional, pydantic)
```python
# schemas/r1.py
from pydantic import BaseModel, IPvAnyAddress

class BgpNeighbor(BaseModel):
    ip: IPvAnyAddress
    remote_as: int
    description: str | None = None

class HostVars(BaseModel):
    hostname: str
    loopback: dict
    bgp: dict
```

## Bundled script usage

```bash
python scripts/render_config.py \
  --templates templates \
  --vars inventories/r1.yaml \
  --template bgp.j2 \
  --out rendered/r1/bgp.conf
```

Flags:
- `--strict` (default true): fail on any undefined variable.
- `--diff rendered/r1/bgp.conf` to compare against a saved current config.
- `--validate schema.py:HostVars` to run a pydantic check on the merged vars.

## Gotchas

- `UndefinedError` on render means a var is missing in the YAML — **do
  not** relax to `Undefined`; it silently produces broken configs.
- `trim_blocks` and `lstrip_blocks` should be on; otherwise newlines and
  indentation produce duplicate blank lines in the output.
- For NX-OS / IOS-XR, line endings are CRLF — don't strip them.
- The template must not call external programs; if it does, refactor to
  a filter (`yaml.safe_load` of an inline data block) and keep rendering
  pure.
- When looping, sort collections (`neighbors | sort(attribute='ip')`) to
  guarantee byte-stable output — useful for Git diffs and idempotent
  deploys.

## Output expectations

The script returns:
- Exit 0 and writes the rendered config to `--out` (or stdout if omitted).
- Exit 2 on validation failure (pydantic).
- Exit 3 on render failure (missing variable, template error).
- Exit 4 on diff failure if `--strict-diff` is set and the diff is non-empty.

The user must confirm any push to a live device. Never auto-apply.
