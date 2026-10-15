#!/usr/bin/env python3
"""Fetch public Virtual Embryo leaderboard snapshots (standard library only).

Writes the raw API responses, unchanged, to snapshots/<UTC date>/:
    <board key with ':' replaced by '_'>.json   one per board
    overall.json                                 team totals

One snapshot per UTC date. If that date's folder already holds a file, it is
skipped, so running this twice on the same day does nothing new.
Exit status is 1 if any request failed; files that did fetch are still written.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
import urllib.request
from pathlib import Path

API = "https://api.virtualembryo.ai/challenge"
BOARDS = ["T1:val", "T2:heart:val_interp", "T2:heart:val_extrap", "T2:embryo:val_interp", "T3:gata4"]
HERE = Path(__file__).resolve().parent
SNAP_ROOT = HERE / "snapshots"
USER_AGENT = "leaderboard-anatomy/1.0 (github.com/i-habib/virtual-embryo-community)"
TIMEOUT_S = 30
TRIES = 3


def file_name(key: str) -> str:
    return key.replace(":", "_") + ".json"


def get_json(url: str) -> bytes:
    """Return the response body if it parses as a JSON object, retrying on failure."""
    last: Exception | None = None
    for attempt in range(1, TRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                body = resp.read()
            obj = json.loads(body.decode("utf-8"))
            if not isinstance(obj, dict):
                raise ValueError("response is not a JSON object")
            return body
        except Exception as exc:  # network, HTTP, or JSON error: retry, then report
            last = exc
            if attempt < TRIES:
                time.sleep(5 * attempt)
    raise RuntimeError(f"{url}: {last}")


def check_board(body: bytes, key: str) -> None:
    obj = json.loads(body)
    if obj.get("board") != key:
        raise ValueError(f"board field is {obj.get('board')!r}, expected {key!r}")
    if not isinstance(obj.get("rows"), list) or not obj["rows"]:
        raise ValueError("no rows")


def write_atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)


def main() -> int:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    out_dir = SNAP_ROOT / today
    failures: list[str] = []

    targets = [(key, f"{API}/leaderboard?board={urllib.request.quote(key, safe='')}") for key in BOARDS]
    targets.append(("overall", f"{API}/overall"))

    for key, url in targets:
        name = "overall.json" if key == "overall" else file_name(key)
        path = out_dir / name
        if path.exists():
            print(f"skip   {today}/{name} (already fetched today)")
            continue
        try:
            body = get_json(url)
            if key != "overall":
                check_board(body, key)
            write_atomic(path, body)
            print(f"wrote  {today}/{name} ({len(body)} bytes)")
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            print(f"FAILED {name}: {exc}", file=sys.stderr)

    if failures:
        print(f"{len(failures)} request(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
