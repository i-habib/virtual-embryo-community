# VEC Metric Lens

When you run the Virtual Embryo scorer locally, you get several metric values back. Those values are useful, but they are not on the same scale. A small MMD value and a small DCS value mean completely different things, and each metric contributes a different amount to the final score.

Metric Lens answers a simpler question:

> **Where are my points actually coming from, and which weak metric has enough weight to matter?**

Give it the JSON from `veckit`. It applies the public validation-board floor, ceiling, and weights, then produces a readable score breakdown.

It also runs one simple what-if check for each metric: if every other metric stayed exactly the same and this one metric reached the published validation ceiling, how much would the total score change?

That is useful for deciding what to inspect next. It is **not** a claim that the metric is easy to fix, and it is not a prediction of hidden-test performance.

## Example

```bash
python vec_metric_lens.py --board T3:gata4 veckit_result.json
```

To save the report:

```bash
python vec_metric_lens.py \
  --board T2:heart:val_interp \
  result.json \
  --markdown report.md \
  --json analysis.json
```

The tool currently knows about these published validation boards:

- `T1:val`
- `T2:embryo:val_interp`
- `T2:heart:val_interp`
- `T2:heart:val_extrap`
- `T3:gata4`

## What you get back

The report has two parts.

First, it shows each metric's raw value, its normalized challenge skill, and the number of score points it currently contributes. This is mainly bookkeeping, but it makes the weighting visible.

Second, it ranks the “what if I fixed only this metric?” cases. For example, if improving DCS all the way to the public ceiling could only recover 1.8 points but improving severity could recover 9.4, that is useful context before spending time tuning the wrong failure mode.

Again, this is only about the **published scoring rule on the board you selected**. A metric that looks like the local bottleneck can still fail to transfer to the hidden target.

## Input format

The normal input is the JSON emitted by `veckit`:

```json
{
  "meta": {"task": "T3"},
  "metrics": {
    "de_score": 0.18,
    "de_direction": 0.10,
    "severity_slope": -0.65,
    "mmd_u": 0.018,
    "variogram": 0.011
  }
}
```

A plain JSON object containing only the metric names and values also works.

## How the score reconstruction works

For each metric, the challenge publishes a **floor** and an empirical **ceiling**.

- The floor is the reference performance level. It maps to 0.5 skill.
- The ceiling is estimated by splitting real target cells into two halves and comparing them. It maps to 1.0 skill.
- Values worse than the floor receive less than 0.5 skill.
- Values better than the empirical ceiling are clipped at 1.0.

Metric Lens uses that same public mapping, then applies the published weights.

Two metrics, `scale_log_ratio` and `severity_slope`, are best when they are near zero, so the tool scores their absolute value rather than treating positive and negative values differently.

## Checks

The implementation has small tests for the parts most likely to go wrong:

```bash
cd metric-lens
pytest -q
```

For every supported board, the tests verify that:

- all published floor values reconstruct to exactly **50/100**
- all published ceiling values reconstruct to exactly **100/100**
- a metric that beats the empirical ceiling is clipped correctly
- the sign of a “best at zero” metric does not change its score

The floor/ceiling constants were transcribed from the official evaluation pages on 2026-09-16. If the challenge changes those values, this file needs to be updated.

## What this does not do

Metric Lens does not download challenge data, query the leaderboard, estimate hidden labels, or infer anything about a held-out target. It is only an explainer for metric values you already have.

The challenge rules prohibit using leaderboard feedback to reverse-engineer hidden targets. Do not use this tool as part of that kind of procedure.

## Sources

- [Task 1 scoring](https://virtualembryo.ai/challenge/evaluation?section=scoring&task=1)
- [Task 2 scoring](https://virtualembryo.ai/challenge/evaluation?section=scoring&task=2)
- [Task 3 scoring](https://virtualembryo.ai/challenge/evaluation?section=scoring&task=3)
- [`veckit`](https://github.com/aristoteleo/veckit)

MIT licensed. Independent community utility, not an official Challenge tool.
