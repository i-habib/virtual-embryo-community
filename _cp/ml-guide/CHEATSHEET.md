# Virtual Embryo cheat sheet for ML entrants

## The central idea

You are **not** predicting one label per input cell.

You are generating a **new population of cells** for a held-out time or perturbation.

There is no assumption that predicted cell 17 corresponds to real cell 17.

## What is a cell here?

For expression data, one cell is a vector

\[
x \in \mathbb{R}^{G},
\]

where each coordinate is the log-normalized expression of one gene.

A stage is therefore a set or empirical distribution of cells

\[
X_t = \{x_1,\ldots,x_n\}.
\]

Task 2 and Task 3 additionally attach a 3D coordinate to each cell.

## Tasks

| Task | Given | Predict | Mental model |
|---|---|---|---|
| T1 | earlier scRNA-seq stages | later cell population, expression only | future distribution generation |
| T2 | earlier 3D MERFISH stages | later expression + 3D coordinates | future tissue generation |
| T3 | WT development + one observed KO | a different knockout | conditional intervention generation |

## What the scorer is trying to stop you from faking

**T1**
- correct average change but collapsed population
- plausible cells with wrong mixture of states
- right marginals but wrong gene-gene structure

**T2**
- good expression with a nonsense tissue shape
- plausible shape with the wrong local neighborhoods
- correct coordinates in an arbitrary global frame but wrong relational structure

**T3**
- simply copying the matched wild type
- moving the right genes in the wrong direction
- getting direction right but perturbation magnitude wrong

## Modeling ladder

0. Copy the last observed stage / WT
1. Global pseudobulk shift
2. Cell-state-aware shifts and mixture proportions
3. Distribution matching / optimal transport across stages
4. Latent dynamics over developmental time
5. Joint conditional generative model over time, state, coordinates, and perturbation

The point of the ladder is not that level 5 is automatically best. Each step fixes a specific failure of the previous one.

## Five traps

1. **Cells are not tracked through time.** Do not train as if cell i at E8.5 maps to cell i at E9.5.
2. **The mean is not the population.** Repeating one average cell can look decent on mean-based metrics and fail distribution metrics.
3. **Cell-type labels are not your submission.** The scorer types submitted cells with its own frozen classifier.
4. **T2 coordinates live in per-embryo local frames.** Absolute xyz regression across stages is the wrong target.
5. **T3 cares about the WT → mutant response.** A mutant can still look very similar to WT in absolute expression.

## First modeling question to ask

Before choosing an architecture, ask:

> **Which part of the target distribution does my current method have no mechanism to represent?**

That usually points to a better next experiment than “use a bigger model.”
