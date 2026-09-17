# Task 3 response playground

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/i-habib/virtual-embryo-community/blob/main/t3-response-playground/t3_response_playground.ipynb)

Task 3 asks you to predict what changes when a gene is knocked out. The tricky part is that a mutant embryo can still look very similar to wild type if you compare absolute expression. A model can therefore look superficially reasonable while completely missing the actual **WT → mutant response**.

This notebook makes that failure mode concrete.

It starts with the small matched wild-type and Mab21l2 knockout examples that the organizers already publish with `veckit`. Because the Mab21l2 answer is known, we can deliberately build predictions that are wrong in one simple way at a time and watch the official metrics react.

The notebook tries:

- no response at all
- 25%, 50%, 100%, 150%, and 200% of the known pseudobulk response
- the correct response with the sign reversed
- the same response values shuffled onto the wrong genes

This is not meant to produce a good competition submission. It is a small experiment for building intuition about the scorer and debugging a real model later.

## Run it

Open [`t3_response_playground.ipynb`](t3_response_playground.ipynb) in Colab or Jupyter and run it from top to bottom.

The notebook installs the public scorer and downloads only two small files from the organizers' `veckit` repository:

- `sample_wt.h5ad`
- `sample_mab21l2_ko.h5ad`

No challenge login or hidden data is needed.

The example files contain only about 150 cells, so the notebook is fast. They are **not large enough to be valid competition submissions**. For a less noisy version of the same experiment, replace them with the full released Mab21l2 training knockout and matched WT files.

## The experiment in one equation

Let

```text
known response = mean(Mab21l2 KO) - mean(WT)
```

Then the simple response-strength probes are

```text
prediction = WT + α × known response
```

where `α = 0` means “do nothing,” `α = 1` matches the known pseudobulk response, and values above or below 1 make the response too strong or too weak.

This is intentionally not a realistic generative model. Keeping the construction simple makes it much easier to tell *why* a metric moved.

## What to look for

**Did I move the right genes?**  
DES should care about recovering the genes that actually respond to the knockout.

**Did I move them in the right direction?**  
DCS should punish a response whose signs are reversed even if its overall magnitude looks plausible.

**Was the response too weak or too strong?**  
`severity_slope` is meant to separate getting the direction roughly right from getting the size of the response right.

**Did I preserve a believable cell population?**  
MMD and the variogram/CSS metric look at the single-cell distribution and co-expression structure, not just the average response.

The notebook also plots ordinary pseudobulk correlation next to the response-sensitive metrics. That comparison is the main reason the notebook exists: a high absolute-state correlation does not necessarily mean the knockout effect was modeled correctly.

## Using it to debug your own model

Once the toy experiment makes sense, add your model's local prediction as another row in the same table.

Then compare its pattern of metrics with the controlled failures. For example:

- good DCS but poor severity may mean the model moves genes in roughly the right direction but gets the response size wrong
- poor DCS with a decent absolute correlation can indicate that the model mostly reproduced the wild-type state
- decent response metrics but poor MMD/CSS can mean the average shift looks right while the generated cell population is unrealistic

Those are hypotheses, not diagnoses. The point is to give you a more concrete starting place than staring at five unrelated numbers.

## A note on noise

The bundled samples are tiny. Do not expect every curve to be perfectly smooth or monotonic. Distributional metrics in particular can bounce around with so few cells.

The notebook is meant to show qualitative behavior quickly. Use the full released training pair when you want a more stable diagnostic.

## Sources

- [Task 3 description](https://virtualembryo.ai/challenge/tasks/perturbation)
- [Task 3 scoring](https://virtualembryo.ai/challenge/evaluation?section=scoring&task=3)
- [`veckit`](https://github.com/aristoteleo/veckit)

MIT licensed. Independent community notebook, not an official Challenge resource.
