# Jinja2 patterns for network configs

## Strict undefined

Always set `StrictUndefined`. A missing variable should crash the render,
not produce an empty string.

```python
from jinja2 import Environment, FileSystemLoader, StrictUndefined
env = Environment(
    loader=FileSystemLoader("templates"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
```

## Whitespace control

`trim_blocks=True` removes the newline after a block tag. `lstrip_blocks=True`
strips leading whitespace from a line that begins with a block tag. Both on
together eliminate "double blank line" bugs.

## Stable ordering for idempotent output

Sort loops over lists and dicts to keep rendered output byte-stable. Git
diffs become meaningful and the deployed config doesn't change between
runs when the data is equivalent.

```jinja
{% for n in bgp.neighbors | sort(attribute='ip') %}
 neighbor {{ n.ip }} remote-as {{ n.remote_as }}
{% endfor %}
```

## Macros for repeated stanzas

```jinja
{# _macros.j2 #}
{% macro interface(name, ip, mask, descr=None) %}
interface {{ name }}
 ip address {{ ip }} {{ mask }}
{% if descr %}
 description {{ descr }}
{% endif %}
!
{% endmacro %}
```

```jinja
{% import "_macros.j2" as m %}
{{ m.interface("Loopback0", loopback.ip, loopback.mask) }}
```

## Conditional sections

```jinja
{% if features.ospf %}
router ospf {{ ospf.process_id }}
 router-id {{ ospf.router_id }}
{% for n in ospf.networks %}
 network {{ n.ip }} {{ n.wildcard }} area {{ n.area }}
{% endfor %}
{% endif %}
```

## Filters to expose

Register these in `env.filters` to keep templates readable:

```python
env.filters["ip_network"] = lambda s: ipaddress.ip_network(s)
env.filters["wildcard"] = lambda n: n.hostmask
env.filters["asplain"] = lambda asn: f"{asn}" if asn < 65536 else f"{asn}.{asn >> 16 & 0xFFFF}"
```

Use in a template:
```jinja
network {{ net | ip_network }} wildcard {{ net | wildcard }} area 0
```

## Anti-patterns

- ❌ Calling `subprocess` from a template — keep rendering pure.
- ❌ Hardcoding device-specific values inside the template — pass them
  through vars.
- ❌ Using `{% set %}` for top-level values that should live in YAML.
- ❌ Putting secrets in templates — render a placeholder and overlay
  secrets from a vault at deploy time.
