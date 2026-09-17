#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import urllib.request
from pathlib import Path

import anndata as ad
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import sparse
from veckit import score
from common.shape_metrics import d2_distance, occupancy_dice, scale_log_ratio, sliced_wasserstein

VECKIT_COMMIT = "46d41e63f42a9aab815db20b742feeccd249cb17"
DATA_BASE = f"https://raw.githubusercontent.com/aristoteleo/veckit/{VECKIT_COMMIT}/data/"
ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)
CACHE = Path(os.environ.get("VEC_INTUITION_CACHE", tempfile.gettempdir())) / "vec-intuition-lab"
CACHE.mkdir(parents=True, exist_ok=True)


def download(name: str) -> Path:
    path = CACHE / name
    if not path.exists():
        urllib.request.urlretrieve(DATA_BASE + name, path)
    return path


def dense(a):
    return a.X.toarray().astype(np.float32) if sparse.issparse(a.X) else np.asarray(a.X, dtype=np.float32)


def _pca_basis(C):
    C = np.asarray(C, float)
    X = C - C.mean(0)
    _, _, Vt = np.linalg.svd(X - X.mean(0), full_matrices=False)
    return Vt.T


def _pca_parity(A, B):
    """+1 when the two SVD PCA bases have the same handedness, -1 otherwise."""
    Va, Vb = _pca_basis(A), _pca_basis(B)
    return int(np.sign(np.linalg.det(Va) * np.linalg.det(Vb)))


def _rz(degrees):
    theta = np.deg2rad(degrees)
    return np.array([
        [np.cos(theta), -np.sin(theta), 0.0],
        [np.sin(theta), np.cos(theta), 0.0],
        [0.0, 0.0, 1.0],
    ])


def _random_so3(rng):
    """Haar-uniform proper rotation from a random unit quaternion."""
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)],
        [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)],
        [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)],
    ])


def _shape_metrics(A, B):
    sw, sw_spread = sliced_wasserstein(A, B)
    dice, dice_resolution = occupancy_dice(A, B)
    return {
        "d2_shape": d2_distance(A, B),
        "sliced_wasserstein": sw,
        "sliced_wasserstein_spread": sw_spread,
        "occupancy_dice": dice,
        "occupancy_resolution": dice_resolution,
        "scale_log_ratio": scale_log_ratio(A, B),
        "pca_parity": _pca_parity(A, B),
    }


def rotation_invariance_results(C):
    """Rigid-frame invariance test on one exact point cloud.

    A correct rigid-frame-invariant metric should stay at its identity value for every
    proper rotation. We record PCA-basis handedness because the public scorer first
    canonicalises each cloud independently with SVD and then only tries proper sign flips.
    """
    C = np.asarray(C, float)
    center = C.mean(0, keepdims=True)
    Cc = C - center

    sweep = []
    for angle in range(0, 360, 5):
        Cr = Cc @ _rz(angle).T + center
        sweep.append({"angle_deg": angle, **_shape_metrics(Cr, C)})
    sweep_df = pd.DataFrame(sweep).set_index("angle_deg")
    sweep_df.to_csv(RESULTS / "task2_rotation_sweep.csv")

    rng = np.random.default_rng(20260917)
    random_rows = []
    for i in range(50):
        R = _random_so3(rng)
        assert np.linalg.det(R) > 0.999999
        Cr = Cc @ R.T + center
        random_rows.append({"rotation": i, "det_R": np.linalg.det(R), **_shape_metrics(Cr, C)})
    random_df = pd.DataFrame(random_rows).set_index("rotation")
    random_df.to_csv(RESULTS / "task2_random_rotations.csv")

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(sweep_df.index, sweep_df["sliced_wasserstein"], marker=".", label="sliced Wasserstein")
    ax.set_xlabel("proper z-axis rotation (degrees)")
    ax.set_ylabel("sliced Wasserstein")
    ax.set_title("Rigid-rotation invariance sweep on the exact same point cloud")
    ax2 = ax.twinx()
    ax2.plot(sweep_df.index, sweep_df["occupancy_dice"], marker=".", linestyle="--", label="occupancy Dice")
    ax2.set_ylabel("occupancy Dice")
    fig.tight_layout()
    fig.savefig(RESULTS / "task2_rotation_invariance.png", dpi=160)
    plt.close(fig)

    return sweep_df, random_df


def t1_results():
    ref_path, target_path = download("sample_8.5.h5ad"), download("sample_9.5.h5ad")
    target = ad.read_h5ad(target_path)
    X = dense(target)
    rng = np.random.default_rng(0)
    work = CACHE / "t1_predictions"
    work.mkdir(exist_ok=True)

    def save(name, X_new=None, idx=None):
        pred = target[idx].copy() if idx is not None else target.copy()
        if idx is not None:
            pred.obs_names_make_unique()
        if X_new is not None:
            pred.X = np.asarray(X_new, dtype=np.float32)
        p = work / f"{name}.h5ad"
        pred.write_h5ad(p)
        return p

    preds = {
        "row_order_only": save("row_order_only", idx=rng.permutation(target.n_obs)),
        "repeated_mean": save("repeated_mean", X_new=np.repeat(X.mean(0, keepdims=True), target.n_obs, axis=0)),
    }
    shuffled = X.copy()
    for j in range(X.shape[1]):
        shuffled[:, j] = X[rng.permutation(target.n_obs), j]
    preds["gene_wise_shuffle"] = save("gene_wise_shuffle", X_new=shuffled)
    if "celltype" in target.obs:
        labels = target.obs["celltype"].astype(str).to_numpy()
        values, counts = np.unique(labels, return_counts=True)
        pool = np.flatnonzero(labels == values[np.argmax(counts)])
        preds["one_state_only"] = save("one_state_only", idx=rng.choice(pool, size=target.n_obs, replace=True))

    metrics = ["de_score", "de_direction", "energy_distance", "mmd_u", "variogram", "variance_ratio", "composition_JSD", "pseudobulk_pearson"]
    rows = []
    for name, path in preds.items():
        m = score(task="T1", input=path, target=target_path, reference=ref_path)["metrics"]
        rows.append({"prediction": name, **{k: m.get(k) for k in metrics}})
    df = pd.DataFrame(rows).set_index("prediction")
    df.to_csv(RESULTS / "task1_scores.csv")
    return df


def t2_results():
    ref_path, target_path = download("sample_heart_9.25.h5ad"), download("sample_heart_9.5.h5ad")
    target = ad.read_h5ad(target_path)
    X = dense(target)
    C = np.asarray(target.obsm["spatial_3D"], dtype=np.float32)[:, :3]
    center = C.mean(0, keepdims=True)
    Cc = C - center
    rng = np.random.default_rng(0)
    work = CACHE / "t2_predictions"
    work.mkdir(exist_ok=True)

    def save(name, coords=None, X_new=None):
        pred = target.copy()
        if coords is not None:
            pred.obsm["spatial_3D"] = np.asarray(coords, dtype=np.float32)
        if X_new is not None:
            pred.X = np.asarray(X_new, dtype=np.float32)
        p = work / f"{name}.h5ad"
        pred.write_h5ad(p)
        return p

    Rz = _rz(67).astype(np.float32)
    reflected = Cc.copy()
    reflected[:, 0] *= -1
    A = np.diag([2.0, 0.5, 1.0]).astype(np.float32)
    preds = {
        "translated": save("translated", C + np.array([100., -50., 25.])),
        "rotated": save("rotated", Cc @ Rz.T + center),
        "reflected": save("reflected", reflected + center),
        "scaled_x2": save("scaled_x2", 2 * Cc + center),
        "anisotropic_stretch": save("anisotropic_stretch", Cc @ A.T + center),
        "expression_location_shuffle": save("expression_location_shuffle", C, X[rng.permutation(target.n_obs)]),
    }
    metrics = ["mmd_u", "variogram", "d2_shape", "sliced_wasserstein", "occupancy_dice", "scale_log_ratio", "neighborhood_mmd", "morans_I_agreement"]
    rows = []
    for name, path in preds.items():
        m = score(task="T2", setting="heart", input=path, target=target_path, reference=ref_path)["metrics"]
        rows.append({"prediction": name, **{k: m.get(k) for k in metrics}})
    df = pd.DataFrame(rows).set_index("prediction")
    df.to_csv(RESULTS / "task2_scores.csv")

    delta = (df - df.loc["translated"]).abs()
    cols = [c for c in ["d2_shape", "sliced_wasserstein", "occupancy_dice", "scale_log_ratio", "neighborhood_mmd"] if c in delta]
    ax = delta[cols].plot.bar(figsize=(10, 4))
    ax.set_ylabel("absolute metric change from translation control")
    ax.set_title("Which spatial metrics notice each controlled failure?")
    plt.tight_layout()
    plt.savefig(RESULTS / "task2_metric_changes.png", dpi=160)
    plt.close()

    sweep, random_rotations = rotation_invariance_results(C)
    return df, sweep, random_rotations


def t3_results():
    wt_path, ko_path = download("sample_wt.h5ad"), download("sample_mab21l2_ko.h5ad")
    wt, ko = ad.read_h5ad(wt_path), ad.read_h5ad(ko_path)
    Xw, Xk = dense(wt), dense(ko)
    delta = Xk.mean(0) - Xw.mean(0)
    rng = np.random.default_rng(0)
    work = CACHE / "t3_predictions"
    work.mkdir(exist_ok=True)

    def save(name, shift):
        pred = wt.copy()
        pred.X = np.clip(Xw + shift[None, :], 0, None).astype(np.float32)
        p = work / f"{name}.h5ad"
        pred.write_h5ad(p)
        return p

    preds = {f"alpha_{a:g}": save(f"alpha_{a:g}", a * delta) for a in [0., .25, .5, 1., 1.5, 2.]}
    preds["reversed"] = save("reversed", -delta)
    preds["shuffled"] = save("shuffled", delta[rng.permutation(len(delta))])
    rows = []
    for name, path in preds.items():
        m = score(task="T3", input=path, target=ko_path, wt=wt_path)["metrics"]
        pb = dense(ad.read_h5ad(path)).mean(0)
        rows.append({
            "prediction": name,
            "de_score": m.get("de_score"),
            "de_direction": m.get("de_direction"),
            "severity_slope": m.get("severity_slope"),
            "mmd_u": m.get("mmd_u"),
            "variogram": m.get("variogram"),
            "absolute_pb_pearson": float(np.corrcoef(pb, Xk.mean(0))[0, 1]),
        })
    df = pd.DataFrame(rows).set_index("prediction")
    df.to_csv(RESULTS / "task3_scores.csv")
    sweep = df.loc[[f"alpha_{a:g}" for a in [0., .25, .5, 1., 1.5, 2.]]].copy()
    sweep.index = [0., .25, .5, 1., 1.5, 2.]
    ax = sweep[["de_score", "de_direction", "absolute_pb_pearson"]].plot(marker="o", figsize=(8, 4))
    ax.axvline(1.0, linestyle="--", alpha=.5)
    ax.set_xlabel("response scale alpha")
    ax.set_title("Absolute similarity can stay high while response metrics move")
    plt.tight_layout()
    plt.savefig(RESULTS / "task3_response_sweep.png", dpi=160)
    plt.close()
    return df


def fmt(x):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{float(x):.4g}"


def render(t1, t2, rotation_sweep, random_rotations, t3):
    opposite = rotation_sweep[rotation_sweep["pca_parity"] < 0]
    same = rotation_sweep[rotation_sweep["pca_parity"] > 0]
    random_opposite = random_rotations[random_rotations["pca_parity"] < 0]
    random_same = random_rotations[random_rotations["pca_parity"] > 0]

    lines = [
        "# Intuition Lab results", "",
        f"Generated with the public `veckit` scorer pinned to `{VECKIT_COMMIT}`.", "",
        "These are **teaching controls on known public targets**, not held-out benchmark results.", "",
        "## Task 1", "",
        "| controlled prediction | pseudobulk Pearson | MMD | variogram/CSS | composition JSD |", "|---|---:|---:|---:|---:|",
    ]
    for name in t1.index:
        r = t1.loc[name]
        lines.append(f"| {name} | {fmt(r.get('pseudobulk_pearson'))} | {fmt(r.get('mmd_u'))} | {fmt(r.get('variogram'))} | {fmt(r.get('composition_JSD'))} |")
    lines += ["", "## Task 2", "", "| controlled prediction | shape distance | sliced Wasserstein | occupancy Dice | scale log-ratio | neighborhood MMD |", "|---|---:|---:|---:|---:|---:|"]
    for name in t2.index:
        r = t2.loc[name]
        lines.append(f"| {name} | {fmt(r.get('d2_shape'))} | {fmt(r.get('sliced_wasserstein'))} | {fmt(r.get('occupancy_dice'))} | {fmt(r.get('scale_log_ratio'))} | {fmt(r.get('neighborhood_mmd'))} |")

    lines += ["", "### Rigid-rotation invariance check", ""]
    lines.append(f"The 5° z-axis sweep produced {len(opposite)}/{len(rotation_sweep)} rotations with opposite PCA handedness relative to the unrotated target. The 50 random SO(3) rotations produced {len(random_opposite)}/50 opposite-handed PCA frames.")
    if len(opposite) and len(same):
        lines.append("")
        lines.append(f"On the angle sweep, same-handed canonical frames had sliced Wasserstein in [{fmt(same['sliced_wasserstein'].min())}, {fmt(same['sliced_wasserstein'].max())}] and Dice in [{fmt(same['occupancy_dice'].min())}, {fmt(same['occupancy_dice'].max())}]. Opposite-handed frames had sliced Wasserstein in [{fmt(opposite['sliced_wasserstein'].min())}, {fmt(opposite['sliced_wasserstein'].max())}] and Dice in [{fmt(opposite['occupancy_dice'].min())}, {fmt(opposite['occupancy_dice'].max())}].")
    if len(random_opposite) and len(random_same):
        lines.append("")
        lines.append(f"For random SO(3) rotations, mean sliced Wasserstein was {fmt(random_same['sliced_wasserstein'].mean())} for same-handed PCA frames versus {fmt(random_opposite['sliced_wasserstein'].mean())} for opposite-handed frames; mean Dice was {fmt(random_same['occupancy_dice'].mean())} versus {fmt(random_opposite['occupancy_dice'].mean())}.")
    lines += [
        "",
        "Every transform in this section is a proper rigid rotation of the exact same point cloud. `d2_shape` and `scale_log_ratio` should therefore remain at their identity values, and the intended rigid-frame invariance implies the same for the PCA-aligned shape terms. The `pca_parity` diagnostic records whether independent SVD canonicalization chose PCA bases of the same (+1) or opposite (-1) handedness.",
        "",
        "![Task 2 rotation invariance sweep](results/task2_rotation_invariance.png)",
        "",
        "Raw sweep: [`task2_rotation_sweep.csv`](results/task2_rotation_sweep.csv) · random SO(3): [`task2_random_rotations.csv`](results/task2_random_rotations.csv)",
        "",
        "### Reflection check", "",
        "Separately, `d2_shape` is reflection-invariant by construction. The official scorer documents that laterality blind spot. The rigid-rotation experiment above asks a different question: whether the two PCA-aligned metrics are actually invariant to *proper* rotations, as intended.", "",
        "![Task 2 metric changes](results/task2_metric_changes.png)", "",
        "## Task 3", "", "| controlled prediction | DES | DCS | severity slope | absolute pseudobulk Pearson |", "|---|---:|---:|---:|---:|",
    ]
    for name in t3.index:
        r = t3.loc[name]
        lines.append(f"| {name} | {fmt(r.get('de_score'))} | {fmt(r.get('de_direction'))} | {fmt(r.get('severity_slope'))} | {fmt(r.get('absolute_pb_pearson'))} |")
    lines += ["", "![Task 3 response sweep](results/task3_response_sweep.png)", "", "The raw CSVs are in [`results/`](results/)."]
    (ROOT / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    readme = ROOT / "README.md"
    src = readme.read_text(encoding="utf-8")
    start = "<!-- AUTO_RESULTS_START -->"
    end = "<!-- AUTO_RESULTS_END -->"
    summary_lines = [
        start,
        "### What the public mini examples actually show",
        "",
        "The notebooks and invariance probes are executed automatically against the pinned public scorer. The current raw tables and figures are in **[RESULTS.md](RESULTS.md)**.",
        "",
        f"- **T1 repeated mean:** pseudobulk Pearson `{fmt(t1.loc['repeated_mean'].get('pseudobulk_pearson'))}`, while MMD is `{fmt(t1.loc['repeated_mean'].get('mmd_u'))}`. A right average can still be a collapsed population.",
        f"- **T2 rigid rotations:** `{len(opposite)}/{len(rotation_sweep)}` points in the 5° sweep and `{len(random_opposite)}/50` random SO(3) rotations landed in opposite-handed PCA frames. See the scorer-metric split in [RESULTS.md](RESULTS.md).",
        f"- **T2 expression-location shuffle:** neighborhood MMD `{fmt(t2.loc['expression_location_shuffle'].get('neighborhood_mmd'))}` while the point cloud itself is unchanged.",
        f"- **T3 no-response:** absolute pseudobulk Pearson `{fmt(t3.loc['alpha_0'].get('absolute_pb_pearson'))}` even though the knockout response is zero.",
        "",
        end,
    ]
    summary = "\n".join(summary_lines)
    if start in src and end in src:
        src = src[:src.index(start)] + summary + src[src.index(end) + len(end):]
        readme.write_text(src, encoding="utf-8")


def main():
    t1 = t1_results()
    t2, rotation_sweep, random_rotations = t2_results()
    t3 = t3_results()
    render(t1, t2, rotation_sweep, random_rotations, t3)
    print("wrote", RESULTS, "and", ROOT / "RESULTS.md")


if __name__ == "__main__":
    main()
