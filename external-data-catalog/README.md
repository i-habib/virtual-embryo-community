# Virtual Embryo external-data catalog

A curated set of public resources that look genuinely useful for the Virtual Embryo Challenge, together with the scripts needed to turn each source into something usable.

The catalog is intentionally small. A list of fifty vaguely related atlases would save nobody time. Each entry here has:

- a reason you might actually use it
- stage/modality notes that matter for VEC
- a task-aware processor
- provenance output
- an explicit caveat about what the adapter does **not** establish

The challenge rules are still the authority. This package only automates the mechanical parts.

Rules snapshot: **2026-09-16**. Re-check the [official rules](https://virtualembryo.ai/challenge/rules) before a final submission.

## Current catalog

| Resource | What it adds | Main caveat | Adapter |
|---|---|---|---|
| Extended Mouse Atlas | dense E6.5–E9.5 whole-embryo scRNA time course | task-specific stage filtering for T2 | `process_extended_mouse_atlas.py` |
| sc3D / GSE197353 | genome-wide spatial embryo maps; 3D reconstructions at E8.5/E9.0 | E8.5 is protected for T2-heart; E9.5 material is partial 2D, not a 3D reconstruction | `process_sc3d.py` |
| GSE247450 MERFISH | WT E9.5/E15.5 MERFISH; useful same-modality prior | 300 genes, not VEC's 500-gene panel | `process_gse247450.py` |
| Tabula Muris | adult tissue/cell-state expression prior | developmentally far from the challenge | `process_tabula_muris.py` |
| Mouse GO annotations | functional gene prior for perturbation conditioning | annotations, not measured embryo expression | `prepare_mouse_go.py` |

Machine-readable metadata is in [`catalog.json`](catalog.json). To see the entries and their task notes:

```bash
python audit_catalog.py --task t2-heart
```

## What every cell-data adapter tries to do

1. Read the upstream file without silently changing stage labels.
2. Parse embryonic stage explicitly.
3. Remove cells/files that fall inside the selected task's mechanically protected stage window.
4. Optionally intersect genes with a panel you supply.
5. Put 3D coordinates in `obsm['spatial_3D']` when the source actually provides them.
6. Write a `*.provenance.json` sidecar with the source, task, filtering, stage information, cell counts, and gene overlap.

A clean output file is **not** an eligibility ruling. Genotype-specific questions, phenocopies, comparable alleles, licenses, and scientific usefulness still need human review.

## 1. Extended Mouse Atlas

Source: <https://marionilab.github.io/ExtendedMouseAtlas/>

The combined atlas contains **430,339 cells across 13 time points from E6.5 to E9.5**. The public `embryo_complete.h5ad` contains log-normalized UMI counts, raw counts in `.raw`, metadata, and precomputed layouts.

This is the strongest general-purpose expression/developmental prior in the current catalog.

```bash
python processors/process_extended_mouse_atlas.py \
  embryo_complete.h5ad \
  --task t1 \
  --out processed/extended_mouse_atlas.t1.h5ad
```

For T2-heart, the processor removes cells strictly inside `(E8.25, E8.75)` before writing the result. For T2-embryo it removes cells strictly inside `(E7.25, E8.0)`.

If you explicitly want to rebuild normalized values from `adata.raw`, use `--use-raw-counts`; otherwise the processor preserves the released expression representation.

## 2. sc3D / GSE197353

GEO: <https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE197353>

Paper/data availability: <https://pmc.ncbi.nlm.nih.gov/articles/PMC10335937/>

The study profiled complete E8.5 and E9.0 embryos plus partial E9.5 material with Slide-seq. The paper distributes **3D visualization h5ad objects for E8.5 and E9.0**. The partial E9.5 sections are useful spatial data, but they should not be described as another whole-embryo 3D reconstruction.

For T2-heart, E8.5 falls inside the protected interpolation window. E9.0 and the E9.5 boundary are outside that window.

```bash
python processors/process_sc3d.py \
  E8_5_Embryo2.h5ad E9_0_Embryo.h5ad \
  --task t2-heart \
  --gene-list vec_500_genes.txt \
  --out-dir processed/sc3d
```

The adapter infers the stage from the filename, skips protected files for the selected task, intersects the supplied gene panel, and standardizes 3D coordinates when present.

Useful direct 3D objects cited by the paper:

- E8.5 Embryo 2: <https://figshare.com/articles/dataset/E8_5_Embryo2_h5ad/21695849/1>
- E9.0: <https://figshare.com/articles/dataset/E9_0_Embryo_h5ad/21695879/1>

## 3. GSE247450 MERFISH

Source: <https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE247450>

The public series contains **two E9.5 WT sagittal regions and one E15.5 WT region**, measured on Vizgen MERSCOPE with a 300-gene panel. GEO distributes per-sample cell-by-gene and cell-metadata CSVs.

```bash
python processors/process_gse247450.py raw/GSE247450 \
  --task t2-heart \
  --gene-list vec_500_genes.txt \
  --out-dir processed/gse247450
```

The adapter pairs each matrix with the matching metadata file, detects orientation from cell IDs, preserves the shared genes in requested order, and copies coordinates into `spatial_3D` when the metadata exposes a recognizable 3D coordinate triplet.

Do not assume every MERFISH export has a meaningful z coordinate. The processor reports whether it found a 3D spatial field instead of inventing one.

## 4. Tabula Muris

Data instructions: <https://github.com/czbiohub-sf/tabula-muris-vignettes/blob/master/data/README.md>

Tabula Muris is adult data from roughly 100,000 cells across 20 organs/tissues. It is not a developmental substitute for the embryo atlases above. Its plausible use is as a broad tissue/cell-state expression prior.

The project publishes Python-ready h5ad matrices and matching metadata files.

```bash
python processors/process_tabula_muris.py TM_droplet_mat.h5ad \
  --metadata TM_droplet_metadata.csv \
  --tissue heart \
  --gene-list vec_500_genes.txt \
  --normalize \
  --out processed/tabula_muris_heart.h5ad
```

Only pass `--normalize` when you are starting from counts. The flag applies library-size normalization followed by `log1p`.

## 5. Mouse Gene Ontology annotations

MGI download page: <https://www.informatics.jax.org/downloads/reports/index.html>

Current mouse GAF: <https://current.geneontology.org/annotations/gaf/MOUSE-mod.gaf.gz>

This is a different kind of external resource. It gives gene-function edges rather than another embryo measurement, which can be useful when representing the identity of a Task 3 perturbation.

```bash
python processors/prepare_mouse_go.py MOUSE-mod.gaf.gz \
  --gene-list vec_500_genes.txt \
  --exclude-iea \
  --out processed/mouse_go_vec500.csv
```

The output is a gene–GO edge table with evidence codes and references. Keep the evidence codes; whether to include IEA annotations is a modeling choice, not a preprocessing fact.

## Gene panels

Pass a text file containing one gene symbol per line with `--gene-list`. The adapters preserve the requested order for genes that are actually present and report missing genes in provenance.

The catalog does not vendor VEC gene lists so that the preprocessing code is not silently tied to an old panel revision.

## Provenance

Every cell-data adapter writes `*.provenance.json` beside its h5ad output. Keep that sidecar with the processed file.

At minimum it records:

- upstream source/input
- selected VEC task
- stage field and parsed stages when applicable
- protected stages/files removed
- cells before/after
- requested/present/missing genes
- rules snapshot used by the adapter

That information is much easier to capture during preprocessing than reconstruct at submission time.

## Tests

```bash
pytest -q tests
```

The tests stay small: no multi-GB atlas downloads. They cover stage parsing, exact open/closed boundary behavior, filename staging, panel intersection helpers, and GSE247450 file pairing. Source-specific end-to-end commands should still be smoke-tested on the exact release you plan to use.

## Scope

This is a curated starting point, not an exhaustive external-data directory. An entry being present means “worth inspecting,” not “guaranteed to improve your model” or “organizer-approved.”
