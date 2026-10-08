#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vec_external.common import load_gene_list, subset_genes, normalize_total_log1p, write_provenance


def main():
    p = argparse.ArgumentParser(description="Prepare adult Tabula Muris expression data as a later-state prior.")
    p.add_argument("input", type=Path, help="TM_droplet_mat.h5ad or TM_facs_mat.h5ad")
    p.add_argument("--metadata", type=Path, help="optional CSV metadata when not already present in obs")
    p.add_argument("--tissue", action="append", help="keep only these tissues; repeat flag for multiple")
    p.add_argument("--tissue-column", default="tissue")
    p.add_argument("--gene-list", type=Path)
    p.add_argument("--normalize", action="store_true", help="normalize raw counts to log1p CP10k")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    import anndata as ad
    import pandas as pd
    a = ad.read_h5ad(args.input)
    if args.metadata:
        meta = pd.read_csv(args.metadata, index_col=0)
        meta.index = meta.index.astype(str)
        a.obs_names = a.obs_names.astype(str)
        common = a.obs_names.intersection(meta.index)
        a = a[common].copy()
        for col in meta.columns:
            a.obs[col] = meta.loc[common, col].to_numpy()
    before = int(a.n_obs)
    if args.tissue:
        if args.tissue_column not in a.obs:
            raise KeyError(f"{args.tissue_column!r} not found in obs")
        wanted = {x.lower() for x in args.tissue}
        mask = a.obs[args.tissue_column].astype(str).str.lower().isin(wanted).to_numpy()
        a = a[mask].copy()
    if args.normalize:
        a = normalize_total_log1p(a)
    genes = load_gene_list(args.gene_list)
    a, gene_report = subset_genes(a, genes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    a.write_h5ad(args.out)
    write_provenance(args.out.with_suffix(".provenance.json"), source="Tabula Muris adult mouse atlas",
        task_note="Adult mouse data are after E13.5; stage restriction is clear, but relevance is mainly cell-state/expression pretraining.",
        input=str(args.input), output=str(args.out), cells_before=before, cells_after=int(a.n_obs),
        tissues=args.tissue, gene_report=gene_report,
        source_url="https://github.com/czbiohub-sf/tabula-muris-vignettes/blob/master/data/README.md",
        rules_snapshot="2026-09-16")
    print(f"wrote {args.out}: {before} -> {a.n_obs} cells")

if __name__ == "__main__": main()
