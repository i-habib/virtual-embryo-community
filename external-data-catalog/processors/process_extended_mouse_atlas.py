#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vec_external.common import find_stage_column, stage_mask, load_gene_list, subset_genes, normalize_total_log1p, write_provenance


def main():
    p = argparse.ArgumentParser(description="Prepare Extended Mouse Atlas data for one VEC task.")
    p.add_argument("input", type=Path, help="embryo_complete.h5ad")
    p.add_argument("--task", required=True, choices=["t1", "t2-heart", "t2-embryo", "t3"])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--stage-column")
    p.add_argument("--gene-list", type=Path, help="optional VEC gene list; output keeps intersection in this order")
    p.add_argument("--use-raw-counts", action="store_true", help="use adata.raw counts when present, then normalize total+log1p")
    args = p.parse_args()

    import anndata as ad
    a = ad.read_h5ad(args.input)
    stage_col = find_stage_column(a.obs.columns, args.stage_column)
    keep, parsed = stage_mask(a.obs[stage_col], args.task)
    removed = sorted(set(parsed[~keep].tolist()))
    before = int(a.n_obs)
    a = a[keep].copy()

    if args.use_raw_counts:
        if a.raw is None:
            raise ValueError("--use-raw-counts requested but adata.raw is missing")
        a = a.raw.to_adata()
        a = normalize_total_log1p(a)

    genes = load_gene_list(args.gene_list)
    a, gene_report = subset_genes(a, genes)
    a.obs["vec_stage"] = [float(x) for x in parsed[keep]]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    a.write_h5ad(args.out)
    write_provenance(args.out.with_suffix(".provenance.json"),
        source="Extended Mouse Atlas", task=args.task, input=str(args.input), output=str(args.out),
        stage_column=str(stage_col), cells_before=before, cells_after=int(a.n_obs),
        protected_stages_removed=removed, gene_report=gene_report,
        source_url="https://marionilab.github.io/ExtendedMouseAtlas/",
        rules_snapshot="2026-09-16")
    print(f"wrote {args.out}: {before} -> {a.n_obs} cells; removed stages {removed}")

if __name__ == "__main__": main()
