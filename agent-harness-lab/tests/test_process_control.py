"""Regression tests for how the runner decides pass/fail and cleans up the agent process tree."""

import json
import shlex
import sys
import textwrap
import time

import psutil

from vec_agent_bench.runner import run_benchmark


def _agent_command(tmp_path, body: str) -> str:
    script = tmp_path / "agent.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"


def _events(trace_path, event):
    rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r["event"] == event]


COPY_PREVIOUS_STAGE = """
import os, shutil
from pathlib import Path
root = Path(os.environ["VEC_BENCH_WORKSPACE"])
shutil.copy2(root / "previous_stage.h5ad", root / "submission.h5ad")
"""


def test_nonzero_exit_fails_task_even_when_grader_accepts_output(tmp_path):
    command = _agent_command(tmp_path, COPY_PREVIOUS_STAGE + "\nimport sys\nsys.exit(3)\n")
    summary = run_benchmark(command, ["t2_copy_last"], tmp_path / "run", timeout_seconds=60)
    row = summary["results"][0]
    trace = tmp_path / "run" / "trace.jsonl"
    assert _events(trace, "grade")[0]["passed"] is True
    assert row["grader_passed"] is True
    assert row["returncode"] == 3
    assert row["passed"] is False
    assert summary["tasks_passed"] == 0
    assert _events(trace, "agent_exit")[0]["returncode"] == 3


def test_timeout_fails_task_even_when_grader_accepts_output(tmp_path):
    command = _agent_command(tmp_path, COPY_PREVIOUS_STAGE + "\nimport time\ntime.sleep(60)\n")
    summary = run_benchmark(command, ["t2_copy_last"], tmp_path / "run", timeout_seconds=3)
    row = summary["results"][0]
    trace = tmp_path / "run" / "trace.jsonl"
    assert _events(trace, "grade")[0]["passed"] is True
    assert row["timed_out"] is True
    assert row["passed"] is False
    assert _events(trace, "agent_exit")[0]["timed_out"] is True


def _gone(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return True
    return proc.status() == psutil.STATUS_ZOMBIE


def test_timeout_kills_grandchild_processes(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    body = f"""
    import subprocess, sys, time
    from pathlib import Path
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    Path({str(pidfile)!r}).write_text(str(child.pid))
    time.sleep(120)
    """
    command = _agent_command(tmp_path, body)
    summary = run_benchmark(command, ["inspect_h5ad"], tmp_path / "run", timeout_seconds=3)
    assert summary["results"][0]["timed_out"] is True
    assert pidfile.exists(), "agent never started its grandchild"
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 10
    while not _gone(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _gone(pid), f"grandchild {pid} survived the timeout"


def test_leftover_background_child_is_killed_after_normal_exit(tmp_path):
    pidfile = tmp_path / "leftover.pid"
    body = f"""
    import subprocess, sys
    from pathlib import Path
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    Path({str(pidfile)!r}).write_text(str(child.pid))
    """
    command = _agent_command(tmp_path, body)
    summary = run_benchmark(command, ["inspect_h5ad"], tmp_path / "run", timeout_seconds=60)
    assert summary["results"][0]["timed_out"] is False
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 10
    while not _gone(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _gone(pid), f"background child {pid} outlived the agent"
