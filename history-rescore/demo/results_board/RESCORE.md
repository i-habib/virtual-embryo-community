# Local rescoring of a submission history

> SYNTHETIC DEMO: board scores for T2:heart:val_interp are not real board values.

Generated 2026-10-14T20:27:41+00:00 UTC.

- Protocol: `board`. Seeds: 3 (0 to 2).
- Stage subsample rate: 0.5 (board protocol); scored against half A of the target.
- Panel index: `/Users/ivanhabib/Projects/vec-community-work/virtual-embryo-community/history-rescore/demo/index_snapshot.json` (sha256 26830523bcba).
- Scorer: veckit 0.1.1 (source sha256 375fb9d2f9ad).
- Board weights and directions: metric-lens `BOARDS`. Anchors: the panel index.

A local rescoring is an analysis of files you already submitted. It is not a score, and it cannot show the hidden test result.

## Coverage

- Rows in submissions.csv: 7
- missing_file: 1
- no_board: 1
- scored: 5

| file | board | status | note |
|---|---|---|---|
| heart_run_01_copy_last.h5ad | T2:heart:val_interp | scored | 150 cells outside board limits [1000, 17616] (scored anyway) |
| heart_run_02_shrink50.h5ad | T2:heart:val_interp | scored | 150 cells outside board limits [1000, 17616] (scored anyway) |
| heart_run_03_scale120.h5ad | T2:heart:val_interp | scored | 150 cells outside board limits [1000, 17616] (scored anyway) |
| heart_run_04_scale080.h5ad | T2:heart:val_interp | scored | 150 cells outside board limits [1000, 17616] (scored anyway) |
| heart_run_05_rotate30.h5ad | T2:heart:val_interp | scored | 150 cells outside board limits [1000, 17616] (scored anyway) |
| heart_run_06_blend_shuffle.h5ad | (blank) | no_board | board blank: set it by hand in submissions.csv |
| heart_run_07_missing.h5ad | T2:heart:val_interp | missing_file | not found under the search folders |

## T2:heart:val_interp

- Files scored: 5; with a board score: 5
- Local minus board: mean 0.34, sd 0.50 (n=5)
- Seed sd of the local headline, mean over files: 1.09 (n=5 files)
- Spearman rho, local vs board headline: 0.975 (n=5)

Largest disagreements (local minus board):

| file | submitted | board | board score | local mean | difference |
|---|---|---|---:|---:|---:|
| heart_run_04_scale080.h5ad | 2026-10-13 09:00 | T2:heart:val_interp | 30.04 | 31.11 | 1.07 |
| heart_run_05_rotate30.h5ad | 2026-10-14 09:00 | T2:heart:val_interp | 31.48 | 31.90 | 0.42 |
| heart_run_01_copy_last.h5ad | 2026-10-10 09:00 | T2:heart:val_interp | 31.50 | 31.90 | 0.40 |
| heart_run_02_shrink50.h5ad | 2026-10-11 09:00 | T2:heart:val_interp | 33.09 | 32.78 | -0.31 |
| heart_run_03_scale120.h5ad | 2026-10-12 09:00 | T2:heart:val_interp | 32.39 | 32.52 | 0.13 |

Which metric moved the board: Spearman rho of each metric's local skill against the board score. n/a means the metric did not vary across these files (or fewer than 3 files).

| metric | rho | n |
|---|---:|---:|
| de_score | 0.359 | 5 |
| de_direction | 0.872 | 5 |
| mmd_u | -0.051 | 5 |
| variogram | 0.975 | 5 |
| d2_shape | n/a | 5 |
| occupancy_dice | n/a | 5 |
| scale_log_ratio | n/a | 5 |
| neighborhood_mmd | -0.051 | 5 |

