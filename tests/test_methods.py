import anndata as ad
import numpy as np

from vec_blender.methods import (
    mean_graft,
    population_mix,
    quantile_graft,
    spatial_transplant,
)


def make_ad(X, genes=None, coords=None):
    X = np.asarray(X, dtype=np.float32)
    if genes is None:
        genes = [f"g{i}" for i in range(X.shape[1])]
    a = ad.AnnData(X=X)
    a.var_names = genes
    if coords is not None:
        a.obsm["spatial_3D"] = np.asarray(coords, dtype=np.float32)
    return a


def test_population_mix_preserves_whole_cells_and_spatial_pairs():
    A = make_ad([[1, 10], [2, 20]], coords=[[1, 0, 0], [2, 0, 0]])
    B = make_ad([[3, 30], [4, 40]], coords=[[3, 0, 0], [4, 0, 0]])
    out = population_mix(A, B, alpha=0.5, n_out=4, seed=3).adata

    pairs = {
        (tuple(x), tuple(c))
        for x, c in zip(np.asarray(out.X), out.obsm["spatial_3D"])
    }
    legal = {
        ((1.0, 10.0), (1.0, 0.0, 0.0)),
        ((2.0, 20.0), (2.0, 0.0, 0.0)),
        ((3.0, 30.0), (3.0, 0.0, 0.0)),
        ((4.0, 40.0), (4.0, 0.0, 0.0)),
    }
    assert pairs <= legal
    assert out.n_obs == 4


def test_gene_order_is_reconciled():
    A = make_ad([[1, 2], [3, 4]], genes=["a", "b"])
    B = make_ad([[20, 10], [40, 30]], genes=["b", "a"])
    out = mean_graft(A, B).adata
    np.testing.assert_allclose(np.asarray(out.X).mean(0), [2, 3], atol=1e-6)


def test_mean_graft_matches_donor_mean_and_carrier_residuals():
    A = make_ad([[5, 10], [7, 14], [9, 18]])
    B = make_ad([[1, 2], [4, 3], [9, 8]])
    result = mean_graft(A, B)
    X = np.asarray(result.adata.X)
    np.testing.assert_allclose(X.mean(0), np.asarray(A.X).mean(0), atol=1e-6)
    np.testing.assert_allclose(
        X - X.mean(0), np.asarray(B.X) - np.asarray(B.X).mean(0), atol=1e-6
    )


def test_quantile_graft_exact_marginals_when_cell_counts_match():
    A = make_ad([[9, 1], [2, 8], [5, 4], [7, 3]])
    B = make_ad([[0, 40], [10, 30], [20, 20], [30, 10]])
    out = quantile_graft(A, B).adata
    X = np.asarray(out.X)
    for j in range(A.n_vars):
        np.testing.assert_allclose(np.sort(X[:, j]), np.sort(np.asarray(A.X)[:, j]))


def test_spatial_transplant_recovers_permuted_geometry_under_gene_shift():
    rng = np.random.default_rng(5)
    X = rng.normal(size=(12, 7)).astype(np.float32)
    coords = rng.normal(size=(12, 3)).astype(np.float32)
    perm = rng.permutation(len(X))
    gene_shift = np.linspace(-3, 4, X.shape[1], dtype=np.float32)

    A = make_ad(X)
    B = make_ad(X[perm] + gene_shift, coords=coords[perm])
    result = spatial_transplant(
        A, B, seed=0, n_components=6, assignment="hungarian"
    )
    np.testing.assert_allclose(np.asarray(result.adata.X), X, atol=1e-6)
    np.testing.assert_allclose(result.adata.obsm["spatial_3D"], coords, atol=1e-5)
    assert result.report["mean_match_distance"] < 1e-5


def test_spatial_transplant_rejects_missing_geometry():
    A = make_ad([[1, 2], [3, 4]])
    B = make_ad([[1, 2], [3, 4]])
    try:
        spatial_transplant(A, B)
    except ValueError as e:
        assert "spatial_3D" in str(e)
    else:
        raise AssertionError("expected ValueError")
