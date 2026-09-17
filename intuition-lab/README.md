# Virtual Embryo Intuition Lab

A small set of controlled experiments for understanding what the Virtual Embryo scorer is actually rewarding.

The goal is not to provide another starter kit or another leaderboard baseline. The official docs and existing community tools already cover submission mechanics well. This package is for a different question:

> If I deliberately break one property of a prediction while keeping another property correct, which part of the scorer notices?

That makes the evaluation much easier to reason about before you start training serious models.

## Learning path

Start with the broader [Virtual Embryo for ML people guide](../ml-guide/README.md), then run the playground for the task you care about.

### Task 1 — population failure playground

[Open in Colab](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/intuition-lab/t1_population_failure_playground.ipynb) · [view notebook](t1_population_failure_playground.ipynb)

Controlled failures:

- row-order shuffle: same set of cells, different order
- repeated mean: perfect pseudobulk, no population diversity
- gene-wise shuffle: same marginal distribution for every gene, broken joint structure
- one-state resample: real cells, deliberately wrong mixture

The useful lesson is that **a good average is not a good generated population**.

### Task 2 — spatial failure playground

[Open in Colab](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/intuition-lab/t2_spatial_failure_playground.ipynb) · [view notebook](t2_spatial_failure_playground.ipynb)

Controlled failures:

- translation
- proper rotation
- reflection
- uniform scaling
- anisotropic stretching
- expression-location shuffle

The last one keeps the exact same 3D point cloud and exact same collection of expression vectors, but attaches those expression states to the wrong positions. It cleanly separates **global geometry** from **local biological organization**.

### Task 3 — perturbation response playground

[Open in Colab](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/t3-response-playground/t3_response_playground.ipynb) · [view notebook](../t3-response-playground/t3_response_playground.ipynb)

Controlled failures:

- no response
- response too weak / too strong
- reversed response
- correct effect sizes assigned to the wrong genes

The useful lesson is that **looking like a plausible mutant state is not the same as predicting the knockout effect**.

## Why the notebooks use known targets

These are teaching/debugging experiments, not benchmark estimates.

Each notebook deliberately uses a public known target to construct synthetic failure cases. That lets us hold one property fixed and break another with certainty. It would be inappropriate to interpret any resulting score as evidence of held-out performance.

## Reproducibility

The notebooks pin the organizers' public `veckit` scorer and example files to the same Git commit:

`46d41e63f42a9aab815db20b742feeccd249cb17`

The tiny bundled examples make the notebooks quick to run, but also noisy. If a qualitative effect matters to your own method, repeat the same diagnostic with the full released training files.

## Official sources

- Challenge tasks: https://virtualembryo.ai/challenge/tasks
- Evaluation: https://virtualembryo.ai/challenge/evaluation
- Local scorer: https://github.com/aristoteleo/veckit

Independent community resource. The official challenge documentation remains the source of truth.
