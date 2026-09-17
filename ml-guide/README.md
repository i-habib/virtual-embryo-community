# Virtual Embryo for ML people

A conceptual guide to the Virtual Embryo Challenge for people who know machine learning but not single-cell biology.

[![Open the data tour in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/ml-guide/notebooks/virtual_embryo_data_tour.ipynb)

The official documentation is already good at telling you the rules, file format, and scoring system. Existing community tooling is also good at getting you from registration to a valid submission. This guide is for the step in between:

> **What is the dataset actually representing, what kind of object am I trying to predict, and what would a sensible model even look like?**

Start with **[the guide](guide.md)**. Then open **[the data tour notebook](notebooks/virtual_embryo_data_tour.ipynb)** and inspect the organizers' small public examples yourself.

## What this covers

- what a row, column, and value in the expression matrix mean
- why there is no “same cell later” target
- why the tasks are population-generation problems rather than ordinary regression
- what changes between Tasks 1, 2, and 3
- how to read the scoring questions without memorizing every metric acronym
- a modeling ladder from copy-last to state-aware dynamics, optimal transport, and conditional generative models
- common failure modes that are easy to miss if you come from standard ML benchmarks

## What this does not cover

For exact contracts, quotas, rules, and upload steps, use the official challenge site and starter kit. Those are the source of truth.

The modeling ideas here are starting points, not claims about what will win the challenge.

## Quick links

- [Full conceptual guide](guide.md)
- [One-page cheat sheet](CHEATSHEET.md)
- [Runnable data tour](notebooks/virtual_embryo_data_tour.ipynb)
- [Intuition Lab: controlled failures for Tasks 1–3](../intuition-lab/README.md)
- [Official challenge](https://virtualembryo.ai/challenge)
- [Official tasks](https://virtualembryo.ai/challenge/tasks)
- [Official evaluation](https://virtualembryo.ai/challenge/evaluation)
- [Official local scorer (`veckit`)](https://github.com/aristoteleo/veckit)

Independent community resource. MIT licensed.
