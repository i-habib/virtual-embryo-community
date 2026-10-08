import sys

from vec_agent_bench.runner import run_benchmark
from vec_agent_bench.tasks import TASKS


def test_reference_agent_passes(tmp_path):
    summary = run_benchmark(f"{sys.executable} -m vec_agent_bench.reference_agent", [t.id for t in TASKS], tmp_path / "run", timeout_seconds=120)
    assert summary["tasks_passed"] == summary["tasks_total"]
    assert summary["tasks_total"] == len(TASKS)
    assert (tmp_path / "run" / "trace.jsonl").exists()
