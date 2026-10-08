from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import anndata as ad
import numpy as np
from scipy import sparse


def dense(x):
    return x.toarray() if sparse.issparse(x) else np.asarray(x)


def main() -> None:
    task = os.environ["VEC_BENCH_TASK_ID"]
    root = Path(os.environ["VEC_BENCH_WORKSPACE"])
    if task == "inspect_h5ad":
        a = ad.read_h5ad(root / "input.h5ad")
        value = {"n_cells": a.n_obs, "n_genes": a.n_vars, "storage": "sparse" if sparse.issparse(a.X) else "dense", "has_spatial_3d": "spatial_3D" in a.obsm}
        (root / "answer.json").write_text(json.dumps(value))
    elif task == "repair_gene_order":
        a = ad.read_h5ad(root / "prediction.h5ad")
        genes = (root / "expected_genes.txt").read_text().splitlines()
        a[:, genes].copy().write_h5ad(root / "fixed.h5ad")
    elif task == "repair_invalid_expression":
        a = ad.read_h5ad(root / "prediction.h5ad")
        X = np.maximum(np.nan_to_num(dense(a.X), nan=0.0, posinf=0.0, neginf=0.0), 0).astype(np.float32)
        a.X = X
        a.write_h5ad(root / "fixed.h5ad")
    elif task == "preserve_spatial_pairing":
        a = ad.read_h5ad(root / "prediction.h5ad")
        order = np.argsort(np.asarray(a.obs["cell_id"], dtype=int))
        a[order].copy().write_h5ad(root / "fixed.h5ad")
    elif task in {"t1_copy_last", "t2_copy_last"}:
        shutil.copy2(root / "previous_stage.h5ad", root / "submission.h5ad")
    elif task == "t3_wt_identity":
        shutil.copy2(root / "wt.h5ad", root / "submission.h5ad")
    elif task == "scorer_diagnosis":
        value = {"case_a": "population_collapse", "case_b": "expression_location_mismatch", "case_c": "negative_expression"}
        (root / "diagnosis.json").write_text(json.dumps(value))
    elif task == "artifact_lineage":
        def sha(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()
        value = {"source_sha256": sha(root / "source.bin"), "prediction_sha256": sha(root / "prediction.bin")}
        (root / "lineage.json").write_text(json.dumps(value))
    else:
        raise SystemExit(f"unknown task: {task}")


if __name__ == "__main__":
    main()
