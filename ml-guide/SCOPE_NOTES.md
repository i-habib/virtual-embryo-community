# Scope notes

Before building these, I checked the official `veckit` repo and the existing community tools. A format validator, first-submission walkthrough, baseline writer, local-score wrapper, and Agent evidence packager were already covered well enough that duplicating them did not seem useful.

The three projects here survived that audit for different reasons.

## Metric Lens

The first version only reconstructed the published weighted score. That was basically arithmetic. I kept it after adding the more useful question: if one metric moved to its published validation ceiling while everything else stayed fixed, how many points are even available there?

The tests enforce two simple sanity checks on every supported board: published floors reconstruct to 50/100 and published ceilings to 100/100. Signed best-at-zero metrics are tested separately.

## ML Guide

The official docs explain the challenge mechanics, but they assume quite a lot of single-cell intuition. I wanted something for the point where an ML entrant has a valid `.h5ad` in front of them and still does not know what the model is meant to learn.

The guide therefore spends most of its time on the missing mental model: cells are not paired through time, a stage is a population rather than one target vector, Task 2 couples expression to tissue geometry, and Task 3 is mostly about the response away from matched WT.

## Data Safety Kit

The external-data rules contain exact stage windows alongside cases that need biological judgment. The checker only automates the former. Somite/Theiler mappings, comparable-stage alleles, and possible phenocopies return `ASK_ORGANIZERS` instead of being guessed.

Its interval logic was rewritten after an early implementation mishandled legal endpoints surrounding protected open intervals. The regression tests now include those exact boundary cases.

The source registry is there for a more mundane reason: external-data disclosure is much easier if the URL, version, licence, stages, role, and filtering are recorded while the experiment is running.

## Split-out projects

Two larger pieces now have their own repositories:

- [Intuition Lab](https://github.com/i-habib/virtual-embryo-community/tree/main/intuition-lab)
- [External Data Catalog](https://github.com/i-habib/external-data-catalog)
