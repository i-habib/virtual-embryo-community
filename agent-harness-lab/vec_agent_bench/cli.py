from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .runner import run_benchmark, task_ids
from .tasks import TASKS


def _print_summary(summary: dict) -> None:
    print(f"{summary['tasks_passed']} / {summary['tasks_total']} tasks passed")
    for row in summary["results"]:
        mark = "PASS" if row["passed"] else "FAIL"
        print(f"{mark:4}  {row['task_id']:<28} {row['duration_seconds']:>7.2f}s  {row['peak_rss_mb']:>8.1f} MiB")
        if not row["passed"]:
            for check in row.get("checks", []):
                print(f"      {check}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="vec-agent-bench")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list benchmark tasks")
    run = sub.add_parser("run", help="run an agent/harness command on benchmark tasks")
    run.add_argument("--command", required=True)
    run.add_argument("--tasks", default="all")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--timeout-seconds", type=float, default=300)
    self_test = sub.add_parser("self-test", help="run the deterministic reference program")
    self_test.add_argument("--out", type=Path, default=Path("runs/reference"))
    self_test.add_argument("--tasks", default="all")
    args = parser.parse_args(argv)
    if args.cmd == "list":
        for task in TASKS:
            print(f"{task.id:<28} {task.title}")
        return
    try:
        ids = task_ids(args.tasks)
    except ValueError as e:
        parser.error(str(e))
    if args.cmd == "self-test":
        command = f"{sys.executable} -m vec_agent_bench.reference_agent"
        summary = run_benchmark(command, ids, args.out, timeout_seconds=120)
    else:
        summary = run_benchmark(args.command, ids, args.out, timeout_seconds=args.timeout_seconds)
    _print_summary(summary)
    if summary["tasks_passed"] != summary["tasks_total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
