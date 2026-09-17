# Development notes

This is a short record of how these resources ended up in their current form. The projects are intentionally narrow, so I wanted to record what was tried, what was dropped, and why the repository did not simply become another starter kit.

## 1. Audit before building

The first pass was mostly looking for repeated friction in the challenge setup. The obvious candidates were:

- a submission-file validator
- a first-submission tutorial
- baseline writers
- a local score wrapper
- an Agent-track evidence packager

I dropped all of those after checking the official `veckit` repository and existing public community tooling. In particular, the public `vec-community-kit` already covers validation, baseline generation, pseudo-validation, Agent evidence packaging, and an English/Chinese walkthrough. A separate `virtual-embryo-cli` covers remote submission from the command line.

That changed the question from “what can I build?” to “what repeated entrant confusion is still unsolved?”

## 2. Metric Lens

The first version simply converted each raw metric to challenge skill and added the published weights. That worked, but it was not very useful: it mostly reproduced arithmetic someone could do by hand.

The useful addition was a simple what-if view: hold every metric fixed, move one metric to its published validation ceiling, and calculate how many total points that change could possibly recover. This does **not** say the metric is easy to improve. It only answers whether improving it is worth much under the public scoring rule.

Before keeping the tool, I added two basic checks that should hold on every supported board:

- published floor values reconstruct to exactly 50/100
- published ceiling values reconstruct to exactly 100/100

I also added a separate test for signed “best at zero” metrics such as `severity_slope`.

Metric Lens stayed in the repository, but after building the later resources I stopped treating it as the main contribution. It is useful during iteration, but it reaches a narrower audience.

## 3. T3 Response Playground

The first notebook idea was a broad Task 3 tutorial. That was too close to the existing documentation and would have become a long explanation rather than a useful experiment.

The notebook was narrowed to one question:

> If I break a known perturbation in one controlled way, which metrics notice?

It uses the small matched-WT / Mab21l2 sample pair already published with `veckit`, then constructs several deliberately simple predictions: no response, weak/strong response, reversed response, and response values assigned to the wrong genes.

The target is known on purpose. The notebook is a scorer/debugging experiment, not a benchmark estimate.

## 4. ML guide

After the first two tools were built, a more foundational gap became clearer.

A new entrant can follow the official challenge docs and the existing first-submission tutorials all the way to a valid upload while still being confused about the actual learning problem. The missing questions are things like:

- what exactly is one row of the matrix?
- why is there no “same cell later” label?
- why is the target a distribution of cells rather than a regression vector?
- what does adding 3D coordinates change in Task 2?
- why can copying wild type look deceptively good in Task 3?
- what is the smallest modeling step beyond the floor that fixes a real failure mode?

That led to `ml-guide/`. The guide introduces modeling ideas through the failure they fix rather than through architecture names.

## 5. Intuition Lab

The T3 playground suggested a more general pattern: definitions are easier to understand when one property is held fixed and another is deliberately broken.

I therefore added two matching experiments and grouped all three into `intuition-lab/`:

- **Task 1:** row-order control, repeated mean, gene-wise shuffle, and one-state resampling. This separates pseudobulk accuracy, population diversity, gene-gene structure, and mixture composition.
- **Task 2:** translation, proper rotation, reflection, scaling, anisotropic stretching, and an expression-location shuffle. The last control keeps the exact same point cloud and exact same expression rows while breaking which biological states are neighbors.
- **Task 3:** the existing perturbation-response failures.

The package is intentionally target-aware and pedagogical. It is not a local validation scheme and does not claim to predict hidden leaderboard performance.

## 6. Data Safety Kit

The other high-impact gap was less glamorous: the external-data rules are permissive, but nuanced enough that a team can accidentally include protected material from a broad atlas or pretrained model.

A fully automatic “eligibility checker” would be irresponsible because some rules depend on biological judgment. So `data-safety/` is deliberately conservative.

It only automates cases that are mechanically clear from the published rules, such as explicit embryonic-day windows and the exact held-out Task 3 conditions. It returns `ASK_ORGANIZERS` for somite/Theiler mappings, comparable-stage allele questions, and phenocopies.

The first implementation was checked against boundary cases that are easy to misremember, especially:

- E9.5 is allowed for the extrapolation rule
- values just after E9.5 are protected
- E13.5 is still protected
- values after E13.5 are outside that explicit window
- the Task 2 interpolation windows are strict, so the released bracketing stages themselves remain allowed

I also added a source registry + disclosure renderer because the useful workflow is not just “is this source allowed?” but “can I reconstruct exactly what external material entered the method when the final report is due?”

## 7. What I deliberately did not add

A few things would make the repository look larger without making it more useful, so I left them out:

- another format validator
- another baseline implementation
- hidden-score estimation
- leaderboard-query inversion
- a generic experiment logger
- a giant methods bibliography with little guidance
- a large model-training framework
- claims that local metric bottlenecks necessarily transfer to the hidden test set
- a giant biology glossary that would turn the guide into a textbook

The goal is to make a few specific jobs easier, not to maximize the number of folders or award submissions.
