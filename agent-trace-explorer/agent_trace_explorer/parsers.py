from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import Event, Trace


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{i}: invalid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"{path}:{i}: expected JSON object")
        rows.append(obj)
    return rows


def detect_format(rows: list[dict]) -> str:
    if not rows:
        return "generic"
    if any("event" in r and r.get("event") in {"run_start", "task_start", "grade", "task_end", "run_end"} for r in rows):
        return "vec-bench"
    if any(r.get("type") in {"assistant", "user", "result", "system"} and "message" in r for r in rows):
        return "claude"
    return "generic"


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def parse_vec(rows: list[dict], source: str) -> Trace:
    events = []
    for i, row in enumerate(rows):
        text = row.get("text")
        if row.get("event") == "grade" and text is None:
            text = "PASS" if row.get("passed") else "FAIL"
        events.append(Event(i, row.get("ts"), str(row.get("event", "event")), row.get("task_id"), _as_text(text), dict(row)))
    return Trace(source, "vec-bench", events)


def _claude_content_events(row: dict, index_start: int) -> list[Event]:
    typ = str(row.get("type", "event"))
    ts = row.get("timestamp") or row.get("ts")
    msg = row.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    out: list[Event] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "text":
                out.append(Event(index_start + len(out), ts, "assistant_text", text=_as_text(item.get("text")), data=row))
            elif kind == "tool_use":
                name = item.get("name", "tool")
                out.append(Event(index_start + len(out), ts, "tool_use", text=str(name), data={"tool": item, "record": row}))
            elif kind == "tool_result":
                out.append(Event(index_start + len(out), ts, "tool_result", text=_as_text(item.get("content")), data={"tool_result": item, "record": row}))
    if out:
        return out
    if typ == "result":
        text = row.get("result")
    else:
        text = msg if isinstance(msg, str) else row.get("content") or row.get("result")
    return [Event(index_start, ts, typ, text=_as_text(text), data=row)]


def parse_claude(rows: list[dict], source: str) -> Trace:
    events: list[Event] = []
    for row in rows:
        events.extend(_claude_content_events(row, len(events)))
    return Trace(source, "claude", events)


def parse_generic(rows: list[dict], source: str) -> Trace:
    events = []
    for i, row in enumerate(rows):
        ts = row.get("ts") or row.get("timestamp") or row.get("time")
        event = row.get("event") or row.get("type") or row.get("kind") or "event"
        task = row.get("task_id") or row.get("task")
        text = row.get("text")
        if text is None:
            text = row.get("message")
        if text is None:
            text = row.get("content")
        events.append(Event(i, _as_text(ts), str(event), _as_text(task), _as_text(text), dict(row)))
    return Trace(source, "generic", events)


def load_trace(path: str | Path, fmt: str = "auto") -> Trace:
    path = Path(path)
    rows = _read_jsonl(path)
    resolved = detect_format(rows) if fmt == "auto" else fmt
    if resolved == "vec-bench":
        return parse_vec(rows, str(path))
    if resolved == "claude":
        return parse_claude(rows, str(path))
    if resolved == "generic":
        return parse_generic(rows, str(path))
    raise ValueError(f"unknown format: {fmt}")
