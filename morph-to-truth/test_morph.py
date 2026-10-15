"""Tests for morph.py. Run from this folder: python -m pytest -q test_morph.py"""
import json
import shutil

import anndata as ad
import numpy as np
import pandas as pd
import pytest

import morph
import render as R  # embryo-timelapse/render.py, put on sys.path by morph


def make_cloud(n=300, genes=30, seed=1):
    """Anisotropic cloud (distinct axis spreads, so PCA order is stable) with random expression."""
    rng = np.random.default_rng(seed)
    xyz = rng.normal(size=(n, 3)) * np.array([300.0, 150.0, 60.0]) + np.array([1000.0, -500.0, 200.0])
    X = rng.gamma(2.0, 1.0, size=(n, genes))
    lab = rng.choice(["A", "B", "C"], size=n)
    return xyz, X, lab


def as_cloud(xyz, X, lab, name):
    n = len(xyz)
    return morph.Cloud(name, n, np.arange(n), xyz, lab, pd.Series(lab).value_counts(), X,
                       [f"g{i}" for i in range(X.shape[1])])


def test_pca_frame_is_a_proper_rotation():
    rng = np.random.default_rng(0)
    for _ in range(20):
        xyz = rng.normal(size=(100, 3)) @ rng.normal(size=(3, 3))
        rot, _ = R.pca_frame(xyz)
        assert np.linalg.det(rot) == pytest.approx(1.0)
        assert np.allclose(rot.T @ rot, np.eye(3), atol=1e-10)
    mirrored = rng.normal(size=(100, 3)) * np.array([-1.0, 1.0, 1.0])
    rot, _ = R.pca_frame(mirrored)
    assert np.linalg.det(rot) == pytest.approx(1.0)
    assert all(np.prod(f) == 1 for f in morph.FLIPS)


def test_identical_clouds_match_in_place():
    xyz, X, lab = make_cloud()
    c = as_cloud(xyz, X, lab, "same")
    res = morph.run_match(c, c, lam=0.5)
    assert np.allclose(res.disp, 0.0, atol=1e-6)
    assert np.array_equal(res.cols, np.arange(len(xyz)))
    assert res.align_info["after_icp"] < 1e-9


def _proper_rotation(seed):
    rng = np.random.default_rng(seed)
    Q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return Q


def test_rotated_and_translated_copy_aligns_to_zero_displacement():
    xyz, X, lab = make_cloud(seed=2)
    pred = as_cloud(xyz @ _proper_rotation(5) + np.array([300.0, -40.0, 12.0]), X, lab, "pred")
    truth = as_cloud(xyz, X, lab, "truth")
    for lam in (0.0, 0.5):
        res = morph.run_match(pred, truth, lam=lam)
        assert res.disp.max() < 1e-6
        assert res.align_info["after_icp"] < 1e-6


def test_rotated_copy_with_ten_percent_corruption_clean_cells_align():
    n = 300
    xyz, X, lab = make_cloud(n=n, genes=30, seed=8)
    pred_xyz = xyz @ _proper_rotation(9) + np.array([-150.0, 75.0, 20.0])
    rng = np.random.default_rng(11)
    bad = rng.choice(n, size=n // 10, replace=False)
    donors = (bad + rng.integers(1, n, size=bad.size)) % n
    pred_xyz[bad] = pred_xyz[donors].copy()           # corrupted cells take another cell's coordinates
    clean = np.ones(n, dtype=bool)
    clean[bad] = False

    res = morph.run_match(as_cloud(pred_xyz, X, lab, "pred"), as_cloud(xyz, X, lab, "truth"), lam=0.0)
    median_clean = float(np.median(res.disp[clean]))
    assert median_clean < 1.0, f"clean-cell median displacement {median_clean:.3f} um"


def test_mismatch_is_not_available_below_five_shared_labels():
    xyz, X, _ = make_cloud(n=120, genes=30, seed=12)
    rng = np.random.default_rng(13)
    lab_pred = rng.choice(["A", "B", "C", "X"], size=120)
    lab_true = rng.choice(["A", "B", "C", "Y"], size=120)
    res = morph.run_match(as_cloud(xyz, X, lab_pred, "p"), as_cloud(xyz, X, lab_true, "t"), lam=0.5)
    s = morph.summarise(res, {})
    assert s["vocabulary"]["shared_label_count"] == 3
    assert s["mismatch_rate"] is None
    assert s["mismatch_status"].startswith("not available")
    assert s["label_difference_rate_all_pairs"] is not None


def test_mismatch_uses_only_shared_vocabulary_when_five_or_more():
    xyz, X, _ = make_cloud(n=120, genes=30, seed=14)
    rng = np.random.default_rng(15)
    vocab_p = ["A", "B", "C", "D", "E", "F"]
    vocab_t = ["A", "B", "C", "D", "E", "G"]           # 5 shared; F and G are one-sided
    lab_pred = rng.choice(vocab_p, size=120)
    lab_true = rng.choice(vocab_t, size=120)
    res = morph.run_match(as_cloud(xyz, X, lab_pred, "p"), as_cloud(xyz, X, lab_true, "t"), lam=0.5)
    s = morph.summarise(res, {})
    assert s["vocabulary"]["shared_label_count"] == 5
    assert s["mismatch_rate"] is not None
    assert 0 < s["mismatch_pairs_compared"] <= 120


def test_twenty_percent_corruption_is_found_in_top_twenty_percent():
    n = 200
    xyz, X, lab = make_cloud(n=n, genes=30, seed=3)
    rng = np.random.default_rng(7)
    bad = rng.choice(n, size=n // 5, replace=False)
    donors = (bad + rng.integers(1, n, size=bad.size)) % n     # a random other cell
    pred_xyz = xyz.copy()
    pred_xyz[bad] = xyz[donors]
    pred = as_cloud(pred_xyz, X, lab, "pred")
    truth = as_cloud(xyz, X, lab, "truth")

    res = morph.run_match(pred, truth, lam=0.5)
    top = np.argsort(-res.disp)[: n // 5]                      # top 20% of displacements
    share = np.isin(top, bad).mean()
    assert share >= 0.6, f"only {share:.0%} of the top 20% are corrupted (base rate 20%)"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_one_second_render_writes_all_outputs(tmp_path):
    xyz, X, lab = make_cloud(n=200, genes=30, seed=4)
    names = [f"c{i}" for i in range(200)]
    paths = {}
    for tag, coords in (("pred", xyz + 5.0), ("truth", xyz)):
        p = tmp_path / f"{tag}.h5ad"
        ad.AnnData(X=X.astype(np.float32),
                   obs=pd.DataFrame({"celltype": lab}, index=names),
                   obsm={"spatial_3D": coords}).write_h5ad(p)
        paths[tag] = p
    out = tmp_path / "out"
    summary = morph.main([str(paths["pred"]), str(paths["truth"]), "--out", str(out),
                          "--cells", "200", "--seconds", "1"])
    for name in ("morph.mp4", "summary.png", "matches.csv", "summary.json"):
        assert (out / name).stat().st_size > 0, name
    assert summary["n_cells"] == 200
    assert json.loads((out / "summary.json").read_text())["n_cells"] == 200
    matches = pd.read_csv(out / "matches.csv")
    assert len(matches) == 200 and matches["true_index"].nunique() == 200
