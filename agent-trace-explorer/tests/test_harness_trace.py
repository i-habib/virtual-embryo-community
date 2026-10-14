import json
from pathlib import Path

from agent_trace_explorer.html import render_trace
from agent_trace_explorer.parsers import load_trace
from agent_trace_explorer.summary import summarize

SHA = "7f7e31fc4394654b07fe70dab3d43e4d93436e9c788622a66b5be847662ba61f"


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "trace.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _exit3_run(tmp_path: Path) -> Path:
    # The grader accepts the output, but the agent exits with code 3: the task does not pass.
    return _write(tmp_path, [
        {"ts": "t0", "event": "run_start", "tasks": ["inspect_h5ad", "repair_gene_order"]},
        {"ts": "t1", "event": "task_start", "task_id": "inspect_h5ad", "title": "Inspect", "argv": ["agent"]},
        {"ts": "t2", "event": "agent_exit", "task_id": "inspect_h5ad", "returncode": 3, "timed_out": False},
        {"ts": "t2", "event": "artifact", "task_id": "inspect_h5ad", "path": "answer.json", "size_bytes": 76, "sha256": SHA},
        {"ts": "t2", "event": "grade", "task_id": "inspect_h5ad", "passed": True, "checks": ["n_cells=37"]},
        {"ts": "t2", "event": "task_end", "task_id": "inspect_h5ad", "passed": False, "grader_passed": True, "returncode": 3,
         "timed_out": False, "duration_seconds": 2.5, "peak_rss_mb": 118.4, "checks": ["n_cells=37"]},
        {"ts": "t3", "event": "task_start", "task_id": "repair_gene_order", "title": "Repair", "argv": ["agent"]},
        {"ts": "t4", "event": "agent_exit", "task_id": "repair_gene_order", "returncode": 0, "timed_out": True},
        {"ts": "t4", "event": "grade", "task_id": "repair_gene_order", "passed": False, "checks": ["missing fixed.h5ad"]},
        {"ts": "t4", "event": "task_end", "task_id": "repair_gene_order", "passed": False, "grader_passed": False, "returncode": 0,
         "timed_out": True, "duration_seconds": 300.0, "peak_rss_mb": 130.0, "checks": ["missing fixed.h5ad"]},
        {"ts": "t5", "event": "run_end", "tasks_passed": 0, "tasks_total": 2},
    ])


def test_task_verdict_follows_harness_not_grader_alone(tmp_path):
    s = summarize(load_trace(_exit3_run(tmp_path)))
    assert s["task_grades"] == {"inspect_h5ad": False, "repair_gene_order": False}
    assert s["task_details"]["inspect_h5ad"]["grader_passed"] is True
    assert s["task_details"]["inspect_h5ad"]["returncode"] == 3
    assert s["task_details"]["repair_gene_order"]["timed_out"] is True
    assert s["task_details"]["inspect_h5ad"]["artifacts"] == 1
    assert (s["tasks_passed"], s["tasks_total"]) == (0, 2)
    assert s["duration_seconds_total"] == 302.5
    assert s["peak_rss_mb_max"] == 130.0


def test_timeline_text_shows_exit_status_hash_and_checks(tmp_path):
    trace = load_trace(_exit3_run(tmp_path))
    text = {(e.event, e.task_id): e.text for e in trace.events}
    assert "return code 3, timed out: no" in text[("agent_exit", "inspect_h5ad")]
    assert SHA in text[("artifact", "inspect_h5ad")]
    assert "answer.json (76 bytes)" in text[("artifact", "inspect_h5ad")]
    assert text[("task_end", "inspect_h5ad")].startswith("FAIL (grader passed; return code 3")
    assert "n_cells=37" in text[("grade", "inspect_h5ad")]


def test_html_report_shows_task_table_and_new_fields(tmp_path):
    out = tmp_path / "report.html"
    render_trace(load_trace(_exit3_run(tmp_path)), out)
    html = out.read_text()
    assert "<h2>Tasks</h2>" in html
    assert "<th>Return code</th>" in html
    assert SHA in html
    assert "Task time" in html
    assert "302.5 s" in html


def test_older_trace_without_grader_field_uses_passed(tmp_path):
    p = _write(tmp_path, [
        {"ts": "t0", "event": "run_start", "tasks": ["a"]},
        {"ts": "t1", "event": "grade", "task_id": "a", "passed": True, "checks": []},
        {"ts": "t1", "event": "task_end", "task_id": "a", "passed": True, "returncode": 0, "duration_seconds": 1.0, "peak_rss_mb": 90.0},
    ])
    s = summarize(load_trace(p))
    assert s["task_grades"] == {"a": True}
    assert s["task_details"]["a"]["grader_passed"] is True


def test_grader_only_task_still_counts(tmp_path):
    p = _write(tmp_path, [
        {"ts": "t0", "event": "run_start", "tasks": ["a"]},
        {"ts": "t1", "event": "grade", "task_id": "a", "passed": False, "checks": ["bad"]},
    ])
    s = summarize(load_trace(p))
    assert s["task_grades"] == {"a": False}
    assert s["tasks_total"] == 1 and s["tasks_passed"] == 0


def test_example_incomplete_run_verdicts():
    root = Path(__file__).parents[1] / "examples"
    s = summarize(load_trace(root / "incomplete.jsonl"))
    assert s["task_grades"] == {"inspect_h5ad": True, "repair_gene_order": False}
    assert s["task_details"]["repair_gene_order"]["returncode"] == 1
    assert (s["tasks_passed"], s["tasks_total"]) == (1, 2)
