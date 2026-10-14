from __future__ import annotations

from collections import Counter
from typing import Any

from .model import Trace

_TASK_FIELDS = ("passed", "grader_passed", "returncode", "timed_out", "duration_seconds", "peak_rss_mb", "artifacts")


def _task_record(details: dict[str, dict[str, Any]], task_id: str) -> dict[str, Any]:
    return details.setdefault(task_id, {k: (0 if k == "artifacts" else None) for k in _TASK_FIELDS})


def summarize(trace: Trace) -> dict[str, Any]:
    counts = Counter(e.event for e in trace.events)
    details: dict[str, dict[str, Any]] = {}
    artifacts = 0
    stderr_lines = 0
    tool_calls = 0
    for e in trace.events:
        if e.event == "artifact":
            artifacts += 1
        if e.event in {"agent_stderr", "stderr", "error"}:
            stderr_lines += 1
        if e.event in {"tool_use", "tool_call"}:
            tool_calls += 1
        if not e.task_id:
            continue
        if e.event == "grade":
            _task_record(details, e.task_id)["grader_passed"] = bool(e.data.get("passed"))
        elif e.event == "artifact":
            _task_record(details, e.task_id)["artifacts"] += 1
        elif e.event == "agent_exit":
            rec = _task_record(details, e.task_id)
            rec["returncode"] = e.data.get("returncode")
            rec["timed_out"] = bool(e.data.get("timed_out"))
        elif e.event == "task_end":
            rec = _task_record(details, e.task_id)
            # The harness writes passed = grader_passed and returncode 0 and not timed_out.
            # Older traces have no grader_passed field; their passed field is the verdict.
            if "passed" in e.data:
                rec["passed"] = bool(e.data["passed"])
            if "grader_passed" in e.data:
                rec["grader_passed"] = bool(e.data["grader_passed"])
            for key in ("returncode", "timed_out", "duration_seconds", "peak_rss_mb"):
                if key in e.data:
                    rec[key] = e.data[key]
    # Official verdict per task: task_end.passed when present, otherwise the grader's verdict alone.
    task_grades = {}
    for task_id, rec in details.items():
        verdict = rec["passed"] if rec["passed"] is not None else rec["grader_passed"]
        if verdict is not None:
            task_grades[task_id] = bool(verdict)
    durations = [float(r["duration_seconds"]) for r in details.values() if r["duration_seconds"] is not None]
    rss = [float(r["peak_rss_mb"]) for r in details.values() if r["peak_rss_mb"] is not None]
    run_end = next((e for e in reversed(trace.events) if e.event == "run_end"), None)
    if run_end:
        passed = run_end.data.get("tasks_passed")
        total = run_end.data.get("tasks_total")
    else:
        passed = sum(task_grades.values()) if task_grades else None
        total = len(task_grades) if task_grades else None
    return {
        "source": trace.source,
        "format": trace.format,
        "events": len(trace.events),
        "event_counts": dict(counts),
        "tasks_passed": passed,
        "tasks_total": total,
        "task_grades": task_grades,
        "task_details": details,
        "duration_seconds_total": round(sum(durations), 4) if durations else None,
        "peak_rss_mb_max": round(max(rss), 3) if rss else None,
        "tool_calls": tool_calls,
        "stderr_lines": stderr_lines,
        "artifacts": artifacts,
    }
