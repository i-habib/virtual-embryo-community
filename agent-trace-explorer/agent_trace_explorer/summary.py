from __future__ import annotations

from collections import Counter
from typing import Any

from .model import Trace


def summarize(trace: Trace) -> dict[str, Any]:
    counts = Counter(e.event for e in trace.events)
    grades = {}
    durations = {}
    rss = {}
    artifacts = 0
    stderr_lines = 0
    tool_calls = 0
    for e in trace.events:
        if e.event == "grade" and e.task_id:
            grades[e.task_id] = bool(e.data.get("passed"))
        if e.event == "task_end" and e.task_id:
            if "duration_seconds" in e.data:
                durations[e.task_id] = float(e.data["duration_seconds"])
            if "peak_rss_mb" in e.data:
                rss[e.task_id] = float(e.data["peak_rss_mb"])
        if e.event == "artifact":
            artifacts += 1
        if e.event in {"agent_stderr", "stderr", "error"}:
            stderr_lines += 1
        if e.event in {"tool_use", "tool_call"}:
            tool_calls += 1
    run_end = next((e for e in reversed(trace.events) if e.event == "run_end"), None)
    if run_end:
        passed = run_end.data.get("tasks_passed")
        total = run_end.data.get("tasks_total")
    else:
        passed = sum(grades.values()) if grades else None
        total = len(grades) if grades else None
    return {"source": trace.source, "format": trace.format, "events": len(trace.events), "event_counts": dict(counts), "tasks_passed": passed, "tasks_total": total, "task_grades": grades, "duration_seconds_total": round(sum(durations.values()), 4) if durations else None, "peak_rss_mb_max": round(max(rss.values()), 3) if rss else None, "tool_calls": tool_calls, "stderr_lines": stderr_lines, "artifacts": artifacts}
