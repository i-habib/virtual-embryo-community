# Virtual Embryo external-data catalog

A small catalog of public resources that are actually relevant to the Virtual Embryo Challenge, with **task-aware preprocessing scripts** for each one.

This is separate from the [Data Safety Kit](../data-safety/). The safety kit answers:

> Is this stage / genotype obviously allowed, excluded, or ambiguous under the published rules?

This catalog answers the more practical follow-up:

> Which external resources are worth looking at, and how do I turn them into a clean file without accidentally carrying protected stages into training?

The challenge explicitly allows public external data, pretrained models, and published code when licences permit and the source is disclosed. It also says that cells inside protected stage/genotype windows must be removed from a broader resource before training. That makes preprocessing part of eligibility, not just convenience.

Rules snapshot used here: **2026-09-16**. Re-check the [official rules](https://virtualembryo.ai/challenge/rules) before a final submission.

## What is in the first release

| Resource | Why it is useful | Main caveat | Processor |
|---|---|---|---|
| Extended Mouse Atlas, E6.5–E9.5 | dense developmental scRNA time course; strong T1 prior | protected interpolation stages must be filtered for T2 | `process_extended_mouse_atlas.py` |
| sc3D / GSE197353 | whole-embryo spatial transcriptomics and 3D reconstructions | E8.5 is protected for T2-heart | `process_sc3d.py` |
| GSE247450 MERFISH | same broad modality family as T2/T3; E9.5 and E15.5 WT | 300-gene panel, not the VEC 500-gene panel | `process_gse247450.py` |
| Tabula Muris | adult mouse cell-state / tissue priors | developmentally distant from the challenge | `process_tabula_muris.py` |
| Mouse GO annotations | non-measured gene-function prior, especially useful for T3 | not expression data; use as gene features, not a cell atlas | `prepare_mouse_go.py` |

The machine-readable details live in [`catalog.json`](catalog.json). You can inspect one task at a time:

```bash
python audit_catalog.py --task t2-heart
```

## The preprocessing contract

The cell-data processors follow the same pattern:

1. read the upstream file without silently relabeling stages;
2. turn stage labels into numeric embryonic days;
3. remove any cells/files in the protected window for the task you selected;
4. optionally intersect genes with a VEC panel you supply;
5. standardize 3D coordinates to `obsm['spatial_3D']` when the source has them;
6. write a sidecar `*.provenance.json` recording what went in, what was removed, and what came out.

The processors **do not** claim that a dataset is scientifically useful just because it passes the stage rule. They also do not make biological judgments about comparable mutant alleles or phenocopies. Those still require organizer clarification.

## 1. Extended Mouse Atlas

Source: <https://marionilab.github.io/ExtendedMouseAtlas/>

The atlas contains 430,339 cells across E6.5–E9.5. That makes it unusually useful for T1, because all of those stages are at or before the released E9.5 boundary. For Task 2 it needs filtering:

- embryo setting: remove stages strictly between E7.25 and E8.0;
- heart setting: remove stages strictly between E8.25 and E8.75.

After downloading/extracting `embryo_complete.h5ad`:

```bash
python processors/process_extended_mouse_atlas.py \
  embryo_complete.h5ad \
  --task t1 \
  --out processed/extended_mouse_atlas.t1.h5ad
```

For a T2-heart expression prior:

```bash
python processors/process_extended_mouse_atlas.py \
  embryo_complete.h5ad \
  --task t2-heart \
  --gene-list vec_500_genes.txt \
  --out processed/extended_mouse_atlas.t2-heart.h5ad
```

The processor records the exact stages removed in the provenance sidecar.

## 2. sc3D / GSE197353

Source: <https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE197353>

The study provides whole E8.5 and E9.0 spatial embryos plus partial E9.5 material. Processed 3D h5ad objects are linked from the paper/figshare.

For T2-heart, **do not mix the E8.5 object into training**. E8.5 is the held-out interpolation stage. E9.0 and E9.5 are outside that interpolation window.

```bash
python processors/process_sc3d.py \
  E8_5_Embryo2.h5ad E9_0_Embryo.h5ad \
  --task t2-heart \
  --gene-list vec_500_genes.txt \
  --out-dir processed/sc3d
```

The command will skip the E8.5 file for T2-heart rather than trusting you to remember.

## 3. GSE247450 embryonic endothelial MERFISH

Source: <https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE247450>

The public GEO series contains two E9.5 WT sagittal regions and one E15.5 WT region, measured with a 300-gene MERFISH panel. E9.5 is permitted and E15.5 is beyond the E13.5 extrapolation protection window.

Download/extract `GSE247450_RAW.tar`, then:

```bash
python processors/process_gse247450.py raw/GSE247450 \
  --task t2-heart \
  --gene-list vec_500_genes.txt \
  --out-dir processed/gse247450
```

The adapter pairs each `*_cell_by_gene.csv.gz` file with its metadata file, detects matrix orientation using cell IDs, standardizes coordinates when it can find them, and preserves only genes shared with the supplied panel.

## 4. Tabula Muris

Source/loading instructions: <https://github.com/czbiohub-sf/tabula-muris-vignettes/blob/master/data/README.md>

This is adult data, so it is outside the embryonic protected windows. Its value is mostly as an expression/cell-state prior rather than as a direct developmental target.

For example, keep only heart cells and the genes you care about:

```bash
python processors/process_tabula_muris.py TM_droplet_mat.h5ad \
  --metadata TM_droplet_metadata.csv \
  --tissue heart \
  --gene-list vec_500_genes.txt \
  --normalize \
  --out processed/tabula_muris_heart.h5ad
```

Do not treat “allowed” as “automatically useful.” Adult heart is much farther from the challenge regime than E9-stage developmental data.

## 5. Mouse Gene Ontology annotations

MGI lists the current mouse GAF here: <https://www.informatics.jax.org/downloads/reports/index.html>

GO annotations are useful for Task 3 because they give each perturbation gene a structured functional prior without using measured expression from a held-out embryo.

```bash
python processors/prepare_mouse_go.py MOUSE-mod.gaf.gz \
  --gene-list vec_500_genes.txt \
  --exclude-iea \
  --out processed/mouse_go_vec500.csv
```

The output is a simple gene–GO edge table with evidence codes and references, ready to turn into bag-of-terms features or embeddings.

## Gene panels

The repository does **not** copy challenge gene lists into this package. Pass your own text file, one gene symbol per line, via `--gene-list`. This keeps the processors useful even if the challenge panel changes.

## Provenance

Every cell-data adapter writes a `*.provenance.json` next to the h5ad output. Keep it. It records the source, selected task, filtering, stage(s), cell counts, gene overlap, and the rules snapshot used by the adapter.

That sidecar is intentionally boring: the challenge asks teams to disclose external sources, versions/stages, and how the material entered the method. Recording those facts during preprocessing is much easier than reconstructing them at the deadline.

## Tests

The small unit tests do not download the large atlases. They cover stage parsing, exact boundary behavior, file-name staging, and GSE247450 file pairing:

```bash
pytest -q external-data-catalog/tests
```

The source-specific scripts use lazy `anndata` imports, so the rule/parsing tests run even before the heavier scientific stack is installed.

## Scope

This is a curated starting point, not an exhaustive atlas directory and not an official eligibility ruling. The official rules and written organizer answers override this catalog.
