# Virtual Embryo community resources

A set of independent resources for the Virtual Embryo Challenge. Each one solves a different problem entrants run into.

## 1. ML Guide

**[`ml-guide/`](ml-guide/)** is for people who know machine learning but not much single-cell or developmental biology.

It explains what the challenge is actually asking you to generate, why cells are not paired across developmental stages, what changes between Tasks 1–3, and what modeling capability each common failure mode points to.

Start here if `.h5ad`, pseudobulk, spatial transcriptomics, or population-level prediction are still fuzzy.

## 2. Intuition Lab

**[`intuition-lab/`](intuition-lab/)** breaks predictions in controlled ways and runs the public scorer.

- Task 1: right mean, wrong population
- Task 2: harmless frame changes, wrong scale/shape, mirrored geometry, and right point cloud with biology in the wrong places
- Task 3: no response, weak/strong response, reversed response, and response assigned to the wrong genes

Rather than memorizing metric acronyms, you can see which scorer terms react when one known property is broken. The notebooks are executed automatically against a pinned `veckit` revision, and the committed tables/figures live in [`intuition-lab/RESULTS.md`](intuition-lab/RESULTS.md).

## 3. Data Safety Kit

**[`data-safety/`](data-safety/)** is a conservative checker for the challenge's external-data rules.

It handles the stage windows that are mechanically specified, including exact open/closed boundaries and broad resources that span both permitted and protected stages. Cases that need biological judgment, such as comparable alleles or phenocopies, return `ASK_ORGANIZERS` instead of guessing.

It also includes a small source registry/disclosure renderer so provenance is recorded while you work.

## 4. Metric Lens

**[`metric-lens/`](metric-lens/)** turns raw local `veckit` metrics into their weighted public-board contributions and shows how much score headroom is associated with each metric.

It is a small debugging utility, not a hidden-score predictor.

## Related: external-data catalog

The curated source catalog and preprocessing adapters now live in their own repository: **[i-habib/external-data-catalog](https://github.com/i-habib/external-data-catalog)**.

That project covers a different problem: finding useful public resources, checking the task-relevant stage caveats, and converting them into cleaner inputs with provenance sidecars.

## Reliability

CI runs the Data Safety and Metric Lens tests and checks every committed notebook for valid JSON/Python cells. A separate workflow executes all three Intuition Lab notebooks against the pinned public scorer and commits the resulting tables and figures.

These are community resources, not official challenge tools. The official rules, evaluation pages, and scorer are the source of truth.

MIT licensed.
