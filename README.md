# Virtual Embryo Ensemble Lab

When is it actually useful to combine two Virtual Embryo predictions?

This repo tests population-level ensemble operations against the public `veckit` scorer. The main experiments make **both parent predictions imperfect**, vary how their errors are split, and measure when a blend matches or beats the better parent on the primary metrics.

The experiments use the organizers' public mini targets. They are controlled scorer studies, not hidden-board estimates.

## Main results

See **[REGIME_RESULTS.md](REGIME_RESULTS.md)** for the full tables and heatmaps.

### Mean graft is robust when the errors are genuinely complementary

The mean-graft grid independently varies error in the mean donor and error in the carrier's cell-level structure.

Across the 24 imperfect grid points:

- 19/24 preserve the better parent on all four primary T1 metrics
- all 24 preserve it on at least half of the primary metrics
- all 24 strictly beat both parents on at least one primary metric
- none are worse than both parents on any primary metric

So the useful regime is much broader than the exact reconstruction control.

### Quantile graft has a clearer failure boundary

The quantile grid independently worsens the marginal donor and corrupts a fraction of the carrier's within-gene ranks.

It preserves the better parent on all four primary metrics at 19/24 imperfect points, but the high-error corner collapses. The heatmap makes that boundary visible instead of implying that rank/marginal grafting is always beneficial.

### Spatial transplant works well until matching becomes ambiguous

The T2 grid varies expression corruption and matching noise independently.

- 20/24 imperfect points preserve the better parent on all eight primary T2 metrics
- all 24 preserve at least half
- 3/24 become worse than both parents on at least one primary metric

The assignment comparison is also useful in practice. Hungarian and greedy matching agree at low noise, but greedy begins assigning the wrong geometry at high noise. At matching-noise `0.6`, coordinate RMSE is about `81.7` for greedy versus `5e-6` for Hungarian; at `1.0`, greedy reaches about `133.8` while Hungarian still recovers the known geometry.

### Simple population mixing is much less predictable

The mixture experiment varies parent complementarity and the mixture fraction. Unlike the factor grafts, whole-cell mixtures usually trade one metric against another rather than preserving the better component from each parent. The raw table is included so entrants can see where a mixture actually helps and where it merely interpolates between two errors.

## Baseline context

The regime run also scores the public challenge floor baselines with the same pinned scorer:

- T1 `copy_last`
- T2-heart `copy_last`
- T3 `wt_identity`

These give a reference point for the controlled grids without using leaderboard feedback.

## Exact preservation checks

**[RESULTS.md](RESULTS.md)** contains the smaller integration tests used to verify the operators themselves:

- mean versus centered population structure
- gene marginals versus within-gene ranks
- expression versus spatial assignment
- direct whole-cell mixtures

Some of those controls deliberately reconstruct the target almost exactly. They are implementation checks. The imperfect-complementarity study above is the evidence for when the operations remain useful away from that ideal case.

## Reproduce

```bash
git clone https://github.com/i-habib/virtual-embryo-ensemble-lab
cd virtual-embryo-ensemble-lab
pip install -r requirements.txt

# exact preservation/integration checks
python run_lab.py --out-dir results

# imperfect-complementarity grids + figures
python regime_map.py --out-dir regime_results
```

Both scripts download the public examples from the pinned scorer revision:

```text
aristoteleo/veckit@46d41e63f42a9aab815db20b742feeccd249cb17
```

The composition code is pinned to a tested revision of [Virtual Embryo Submission Blender](https://github.com/i-habib/virtual-embryo-submission-blender).

Raw metric tables are committed in [`results/`](results/) and [`regime_results/`](regime_results/). GitHub Actions reruns both studies when their experiment code changes.

## Why this is separate from the blender

The [Submission Blender](https://github.com/i-habib/virtual-embryo-submission-blender) is the reusable CLI/library. Ensemble Lab answers the decision question: **which operation should you try, and how much imperfect complementarity can it tolerate before the blend stops helping?**
