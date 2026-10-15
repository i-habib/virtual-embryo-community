"""Stage container and .h5ad I/O.

A Stage holds one timepoint as dense arrays: X (cells x genes, log1p CP10k), coords (cells x 3,
obsm['spatial_3D']), ct (cell-type labels, obs['celltype']) and genes. Prepared stage files are small
enough to hold three at once; released files are read one at a time by prepare.py.
"""
from __future__ import annotations

from dataclasses import dataclass

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse


@dataclass
class Stage:
    name: str
    time: float
    X: np.ndarray
    coords: np.ndarray
    ct: np.ndarray
    genes: np.ndarray
    has_coords: bool = True  # False for stages without obsm['spatial_3D'] (T1 pairs); coords is then zeros

    def __len__(self) -> int:
        return int(self.X.shape[0])

    def take(self, idx, name: str | None = None) -> "Stage":
        idx = np.asarray(idx)
        return Stage(name or self.name, self.time, self.X[idx], self.coords[idx], self.ct[idx], self.genes,
                     self.has_coords)


def read_stage(path, name: str, time: float) -> Stage:
    return stage_from_adata(ad.read_h5ad(path), name, time)


def read_subsample(path, name: str, time: float, idx) -> Stage:
    """Read only the rows in idx from a released file (backed mode), so the full matrix is never loaded."""
    backed = ad.read_h5ad(path, backed="r")
    try:
        sub = backed[np.asarray(idx)].to_memory()
    finally:
        backed.file.close()
    return stage_from_adata(sub, name, time)


def stage_from_adata(a, name: str, time: float) -> Stage:
    X = a.X.toarray() if sparse.issparse(a.X) else np.asarray(a.X)
    if "celltype" not in a.obs:
        raise KeyError(f"{path}: obs['celltype'] is missing")
    has_coords = "spatial_3D" in a.obsm
    if has_coords:
        coords = np.asarray(a.obsm["spatial_3D"])[:, :3]
    else:
        coords = np.zeros((a.n_obs, 3))
    return Stage(
        name=name,
        time=float(time),
        X=np.asarray(X, dtype=np.float32),
        coords=np.asarray(coords, dtype=np.float32),
        ct=a.obs["celltype"].astype(str).to_numpy(),
        genes=a.var_names.to_numpy().astype(str),
        has_coords=has_coords,
    )


def write_stage(stage: Stage, path) -> None:
    n = len(stage)
    obs = pd.DataFrame(
        {"celltype": stage.ct.astype(str)},
        index=pd.Index([f"{stage.name}_{i}" for i in range(n)]),
    )
    a = ad.AnnData(
        X=np.asarray(stage.X, dtype=np.float32),
        obs=obs,
        var=pd.DataFrame(index=pd.Index(stage.genes.astype(str))),
    )
    if stage.has_coords:
        a.obsm["spatial_3D"] = np.asarray(stage.coords, dtype=np.float32)
    a.uns["stage"] = stage.name
    a.uns["time"] = float(stage.time)
    a.write_h5ad(path)


def split_half(n: int, seed: int):
    """Seeded split of n cells into two disjoint halves: (half_a, half_b)."""
    perm = np.random.default_rng(seed).permutation(n)
    h = n // 2
    return np.sort(perm[:h]), np.sort(perm[h:])
