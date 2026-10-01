# Virtual Embryo Ensemble Atlas

When do two imperfect Virtual Embryo predictions actually combine well?

This repo studies ensemble behavior at the level of the submitted cell population. It maps where different composition strategies help, where they trade metrics, and where they fail. It also measures properties of the two parent predictions that can be computed **without a target** and asks whether those properties predict ensemble success.

The experiments use the organizers' public mini examples and the pinned public `veckit` scorer. They are controlled studies, not hidden-board estimates.

## Start here

- **[ATLAS_RESULTS.md](ATLAS_RESULTS.md)**: target-free parent diagnostics, method × metric transfer matrix, comparisons with simple ensemble baselines, and organizer reference-row pairs.
- **[REGIME_RESULTS.md](REGIME_RESULTS.md)**: phase diagrams for imperfect complementarity.
- **[RESULTS.md](RESULTS.md)**: exact preservation checks for the individual operators.

## What seems useful so far

### Mean graft is fairly forgiving

Across the imperfect T1 grid, mean graft preserved the better parent on all four primary metrics at 19/24 nontrivial points and never became worse than both parents on any primary metric.

Among target-free diagnostics, variance disagreement is the clearest signal in this grid (`Spearman rho = -0.52`). Below the grid median, the graft preserved the better parent on all primary metrics on average. Above it, that average fell to about 0.90. The method still worked surprisingly often even when the two populations had fairly different variance structure.

### Quantile graft needs more compatible population structure

Quantile graft also succeeds at 19/24 imperfect grid points on all four primary metrics, but its failure region is much sharper.

Variance disagreement between the parent predictions has `rho = -0.71` with preservation of the better parent. In the lower-disagreement half of the grid, the graft preserved the better parent on every primary metric on average. In the higher-disagreement half, the average dropped to 0.50.

That is a useful warning: complementary-looking marginals and ranks are not enough if the two parent populations disagree strongly in their overall spread.

### Spatial transplant depends on match confidence

Spatial transplant preserves the better parent on all eight primary T2 metrics at 20/24 imperfect points, but matching quality matters.

Two diagnostics computed from the parent files alone are informative here:

- expression-space assignment ambiguity: `rho = -0.60`
- mutual nearest-neighbor fraction: `rho = +0.59`

Below the controlled-grid median ambiguity, every tested point preserved the better parent on all primary metrics and none lost to both parents. Above it, 25% of the tested points lost to both parents on at least one primary metric.

The Hungarian/greedy comparison shows the same failure directly. Greedy matching is fine at low noise, then breaks sharply once correspondences become ambiguous.

### Whole-cell mixtures are much less predictable

Population mixing rarely preserves the best component from both parents. In the current T1 grid it preserves the better parent on `mmd_u` fairly often, but almost never preserves the better parent on `de_direction` or `variogram`.

The target-free diagnostics tested so far do not predict mixture success well. For now, mixture sweeps are better treated as a cheap empirical search than as a reliable factor-combination rule.

## Metric transfer matrix

`ATLAS_RESULTS.md` reports, for each method and each official primary metric, the fraction of tested regimes where the blend matched or beat the better parent on that metric.

A few examples from the current run:

| method | DE direction | MMD | variogram | occupancy Dice | neighborhood MMD |
|---|---:|---:|---:|---:|---:|
| mean graft | 1.00 | 0.80 | 1.00 | - | - |
| quantile graft | 0.80 | 0.80 | 0.80 | - | - |
| population mixture | 0.00 | 0.89 | 0.00 | - | - |
| spatial transplant | 1.00 | 1.00 | 1.00 | 0.92 | 1.00 |

The point is the tradeoff pattern, not a single aggregate score.

## Comparisons that do not use Blender operators

The Atlas includes simple alternatives so the study is not just a test suite for the companion Blender repo:

- rowwise averaging where a controlled pair really has aligned rows
- half pseudobulk shifting
- whole-cell population mixing
- raw-expression Hungarian matching
- random coordinate transfer
- same-index coordinate transfer

On the representative imperfect T1 pairs, mean and quantile graft each preserve the better parent on all four primary metrics. Rowwise averaging preserves none. Whole-cell mixing preserves only one of four.

For the T2 pair, several coordinate-transfer rules look acceptable on global metrics, which is itself useful: spatial ensembling needs local-structure metrics and matching diagnostics to distinguish plausible from genuinely coherent assignments.

## Negative results

The repo keeps cases where ensembling makes things worse.

- population mixing can lose to **both** parents on a primary metric
- quantile graft has a high-disagreement failure region
- spatial transplant has failures once matching becomes ambiguous
- greedy spatial assignment can suddenly collapse while Hungarian matching still recovers the known geometry
- on organizer reference-row pairs, a supposedly complementary-looking pair often gives only partial or zero improvement

These are as important as the clean success cases because they answer when **not** to ensemble.

## Organizer reference-row stress tests

The public mini bundle is too small to reconstruct every published baseline honestly. In particular, `pseudobulk_shift` requires two preceding observed stages, and a non-leaking `shift_transfer` experiment needs a distinct training and evaluation knockout.

The Atlas therefore reconstructs only organizer-defined reference rows supported by the public mini files:

- T1: `copy_last`, `ctrl_one_cell`, `ctrl_scale_ref`, `ctrl_shrink_ref`
- T2: `ctrl_scale_ref`, `ctrl_squashed_ref`
- T3: `wt_identity`, `ctrl_scale_wt`

These pairs were defined by the organizers rather than designed around an ensemble operator. Their results are in [`atlas_results/organizer_reference_pairs.csv`](atlas_results/organizer_reference_pairs.csv).

## Target-free complementarity diagnostics

For every controlled parent pair the Atlas computes quantities available before scoring:

- pseudobulk mean disagreement
- variance disagreement
- covariance disagreement
- average marginal Wasserstein distance
- cell-count mismatch
- spatial shape disagreement
- expression-space assignment ambiguity
- mutual nearest-neighbor fraction

The outcome correlations and median-split summaries are in:

- [`atlas_results/diagnostic_correlations.csv`](atlas_results/diagnostic_correlations.csv)
- [`atlas_results/diagnostic_bins.csv`](atlas_results/diagnostic_bins.csv)
- [`atlas_results/parent_diagnostics.csv`](atlas_results/parent_diagnostics.csv)

The current numeric thresholds come from small controlled grids. They are clues for model selection, not universal cutoffs.

## Reproduce

```bash
git clone https://github.com/i-habib/virtual-embryo-ensemble-lab
cd virtual-embryo-ensemble-lab
pip install -r requirements.txt

# exact operator checks
python run_lab.py --out-dir results

# phase diagrams and failure regions
python regime_map.py --out-dir regime_results

# diagnostics, transfer matrix, comparator and reference-row studies
python ensemble_atlas.py --regime-dir regime_results --out-dir atlas_results
```

All studies use:

```text
aristoteleo/veckit@46d41e63f42a9aab815db20b742feeccd249cb17
```

GitHub Actions reruns the experiments and commits the tables/figures.

## Validation-data rerun

The challenge says validation ground truth is released on **20 October 2026**, when ranking moves to the hidden test split. The Atlas analysis is set up so the same transfer matrices and diagnostics can be rerun on those released conditions. That will be the first useful check of whether the controlled-mini decision patterns transfer to realistic validation predictions.

The companion [Virtual Embryo Submission Blender](https://github.com/i-habib/virtual-embryo-submission-blender) provides reusable composition code. This repo is about the empirical question of when ensembling helps.
