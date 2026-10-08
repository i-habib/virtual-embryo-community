# Panel normalisation for Virtual Embryo data

`vec_normalise.py` maps mouse gene names in a raw count matrix onto a challenge gene panel and writes natural-log CP10k computed over the panel genes only, so the values match the challenge release.

Terms used here:

- **CP10k**: each cell's counts divided by that cell's total over the panel genes, times 10,000.
- **Natural log1p**: log(1 + x) with the natural logarithm, applied after CP10k.
- **Panel**: the board's ordered gene list for a task, downloadable from https://virtualembryo.ai/challenge/data. The Task 2 and Task 3 MERFISH panels have about 500 genes. The Task 1 list (`T1__val.genes.txt`) has 32,285 genes.
- **MGI**: Mouse Genome Informatics gene nomenclature tables. `MRK_List2.rpt` gives current symbols and synonyms, and `MRK_ENSEMBL.rpt` gives mouse Ensembl gene IDs. The tool downloads both unless `--mgi-dir` points to local copies.

## Why the order matters

In the GSE193346 E9.5 heart scRNA-seq (887 cells), the 498 panel genes that match by exact symbol hold a median of 5.3% of each cell's counts (5th to 95th percentile: 0.8% to 7.8%). If you normalise over all genes and then select the panel, the panel values sum to a median of 529 per cell instead of 10,000. Their log1p values are then too low by 2.3 on average over nonzero entries, with a largest gap of 5.3.

## Installation and tests

```sh
python -m pip install anndata numpy pandas scipy pytest
python -m pytest -q
```

The tests passed on Python 3.11 with anndata 0.12.19, pandas 2.3.3, numpy 2.4.6 and scipy 1.17.1. The real-data runs in this README used Python 3.13 with anndata 0.13.4, pandas 3.0.6, numpy 2.5.3 and scipy 1.18.1.

## Commands

```sh
# Report how each input column resolves, without writing a matrix
python vec_normalise.py resolve raw.h5ad --panel T2__heart__val_interp.genes.txt --mgi-dir mgi --report mapping.tsv

# Normalise raw counts over a panel (Tasks 2 and 3)
python vec_normalise.py normalise raw.h5ad --panel T2__heart__val_interp.genes.txt --out panel.h5ad --mgi-dir mgi --report mapping.tsv

# Normalise over the Task 1 list, zero-filling genes the input lacks
python vec_normalise.py normalise raw.h5ad --panel T1__val.genes.txt --out task1.h5ad --fill-missing zeros

# Check a release file against its counts layer
python vec_normalise.py verify release.h5ad --panel T2__heart__val_interp.genes.txt
```

Input must hold raw counts, in `X` or in a layer named with `--layer`. Integer values are required. `--allow-noninteger` accepts raw counts stored as floats, but refuses matrices that look log-transformed (every value below 20 and constant expm1 row sums). To check whether a file holds counts or logged values, use [vec-logcheck](https://github.com/random-guy-05/vec-logcheck). This tool keeps only the minimal guard described above.

## How names are matched

Each input column is resolved to at most one panel symbol, in this order:

- **exact**: the name equals a panel symbol.
- **rescued**: a case-only current symbol, a mouse Ensembl gene ID (version suffix ignored), or an MGI synonym maps to a panel gene that no exact column carries.
- **conflict**: a rescue whose target panel gene is already carried by an exact column. The rescue is refused. For example, the synonym `Palm2` of `Pakap` is refused when `Pakap` is also an input column.
- **ambiguous**: a case-only key or synonym has several current gene symbols, and one is in the panel. The rescue is refused. The name `t` is not mapped to the panel gene `T`.
- **unmatched**: no panel gene matches.
- **missing**: a panel gene with no input column. Normalisation stops unless `--fill-missing zeros` is given.

Only `Gene` and `Pseudogene` MGI records are targets. A current symbol of any other marker type never becomes a synonym of a gene. Ensembl IDs are joined to symbols through the MGI accession. An Ensembl ID that MGI no longer lists is unmatched.

Input columns that resolve to the same panel gene are summed as raw counts, and only then is CP10k applied. The denominator is the sum over the panel genes in the input, so zero-filled genes do not change the total.

## Output

The output has panel-ordered `var_names`, a float32 CSR `X`, and the input `obs`. `var['filled_zero']` marks zero-filled genes. `uns['vec_normalise']` records the input and panel checksums, the MGI report URLs, checksums and download date (written once, when the report is downloaded), the mapping counts, the zero-filled genes, and the target genes that received summed columns. `uns['vec_normalise_mapping']` holds the full mapping table. The `--report` file is the same table as TSV.

## Measured results

The counts come from `resolve` on each input, and the row-sum checks come from `normalise` on the same inputs. The panels are the board's gene lists. The GSE193346 E9.5 input is integer raw counts. The GSE150817 E16.5 input is a sparse raw-count matrix for its 4,200 cells, rebuilt from the public UMI table by [scripts/rebuild_gse150817_counts.py](scripts/rebuild_gse150817_counts.py).

| Input and panel | Exact | Rescued | Conflict | Ambiguous | Unmatched input columns | Missing panel genes | Output (cells × genes) |
|---|---:|---:|---:|---:|---:|---:|---:|
| GSE193346 E9.5, T2 heart | 498 | 2 | 0 | 0 | 30,476 | 0 | 887 × 500 |
| GSE193346 E9.5, Task 1 list | 29,715 | 227 | 7 | 3 | 1,024 | 2,343 | 887 × 32,285 |
| GSE150817 E16.5, T2 heart | 468 | 0 | 0 | 0 | 22,781 | 32 | 4,200 × 500 |
| GSE150817 E16.5, Task 1 list | 19,320 | 1 | 2 | 0 | 3,926 | 12,964 | 4,200 × 32,285 |

Every output has row sums of expm1(X) between 9,999.99 and 10,000.01, so each cell's CP10k total is 10,000 over the panel genes.

Rescued examples from the tables: `Wisp2` maps to `Ccn5`, `Tmem2` maps to `Cemip2`, and `3110035E14Rik` maps to `Vxn` (Task 1 list). Refused example: `Palm2` is a synonym of `Pakap` and is reported as a conflict, because `Pakap` is an exact input column.

The normalisation of the released Task 1 and MERFISH files is described in [NORMALISATION.md](NORMALISATION.md).

## Relation to the External Data Catalog

The [External Data Catalog](../external-data-catalog/) in this repository has processors for Tabula Muris and the Extended Mouse Atlas. Those processors subset to the panel before normalising. This tool adds the alias rescue steps and conflict checks described above, and the same panel-first normalisation order.
