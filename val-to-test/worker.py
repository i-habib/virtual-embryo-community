#!/usr/bin/env python3
"""Run one scoring job in its own process and print one JSON line on stdout.

A job is either a candidate prediction on a pair (--candidate NAME) or the split-half ceiling
(--candidate __ceiling__: half A of the target scored against half B). Both are scored with veckit,
against the last input stage as reference. Called by score.py; not normally run by hand.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from config import CEILING, load_config, stage_file  # noqa: E402
from methods import predict  # noqa: E402
from stages import read_stage, split_half, write_stage  # noqa: E402


def run_job(cfg: dict, work: Path, pair_name: str, candidate: str, seed: int) -> dict:
    from veckit import score  # imported here so the parent process never loads the scorer

    pair = cfg["pairs"][pair_name]
    stage_cfg = cfg["stages"]
    inputs = [read_stage(stage_file(work, n), n, stage_cfg[n]["time"]) for n in pair["inputs"]]
    target = read_stage(stage_file(work, pair["target"]), pair["target"], stage_cfg[pair["target"]]["time"])
    reference_path = stage_file(work, pair["inputs"][-1])

    (work / "tmp").mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="job_", dir=work / "tmp"))
    try:
        if candidate == CEILING:
            idx_a, idx_b = split_half(len(target), seed)
            pred = target.take(idx_a, name="pred")
            truth = target.take(idx_b)
            truth_path = tmp / "truth.h5ad"
            write_stage(truth, truth_path)
        else:
            pred = predict(candidate, inputs, target.time, seed)
            truth_path = stage_file(work, pair["target"])
        pred_path = tmp / "pred.h5ad"
        write_stage(pred, pred_path)

        kwargs = dict(input=pred_path, target=truth_path, seed=seed)
        if pair["task"] == "T3":
            kwargs["wt"] = stage_file(work, pair["wt"])
        else:
            kwargs["reference"] = reference_path
        if pair["task"] == "T2":
            kwargs["setting"] = pair["setting"]

        t0 = time.time()
        result = score(pair["task"], **kwargs)
        seconds = time.time() - t0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    meta = dict(result["meta"])
    meta["target_source"] = (f"split-half of stages/{pair['target']}.h5ad" if candidate == CEILING
                             else f"stages/{pair['target']}.h5ad")

    pb = pred.X.astype(np.float64).mean(axis=0)
    fingerprint = hashlib.sha1(np.ascontiguousarray(pred.X, dtype=np.float32).tobytes()).hexdigest()[:16]
    return {
        "metrics": result["metrics"],
        "meta": meta,
        "pb": [round(float(v), 8) for v in pb],
        "fingerprint": fingerprint,
        "pred_cells": len(pred),
        "truth_cells": int(result["meta"]["truth_cells"]),
        "seconds": round(seconds, 2),
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--pair", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--seed", required=True, type=int)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    out = run_job(cfg, args.work_dir, args.pair, args.candidate, args.seed)
    print(json.dumps(out, default=str), flush=True)


if __name__ == "__main__":
    main()
