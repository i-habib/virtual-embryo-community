# VEC Metric Lens

A board score is one number built from several metrics, each with a fixed weight. Metric Lens takes the metrics JSON that `veckit` writes and shows where your points come from. It also shows how many points each metric could still add if it reached its published validation ceiling, which tells you where the next points are.

Example, using the synthetic `example_t3.json` in this folder:

```bash
python vec_metric_lens.py --board T3:gata4 example_t3.json
```

Output:

```text
# VEC Metric Lens: `T3:gata4`

**Reconstructed public validation score: 66.51 / 100**

Anchors: built-in table, transcribed 2026-09-16. Weights and directions: built into `vec_metric_lens.py`.

> This explains a known validation metric vector. It is not a predictor of the hidden test score.

## Score breakdown

| Metric | Raw | Skill | Weight | Points | Points left |
|---|---:|---:|---:|---:|---:|
| de_score (DES / response gene recovery) | 0.18 | 0.558 | 30.0% | 16.73 | 13.27 |
| de_direction (DCS / response direction) | 0.1 | 0.529 | 25.0% | 13.21 | 11.79 |
| severity_slope (PSS / response magnitude) | -0.65 | 0.915 | 25.0% | 22.87 | 2.13 |
| mmd_u (MMD / cell-state distribution) | 0.018 | 0.638 | 12.0% | 7.65 | 4.35 |
| variogram (CSS / co-expression structure) | 0.011 | 0.754 | 8.0% | 6.03 | 1.97 |

## If one metric were fixed

For each row below, every other metric is held fixed. That one metric is moved to its published validation ceiling.

| Rank | Metric | Score after fix | Gain |
|---:|---|---:|---:|
| 1 | de_score | 79.78 | +13.27 |
| 2 | de_direction | 78.29 | +11.79 |
| 3 | mmd_u | 70.85 | +4.35 |
| 4 | severity_slope | 68.63 | +2.13 |
| 5 | variogram | 68.47 | +1.97 |

## A few cautions

- A model at every floor scores 50, and a model at every ceiling scores 100.
- Ceilings are empirical split-half estimates, not theoretical maxima. A metric beyond its ceiling gets skill 1.
- `scale_log_ratio` and `severity_slope` are scored on absolute value, because zero is best.
- A missing or NaN metric gets skill 0. In the fixed-metric table it is counted at its ceiling.
- Gains on this board do not guarantee gains on the hidden test target.
```

## How to read it

- **Raw** is the value `veckit` reported for that metric.
- **Skill** runs from 0 to 1. A metric at its published floor has skill 0.5, and a metric at its ceiling has skill 1.
- **Points** is the weight times the skill, scaled to 100. **Points left** is the difference from the metric's maximum.
- **If one metric were fixed** moves one metric at a time to its ceiling and keeps the rest as they are. The gain equals that metric's points left, so the table ranks where the points are. It does not say how hard each metric is to improve.

In this example, `de_score` has the most points left (13.27), so response gene recovery is worth the most on this board. `severity_slope` already contributes 22.87 of its 25.

## Input

- A `veckit` result with a top-level `metrics` object, or a bare JSON object that maps metric names to values.
- A board key: `T1:val`, `T2:embryo:val_interp`, `T2:heart:val_interp`, `T2:heart:val_extrap`, or `T3:gata4`.

Metrics that have no published anchor for the board are ignored. Missing or non-finite values count as skill 0.

Optional outputs:

```bash
python vec_metric_lens.py --board T2:heart:val_interp result.json --markdown report.md --json analysis.json
```

## Which veckit

Several `veckit` versions are in circulation, and they do not produce identical numbers. The PyPI 0.1.2 release also reports metrics that the board does not rank, such as `severity_ratio`. Metric Lens ignores any metric without an anchor, so those extra keys do not affect the output. The versions do differ on `occupancy_dice` for some inputs, so compare numbers only between runs from the same variant. To identify your install, run `which_veckit.py` in [`../scorer-versions/`](../scorer-versions/).

## Live anchors

The built-in anchors were transcribed from the evaluation pages on 2026-09-16 and matched value by value against the board contract, [`panels/index.json`](https://virtualembryo.ai/challenge/panels/index.json), on 2026-10-14. To use the contract directly, pass `--index` with a URL or a local path:

```bash
python vec_metric_lens.py --board T3:gata4 example_t3.json \
  --index https://virtualembryo.ai/challenge/panels/index.json
```

`--index` replaces the floors and ceilings for the requested board only. Weights and directions still come from this file, so a board can be explained only once its weights are in the `BOARDS` table. Every metric of that board must have anchors in the index; a gap is an error, not a fallback to the built-in values. Boards that appear in the index without weights here are listed on stderr.

## Tests

```bash
cd metric-lens
pytest -q
```

The tests check that published floors reconstruct to 50 and ceilings to 100 on every board, both for the built-in table and for anchors loaded from an index. They also cover clipping at ceiling, NaN handling, the absolute-value metrics, and the output format. To check the built-in table against a local copy of `index.json`, set `VEC_PANELS_INDEX` to its path before running `pytest`.

## Limits

Metric Lens only explains metric values you already have. It does not download hidden data, query the leaderboard, or predict hidden test scores. The ceilings are empirical, so a metric beyond its ceiling gets no extra credit. Use the table to decide where to look, and check the result on held-out data before relying on it.

Other community tools for this challenge include [VecBench](https://github.com/AJK0921/vecbench) and [VEC ScoreLens](https://github.com/cadentann/vec-scorelens). ScoreLens, as its README describes it, inspects gene-level and spatial differences from a local target, while Metric Lens focuses on the points available per metric on the published board.

Sources: [Task 1](https://virtualembryo.ai/challenge/evaluation?section=scoring&task=1), [Task 2](https://virtualembryo.ai/challenge/evaluation?section=scoring&task=2), [Task 3](https://virtualembryo.ai/challenge/evaluation?section=scoring&task=3), and the official [`veckit`](https://github.com/aristoteleo/veckit) scorer.

MIT licensed. Independent community utility.
