#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import urllib.request
from pathlib import Path

import anndata as ad
import matplotlib.pyplot as plt
import numpy as np

from experiments import (
    make_t1_failures,
    make_t2_failures,
    make_t3_failures,
    score_t1_failures,
    score_t2_failures,
    score_t3_failures,
)

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


def t1_results():
    ref_path, target_path = download("sample_8.5.h5ad"), download("sample_9.5.h5ad")
    target = ad.read_h5ad(target_path)
    preds, _ = make_t1_failures(target, CACHE / "t1_predictions", seed=0)
    df = score_t1_failures(preds, target=target_path, reference=ref_path)
    df.to_csv(RESULTS / "task1_scores.csv")
    return df


def t2_results():
    ref_path, target_path = download("sample_heart_9.25.h5ad"), download("sample_heart_9.5.h5ad")
    target = ad.read_h5ad(target_path)
    preds, _ = make_t2_failures(target, CACHE / "t2_predictions", seed=0)
    df = score_t2_failures(preds, target=target_path, reference=ref_path)
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
    preds, meta = make_t3_failures(wt, ko, CACHE / "t3_predictions", seed=0)
    df = score_t3_failures(preds, target=ko_path, wt=wt_path)
    df.to_csv(RESULTS / "task3_scores.csv")

    sweep = df.loc[[f"alpha_{a:g}" for a in meta["alphas"]]].copy()
    sweep.index = meta["alphas"]
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
    lines += ["", "## Task 2", "", "| controlled prediction | shape distance | sliced Wasserstein | occupancy Dice | scale log-ratio | neighborhood MMD |", "|---|---:|---:|---:|---:|---:|"]
    for name in t2.index:
        r = t2.loc[name]
        lines.append(f"| {name} | {fmt(r.get('d2_shape'))} | {fmt(r.get('sliced_wasserstein'))} | {fmt(r.get('occupancy_dice'))} | {fmt(r.get('scale_log_ratio'))} | {fmt(r.get('neighborhood_mmd'))} |")
    lines += [
        "", "### The rotation audit changed how to read this table", "",
        "The 67° `rotated` row is a proper rigid rotation of the exact same point cloud, yet the current public scorer penalizes sliced Wasserstein and occupancy Dice for some proper rotations. A separate 72-angle + 50-random-SO(3) audit traced this to independently signed PCA frames: opposite-handed PCA canonicalizations are exactly the cases that fail. See [`rotation_audit.py`](rotation_audit.py), the committed audit outputs, and [upstream issue #7](https://github.com/aristoteleo/veckit/issues/7).", "",
        "The older reflection observation still matters separately: `d2_shape` is reflection-blind by construction. Do not treat either phenomenon as a statement about biological laterality performance.", "",
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
        f"- **T2 proper 67° rotation:** sliced Wasserstein `{fmt(t2.loc['rotated'].get('sliced_wasserstein'))}` and occupancy Dice `{fmt(t2.loc['rotated'].get('occupancy_dice'))}` even though the point cloud is unchanged up to a proper rotation. The dedicated audit reproduces this as the PCA-handedness issue reported upstream in `veckit#7`.",
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
