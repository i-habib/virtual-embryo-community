#!/usr/bin/env python3
"""Measure how the Task 2 spatial metrics respond to controlled changes of a truth cloud.

The truth is a fixed random subsample (seed 0) of the released E9.5 file. Each clip applies one
perturbation at a list of strengths and scores every step with the same functions that
`T2/metrics_v2.py::score_task2_v2` calls, with the same arguments, from the pinned veckit
scorer (GitHub main cc3859a, which contains the issue #7 rotation fix).

Run it with the pinned scorer environment's Python, after the data path is known:

    <git-main-cc3859a env>/bin/python compute.py --data ~/virtual-embryo/E9.5.h5ad

Outputs (this folder): responses.csv, run_info.json, anchors_T2_heart_val_interp.json.
Per-step caches go to cache/ (one .json with the metric values, one .npz with the point cloud).
Use --verify to check the direct metric calls against the full `veckit.score()` on a few steps.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_HELPER = HERE.parent / "metric-lens" / "vec_metric_lens.py"
BOARD = "T2:heart:val_interp"
INDEX_URL = "https://virtualembryo.ai/challenge/panels/index.json"
SCORER_COMMIT = "cc3859a"
N_CELLS = 4000
SUB_SEED = 0       # truth subsample and perturbation randomness
METRIC_SEED = 0    # the `seed=` the T2 scorer passes to its metric functions

# Strength grids. Each clip is one perturbation family; `metrics` are the ones it reports.
CLIPS = {
    "scale": {
        "values": [float(x) for x in np.linspace(0.6, 1.4, 15)],
        "metrics": ["scale_log_ratio", "d2_shape", "occupancy_dice"],
    },
    "stretch": {
        "values": [float(x) for x in np.linspace(1.0, 1.6, 13)],
        "metrics": ["d2_shape", "occupancy_dice"],
    },
    "crop": {
        "values": [float(x) for x in np.linspace(0.0, 0.5, 13)],
        "metrics": ["occupancy_dice", "d2_shape"],
    },
    "rotate": {
        "values": [float(x) for x in np.linspace(0.0, 180.0, 13)],
        "metrics": ["d2_shape", "occupancy_dice", "sliced_wasserstein"],
    },
    "shuffle": {
        # Fraction of the cloud diameter. Denser at small radii, where most of the change happens.
        "values": [0.0, 0.01, 0.02, 0.03, 0.04, 0.06, 0.08, 0.12, 0.17, 0.25, 0.35, 0.5, 1.0],
        "metrics": ["neighborhood_mmd", "mmd_u"],
    },
    "jitter": {
        "values": [float(x) for x in np.linspace(0.0, 50.0, 13)],
        "metrics": ["neighborhood_mmd", "d2_shape", "occupancy_dice"],
    },
    # Control, not shown as a video: remove the same share of cells at random instead of as a slab.
    "crop_random_control": {
        "values": [float(x) for x in np.linspace(0.0, 0.5, 13)],
        "metrics": ["occupancy_dice", "d2_shape"],
    },
}


# ----------------------------------------------------------------------------- perturbations
def long_axis(C):
    """Centroid and principal axes of a cloud, columns ordered long to short. Axes are orthonormal."""
    C = np.asarray(C, dtype=np.float64)
    mu = C.mean(0)
    X = C - mu
    w, V = np.linalg.eigh(X.T @ X / len(X))
    V = V[:, np.argsort(w)[::-1]]
    return mu, V


def perturb_scale(C, k, mu):
    """Isotropic scaling about the centroid. Every distance is multiplied by k."""
    return (mu + k * (np.asarray(C, np.float64) - mu)).astype(np.float32)


def stretch_matrix(V, s):
    """Stretch by s along the long axis and by 1/sqrt(s) across it. Determinant is 1, so volume is kept."""
    return V @ np.diag([s, s ** -0.5, s ** -0.5]) @ V.T


def perturb_stretch(C, s, mu, V):
    return (mu + (np.asarray(C, np.float64) - mu) @ stretch_matrix(V, s).T).astype(np.float32)


def rotation_matrix(axis, theta):
    """Proper rotation by theta (radians) about a unit axis (Rodrigues formula). Determinant is +1."""
    u = np.asarray(axis, np.float64)
    u = u / np.linalg.norm(u)
    K = np.array([[0.0, -u[2], u[1]], [u[2], 0.0, -u[0]], [-u[1], u[0], 0.0]])
    return np.eye(3) + np.sin(theta) * K + (1.0 - np.cos(theta)) * (K @ K)


def perturb_rotate(C, degrees, mu, axis):
    R = rotation_matrix(axis, np.deg2rad(degrees))
    return (mu + (np.asarray(C, np.float64) - mu) @ R.T).astype(np.float32)


def crop_keep(C, frac, mu, V):
    """Indices of the cells kept after removing the `frac` share with the largest projection on the long axis.

    The removed cells form a slab at one end of the cloud. The count removed is round(frac * n).
    """
    n = len(C)
    n_drop = int(round(frac * n))
    proj = (np.asarray(C, np.float64) - mu) @ V[:, 0]
    order = np.argsort(proj)
    return np.sort(order[: n - n_drop])


def crop_random_keep(n, frac, rng_seed=SUB_SEED):
    """Control: keep a uniformly random subset of the same size as crop_keep would keep."""
    n_drop = int(round(frac * n))
    perm = np.random.default_rng(rng_seed).permutation(n)
    return np.sort(perm[: n - n_drop])


def perturb_jitter(C, sigma_um, Z):
    return (np.asarray(C, np.float64) + sigma_um * Z).astype(np.float32)


def shuffle_perm(D, radius, rng_seed=SUB_SEED):
    """Random pairwise swaps of expression between cells closer than `radius`.

    Cells are visited in random order. An unpaired cell is paired with a random unpaired cell
    within `radius`, and the two swap expression rows. The result is an involution, so the set of
    expression rows is unchanged. A cell with no unpaired neighbour in range keeps its own row.
    """
    n = D.shape[0]
    perm = np.arange(n)
    if radius <= 0:
        return perm
    rng = np.random.default_rng(rng_seed)
    free = np.ones(n, dtype=bool)
    for i in rng.permutation(n):
        if not free[i]:
            continue
        cand = np.flatnonzero(free & (D[i] <= radius))
        cand = cand[cand != i]
        if cand.size == 0:
            continue
        j = int(rng.choice(cand))
        perm[i], perm[j] = j, i
        free[i] = free[j] = False
    return perm


# ----------------------------------------------------------------------------- data and scorer
def load_truth(data_path: Path):
    import anndata as ad
    from scipy import sparse

    a = ad.read_h5ad(data_path, backed="r")
    n_source = int(a.n_obs)
    try:
        rng = np.random.default_rng(SUB_SEED)
        idx = np.sort(rng.choice(n_source, size=N_CELLS, replace=False))
        sub = a[idx].to_memory()
    finally:
        a.file.close()
    X = sub.X.toarray() if sparse.issparse(sub.X) else np.asarray(sub.X)
    X = np.asarray(X, dtype=np.float32)
    if not np.isfinite(X).all() or (X < 0).any():
        raise ValueError("truth X must be finite and non-negative (log1p CP10k expected)")
    C = np.asarray(sub.obsm["spatial_3D"], dtype=np.float32)[:, :3]
    ct = np.asarray(sub.obs["celltype"]).astype(str)
    genes = [str(g) for g in sub.var_names]
    return {"X": X, "C": C, "ct": ct, "idx": idx, "genes": genes, "n_source": n_source}


def load_helper(path: Path):
    spec = importlib.util.spec_from_file_location("vec_metric_lens", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_index(helper, cache_dir: Path, source: str | None):
    """Board anchors from panels/index.json. Uses the saved copy in cache/ when the network is unavailable."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    saved = cache_dir / "index.json"
    src = source or INDEX_URL
    try:
        index = helper.read_index(src)
        saved.write_text(json.dumps(index, indent=2) + "\n")
        return index, src
    except Exception as exc:  # network or parse failure
        if not saved.exists():
            raise
        print(f"[index] could not read {src} ({exc}); using saved copy", file=sys.stderr)
        return helper.read_index(str(saved)), "saved copy of " + INDEX_URL


def load_metric_module():
    """The T2 metric modules as the scorer loads them (same loader, same files)."""
    import score_h5ad

    _, metrics_v2 = score_h5ad._load_task_metrics("T2")
    return metrics_v2


def score_step(names, pred_X, pred_C, true_X, true_C, mv2):
    """Same calls and arguments as score_task2_v2 for the requested metrics."""
    out, extra = {}, {}
    if "d2_shape" in names:
        out["d2_shape"] = float(mv2.d2_distance(pred_C, true_C, seed=METRIC_SEED))
    if "occupancy_dice" in names:
        dice, ratio = mv2.occupancy_dice(pred_C, true_C, seed=METRIC_SEED)
        out["occupancy_dice"] = float(dice)
        extra["voxel_over_nn"] = float(ratio)
    if "sliced_wasserstein" in names:
        sw, spread = mv2.sliced_wasserstein(pred_C, true_C, seed=METRIC_SEED)
        out["sliced_wasserstein"] = float(sw)
        extra["sliced_flip_spread"] = float(spread)
    if "scale_log_ratio" in names:
        out["scale_log_ratio"] = float(mv2.scale_log_ratio(pred_C, true_C))
    if "neighborhood_mmd" in names:
        out["neighborhood_mmd"] = float(mv2.neighborhood_mmd(pred_X, pred_C, true_X, true_C))
    if "mmd_u" in names:
        out["mmd_u"] = float(mv2.mmd_unbiased(pred_X, true_X, seed=METRIC_SEED))
    return out, extra


def point_value(helper, board, metric, value):
    """Skill on 0 to 1 and board points for one metric. None when the metric has no board anchor."""
    spec = board["metrics"].get(metric)
    if spec is None:
        return None, None
    skill = helper.metric_skill(value, spec)
    return skill, 100.0 * spec["weight"] * skill


# ----------------------------------------------------------------------------- steps
def make_step(clip, value, ctx):
    X, C, ct = ctx["X"], ctx["C"], ctx["ct"]
    mu, V = ctx["mu"], ctx["V"]
    info = {}
    if clip == "scale":
        pC, pX, pct = perturb_scale(C, value, mu), X, ct
    elif clip == "stretch":
        pC, pX, pct = perturb_stretch(C, value, mu, V), X, ct
    elif clip == "rotate":
        pC, pX, pct = perturb_rotate(C, value, mu, V[:, 0]), X, ct
    elif clip == "jitter":
        pC, pX, pct = perturb_jitter(C, value, ctx["Z"]), X, ct
    elif clip == "crop":
        keep = crop_keep(C, value, mu, V)
        pC, pX, pct = C[keep], X[keep], ct[keep]
        info["cells_kept"] = int(keep.size)
    elif clip == "crop_random_control":
        keep = crop_random_keep(len(C), value)
        pC, pX, pct = C[keep], X[keep], ct[keep]
        info["cells_kept"] = int(keep.size)
    elif clip == "shuffle":
        perm = shuffle_perm(ctx["D"], value * ctx["diameter"])
        pC, pX, pct = C, X[perm], ct[perm]
        info["frac_moved"] = float(np.mean(perm != np.arange(len(perm))))
        info["radius_um"] = float(value * ctx["diameter"])
    else:
        raise KeyError(clip)
    return pX, pC, pct, info


def step_key(clip, value, digest):
    blob = json.dumps({"clip": clip, "value": value, "n": N_CELLS, "sub_seed": SUB_SEED,
                       "metric_seed": METRIC_SEED, "scorer": SCORER_COMMIT, "truth": digest},
                      sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def codes_for(labels, names):
    lookup = {n: i for i, n in enumerate(names)}
    return np.array([lookup[x] for x in labels], dtype=np.int16)


def run_clip(clip, spec, ctx, mv2, helper, board, cache_dir, force):
    rows, steps = [], []
    names = spec["metrics"]
    for i, value in enumerate(spec["values"]):
        tag = f"{clip}_{i:02d}"
        jpath, npath = cache_dir / f"{tag}.json", cache_dir / f"{tag}.npz"
        key = step_key(clip, value, ctx["digest"])
        pX, pC, pct, info = make_step(clip, value, ctx)
        np.savez_compressed(npath, C=pC, ct=codes_for(pct, ctx["names"]))

        cached = None
        if jpath.exists() and not force:
            c = json.loads(jpath.read_text())
            if c.get("key") == key and all(m in c["metrics"] for m in names):
                cached = c
        if cached is None:
            t0 = time.time()
            metrics, extra = score_step(names, pX, pC, ctx["X"], ctx["C"], mv2)
            cached = {"key": key, "clip": clip, "index": i, "value": value, "metrics": metrics,
                      "extra": {**info, **extra}, "n_pred": int(pC.shape[0]),
                      "seconds": round(time.time() - t0, 2)}
            jpath.write_text(json.dumps(cached, indent=1) + "\n")
            status = f"{cached['seconds']:.1f}s"
        else:
            status = "cached"
        print(f"[{clip} {i + 1:>2}/{len(spec['values'])}] value={value:.4g} n_pred={cached['n_pred']} "
              f"{status} " + " ".join(f"{m}={cached['metrics'][m]:.5g}" for m in names), flush=True)
        steps.append(cached)
        for m in names:
            v = cached["metrics"][m]
            skill, pts = point_value(helper, ctx["board"], m, v)
            rows.append({"clip": clip, "strength": value, "metric": m, "value": v,
                         "skill": None if skill is None else 100.0 * skill, "points": pts})
    return rows, steps


def verify(ctx, mv2_check, cache_dir: Path):
    """Compare the direct metric calls with the full veckit.score() path on a few steps."""
    import anndata as ad
    import pandas as pd
    import veckit

    vdir = cache_dir / "verify"
    vdir.mkdir(parents=True, exist_ok=True)
    n = len(ctx["C"])
    obs = pd.DataFrame({"celltype": ctx["ct"]}, index=[f"c{i}" for i in range(n)])
    var = pd.DataFrame(index=ctx["genes"])

    def write(path, X, C, ct):
        o = obs if ct is ctx["ct"] else pd.DataFrame({"celltype": ct}, index=[f"c{i}" for i in range(len(ct))])
        a = ad.AnnData(X=np.asarray(X, np.float32), obs=o, var=var)
        a.obsm["spatial_3D"] = np.asarray(C, np.float32)
        a.write_h5ad(path)

    truth_path = vdir / "truth.h5ad"
    write(truth_path, ctx["X"], ctx["C"], ctx["ct"])
    decimals = {"d2_shape": 5, "occupancy_dice": 4, "scale_log_ratio": 4,
                "neighborhood_mmd": 5, "mmd_u": 5}
    report = []
    cases = [("scale", 1.4), ("shuffle", 0.5), ("crop", 0.3), ("rotate", 90.0)]
    for clip, value in cases:
        pX, pC, pct, _ = make_step(clip, value, ctx)
        pred_path = vdir / f"{clip}_{value:g}.h5ad"
        write(pred_path, pX, pC, pct)
        full = veckit.score(task="T2", input=pred_path, target=truth_path, setting="heart", seed=SUB_SEED)
        names = list(decimals)
        direct, _ = score_step(names, pX, pC, ctx["X"], ctx["C"], mv2_check)
        for m in names:
            if m not in full["metrics"] or m not in direct:
                continue
            fv, dv = float(full["metrics"][m]), direct[m]
            ok = abs(fv - round(dv, decimals[m])) <= 10 ** -decimals[m] * 0.5 + 1e-12
            report.append({"clip": clip, "value": value, "metric": m, "full_scorer": fv,
                           "direct": dv, "match_after_rounding": bool(ok)})
            print(f"[verify] {clip} {value:g} {m}: full={fv} direct={dv:.6g} match={ok}", flush=True)
    return report


# ----------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=os.environ.get("VEC_E95"),
                    help="released E9.5.h5ad (or set VEC_E95)")
    ap.add_argument("--helper", type=Path, default=DEFAULT_HELPER, help="path to vec_metric_lens.py")
    ap.add_argument("--index", default=None, help="panels/index.json as a local path or URL")
    ap.add_argument("--cache-dir", type=Path, default=HERE / "cache")
    ap.add_argument("--out-dir", type=Path, default=HERE)
    ap.add_argument("--clips", default=",".join(CLIPS), help="comma-separated subset of clips")
    ap.add_argument("--force", action="store_true", help="recompute steps even if cached")
    ap.add_argument("--verify", action="store_true", help="check direct metric calls against veckit.score()")
    args = ap.parse_args(argv)
    if args.data is None:
        ap.error("pass --data or set VEC_E95")
    data_path = Path(args.data).expanduser()
    t_start = time.time()

    cache_dir = args.cache_dir.expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_dir = args.out_dir.expanduser()

    truth = load_truth(data_path)
    C64 = truth["C"].astype(np.float64)
    names = sorted(set(truth["ct"]))
    digest = hashlib.sha1(truth["X"].tobytes() + truth["C"].tobytes()).hexdigest()[:16]
    mu, V = long_axis(C64)
    from scipy.spatial.distance import cdist

    D = cdist(C64, C64).astype(np.float32)
    diameter = float(D.max())
    Z = np.random.default_rng(SUB_SEED).standard_normal(C64.shape)
    print(f"[truth] {len(C64)} cells from {truth['n_source']} (seed {SUB_SEED}), "
          f"{len(names)} cell types, diameter {diameter:.1f} um", flush=True)
    np.savez_compressed(cache_dir / "truth.npz", C=truth["C"], ct=codes_for(truth["ct"], names),
                        names=np.array(names))

    helper = load_helper(args.helper.expanduser())
    index, index_src = load_index(helper, cache_dir, args.index)
    board = helper.anchored_board(index, BOARD)
    (out_dir / "anchors_T2_heart_val_interp.json").write_text(
        json.dumps(index[BOARD], indent=2) + "\n")

    mv2 = load_metric_module()
    ctx = {"X": truth["X"], "C": truth["C"], "ct": truth["ct"], "genes": truth["genes"], "names": names,
           "mu": mu, "V": V, "Z": Z, "D": D, "diameter": diameter, "digest": digest, "board": board}

    wanted = [c.strip() for c in args.clips.split(",") if c.strip()]
    rows, ratios, timings, all_steps = [], {}, {}, {}
    for clip in wanted:
        t0 = time.time()
        clip_rows, steps = run_clip(clip, CLIPS[clip], ctx, mv2, helper, board, cache_dir, args.force)
        rows += clip_rows
        all_steps[clip] = steps
        timings[clip] = round(time.time() - t0, 1)
        ratios[clip] = [s["extra"]["voxel_over_nn"] for s in steps if "voxel_over_nn" in s["extra"]]

    fields = ["clip", "strength", "metric", "value", "skill", "points"]
    with open(out_dir / "responses.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({"clip": r["clip"], "strength": f"{r['strength']:.6g}", "metric": r["metric"],
                        "value": f"{r['value']:.6g}",
                        "skill": "" if r["skill"] is None else f"{r['skill']:.2f}",
                        "points": "" if r["points"] is None else f"{r['points']:.3f}"})

    verify_report = None
    if args.verify:
        verify_report = verify(ctx, mv2, cache_dir)

    run_info = {
        "board": BOARD,
        "anchors_source": index_src,
        "scorer": f"veckit GitHub main {SCORER_COMMIT} (issue #7 fix included), T2 metrics_v2 functions",
        "truth": {"source_cells": truth["n_source"], "cells": int(len(truth["C"])), "subsample_seed": SUB_SEED,
                  "subsample_index_sha1": hashlib.sha1(truth["idx"].tobytes()).hexdigest()[:16],
                  "genes": len(truth["genes"]), "cell_types": len(names), "digest": digest,
                  "diameter_um": round(diameter, 2)},
        "metric_seed": METRIC_SEED,
        "clip_seconds": timings,
        "occupancy_voxel_over_nn_range": {k: [round(min(v), 2), round(max(v), 2)] for k, v in ratios.items() if v},
        "cells_kept": {k: [s["extra"]["cells_kept"] for s in v] for k, v in all_steps.items()
                       if "cells_kept" in v[0]["extra"]},
        "shuffle_frac_moved": [round(s["extra"]["frac_moved"], 3) for s in all_steps.get("shuffle", [])],
        "verify": verify_report,
        "total_seconds": round(time.time() - t_start, 1),
    }
    (out_dir / "run_info.json").write_text(json.dumps(run_info, indent=2) + "\n")
    print(f"[done] {len(rows)} rows -> {out_dir / 'responses.csv'} in {run_info['total_seconds']} s", flush=True)


if __name__ == "__main__":
    main()
