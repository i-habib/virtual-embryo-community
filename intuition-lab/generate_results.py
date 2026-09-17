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

    theta = np.deg2rad(67)
    Rz = np.array([[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1]], dtype=np.float32)
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
    return df


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


def render(t1, t2, t3):
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
    lines += ["", "## Task 2", "", "| controlled prediction | shape distance | sliced Wasserstein | scale log-ratio | neighborhood MMD |", "|---|---:|---:|---:|---:|"]
    for name in t2.index:
        r = t2.loc[name]
        lines.append(f"| {name} | {fmt(r.get('d2_shape'))} | {fmt(r.get('sliced_wasserstein'))} | {fmt(r.get('scale_log_ratio'))} | {fmt(r.get('neighborhood_mmd'))} |")
    lines += [
        "", "### The reflection lesson", "",
        "The distance-based shape term is reflection-invariant. A mirrored embryo can therefore look perfect to that part of the panel. The official scorer source explicitly documents this laterality blind spot. `sliced_wasserstein` and `occupancy_dice` only optimize over proper rotations, but the organizers also caution that they are not calibrated laterality tests.", "",
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
    summary = "\n".join([
        start,
        "### What the public mini examples actually show",
        "",
        "The notebooks are executed automatically against the pinned public scorer. The current raw tables and figures are in **[RESULTS.md](RESULTS.md)**.",
        "",
        f"- **T1 repeated mean:** pseudobulk Pearson `{fmt(t1.loc['repeated_mean'].get('pseudobulk_pearson'))}`, while MMD is `{fmt(t1.loc['repeated_mean'].get('mmd_u'))}`. A right average can still be a collapsed population.",
        f"- **T2 mirror:** `d2_shape` `{fmt(t2.loc['reflected'].get('d2_shape'))}` versus translation control `{fmt(t2.loc['translated'].get('d2_shape'))}`. This is the scorer's documented laterality blind spot, not a bug in the notebook.",
        f"- **T2 expression-location shuffle:** neighborhood MMD `{fmt(t2.loc['expression_location_shuffle'].get('neighborhood_mmd'))}` while the point cloud itself is unchanged.",
        f"- **T3 no-response:** absolute pseudobulk Pearson `{fmt(t3.loc['alpha_0'].get('absolute_pb_pearson'))}` even though the knockout response is zero.",
        "",
        end,
    ])
    if start in src and end in src:
        src = src[:src.index(start)] + summary + src[src.index(end) + len(end):]
        readme.write_text(src, encoding="utf-8")


def main():
    t1, t2, t3 = t1_results(), t2_results(), t3_results()
    render(t1, t2, t3)
    print("wrote", RESULTS, "and", ROOT / "RESULTS.md")


if __name__ == "__main__":
    main()
