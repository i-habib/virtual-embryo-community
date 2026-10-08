# Virtual Embryo for ML people

If you know ordinary ML but not single-cell biology, the challenge has a slightly awkward first hour. You can understand the file format and still not know what a sensible prediction is supposed to represent.

This guide is for that gap.

[![Open the data tour in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/i-habib/community-projects/blob/main/ml-guide/notebooks/virtual_embryo_data_tour.ipynb)

The central idea is that a developmental stage is a **population of cells**, not one supervised target vector and not a set of cells paired one-to-one with an earlier stage. From there, the guide works through what Task 1 is really predicting, what 3-D position adds in Task 2, and why Task 3 is easier to reason about as a perturbation response away from matched WT.

It also gets into modeling choices, but only after the failure mode is clear. The point is to end up with a sentence like “I need changing cell-state proportions without collapsing within-state diversity,” not just “maybe diffusion.”

Start with the **[full guide](guide.md)**. The **[data tour](notebooks/virtual_embryo_data_tour.ipynb)** opens the organizers' small public examples directly. There is also a **[one-page cheat sheet](CHEATSHEET.md)** if you only need the basic mental model.

For scorer behavior, the separate [Intuition Lab](https://github.com/i-habib/virtual-embryo-community/tree/main/intuition-lab) deliberately breaks known public targets and shows which metrics react.

For exact rules, file contracts, quotas, and uploads, use the official challenge documentation. Those are intentionally not duplicated here.

Independent community resource. MIT licensed.
