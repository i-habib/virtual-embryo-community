# Virtual Embryo Intuition Lab

The easiest way I found to understand the Virtual Embryo metrics was to stop reading metric definitions and start breaking predictions on purpose.

Each notebook takes a public target, keeps one property correct, damages another, and then runs the official scorer. The examples are target-aware by design. They are for understanding and debugging the evaluation, **not for estimating held-out performance**.

If the underlying biology/data objects are still unfamiliar, start with the [ML guide](../ml-guide/README.md).

## The three labs

### Task 1: population failures

[Open in Colab](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/intuition-lab/t1_population_failure_playground.ipynb) · [notebook](t1_population_failure_playground.ipynb)

The notebook asks what happens when the average expression is right but the population is wrong.

It compares:

- the same cells in a different row order
- one mean cell repeated over and over
- each gene independently shuffled across cells
- a population resampled from only one observed cell state

The useful distinction is between **mean**, **per-gene marginals**, **gene-gene structure**, and **population mixture**. Those are easy to blur together when looking at one aggregate score.

### Task 2: spatial failures

[Open in Colab](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/intuition-lab/t2_spatial_failure_playground.ipynb) · [notebook](t2_spatial_failure_playground.ipynb)

This started as a set of simple geometry controls. One of them exposed a scorer invariance failure that is more important than the tutorial example itself.

#### Proper rotations can change two shape scores

The public scorer says embryos may arrive in arbitrary rigid frames, so a proper rotation of the exact same point cloud should not change a shape score. I tested that directly on the public `sample_heart_9.5.h5ad` cloud:

- 72 z-axis rotations: `0°, 5°, ..., 355°`
- 50 random rotations from SO(3)

Across those 122 proper rotations, `d2_shape` and `scale_log_ratio` stay invariant to numerical precision. `sliced_wasserstein` and `occupancy_dice` do not.

The failure is discrete. After reproducing the scorer's `_match_n(seed=0)` step and PCA canonicalization exactly:

- 61 rotations end up with PCA frames of the same handedness: SW is essentially zero and Dice is `1.0`
- 61 end up with opposite-handed PCA frames: SW is `0.0384619` and Dice is `0.627451`

PCA handedness predicts **all 61 failures exactly**. The principal axes themselves are stable; the largest off-diagonal basis error after accounting for the known rotation is about `3e-14`.

The mechanism is that SVD chooses each principal-axis sign arbitrarily. Independent PCA canonicalization can therefore introduce an odd number of sign flips even when the world transform was a proper rotation. The downstream alignment only searches the four determinant-`+1` sign combinations, so it cannot undo that induced reflection.

The full audit is in [`rotation_audit.py`](rotation_audit.py), with [raw results](results/task2_rotation_audit.csv) and a [compact summary](results/task2_rotation_audit_summary.json). I filed the reproducer upstream as [aristoteleo/veckit#7](https://github.com/aristoteleo/veckit/issues/7).

#### Other spatial controls

The notebook also tests:

- translation
- a single proper rotation
- reflection
- 2× uniform scale
- anisotropic stretch
- shuffling expression states among the exact same spatial coordinates

The expression-location shuffle is especially useful: the point cloud is literally unchanged, while neighborhood MMD changes because biological states were moved to the wrong locations.

There is also a separate documented limitation: `d2_shape` is reflection-invariant. That laterality issue is distinct from the proper-rotation failure above.

### Task 3: perturbation-response failures

[Open in Colab](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/intuition-lab/task3_response_playground.ipynb) · [notebook](task3_response_playground.ipynb)

The Task 3 lab starts from the public matched WT/Mab21l2 pair and changes only the response:

- no response
- 25%, 50%, 100%, 150%, and 200% of the known mean response
- reversed response
- the same response values assigned to the wrong genes

This makes it obvious why a mutant prediction can have very high absolute expression correlation while completely missing the actual knockout effect.

<!-- AUTO_RESULTS_START -->
### What the public mini examples actually show

The notebooks are executed automatically against the pinned public scorer. The current raw tables and figures are in **[RESULTS.md](RESULTS.md)**.

- **T1 repeated mean:** pseudobulk Pearson `1`, while MMD is `0.2613`. A right average can still be a collapsed population.
- **T2 proper 67° rotation:** sliced Wasserstein `0.03846` and occupancy Dice `0.6275` even though the point cloud is unchanged up to a proper rotation. The dedicated audit reproduces this as the PCA-handedness issue reported upstream in `veckit#7`.
- **T2 expression-location shuffle:** neighborhood MMD `0.121` while the point cloud itself is unchanged.
- **T3 no-response:** absolute pseudobulk Pearson `0.9033` even though the knockout response is zero.

<!-- AUTO_RESULTS_END -->

## Reproduce the results

All three notebooks and the rotation audit pin `veckit` to:

`46d41e63f42a9aab815db20b742feeccd249cb17`

The result-refresh workflow executes the notebooks against that same scorer revision, runs the invariance audit, and regenerates the committed result files. The tiny public examples are intentionally small, so some distributional metrics are noisy. The rotation audit is different: every comparison is the exact same 150-point cloud under a known proper rigid transform.

```bash
pip install "git+https://github.com/aristoteleo/veckit.git@46d41e63f42a9aab815db20b742feeccd249cb17" matplotlib pandas
python intuition-lab/generate_results.py
python intuition-lab/rotation_audit.py
```

## What this is useful for

These controls are not diagnoses. If your model resembles one of them, it gives you a concrete hypothesis to test.

For example, good perturbation direction with poor severity suggests a different problem from high absolute correlation with a near-zero response. Likewise, good T2 shape with poor neighborhood structure points somewhere very different from a global scale error.

The rotation audit is the exception: it found a property of the scorer itself rather than a model failure.

## Sources

- [Challenge evaluation](https://virtualembryo.ai/challenge/evaluation)
- [Official `veckit` scorer](https://github.com/aristoteleo/veckit)
- [`shape_metrics.py`](https://github.com/aristoteleo/veckit/blob/46d41e63f42a9aab815db20b742feeccd249cb17/common/shape_metrics.py)
- [Upstream rotation-invariance issue](https://github.com/aristoteleo/veckit/issues/7)

Independent community resource. The official challenge documentation and scorer remain the source of truth.
