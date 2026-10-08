from __future__ import annotations

from pathlib import Path
from typing import Iterable

import anndata as ad
import numpy as np
from scipy import sparse


SPATIAL_KEY = "spatial_3D"


def read_h5ad(path: str | Path) -> ad.AnnData:
    return ad.read_h5ad(Path(path))


def dense_x(adata: ad.AnnData, *, dtype=np.float32) -> np.ndarray:
    """Materialize X as a dense array.

    Kept for small analyses. Core blend paths avoid this helper when they can
    preserve sparsity or work in chunks.
    """
    X = adata.X
    if sparse.issparse(X):
        X = X.toarray()
    return np.asarray(X, dtype=dtype)


def _assert_unique_genes(adata: ad.AnnData, label: str) -> None:
    if not adata.var_names.is_unique:
        duplicated = adata.var_names[adata.var_names.duplicated()].tolist()[:8]
        raise ValueError(f"{label} has duplicate var_names, e.g. {duplicated}")


def _matrix_finite(X) -> bool:
    if sparse.issparse(X):
        return bool(np.isfinite(X.data).all())
    return bool(np.isfinite(np.asarray(X)).all())


def matrix_minmax(X) -> tuple[float, float]:
    """Return min/max without densifying a scipy sparse matrix."""
    if sparse.issparse(X):
        if X.nnz == 0:
            return 0.0, 0.0
        lo = float(np.min(X.data))
        hi = float(np.max(X.data))
        if X.nnz < int(np.prod(X.shape)):
            lo = min(lo, 0.0)
            hi = max(hi, 0.0)
        return lo, hi
    A = np.asarray(X)
    return float(np.min(A)), float(np.max(A))


def matrix_mean(X) -> np.ndarray:
    if sparse.issparse(X):
        return np.asarray(X.mean(axis=0), dtype=np.float32).ravel()
    return np.asarray(X, dtype=np.float32).mean(axis=0, dtype=np.float64).astype(np.float32)


def matrix_variance(X) -> np.ndarray:
    """Per-column population variance without dense materialization."""
    if sparse.issparse(X):
        mu = np.asarray(X.mean(axis=0), dtype=np.float64).ravel()
        ex2 = np.asarray(X.multiply(X).mean(axis=0), dtype=np.float64).ravel()
        return np.maximum(ex2 - mu * mu, 0.0).astype(np.float32)
    A = np.asarray(X, dtype=np.float32)
    return A.var(axis=0, dtype=np.float64).astype(np.float32)


def take_rows(X, idx: np.ndarray):
    if sparse.issparse(X):
        return X[idx].astype(np.float32, copy=False).tocsr()
    return np.asarray(X[idx], dtype=np.float32)


def dense_rows_cols(X, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    if sparse.issparse(X):
        return X[rows][:, cols].toarray().astype(np.float32, copy=False)
    return np.asarray(X[np.ix_(rows, cols)], dtype=np.float32)


def align_genes(a: ad.AnnData, b: ad.AnnData) -> tuple[ad.AnnData, ad.AnnData]:
    """Return views with the same genes in A's order."""
    _assert_unique_genes(a, "A")
    _assert_unique_genes(b, "B")

    a_genes = list(map(str, a.var_names))
    b_genes = set(map(str, b.var_names))
    a_set = set(a_genes)
    if a_set != b_genes:
        missing = [g for g in a_genes if g not in b_genes][:8]
        extra = [g for g in map(str, b.var_names) if g not in a_set][:8]
        raise ValueError(
            "A and B do not contain the same genes. "
            f"Missing from B: {missing}; extra in B: {extra}"
        )
    return a, b[:, a_genes]


def spatial_coords(adata: ad.AnnData) -> np.ndarray | None:
    if SPATIAL_KEY not in adata.obsm:
        return None
    C = np.asarray(adata.obsm[SPATIAL_KEY], dtype=np.float32)
    if C.ndim != 2 or C.shape[0] != adata.n_obs or C.shape[1] < 3:
        raise ValueError(
            f"{SPATIAL_KEY!r} must have shape (n_cells, >=3); got {C.shape}"
        )
    if not np.isfinite(C[:, :3]).all():
        raise ValueError(f"{SPATIAL_KEY!r} contains non-finite values")
    return C[:, :3]


def validate_pair(a: ad.AnnData, b: ad.AnnData) -> tuple[ad.AnnData, ad.AnnData]:
    """Check compatible inputs without materializing sparse expression matrices."""
    a, b = align_genes(a, b)
    for label, obj in (("A", a), ("B", b)):
        if obj.X.ndim != 2 or obj.X.shape != obj.shape:
            raise ValueError(f"{label}.X has unexpected shape {obj.X.shape}")
        if not _matrix_finite(obj.X):
            raise ValueError(f"{label}.X contains non-finite values")
        spatial_coords(obj)
    return a, b


def validate_submission_output(adata: ad.AnnData) -> None:
    """Validate the mechanical scorer contract shared by blend outputs."""
    _assert_unique_genes(adata, "output")
    if adata.n_obs <= 0 or adata.n_vars <= 0:
        raise ValueError("output must contain at least one cell and one gene")
    if adata.X.ndim != 2 or adata.X.shape != adata.shape:
        raise ValueError(f"output.X has unexpected shape {adata.X.shape}")
    if not _matrix_finite(adata.X):
        raise ValueError("output.X contains non-finite values")
    x_min, _ = matrix_minmax(adata.X)
    if x_min < 0:
        raise ValueError(
            f"output.X contains negative expression values (min={x_min:.6g}); "
            "veckit expects nonnegative log-normalized expression"
        )
    spatial_coords(adata)


def build_output(
    X,
    template: ad.AnnData,
    *,
    coords: np.ndarray | None = None,
    obs_indices: Iterable[int] | None = None,
    obs_prefix: str = "blend",
) -> ad.AnnData:
    if sparse.issparse(X):
        X2 = X.astype(np.float32, copy=False).tocsr()
    else:
        X2 = np.asarray(X, dtype=np.float32)
    n = X2.shape[0]
    if X2.ndim != 2 or X2.shape[1] != template.n_vars:
        raise ValueError(
            f"Output X must have shape (n, {template.n_vars}); got {X2.shape}"
        )

    if obs_indices is None:
        obs = None
    else:
        idx = np.asarray(list(obs_indices), dtype=int)
        obs = template.obs.iloc[idx].copy()

    out = ad.AnnData(X=X2, var=template.var.copy(), obs=obs)
    out.var_names = template.var_names.copy()
    out.obs_names = [f"{obs_prefix}_{i:06d}" for i in range(n)]

    if coords is not None:
        coords = np.asarray(coords, dtype=np.float32)
        if coords.shape != (n, 3):
            raise ValueError(f"coords must have shape {(n, 3)}; got {coords.shape}")
        out.obsm[SPATIAL_KEY] = coords

    out.uns["vec_blender"] = {"format_version": 2}
    return out


def summarize(path: str | Path, adata: ad.AnnData) -> dict:
    C = spatial_coords(adata)
    lo, hi = matrix_minmax(adata.X)
    return {
        "path": str(path),
        "cells": int(adata.n_obs),
        "genes": int(adata.n_vars),
        "sparse_X": bool(sparse.issparse(adata.X)),
        "spatial_3D": C is not None,
        "x_min": lo,
        "x_max": hi,
        "finite": _matrix_finite(adata.X),
        "nonnegative": bool(lo >= 0),
    }
