# Virtual Embryo external-data catalog

A short list of outside datasets I would actually consider using for the Virtual Embryo Challenge, with preprocessing code and a record of what happened when I tried the real releases.

I started with a broader list. That was not very useful. The current version separates sources I have run end-to-end from sources that only look promising on paper, and keeps failed access attempts visible instead of quietly dropping them.

Rules snapshot: **2026-09-17**. The [official challenge rules](https://virtualembryo.ai/challenge/rules) override anything here.

## Current state

| Source | Release checked | What happened | VEC heart-panel overlap | Spatial data | Status |
|---|---|---|---:|---|---|
| **GSE282547 developing heart** | GSM8645799, E14.5 Visium, CD1 WT | processor passed on 456 spots × 32,285 genes | **500 / 500** | real 2-D coordinates | **recommended / validated** |
| **GSE247450 MERFISH** | GSM7890128, E9.5 WT region 0 | processor passed on 1,077 cells × 315 genes | **68 / 500** | x/y only | **validated, narrow panel** |
| **Mouse GO** | current `MOUSE-mod.gaf.gz` | processor passed; 1,111 edges for Gata4/Ctnnb1/Mab21l2 probe | n/a | n/a | **recommended / validated** |
| **sc3D E9.0** | official Figshare h5ad discovered | object is 12.19 GB; not run in hosted validation | not measured | intended 3-D reconstruction | **candidate** |
| **Extended Mouse Atlas** | official download index inspected | release is a 25 GB archive; not run in hosted validation | not measured | no | **candidate** |
| **Tabula Muris** | old and current processed-data routes tried | both failed from the hosted validator | not measured | no | **demoted** |

The manifests in [`validation/`](validation/) contain the exact URLs, hashes, commands, observed schemas, counts, overlaps, and failures. For the spatial expression sources, overlap is measured against the 500-gene panel read directly from the pinned public `veckit` heart example.

## The three sources I would start with

### GSE282547: developing mouse heart

[GEO](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE282547)

This is the strongest expression/spatial source I found after checking the releases rather than just the paper descriptions. The validated **GSM8645799 E14.5 Visium CD1 WT** sample has:

- 456 spots
- 32,285 genes
- all **500/500** genes in the public VEC heart panel
- genuine 2-D tissue coordinates

The adapter stores those coordinates as `obsm['spatial_2D']`. It does not add a fake z coordinate to make the object resemble a Task 2 submission.

```bash
python processors/process_gse282547_visium.py raw/GSM8645799 \
  --stage 14.5 \
  --task t2-heart \
  --gene-list vec_heart_500.txt \
  --out processed/GSM8645799.E14.5.h5ad
```

This is useful as later-stage, heart-specific expression/spatial data. It is still a 2-D section, so turning it into a 3-D developmental prior is a modeling problem, not a preprocessing trick.

Manifest: [`validation/gse282547_e14_5_visium.json`](validation/gse282547_e14_5_visium.json)

### GSE247450: embryonic endothelial MERFISH

[GEO](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE247450)

The assay is close to the challenge's spatial data, but the real release is much narrower than I expected from the headline. For **GSM7890128 E9.5 region 0**, the matrix has 315 genes and only **68/500** overlap the public VEC heart panel. The metadata has `center_x` and `center_y`, but no genuine z coordinate.

I would use it as a same-modality/endothelial prior, not as a drop-in Task 2 training set.

```bash
python processors/process_gse247450.py raw/GSE247450 \
  --task t2-heart \
  --gene-list vec_heart_500.txt \
  --out-dir processed/gse247450
```

Manifest: [`validation/gse247450_e9_5_region0.json`](validation/gse247450_e9_5_region0.json)

### Mouse Gene Ontology

[Current mouse GAF](https://current.geneontology.org/annotations/gaf/MOUSE-mod.gaf.gz)

Task 3 has very little supervision over perturbation identity. GO gives gene-function structure without adding another embryo measurement. The validated run hashed the current GAF and found **1,111 gene-GO edges** across the Gata4/Ctnnb1/Mab21l2 probe.

```bash
python processors/prepare_mouse_go.py MOUSE-mod.gaf.gz \
  --gene-list vec_500_genes.txt \
  --exclude-iea \
  --out processed/mouse_go_vec500.csv
```

The processor keeps evidence codes. Whether to exclude IEA annotations is left to the modeler.

Manifest: [`validation/mouse_go.json`](validation/mouse_go.json)

## Promising, but not real-release validated here

### Extended Mouse Atlas

[Project page](https://marionilab.github.io/ExtendedMouseAtlas/)

Scientifically, this is a strong fit: 430,339 cells across 13 time points from E6.5 through E9.5. Practically, the official package is a **25 GB archive**. The adapter has synthetic end-to-end tests, but I have not run it against that full release.

Manifest: [`validation/extended_mouse_atlas.json`](validation/extended_mouse_atlas.json)

### sc3D / GSE197353

[GEO](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE197353)

The convenient reconstructed E9.0 h5ad on Figshare is **12,187,200,243 bytes**. The validator records the exact object instead of pretending that a compile test proves the processor works on it. I still think the source is interesting for 3-D priors, but it needs a real run on a machine with enough disk/RAM before I would call the adapter validated.

Manifest: [`validation/sc3d_e9_0.json`](validation/sc3d_e9_0.json)

## Demoted: Tabula Muris

I originally kept Tabula Muris as a broad adult-tissue prior. In practice it is developmentally distant, and both processed-data routes I tried failed from GitHub Actions:

- legacy `czbiohub-tabula-muris`: 403
- current Open Data Registry object: `HeadObject 403 Forbidden`

Once the E14.5 developing-heart data worked, there was little reason to spend more time rescuing this entry. The old processor remains for people who already have the files, but `audit_catalog.py` hides it by default.

Manifest: [`validation/tabula_muris.json`](validation/tabula_muris.json)

## What the processors are conservative about

- Ambiguous stage strings and stage ranges are rejected rather than reduced to the first number found.
- Somite/Theiler stages need source-specific handling.
- T1/T2 filtering uses explicit open/closed stage windows.
- A Task 3 processor cannot certify genotype safety from stage alone; provenance records `T3_GENOTYPE_NOT_AUDITED` where appropriate.
- x/y coordinates stay 2-D. `spatial_3D` is only created when a real 3-D field has been validated.

These checks reduce easy mistakes. They do not replace the challenge rules or organizer judgment.

## Validation

There are two layers.

**Synthetic CI** runs small end-to-end fixtures through every processor with the real runtime dependencies. This catches parser, filtering, AnnData/schema, coordinate, and provenance regressions.

```bash
pytest -q tests
```

**Real-source validation** downloads specific public releases where practical, runs the corresponding processor, and writes a manifest. [`scripts/add_vec_panel_overlap.py`](scripts/add_vec_panel_overlap.py) separately measures overlap with the pinned public VEC heart panel.

A failed source stays failed in the repository. The workflow preserves the evidence it gathered and then exits nonzero instead of turning the problem into a missing log.

## Source terms

[`SOURCE_TERMS.md`](SOURCE_TERMS.md) records what I could establish from the upstream sources. In brief: GEO being public is not treated as a blanket CC0/CC-BY grant, Gene Ontology data products are CC BY 4.0, and sources without a clear dataset-specific redistribution licence are linked rather than vendored.

## Machine-readable catalog

[`catalog.json`](catalog.json) stores the evidence tier, manifest path, task notes, processor, and source-term notes for each entry.

```bash
python audit_catalog.py --task t2-heart
python audit_catalog.py --task t2-heart --include-demoted
```

This is intentionally a short catalog. A source marked **validated** means the advertised processor was run on the named release and the evidence was committed. It does not mean the source will improve a model or that every file in the study is challenge-eligible.
