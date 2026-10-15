<!-- BEGIN OPERATOR-ONLY (delete this block and the END marker before locking; codex_lock.py refuses while either marker is present)

Port checklist for converting a human pipeline into an agent run:
1. Remove hard-coded hold-out stages, genotypes and file names from the code. The agent may load only the files in the Data table below.
2. Remove human notes, comments with prior scores, and README sections that describe past results. Check the workspace and its git history for prior scores (grep for "score", "board", "rho" and the held-out stage names). The prelock audit in ../agent-prelock-audit/ is being built in parallel; run it when it exists. It is not present yet.
3. Make sure the brief and the prompt do not mention leaderboard positions or earlier run results.
4. Replace machine-specific absolute paths with the placeholders in this file.
5. Run ../agent-harness-lab/ first (`vec-agent-bench list`, then the dry-run tasks) with the same codex model and sandbox you will lock. Its tasks are not the real task and do not certify eligibility.
6. Install veckit at the pinned commit before locking, and check it with `{{SCORER_CHECK_COMMAND}}`. Do not change packages during the run.
7. Lock with codex_lock.py. Do not edit this brief after the lock.

END OPERATOR-ONLY -->

# Task brief

Run: `{{RUN_ID}}`. Task: `{{TASK_ID}}`. Board: `{{BOARD}}`. Stop by: `{{DEADLINE_UTC}}`.

## Your task

{{TASK_DESCRIPTION}}

You are working alone. No person will read your intermediate results or answer questions during the run. Choose the method yourself and carry it through to a prediction file.

## Data

The read-only inputs are under `{{DATA_ROOT}}`:

{{DATA_FILES_TABLE}}

Use only the files in this table, plus any external source you name in `out/method/SOURCES.md` with the stages it covers.

## What you may read and use

- The files in the Data table above, the workspace, and the scorer documentation in `{{SCORER_DIR}}`.
- Released training stages only, as the Data table marks them.
- External public data, pre-trained models and code, if their licences allow it and you record them in `out/method/SOURCES.md`. Say which stages each source covers.

## What you may not read or use

- Measured data from any held-out stage or genotype. For this task these are: `{{HELD_OUT_DESCRIPTION}}`.
- External data that is closer to a held-out stage than to the nearest released stage, or that falls inside the protected windows in rules section 10. If a source is near a boundary, do not use it; write the question in `out/method/SOURCES.md`.
- Any file that could hold earlier results: other run directories, lock directories, earlier prediction files, notes from earlier attempts, or leaderboard pages. Do not search the home directory or the parent directories of the workspace for such files.
- Credentials of any kind.

## Scores

You may score your own candidate predictions with veckit against the validation data in the Data table, and you may choose the best candidate among completed prediction files. You may not build a prediction from a score: no inverting a score map, no solving for a property of a target from scores, and no differencing scores across submissions. Trying a parameter, seeing how it scores, and trying another is allowed. If the Data table lists no validation data, do not score.

## Scorer

- veckit is pinned to GitHub main at commit `cc3859ab2a2305efc4544815d3f44f660efa77d4`, which is the version with the issue #7 fix (`git-main-cc3859a` in the scorer-versions registry). Check it with `{{SCORER_CHECK_COMMAND}}` before you rely on any number. Quote the variant name with any score you report.
- Run format checks freely. They report whether a file is well formed and say nothing about how it would score.

## Output

- Write each final prediction into `{{PREDICTIONS_DIR}}`, named as the board requires: `{{PREDICTION_FILENAME}}`. Write nothing else into that directory.
- Write `out/method/METHOD.md`: the approach in plain words, what each part does, and what you did not try. Define every term you use.
- Write `out/method/SOURCES.md`: every external source, its licence, the stages it covers, and how you used it.
- Finish with one short paragraph: which prediction file you chose and why.

## Working rules

- Do not install or upgrade packages. Do not edit this brief, the data, or anything outside the workspace.
- Do not write predictions anywhere except `{{PREDICTIONS_DIR}}`.
- Stay within the wall-clock budget. A run that is still working at the deadline is stopped and its last prediction is what gets packaged, so write a valid prediction early and improve it.
