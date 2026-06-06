---
name: netdevops-connect
description: Connect to network devices via SSH (netmiko/scrapli), NETCONF (ncclient), or HTTP RESTCONF/eAPI. Use when the user asks to reach a router, switch, or firewall, run a "show" command, fetch the running config, push configuration, or troubleshoot a connection problem. Triggers on tasks involving Cisco IOS/IOS-XE/IOS-XR/NX-OS, Arista EOS, Juniper Junos, Nokia SR OS, or any device reachable over the management network.
license: MIT
compatibility: Requires Python 3.10+ and the netmiko, scrapli, ncclient packages installed.
allowed-tools: Bash(python:*) Read
---

# Connect to a network device

This skill gives you a safe, vendor-aware pattern for opening a session to a
network device, running a read-only command (or sending a config), and closing
the session cleanly.

## When to use
- The user asks to "show", "get", "fetch", "collect" something from a device.
- The user provides an inventory entry (host, platform, credentials) and
  wants a script that opens a session.
- The user is debugging a failed connection (auth, timeout, banner, host key).

## When NOT to use
- Pure local config rendering with no device contact → use `netdevops-config-render`.
- Bulk config archival without running commands → use `netdevops-config-backup`.

## Workflow

1. **Resolve credentials.** Read from env vars or a vault. Never hardcode.
   Expected env vars: `NETDEV_USER`, `NETDEV_PASSWORD`, `NETDEV_ENABLE` (optional).
2. **Build the device dict.** `device_type` is mandatory for netmiko.
   See `references/platforms.md` for the canonical `device_type` per platform.
3. **Open the session.** Use `scripts/connect_device.py` — it tries
   `netmiko.ConnectHandler` first and falls back to `scrapli` if installed
   and requested. Both raise on auth/timeout errors; let the exception
   propagate so the caller can log it.
4. **Run the command.** Prefer `send_command` (read) or `send_config_set`
   (write) on netmiko. Always set `read_timeout` and `session_log` for
   troubleshooting.
5. **Close the session.** Use a context manager (`with`) or a `try/finally`.

## Reference inputs

A device spec is a plain dict. Example:

```python
device = {
    "host": "10.0.0.1",
    "device_type": "cisco_ios",
    "username": "netops",
    "password": "...",      # from env, never literal
    "port": 22,
    "timeout": 30,
    "session_log": "logs/10.0.0.1.log",
}
```

For NETCONF, replace netmiko with `ncclient`:

```python
from ncclient import manager
with manager.connect(
    host=device["host"],
    port=830,
    username=device["username"],
    password=device["password"],
    hostkey_verify=False,   # lab only; verify in prod
    allow_agent=False,
    look_for_keys=False,
    device_params={"name": "default"},
) as m:
    config = m.get_config(source="running").data_xml
```

For RESTCONF / eAPI, use `httpx` and vendor-specific headers. See
`references/platforms.md` for the exact URL shape per platform.

## Gotchas

- `cisco_ios` vs `cisco_xe` vs `cisco_xr` vs `cisco_nxos` are different
  `device_type` values. Pick the right one or netmiko will hang on
  the wrong prompt pattern.
- Juniper `junos` devices often need `ssh_config_file=True` and a known host
  key. Use `scrapli` with `auth_strict_key=False` only in lab.
- Nokia SR OS uses `nokia_sros` and requires MD-CLI or classic CLI mode
  set explicitly via `conn_timeout`/`timeout` tuning.
- Always pass `banner_timeout` separately — devices behind a TACACS banner
  will hang with the default 5 s.
- If the user says "the device is slow", raise `read_timeout` to 120 s and
  set `conn_timeout` to 20 s before retrying.

## Bundled script

Run `python scripts/connect_device.py --device-type cisco_ios --host 10.0.0.1 --command "show version"`
to verify the script in your environment. The script:

- Reads `NETDEV_USER` and `NETDEV_PASSWORD` from the environment.
- Opens a netmiko session.
- Runs the command with TextFSM parsing (`--use-textfsm`).
- Prints the result as JSON to stdout.
- Returns exit code 0 on success, non-zero on any netmiko exception.
