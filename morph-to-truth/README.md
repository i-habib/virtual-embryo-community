# morph-to-truth

For Task 2 (3D MERFISH). Pairs each predicted cell with a true cell and shows where each one has to move, so the misplaced regions and cell types are visible. Existing tools report global geometry numbers or show one cloud; none matches cells or shows displacement.

## Run

    python morph.py PRED.h5ad TRUTH.h5ad --out DIR [--cells 3000] [--lam 0.5] [--rescale] [--seconds 10] [--no-video]

Needs ffmpeg on PATH and the sibling `embryo-timelapse/` folder (its `render.py` and `palette.json` are reused). Tests: `python -m pytest -q test_morph.py`.

## Method

1. Subsample each file to N cells (default 3,000, seed 0). Both files use the same seed and N, so the pairs are 1:1. Files are read backed, and only the sampled rows are loaded.
2. Align. Frames are per embryo and not registered across files. Five starts are tried: both clouds centred with no rotation, and both clouds in their PCA frames with each of the four proper sign patterns applied to the prediction. Each start is refined by rigid ICP (nearest-neighbour pairs, Kabsch rotation with det +1, translation; at most 30 rounds, or stop when chamfer changes by under 0.1%). The start with the lowest chamfer after ICP wins. Chamfer is the mean of the two mean nearest-neighbour distances. Units stay in µm; `--rescale` matches the RMS radius first.
3. Match. One-to-one assignment (`scipy.optimize.linear_sum_assignment`). Cost = position distance / its median over all pairs + λ × expression distance / its median over all pairs. Expression is the stored `.X` (no extra transform), projected onto 20 PCs fitted on the true cells. λ = 0.5 by default; λ = 0 is geometry only.
4. Displacement = distance from the aligned predicted cell to its matched true cell, in µm.
5. Cell-type mismatch is scored only over matched pairs whose two labels both belong to the shared vocabulary (labels present in both full files). If fewer than 5 labels are shared, the rate is reported as not available.

## Outputs

- `morph.mp4`, 1280×720, 30 fps. Holds the prediction for 1.5 s, moves each cell linearly to its match, holds the truth for 1.5 s. True cells stay as a grey ghost. Cells are coloured by predicted cell type when `celltype` exists, otherwise by displacement. The turntable makes half a turn over the clip. The spec's 1.5 + 6 + 1.5 s adds to 9 s, so the default `--seconds 10` gives a 7 s move.
- `summary.png`. Left: truth cells on their first two PCs, coloured by how far their match moved. Right: the 15 true cell types with the largest median displacement (types with at least 20 true cells), and the mismatch rate with its basis.
- `matches.csv`: file row of each predicted and true cell, displacement, both types.
- `summary.json`: alignment (winner, chamfer unaligned, best start before ICP, after ICP, every start's numbers), median and 90th percentile displacement, both label vocabularies, mismatch rate and status, per-type medians.

## Demo

`demo/` is a pseudo pair built from released files only. Truth is E9.5.

- `copy_last`: E8.75 used as the prediction of E9.5.
- `corrupt30`: E9.5 with 30% of cells' coordinates replaced by another random cell's coordinates. The corrupted set is known, so this checks that the tool finds it.

| Demo | Winner | Chamfer unaligned → best start → after ICP (µm) | Median / 90th displacement (µm) | Type mismatch |
|---|---|---|---|---|
| copy_last | identity | 50.2 → 50.2 → 50.1 | 106.6 / 248.7 | 30.3% on 409 pairs |
| corrupt30 | PCA (1, 1, 1) | 10.1 → 10.1 → 7.1 | 0.6 / 81.7 | 23.6% on 3,000 pairs |

corrupt30 detail (corrupted flags are used for scoring only, not by the tool): clean cells (2,056) have median displacement 0.44 µm and 90th percentile 0.68 µm. All 600 cells in the top 20% of displacements are corrupted; corrupted cells are 31% of the sample.

Vocabulary, copy_last: E8.75 has 33 cell-type labels, E9.5 has 22, and 5 are shared (NCC, Peri, V-CM, aPHM, pPHM). Matched pairs whose labels are both in that set number 409. Over all 3,000 pairs, 90.5% of labels differ as strings, which is almost entirely vocabulary, not placement. 30.3% is a thin basis, so read it with care. corrupt30 has identical vocabularies (22 shared).

Expression weight trade-off, corrupt30: λ = 0 gives mismatch 30.2% and 90th percentile 57.6 µm; λ = 0.5 gives 23.6% and 81.7 µm.

After 20 October the same command works with the released validation answers.

## Limits

- ICP is local. It refines the chosen start, so a start far from the right answer can converge to a wrong alignment. The five starts cover no rotation and the four PCA sign patterns, but not swapped PCA axes.
- If two principal axes have similar spread, the PCA starts may point the wrong way. The identity start is the only other one, so check the `candidates` block in `summary.json`.
- Once clean cells take their own true positions, corrupted cells can only be matched to other corrupted cells. Their large displacements still flag them.
- Chamfer after ICP stays above zero in corrupt30 (7.1 µm). The corrupted cells sit at positions of cells that are not in the 3,000-cell truth sample, so they have no exact partner.
- Results depend on the 3,000-cell subsample. Change `--seed` to check stability.
- Expression uses whatever `.X` holds. Raw counts are not log-transformed.

## Files

- `morph.py`: pipeline and CLI.
- `test_morph.py`: rotation, identity, rotated copy, 10% and 20% corruption, mismatch vocabulary rules, one-second render.
- `demo/copy_last/`, `demo/corrupt30/`: outputs above.
