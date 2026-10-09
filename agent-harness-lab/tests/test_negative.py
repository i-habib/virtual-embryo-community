"""Negative tests: an agent that does nothing must fail, and graders must reject bad h5ad output."""

import sys
import shlex

import anndata as ad
import numpy as np

from vec_agent_bench.runner import run_benchmark
from vec_agent_bench.tasks import TASK_BY_ID, TASKS
from vec_agent_bench.util import dense


def test_noop_agent_fails_every_task(tmp_path):
    command = f"{shlex.quote(sys.executable)} -c pass"
    summary = run_benchmark(command, [t.id for t in TASKS], tmp_path / "run", timeout_seconds=120)
    assert summary["tasks_total"] == len(TASKS)
    assert summary["tasks_passed"] == 0
    assert all(r["returncode"] == 0 and not r["timed_out"] for r in summary["results"])
    assert all(r["passed"] is False for r in summary["results"])


def _workspace(tmp_path, task_id):
    root = tmp_path / task_id
    root.mkdir()
    TASK_BY_ID[task_id].prepare(root)
    return root


def test_gene_order_grader_rejects_wrong_order(tmp_path):
    root = _workspace(tmp_path, "repair_gene_order")
    src = ad.read_h5ad(root / "prediction.h5ad")
    genes = (root / "expected_genes.txt").read_text().splitlines()

    src.copy().write_h5ad(root / "fixed.h5ad")  # same data, still in the wrong gene order
    grade = TASK_BY_ID["repair_gene_order"].grade(root)
    assert grade["passed"] is False
    assert "gene_order=wrong" in grade["checks"]

    src[:, genes].copy().write_h5ad(root / "fixed.h5ad")  # positive control: correct reorder passes
    assert TASK_BY_ID["repair_gene_order"].grade(root)["passed"] is True


def test_invalid_expression_grader_rejects_nan_and_negative_values(tmp_path):
    root = _workspace(tmp_path, "repair_invalid_expression")
    src = ad.read_h5ad(root / "prediction.h5ad")
    grade = TASK_BY_ID["repair_invalid_expression"].grade

    src.copy().write_h5ad(root / "fixed.h5ad")  # NaN and negative values left in place
    assert grade(root)["passed"] is False

    nan_fixed = src.copy()
    nan_fixed.X = np.nan_to_num(dense(src.X), nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    nan_fixed.write_h5ad(root / "fixed.h5ad")  # negative value still present
    assert grade(root)["passed"] is False

    fixed = src.copy()
    fixed.X = np.maximum(np.nan_to_num(dense(src.X), nan=0.0, posinf=0.0, neginf=0.0), 0).astype(np.float32)
    fixed.write_h5ad(root / "fixed.h5ad")  # positive control: full repair passes
    assert grade(root)["passed"] is True
