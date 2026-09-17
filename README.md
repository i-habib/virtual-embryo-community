# Virtual Embryo Intuition Lab

I built this to answer a simple debugging question: if I keep most of a prediction fixed and break one thing, which scorer terms move?

The repo has one set of controlled experiments for each Virtual Embryo task:

- **Task 1:** preserve the mean while collapsing or scrambling the population.
- **Task 2:** change geometry, scale, or the mapping between expression and position while keeping other pieces fixed.
- **Task 3:** weaken, reverse, remove, or misassign a known perturbation response.

The notebooks use the organizers' public mini examples and known targets on purpose. They are for understanding the scorer, not for estimating hidden-board performance.

The Task 2 controls also turned up a real scorer issue: some proper rigid rotations of the exact same point cloud change `sliced_wasserstein` and `occupancy_dice`. A 122-rotation audit traced it to PCA handedness, and the reproducer is filed upstream as [`veckit#7`](https://github.com/aristoteleo/veckit/issues/7).

Start with [`intuition-lab/README.md`](intuition-lab/README.md). The current executed tables and figures are in [`intuition-lab/RESULTS.md`](intuition-lab/RESULTS.md).

## Related resources

- [External Data Catalog](https://github.com/i-habib/external-data-catalog) — public data sources with real-release validation and preprocessing adapters.
- [Community Projects](https://github.com/i-habib/community-projects) — the ML guide, Data Safety Kit, and Metric Lens.

Independent community work. The official challenge rules and scorer are the source of truth.

MIT licensed.
