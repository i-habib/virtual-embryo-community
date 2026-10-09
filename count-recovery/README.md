# Recover integer counts from the T1 RNA files

Many single-cell tools expect integer UMI counts. scVI and scANVI fit a negative-binomial likelihood to counts, scanpy's `seurat_v3` method selects highly variable genes from counts, pseudobulk differential expression with DESeq2 or edgeR works on summed counts, and Poisson resampling starts from counts. The T1 release (the E8.5 and E9.5 RNA files) stores only normalized log values in `.X` and has no counts layer. This tool inverts the normalization for each cell and checks that the result is made of integers.

## Terms

- **UMI count**: the number of unique molecular identifiers, short barcodes that tag individual mRNA molecules, detected for one gene in one cell. It is a whole number.
- **Library size**: the total UMI count of one cell, summed over all genes. Written L below.
- **CP10k**: counts per 10,000. Each count is divided by the cell's library size and multiplied by 10,000.
- **Natural log1p**: log(1 + x), with the natural logarithm. Its inverse is expm1(y) = exp(y) - 1.
- **AnnData and h5ad**: AnnData is the Python container for single-cell data, and h5ad is its HDF5 file format. `.X` holds the expression matrix, `.obs` holds one row of metadata per cell, and `.var` holds one row per gene.
- **CSR and CSC**: two ways to store a sparse matrix, which is mostly zeros. CSR stores rows contiguously and CSC stores columns contiguously.

## Method

For cell i and gene j, the file stores x_ij = log(1 + 1e4 c_ij / L_i), where c_ij is the count and L_i the library size.

1. expm1(x_ij) = 1e4 c_ij / L_i.
2. Dividing by the cell's smallest nonzero value gives c_ij / c_min, where c_min is the count of the cell's least-expressed detected gene.
3. Assuming c_min = 1 gives c_ij, and then L_i = sum over j of c_ij. If that assumption does not make every value an integer, the tool tries c_min = 2 up to 5. Integrality is the check.

A value s counts as an integer when its distance to the nearest integer is at most tol times max(1, s). The default tol is 1.9e-6, which is 16 float32 machine epsilons and covers the rounding that float32 storage adds. Each cell also needs its counts to sum to L_i within relative 1e-5. That check confirms the normalization total equals the sum over the stored genes.

A normalized matrix cannot tell apart two count vectors that differ only by a shared integer factor. Cells that needed c_min above 1 are therefore recorded in `obs['recovery_smallest_count']` and counted in the report.

To convert recovered counts back to the release representation, divide each cell by its total, multiply by 10,000, and apply natural log1p.

## Commands

Install the dependencies:

```sh
pip install numpy scipy h5py anndata
```

Check a file without writing a matrix:

```sh
python vec_counts.py recover input.h5ad --check-only --report check.json
```

Recover the counts:

```sh
python vec_counts.py recover input.h5ad counts.h5ad
```

Compare recovered counts with the original log1p matrix:

```sh
python vec_counts.py roundtrip counts.h5ad input.h5ad
```

Run the tests from this directory:

```sh
python -m pytest -q
```

The recovered `.X` is int32 CSR with stored zeros removed. `obs` gains `library_size`, `recovery_max_residual` (the largest normalized distance to an integer in the cell), and `recovery_smallest_count` (0 for all-zero cells). `uns['vec_counts']` records the input file name, its SHA-256 hash, the tolerance, and the tool version. Existing output files and existing `obs` columns are not overwritten unless `--force` is given. NaN or Inf values, negative values, cells that fail integer recovery, and CP10k check failures stop the run with a message and a nonzero exit status before any matrix is written.

## Measured results

Machine: 8 GB Apple M1 laptop. Versions: anndata 0.13.4, numpy 2.5.3, scipy 1.18.1.

Released E9.5 RNA file, `--check-only` with the default tolerance (8 October 2026):

| Cells | Genes | Cells recovered | Worst normalized residual | Cells needing smallest count > 1 | Max abs(sum(counts) - L) | Library size min / median / max | Runtime | Peak memory |
|---:|---:|---:|---:|---:|---:|---|---:|---:|
| 17,057 | 32,285 | 17,057 | 3.4e-7 | 0 | 0.003 | 731 / 11,080 / 94,591 | 39 s | 1.0 GB |

The worst residual is about one sixth of the default tolerance. The file stores 6,054,489 explicit zeros, which the recovered matrix drops. Every cell's counts sum to its library size to within a relative 1.1e-7, so the release normalized over all 32,285 genes.

The released E8.5 RNA file (16,787 cells) was checked on 3 October 2026 with an earlier version of the same method: every cell recovered to integers, with library sizes from 1,299 to 63,850. Writing its recovered matrix took 25 s and produced a 147 MB file. Converting those counts back with CP10k over all genes and natural log1p reproduced the original values to within 2.4e-7, which is float32 rounding.

## Limits

The tool assumes that `.X` holds natural log1p of CP10k values over all stored genes, with no other transformation. It recovers the counts that the normalization encodes, not counts corrected for ambient RNA or other quality control. The CP10k check confirms that the normalization total equals the sum over the stored genes. It cannot detect a matrix normalized over a subset of genes and then stored with only that subset, because the stored genes then sum to the total. The T1 files store all 32,285 genes, so for them the check confirms normalization over the full gene set. At the default tolerance, counts above about 260,000 cannot be checked, because rounding would become ambiguous.
