"""End-to-end check of one worker job on tiny synthetic stages (calls veckit, so it is slower)."""
import json
from pathlib import Path

import numpy as np

import worker
from config import CEILING, load_config
from stages import write_stage
from helpers import make_stage


def _write_tiny_work(work: Path, n=240, g=40):
    (work / "stages").mkdir(parents=True)
    rng = np.random.default_rng(0)
    labels = np.array(["A", "B", "C"] * (n // 3))
    specs = {"S1": (8.25, 0.0), "S2": (8.75, 0.3), "S3": (9.5, 0.7)}
    for name, (t, shift) in specs.items():
        X = np.abs(rng.normal(loc=1.0 + shift, scale=0.5, size=(n, g))).astype(np.float32)
        coords = rng.normal(size=(n, 3)) * (10 + 5 * shift)
        write_stage(make_stage(name, t, X, coords=coords, ct=labels), work / "stages" / f"{name}.h5ad")


def test_worker_scores_candidate_and_ceiling(tmp_path):
    work = tmp_path / "work"
    _write_tiny_work(work)
    cfg = {
        "name": "tiny", "subsample_cells": 240, "subsample_seed": 0, "seeds": [0],
        "stages": {"S1": {"path": "unused", "time": 8.25}, "S2": {"path": "unused", "time": 8.75},
                   "S3": {"path": "unused", "time": 9.5}},
        "pairs": {"test": {"inputs": ["S1", "S2"], "target": "S3", "task": "T2", "setting": "heart",
                           "board": "T2:heart:val_extrap"}},
    }
    cfg_path = tmp_path / "tiny.json"
    cfg_path.write_text(json.dumps(cfg))
    from config import load_config as lc
    loaded = lc(cfg_path)
    out = worker.run_job(loaded, work, "test", "drift:a=1.0", seed=0)
    assert set(["de_score", "de_direction", "mmd_u", "variogram", "d2_shape", "occupancy_dice",
                "scale_log_ratio", "neighborhood_mmd"]).issubset(out["metrics"])
    assert out["pred_cells"] == 240 and out["truth_cells"] == 240
    assert len(out["pb"]) == 40
    ceil = worker.run_job(loaded, work, "test", CEILING, seed=0)
    assert ceil["pred_cells"] == 120 and ceil["truth_cells"] == 120
    assert not any(p.name.startswith("job_") for p in (work / "tmp").iterdir())
