import json

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from config import ConfigError, CEILING, load_config, pair_signature, stage_source
from helpers import make_stage
from stages import Stage, read_stage, write_stage
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def test_heart_now_config_loads_and_orders_inputs():
    cfg = load_config(HERE / "configs" / "heart_now.json")
    assert cfg["pairs"]["test"]["inputs"] == ["E8.25", "E8.75"]
    assert cfg["pairs"]["val"]["board"] == "T2:heart:val_extrap"
    assert CEILING == "__ceiling__"


def test_env_variable_is_expanded_and_unset_variable_is_refused(monkeypatch):
    cfg = load_config(HERE / "configs" / "heart_now.json")
    monkeypatch.setenv("VEC_STAGE_DIR", "/data/stages")
    assert str(stage_source(cfg, "E9.5")) == "/data/stages/E9.5.h5ad"
    monkeypatch.delenv("VEC_STAGE_DIR")
    with pytest.raises(ConfigError):
        stage_source(cfg, "E9.5")


def test_template_placeholders_are_refused_at_source_time():
    cfg = load_config(HERE / "configs" / "oct20_template.json")
    with pytest.raises(ConfigError):
        stage_source(cfg, "E8.5")


def test_input_must_precede_target(tmp_path):
    bad = {
        "name": "bad", "subsample_cells": 10, "subsample_seed": 0, "seeds": [0],
        "stages": {"a": {"path": "x", "time": 9.0}, "b": {"path": "y", "time": 8.0}},
        "pairs": {"p": {"inputs": ["a"], "target": "b", "task": "T2"}},
    }
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(bad))
    with pytest.raises(ConfigError):
        load_config(f)


def test_signature_ignores_paths_but_follows_inputs(tmp_path):
    cfg = load_config(HERE / "configs" / "heart_now.json")
    sig = pair_signature(cfg, "test")
    cfg["stages"]["E9.5"]["path"] = "/elsewhere/E9.5.h5ad"
    assert pair_signature(cfg, "test") == sig
    cfg["subsample_cells"] = 3000
    assert pair_signature(cfg, "test") != sig


def test_stage_round_trip(tmp_path):
    st = make_stage("E8.25", 8.25, np.arange(12, dtype=np.float32).reshape(4, 3),
                    coords=np.arange(12, dtype=np.float32).reshape(4, 3), ct=["a", "b", "a", "c"])
    path = tmp_path / "s.h5ad"
    write_stage(st, path)
    back = read_stage(path, "E8.25", 8.25)
    assert np.array_equal(back.X, st.X)
    assert np.array_equal(back.coords, st.coords)
    assert list(back.ct) == ["a", "b", "a", "c"]
    assert list(back.genes) == list(st.genes)
    assert back.has_coords


def test_stage_without_coordinates_reads_with_flag(tmp_path):
    a = ad.AnnData(X=np.ones((5, 3), dtype=np.float32),
                   obs=pd.DataFrame({"celltype": ["x"] * 5}, index=[f"c{i}" for i in range(5)]),
                   var=pd.DataFrame(index=["g1", "g2", "g3"]))
    path = tmp_path / "t1.h5ad"
    a.write_h5ad(path)
    st = read_stage(path, "T1_E8.5", 8.5)
    assert not st.has_coords
    assert st.coords.shape == (5, 3)
