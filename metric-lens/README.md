# VEC Metric Lens

`veckit` gives you a vector of raw metrics. Metric Lens answers the bookkeeping question I kept wanting during debugging: **where are the weighted points coming from, and which weak metric is large enough to matter?**

```bash
python vec_metric_lens.py --board T3:gata4 veckit_result.json
```

It applies the published validation-board floors, ceilings, and weights, then reports each metric's normalized skill and score contribution. It also runs a simple counterfactual: hold every other metric fixed and move one metric to its published validation ceiling.

That counterfactual is only a prioritization aid. It does not say a metric is easy to improve, and it says nothing about transfer to the hidden target.

Supported public validation boards:

- `T1:val`
- `T2:embryo:val_interp`
- `T2:heart:val_interp`
- `T2:heart:val_extrap`
- `T3:gata4`

To save both report formats:

```bash
python vec_metric_lens.py \
  --board T2:heart:val_interp \
  result.json \
  --markdown report.md \
  --json analysis.json
```

The input can be a normal `veckit` result with a top-level `metrics` object or a bare JSON object of metric names and values.

## Scoring details

The tool follows the public validation mapping: the published floor maps to 0.5 skill, the empirical ceiling maps to 1.0, and values beyond the ceiling are clipped. `scale_log_ratio` and `severity_slope` are scored by absolute value because zero is best.

The tests check the parts most likely to drift or be mistranscribed:

```bash
cd metric-lens
pytest -q
```

For every supported board, published floor values must reconstruct to 50/100 and ceiling values to 100/100. There are separate checks for clipping and signed best-at-zero metrics.

The constants were transcribed from the official evaluation pages on **2026-09-16**. If the organizers change those anchors, this file needs updating.

Metric Lens never downloads hidden data or queries the leaderboard. It only explains metric values you already have.

Sources: [Task 1](https://virtualembryo.ai/challenge/evaluation?section=scoring&task=1), [Task 2](https://virtualembryo.ai/challenge/evaluation?section=scoring&task=2), [Task 3](https://virtualembryo.ai/challenge/evaluation?section=scoring&task=3), and the official [`veckit`](https://github.com/aristoteleo/veckit) scorer.

MIT licensed. Independent community utility.
