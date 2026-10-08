from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import json

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

from .util import dense, finite_nonnegative, json_dump, sha256_file


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    prompt: str
    prepare: Callable[[Path], None]
    grade: Callable[[Path], dict]


def _adata(X, genes, *, cell_ids=None, coords=None) -> ad.AnnData:
    n = X.shape[0]
    obs = pd.DataFrame(index=[f"cell_{i:04d}" for i in range(n)])
    if cell_ids is not None:
        obs["cell_id"] = np.asarray(cell_ids)
    var = pd.DataFrame(index=list(genes))
    a = ad.AnnData(X=X, obs=obs, var=var)
    if coords is not None:
        a.obsm["spatial_3D"] = np.asarray(coords, dtype=np.float32)
    return a


def _write(a: ad.AnnData, path: Path) -> None:
    a.write_h5ad(path)


def _rng(seed: int):
    return np.random.default_rng(seed)


def _check_file(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing {path.name}"
    try:
        ad.read_h5ad(path)
    except Exception as e:
        return False, f"cannot open {path.name}: {e}"
    return True, "opens as h5ad"


def prep_inspect(root: Path) -> None:
    X = sparse.random(37, 23, density=0.18, random_state=1, format="csr", dtype=np.float32)
    X.data = np.abs(X.data * 3).astype(np.float32)
    a = _adata(X, [f"G{i:03d}" for i in range(23)])
    _write(a, root / "input.h5ad")


def grade_inspect(root: Path) -> dict:
    p = root / "answer.json"
    if not p.exists():
        return {"passed": False, "checks": ["missing answer.json"]}
    try:
        got = json.loads(p.read_text())
    except Exception as e:
        return {"passed": False, "checks": [f"invalid JSON: {e}"]}
    expected = {"n_cells": 37, "n_genes": 23, "storage": "sparse", "has_spatial_3d": False}
    checks = [f"{k}={got.get(k)!r}" for k in expected]
    passed = all(got.get(k) == v for k, v in expected.items())
    return {"passed": passed, "checks": checks}


def prep_gene_order(root: Path) -> None:
    rng = _rng(2)
    genes = [f"G{i:03d}" for i in range(17)]
    X = rng.gamma(1.5, 1.0, size=(31, 17)).astype(np.float32)
    perm = rng.permutation(len(genes))
    a = _adata(X[:, perm], [genes[i] for i in perm])
    _write(a, root / "prediction.h5ad")
    (root / "expected_genes.txt").write_text("\n".join(genes) + "\n")


def grade_gene_order(root: Path) -> dict:
    out = root / "fixed.h5ad"
    ok, msg = _check_file(out)
    if not ok:
        return {"passed": False, "checks": [msg]}
    src = ad.read_h5ad(root / "prediction.h5ad")
    got = ad.read_h5ad(out)
    genes = (root / "expected_genes.txt").read_text().splitlines()
    expected = src[:, genes]
    checks = [f"gene_order={'ok' if list(got.var_names) == genes else 'wrong'}", f"shape={got.shape}", f"values_preserved={np.allclose(dense(got.X), dense(expected.X))}"]
    passed = list(got.var_names) == genes and got.shape == expected.shape and np.allclose(dense(got.X), dense(expected.X))
    return {"passed": bool(passed), "checks": checks}


def prep_invalid(root: Path) -> None:
    rng = _rng(3)
    X = rng.gamma(1.2, 0.8, size=(29, 13)).astype(np.float32)
    X[2, 4] = -0.25
    X[8, 7] = np.nan
    _write(_adata(X, [f"G{i:03d}" for i in range(13)]), root / "prediction.h5ad")


def grade_invalid(root: Path) -> dict:
    out = root / "fixed.h5ad"
    ok, msg = _check_file(out)
    if not ok:
        return {"passed": False, "checks": [msg]}
    src = ad.read_h5ad(root / "prediction.h5ad")
    got = ad.read_h5ad(out)
    expected = np.maximum(np.nan_to_num(dense(src.X), nan=0.0, posinf=0.0, neginf=0.0), 0)
    passed = got.shape == src.shape and np.allclose(dense(got.X), expected) and finite_nonnegative(got.X)
    return {"passed": bool(passed), "checks": [f"shape={got.shape}", f"finite_nonnegative={finite_nonnegative(got.X)}", f"requested_repair={np.allclose(dense(got.X), expected)}"]}


def prep_spatial_pairing(root: Path) -> None:
    rng = _rng(4)
    n, g = 24, 11
    ids = np.arange(n)
    X = np.stack([ids + 0.01 * j for j in range(g)], axis=1).astype(np.float32)
    C = np.stack([ids, ids * 2, -ids], axis=1).astype(np.float32)
    perm = rng.permutation(n)
    a = _adata(X[perm], [f"G{i:03d}" for i in range(g)], cell_ids=ids[perm], coords=C[perm])
    _write(a, root / "prediction.h5ad")


def grade_spatial_pairing(root: Path) -> dict:
    out = root / "fixed.h5ad"
    ok, msg = _check_file(out)
    if not ok:
        return {"passed": False, "checks": [msg]}
    got = ad.read_h5ad(out)
    ids = np.asarray(got.obs["cell_id"])
    C = np.asarray(got.obsm.get("spatial_3D", []))
    X = dense(got.X)
    ordered = np.array_equal(ids, np.arange(24))
    expression_ok = X.shape == (24, 11) and np.allclose(X[:, 0], ids)
    coords_ok = C.shape[0] == 24 and np.allclose(C[:, 0], ids) and np.allclose(C[:, 1], 2 * ids)
    return {"passed": bool(ordered and expression_ok and coords_ok), "checks": [f"sorted_cell_ids={ordered}", f"expression_pairing={expression_ok}", f"coordinate_pairing={coords_ok}"]}


def _full_width_sparse(seed: int, n: int = 512, g: int = 32285):
    X = sparse.random(n, g, density=0.0015, random_state=seed, format="csr", dtype=np.float32)
    X.data = np.abs(X.data * 2).astype(np.float32)
    return X


def prep_t1(root: Path) -> None:
    genes = [f"Gene{i:05d}" for i in range(32285)]
    _write(_adata(_full_width_sparse(5), genes), root / "previous_stage.h5ad")
    (root / "genes.txt").write_text("\n".join(genes) + "\n")


def grade_t1(root: Path) -> dict:
    out = root / "submission.h5ad"
    ok, msg = _check_file(out)
    if not ok:
        return {"passed": False, "checks": [msg]}
    src, got = ad.read_h5ad(root / "previous_stage.h5ad"), ad.read_h5ad(out)
    genes = (root / "genes.txt").read_text().splitlines()
    same = got.shape == src.shape and list(got.var_names) == genes and np.allclose(dense(got.X), dense(src.X))
    no_coords = "spatial_3D" not in got.obsm
    return {"passed": bool(same and no_coords and finite_nonnegative(got.X)), "checks": [f"shape={got.shape}", f"gene_order={list(got.var_names) == genes}", f"expression_copy={same}", f"no_spatial_3D={no_coords}"]}


def prep_t2(root: Path) -> None:
    rng = _rng(6)
    n, g = 80, 500
    X = rng.gamma(1.2, 0.7, size=(n, g)).astype(np.float32)
    C = rng.normal(size=(n, 3)).astype(np.float32)
    _write(_adata(X, [f"M{i:03d}" for i in range(g)], coords=C), root / "previous_stage.h5ad")


def _grade_copy_with_coords(root: Path, source_name: str) -> dict:
    out = root / "submission.h5ad"
    ok, msg = _check_file(out)
    if not ok:
        return {"passed": False, "checks": [msg]}
    src, got = ad.read_h5ad(root / source_name), ad.read_h5ad(out)
    expr = got.shape == src.shape and list(got.var_names) == list(src.var_names) and np.allclose(dense(got.X), dense(src.X))
    spatial = "spatial_3D" in got.obsm and np.allclose(np.asarray(got.obsm["spatial_3D"])[:, :3], np.asarray(src.obsm["spatial_3D"])[:, :3])
    return {"passed": bool(expr and spatial and finite_nonnegative(got.X)), "checks": [f"expression_copy={expr}", f"spatial_copy={spatial}"]}


def grade_t2(root: Path) -> dict:
    return _grade_copy_with_coords(root, "previous_stage.h5ad")


def prep_t3(root: Path) -> None:
    rng = _rng(7)
    n, g = 76, 500
    X = rng.gamma(1.1, 0.9, size=(n, g)).astype(np.float32)
    C = rng.normal(size=(n, 3)).astype(np.float32)
    _write(_adata(X, [f"M{i:03d}" for i in range(g)], coords=C), root / "wt.h5ad")


def grade_t3(root: Path) -> dict:
    return _grade_copy_with_coords(root, "wt.h5ad")


def prep_scorer(root: Path) -> None:
    cases = {"case_a": {"pseudobulk_pearson": 0.999, "variance_ratio": 0.01, "composition_JSD": 0.71, "mmd_u": 0.24}, "case_b": {"d2_shape": 0.001, "sliced_wasserstein": 0.0, "occupancy_dice": 1.0, "neighborhood_mmd": 0.19}, "case_c": {"validation_error": ".X must be non-negative; minimum=-0.031"}}
    json_dump(root / "scores.json", cases)


def grade_scorer(root: Path) -> dict:
    out = root / "diagnosis.json"
    if not out.exists():
        return {"passed": False, "checks": ["missing diagnosis.json"]}
    try:
        got = json.loads(out.read_text())
    except Exception as e:
        return {"passed": False, "checks": [f"invalid JSON: {e}"]}
    expected = {"case_a": "population_collapse", "case_b": "expression_location_mismatch", "case_c": "negative_expression"}
    checks = [f"{k}={got.get(k)!r}" for k in expected]
    return {"passed": got == expected, "checks": checks}


def prep_lineage(root: Path) -> None:
    (root / "source.bin").write_bytes(b"source artifact\n" * 19)
    (root / "prediction.bin").write_bytes(b"final prediction\n" * 23)


def grade_lineage(root: Path) -> dict:
    out = root / "lineage.json"
    if not out.exists():
        return {"passed": False, "checks": ["missing lineage.json"]}
    try:
        got = json.loads(out.read_text())
    except Exception as e:
        return {"passed": False, "checks": [f"invalid JSON: {e}"]}
    expected = {"source_sha256": sha256_file(root / "source.bin"), "prediction_sha256": sha256_file(root / "prediction.bin")}
    return {"passed": got == expected, "checks": [f"source_hash={got.get('source_sha256') == expected['source_sha256']}", f"prediction_hash={got.get('prediction_sha256') == expected['prediction_sha256']}"]}


TASKS = [
    Task("inspect_h5ad", "Inspect an unfamiliar AnnData file", """Inspect `input.h5ad` without modifying it. Write `answer.json` with exactly these keys: `n_cells`, `n_genes`, `storage` (`\"sparse\"` or `\"dense\"`), and `has_spatial_3d` (boolean).""", prep_inspect, grade_inspect),
    Task("repair_gene_order", "Repair gene order", """`prediction.h5ad` contains the right genes in the wrong order. `expected_genes.txt` gives the required order. Write `fixed.h5ad` with genes reordered exactly while preserving each gene's expression values.""", prep_gene_order, grade_gene_order),
    Task("repair_invalid_expression", "Repair explicitly invalid expression", """`prediction.h5ad` contains a NaN and a negative expression value. Write `fixed.h5ad` by replacing non-finite entries with 0 and clipping negative values to 0. Do not otherwise change the matrix.""", prep_invalid, grade_invalid),
    Task("preserve_spatial_pairing", "Reorder cells without breaking spatial pairing", """Sort `prediction.h5ad` by integer `obs[\"cell_id\"]` ascending and write `fixed.h5ad`. Expression rows, `obs`, and `obsm[\"spatial_3D\"]` must stay paired during the reorder.""", prep_spatial_pairing, grade_spatial_pairing),
    Task("t1_copy_last", "Produce a Task 1-style copy-last file", """Treat `previous_stage.h5ad` as the last observed Task 1 stage. Write `submission.h5ad` as a copy-last prediction: preserve all expression and the exact order in `genes.txt`. The output must not contain `obsm[\"spatial_3D\"]`. The synthetic file uses the full 32,285-gene Task 1 width.""", prep_t1, grade_t1),
    Task("t2_copy_last", "Produce a Task 2-style copy-last file", """Write `submission.h5ad` from `previous_stage.h5ad`, preserving expression, gene order, row order, and the first three columns of `obsm[\"spatial_3D\"]`.""", prep_t2, grade_t2),
    Task("t3_wt_identity", "Produce a Task 3-style wild-type identity file", """Write `submission.h5ad` as an identity prediction from `wt.h5ad`, preserving expression, gene order, rows, and `obsm[\"spatial_3D\"]`.""", prep_t3, grade_t3),
    Task("scorer_diagnosis", "Interpret controlled scorer/validator failures", """Read `scores.json`. Choose one label for each case and write `diagnosis.json`. Allowed labels: `population_collapse`, `expression_location_mismatch`, `negative_expression`. Use each label once.""", prep_scorer, grade_scorer),
    Task("artifact_lineage", "Record artifact hashes", """Compute SHA-256 for `source.bin` and `prediction.bin`. Write `lineage.json` with exactly `source_sha256` and `prediction_sha256`.""", prep_lineage, grade_lineage),
]

TASK_BY_ID = {t.id: t for t in TASKS}
