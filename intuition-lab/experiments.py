from __future__ import annotations

from pathlib import Path
from typing import Mapping

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse
from veckit import score


def dense(a: ad.AnnData) -> np.ndarray:
    return a.X.toarray().astype(np.float32) if sparse.issparse(a.X) else np.asarray(a.X, dtype=np.float32)


def _write_prediction(target: ad.AnnData, out_dir: Path, name: str, *, X_new=None, row_indices=None, coords=None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    pred = target[row_indices].copy() if row_indices is not None else target.copy()
    if row_indices is not None:
        pred.obs_names_make_unique()
    if X_new is not None:
        pred.X = np.asarray(X_new, dtype=np.float32)
    if coords is not None:
        pred.obsm["spatial_3D"] = np.asarray(coords, dtype=np.float32)
    path = out_dir / f"{name}.h5ad"
    pred.write_h5ad(path)
    return path


def make_t1_failures(target: ad.AnnData, out_dir: Path, seed: int = 0) -> tuple[dict[str, Path], dict]:
    """Construct the four target-aware Task 1 teaching controls used everywhere in the lab."""
    X = dense(target)
    rng = np.random.default_rng(seed)
    preds: dict[str, Path] = {}

    preds["row_order_only"] = _write_prediction(
        target, out_dir, "row_order_only", row_indices=rng.permutation(target.n_obs)
    )
    mean_cell = X.mean(axis=0, keepdims=True)
    preds["repeated_mean"] = _write_prediction(
        target, out_dir, "repeated_mean", X_new=np.repeat(mean_cell, target.n_obs, axis=0)
    )

    shuffled = X.copy()
    for j in range(X.shape[1]):
        shuffled[:, j] = X[rng.permutation(target.n_obs), j]
    preds["gene_wise_shuffle"] = _write_prediction(
        target, out_dir, "gene_wise_shuffle", X_new=shuffled
    )

    meta = {"seed": seed, "one_state_label": None, "one_state_pool": None}
    if "celltype" in target.obs:
        labels = target.obs["celltype"].astype(str).to_numpy()
        values, counts = np.unique(labels, return_counts=True)
        dominant = values[np.argmax(counts)]
        pool = np.flatnonzero(labels == dominant)
        idx = rng.choice(pool, size=target.n_obs, replace=True)
        preds["one_state_only"] = _write_prediction(
            target, out_dir, "one_state_only", row_indices=idx
        )
        meta.update(one_state_label=str(dominant), one_state_pool=int(len(pool)))
    return preds, meta


def make_t2_failures(target: ad.AnnData, out_dir: Path, seed: int = 0) -> tuple[dict[str, Path], dict]:
    """Construct geometry/expression-location controls for the public Task 2 mini target."""
    X = dense(target)
    C = np.asarray(target.obsm["spatial_3D"], dtype=np.float32)[:, :3]
    center = C.mean(axis=0, keepdims=True)
    Cc = C - center
    rng = np.random.default_rng(seed)

    theta_deg = 67.0
    theta = np.deg2rad(theta_deg)
    Rz = np.array(
        [[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1]],
        dtype=np.float32,
    )
    reflected = Cc.copy()
    reflected[:, 0] *= -1
    anisotropic = np.diag([2.0, 0.5, 1.0]).astype(np.float32)

    preds = {
        "translated": _write_prediction(target, out_dir, "translated", coords=C + np.array([100.0, -50.0, 25.0])),
        "rotated": _write_prediction(target, out_dir, "rotated", coords=Cc @ Rz.T + center),
        "reflected": _write_prediction(target, out_dir, "reflected", coords=reflected + center),
        "scaled_x2": _write_prediction(target, out_dir, "scaled_x2", coords=2.0 * Cc + center),
        "anisotropic_stretch": _write_prediction(target, out_dir, "anisotropic_stretch", coords=Cc @ anisotropic.T + center),
        "expression_location_shuffle": _write_prediction(
            target, out_dir, "expression_location_shuffle", coords=C, X_new=X[rng.permutation(target.n_obs)]
        ),
    }
    return preds, {"seed": seed, "proper_rotation_degrees": theta_deg}


def make_t3_failures(wt: ad.AnnData, ko: ad.AnnData, out_dir: Path, seed: int = 0) -> tuple[dict[str, Path], dict]:
    """Construct response-scale/direction controls from the public matched WT/KO pair."""
    Xw, Xk = dense(wt), dense(ko)
    delta = Xk.mean(axis=0) - Xw.mean(axis=0)
    rng = np.random.default_rng(seed)

    def save(name: str, shift: np.ndarray) -> Path:
        pred = wt.copy()
        pred.X = np.clip(Xw + shift[None, :], 0, None).astype(np.float32)
        return _write_prediction(pred, out_dir, name, X_new=pred.X)

    alphas = [0.0, 0.25, 0.5, 1.0, 1.5, 2.0]
    preds = {f"alpha_{a:g}": save(f"alpha_{a:g}", a * delta) for a in alphas}
    preds["reversed"] = save("reversed", -delta)
    preds["shuffled"] = save("shuffled", delta[rng.permutation(len(delta))])
    return preds, {"seed": seed, "alphas": alphas, "mean_response_l2": float(np.linalg.norm(delta))}


def score_t1_failures(preds: Mapping[str, Path], *, target: Path, reference: Path) -> pd.DataFrame:
    metrics = [
        "de_score", "de_direction", "energy_distance", "mmd_u", "variogram",
        "variance_ratio", "composition_JSD", "pseudobulk_pearson",
    ]
    rows = []
    for name, path in preds.items():
        m = score(task="T1", input=path, target=target, reference=reference)["metrics"]
        rows.append({"prediction": name, **{k: m.get(k) for k in metrics}})
    return pd.DataFrame(rows).set_index("prediction")


def score_t2_failures(preds: Mapping[str, Path], *, target: Path, reference: Path) -> pd.DataFrame:
    metrics = [
        "mmd_u", "variogram", "d2_shape", "sliced_wasserstein", "occupancy_dice",
        "scale_log_ratio", "neighborhood_mmd", "morans_I_agreement",
    ]
    rows = []
    for name, path in preds.items():
        m = score(task="T2", setting="heart", input=path, target=target, reference=reference)["metrics"]
        rows.append({"prediction": name, **{k: m.get(k) for k in metrics}})
    return pd.DataFrame(rows).set_index("prediction")


def score_t3_failures(preds: Mapping[str, Path], *, target: Path, wt: Path) -> pd.DataFrame:
    target_adata = ad.read_h5ad(target)
    target_pb = dense(target_adata).mean(axis=0)
    rows = []
    for name, path in preds.items():
        m = score(task="T3", input=path, target=target, wt=wt)["metrics"]
        pb = dense(ad.read_h5ad(path)).mean(axis=0)
        rows.append({
            "prediction": name,
            "de_score": m.get("de_score"),
            "de_direction": m.get("de_direction"),
            "severity_slope": m.get("severity_slope"),
            "mmd_u": m.get("mmd_u"),
            "variogram": m.get("variogram"),
            "absolute_pb_pearson": float(np.corrcoef(pb, target_pb)[0, 1]),
        })
    return pd.DataFrame(rows).set_index("prediction")
