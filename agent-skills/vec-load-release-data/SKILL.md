---
name: vec-load-release-data
description: Loads Virtual Embryo release .h5ad files without exhausting memory on an 8 GB machine, handles the CSC sparse and dense Mab21l2 knockout layouts, recovers integer counts from Task 1 files, and normalises external counts onto the release scale. Use whenever a released or external AnnData file is opened, sliced, counted or normalised.
---

# Load and normalise release data

Read the data page first: https://virtualembryo.ai/challenge/data. It lists the files and the panel gene lists. The normalisation of each released file is documented in [NORMALISATION.md](../../panel-normalise/NORMALISATION.md).

## Facts to check against before any computation

- Every released matrix stores natural log1p of counts per 10,000 (CP10k). The denominator differs by task.
- Task 1 (E8.5 and E9.5 RNA): CP10k over all 32,285 genes. The file has no `counts` layer.
- Tasks 2 and 3 (3D MERFISH): CP10k over the board panel only, about 500 genes. Wild-type files have `counts` and `log1p` layers and `spatial_2D` and `spatial_3D` coordinates.
- The Mab21l2 knockout at E9.5 (50,294 cells by 500 genes) has a dense float32 `X`, not sparse. It has an extra `normalized_counts` layer, its `obsm` holds `spatial`, `spatial_3D`, PCA, Harmony and UMAP, and its observation names are not unique.
- The machine is an 8 GB laptop. Run one heavy job at a time.

## Loading

1. Inspect the file without loading the matrix:

   ```python
   import anndata as ad
   a = ad.read_h5ad("release.h5ad", backed="r")
   print(a.shape, list(a.layers), list(a.obsm), a.X.__class__)
   a.file.close()
   ```

2. Read only the slice you need, for example `a[idx].to_memory()`. Do not call `to_memory()` on the whole file.
3. Sparse `X` for the MERFISH files is CSC. Column (gene) slices are cheap. For per-cell work, convert once with `X.tocsr()` and keep the result.
4. The Mab21l2 knockout's `X` is dense, about 100 MB. Index it with `np.asarray`, and do not convert it to sparse just to slice it.
5. Before indexing the knockout by observation name, run `a.obs_names_make_unique()`. Never write back to a release file. Save derived matrices to new paths.

## Recovering counts from Task 1

Task 1 files have no counts layer. The counts can be recovered from the normalised values, because dividing each cell's `expm1(X)` values by its smallest nonzero value gives integers.

```bash
python count-recovery/vec_counts.py recover release.h5ad --check-only --report check.json
python count-recovery/vec_counts.py recover release.h5ad counts.h5ad
```

Run the `--check-only` pass first. Recovered `.X` is int32 CSR with stored zeros removed. Cells that fail the integer test stop the run. The recovered counts are the ones the normalisation encodes, not counts corrected for ambient RNA.

## Normalising external counts

External data must be subset to the panel and then normalised. Normalising over all genes and selecting the panel afterwards gives values too low by about 2.3 in log1p (see the README in [panel-normalise](../../panel-normalise/README.md)).

```bash
python panel-normalise/vec_normalise.py resolve raw.h5ad --panel PANEL.genes.txt --report mapping.tsv
python panel-normalise/vec_normalise.py normalise raw.h5ad --panel PANEL.genes.txt --out panel.h5ad --report mapping.tsv
python panel-normalise/vec_normalise.py verify release.h5ad --panel PANEL.genes.txt
```

`verify` compares a file against its own `counts` layer, so use it on a release file that has one. Its output has no counts layer, so check it with the row sums instead (see below).

- For Task 1, use the Task 1 gene list with `--fill-missing zeros`.
- Input must be raw integer counts. The tool refuses matrices that look log-transformed.
- Gene names are matched exactly first, then by case-only symbol, Ensembl ID or MGI synonym. Read the mapping report. Conflicts and ambiguous names are refused.
- Pass `--mgi-dir DIR` to use local MGI tables, or leave it out to download them.

Panel gene lists come from https://virtualembryo.ai/challenge/panels/. That host answers 403 to the default User-Agent, so fetch with `curl -A "Mozilla/5.0"`.

## Before using the output

- For normalised output, the row sums of `expm1(X)` over the panel genes should lie between 9,999.99 and 10,000.01, which is the range the tool's own outputs meet. Check every row, not one cell.
- Check that the external source passed [vec-external-data-guard](../vec-external-data-guard/SKILL.md) first. Loading a file is already a use.
