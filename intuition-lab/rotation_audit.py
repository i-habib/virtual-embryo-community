#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from pathlib import Path

import anndata as ad
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from common.shape_metrics import d2_distance, occupancy_dice, scale_log_ratio, sliced_wasserstein

VECKIT_COMMIT = "46d41e63f42a9aab815db20b742feeccd249cb17"
DATA_URL = f"https://raw.githubusercontent.com/aristoteleo/veckit/{VECKIT_COMMIT}/data/sample_heart_9.5.h5ad"
ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)
CACHE = Path(os.environ.get("VEC_INTUITION_CACHE", tempfile.gettempdir())) / "vec-intuition-lab"
CACHE.mkdir(parents=True, exist_ok=True)


def load_coords() -> np.ndarray:
    path = CACHE / "sample_heart_9.5.h5ad"
    if not path.exists():
        urllib.request.urlretrieve(DATA_URL, path)
    adata = ad.read_h5ad(path)
    return np.asarray(adata.obsm["spatial_3D"], dtype=np.float64)[:, :3]


def z_rotation(degrees: float) -> np.ndarray:
    theta = np.deg2rad(degrees)
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=float)


def random_proper_rotation(rng: np.random.Generator) -> np.ndarray:
    # Haar-distributed O(3) draw, then force determinant +1.
    q, r = np.linalg.qr(rng.normal(size=(3, 3)))
    q = q @ np.diag(np.where(np.diag(r) >= 0, 1.0, -1.0))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    return q


def pca_basis(C: np.ndarray) -> np.ndarray:
    """Reproduce veckit's `_canonicalise` SVD input exactly.

    The second centering looks redundant mathematically, but reproducing it matters here:
    singular-vector signs are arbitrary, so tiny floating-point differences can change the
    discrete sign pattern even when the principal axes themselves are identical.
    """
    C = np.asarray(C, float)
    X = C - C.mean(0)
    _, _, vt = np.linalg.svd(X - X.mean(0), full_matrices=False)
    return vt.T


def svd_sign_parity(C: np.ndarray, R: np.ndarray) -> tuple[int, str, float]:
    """Compare observed PCA basis after rotation with the mathematically expected one.

    If B is the original right-singular-vector basis, a proper input rotation R should
    produce R @ B, up to independent column signs. The product of those three signs
    says whether SVD selected the same (+1) or opposite (-1) handedness.
    """
    center = C.mean(0, keepdims=True)
    B0 = pca_basis(C)
    Brot = pca_basis((C - center) @ R.T + center)
    M = (R @ B0).T @ Brot
    diag = np.diag(M)
    signs = np.where(diag >= 0, 1, -1).astype(int)
    parity = int(np.prod(signs))
    offdiag = float(np.linalg.norm(M - np.diag(diag)))
    return parity, "".join("+" if s > 0 else "-" for s in signs), offdiag


def score_rotation(C: np.ndarray, R: np.ndarray, kind: str, label: str, angle_deg=None) -> dict:
    center = C.mean(0, keepdims=True)
    rotated = (C - center) @ R.T + center
    parity, signs, offdiag = svd_sign_parity(C, R)
    sw, sw_spread = sliced_wasserstein(rotated, C, seed=0)
    dice, dice_resolution = occupancy_dice(rotated, C, seed=0)
    return {
        "kind": kind,
        "label": label,
        "angle_deg": angle_deg,
        "det_rotation": float(np.linalg.det(R)),
        "pca_sign_parity": parity,
        "pca_signs": signs,
        "pca_basis_offdiag": offdiag,
        "d2_shape": d2_distance(rotated, C, seed=0),
        "sliced_wasserstein": sw,
        "sliced_wasserstein_sign_spread": sw_spread,
        "occupancy_dice": dice,
        "occupancy_resolution": dice_resolution,
        "scale_log_ratio": scale_log_ratio(rotated, C),
    }


def main():
    C = load_coords()
    rows = []

    for angle in range(0, 360, 5):
        rows.append(score_rotation(C, z_rotation(angle), "z_sweep", f"z_{angle:03d}", angle))

    rng = np.random.default_rng(20260917)
    for i in range(50):
        rows.append(score_rotation(C, random_proper_rotation(rng), "random_so3", f"random_{i:02d}"))

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "task2_rotation_audit.csv", index=False)

    sweep = df[df["kind"] == "z_sweep"].sort_values("angle_deg")
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(sweep["angle_deg"], sweep["sliced_wasserstein"], marker=".", label="sliced Wasserstein")
    ax.set_xlabel("proper z rotation (degrees)")
    ax.set_ylabel("distance")
    ax.set_title("Rigid-frame invariance audit")
    bad = sweep[sweep["pca_sign_parity"] < 0]
    if len(bad):
        ax.scatter(bad["angle_deg"], bad["sliced_wasserstein"], marker="x", label="PCA parity = -1")
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTS / "task2_rotation_audit.png", dpi=160)
    plt.close(fig)

    parity = df.groupby(["kind", "pca_sign_parity"]).agg(
        n=("label", "count"),
        sw_mean=("sliced_wasserstein", "mean"),
        sw_max=("sliced_wasserstein", "max"),
        dice_mean=("occupancy_dice", "mean"),
        dice_min=("occupancy_dice", "min"),
        d2_range=("d2_shape", lambda x: float(x.max() - x.min())),
        scale_abs_max=("scale_log_ratio", lambda x: float(np.abs(x).max())),
    ).reset_index()

    # A direct mechanism check: if parity alone predicts every non-identity score,
    # the failure is the SVD-handedness / proper-flip mismatch rather than unstable axes.
    tol = 1e-10
    expected_bad = df["pca_sign_parity"] < 0
    observed_bad = (df["sliced_wasserstein"] > tol) | (df["occupancy_dice"] < 1 - tol)
    mechanism_matches = bool(np.array_equal(expected_bad.to_numpy(), observed_bad.to_numpy()))

    summary = {
        "veckit_commit": VECKIT_COMMIT,
        "sample": "sample_heart_9.5.h5ad",
        "n_points": int(C.shape[0]),
        "z_sweep_n": int((df.kind == "z_sweep").sum()),
        "random_so3_n": int((df.kind == "random_so3").sum()),
        "parity_groups": parity.to_dict(orient="records"),
        "mechanism_check": {
            "tolerance": tol,
            "opposite_handed_count": int(expected_bad.sum()),
            "non_identity_sw_or_dice_count": int(observed_bad.sum()),
            "parity_exactly_predicts_failures": mechanism_matches,
        },
        "overall": {
            "sliced_wasserstein_min": float(df.sliced_wasserstein.min()),
            "sliced_wasserstein_max": float(df.sliced_wasserstein.max()),
            "occupancy_dice_min": float(df.occupancy_dice.min()),
            "occupancy_dice_max": float(df.occupancy_dice.max()),
            "d2_shape_range": float(df.d2_shape.max() - df.d2_shape.min()),
            "scale_log_ratio_abs_max": float(np.abs(df.scale_log_ratio).max()),
            "max_pca_basis_offdiag": float(df.pca_basis_offdiag.max()),
        },
    }
    (RESULTS / "task2_rotation_audit_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
