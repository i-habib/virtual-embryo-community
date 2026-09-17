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

This notebook keeps expression fixed and changes the geometry in controlled ways:

- translation
- proper rotation
- reflection
- 2× uniform scale
- anisotropic stretch
- shuffling expression states among the exact same spatial coordinates

The last control is especially useful. The point cloud is literally unchanged. Only which biological state sits at which location changes. That separates global tissue geometry from local biological organization.

#### A surprisingly important blind spot: reflection

The public scorer source documents that the distance-based shape term is reflection-invariant. A mirrored embryo can therefore look perfect to that part of the shape panel. `sliced_wasserstein` and `occupancy_dice` only search over proper rotations, but the organizers explicitly caution that they have not been calibrated as laterality tests either.

That is exactly the kind of thing that is much easier to remember after seeing a mirrored embryo score than after reading a metric formula.

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

The result tables are generated from the pinned public scorer by CI. See [RESULTS.md](RESULTS.md) for the current values and figures.
<!-- AUTO_RESULTS_END -->

## Reproduce the results

All three notebooks pin `veckit` to:

`46d41e63f42a9aab815db20b742feeccd249cb17`

The result-refresh workflow executes the notebooks against that same scorer revision and regenerates the CSVs/figures in [`results/`](results/). The tiny public examples are intentionally small, so some distributional metrics are noisy. If a qualitative pattern matters to your method, repeat the same control on the full released training pair.

You can also regenerate the summary directly:

```bash
pip install "git+https://github.com/aristoteleo/veckit.git@46d41e63f42a9aab815db20b742feeccd249cb17" matplotlib pandas
python intuition-lab/generate_results.py
```

## What this is useful for

These controls are not diagnoses. If your model resembles one of them, it gives you a concrete hypothesis to test.

For example, good perturbation direction with poor severity suggests a different problem from high absolute correlation with a near-zero response. Likewise, good T2 shape with poor neighborhood structure points somewhere very different from a global scale error.

That is the goal of the lab: turn a vector of scorer numbers into something you can reason about.

## Sources

- [Challenge evaluation](https://virtualembryo.ai/challenge/evaluation)
- [Official `veckit` scorer](https://github.com/aristoteleo/veckit)
- [`shape_metrics.py` reflection/laterality note](https://github.com/aristoteleo/veckit/blob/46d41e63f42a9aab815db20b742feeccd249cb17/common/shape_metrics.py)

Independent community resource. The official challenge documentation and scorer remain the source of truth.
