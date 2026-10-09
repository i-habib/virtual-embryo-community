# Virtual Embryo for ML people

If your background is mostly normal ML, the first few minutes with this challenge are weird. You open an `.h5ad`, see a giant matrix, and your regression instincts kick in.

The useful mental model is simpler: **generate a future population of cells**. Task 2 also asks where those cells sit in tissue. Task 3 asks how the population changes under a genetic perturbation.

That framing explains most of the evaluation and rules out several bad modeling ideas immediately.

## Stages and splits

| Task | Train | Validation | Hidden test |
|---|---|---|---|
| T1, single-cell RNA (32,285 genes) | E8.5, E9.5 | E10.5 | E12.5 |
| T2 heart (MERFISH panel, 500 genes) | E8.25, E8.75, E9.5 | E8.5 (interpolation), E10.5 (extrapolation) | E12.5 (extrapolation) |
| T2 embryo (MERFISH panel, 500 genes; 498 on the validation board) | E6.75, E7.25, E8.0 | E7.5 | E7.75 |
| T3, knockouts (MERFISH panel, 500 genes) | Mab21l2 KO at E9.5 | Gata4 KO at E8.75 | beta-catenin KO at E8.75 |

Task 3 also releases wild-type references at E8.75 and E9.5. Each board's ordered gene list is downloadable from the [data page](https://virtualembryo.ai/challenge/data). From 20 October 2026, when the test phase starts, validation answers are released as training data. Source: [data page](https://virtualembryo.ai/challenge/data) and [challenge page](https://virtualembryo.ai/challenge).

## What is one example?

For Task 1, one measured cell is a gene-expression vector

\[
x_i \in \mathbb{R}^{G},
\]

where \(G = 32{,}285\) is the number of genes in the whole transcriptome.

Put the cells from a stage together and you get

\[
X_t \in \mathbb{R}^{n_t \times G}
\]

with the same \(G = 32{,}285\) for Task 1.

A row is a cell. A column is a gene. An entry is the released expression value for that gene in that cell.

The whole matrix is the prediction object. It helps to write a developmental stage as a distribution

\[
X_t \sim p_t(x)
\]

and a prediction as another sample

\[
\hat X_t \sim q_\theta(x \mid \text{earlier data}).
\]

You do not need a probabilistic model for this notation to be useful. It is just a reminder that the scorer compares populations rather than paired rows.

### There is no “same cell later”

An E8.5 cell and an E9.5 cell are different measured cells. The assay destroys the cell, later experiments sample other cells, and development includes division and differentiation.

So there is no target like

\[
x_i^{(8.5)} \rightarrow x_i^{(9.5)}.
\]

The object you actually observe is closer to

\[
p_{8.5}(x),\; p_{9.5}(x) \rightarrow p_{10.5}(x).
\]

This is why soft population matching, changing mixture proportions, and distributional metrics show up naturally.

## Enough biology vocabulary to start

### Gene expression

A gene can be more or less active in a cell. The released matrix contains processed measurements of that activity. Do not silently treat those values as raw molecule counts. In particular, arithmetic on log-normalized values is a modeling convenience rather than a literal transcript-count operation.

The released values are natural-log log1p of counts per 10,000 (CP10k): each value is \(\ln(1 + 10^4 \cdot \text{count}/\text{total})\), where the total is that cell's summed counts over the gene set used by the task. For Task 1 that set is all 32,285 genes. For Tasks 2 and 3 it is only the panel genes. The measured evidence for this choice is in [NORMALISATION.md](../panel-normalise/NORMALISATION.md). To get integer counts back from Task 1 files, see [count-recovery](../count-recovery/).

### Cell state and cell type

Cell populations are strongly multimodal. A rough mixture view is

\[
p_t(x)=\sum_k \pi_k(t) p_t(x\mid k).
\]

Both the mixture weights \(\pi_k(t)\) and the within-state distributions can change during development. A model can therefore get the global mean right while producing a biologically silly population.

### Pseudobulk

Average expression across cells is

\[
\bar x_t=\frac{1}{n_t}\sum_i x_i.
\]

It is useful and very lossy. A 50/50 mixture of two opposite cell states can have the same average as one homogeneous medium state. That is the easiest example of why a good mean is not enough.

### Differential expression

A first approximation to a developmental or perturbation response is

\[
\Delta = \bar x_{\text{target}}-\bar x_{\text{reference}}.
\]

Which genes move, which direction they move, and how strongly they move are distinct pieces of information. The official metrics are more careful, but this is enough intuition for debugging.

### AnnData

An `.h5ad` is mostly a matrix plus metadata:

```text
adata.X                    cells × genes
adata.var_names            gene names
adata.obs                  per-cell metadata
adata.obsm['spatial_3D']   xyz coordinates when the VEC object is spatial
```

The [data-tour notebook](notebooks/virtual_embryo_data_tour.ipynb) opens the organizers' public mini examples and shows these fields directly.

# Task 1: generate a later population

A copy-last baseline uses the latest observed population as the future prediction:

\[
q(x)=p_{9.5}(x).
\]

It is a useful floor because its failure mode is obvious: development stops.

A slightly better educational baseline moves the mean

\[
\Delta=\bar x_{9.5}-\bar x_{8.5},
\qquad
\hat x=x+\alpha\Delta.
\]

That can move aggregate expression in a sensible direction, but every cell receives the same shift. It cannot naturally handle state-specific changes, branching, new states, or changing proportions.

The next useful step is usually state-aware. Estimate different motion for different cell states or neighborhoods in a learned latent space, and model the population weights separately. After that, methods such as optimal transport or learned generative dynamics become attractive because they can represent soft transitions and continuous state changes without inventing one-to-one cell identities.

One warning about optimal transport: a coupling between observed stages explains how mass could move **between those stages**. It does not automatically solve extrapolation beyond the last observed time point.

# Task 2: expression attached to tissue geometry

Task 2 gives each cell a coordinate

\[
(x_i,c_i),
\qquad
x_i\in\mathbb R^{G},\; c_i\in\mathbb R^3,
\]

where \(G = 500\) is the size of the MERFISH gene panel used in Tasks 2 and 3 (498 genes on the embryo validation board).

I think of this as a point cloud with biological features attached to the points.

Two failures matter immediately. The global tissue shape can be wrong even when expression looks plausible, or the global shape can be right while the wrong cell states occupy the wrong neighborhoods.

There is also a coordinate-frame trap. Embryos are not supplied in one globally registered xyz frame, so naive absolute-coordinate regression can optimize an arbitrary orientation. Translation and proper rotation should be treated as frame choices when reasoning about the public shape metrics.

The public scorer had an implementation issue here, now fixed. In controlled tests, some **proper rigid rotations of the exact same point cloud** received a sliced-Wasserstein and occupancy-Dice penalty. A 72-angle sweep plus 50 random SO(3) rotations traced the failure to arbitrary SVD signs during PCA canonicalization: opposite-handed canonical frames failed because the downstream alignment only searches determinant-+1 sign flips. The reproducer is in the [Task 2 Intuition Lab](https://github.com/i-habib/virtual-embryo-community/tree/main/intuition-lab). The bug was reported as [`veckit#7`](https://github.com/aristoteleo/veckit/issues/7) and fixed upstream by [PR #9](https://github.com/aristoteleo/veckit/pull/9), merged 2026-10-02. Older pinned veckit commits, such as 46d41e6 used by the Intuition Lab notebooks, predate the fix and can still show the penalty.

Separately, a mirrored embryo can score the same as the original. This is the laterality issue the challenge FAQ describes.

The most useful modeling control is simpler: hold the point cloud fixed and randomly reassign expression rows to coordinates. Shape is unchanged, while local biological organization is destroyed. If your method fails that distinction, better geometry alone will not fix it.

# Task 3: predict a perturbation response

Task 3 adds a knockout. You see WT development and one observed perturbation, then generalize to another gene.

A useful summary is the response away from matched WT

\[
\Delta_{KO}\approx \bar x_{KO}-\bar x_{WT}.
\]

This is population-level intuition, not paired-cell subtraction.

The reason to think in responses is practical. A mutant embryo still shares most of its expression program with WT. Copying WT can therefore achieve surprisingly high absolute expression correlation while missing the knockout effect.

Controlled failures make this concrete:

\[
\hat\Delta=0
\]

means no response,

\[
\hat\Delta=0.3\Delta
\]

gets the direction roughly right but makes the phenotype too weak, and

\[
\hat\Delta=-\Delta
\]

moves responsive genes the wrong way.

The [Task 3 Intuition Lab](https://github.com/i-habib/virtual-embryo-community/blob/main/intuition-lab/task3_response_playground.ipynb) scores those cases directly.

There is a bigger modeling issue that is easy to miss: **one observed knockout does not identify a general gene-to-phenotype function**. Challenge data alone give almost no supervision over perturbation identity. A serious T3 model therefore needs transferable structure from somewhere else, such as gene-function annotations, regulatory priors, pretrained representations, or a strong mechanistic inductive bias. Any external data still have to satisfy the challenge rules and be disclosed.

# What should I actually try?

I would use a short capability ladder rather than start with architecture names.

**1. Identity / copy-last.** Get the complete pipeline working and establish the trivial floor.

**2. State-aware shifts and mixture changes.** Let different cell states move differently and allow their proportions to change. This is the first baseline that addresses the obvious weakness of a global mean shift.

**3. Soft or learned population dynamics.** Use OT, latent dynamics, flows, diffusion, or another generative model only when you can name the missing capability it supplies: continuous transitions, new states, realistic diversity, or extrapolation.

A generic latent version looks like

\[
z=E(x), \qquad z_{t+\Delta}=F(z_t,t,\Delta),
\]

followed by a decoder. For Task 2 the dynamics also need a meaningful treatment of space.

**4. Perturbation conditioning.** For Task 3, condition on gene identity or gene representation and test whether the model predicts a response away from WT rather than merely reconstructing WT-like embryos.

The architecture can be fancy later. First make sure it can express the failure mode you are trying to fix.

# Debug from the failure

| What looks wrong? | What your method may be missing |
|---|---|
| mean expression change is wrong | basic temporal or perturbation shift |
| mean is good but population score is poor | mixture changes or multimodal generation |
| state mixture looks right but covariance is bad | realistic within-state diversity / gene-gene structure |
| T2 molecular scores are good but shape is bad | explicit geometry model |
| T2 shape is good but neighborhoods are bad | coupling between state and position |
| T3 prediction stays close to WT | perturbation conditioning |
| T3 moves the right genes but too weakly | response-magnitude calibration |
| T3 changes genes in the wrong direction | gene-specific response structure |

# Before training anything large

Run the [data tour](notebooks/virtual_embryo_data_tour.ipynb), make the simplest valid baseline, and then break it deliberately with the [Intuition Lab](https://github.com/i-habib/virtual-embryo-community/tree/main/intuition-lab). After each modeling change, inspect which metric moved rather than only the weighted total.

You should end up with a sentence like:

> I need a model that changes cell-state proportions without collapsing within-state diversity.

That is a much better architecture brief than “maybe diffusion.”

# Official references

Use the challenge site for anything contractual:

- [Tasks](https://virtualembryo.ai/challenge/tasks)
- [Evaluation](https://virtualembryo.ai/challenge/evaluation)
- [Rules](https://virtualembryo.ai/challenge/rules)
- [Public local scorer and mini examples](https://github.com/aristoteleo/veckit)

For submission plumbing, the [`vec-community-kit`](https://github.com/xxx12e/vec-community-kit) community kit covers validation, simple baselines, pseudo-validation, first-submission setup, and evidence packaging for the Agent track. The Agent track is the challenge track for methods produced by coding agents or LLM-driven evolutionary systems. This guide focuses on what the prediction object means and what capabilities a model needs.

Written against the public challenge materials available on 2026-10-08. If a rule or metric changes, the official site wins.
