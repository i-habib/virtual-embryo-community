# Virtual Embryo for ML people

If your background is mostly normal ML, the first few minutes with this challenge are weird. You open an `.h5ad`, see a giant matrix, and it is tempting to think you are doing regression on cells.

You are not.

The cleanest way I found to think about the challenge is: **you are generating a new population of cells**. Sometimes those cells also need positions in 3D. In Task 3, the population should additionally reflect a genetic perturbation.

That one idea explains most of the evaluation.

## What is one example?

For Task 1, one measured cell is a gene-expression vector

\[
x_i \in \mathbb{R}^{G}.
\]

Put all cells from one embryo or stage together and you get

\[
X_t \in \mathbb{R}^{n_t \times G}.
\]

A row is a cell. A column is a gene. An entry is the released expression value for that gene in that cell.

The important part is that **the whole matrix is the object of interest**. The target is not one future vector.

It is useful to write a stage as a distribution

\[
X_t \sim p_t(x).
\]

and your prediction as another sample

\[
\hat X_t \sim q_\theta(x \mid \text{what you observed}).
\]

You do not need a probabilistic model for this notation to help. It is just a reminder that the scorer compares populations.

### There is no “same cell later”

This is probably the easiest mistake to make.

An E8.5 cell and an E9.5 cell are not an input-target pair. The measurement destroys the cell, the later experiment measures different cells, and development includes division and differentiation anyway.

So this picture is wrong:

\[
x_i^{(8.5)} \rightarrow x_i^{(9.5)}.
\]

A better picture is

\[
p_{8.5}(x),\; p_{9.5}(x) \rightarrow p_{10.5}(x).
\]

Once that clicks, things like optimal transport, changing mixture proportions, and distributional metrics stop feeling arbitrary.

## A little biology vocabulary

You do not need a developmental-biology course before trying a baseline. You do need enough vocabulary to know what the matrix means.

### Gene expression

A gene can be more or less active in a cell. The released matrix contains processed measurements of that activity. Treat those values as expression features, not raw molecule counts unless the source explicitly says otherwise.

### Cell state / cell type

Different cells run different programs. In ML terms, the population is strongly multimodal:

\[
p_t(x)=\sum_k \pi_k(t) p_t(x\mid k).
\]

Both pieces can change with development:

- \(\pi_k(t)\): how common state \(k\) is
- \(p_t(x\mid k)\): what cells in that state look like

A model can therefore have the correct global mean and still generate a terrible population.

### Pseudobulk

Average expression across cells:

\[
\bar x_t=\frac{1}{n_t}\sum_i x_i.
\]

This is useful and lossy.

For example, these populations can have the same average:

```text
50% [high gene 1, low gene 2]
50% [low gene 1, high gene 2]
```

and

```text
100% [medium gene 1, medium gene 2]
```

The mean cannot tell you that one population has two states and the other has one.

### Differential expression

A simple first approximation is the change in pseudobulk:

\[
\Delta = \bar x_{\text{target}}-\bar x_{\text{reference}}.
\]

Which genes move, which direction they move, and how much they move are all useful signals. The official metrics are more careful than this one equation, but it is enough intuition to start.

### AnnData

An `.h5ad` is mostly a container around the matrix and metadata.

```text
adata.X                    cells × genes
adata.var_names            gene names
adata.obs                  per-cell metadata
adata.obsm['spatial_3D']   xyz coordinates for spatial tasks
```

The [data-tour notebook](notebooks/virtual_embryo_data_tour.ipynb) opens the organizers' tiny public examples and shows these directly.

# Task 1: generate a later cell population

Task 1 gives you earlier developmental stages and asks for a later one.

A copy-last baseline says

\[
q(x)=p_{9.5}(x).
\]

That is bad biology, but a useful floor. It tells you what “development stops here” looks like.

A slightly less dumb baseline moves the mean:

\[
\Delta=\bar x_{9.5}-\bar x_{8.5},
\qquad
\hat x=x+\alpha\Delta.
\]

Now average expression can move in the right direction. But every cell is still pushed by the same vector.

Real development can do things that this has no way to represent:

- one state changes more than another
- proportions change
- one state branches into several
- new states appear

A useful progression is therefore:

```text
copy latest stage
    ↓
move the global mean
    ↓
move different states differently
    ↓
change state proportions
    ↓
generate continuous or new states
```

The score reflects both changing genes and the generated population itself. That is why “predict pseudobulk well” is only part of the problem.

# Task 2: now the cells have to form a tissue

Task 2 attaches a 3D coordinate to each cell:

\[
(x_i,c_i),
\qquad
x_i\in\mathbb R^{500},\; c_i\in\mathbb R^3.
\]

A useful mental model is a point cloud with biological features attached to each point.

There are several independent ways to fail.

**Good expression, bad geometry.** The cells are plausible but the tissue has the wrong shape or scale.

**Good global geometry, bad local biology.** The cloud looks right but the wrong expression states are next to each other.

**Good-looking coordinates in the wrong frame.** The embryos are not given in a shared global coordinate system. Absolute xyz MSE is a poor target when the evaluation intentionally ignores global translation and rotation.

There is also a subtle laterality issue. The public scorer's distance-based shape term is reflection-invariant, so mirroring an embryo can leave that component essentially unchanged. The [Task 2 Intuition Lab](../intuition-lab/README.md) makes this visible instead of leaving it buried in a metric definition.

The most useful T2 control in that lab is even simpler: keep the exact same point cloud and exact same expression rows, but randomly reassign which expression row sits at which point. Global geometry is unchanged while local biological organization is scrambled.

# Task 3: predict the effect of an intervention

Task 3 adds a knockout.

You see normal development and one observed perturbation, then have to generalize to another gene.

The useful object to think about is the response away from matched wild type:

\[
\Delta_{KO}\approx \bar x_{KO}-\bar x_{WT}.
\]

Do not read that as literal paired-cell subtraction. It is population-level intuition.

Why frame the problem this way? Because a mutant embryo still mostly looks like an embryo. A model can return something extremely similar to WT and still achieve high absolute expression correlation while missing nearly all of the actual knockout effect.

A few controlled mistakes make the distinction clearer:

\[
\hat\Delta=0
\]

No response.

\[
\hat\Delta=0.3\Delta
\]

Right general direction, phenotype too weak.

\[
\hat\Delta=-\Delta
\]

Responsive genes move the wrong way.

\[
\hat\Delta=P\Delta
\]

Right collection of effect sizes, wrong genes.

The [Task 3 Intuition Lab](../intuition-lab/task3_response_playground.ipynb) runs exactly these failures through the public scorer.

# A modeling ladder that is actually useful

Architecture names matter less than knowing what capability is missing.

## 0. Copy last / WT identity

Use it to prove your pipeline works. It has no model of development or perturbation.

## 1. Global mean shift

Estimate one average change vector and apply it to sampled cells.

This models “things change,” but every cell still changes the same way.

## 2. State-aware dynamics

Split cells using provided labels, clusters, or a learned latent representation.

For state \(k\), estimate something like

\[
\Delta_k=\mu_{k,t}-\mu_{k,t-1}
\]

and separately model mixture weights \(\pi_k(t)\).

Now states can move differently and their proportions can change.

## 3. Soft population matching / optimal transport

Instead of inventing hard cell correspondences, infer a soft coupling between stages.

Conceptually:

```text
early A ───────▶ later C
       └───────▶ later D

early B ───────▶ later E
```

This fits development naturally because mass can split across descendants.

The catch is extrapolation. A coupling explains transitions you observed. It does not automatically tell you how to continue beyond them.

## 4. Learned latent dynamics

Encode cells

\[
z=E(x)
\]

and learn time-conditioned dynamics

\[
z_{t+\Delta}=F(z_t,t,\Delta).
\]

Then decode.

This could be an ODE, flow model, VAE, diffusion model, transformer, or something simpler. The useful questions are more basic:

- does it generate diversity rather than one mean?
- can proportions change?
- can it create states not literally copied from the previous stage?
- does it have any reason to extrapolate sensibly?

For Task 2, ask the same questions about space.

## 5. Condition on the perturbation

For Task 3, add perturbation identity \(g\):

\[
q_\theta(x,c\mid t,g,\text{WT context}).
\]

One observed knockout is nowhere near enough to learn arbitrary gene effects from scratch. You need some transferable structure, such as gene-function priors, pretrained representations, regulatory information, or a model whose inductive bias can use the WT developmental context.

# Debug from the failure

This table is more useful than a list of fashionable architectures.

| What looks wrong? | What your method may be missing |
|---|---|
| mean expression change is wrong | basic temporal / perturbation shift |
| mean is good but cell-state score is poor | mixture changes or multimodal generation |
| cell states look right but covariance is bad | realistic within-state diversity / gene-gene structure |
| T2 molecular scores are good but shape is bad | explicit geometry model |
| T2 shape is good but neighborhoods are bad | coupling between state and position |
| T3 prediction looks almost exactly like WT | perturbation conditioning |
| T3 moves the right genes but too weakly | response-magnitude calibration |
| T3 changes lots of genes in the wrong direction | gene-specific response structure |

# Five traps worth remembering

**1. Cells are not paired across stages.** If your loss depends on row `i` matching row `i`, you probably invented a target that does not exist.

**2. A good mean can hide a terrible population.** This is why the challenge has distributional terms.

**3. Cell-type labels are useful scaffolding, not the submission.** You generate cells, not labels.

**4. Absolute T2 coordinates are not sacred.** Translation and rotation of the whole embryo are frame choices.

**5. Task 3 is about the response away from WT.** High mutant-state correlation can coexist with a useless perturbation prediction.

# What I would do before training anything large

1. Run the [data tour](notebooks/virtual_embryo_data_tour.ipynb).
2. Produce the simplest valid copy-last or WT-identity prediction and score it locally.
3. Run the [Intuition Lab](../intuition-lab/README.md) for the task you care about.
4. Make one small modeling change whose purpose you can state in one sentence.
5. Look at *which* metric moved, not only the weighted total.

By then you should be able to say something concrete like:

> I need a model that changes cell-state proportions without collapsing within-state diversity.

That is a much better architecture brief than “maybe diffusion.”

# Official references

Use the challenge site for anything contractual:

- [Tasks](https://virtualembryo.ai/challenge/tasks)
- [Evaluation](https://virtualembryo.ai/challenge/evaluation)
- [Rules](https://virtualembryo.ai/challenge/rules)
- [Public local scorer and mini examples](https://github.com/aristoteleo/veckit)

For submission plumbing, [`vec-community-kit`](https://github.com/xxx12e/vec-community-kit) already covers validation, simple baselines, pseudo-validation, first-submission setup, and Agent-track evidence. This guide is about the modeling problem instead.

Written against the public challenge materials available on 2026-09-16. If a rule or metric changes, the official site wins.
