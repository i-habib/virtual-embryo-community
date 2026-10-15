# Validation-to-test transfer for two-slot submissions

## Question

Each team designates two official submissions per board in the final phase. The test answers are hidden and there is no
feedback before the choice, so teams rank methods on the validation board. How well does a validation-like ranking carry
over to a test-like target, and which rule for picking two submissions loses the least? The study uses pseudo pairs built
from released stages. It does not use the official boards.

## Pair design

Both pseudo pairs have two input stages, so every trend-based candidate is defined on both sides.

| Pair | Input stages | Target | Step from last input (days) |
|---|---|---|---|
| `val` | E8.0, E8.25 | E8.75 | 0.5 |
| `test` | E8.25, E8.75 | E9.5 | 0.75 |

The real validation task predicts E10.5 from several earlier stages. The real test task predicts E12.5 from one more stage
than validation, with a longer step. The `test` pair mirrors that pattern (two inputs, longer step). The `val` pair gives the
validation side two inputs as well, so its trend estimates are not all zero. The first version used one input on the
validation side and was dropped, because 12 of its 16 candidates were identical to `copy_last`.

Stages are heart MERFISH on the 500-gene panel, each subsampled to 4000 cells with a fixed seed. Real steps are 1 day
(validation) and 2 days (test), so the pseudo steps are shorter.

## Candidates

Sixteen candidates, each returning a predicted stage:

- `copy_last`: the last input stage.
- `drift:a=`: last stage shifted by `a` times the per-day mean change over the last two inputs, times the step, clipped at 0.
- `composition:s=`: last-stage cells resampled so cell-type proportions follow the per-day log-proportion trend, scaled by `s`.
- `growth:s=`: coordinates scaled about their centroid by the per-day RMS-radius trend, scaled by `s`.
- `combo:`: composition plus drift, with and without growth.
- `degraded:`: drift or composition, with each cell moved a fraction `b` toward the per-gene mean of the predicted cells.

Scoring uses veckit at commit `cc3859a`, T2 heart, the last input stage as reference, and seeds 0, 1 and 2. Local anchors are
recomputed for each pair and seed: floor = `copy_last`, ceiling = a seeded split-half of the target. Skill is
`metric_skill` from `../metric-lens`, and the headline uses the eight T2 heart weights of `T2:heart:val_extrap`.

## How to run

```
uv pip install -p PYTHON "git+https://github.com/aristoteleo/veckit@cc3859ab2a2305efc4544815d3f44f660efa77d4" matplotlib pytest
export VEC_STAGE_DIR=/path/to/directory/with/released/stages
python prepare.py --config configs/heart_now.json   # subsample stages to work/heart_now
python score.py --config configs/heart_now.json     # one subprocess per job; resumes from results/scores.jsonl
python analyse.py --config configs/heart_now.json   # writes results/analysis.json and report.html
python -m pytest -q
```

Stage files are read in backed mode and only the subsampled rows are loaded. A job key includes a pair signature (stage
names, times, inputs, target, task, board, subsample size and seed), so changing a pair re-scores only that pair.

For 20 October, `configs/oct20_template.json` lists the pairs for the validation answers (heart, T1, and T3 knockout pairs).
Its paths are placeholders and must be filled in first. `analyse.py` compares one validation and one test pair per run, so
T1 is run with `--val-pair t1_val --test-pair t1_test`, and the T3 knockout pairs are scored but not compared here.

## Results (heart_now, two-input validation pair)

Full table: `report.html`. Raw values: `results/analysis.json`.

Top three by headline (mean over 3 seeds):

- Validation: `composition:s=0.5` 53.54, `composition:s=1.0` 51.13, `copy_last` 50.00.
- Test: `composition:s=1.0` 54.90, `composition:s=0.5` 52.77, `degraded:composition=1.0+shrink=0.2` 50.17.

The test winner `composition:s=1.0` ranks 2nd of 16 on validation, so a top-2 pick by validation includes it.
`copy_last` scores 50.00 on test and ranks 4th. Ranks are 1 = best.

Rank agreement across the 16 candidates: Spearman 0.879 (seed-bootstrap 95% interval
0.812 to 0.921); Kendall tau-b 0.717
(0.667 to 0.783). The intervals cover seed resampling only, not the choice of
pseudo pair or candidate set.

Two-slot regret, in headline points (500 draws; "perturbed" resamples seeds and drops 20% of candidates per draw):

| Rule | Full set | Perturbed mean | Perturbed sd | Perturbed 5th to 95th |
|---|---:|---:|---:|---:|
| R1 top-2 by validation | 0.00 | 0.01 | 0.04 | 0.00 to 0.00 |
| R2 top-1 plus best of another family | 2.13 | 1.42 | 1.03 | 0.00 to 2.46 |
| R3 top-1 plus most dissimilar of top-5 | 2.13 | 1.32 | 1.04 | 0.00 to 2.46 |

R1's two picks are both composition candidates, which include the best test candidate, so its full-set regret is zero.
Its perturbed mean is nonzero because dropping a composition candidate in a draw removes that option.
With 20,000 draws the perturbed means are about 0.01 (R1), 1.38 to 1.41 (R2) and 1.38 to 1.39 (R3), so the 500-draw
values are within sampling error.

Distinct validation predictions: 12 expression matrices among 16 candidates. Four candidates repeat an expression matrix
already produced by another candidate, because growth changes coordinates only: the two growth candidates repeat
`copy_last`, and the two combo-with-growth candidates repeat their combo without growth. Those are the expected ties. The 16
validation headlines are all distinct, so no two candidates tie on the validation headline. The test side has 12 expression
matrices by the same count.

Checks: an independent script recomputed all 32 candidate headline means and both rank correlations from
`results/scores.jsonl`, with zero difference. An independent Monte Carlo reproduces the regret means.

## Limits

- One pseudo pair per side, heart only, with two input stages each. Steps are shorter than the real ones (0.5 and 0.75 days
  against 1 and 2 days).
- Candidates are shifts, resamplings and rescalings. Real submissions are learned models.
- Stages are subsampled to 4000 cells, and there are 3 seeds, so seed noise is poorly estimated.
- Degraded controls shrink each cell toward the per-gene mean of the predicted cells. This is one reading of "shrunk toward
  the population mean".
- Anchors come from split-half scores within one pseudo target, not from the organisers' ceilings.
- Expression fingerprints ignore coordinates, so growth-only differences appear as expression ties.

## Files

- `configs/`: pair definitions. Paths use environment variables.
- `prepare.py`, `stages.py`, `config.py`: subsampling, stage files and signatures.
- `methods.py`: candidate families. `worker.py`: one scoring job. `score.py`: cached driver.
- `analyse.py`: anchors, headlines, rank statistics, rules, figures and report.
- `results/scores.jsonl`: one line per job, with veckit metrics and pseudobulk. The `meta.target_source` field of the
  first 102 lines was rewritten from an absolute path to a relative stage name after the run. No metric changed.
- `tests/`: 33 tests on synthetic data, including one worker job through veckit.
- Related folders: [../history-rescore/](../history-rescore/) and [../test-phase-switchover/](../test-phase-switchover/).
