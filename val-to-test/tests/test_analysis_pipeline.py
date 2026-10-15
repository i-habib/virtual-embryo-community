"""Run analyse() on fabricated records, to test the whole path without the scorer."""
import numpy as np
import pytest
from pathlib import Path

import analyse as A
import methods as M
from config import CEILING, load_config, pair_signature
import vec_metric_lens as vml

HERE = Path(__file__).resolve().parents[1]


def fabricated_records(cfg, seeds, rng):
    recs = {}
    names = [c.name for c in M.candidates()]
    fam = {c.name: c.family for c in M.candidates()}
    for pair in ("val", "test"):
        board = cfg["pairs"][pair]["board"]
        metrics = vml.BOARDS[board]["metrics"]
        for c in names:
            for s in seeds:
                vals = {}
                for m, spec in metrics.items():
                    floor, ceil = _floor_ceiling(spec["direction"])
                    vals[m] = floor if c == "copy_last" else floor + rng.random() * (ceil - floor) * 0.8
                recs[(pair, c, s)] = {"pair": pair, "candidate": c, "seed": s, "family": fam[c],
                                      "config": cfg["name"], "signature": A_sig(cfg, pair),
                                      "metrics": vals, "pb": list(rng.random(7)),
                                      "fingerprint": f"fp-{c}-{pair}" if c != "copy_last" else "fp-base",
                                      "veckit": "testcommit"}
        for s in seeds:
            vals = {m: ceil_value(spec) for m, spec in metrics.items()}
            recs[(pair, CEILING, s)] = {"pair": pair, "candidate": CEILING, "seed": s, "family": "ceiling",
                                        "config": cfg["name"], "signature": A_sig(cfg, pair),
                                        "metrics": vals, "pb": list(np.zeros(7)),
                                        "fingerprint": "ceil", "veckit": "testcommit"}
    return recs


def _floor_ceiling(direction):
    return {"higher": (0.3, 0.9), "lower": (0.5, 0.1), "abs_lower": (-0.5, -0.01)}[direction]


def ceil_value(spec):
    return _floor_ceiling(spec["direction"])[1]


def A_sig(cfg, pair):
    return pair_signature(cfg, pair)


def test_analysis_runs_and_copy_last_sits_at_fifty():
    cfg = load_config(HERE / "configs" / "heart_now.json")
    seeds = cfg["seeds"]
    rng = np.random.default_rng(3)
    recs = fabricated_records(cfg, seeds, rng)
    # Fabricated copy_last values are the floors, so every seed gives copy_last a headline of 50.
    res = A.analyse(cfg, recs, "val", "test", draws=20, boot_draws=50, rng_seed=1, veckit_version="testcommit")
    cl = next(c for c in res["candidates"] if c["name"] == "copy_last")
    assert cl["val_mean"] == pytest.approx(50.0)
    assert cl["test_mean"] == pytest.approx(50.0)
    assert set(res["rules"]) == {"R1", "R2", "R3"}
    assert len(res["candidates"]) == 16
    assert res["pairs"]["val"]["distinct_predictions"]["candidates"] == 16
    for key in res["rules"]:
        assert res["rules"][key]["perturbed"]["draws"] == 20
