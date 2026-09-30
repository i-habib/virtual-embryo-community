# Virtual Embryo Ensemble Lab

What does it mean to ensemble two predictions when the output is an **unordered population of cells**, sometimes with a 3-D point cloud attached?

This repo tests several composition operations against the official public `veckit` scorer. Each experiment creates two predictions that are good at different things, combines them, and measures which properties survive.

The examples use the organizers' public mini targets on purpose. They are controlled scorer experiments, not hidden-board estimates.

## Experiments

### Mean / response graft

One prediction supplies the per-gene mean. The other supplies centered cell-to-cell structure.

\[
X_{\text{blend}}=(X_B-\mu_B)+\mu_A
\]

The lab tests this on T1 developmental prediction and T3 perturbation response.

### Quantile graft

One prediction has the right per-gene marginals with gene-gene structure scrambled. Another has the right within-gene cell ranks with distorted marginals.

The graft assigns the first model's observed values according to the second model's ranks.

With equal cell counts this preserves the donor's empirical marginal for every gene exactly.

### Spatial transplant

For T2, one prediction gets expression right while attaching coordinates to the wrong cells. A second keeps a coherent point cloud/expression pairing but has shifted expression.

The blender matches cells one-to-one in centered expression space, keeps the first prediction's expression rows, and copies matched coordinates from the second.

### Population mixture

The lab also sweeps simple cell-level mixtures between complementary T1 predictions. This gives a baseline for the most direct ensemble: sampling whole cells from A and B.

## Results

See **[RESULTS.md](RESULTS.md)** for scorer tables and preservation diagnostics generated from the current pinned run.

Raw CSVs and diagnostics are in [`results/`](results/).

## Reproduce everything

```bash
git clone https://github.com/i-habib/virtual-embryo-ensemble-lab
cd virtual-embryo-ensemble-lab
pip install -r requirements.txt
python run_lab.py --out-dir results
```

`run_lab.py` downloads six tiny public `.h5ad` examples directly from the pinned `veckit` revision, constructs every controlled pair, runs the public scorer, and rewrites the result tables.

Pinned scorer:

```text
aristoteleo/veckit@46d41e63f42a9aab815db20b742feeccd249cb17
```

The composition code is pinned to a tested revision of [Virtual Embryo Submission Blender](https://github.com/i-habib/virtual-embryo-submission-blender).

## Why keep this separate from the blender?

The blender is the reusable tool. This repo answers a different question: **what does each blend operation actually preserve under VEC-style metrics?**

The controlled pairs make the guarantees visible:

- pseudobulk mean versus centered population structure
- gene marginals versus cross-gene/rank organization
- expression versus spatial assignment
- direct population interpolation versus factor grafting

Independent community resource for the Virtual Embryo Challenge. The official rules and scorer remain authoritative.
