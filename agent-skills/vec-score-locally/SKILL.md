---
name: vec-score-locally
description: Scores a prediction locally with the pinned veckit scorer at commit cc3859ab2a2305efc4544815d3f44f660efa77d4, confirms the installed variant, and turns the metrics into board points with metric-lens. Use when comparing candidate predictions before choosing what to upload, or when a local number must be matched to a board.
---

# Score a prediction locally

The local scorer helps choose among predictions. It does not compute a board score, and the board is the only official number. Rules section 10 (https://virtualembryo.ai/challenge/rules): "Returned scores may be used to choose among predictions, not to compute them."

Never score against held-out data. Targets are allowed only when the rules allow them: pseudo-splits built from training stages, or validation answers after they are released on 20 October 2026. Never use a test target. The rules also forbid recovering held-out values by inverting the skill map or differencing scores across submissions, so do not do either.

## Steps

1. Install the pinned scorer in the environment you will use:

   ```bash
   pip install "git+https://github.com/aristoteleo/veckit@cc3859ab2a2305efc4544815d3f44f660efa77d4"
   ```

   Its `pyproject.toml` still says 0.1.1, so `pip show veckit` cannot tell it apart from the PyPI release.

2. Confirm the variant from the repository root:

   ```bash
   python scorer-versions/which_veckit.py
   ```

   The result must read `result: git-main-cc3859a`. If it reports `pypi-0.1.2` or any other variant, stop. Versions disagree on `occupancy_dice` and on the metrics the board does not rank. See [scorer-versions](../../scorer-versions/README.md).

3. Score the file. Use the task flags that match the board:

   ```bash
   veckit --task T2 --setting heart --input PRED.h5ad --target TARGET.h5ad --reference REF.h5ad --seed 0 --out result.json
   veckit --task T1 --input PRED.h5ad --target TARGET.h5ad --reference REF.h5ad --seed 0 --out result.json
   veckit --task T3 --input PRED.h5ad --target TARGET.h5ad --wt WT.h5ad --seed 0 --out result.json
   ```

   `--reference` is the earlier stage that `de_score` and `de_direction` measure change against. `--wt` plays that role for T3. Check that `result.json` has a top-level `metrics` object.

4. Convert the metrics to board points:

   ```bash
   python metric-lens/vec_metric_lens.py --board T2:heart:val_interp result.json --markdown report.md
   ```

   The table shows the points each metric contributes and the points it could still add. Keep the board key in the file name, because the anchors differ by board.

5. Record the variant, the seed, the target file name and the metric values together. A number without the variant is not comparable.

## Checks before comparing numbers

- Compare only files scored with the same variant, the same seed and the same target. Metric Lens says the same thing about variants.
- Pseudo-target scores can rank candidates but cannot predict the hidden score. Metric Lens's own cautions say the same. A metric above its ceiling gets no extra credit.
- Do not tune a model to a single local number. Choose among candidates that differ in structure, then confirm them on another target.

## Related

- [vec-check-submission](../vec-check-submission/SKILL.md) for the format checks that come before scoring.
- [vec-final-phase](../vec-final-phase/SKILL.md) for rescoring the team's history once the validation answers are released.
- Official evaluation pages: https://virtualembryo.ai/challenge/evaluation, with the board anchors in https://virtualembryo.ai/challenge/panels/index.json.
