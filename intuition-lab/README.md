# Virtual Embryo Intuition Lab

The easiest way I found to understand the Virtual Embryo metrics was to stop reading metric definitions and start breaking predictions on purpose.

Each notebook takes a public target, keeps some properties fixed, damages one other property, and runs the official scorer. The examples are deliberately target-aware. They are debugging experiments, **not hidden-board estimates**.

If the single-cell objects themselves are still unfamiliar, the separate [ML guide](https://github.com/i-habib/community-projects/tree/main/ml-guide) is a better place to start.

## Task 1: right mean, wrong population

[Open in Colab](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/intuition-lab/t1_population_failure_playground.ipynb) · [notebook](t1_population_failure_playground.ipynb)

The Task 1 notebook compares the real target with four controls:

- the same cells in a different row order
- the mean cell repeated over and over
- each gene shuffled independently across cells
- cells resampled from only one observed state

These separate a few things that are easy to conflate: a correct pseudobulk mean, correct per-gene marginals, realistic gene-gene structure, and a realistic mixture of cell states.

## Task 2: break the tissue in controlled ways

[Open in Colab](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/intuition-lab/t2_spatial_failure_playground.ipynb) · [notebook](t2_spatial_failure_playground.ipynb)

The notebook tries translation, rotation, reflection, uniform scaling, anisotropic stretch, and an expression-location shuffle. The last control keeps the exact same point cloud and the exact same set of expression vectors, but assigns those vectors to different positions. Shape stays fixed while local biological organization is destroyed.

### The rotation control found a scorer bug

A proper rigid rotation should only change the coordinate frame. On the public `sample_heart_9.5.h5ad` cloud, however, some proper rotations change `sliced_wasserstein` and `occupancy_dice`.

I checked 72 z-axis rotations and 50 random rotations from SO(3). After reproducing the scorer's `_match_n(seed=0)` and PCA canonicalization exactly:

- 61 rotations produce same-handed PCA frames and score essentially as identity: SW ≈ 0, Dice = `1.0`
- 61 produce opposite-handed PCA frames and all receive the same penalty: SW = `0.0384619`, Dice = `0.627451`

PCA handedness predicts all 61 failures with no false positives or false negatives. The principal axes themselves are stable; the largest off-diagonal basis error after accounting for the known rotation is about `3e-14`.

The issue comes from independent SVD sign choices. PCA can insert an odd number of sign flips even when the original transform has determinant `+1`, while the downstream alignment only searches determinant-`+1` sign combinations and therefore cannot undo the induced reflection.

The reproducer is in [`rotation_audit.py`](rotation_audit.py), with [raw results](results/task2_rotation_audit.csv) and a [summary](results/task2_rotation_audit_summary.json). I filed it upstream as [aristoteleo/veckit#7](https://github.com/aristoteleo/veckit/issues/7).

This is separate from the known fact that `d2_shape` is reflection-invariant.

## Task 3: perturbation response, not just absolute similarity

[Open in Colab](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/intuition-lab/task3_response_playground.ipynb) · [notebook](task3_response_playground.ipynb)

Starting from the public matched WT/Mab21l2 pair, the notebook tries no response, several response magnitudes, a reversed response, and the right response values assigned to the wrong genes.

The useful lesson is that a prediction can still look very WT-like in absolute expression while missing the knockout effect almost completely.

<!-- AUTO_RESULTS_START -->
### What the public mini examples actually show

The notebooks are executed automatically against the pinned public scorer. The current raw tables and figures are in **[RESULTS.md](RESULTS.md)**.

- **T1 repeated mean:** pseudobulk Pearson `1`, while MMD is `0.2613`. A right average can still be a collapsed population.
- **T2 proper 67° rotation:** sliced Wasserstein `0.03846` and occupancy Dice `0.6275` even though the point cloud is unchanged up to a proper rotation. The dedicated audit reproduces this as the PCA-handedness issue reported upstream in `veckit#7`.
- **T2 expression-location shuffle:** neighborhood MMD `0.121` while the point cloud itself is unchanged.
- **T3 no-response:** absolute pseudobulk Pearson `0.9033` even though the knockout response is zero.

<!-- AUTO_RESULTS_END -->

## Reproducing it

Everything is pinned to `veckit` commit `46d41e63f42a9aab815db20b742feeccd249cb17`. A GitHub Actions workflow executes the notebooks, reruns the rotation audit, and refreshes the committed tables and figures.

```bash
pip install "git+https://github.com/aristoteleo/veckit.git@46d41e63f42a9aab815db20b742feeccd249cb17" matplotlib pandas
python intuition-lab/generate_results.py
python intuition-lab/rotation_audit.py
```

The public mini datasets are tiny, so I would not over-interpret small changes in their distributional metrics. The rotation audit is cleaner: every comparison is the same 150-point cloud under a known proper rigid transform.

## Sources

- [Challenge evaluation](https://virtualembryo.ai/challenge/evaluation)
- [Official `veckit` scorer](https://github.com/aristoteleo/veckit)
- [`shape_metrics.py`](https://github.com/aristoteleo/veckit/blob/46d41e63f42a9aab815db20b742feeccd249cb17/common/shape_metrics.py)
- [Upstream rotation-invariance issue](https://github.com/aristoteleo/veckit/issues/7)

Independent community resource. The official challenge documentation and scorer remain the source of truth.
