"""Fetch data from the Star Wars API (swapi.info) with optional URL expansion.

Examples:
    python swapi_fetch.py people
    python swapi_fetch.py people --expand homeworld,films
    python swapi_fetch.py planets --select name,climate,terrain,population --format md
    python swapi_fetch.py people/1 --expand homeworld,films
    python swapi_fetch.py species --cache-ttl 3600 --out species.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import httpx

logger = logging.getLogger("netdevops.swapi")
DEFAULT_BASE = "https://swapi.info/api"
NAME_FIELD = {
    "films": "title",
    "people": "name",
    "planets": "name",
    "species": "name",
    "vehicles": "name",
    "starships": "name",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource", help="people, people/1, planets, films, …")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--expand", default=None,
                        help="Comma-separated URL field names to resolve into names")
    parser.add_argument("--select", default=None,
                        help="Comma-separated scalar fields to keep")
    parser.add_argument("--keep-urls", action="store_true",
                        help="Keep <field>_urls alongside the resolved field")
    parser.add_argument("--format", choices=["json", "csv", "md"], default="json")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/swapi"))
    parser.add_argument("--cache-ttl", type=int, default=0,
                        help="Reuse cached responses within N seconds (0 = disabled)")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-concurrency", type=int, default=8)
    return parser.parse_args()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )


def cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{digest}.json"


def cached_get(client: httpx.Client, url: str, cache_dir: Path, ttl: int) -> Any:
    path = cache_path(cache_dir, url)
    if ttl > 0 and path.exists():
        age = time.time() - path.stat().st_mtime
        if age < ttl:
            logger.info("cache hit", extra={"url": url, "age_s": int(age)})
            return json.loads(path.read_text(encoding="utf-8"))
    logger.info("fetch", extra={"url": url})
    resp = client.get(url, timeout=30)
    if resp.status_code >= 400:
        raise SystemExit(f"FAILED: HTTP {resp.status_code} at {url}")
    payload = resp.json()
    if ttl > 0:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def resolve_resource_name(url: str) -> str | None:
    m = re.match(r".*/api/([^/]+)/(\d+)/?$", url)
    if not m:
        return None
    resource, _ = m.group(1), m.group(2)
    return NAME_FIELD.get(resource)


def expand_field(
    records: list[dict[str, Any]],
    field: str,
    client: httpx.Client,
    cache_dir: Path,
    ttl: int,
    url_cache: dict[str, Any],
    concurrency: int,
) -> None:
    urls: set[str] = set()
    for r in records:
        v = r.get(field)
        if isinstance(v, str):
            urls.add(v)
        elif isinstance(v, list):
            urls.update(x for x in v if isinstance(x, str))

    def fetch(u: str) -> Any:
        if u in url_cache:
            return url_cache[u]
        url_cache[u] = cached_get(client, u, cache_dir, ttl)
        return url_cache[u]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for _ in pool.map(fetch, urls):
            pass

    for r in records:
        v = r.get(field)
        target_field = NAME_FIELD.get(
            re.match(r".*/api/([^/]+)/", (v if isinstance(v, str) else (v[0] if v else "")) or "").group(1)
            if isinstance(v, str) or (isinstance(v, list) and v)
            else ""
        ) or "name"
        if isinstance(v, str):
            r[field] = (url_cache.get(v) or {}).get(target_field)
        elif isinstance(v, list):
            r[field] = [(url_cache.get(u) or {}).get(target_field) for u in v]


def apply_select(records: list[dict[str, Any]], select: list[str] | None) -> list[dict[str, Any]]:
    if not select:
        return records
    out = []
    for r in records:
        out.append({k: r.get(k) for k in select if k in r})
    return out


def render_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def render_csv(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    keys: list[str] = []
    for r in records:
        for k in r:
            if k not in keys:
                keys.append(k)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(keys)
    for r in records:
        row = []
        for k in keys:
            v = r.get(k)
            if isinstance(v, list):
                row.append(";".join("" if x is None else str(x) for x in v))
            elif v is None:
                row.append("")
            else:
                row.append(v)
        writer.writerow(row)
    return buf.getvalue()


def render_md(records: list[dict[str, Any]]) -> str:
    if not records:
        return "(no rows)\n"
    keys: list[str] = []
    for r in records:
        for k in r:
            if k not in keys:
                keys.append(k)
    out = io.StringIO()
    out.write("| " + " | ".join(keys) + " |\n")
    out.write("|" + "|".join("---" for _ in keys) + "|\n")
    for r in records:
        cells = []
        for k in keys:
            v = r.get(k)
            if isinstance(v, list):
                cells.append("; ".join("" if x is None else str(x) for x in v))
            elif v is None:
                cells.append("")
            else:
                cells.append(str(v).replace("|", "\\|").replace("\n", " "))
        out.write("| " + " | ".join(cells) + " |\n")
    return out.getvalue()


def fetch_top_level(client: httpx.Client, base: str, resource: str,
                    cache_dir: Path, ttl: int) -> list[dict[str, Any]] | dict[str, Any]:
    if "/" in resource:
        url = f"{base.rstrip('/')}/{resource}"
        return cached_get(client, url, cache_dir, ttl)
    url = f"{base.rstrip('/')}/{resource}"
    payload = cached_get(client, url, cache_dir, ttl)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "results" in payload:
        return payload["results"]
    return [payload]


def main() -> int:
    configure_logging()
    args = parse_args()

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    expand = [s.strip() for s in (args.expand or "").split(",") if s.strip()]
    select = [s.strip() for s in (args.select or "").split(",") if s.strip()]

    with httpx.Client(timeout=args.timeout) as client:
        try:
            data = fetch_top_level(client, args.base, args.resource,
                                   args.cache_dir, args.cache_ttl)
        except (httpx.HTTPError, OSError) as exc:
            logger.exception("network error")
            print(f"FAILED: {exc}", file=sys.stderr)
            return 2

        records = data if isinstance(data, list) else [data]

        if expand:
            url_cache: dict[str, Any] = {}
            for field in expand:
                if not any(isinstance(r.get(field), (str, list)) for r in records):
                    print(f"no such field to expand: {field}", file=sys.stderr)
                    return 4
                expand_field(
                    records=records,
                    field=field,
                    client=client,
                    cache_dir=args.cache_dir,
                    ttl=args.cache_ttl,
                    url_cache=url_cache,
                    concurrency=args.max_concurrency,
                )

    records = apply_select(records, select)

    renderers: dict[str, Callable[[Any], str]] = {
        "json": render_json,
        "csv": render_csv,
        "md": render_md,
    }
    if args.format in ("csv", "md") and not records:
        output = ""
    else:
        output = renderers[args.format](records)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        print(f"saved to {args.out} ({len(records)} record(s))", file=sys.stderr)
    else:
        sys.stdout.write(output)
        if output and not output.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
