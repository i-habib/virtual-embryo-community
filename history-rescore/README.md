[中文](README.zh.md)
# history-rescore

Rescores every file a team has submitted, locally, once the validation answers are released.

The validation answers for E10.5 T1, E7.5 embryo, E8.5 heart interpolation, E10.5 heart extrapolation and Gata4 KO are released on 20 October 2026, when the test phase starts. Until then a team sees one headline number per submitted file. With the answers in hand, the team can rescore its whole history on its own machine. That gives three things:

1. the per-metric breakdown of every file the team has submitted, not only its headline;
2. how closely a local rescoring reproduces the board's number, board by board;
3. which of the team's own local validation signals tracked the board.

These are the inputs for choosing the two final test submissions. The test phase gives no feedback, so the history is the only evidence available.

Related tools: [vec_local_score](https://github.com/xxx12e/vec-community-kit) (in vec-community-kit) implements the scorer protocol on pseudo splits, and this tool does not repeat that scope. [vecbench](https://github.com/AJK0921/vecbench) rank-correlates local holdouts with the board, and this tool applies the same kind of rank check to the files a team has already submitted.

## Requirements

- Python 3.9 or newer, with `numpy`, `scipy`, `anndata` and `pytest`.
- `veckit` at the pinned commit the tool was built against:

  ```bash
  pip install "git+https://github.com/aristoteleo/veckit@cc3859a" anndata numpy scipy pytest
  ```

- The `metric-lens` folder from the same repository, next to this folder. The headline formula and the weights come from it.

## The three steps

### 1. Export the submissions table

Open https://virtualembryo.ai/challenge/account/submissions, expand the list until every row is shown, and paste `export_submissions.js` into the browser console. The script keeps the scored rows and downloads `submissions.csv` with the columns `submitted,task,file,board,board_score`.

The `board` column is a guess made from the task and the file name:

- `T1` gives `T1:val`;
- `T2 · embryo` gives `T2:embryo:val_interp`;
- `T2 · heart` gives `T2:heart:val_interp` if the file name mentions E8.5 or interp, and `T2:heart:val_extrap` if it mentions E10.5 or extrap;
- `T3` gives `T3:gata4`.

Rows where the guess is blank, including every heart file whose name mentions both or neither, must be filled in by hand before the next step. Use the key from the panel index for test-phase boards, because the script does not guess those.

### 2. Write boards.json once the files are out

`boards.json` maps each board key to the released files. Paths are relative to the file itself.

```json
{
  "T1:val": {"target": "released/T1_E10.5.h5ad", "reference": "released/E9.5_RNA.h5ad"},
  "T2:heart:val_extrap": {"target": "released/heart_E10.5.h5ad", "reference": "released/heart_E9.5.h5ad", "setting": "heart"},
  "T3:gata4": {"target": "released/gata4_ko.h5ad", "wt": "released/wt.h5ad"}
}
```

- `reference` is the stage the board's copy-last floor comes from, which the change is measured against (for `T1:val` that is E9.5; its `ref_cells` in the index, 1,706, is 10% of E9.5's 17,057 cells). For T3 use `wt`.
- `setting` is `heart` or `embryo` for T2.
- `target_is_working_copy` and `reference_is_working_copy` (default `false`): set to `true` if the released file is already the 10% working copy, so that it is not subsampled a second time.
- `weights_from` is needed only when a test-phase board does not match a validation board by name.
- `fraction` (default 0.1) is the subsample rate of the board protocol. Leave it at the default for real boards.

### 3. Run

```bash
python rescore.py \
  --submissions submissions.csv \
  --search ~/Downloads/vec-files ~/Projects/vec-runs \
  --boards boards.json \
  --protocol board --seeds 3 \
  --out results/
```

Run it once with `--protocol board` and once with `--protocol full`, and compare the two reports.

Options:

- `--search` takes one or more folders. Each submitted file is found by its name, recursively.
- `--prefer DIR` decides a clash when two different files share a name. Without it the newest file is used and a warning is written.
- `--index FILE` uses a saved copy of the panel index. Without it the live index is downloaded. The tool reads anchors and cell limits from the index, so test-phase boards need no code change.
- `--local-validator FILE` takes a CSV with the columns `file,board,value`, such as one of the team's own validation metrics, and adds its rank agreement with the board and with the local headline.
- `--guess-blank` fills blank board cells with the export rules and warns for each guess. Check the guesses by hand.
- `--keep-work` keeps the derived 10% working copies in `results/work/`. They are deleted by default.

## Protocols

- `board` follows the protocol described on the [data page](https://virtualembryo.ai/challenge/data) ("How many cells to submit"): the scorer subsamples every stage to 10%, splits the target in half, scores against one half and uses the other for the ceiling. Here every stage is subsampled to 10% with a seed. The target is split in half and the prediction is scored against half A. The reference is its own 10% working copy. Each seed gives a different subsample and a different split.
- `full` scores the prediction against the whole released target. The seed then changes only the scorer's internal randomness.

## Outputs

- `results/rescore.csv`: one row per submission row. It has the board score, the status (`scored`, `missing_file`, `no_board`, `board_not_configured`, `scoring_error`, or `scored_ambiguous_name`), the local headline mean and sd over seeds, the difference from the board, and the mean raw value and skill of each metric.
- `results/RESCORE.md`: coverage (missing, blank and failed rows), then for each board the number of files, the mean and sd of local minus board, the Spearman rank correlation between the local and board headlines, the five largest disagreements, and the rank correlation of each metric's skill with the board score. `n/a` means the value is undefined, because there are fewer than three files or the metric did not change across files.
- `results/scores.jsonl`: one line per file, board, protocol and seed, with the raw metrics. Reruns read this file and score only what is missing. Changing a board's released files or the scorer changes the key, so the affected files are scored again.
- `results/index_used.json`: the copy of the panel index that the run used.

How to read the numbers. A small local minus board difference means that the local protocol reproduces the board for that file. The rank correlation says whether the ordering of files agrees, and the per-metric table says which metric moved the board. With few files these correlations are unstable, so read them together with n.

## Limits

- The board's exact subsample is not published. Under the board protocol the local headline changes with the seed, so expect noise. The demo below measured a seed sd of 1.09 points for the board protocol, on 150-cell synthetic data. Real stages have more cells, so the noise may be smaller, but measure it on release rather than assume it.
- The released truth may be the full stage or the 10% working copy. Check which one it is at release and set the `*_is_working_copy` flags to match.
- A local rescoring is an analysis of files already submitted. It is not a score, and it cannot show the hidden test result. Agreement with the board on old files does not guarantee the ranking of the final test submissions.
- Files are matched by name. Two different files with the same name under the search folders are a clash, and the tool says so.
- Weights and directions come from the `metric-lens` copy of the board definitions. The anchors come from the live index. If the two differ, the tool warns and uses the index.
- Under the full protocol the whole target is loaded for each file, one file at a time in a separate process. The machine used for development has 8 GB of memory. The demo peaked at about 300 MB per scoring process, at 150 cells. That does not show what a full release needs, so check memory on the first full-size run.
- `export_submissions.js` depends on the layout of the submissions table. If a column is missing it stops and lists the headers it found.

## Demo

`demo/run_demo.sh` runs everything on synthetic data. It downloads veckit's public 150-cell heart samples from GitHub at the pinned commit. The reference is `sample_heart_9.25`, the target is `sample_heart_9.5`, and six predictions are made by transforming the reference only: copy, shrink toward the mean, scale by 1.2 and 0.8, rotate the coordinates by 30 degrees, and blend with a shuffled copy. The board score for each file is one full score with the index's anchors and weights, plus Gaussian noise with sd 1.0. These are not real board values. The demo tests the pipeline and shows how a local rescoring compares with a noisy board.

```bash
PY=python3 ./demo/run_demo.sh
```

Results from the run used for this README:

- Full protocol, 5 files scored: local minus board mean 0.04, sd 0.23. The seed sd of the local headline averages 0.13. Spearman rank correlation 0.975 (n=5).
- Board protocol at fraction 0.5, 5 files scored: local minus board mean 0.34, sd 0.50. The seed sd of the local headline averages 1.09. Spearman 0.975 (n=5).

Notes on these numbers:

- The fraction is 0.5, not 0.1. At 0.1 a 150-cell sample leaves 7 cells after the half split, and veckit fails on a 15-cell target. At 0.5 the target half A has 37 cells.
- The synthetic noise drew small values by chance. The differences in the full run have sd 0.23, which is smaller than the injected sd of 1.0, so they do not measure the noise of a real board.
- The spatial metrics `d2_shape`, `occupancy_dice` and `scale_log_ratio` do not change across these predictions, so their rank correlations are `n/a`.
- Row 6 has a blank board and row 7 names a file that is not on disk. The report lists both under coverage.

The demo writes its generated files into `demo/`. The folder `demo/data/` and the generated results are not committed.
