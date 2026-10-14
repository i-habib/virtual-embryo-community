#!/usr/bin/env python3
"""Score a fixed grid of cases with every veckit variant, one run at a time, and write results/grid.csv.

    python run_grid.py prepare              # write case .h5ad files (needs numpy + anndata: envs/tools)
    python run_grid.py run [VARIANT ...]    # score cases with each variant env (default: all variants)
    python run_grid.py run --real           # also the real-scale E9.5 check (pypi-0.1.2 and git-main only)
    python run_grid.py collect              # rebuild results/grid.csv from the per-run records

Each case runs as its own `python -m score_h5ad` process inside the variant's uv env, so the peak RSS
reported (ru_maxrss of that child, from os.wait4) is per case, and imports are included. `run` skips cases
whose record already exists; delete a record under scratch raw/ to rerun it.

Scratch files (case inputs, raw JSON, logs) live under scorer-variants/, outside the repository. Only
results/grid.csv is written into this folder.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SCRATCH = Path(os.environ.get("SCORER_VARIANTS", HERE.parent.parent / "scorer-variants"))
DATA = SCRATCH / "worktrees" / "git-main-cc3859a" / "data"
CASES = SCRATCH / "cases"
RAW = SCRATCH / "raw"
ENVS = SCRATCH / "envs"
E95 = Path(os.environ.get("VEC_E95_H5AD", "E9.5.h5ad"))  # released MERFISH E9.5 file, for --real
GRID_CSV = HERE / "results" / "grid.csv"

VARIANTS = ["pypi-0.1.0", "pypi-0.1.1", "pypi-0.1.2", "git-46d41e6", "git-main-cc3859a",
            "pr2", "pr4", "pr5", "pr6", "pr8", "pr11"]
REAL_VARIANTS = ["pypi-0.1.2", "git-main-cc3859a"]
SUBSAMPLE_N = 3000
N_ROTATIONS = 12


# ---------------------------------------------------------------- case construction

def proper_rotation(seed: int) -> np.ndarray:
    """A 3x3 rotation with determinant +1, drawn from a fixed seed (QR of a Gaussian matrix)."""
    rng = np.random.default_rng(seed)
    q, r = np.linalg.qr(rng.normal(size=(3, 3)))
    q = q * np.sign(np.diag(r))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    assert abs(np.linalg.det(q) - 1.0) < 1e-9
    return q


def dense(X) -> np.ndarray:
    return np.asarray(X.toarray() if hasattr(X, "toarray") else X, dtype=np.float32)


def with_matrix(a, X: np.ndarray):
    b = a.copy()
    b.X = X.astype(np.float32)
    return b


def with_coords(a, C: np.ndarray):
    b = a.copy()
    b.obsm["spatial_3D"] = np.asarray(C, dtype=np.float64)
    return b


def write(a, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    a.write_h5ad(path)
    return str(path)


def prepare() -> dict:
    import anndata as ad

    CASES.mkdir(parents=True, exist_ok=True)
    rd = lambda name: ad.read_h5ad(DATA / name)  # noqa: E731
    s85, s95 = rd("sample_8.5.h5ad"), rd("sample_9.5.h5ad")
    h925, h95 = rd("sample_heart_9.25.h5ad"), rd("sample_heart_9.5.h5ad")
    wt, ko = rd("sample_wt.h5ad"), rd("sample_mab21l2_ko.h5ad")
    assert (s85.var_names == s95.var_names).all()
    assert all((h925.var_names == x.var_names).all() for x in (h95, wt, ko))

    cases = {}  # name -> dict(task, input, target, reference or wt)
    d = DATA

    # T1: copy_last, and 50% of the way from sample_8.5 toward the sample_9.5 per-gene mean (clipped at 0).
    x85 = dense(s85.X)
    mu95 = dense(s95.X).mean(axis=0)
    shift50 = np.clip(x85 + 0.5 * (mu95 - x85), 0, None)
    cases["T1/copy_last"] = dict(task="T1", input=str(d / "sample_8.5.h5ad"),
                                 target=str(d / "sample_9.5.h5ad"), reference=str(d / "sample_8.5.h5ad"))
    cases["T1/shift50"] = dict(task="T1",
                               input=write(with_matrix(s85, shift50), CASES / "T1" / "shift50.h5ad"),
                               target=str(d / "sample_9.5.h5ad"), reference=str(d / "sample_8.5.h5ad"))

    # T2 heart: copy_last, the target under 12 proper rotations and 1 mirror, and coordinate scale x0.8, x1.25.
    # The preceding stage (sample_heart_9.25) is the reference for every case.
    ref925 = str(d / "sample_heart_9.25.h5ad")
    tgt95 = str(d / "sample_heart_9.5.h5ad")
    cases["T2/copy_last"] = dict(task="T2", input=ref925, target=tgt95, reference=ref925)
    cases["T2/identity"] = dict(task="T2", input=tgt95, target=tgt95, reference=ref925)  # unrotated baseline
    C = np.asarray(h95.obsm["spatial_3D"], dtype=np.float64)
    for k in range(N_ROTATIONS):
        R = proper_rotation(k)
        p = write(with_coords(h95, C @ R.T), CASES / "T2" / f"rot{k:02d}.h5ad")
        cases[f"T2/rot{k:02d}"] = dict(task="T2", input=p, target=tgt95, reference=ref925)
    mirror = C * np.array([1.0, 1.0, -1.0])
    cases["T2/mirror_z"] = dict(task="T2", input=write(with_coords(h95, mirror), CASES / "T2" / "mirror_z.h5ad"),
                                target=tgt95, reference=ref925)
    for f in (0.8, 1.25):
        p = write(with_coords(h95, C * f), CASES / "T2" / f"scale_x{f}.h5ad")
        cases[f"T2/scale_x{f}"] = dict(task="T2", input=p, target=tgt95, reference=ref925)

    # T3: wt_identity, wt + a * (ko_mean - wt_mean) for a in {0.5, 1, 2} (clipped at 0), and the KO itself.
    wt_x = dense(wt.X)
    delta = dense(ko.X).mean(axis=0) - wt_x.mean(axis=0)
    wt_path = str(d / "sample_wt.h5ad")
    ko_path = str(d / "sample_mab21l2_ko.h5ad")
    cases["T3/wt_identity"] = dict(task="T3", input=wt_path, target=ko_path, wt=wt_path)
    for a in (0.5, 1, 2):
        X = np.clip(wt_x + a * delta, 0, None)
        p = write(with_matrix(wt, X), CASES / "T3" / f"wt_plus_{a}d.h5ad")
        cases[f"T3/wt_plus_{a}d"] = dict(task="T3", input=p, target=ko_path, wt=wt_path)
    cases["T3/ko_itself"] = dict(task="T3", input=ko_path, target=ko_path, wt=wt_path)

    # Real-scale check: 3,000 MERFISH cells from E9.5 (seed 0), unrotated as target and reference.
    real = {}
    if not E95.exists():
        print(f"skipping the real-scale cases: {E95} not found (set VEC_E95_H5AD)")
        manifest = {"cases": cases, "real": real}
        (CASES / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
    full = ad.read_h5ad(E95)
    rng = np.random.default_rng(0)
    idx = np.sort(rng.choice(full.n_obs, size=SUBSAMPLE_N, replace=False))
    sub = full[idx].to_memory()
    del full
    (CASES / "real").mkdir(parents=True, exist_ok=True)
    np.save(CASES / "real" / "subsample_idx.npy", idx)
    sub_path = write(sub, CASES / "real" / "E9.5_sub3000.h5ad")
    Cs = np.asarray(sub.obsm["spatial_3D"], dtype=np.float64)
    Xs = dense(sub.X)
    for k in range(N_ROTATIONS):
        p = write(with_coords(sub, Cs @ proper_rotation(k).T), CASES / "real" / f"rot{k:02d}.h5ad")
        real[f"REAL/rot{k:02d}"] = dict(task="T2", input=p, target=sub_path, reference=sub_path)
    p = write(with_coords(sub, Cs * np.array([1.0, 1.0, -1.0])), CASES / "real" / "mirror_z.h5ad")
    real["REAL/mirror_z"] = dict(task="T2", input=p, target=sub_path, reference=sub_path)
    real["REAL/identity"] = dict(task="T2", input=sub_path, target=sub_path, reference=sub_path)  # unrotated
    manifest = {"cases": cases, "real": real,
                "real_source": str(E95), "real_cells": int(idx.size), "real_source_cells": int(idx.max() + 1)}
    (CASES / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"prepared {len(cases)} grid cases and {len(real)} real-scale cases in {CASES}")
    return manifest


def load_manifest() -> dict:
    return json.loads((CASES / "manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- running

def record_paths(variant: str, name: str) -> tuple[Path, Path, Path]:
    """(run record, scorer JSON output, scorer log) for one variant and case."""
    base = RAW / variant / name.replace("/", "__")
    return Path(f"{base}.run.json"), Path(f"{base}.out.json"), Path(f"{base}.log")


def run_one(variant: str, name: str, case: dict) -> dict:
    py = ENVS / variant / "bin" / "python"
    rec_path, out, log = record_paths(variant, name)
    if rec_path.exists():
        return json.loads(rec_path.read_text(encoding="utf-8"))
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(py), "-m", "score_h5ad", "--task", case["task"], "--input", case["input"],
           "--target", case["target"], "--seed", "0", "--out", str(out)]
    if case["task"] == "T2":
        cmd += ["--setting", "heart", "--reference", case["reference"]]
    elif case["task"] == "T1":
        cmd += ["--reference", case["reference"]]
    else:
        cmd += ["--wt", case["wt"]]
    if out.exists():
        out.unlink()
    t0 = time.perf_counter()
    with open(log, "w", encoding="utf-8") as lf:
        proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(proc.pid, 0)
    runtime = time.perf_counter() - t0
    rss_bytes = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    rec = {"variant": variant, "case": name, "rc": os.waitstatus_to_exitcode(status),
           "runtime_s": round(runtime, 3), "peak_rss_mb": round(rss_bytes / 2**20, 1)}
    rec_path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def run(variants: list[str], real: bool) -> None:
    manifest = load_manifest()
    for v in variants:
        jobs = list(manifest["cases"].items())
        if real and v in REAL_VARIANTS:
            jobs += list(manifest["real"].items())
        elif real:
            print(f"skip real-scale for {v}")
        for i, (name, case) in enumerate(jobs, 1):
            rec = run_one(v, name, case)
            status = "ok" if rec["rc"] == 0 else f"rc={rec['rc']}"
            print(f"[{v}] {i}/{len(jobs)} {name}: {status} {rec['runtime_s']}s {rec['peak_rss_mb']}MB", flush=True)


# ---------------------------------------------------------------- collecting

def flatten(prefix: str, obj, out: dict) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    elif isinstance(obj, bool):
        out[prefix] = "true" if obj else "false"
    elif isinstance(obj, (int, float, np.floating, np.integer)):
        out[prefix] = float(obj)
    elif obj is None:
        out[prefix] = ""
    else:
        out[prefix] = json.dumps(obj, default=str)


def collect(variants: list[str]) -> int:
    manifest = load_manifest()
    names = list(manifest["cases"]) + list(manifest["real"])
    GRID_CSV.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with open(GRID_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["variant", "case", "metric", "value", "runtime_s", "peak_rss_mb"])
        for v in variants:
            for name in names:
                rec_path, out_path, log_path = record_paths(v, name)
                if not rec_path.exists():
                    continue
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
                if rec["rc"] != 0:
                    tail = log_path.read_text(encoding="utf-8", errors="replace").strip()
                    last = tail.splitlines()[-1] if tail else "no output"
                    w.writerow([v, name, "__error__", last, rec["runtime_s"], rec["peak_rss_mb"]])
                    rows += 1
                    continue
                scored = json.loads(out_path.read_text(encoding="utf-8"))
                flat: dict = {}
                flatten("", scored["metrics"], flat)
                for metric, value in flat.items():
                    w.writerow([v, name, metric, repr(value) if isinstance(value, float) else value,
                                rec["runtime_s"], rec["peak_rss_mb"]])
                    rows += 1
    print(f"wrote {GRID_CSV} ({rows} rows)")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    pr = sub.add_parser("run")
    pr.add_argument("variants", nargs="*", default=VARIANTS)
    pr.add_argument("--real", action="store_true")
    sub.add_parser("collect")
    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare()
    elif args.cmd == "run":
        unknown = [v for v in args.variants if v not in VARIANTS]
        if unknown:
            raise SystemExit(f"unknown variants: {unknown}")
        run(args.variants, args.real)
    else:
        collect(VARIANTS)


if __name__ == "__main__":
    main()
