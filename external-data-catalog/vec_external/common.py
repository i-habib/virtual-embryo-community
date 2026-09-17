from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StageWindow:
    lo: float
    hi: float
    include_lo: bool
    include_hi: bool

    def contains(self, x: float) -> bool:
        return (x > self.lo or (self.include_lo and x == self.lo)) and (
            x < self.hi or (self.include_hi and x == self.hi)
        )


PROTECTED_WINDOWS = {
    "t1": (StageWindow(9.5, 13.5, False, True),),
    "t2-heart": (
        StageWindow(8.25, 8.75, False, False),
        StageWindow(9.5, 13.5, False, True),
    ),
    "t2-embryo": (StageWindow(7.25, 8.0, False, False),),
}

TASK_ALIASES = {
    "t1": "t1", "task1": "t1",
    "t2-heart": "t2-heart", "heart": "t2-heart", "t2_heart": "t2-heart",
    "t2-embryo": "t2-embryo", "embryo": "t2-embryo", "t2_embryo": "t2-embryo",
    "t3": "t3", "task3": "t3",
}

STAGE_CANDIDATES = (
    "stage", "developmental_stage", "development_stage", "embryonic_day",
    "timepoint", "time_point", "age", "day",
)


def canonical_task(task: str) -> str:
    key = task.strip().lower()
    if key not in TASK_ALIASES:
        raise ValueError(f"Unknown task {task!r}")
    return TASK_ALIASES[key]


def parse_stage(value) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        raise ValueError("missing stage")
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    s = str(value).strip().lower().replace("_", ".")
    # Handles E8.5, e8_5, 8.5, E8.5TS12 and similar labels.
    m = re.search(r"(?:^|\b)e?\s*(\d+(?:\.\d+)?)", s)
    if not m:
        raise ValueError(f"Could not parse embryonic day from {value!r}")
    return float(m.group(1))


def stage_allowed(task: str, stage: float) -> bool:
    task = canonical_task(task)
    if task == "t3":
        return True  # genotype restrictions need a separate audit; these adapters use WT sources.
    return not any(w.contains(float(stage)) for w in PROTECTED_WINDOWS[task])


def find_stage_column(columns: Iterable[str], preferred: Optional[str] = None) -> str:
    cols = list(columns)
    if preferred:
        if preferred not in cols:
            raise KeyError(f"Stage column {preferred!r} not found. Available: {cols}")
        return preferred
    lower = {str(c).lower(): c for c in cols}
    for name in STAGE_CANDIDATES:
        if name in lower:
            return lower[name]
    for c in cols:
        lc = str(c).lower()
        if "stage" in lc or "timepoint" in lc or "embry" in lc:
            return c
    raise KeyError(f"Could not infer a stage column. Pass --stage-column. Available: {cols}")


def stage_mask(values: Iterable, task: str):
    parsed = np.array([parse_stage(v) for v in values], dtype=float)
    keep = np.array([stage_allowed(task, x) for x in parsed], dtype=bool)
    return keep, parsed


def load_gene_list(path: Optional[Path]):
    if path is None:
        return None
    genes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            genes.append(s.split()[0])
    if len(set(genes)) != len(genes):
        raise ValueError("Gene list contains duplicates")
    return genes


def subset_genes(adata, genes):
    if not genes:
        return adata, {"requested": None, "kept": int(adata.n_vars), "missing": []}
    present = set(map(str, adata.var_names))
    keep = [g for g in genes if g in present]
    missing = [g for g in genes if g not in present]
    if not keep:
        raise ValueError("None of the requested genes are present")
    return adata[:, keep].copy(), {"requested": len(genes), "kept": len(keep), "missing": missing}


def normalize_total_log1p(adata, target_sum: float = 1e4):
    from scipy import sparse
    X = adata.X
    totals = np.asarray(X.sum(axis=1)).ravel()
    scale = np.divide(target_sum, totals, out=np.zeros_like(totals, dtype=float), where=totals > 0)
    if sparse.issparse(X):
        X = sparse.diags(scale) @ X
        X = X.tocsr(copy=False)
        X.data = np.log1p(X.data)
    else:
        X = np.log1p(np.asarray(X, dtype=float) * scale[:, None])
    adata.X = X.astype(np.float32)
    return adata


def standardize_spatial_3d(adata):
    if "spatial_3D" in adata.obsm:
        arr = np.asarray(adata.obsm["spatial_3D"], dtype=np.float32)
        if arr.ndim == 2 and arr.shape[1] >= 3:
            adata.obsm["spatial_3D"] = arr[:, :3]
            return "obsm:spatial_3D"
    for key in ("spatial", "X_spatial", "spatial3d", "coords"):
        if key in adata.obsm:
            arr = np.asarray(adata.obsm[key], dtype=np.float32)
            if arr.ndim == 2 and arr.shape[1] >= 3:
                adata.obsm["spatial_3D"] = arr[:, :3]
                return f"obsm:{key}"
    cols = {str(c).lower(): c for c in adata.obs.columns}
    candidates = [
        ("x", "y", "z"),
        ("x_coord", "y_coord", "z_coord"),
        ("xcoord", "ycoord", "zcoord"),
        ("center_x", "center_y", "center_z"),
        ("centroid_x", "centroid_y", "centroid_z"),
    ]
    for trio in candidates:
        if all(c in cols for c in trio):
            arr = adata.obs[[cols[c] for c in trio]].to_numpy(dtype=np.float32)
            adata.obsm["spatial_3D"] = arr
            return "obs:" + ",".join(trio)
    return None


def write_provenance(path: Path, **payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def infer_stage_from_name(name: str) -> float:
    m = re.search(r"[Ee](\d+)[._](\d+)", name)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"[Ee](\d+(?:\.\d+)?)", name)
    if m:
        return float(m.group(1))
    raise ValueError(f"Could not infer stage from filename {name!r}; pass it explicitly")


def open_text_maybe_gzip(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if str(path).endswith(".gz") else path.open("r", encoding="utf-8")
