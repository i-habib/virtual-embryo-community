import numpy as np
import pytest

import methods as M
from helpers import make_stage


def rng_stage(name, t, n=300, g=20, seed=0, ct=None):
    rng = np.random.default_rng(seed)
    X = rng.random((n, g)) * 3
    coords = rng.normal(size=(n, 3)) * 10
    return make_stage(name, t, X, coords, ct)


def test_candidate_set_is_sixteen_named_candidates():
    cands = M.candidates()
    names = [c.name for c in cands]
    assert len(cands) == 16
    assert len(set(names)) == 16
    assert all(":" in n for n in names if n != "copy_last")
    counts = {f: sum(c.family == f for c in cands) for f in M.FAMILIES}
    assert counts == {"copy_last": 1, "drift": 3, "composition": 2, "growth": 2, "combo": 4, "degraded": 4}


def test_copy_last_returns_last_stage_values():
    st = [rng_stage("a", 8.25, seed=1), rng_stage("b", 8.75, seed=2)]
    out = M.predict("copy_last", st, 9.5, seed=0)
    assert np.array_equal(out.X, st[-1].X)
    assert np.array_equal(out.coords, st[-1].coords)
    assert out.time == 9.5


def test_one_input_stage_trend_families_equal_copy_last():
    st = [rng_stage("a", 8.25, seed=3)]
    base = M.predict("copy_last", st, 8.75, seed=0)
    for c in M.candidates():
        if c.family in ("drift", "composition", "growth", "combo"):
            out = c.fn(st, 8.75, 0)
            assert np.array_equal(out.X, base.X), c.name
            assert np.array_equal(out.coords, base.coords), c.name


def test_drift_adds_rate_times_dt_to_every_cell():
    prev = make_stage("p", 8.25, np.full((50, 4), 1.0))
    last = make_stage("l", 8.75, np.full((50, 4), 2.0))  # +1.0 over 0.5 day, so rate = 2 per day
    out = M.drift([prev, last], 9.5, 0, a=1.0)  # dt = 0.75 day
    assert np.allclose(out.X, 2.0 + 2.0 * 0.75)
    half = M.drift([prev, last], 9.5, 0, a=0.5)
    assert np.allclose(half.X, 2.0 + 0.5 * 2.0 * 0.75)


def test_drift_is_clipped_at_zero():
    prev = make_stage("p", 8.25, np.full((20, 3), 1.0))
    last = make_stage("l", 8.75, np.full((20, 3), 0.2))
    out = M.drift([prev, last], 10.75, 0, a=1.0)
    assert out.X.min() >= 0.0
    assert np.allclose(out.X, 0.0)


def test_composition_follows_log_proportion_trend():
    # Type A goes from 50% to 25% over one day. With s=1 and dt=1 the trend projects
    # z_A = log(0.25) + (log(0.25) - log(0.5)) and z_B = log(0.75) + (log(0.75) - log(0.5)).
    n = 4000
    prev_ct = np.array(["A"] * 2000 + ["B"] * 2000)
    last_ct = np.array(["A"] * 1000 + ["B"] * 3000)
    prev = make_stage("p", 8.0, np.zeros((n, 2)), ct=prev_ct)
    last = make_stage("l", 9.0, np.zeros((n, 2)), ct=last_ct)
    z_a = np.log(0.25) + (np.log(0.25) - np.log(0.5))
    z_b = np.log(0.75) + (np.log(0.75) - np.log(0.5))
    expected_a = np.exp(z_a) / (np.exp(z_a) + np.exp(z_b))
    out = M.composition([prev, last], 10.0, seed=7, s=1.0)
    frac_a = np.mean(out.ct == "A")
    assert abs(frac_a - expected_a) < 0.02
    assert len(out) == n


def test_composition_is_deterministic_for_a_seed():
    st = [rng_stage("a", 8.25, seed=4, ct=np.array(["x", "y"] * 150)),
          rng_stage("b", 8.75, seed=5, ct=np.array(["x", "y", "y"] * 100))]
    a = M.composition(st, 9.5, seed=11, s=1.0)
    b = M.composition(st, 9.5, seed=11, s=1.0)
    c = M.composition(st, 9.5, seed=12, s=1.0)
    assert np.array_equal(a.X, b.X)
    assert not np.array_equal(a.X, c.X)


def test_growth_scales_rms_radius_by_per_day_ratio_and_keeps_centroid():
    rng = np.random.default_rng(9)
    base = rng.normal(size=(500, 3)) * 5
    prev = make_stage("p", 8.0, np.zeros((500, 2)), coords=base)
    last = make_stage("l", 9.0, np.zeros((500, 2)), coords=2 * base)  # RMS radius doubles over 1 day
    out = M.growth([prev, last], 10.0, seed=0, s=1.0)  # dt = 1, s = 1, so factor = 2
    rms = lambda c: np.sqrt(((c - c.mean(0)) ** 2).sum(1).mean())
    assert rms(out.coords) == pytest.approx(2 * rms(last.coords), rel=1e-4)
    assert np.allclose(out.coords.mean(0), last.coords.mean(0), atol=1e-3)


def test_combo_without_growth_keeps_coordinates_of_resampled_cells():
    st = [rng_stage("a", 8.25, seed=6, ct=np.array(["x", "y"] * 150)),
          rng_stage("b", 8.75, seed=7, ct=np.array(["x", "y", "y"] * 100))]
    out = M.combo(st, 9.5, seed=3, s=1.0, a=1.0, growth_s=None)
    rows = {tuple(np.round(r, 4)) for r in st[-1].coords}
    assert all(tuple(np.round(r, 4)) in rows for r in out.coords)


def test_shrink_keeps_mean_and_scales_variance():
    rng = np.random.default_rng(1)
    pred = make_stage("p", 9.0, rng.random((400, 6)) * 4)
    out = M.shrink(pred, 0.5)
    assert np.allclose(out.X.mean(0), pred.X.mean(0), atol=1e-5)
    assert np.allclose(out.X.var(0), 0.25 * pred.X.var(0), rtol=1e-4)


def test_unknown_candidate_raises():
    with pytest.raises(KeyError):
        M.predict("not_a_candidate", [rng_stage("a", 8.0)], 8.5, 0)


def test_missing_coordinates_disable_growth_only():
    prev = make_stage("p", 8.0, np.ones((30, 2)), has_coords=False)
    last = make_stage("l", 8.5, np.ones((30, 2)), has_coords=False)
    out = M.growth([prev, last], 9.0, 0, s=1.0)
    assert np.array_equal(out.coords, last.coords)
