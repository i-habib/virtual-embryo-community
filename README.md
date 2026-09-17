# Virtual Embryo Intuition Lab

Controlled experiments for understanding what the Virtual Embryo Challenge scorer notices when one property of a prediction is deliberately broken.

## Intuition Lab

**[`intuition-lab/`](intuition-lab/)** contains matched teaching experiments for all three tasks:

- **Task 1:** right mean, wrong population; gene-wise shuffling; one-state resampling
- **Task 2:** translation/rotation/reflection/scale controls, anisotropic distortion, and expression-location shuffling
- **Task 3:** no response, weak/strong response, reversed response, and response assigned to the wrong genes

The notebooks use known public targets on purpose. They are scorer/intuition experiments, not hidden-board estimates.

The repo also includes the Task 2 rigid-rotation audit that found a reproducible PCA-canonicalization invariance issue in the public scorer, with the finding filed upstream as [`veckit#7`](https://github.com/aristoteleo/veckit/issues/7).

Start with **[`intuition-lab/README.md`](intuition-lab/README.md)** and the committed **[`RESULTS.md`](intuition-lab/RESULTS.md)**.

## Other community resources

The smaller standalone projects were consolidated into **[i-habib/community-projects](https://github.com/i-habib/community-projects)**:

- ML Guide
- Data Safety Kit
- Metric Lens

The larger external-data contribution remains separate at **[i-habib/external-data-catalog](https://github.com/i-habib/external-data-catalog)**.

These are independent community resources, not official challenge tools. The official rules, evaluation pages, and scorer remain the source of truth.

MIT licensed.
