from __future__ import annotations

from pathlib import Path
from typing import Iterable

import anndata as ad
import numpy as np
from scipy import sparse


SPATIAL_KEY = "spatial_3D"


def read_h5ad(path: str | Path) -> ad.AnnData:
    return ad.read_h5ad(Path(path))


def dense_x(adata: ad.AnnData, *, dtype=np.float64) -> np.ndarray:
    X = adata.X
    if sparse.issparse(X):
        X = X.toarray()
    return np.asarray(X, dtype=dtype)


def _assert_unique_genes(adata: ad.AnnData, label: str) -> None:
    if not adata.var_names.is_unique:
        duplicated = adata.var_names[adata.var_names.duplicated()].tolist()[:8]
        raise ValueError(f"{label} has duplicate var_names, e.g. {duplicated}")


def align_genes(
    a: ad.AnnData, b: ad.AnnData
) -> tuple[ad.AnnData, ad.AnnData]:
    """Return views with the same genes in A's order.

    VEC submissions are expected to describe the same target gene panel. We fail
    rather than silently taking an intersection, because dropping genes can turn a
    syntactically valid blend into an invalid challenge submission.
    """
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
    b2 = b[:, a_genes]
    return a, b2


def spatial_coords(adata: ad.AnnData) -> np.ndarray | None:
    if SPATIAL_KEY not in adata.obsm:
        return None
    C = np.asarray(adata.obsm[SPATIAL_KEY], dtype=np.float64)
    if C.ndim != 2 or C.shape[0] != adata.n_obs or C.shape[1] < 3:
        raise ValueError(
            f"{SPATIAL_KEY!r} must have shape (n_cells, >=3); got {C.shape}"
        )
    if not np.isfinite(C[:, :3]).all():
        raise ValueError(f"{SPATIAL_KEY!r} contains non-finite values")
    return C[:, :3]


def validate_pair(a: ad.AnnData, b: ad.AnnData) -> tuple[ad.AnnData, ad.AnnData]:
    a, b = align_genes(a, b)
    for label, obj in (("A", a), ("B", b)):
        X = dense_x(obj)
        if X.ndim != 2 or X.shape != obj.shape:
            raise ValueError(f"{label}.X has unexpected shape {X.shape}")
        if not np.isfinite(X).all():
            raise ValueError(f"{label}.X contains non-finite values")
        spatial_coords(obj)
    return a, b


def build_output(
    X: np.ndarray,
    template: ad.AnnData,
    *,
    coords: np.ndarray | None = None,
    obs_indices: Iterable[int] | None = None,
    obs_prefix: str = "blend",
) -> ad.AnnData:
    X = np.asarray(X, dtype=np.float32)
    n = X.shape[0]
    if X.ndim != 2 or X.shape[1] != template.n_vars:
        raise ValueError(
            f"Output X must have shape (n, {template.n_vars}); got {X.shape}"
        )

    if obs_indices is None:
        # Mixed/generated rows do not necessarily correspond to template.obs.
        obs = None
    else:
        idx = np.asarray(list(obs_indices), dtype=int)
        obs = template.obs.iloc[idx].copy()

    out = ad.AnnData(X=X, var=template.var.copy(), obs=obs)
    out.var_names = template.var_names.copy()
    out.obs_names = [f"{obs_prefix}_{i:06d}" for i in range(n)]

    if coords is not None:
        coords = np.asarray(coords, dtype=np.float32)
        if coords.shape != (n, 3):
            raise ValueError(f"coords must have shape {(n, 3)}; got {coords.shape}")
        out.obsm[SPATIAL_KEY] = coords

    out.uns["vec_blender"] = {"format_version": 1}
    return out


def summarize(path: str | Path, adata: ad.AnnData) -> dict:
    C = spatial_coords(adata)
    X = dense_x(adata)
    return {
        "path": str(path),
        "cells": int(adata.n_obs),
        "genes": int(adata.n_vars),
        "spatial_3D": C is not None,
        "x_min": float(np.min(X)),
        "x_max": float(np.max(X)),
        "finite": bool(np.isfinite(X).all()),
    }
