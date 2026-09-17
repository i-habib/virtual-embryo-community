# Virtual Embryo community resources

A few independent resources I made while getting familiar with the Virtual Embryo Challenge. They are meant to fill gaps around the official documentation, not replace it.

I have grouped the useful pieces into two main packages rather than treating every small notebook as a separate project.

## 1. Intuition Lab — understand what the tasks are actually measuring

Start with **[`ml-guide/`](ml-guide/)** if you know machine learning but have little or no single-cell background.

Then use **[`intuition-lab/`](intuition-lab/)** to break each task in controlled ways and watch the official scorer react:

- **Task 1:** keep the mean right while destroying population diversity, gene-gene structure, or cell-state mixture.
- **Task 2:** separate harmless coordinate-frame changes from wrong scale, wrong shape, and wrong local biological organization.
- **Task 3:** keep a plausible mutant state while making the knockout response too weak, too strong, reversed, or assigned to the wrong genes.

The point is to make abstract phrases like “cell-state distribution,” “joint structure,” and “local spatial organization” concrete before you spend time training a serious model.

The notebooks use only public known targets and are explicitly **teaching/debugging experiments, not held-out benchmark estimates**.

## 2. Data Safety Kit — audit external data before it becomes a problem

**[`data-safety/`](data-safety/)** is a conservative helper for external datasets, pretrained models, and published code.

It includes:

- a stage/genotype checker for the cases that are mechanically clear from the published rules
- `FILTER_REQUIRED` handling for general-purpose resources that span both allowed and protected stages
- explicit `ASK_ORGANIZERS` results for cases that require biological judgment rather than pretending the rule can be automated
- a tiny source registry and renderer so external-data disclosures are recorded while you work
- boundary tests for the easy-to-misremember stage rules

This is not an official eligibility oracle. The current challenge rules and organizer answers always win.

## Smaller utility

**[`metric-lens/`](metric-lens/)** takes raw local `veckit` metrics and shows where the weighted score is coming from, including a simple “if only this metric reached its published ceiling, how many points are available?” view.

It is useful during iteration, but I consider the two packages above the more generally useful community resources.

## Why these, rather than another starter kit?

The first ideas were a submission validator, baseline writer, first-submission tutorial, and Agent-track evidence helper. After checking the official `veckit` repository and existing community projects, those jobs were already covered well. Rebuilding them would mostly create duplicate plumbing.

The remaining friction was different:

1. A general ML entrant can make a valid file while still not understanding what a “future population of cells” means or why there is no cell-to-cell target across time.
2. Metric definitions are much easier to internalize when you deliberately preserve one property and break another.
3. The external-data rules are permissive but nuanced enough that a general-purpose atlas or pretrained model can accidentally contain protected material.

The development notes in [`DEVELOPMENT.md`](DEVELOPMENT.md) record how the scope changed and what was dropped along the way.

## Status

These are independent community resources, not official Virtual Embryo tools. None use hidden challenge data. The official challenge site, rules, and scorer remain the source of truth.

MIT licensed.
