# Virtual Embryo Submission Blender

Two good Virtual Embryo submissions can fail in different ways. One may get the developmental shift right but collapse the cell population. Another may produce a good T2 point cloud while putting weaker expression on it.

`vec-blend` composes the **prediction files themselves**. It never consumes leaderboard scores or hidden-target feedback.

## Four ways to combine submissions

### Population mixture

Sample complete cells from both submissions.

```bash
vec-blend blend A.h5ad B.h5ad \
  --method mixture --alpha 0.4 \
  -o mixed.h5ad
```

Expression and coordinates stay paired within every sampled cell. `alpha=0.4` means roughly 40% of the output cells come from A.

This is the most literal ensemble for an unordered population.

### Mean graft

Use A's per-gene mean with B's centered cell-to-cell structure.

\[
X_{\text{out}} = (X_B-\mu_B)+\mu_A
\]

```bash
vec-blend blend A.h5ad B.h5ad \
  --method mean-graft \
  -o grafted.h5ad
```

Before clipping, the output pseudobulk mean equals A's exactly and B's centered residual matrix is unchanged. For T3 this also composes a pseudobulk perturbation response with another prediction's cell-level structure.

A large shift can create negative expression values. `veckit` rejects negative `prediction.X`, so the CLI refuses to write an unclipped negative mean graft. Re-run with `--clip-min 0` to make the file scorer-valid; clipping gives up the exact-mean guarantee. The Python API still returns the raw graft and reports its negative fraction for analysis.

### Quantile graft

Use A's per-gene empirical distributions while preserving B's within-gene cell ranks.

```bash
vec-blend blend A.h5ad B.h5ad \
  --method quantile-graft \
  -o quantile_graft.h5ad
```

With equal cell counts, every output gene has exactly the same multiset of values as A. Which cells receive the high and low values follows B.

### Spatial transplant

Keep A's expression cells and place them into B's spatial slots by one-to-one matching in centered expression space.

```bash
vec-blend blend expression_model.h5ad geometry_model.h5ad \
  --method spatial-transplant \
  -o transplanted.h5ad
```

The matcher removes each submission's per-gene mean, builds a joint PCA embedding, then assigns A cells to B cells. Small problems use the exact Hungarian assignment. Larger problems switch to a unique greedy nearest-neighbor match.

The output contains A's expression rows and coordinates copied from the matched B cells.

## A fixed mixture sweep

Generate several candidates without writing a loop:

```bash
vec-blend sweep A.h5ad B.h5ad \
  --alphas 0,0.25,0.5,0.75,1 \
  --out-dir blends/
```

Each output gets a `.blend.json` sidecar with the method and parameters used.

## Input checks

The tool fails when:

- the two files do not contain the same gene set
- gene names are duplicated
- expression or spatial arrays contain non-finite values
- only one input has `spatial_3D` for a population mixture
- a spatial transplant has no 3-D geometry carrier
- an unclipped mean graft would contain negative expression values

Gene order can differ; B is reordered to A automatically.

## What each method preserves

| Method | Comes from A | Comes from B |
|---|---|---|
| population mixture | sampled whole cells | sampled whole cells |
| mean graft | per-gene mean | centered expression residuals + coordinates |
| quantile graft | per-gene marginals | within-gene cell ranks + coordinates |
| spatial transplant | expression cells | matched 3-D coordinates |

These are mechanical guarantees about the generated file. They do not imply a better challenge score.

## Install

```bash
git clone https://github.com/i-habib/virtual-embryo-submission-blender
cd virtual-embryo-submission-blender
pip install -e .
```

Then:

```bash
vec-blend inspect A.h5ad B.h5ad
vec-blend --help
```

## Why there is no “auto-pick the best blend” command

The blender only uses the two submitted prediction files and parameters you provide. It does not accept leaderboard returns or try to infer target properties from score feedback.

That keeps the composition step reusable and auditable. Candidate selection is separate from file construction.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

The tests check the preservation guarantees above, actual `.h5ad` write/reopen behavior, rejection of invalid negative mean grafts, and recovery of a permuted spatial geometry when two expression clouds differ only by a gene-wise shift.

Independent community tool for the Virtual Embryo Challenge. The official rules and submission contract remain authoritative.
