# Released data normalisation

Every released expression matrix stores natural-log `log1p` of counts per 10,000 (CP10k). What differs between tasks is the denominator, the set of genes a cell's total is taken over:

- **Task 1** (single-cell RNA, E8.5 and E9.5): all 32,285 genes in the whole-transcriptome file.
- **Tasks 2 and 3** (3D MERFISH): only the genes in that file's panel, about 500.

So whole-transcriptome counts from another dataset must be subset to the panel first and normalised second. The challenge data page is https://virtualembryo.ai/challenge/data.

## MERFISH files

`vec_normalise.py verify` recomputes `log1p(counts / row_sum(counts) * 10000)` from the file's `counts` layer and reports the largest absolute difference from `X`. Row sums are of `expm1(X)`. Peak memory is the maximum resident set size of the `verify` process on an 8 GB laptop.

| File | Cells × genes | `X` storage | `expm1(X)` row sums | Max difference from counts | Peak memory |
|---|---:|---|---|---:|---:|
| E6.75 | 7,093 × 498 | sparse CSC | 10,000 ± 0.01 | < 1e-6 | not recorded |
| E8.0 | 31,671 × 500 | sparse CSC | 10,000 ± 0.02 | < 1e-6 | 0.4 GB |
| E8.75 | 24,826 × 500 | sparse CSC | 10,000 ± 0.02 | 5.4e-7 | 0.3 GB |
| E9.5 | 53,742 × 500 | sparse CSC | 10,000 ± 0.02 | 5.4e-7 | 0.4 GB |
| E9.5 Mab21l2 knockout | 50,294 × 500 | dense float32 | 10,000 ± 0.01 | 5.7e-7 | 0.5 GB |

The E6.75 and E8.0 rows were measured on 3 October 2026, the others on 8 October. A difference below 1e-6 is float32 rounding, so `X` is exactly CP10k over the panel. E6.75 has 498 genes because `Casp4` and `Pnliprp1` were not measured at that stage.

The wild-type files carry `counts` and `log1p` layers and `spatial_2D` / `spatial_3D` coordinates. The Mab21l2 knockout file is laid out differently: `X` is dense rather than sparse, there is an extra `normalized_counts` layer, and the coordinates are in `obsm['spatial']` and `obsm['spatial_3D']` alongside PCA, Harmony and UMAP embeddings. Its observation names are not unique.

## Task 1

The Task 1 files have no `counts` layer. Their integer counts can still be recovered: in each cell, dividing every `expm1(X)` value by the cell's smallest nonzero value gives integers. Doing this on the released E9.5 RNA file (17,057 cells) on 3 October 2026 recovered integer counts for every cell, and each cell's counts summed to its implied library size to within 0.003. That is what CP10k over all 32,285 genes predicts.
