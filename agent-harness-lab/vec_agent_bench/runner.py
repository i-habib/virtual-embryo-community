from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import psutil

from . import __version__
from .tasks import TASK_BY_ID, TASKS
from .util import json_dump, sha256_file


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TraceWriter:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def emit(self, event: str, **data) -> None:
        row = {"ts": _ts(), "event": event, **data}
        with self.lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _command_argv(template: str, *, prompt: str, prompt_file: Path, workspace: Path, task_id: str) -> list[str]:
    argv = shlex.split(template)
    values = {
        "{prompt}": prompt,
        "{prompt_file}": str(prompt_file),
        "{workspace}": str(workspace),
        "{task_id}": task_id,
    }
    return [values.get(arg, arg) for arg in argv]


def _monitor_rss(pid: int, stop: threading.Event, state: dict) -> None:
    peak = 0
    try:
        proc = psutil.Process(pid)
    except psutil.Error:
        return
    while not stop.wait(0.05):
        total = 0
        try:
            procs = [proc] + proc.children(recursive=True)
            for p in procs:
                try:
                    total += p.memory_info().rss
                except psutil.Error:
                    pass
        except psutil.Error:
            pass
        peak = max(peak, total)
    state["peak_rss_bytes"] = peak


def _stream(pipe, trace: TraceWriter, event: str, task_id: str) -> None:
    try:
        for line in iter(pipe.readline, ""):
            trace.emit(event, task_id=task_id, text=line.rstrip("\n"))
    finally:
        pipe.close()


def _file_snapshot(workspace: Path) -> dict[str, tuple[int, str]]:
    out = {}
    for p in sorted(workspace.rglob("*")):
        if not p.is_file() or p.name == "PROMPT.md":
            continue
        try:
            out[str(p.relative_to(workspace))] = (p.stat().st_size, sha256_file(p))
        except OSError:
            pass
    return out


def _artifact_rows(workspace: Path, before: dict[str, tuple[int, str]]) -> list[dict]:
    rows = []
    for rel, (size, digest) in _file_snapshot(workspace).items():
        if before.get(rel) == (size, digest):
            continue
        rows.append({"path": rel, "size_bytes": size, "sha256": digest})
    return rows


def run_benchmark(
    command: str,
    task_ids: Iterable[str],
    out_dir: Path,
    *,
    timeout_seconds: float = 300,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    task_root = out_dir / "tasks"
    task_root.mkdir(exist_ok=True)
    trace = TraceWriter(out_dir / "trace.jsonl")
    selected = [TASK_BY_ID[t] for t in task_ids]
    trace.emit("run_start", benchmark_version=__version__, command_template=command, tasks=[t.id for t in selected])

    results = []
    for task in selected:
        workspace = task_root / task.id
        if workspace.exists():
            import shutil
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        task.prepare(workspace)
        prompt_file = workspace / "PROMPT.md"
        prompt_file.write_text(task.prompt.strip() + "\n", encoding="utf-8")
        before_files = _file_snapshot(workspace)

        env = os.environ.copy()
        env.update(
            {
                "VEC_BENCH_TASK_ID": task.id,
                "VEC_BENCH_WORKSPACE": str(workspace.resolve()),
                "VEC_BENCH_PROMPT_FILE": str(prompt_file.resolve()),
                "VEC_BENCH_PROMPT": task.prompt.strip(),
            }
        )
        argv = _command_argv(
            command,
            prompt=task.prompt.strip(),
            prompt_file=prompt_file.resolve(),
            workspace=workspace.resolve(),
            task_id=task.id,
        )
        trace.emit("task_start", task_id=task.id, title=task.title, argv=argv)
        started = time.monotonic()
        timed_out = False
        proc = subprocess.Popen(
            argv,
            cwd=workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        rss_stop = threading.Event()
        rss_state = {}
        threads = [
            threading.Thread(target=_stream, args=(proc.stdout, trace, "agent_stdout", task.id), daemon=True),
            threading.Thread(target=_stream, args=(proc.stderr, trace, "agent_stderr", task.id), daemon=True),
            threading.Thread(target=_monitor_rss, args=(proc.pid, rss_stop, rss_state), daemon=True),
        ]
        for th in threads:
            th.start()
        try:
            returncode = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            returncode = proc.wait()
        rss_stop.set()
        for th in threads:
            th.join(timeout=2)

        duration = time.monotonic() - started
        grade = task.grade(workspace)
        for art in _artifact_rows(workspace, before_files):
            trace.emit("artifact", task_id=task.id, **art)
        trace.emit("grade", task_id=task.id, **grade)
        peak_mb = rss_state.get("peak_rss_bytes", 0) / (1024 * 1024)
        row = {
            "task_id": task.id,
            "title": task.title,
            "passed": bool(grade["passed"]),
            "returncode": int(returncode),
            "timed_out": timed_out,
            "duration_seconds": round(duration, 4),
            "peak_rss_mb": round(peak_mb, 3),
            "checks": grade.get("checks", []),
        }
        results.append(row)
        trace.emit("task_end", **row)

    summary = {
        "benchmark_version": __version__,
        "tasks_passed": sum(r["passed"] for r in results),
        "tasks_total": len(results),
        "results": results,
    }
    json_dump(out_dir / "summary.json", summary)
    trace.emit("run_end", tasks_passed=summary["tasks_passed"], tasks_total=summary["tasks_total"])
    return summary


def task_ids(spec: str) -> list[str]:
    if spec.strip().lower() == "all":
        return [t.id for t in TASKS]
    ids = [x.strip() for x in spec.split(",") if x.strip()]
    unknown = [x for x in ids if x not in TASK_BY_ID]
    if unknown:
        raise ValueError(f"unknown task(s): {', '.join(unknown)}")
    return ids
