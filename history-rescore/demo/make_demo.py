#!/usr/bin/env python3
"""Build the synthetic demo: six team files, a boards.json, and a submissions.csv.

Everything here is synthetic. The "released" target and reference are veckit's public 150-cell heart samples
(sample_heart_9.5 as the target, sample_heart_9.25 as the reference). The six predictions are transformations
of the reference alone; the target is never used to make them. The board scores in submissions.csv are NOT
real board values: each is one protocol-full veckit score with the index's anchors and weights, plus Gaussian
noise (sd 1.0 points). They exist only to exercise the pipeline and to show how far a noisy board can sit from
a local rescoring.

Usage (run_demo.sh does this):  python make_demo.py --data demo/data --out demo
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import rescore as rs  # noqa: E402

BOARD = "T2:heart:val_interp"
REF_NAME = "sample_heart_9.25.h5ad"
TARGET_NAME = "sample_heart_9.5.h5ad"
NOISE_SD = 1.0
FRACTION = 0.5  # 150 cells at 0.1 leaves veckit too few truth cells; the demo uses 0.5 (see README)


def rotate_z(coords: np.ndarray, degrees: float) -> np.ndarray:
    t = np.deg2rad(degrees)
    R = np.array([[np.cos(t), -np.sin(t), 0.0], [np.sin(t), np.cos(t), 0.0], [0.0, 0.0, 1.0]])
    return coords @ R.T


def main() -> int:
    import anndata as ad

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--index", type=Path, default=HERE / "index_snapshot.json")
    args = ap.parse_args()

    ref_path = args.data / REF_NAME
    tgt_path = args.data / TARGET_NAME
    ref = ad.read_h5ad(ref_path)
    X0 = ref.X.toarray() if hasattr(ref.X, "toarray") else np.asarray(ref.X)
    X0 = X0.astype(np.float32)
    n, g = X0.shape
    rng = np.random.default_rng(20261014)

    team = args.out / "team_files"
    (team / "archive").mkdir(parents=True, exist_ok=True)

    def write(name: str, X: np.ndarray, coords: np.ndarray | None = None, folder: Path = team) -> str:
        a = ref.copy()
        a.X = X.astype(np.float32)
        if coords is not None:
            a.obsm["spatial_3D"] = coords.astype(np.float32)
        a.write_h5ad(folder / name)
        return name

    preds = {
        "heart_run_01_copy_last.h5ad": (X0, None, team),
        "heart_run_02_shrink50.h5ad": (0.5 * X0 + 0.5 * X0.mean(axis=0, keepdims=True), None, team),
        "heart_run_03_scale120.h5ad": (1.2 * X0, None, team),
        "heart_run_04_scale080.h5ad": (0.8 * X0, None, team),
        "heart_run_05_rotate30.h5ad": (X0, rotate_z(np.asarray(ref.obsm["spatial_3D"])[:, :3], 30.0),
                                       team / "archive"),
        "heart_run_06_blend_shuffle.h5ad": (0.7 * X0 + 0.3 * X0[rng.permutation(n)], None, team),
    }
    for name, (X, coords, folder) in preds.items():
        write(name, X, coords, folder)

    # Board scores: one protocol-full veckit score per prediction, then noise.
    index = json.loads(args.index.read_text(encoding="utf-8"))
    entry = index[BOARD]
    wkey = rs.weights_key_for(BOARD, entry, {})
    scratch = args.out / "_scratch_make_demo"
    scratch.mkdir(parents=True, exist_ok=True)
    rows = []
    for k, name in enumerate(preds):
        folder = preds[name][2]
        spec = {"op": "score", "task": "T2", "setting": "heart", "input": str(folder / name),
                "target": str(tgt_path), "reference": str(ref_path), "seed": 0,
                "result_path": str(scratch / f"full_{k}.json")}
        data = rs.run_worker(spec)
        local = rs.board_headline(data["metrics"], entry, wkey)["headline"]
        board_score = round(local + rng.normal(0.0, NOISE_SD), 2)
        rows.append({"submitted": f"2026-10-{10 + k:02d} 09:00", "task": "T2 · heart", "file": name,
                     # run 6 is left blank on purpose: the board must be set by hand
                     "board": "" if name.endswith("blend_shuffle.h5ad") else BOARD,
                     "board_score": f"{board_score:.2f}", "_local_full": round(local, 4)})
    # One submission whose file is not on disk: it should show as missing_file.
    rows.append({"submitted": "2026-10-20 09:00", "task": "T2 · heart", "file": "heart_run_07_missing.h5ad",
                 "board": BOARD, "board_score": "41.00", "_local_full": None})
    shutil.rmtree(scratch, ignore_errors=True)

    with open(args.out / "submissions.csv", "w", encoding="utf-8", newline="") as fh:
        fh.write("submitted,task,file,board,board_score\n")
        for r in rows:
            fh.write(",".join([r["submitted"], r["task"], r["file"], r["board"], r["board_score"]]) + "\n")

    boards = {
        "_note": "Synthetic demo. Not a real board. Paths are relative to this file.",
        BOARD: {"target": f"data/{TARGET_NAME}", "reference": f"data/{REF_NAME}", "setting": "heart",
                "fraction": FRACTION, "synthetic": True},
    }
    (args.out / "boards.json").write_text(json.dumps(boards, indent=2) + "\n", encoding="utf-8")

    audit = {"synthetic": True, "noise_sd": NOISE_SD, "board_protocol_fraction": FRACTION,
             "rows": rows, "n_predictions": len(preds), "genes": g, "cells": n}
    print(json.dumps(audit, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
