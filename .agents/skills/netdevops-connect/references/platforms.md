# Platform reference for netmiko `device_type`

Use this table to pick the correct `device_type` value. The wrong one
will cause netmiko to fail prompt detection.

| Vendor / OS                | `device_type`           | Notes                                                 |
| -------------------------- | ----------------------- | ----------------------------------------------------- |
| Cisco IOS / IOS XE         | `cisco_ios`             | Most ISR/ASR/Catalyst                                 |
| Cisco IOS XR               | `cisco_xr`              | IOS XR prompt ends in `#` or `>`                      |
| Cisco NX-OS                | `cisco_nxos`            | Nexus 9k/7k/5k/3k; supports `read_timeout` tuning     |
| Cisco ASA                  | `cisco_asa`             | Use `secret=` for enable                              |
| Arista EOS                 | `arista_eos`            | eAPI is faster for structured output                  |
| Juniper Junos              | `juniper_junos`         | Netconf (`ncclient`) is preferable for Junos          |
| Nokia SR OS                | `nokia_sros`            | MD-CLI needs `conn_timeout` tuning                    |
| HPE Comware (Aruba)        | `hp_comware`            | 5930/5940/Aruba CX uses different type                |
| Huawei VRP                 | `huawei`                | CloudEngine switches                                  |
| MikroTik RouterOS          | `mikrotik_routeros`     | SSH port 22 by default                                |
| Linux host                 | `linux`                 | For Linux-based NOS (Cumulus, SONiC, FRR)             |

## Connection transport

By default, netmiko uses SSH. To switch:

- `session_log`: writes the entire SSH transcript to a file — invaluable
  for debugging regex/parsing issues.
- `fast_cli=True`: skips some delays, faster but less compatible.
- `disable_lf_normalization=True`: keep CRLF as-is for Windows shells.

## Timeouts

| Knob             | Default | When to raise                          |
| ---------------- | ------- | -------------------------------------- |
| `timeout`        | 60 s    | Slow WAN links                         |
| `session_timeout`| 60 s    | Long-running commands                 |
| `auth_timeout`   | 6 s     | TACACS/RADIUS with slow response       |
| `banner_timeout` | 5 s     | Devices behind login/legal banners     |
| `read_timeout`   | 10 s    | `show tech-support`, large tables      |

## Auth methods

| Method              | How                                              |
| ------------------- | ------------------------------------------------ |
| Password            | `password=...`                                   |
| SSH key             | `use_keys=True`, default key in `~/.ssh/`        |
| Enable secret       | `secret=...` then call `conn.enable()`           |
| TACACS              | Same as password; ensure TACACS reachable        |
| Jump host / bastion | `ssh_config_file=True` + `~/.ssh/config` entries |

## NETCONF vs RESTCONF vs eAPI vs SSH

| API      | Library       | When to pick                                 |
| -------- | ------------- | -------------------------------------------- |
| SSH/CLI  | `netmiko`     | Default. Works on any device with SSH.       |
| NETCONF  | `ncclient`    | YANG-modeled config, atomic transactions.    |
| RESTCONF | `httpx`       | HTTP-friendly, structured JSON/XML payloads. |
| gNMI     | `pygnmi`      | Streaming telemetry, modern telemetry stack. |
| eAPI     | `httpx`       | Arista EOS native JSON-RPC.                  |
| NX-API   | `requests`    | Cisco Nexus HTTP API.                        |

Choose the most structured option you can — it eliminates parsing fragility.
