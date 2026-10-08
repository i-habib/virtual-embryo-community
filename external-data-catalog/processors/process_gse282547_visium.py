#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vec_external.common import (
    load_gene_list,
    stage_allowed,
    subset_genes,
    task_safety_metadata,
    warn_if_t3_not_audited,
    write_provenance,
)


def _one(raw_dir: Path, suffix: str) -> Path:
    hits = sorted(raw_dir.glob(f"*{suffix}"))
    if len(hits) != 1:
        raise FileNotFoundError(f"Expected exactly one *{suffix} in {raw_dir}; found {[p.name for p in hits]}")
    return hits[0]


def _read_tsv(path: Path, **kwargs):
    import pandas as pd
    return pd.read_csv(path, sep="\t", header=None, compression="infer", **kwargs)


def read_visium_release(raw_dir: Path):
    import anndata as ad
    import numpy as np
    import pandas as pd
    from scipy import sparse
    from scipy.io import mmread

    matrix_path = _one(raw_dir, "_matrix.mtx.gz")
    features_path = _one(raw_dir, "_features.tsv.gz")
    barcodes_path = _one(raw_dir, "_barcodes.tsv.gz")
    positions_path = _one(raw_dir, "_tissue_positions_list.csv.gz")

    X = mmread(matrix_path).tocsr().T.astype("float32")
    features = _read_tsv(features_path)
    barcodes = _read_tsv(barcodes_path)[0].astype(str)
    positions = pd.read_csv(positions_path, header=None, compression="infer")
    if positions.shape[1] < 6:
        raise ValueError(f"Expected six Visium position columns, got {positions.shape[1]}")
    positions = positions.iloc[:, :6].copy()
    positions.columns = ["barcode", "in_tissue", "array_row", "array_col", "pxl_row", "pxl_col"]
    positions["barcode"] = positions["barcode"].astype(str)
    positions = positions.set_index("barcode")

    if X.shape[0] != len(barcodes):
        raise ValueError(f"Matrix/barcode mismatch: {X.shape[0]} spots vs {len(barcodes)} barcodes")
    if X.shape[1] != len(features):
        raise ValueError(f"Matrix/feature mismatch: {X.shape[1]} genes vs {len(features)} features")

    feature_type = features.iloc[:, 2].astype(str) if features.shape[1] >= 3 else pd.Series(["Gene Expression"] * len(features))
    gene_mask = feature_type.eq("Gene Expression").to_numpy()
    if not gene_mask.any():
        raise ValueError("No 'Gene Expression' features found")
    X = X[:, gene_mask]
    features = features.loc[gene_mask].reset_index(drop=True)

    symbols = features.iloc[:, 1].astype(str) if features.shape[1] >= 2 else features.iloc[:, 0].astype(str)
    ids = features.iloc[:, 0].astype(str)
    obs = pd.DataFrame(index=barcodes.to_numpy())
    a = ad.AnnData(X=sparse.csr_matrix(X), obs=obs)
    a.var_names = symbols.to_numpy()
    a.var["gene_id"] = ids.to_numpy()
    a.var_names_make_unique()

    common = a.obs_names.intersection(positions.index)
    if len(common) != a.n_obs:
        missing = a.n_obs - len(common)
        raise ValueError(f"Positions missing for {missing} matrix barcodes")
    positions = positions.loc[a.obs_names]
    for col in ["in_tissue", "array_row", "array_col"]:
        a.obs[col] = positions[col].to_numpy()

    # GEO distributes a 2-D Visium section. Keep it explicitly 2-D rather than
    # manufacturing a challenge-style z coordinate.
    a.obsm["spatial_2D"] = positions[["pxl_col", "pxl_row"]].to_numpy(dtype=np.float32)
    a.uns["spatial_coordinate_source"] = "Visium pxl_col,pxl_row from tissue_positions_list"

    return a, {
        "matrix": matrix_path.name,
        "features": features_path.name,
        "barcodes": barcodes_path.name,
        "positions": positions_path.name,
    }


def main():
    p = argparse.ArgumentParser(description="Convert one GSE282547 Visium sample into an audited AnnData object.")
    p.add_argument("raw_dir", type=Path, help="directory containing one sample's matrix/features/barcodes/positions files")
    p.add_argument("--stage", type=float, required=True, help="embryonic day, e.g. 14.5")
    p.add_argument("--task", required=True, choices=["t1", "t2-heart", "t2-embryo", "t3"])
    p.add_argument("--gene-list", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    warn_if_t3_not_audited(args.task)
    if not stage_allowed(args.task, args.stage):
        raise ValueError(f"E{args.stage:g} is protected for {args.task}; refusing to write output")

    a, source_files = read_visium_release(args.raw_dir)
    before_genes = int(a.n_vars)
    genes = load_gene_list(args.gene_list)
    a, gene_report = subset_genes(a, genes)
    a.obs["vec_stage"] = float(args.stage)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    a.write_h5ad(args.out)
    write_provenance(
        args.out.with_suffix(".provenance.json"),
        source="GSE282547 developing-heart Visium",
        source_url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE282547",
        task=args.task,
        stage=float(args.stage),
        input_dir=str(args.raw_dir),
        source_files=source_files,
        output=str(args.out),
        cells=int(a.n_obs),
        genes_before_panel=before_genes,
        genes_after_panel=int(a.n_vars),
        gene_report=gene_report,
        spatial_2d_present=True,
        spatial_3d_present=False,
        spatial_note="This GEO release is a 2-D tissue section; no z coordinate is invented.",
        rules_snapshot="2026-09-17",
        **task_safety_metadata(args.task),
    )
    print(f"wrote {args.out}: {a.n_obs} spots, {a.n_vars} genes, spatial_2D=yes, spatial_3D=no")


if __name__ == "__main__":
    main()
