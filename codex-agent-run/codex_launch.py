#!/usr/bin/env python3
"""Run the locked `codex exec` command once and record what happened.

Usage:
  codex_launch.py RUNDIR

Steps: verify lock.json and every locked input (refuse on any change), write launch_state.json
as "running", start `codex exec --json` with the locked argv in the locked workspace, feed the
locked prompt copy on stdin (end of file after the prompt, so no terminal input), stream stdout
byte for byte into trajectory.jsonl and stderr into stderr.log, kill the process group at the
wall-clock budget, copy the Codex session (rollout) file from $CODEX_HOME/sessions, snapshot the
prediction directory, re-verify the locked inputs, and record start, end and exit code.

A run directory is launched once. A second attempt needs a new lock.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from codex_common import (
    SCHEMA, ToolError, check_locked_state, load_lock, thread_id_from_event, tree_listing,
    sha256_file, utc_now, write_json_new, write_json_replace,
)


def _pump(stream, sink, on_line) -> None:
    for line in iter(stream.readline, b""):
        sink.write(line)
        sink.flush()
        if on_line is not None:
            on_line(line)
    stream.close()


def _thread_id_from_line(line: bytes) -> str | None:
    try:
        return thread_id_from_event(json.loads(line))
    except ValueError:
        return None


def _terminate_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def _kill_leftovers(pgid: int) -> bool:
    """Stop processes the agent left running in the same process group. True if any were signalled."""
    try:
        os.killpg(pgid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return False


def find_rollouts(codex_home: Path, thread_id: str | None, start: float, end: float) -> tuple[list[Path], str]:
    """Session files under $CODEX_HOME/sessions. Matched by session id first, else by modification time."""
    root = codex_home / "sessions"
    if not root.is_dir():
        return [], "no sessions directory"
    candidates = [p for p in root.rglob("rollout-*") if p.is_file()]
    if thread_id:
        by_id = [p for p in candidates if thread_id in p.name]
        if by_id:
            return sorted(by_id), "session id"
    window = [p for p in candidates if start - 5 <= p.stat().st_mtime <= end + 5]
    return sorted(window), "time window"


def _launch(run: Path) -> int:
    lock = load_lock(run)
    if (run / "launch_state.json").exists():
        raise ToolError("this run directory was already launched; a run is launched once, make a new lock for another attempt")
    problems = check_locked_state(run, lock)
    if problems:
        raise ToolError("the lock no longer matches the files:\n  " + "\n  ".join(problems))

    ws = Path(lock["workspace"])
    pred_dir = ws / lock["predictions_dir"]
    if pred_dir.exists() and any(pred_dir.iterdir()):
        raise ToolError(f"{pred_dir} is not empty at launch")
    pred_dir.mkdir(parents=True, exist_ok=True)

    budget_s = lock["budget"]["wall_clock_seconds"]
    argv = lock["launch"]["argv"]
    state = {
        "schema": SCHEMA,
        "run_id": lock["run_id"],
        "status": "running",
        "started_utc": utc_now(),
        "argv": argv,
        "cwd": str(ws),
        "budget_seconds": budget_s,
        "warnings": [],
    }
    write_json_new(run / "launch_state.json", state)
    env = dict(os.environ)
    env["CODEX_HOME"] = lock["codex_home"]
    start_epoch = time.time()
    t0 = time.monotonic()

    thread = {"id": None}

    def on_line(line: bytes) -> None:
        if thread["id"] is None:
            thread["id"] = _thread_id_from_line(line)

    try:
        with open(run / "inputs" / "prompt.md", "rb") as stdin_fh, \
                open(run / "trajectory.jsonl", "xb") as traj, \
                open(run / "stderr.log", "xb") as errlog:
            proc = subprocess.Popen(argv, cwd=str(ws), stdin=stdin_fh, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=env, start_new_session=True)
            t_out = threading.Thread(target=_pump, args=(proc.stdout, traj, on_line), daemon=True)
            t_err = threading.Thread(target=_pump, args=(proc.stderr, errlog, None), daemon=True)
            t_out.start()
            t_err.start()
            timed_out = False
            try:
                rc = proc.wait(timeout=budget_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_group(proc)
                rc = proc.returncode
            leftovers = _kill_leftovers(proc.pid)
            t_out.join(timeout=60)
            t_err.join(timeout=60)
    except OSError as exc:
        state.update(status="failed_to_start", error=str(exc), ended_utc=utc_now())
        write_json_replace(run / "launch_state.json", state)
        raise ToolError(f"could not start codex: {exc}") from exc

    end_epoch = time.time()
    duration = round(time.monotonic() - t0, 3)

    rollouts, matched_by = find_rollouts(Path(lock["codex_home"]), thread["id"], start_epoch, end_epoch)
    rollout_rows = []
    for src in rollouts:
        dst_dir = run / "trajectory" / "rollout"
        dst_dir.mkdir(parents=True, exist_ok=True)
        before = sha256_file(src)
        shutil.copyfile(src, dst_dir / src.name)
        rollout_rows.append({
            "name": src.name, "source": str(src), "bytes": (dst_dir / src.name).stat().st_size,
            "sha256": sha256_file(dst_dir / src.name), "source_stable_during_copy": before == sha256_file(src),
            "matched_by": matched_by, "copy": f"trajectory/rollout/{src.name}",
        })

    write_json_new(run / "predictions_at_end.json", {
        "predictions_dir": lock["predictions_dir"], "taken_utc": utc_now(),
        "files": tree_listing(pred_dir),
    })
    after_problems = check_locked_state(run, lock)

    warnings = list(state["warnings"])
    if not rollout_rows:
        warnings.append("no Codex session file was found under $CODEX_HOME/sessions")
    if matched_by == "time window" and len(rollout_rows) > 1:
        warnings.append("several session files matched by time; check which one belongs to this run")
    if leftovers:
        warnings.append("processes left in the run's process group were killed after Codex exited")
    if rc < 0:
        exit_code = 128 - rc
    else:
        exit_code = rc
    if timed_out:
        exit_code = 124
    state.update(
        status="finished",
        ended_utc=utc_now(),
        duration_seconds=duration,
        exit_code=exit_code,
        returncode=rc,
        signal=-rc if rc < 0 else None,
        timed_out=timed_out,
        thread_id=thread["id"],
        rollouts=rollout_rows,
        rollout_match=matched_by,
        inputs_changed_during_run=after_problems,
        warnings=warnings,
    )
    write_json_replace(run / "launch_state.json", state)
    print(f"LAUNCH FINISHED: exit={exit_code} timed_out={timed_out} duration={duration}s "
          f"thread_id={thread['id']} rollouts={len(rollout_rows)}")
    for w in warnings:
        print(f"warning: {w}")
    if after_problems:
        print("warning: locked inputs changed during the run; package will refuse:", file=sys.stderr)
        for p in after_problems:
            print(f"  {p}", file=sys.stderr)
    return exit_code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a locked Codex CLI command once and record the trajectory.")
    ap.add_argument("run", type=Path, help="run directory created by codex_lock.py")
    a = ap.parse_args(argv)
    try:
        return _launch(a.run.resolve())
    except ToolError as exc:
        print(f"codex_launch: refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
