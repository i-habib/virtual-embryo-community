# Virtual Embryo community tools

Independent tools, experiments and guides for the [Virtual Embryo Challenge](https://virtualembryo.ai/challenge). Each folder is self-contained, with its own README, tests and install line. The official challenge rules and the `veckit` scorer are the source of truth.

## Getting started

- [ml-guide](ml-guide/): what the data and prediction targets mean, for people who know ML but not single-cell biology. Includes a Colab data tour.
- [intuition-lab](intuition-lab/): notebooks that break one property of a prediction at a time and show which scorer terms move. The Task 2 controls found the rotation/handedness issue filed upstream as [`veckit#7`](https://github.com/aristoteleo/veckit/issues/7).
- [metric-lens](metric-lens/): turns a `veckit` metric vector into weighted score contributions and shows how many points each metric could still add.

## Data

- [panel-normalise](panel-normalise/): puts external raw counts on the release's normalisation (CP10k over the board panel, then log1p), with MGI alias and Ensembl rescue of gene names. [NORMALISATION.md](panel-normalise/NORMALISATION.md) documents how each released file was normalised.
- [external-data-catalog](external-data-catalog/): public external datasets with preprocessing adapters and records of real-release validation.
- [data-safety](data-safety/): checks the mechanically checkable external-data rules and renders a source disclosure.

## Combining predictions

- [submission-blender](submission-blender/): `vec-blend` combines two compatible prediction files (mixture, mean graft, quantile graft, spatial transplant).
- [ensemble-lab](ensemble-lab/): controlled experiments on when combining two predictions helps or hurts each scorer term.

## Agent track

- [agent-harness-lab](agent-harness-lab/): deterministic dry-run tasks for testing an agent harness before a locked run.
- [agent-trace-explorer](agent-trace-explorer/): turns an agent run log into a single static HTML report.

Each folder that used to be its own repository was imported with its history. MIT licensed.
