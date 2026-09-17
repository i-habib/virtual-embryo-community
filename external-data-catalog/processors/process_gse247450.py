#!/usr/bin/env python3
from __future__ import annotations
import argparse
import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vec_external.common import infer_stage_from_name, stage_allowed, load_gene_list, subset_genes, standardize_spatial_3d, write_provenance


def _sample_key(path: Path):
    name = path.name
    name = re.sub(r"_cell_by_gene\.csv(?:\.gz)?$", "", name)
    name = re.sub(r"_cell_metadata\.csv(?:\.gz)?$", "", name)
    return name


def _read_pair(matrix_path: Path, meta_path: Path):
    import anndata as ad
    import pandas as pd
    matrix = pd.read_csv(matrix_path, index_col=0)
    meta = pd.read_csv(meta_path, index_col=0)
    # Match cell IDs to choose orientation. If neither side matches, fail rather than guess.
    idx_overlap = len(set(map(str, matrix.index)) & set(map(str, meta.index)))
    col_overlap = len(set(map(str, matrix.columns)) & set(map(str, meta.index)))
    if col_overlap > idx_overlap:
        matrix = matrix.T
    elif idx_overlap == 0 and col_overlap == 0:
        raise ValueError(f"Could not match matrix cell IDs to metadata for {matrix_path.name}")
    common = matrix.index.astype(str).intersection(meta.index.astype(str))
    if len(common) == 0:
        raise ValueError(f"No shared cell IDs for {matrix_path.name}")
    matrix.index = matrix.index.astype(str)
    meta.index = meta.index.astype(str)
    matrix = matrix.loc[common]
    meta = meta.loc[common]
    a = ad.AnnData(X=matrix.to_numpy(dtype="float32"), obs=meta.copy())
    a.var_names = matrix.columns.astype(str)
    a.obs_names = common
    return a


def main():
    p = argparse.ArgumentParser(description="Convert GSE247450 MERFISH CSV pairs to task-audited h5ad files.")
    p.add_argument("raw_dir", type=Path, help="directory containing extracted *_cell_by_gene.csv.gz and *_cell_metadata.csv.gz")
    p.add_argument("--task", required=True, choices=["t1", "t2-heart", "t2-embryo", "t3"])
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--gene-list", type=Path)
    args = p.parse_args()

    matrices = {_sample_key(p): p for p in args.raw_dir.glob("*cell_by_gene.csv*")}
    metas = {_sample_key(p): p for p in args.raw_dir.glob("*cell_metadata.csv*")}
    keys = sorted(set(matrices) & set(metas))
    if not keys:
        raise FileNotFoundError("No matrix/metadata pairs found")
    genes = load_gene_list(args.gene_list)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for key in keys:
        stage = infer_stage_from_name(key)
        if not stage_allowed(args.task, stage):
            print(f"SKIP {key}: E{stage:g} is protected for {args.task}")
            continue
        a = _read_pair(matrices[key], metas[key])
        spatial_source = standardize_spatial_3d(a)
        a, gene_report = subset_genes(a, genes)
        a.obs["vec_stage"] = float(stage)
        out = args.out_dir / f"{key}.{args.task}.h5ad"
        a.write_h5ad(out)
        write_provenance(out.with_suffix(".provenance.json"), source="GSE247450 MERFISH endothelial atlas",
            task=args.task, stage=stage, matrix=str(matrices[key]), metadata=str(metas[key]),
            output=str(out), cells=int(a.n_obs), spatial_source=spatial_source, gene_report=gene_report,
            source_url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE247450",
            rules_snapshot="2026-09-16")
        print(f"wrote {out} ({a.n_obs} cells, {a.n_vars} genes)")

if __name__ == "__main__": main()
