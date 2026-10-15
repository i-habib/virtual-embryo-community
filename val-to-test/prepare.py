#!/usr/bin/env python3
"""Subsample every stage in a config to at most `subsample_cells` cells (seeded) and write small stage files.

    python prepare.py --config configs/heart_now.json [--stage-dir DIR] [--work-dir DIR]

Released stages are read one at a time, so at most one full file is in memory during this step.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from config import ConfigError, load_config, stage_file, stage_source  # noqa: E402
from stages import read_subsample, write_stage  # noqa: E402


def subsample_indices(n: int, k: int, seed: int) -> np.ndarray:
    if n <= k:
        return np.arange(n)
    return np.sort(np.random.default_rng(seed).choice(n, size=k, replace=False))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--stage-dir", help="directory holding the released stage files; sets VEC_STAGE_DIR")
    ap.add_argument("--work-dir", type=Path, help="default: work/<config name> next to this script")
    args = ap.parse_args(argv)
    if args.stage_dir:
        os.environ["VEC_STAGE_DIR"] = str(args.stage_dir)
    cfg = load_config(args.config)
    work = args.work_dir or HERE / "work" / cfg["name"]
    (work / "stages").mkdir(parents=True, exist_ok=True)

    manifest = {"config": cfg["name"], "subsample_cells": cfg["subsample_cells"],
                "subsample_seed": cfg["subsample_seed"], "stages": {}}
    genes_by_stage = {}
    for name, spec in cfg["stages"].items():
        src = stage_source(cfg, name)  # raises ConfigError on placeholders or unset variables
        if not src.exists():
            raise ConfigError(f"stage {name!r}: file not found at the configured location")
        import anndata as ad
        n_source = ad.read_h5ad(src, backed="r").n_obs
        idx = subsample_indices(n_source, cfg["subsample_cells"], cfg["subsample_seed"])
        small = read_subsample(src, name, spec["time"], idx)
        genes_by_stage[name] = small.genes
        write_stage(small, stage_file(work, name))
        manifest["stages"][name] = {
            "time": spec["time"],
            "source_cells": n_source,
            "kept_cells": len(small),
            "celltypes_kept": int(len(np.unique(small.ct))),
            "genes": int(small.X.shape[1]),
            "x_min": float(small.X.min()),
            "x_max": float(small.X.max()),
        }
        print(f"{name}: {n_source} cells -> {len(small)} kept", flush=True)
        del small
    for pname, pair in cfg["pairs"].items():
        members = pair["inputs"] + [pair["target"]]
        for other in members[1:]:
            if not np.array_equal(genes_by_stage[members[0]], genes_by_stage[other]):
                raise ConfigError(f"pair {pname!r}: stages {members[0]!r} and {other!r} have different gene panels")
    (work / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {work}")


if __name__ == "__main__":
    main()
