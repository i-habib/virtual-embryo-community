# Virtual Embryo Ensemble Lab

What does it mean to ensemble two predictions when the output is an **unordered population of cells**, sometimes with a 3-D point cloud attached?

This repo tests several composition operations against the official public `veckit` scorer. Each experiment creates two predictions that are good at different things, combines them, and measures which properties survive.

The examples use the organizers' public mini targets. They are controlled scorer experiments, not hidden-board estimates.

## What the current run shows

The composition methods can recover complementary properties that neither input has on its own.

- **T1 mean graft:** one input has the correct pseudobulk mean but a collapsed population; the other has the target centered population structure but a wrong mean. The graft reaches `MMD = -0.00813`, variance ratio `1`, composition JSD `0`, and pseudobulk Pearson `1`.
- **T1 quantile graft:** one input has the target gene marginals with genes independently shuffled across cells; the other preserves within-gene ranks but distorts the marginals. The graft reconstructs the public target expression matrix exactly in this control.
- **T2 spatial transplant:** one input has exact target expression attached to the wrong positions; the other has coherent target geometry with shifted expression. The transplant keeps exact target expression while reaching sliced Wasserstein `0`, occupancy Dice `1`, and neighborhood MMD `-0.00793`.
- **T3 mean graft:** one input has the right KO mean but collapsed cells; the other has the KO centered population structure with a shifted response mean. The graft restores the response while reaching `MMD = -0.00804`, variance ratio `1`, and composition JSD `0`.

Full scorer tables and reconstruction diagnostics are in **[RESULTS.md](RESULTS.md)**.

## Experiments

### Mean / response graft

One prediction supplies the per-gene mean. The other supplies centered cell-to-cell structure.

\[
X_{\text{blend}}=(X_B-\mu_B)+\mu_A
\]

The lab tests this on T1 developmental prediction and T3 perturbation response.

### Quantile graft

One prediction has the right per-gene marginals with gene-gene structure scrambled. Another has the right within-gene cell ranks with distorted marginals.

The graft assigns the first model's observed values according to the second model's ranks. With equal cell counts, it preserves the donor's empirical marginal for every gene exactly.

### Spatial transplant

For T2, one prediction gets expression right while attaching coordinates to the wrong cells. A second keeps a coherent point-cloud/expression pairing but has shifted expression.

The blender matches cells one-to-one in centered expression space, keeps the first prediction's expression rows, and copies matched coordinates from the second.

### Population mixture

The lab also sweeps simple cell-level mixtures between complementary T1 predictions. This is the direct population ensemble: sample complete cells from A and B.

## Reproduce everything

```bash
git clone https://github.com/i-habib/virtual-embryo-ensemble-lab
cd virtual-embryo-ensemble-lab
pip install -r requirements.txt
python run_lab.py --out-dir results
```

`run_lab.py` downloads six public `.h5ad` examples from the pinned `veckit` revision, constructs every controlled pair, runs the scorer, and rewrites the result tables.

Pinned scorer:

```text
aristoteleo/veckit@46d41e63f42a9aab815db20b742feeccd249cb17
```

The composition code is pinned to a tested revision of [Virtual Embryo Submission Blender](https://github.com/i-habib/virtual-embryo-submission-blender).

Raw CSVs and diagnostics are in [`results/`](results/).

## Why this is separate from the blender

The [Submission Blender](https://github.com/i-habib/virtual-embryo-submission-blender) is the reusable CLI/library. Ensemble Lab is the executable evidence for what its composition operations preserve under the public VEC metrics.

Independent community resource for the Virtual Embryo Challenge. The official rules and scorer remain authoritative.
