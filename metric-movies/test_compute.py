"""Checks for the perturbations in compute.py. Synthetic clouds only, so no data or scorer is needed.

Run:  python -m pytest test_compute.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compute as c  # noqa: E402


def cloud(n=600, seed=1):
    rng = np.random.default_rng(seed)
    return rng.normal(size=(n, 3)) * np.array([3.0, 1.5, 0.6]) + np.array([10.0, -4.0, 2.0])


def pdist(X):
    return np.sqrt(((X[:, None, :] - X[None, :, :]) ** 2).sum(-1))


def test_scale_multiplies_every_distance_and_keeps_centroid():
    C = cloud()
    mu, _ = c.long_axis(C)
    S = c.perturb_scale(C, 1.25, mu)
    np.testing.assert_allclose(pdist(S.astype(float)), 1.25 * pdist(C), rtol=1e-5)
    np.testing.assert_allclose(S.mean(0), C.mean(0), atol=1e-3)


def test_scale_identity_is_exact():
    C = cloud()
    mu, _ = c.long_axis(C)
    np.testing.assert_allclose(c.perturb_scale(C, 1.0, mu), C.astype(np.float32), rtol=1e-6)


def test_stretch_keeps_volume_and_stretches_long_axis():
    C = cloud()
    mu, V = c.long_axis(C)
    for s in (1.0, 1.3, 1.6):
        M = c.stretch_matrix(V, s)
        assert abs(np.linalg.det(M) - 1.0) < 1e-10, "stretch must have determinant 1"
    S = c.perturb_stretch(C, 1.6, mu, V).astype(float)
    proj_before = (C - mu) @ V[:, 0]
    proj_after = (S - mu) @ V[:, 0]
    # Long-axis spread grows by s, and the spread across the long axis shrinks by 1/sqrt(s).
    np.testing.assert_allclose(proj_after.std() / proj_before.std(), 1.6, rtol=1e-4)
    across = (S - mu) @ V[:, 1]
    across0 = (C - mu) @ V[:, 1]
    np.testing.assert_allclose(across.std() / across0.std(), 1.6 ** -0.5, rtol=1e-4)


def test_rotation_is_proper_and_preserves_distances():
    rng = np.random.default_rng(3)
    axis = rng.normal(size=3)
    for deg in (0.0, 45.0, 90.0, 180.0):
        R = c.rotation_matrix(axis, np.deg2rad(deg))
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-12)
        assert abs(np.linalg.det(R) - 1.0) < 1e-12, "rotation must be proper (det +1)"
    C = cloud()
    mu, V = c.long_axis(C)
    Rot = c.perturb_rotate(C, 180.0, mu, V[:, 0]).astype(float)
    np.testing.assert_allclose(pdist(Rot), pdist(C), rtol=1e-5, atol=1e-4)


def test_shuffle_keeps_multiset_of_expression_rows():
    C = cloud(n=400)
    rng = np.random.default_rng(5)
    X = rng.poisson(1.0, size=(len(C), 12)).astype(np.float32)
    D = pdist(C).astype(np.float32)
    diameter = float(D.max())
    perm = c.shuffle_perm(D, 0.3 * diameter)
    assert sorted(perm.tolist()) == list(range(len(C))), "perm must be a permutation"
    np.testing.assert_array_equal(perm[perm], np.arange(len(C)))  # swaps are involutions
    Xs = X[perm]
    key = lambda M: np.array(sorted(map(tuple, M)))  # noqa: E731
    np.testing.assert_array_equal(key(Xs), key(X))


def test_shuffle_only_swaps_cells_within_radius():
    C = cloud(n=400)
    D = pdist(C).astype(np.float32)
    radius = 0.2 * float(D.max())
    perm = c.shuffle_perm(D, radius)
    moved = np.flatnonzero(perm != np.arange(len(C)))
    assert moved.size > 0
    assert np.all(D[moved, perm[moved]] <= radius + 1e-6)


def test_shuffle_zero_radius_is_identity_and_full_radius_moves_most_cells():
    C = cloud(n=400)
    D = pdist(C).astype(np.float32)
    np.testing.assert_array_equal(c.shuffle_perm(D, 0.0), np.arange(len(C)))
    full = c.shuffle_perm(D, float(D.max()))
    assert np.mean(full != np.arange(len(C))) > 0.9


def test_crop_removes_stated_share_from_one_end():
    C = cloud(n=1000)
    mu, V = c.long_axis(C)
    for frac in (0.0, 0.1, 0.25, 0.5):
        keep = c.crop_keep(C, frac, mu, V)
        assert keep.size == 1000 - int(round(frac * 1000))
    keep = c.crop_keep(C, 0.3, mu, V)
    removed = np.setdiff1d(np.arange(1000), keep)
    proj = (C - mu) @ V[:, 0]
    assert proj[removed].min() >= proj[keep].max(), "removed cells must be the far end"


def test_random_control_removes_same_count():
    for frac in (0.1, 0.5):
        keep = c.crop_random_keep(1000, frac)
        assert keep.size == 1000 - int(round(frac * 1000))
        assert len(np.unique(keep)) == keep.size


def test_jitter_zero_is_identity_and_noise_scales_with_sigma():
    C = cloud(n=20000)
    Z = np.random.default_rng(0).standard_normal(C.shape)
    np.testing.assert_allclose(c.perturb_jitter(C, 0.0, Z), C.astype(np.float32))
    disp = np.linalg.norm(c.perturb_jitter(C, 20.0, Z).astype(float) - C, axis=1)
    expected = 20.0 * 2.0 * np.sqrt(2.0 / np.pi)  # mean norm of a 3-D Gaussian with sd sigma
    np.testing.assert_allclose(disp.mean(), expected, rtol=0.02)
