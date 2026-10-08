from __future__ import annotations

import gzip
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np


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

T3_GENOTYPE_WARNING = (
    "T3_GENOTYPE_NOT_AUDITED: this adapter only handles file/schema/stage mechanics. "
    "It does not determine whether a perturbation, allele, phenocopy, or related genotype is eligible."
)


def canonical_task(task: str) -> str:
    key = task.strip().lower()
    if key not in TASK_ALIASES:
        raise ValueError(f"Unknown task {task!r}")
    return TASK_ALIASES[key]


def parse_stage(value) -> float:
    """Parse one explicit embryonic-day label and fail closed on ambiguous staging.

    Accepted examples: E8.5, E8_75, 9.5, "embryonic day 9.0".
    Ranges, Theiler/somite labels, and strings containing extra stage-like numbers are
    rejected so a protected mixed-stage sample cannot silently collapse to one endpoint.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        raise ValueError("missing stage")
    if isinstance(value, (int, float, np.integer, np.floating)):
        x = float(value)
        if not np.isfinite(x):
            raise ValueError(f"non-finite stage {value!r}")
        return x

    raw = str(value).strip()
    low = raw.lower()
    if re.search(r"(?:theiler|\bts\s*\d|somite|\bss\s*\d)", low):
        raise ValueError(f"Non-embryonic-day staging needs a source-specific parser: {value!r}")
    if re.search(r"[–—/]", raw) or re.search(r"\d\s*-\s*[Ee]?\s*\d", raw):
        raise ValueError(f"Ambiguous stage range: {value!r}")

    normalized = re.sub(r"(?<=\d)_(?=\d)", ".", raw)
    m = re.fullmatch(
        r"\s*(?:(?:embryonic\s+day|day)\s*)?[Ee]?\s*(\d+(?:\.\d+)?)\s*(?:dpc|days?)?\s*",
        normalized,
        flags=re.IGNORECASE,
    )
    if not m:
        raise ValueError(f"Expected one embryonic-day label, got {value!r}")
    return float(m.group(1))


def stage_allowed(task: str, stage: float) -> bool:
    """Apply only the challenge's mechanically specified stage windows.

    Task 3 has genotype/perturbation restrictions that cannot be decided from stage
    alone, so stage_allowed returns True there and callers must surface the explicit
    T3_GENOTYPE_NOT_AUDITED warning.
    """
    task = canonical_task(task)
    if task == "t3":
        return True
    return not any(w.contains(float(stage)) for w in PROTECTED_WINDOWS[task])


def warn_if_t3_not_audited(task: str) -> None:
    if canonical_task(task) == "t3":
        print(f"WARNING: {T3_GENOTYPE_WARNING}", file=sys.stderr)


def task_safety_metadata(task: str) -> dict:
    task = canonical_task(task)
    return {
        "stage_filter_applied": task != "t3",
        "t3_genotype_audit": "not_audited" if task == "t3" else "not_applicable",
        "safety_note": T3_GENOTYPE_WARNING if task == "t3" else None,
    }


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


def standardize_spatial_3d(adata, *, allowed_obs_triples=None, allowed_obsm_keys=None):
    """Copy an observed 3-D coordinate representation into obsm['spatial_3D'].

    Source adapters should pass the exact keys/columns they have validated when known.
    The generic defaults remain for explicitly generic use, but source-specific code can
    now fail rather than guessing from unrelated coordinate-looking columns.
    """
    if "spatial_3D" in adata.obsm:
        arr = np.asarray(adata.obsm["spatial_3D"], dtype=np.float32)
        if arr.ndim == 2 and arr.shape[1] >= 3:
            adata.obsm["spatial_3D"] = arr[:, :3]
            return "obsm:spatial_3D"

    obsm_keys = tuple(allowed_obsm_keys) if allowed_obsm_keys is not None else (
        "spatial", "X_spatial", "spatial3d", "coords"
    )
    for key in obsm_keys:
        if key in adata.obsm:
            arr = np.asarray(adata.obsm[key], dtype=np.float32)
            if arr.ndim == 2 and arr.shape[1] >= 3:
                adata.obsm["spatial_3D"] = arr[:, :3]
                return f"obsm:{key}"

    cols = {str(c).lower(): c for c in adata.obs.columns}
    candidates = tuple(allowed_obs_triples) if allowed_obs_triples is not None else (
        ("x", "y", "z"),
        ("x_coord", "y_coord", "z_coord"),
        ("xcoord", "ycoord", "zcoord"),
        ("center_x", "center_y", "center_z"),
        ("centroid_x", "centroid_y", "centroid_z"),
    )
    for trio in candidates:
        trio = tuple(str(x).lower() for x in trio)
        if all(c in cols for c in trio):
            arr = adata.obs[[cols[c] for c in trio]].to_numpy(dtype=np.float32)
            adata.obsm["spatial_3D"] = arr
            return "obs:" + ",".join(trio)
    return None


def write_provenance(path: Path, **payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def infer_stage_from_name(name: str) -> float:
    matches = re.findall(r"[Ee](\d+(?:[._]\d+)?)", name)
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one embryonic-day token in filename {name!r}; found {matches or 'none'}. "
            "Pass --stage explicitly when the source naming is more complicated."
        )
    return float(matches[0].replace("_", "."))


def open_text_maybe_gzip(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if str(path).endswith(".gz") else path.open("r", encoding="utf-8")
