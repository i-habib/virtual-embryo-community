#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vec_external.common import infer_stage_from_name, stage_allowed, load_gene_list, subset_genes, standardize_spatial_3d, write_provenance


def main():
    p = argparse.ArgumentParser(description="Prepare public sc3D/Slide-seq embryo h5ad files for a VEC task.")
    p.add_argument("inputs", nargs="+", type=Path)
    p.add_argument("--task", required=True, choices=["t1", "t2-heart", "t2-embryo", "t3"])
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--gene-list", type=Path)
    p.add_argument("--stage", action="append", type=float, help="explicit stage per input, in input order")
    args = p.parse_args()
    if args.stage and len(args.stage) != len(args.inputs):
        raise ValueError("Provide one --stage per input or none")

    import anndata as ad
    genes = load_gene_list(args.gene_list)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(args.inputs):
        stage = args.stage[i] if args.stage else infer_stage_from_name(src.name)
        if not stage_allowed(args.task, stage):
            print(f"SKIP {src.name}: E{stage:g} is protected for {args.task}")
            continue
        a = ad.read_h5ad(src)
        spatial_source = standardize_spatial_3d(a)
        a, gene_report = subset_genes(a, genes)
        a.obs["vec_stage"] = float(stage)
        out = args.out_dir / (src.stem + f".{args.task}.h5ad")
        a.write_h5ad(out)
        write_provenance(out.with_suffix(".provenance.json"), source="sc3D / GSE197353",
            task=args.task, stage=stage, input=str(src), output=str(out), cells=int(a.n_obs),
            spatial_source=spatial_source, gene_report=gene_report,
            source_url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE197353",
            rules_snapshot="2026-09-16")
        print(f"wrote {out} ({a.n_obs} cells, E{stage:g}, spatial={spatial_source})")

if __name__ == "__main__": main()
