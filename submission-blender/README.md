# Virtual Embryo Submission Blender

`vec-blend` combines two compatible Virtual Embryo prediction files when they are good at different parts of the problem. It works on the `.h5ad` predictions themselves and does not use leaderboard scores or hidden-target feedback.

## Blend methods

### Population mixture

Sample complete cells from both submissions.

```bash
vec-blend blend A.h5ad B.h5ad \
  --method mixture --alpha 0.4 --n-out 10000 \
  -o mixed.h5ad
```

Expression and coordinates stay paired within every sampled cell. Sparse inputs stay sparse.

### Mean graft

Give B's centered cell population A's per-gene mean:

\[
X_{out}=X_B+(\mu_A-\mu_B).
\]

```bash
vec-blend blend A.h5ad B.h5ad \
  --method mean-graft --clip-min 0 \
  -o grafted.h5ad
```

The operation is row-chunked and uses float32. Before clipping, it preserves B's centered residuals and replaces its mean with A's. A large shift can make some values negative, so the CLI refuses to write the result unless a nonnegative floor is supplied. `--clip-min 0` floors those values and records the resulting mean error.

### Quantile graft

Use A's empirical distribution for each gene while following B's within-gene cell ranks.

```bash
vec-blend blend A.h5ad B.h5ad \
  --method quantile-graft \
  -o quantile_graft.h5ad
```

When the cell counts match, each output gene has the same float32 values as A, reordered according to B's ranks. Genes are processed one at a time, including for sparse inputs, so the two full input matrices are not simultaneously densified. The output itself is dense.

### Spatial transplant

Keep A's expression rows and assign coordinates from B by one-to-one matching in centered expression space.

```bash
vec-blend blend expression_model.h5ad geometry_model.h5ad \
  --method spatial-transplant \
  --max-match-genes 2048 \
  -o transplanted.h5ad
```

The matcher uses the highest pooled-variance genes, capped at 2,048 by default, then runs PCA and a one-to-one assignment. Up to the exact limit it uses Hungarian matching; larger jobs use the unique greedy matcher. A's `obs` metadata is retained while coordinates come from B, so location-derived `obs` fields from A may be stale after a transplant.

## Output checks and provenance

Every CLI output passes blend-level checks before it is written: finite and nonnegative expression, nonempty dimensions, unique genes, and a well-formed `spatial_3D` array when one is present. `--clip-min` must be nonnegative.

These checks do not replace the official task-specific validator. They do not know which board you are targeting, so they cannot enforce that board's exact gene panel, cell-count range, required spatial fields, or upload-size limit. Run the current official validation path before upload.

Gene order may differ between inputs; B is reordered to A. The gene sets themselves must match.

Every output also gets a `.blend.json` sidecar with the blend parameters, package version, input paths, SHA-256 hashes of both source files, and the final `.h5ad` size in bytes/MiB.

## Mixture sweeps

```bash
vec-blend sweep A.h5ad B.h5ad \
  --alphas 0,0.25,0.5,0.75,1 \
  --n-out 10000 \
  --out-dir blends/
```

A sweep uses one fixed output cell count. If A and B have different sizes, `--n-out` is required so changing alpha does not also change the number of predicted cells.

## Tested scale

CI includes a synthetic full-T1-width stress test. On the hosted Ubuntu runner it completed:

- sparse population mixture: **10,000 cells × 32,285 genes**, 2% density, output remained sparse, **1.79 s**
- chunked mean graft: **10,000 cells × 32,285 genes**, 2% sparse inputs, dense float32 output, **4.24 s**
- peak process RSS across the combined stress script: **1,816.66 MiB**

The exact command and latest recorded run are in [`benchmarks/`](benchmarks/). These numbers are a regression test, not a runtime guarantee. Population mixing can remain sparse. Mean graft and quantile graft currently produce dense float32 outputs, so output memory grows roughly as `4 * cells * genes` bytes before `.h5ad` compression. Spatial matching only materializes its selected matching genes, while the returned expression matrix preserves A's storage format.

The stress test establishes that the operations run at full Task 1 gene width. It does not imply that every resulting file fits the challenge upload limit; the sidecar reports the actual written size so that can be checked directly.

## Inspect files

```bash
vec-blend inspect A.h5ad B.h5ad
```

`inspect` reports dimensions, spatial availability, sparse/dense storage, expression range, finiteness, and nonnegativity without densifying sparse expression.

## Install

```bash
git clone https://github.com/i-habib/virtual-embryo-community
cd virtual-embryo-community/submission-blender
pip install -e .
```

Tests:

```bash
pip install -e ".[dev]"
pytest -q
```

The suite checks the preservation claims, sparse handling, final output guard, `.h5ad` write/reopen behavior, fixed-size sweeps, provenance hashes, and both Hungarian and greedy spatial matching on known correspondences.

See [Virtual Embryo Ensemble Lab](../ensemble-lab/) for controlled scorer experiments and imperfect-complementarity regime maps.
