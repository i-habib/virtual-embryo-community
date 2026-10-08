#!/usr/bin/env python3
"""Rebuild a sparse raw-count AnnData from the GSE150817 per-cell UMI table.

The table is a gzipped TSV. Its first line holds cell barcodes, and each later line
holds one gene followed by its UMI counts. Rows are read in chunks, so memory scales
with the chunk size and the stored non-zero entries rather than the full table.

Usage:
    python scripts/rebuild_gse150817_counts.py SOURCE.tsv.gz --out OUT.h5ad [--cells CELLS.txt]

CELLS.txt, when given, lists one cell barcode per line. The output keeps those cells in
that order. Without it, every cell column in the table is kept.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

CHUNK_GENES = 64


def read_cell_list(path: str | Path) -> list[str]:
    cells = [line.strip() for line in Path(path).read_text().splitlines() if line.strip()]
    if not cells or len(cells) != len(set(cells)):
        raise ValueError(f"Cell list must be non-empty and unique: {path}")
    return cells


def table_header(source: Path) -> list[str]:
    import gzip

    with gzip.open(source, "rt") as stream:
        return stream.readline().rstrip("\n").split("\t")[1:]


def rebuild(source: str | Path, out: str | Path, cells: list[str] | None = None) -> ad.AnnData:
    source = Path(source)
    table_cells = table_header(source)
    if cells is None:
        cells = table_cells
    position = {cell: i for i, cell in enumerate(table_cells)}
    absent = [cell for cell in cells if cell not in position]
    if absent:
        raise ValueError(f"{len(absent)} requested cells are absent from the table; first: {absent[:5]}")
    # Column 0 is the gene name. Cell columns are read in table order, then reordered by name.
    usecols = [0] + sorted(position[cell] + 1 for cell in set(cells))

    gene_blocks, genes = [], []
    reader = pd.read_csv(source, sep="\t", header=0, index_col=0, usecols=usecols,
                         dtype={cell: np.int32 for cell in cells}, chunksize=CHUNK_GENES, compression="gzip")
    for chunk in reader:
        genes.extend(map(str, chunk.index))
        gene_blocks.append(sparse.csr_matrix(chunk[cells].to_numpy(dtype=np.int32, copy=False)))
    counts = sparse.vstack(gene_blocks, format="csr").T.tocsr()
    result = ad.AnnData(
        X=counts,
        obs=pd.DataFrame(index=pd.Index(cells, name="cell")),
        var=pd.DataFrame(index=pd.Index(genes, name="gene")),
    )
    result.uns["source"] = {
        "raw_counts_tsv": source.name,
        "cells": len(cells),
        "genes": len(genes),
        "nonzero_entries": int(counts.nnz),
    }
    result.write_h5ad(out, compression="gzip")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source")
    parser.add_argument("--out", required=True)
    parser.add_argument("--cells")
    args = parser.parse_args(argv)
    cells = read_cell_list(args.cells) if args.cells else None
    result = rebuild(args.source, args.out, cells)
    print(json.dumps({"shape": list(result.shape), "nnz": int(result.X.nnz), "output": args.out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
