# Ensemble Atlas results

Scorer pinned to `aristoteleo/veckit@46d41e63f42a9aab815db20b742feeccd249cb17`.

The public mini targets are used to score outcomes. The parent diagnostics below use only the two prediction files.

## Parent differences and ensemble results

These Spearman correlations are descriptive. The 25 points in each controlled grid reuse the same five A variants and five B variants, so they are not independent samples and no inferential p-values are reported.

| method             | diagnostic            |   n_grid_points |   spearman_rho |
|:-------------------|:----------------------|----------------:|---------------:|
| mean graft         | variance_disagreement |              25 |         -0.521 |
| mean graft         | marginal_wasserstein  |              25 |          0.174 |
| quantile graft     | variance_disagreement |              25 |         -0.706 |
| quantile graft     | mean_disagreement     |              25 |          0.354 |
| spatial transplant | assignment_ambiguity  |              25 |         -0.596 |
| spatial transplant | mutual_nn_fraction    |              25 |          0.587 |

The numeric cutoffs in `diagnostic_halves.csv` are medians of these controlled grids. They show the direction of the relationship in this experiment; they are not universal thresholds.

## Simple methods across a fixed 3×3 grid

Each comparison method is run at all nine combinations of low (0.1), medium (0.3), and high (0.6) error in the existing controlled experiments.

|                                                           |   d2_shape |   de_direction |   de_score |   mmd_u |   neighborhood_mmd |   occupancy_dice |   sliced_wasserstein |   variogram |
|:----------------------------------------------------------|-----------:|---------------:|-----------:|--------:|-------------------:|-----------------:|---------------------:|------------:|
| ('T1 marginals/ranks', 'half mean shift')                 |        nan |              0 |      0.333 |   1     |                nan |              nan |                  nan |           0 |
| ('T1 marginals/ranks', 'population mix')                  |        nan |              0 |      0.333 |   0.667 |                nan |              nan |                  nan |           0 |
| ('T1 marginals/ranks', 'quantile graft')                  |        nan |              1 |      1     |   1     |                nan |              nan |                  nan |           1 |
| ('T1 marginals/ranks', 'rowwise average')                 |        nan |              0 |      0.333 |   0     |                nan |              nan |                  nan |           0 |
| ('T1 mean/structure', 'half mean shift')                  |        nan |              0 |      0     |   0.444 |                nan |              nan |                  nan |           0 |
| ('T1 mean/structure', 'mean graft')                       |        nan |              1 |      1     |   1     |                nan |              nan |                  nan |           1 |
| ('T1 mean/structure', 'population mix')                   |        nan |              0 |      0     |   0.889 |                nan |              nan |                  nan |           0 |
| ('T1 mean/structure', 'rowwise average')                  |        nan |              0 |      0     |   0     |                nan |              nan |                  nan |           0 |
| ('T2 expression/space', 'random coordinate transfer')     |          0 |              1 |      1     |   1     |                  1 |                1 |                    1 |           1 |
| ('T2 expression/space', 'raw-expression Hungarian')       |          1 |              1 |      1     |   1     |                  1 |                1 |                    1 |           1 |
| ('T2 expression/space', 'same-index coordinate transfer') |          1 |              1 |      1     |   1     |                  1 |                1 |                    1 |           1 |
| ('T2 expression/space', 'spatial transplant')             |          1 |              1 |      1     |   1     |                  1 |                1 |                    1 |           1 |

The table reports the fraction of the nine grid points where a method matched or beat the better parent on each metric.

## Organizer-defined controls

All six pairs are tested for each task using four organizer-defined rows that can be reconstructed from the public mini bundle:

- T1: `copy_last`, `ctrl_one_cell`, `ctrl_scale_ref`, `ctrl_shrink_ref`
- T2: `copy_last`, `ctrl_scale_ref`, `ctrl_squashed_ref`, `ctrl_random_cube`
- T3: `wt_identity`, `ctrl_scale_wt`, `ctrl_shrink_wt`, `ctrl_random_dir`

| task   | method                         |   organizer_pairs_tested |   mean_better_parent_preserved_fraction |   fraction_with_any_strict_win |   fraction_with_any_loss_vs_both |
|:-------|:-------------------------------|-------------------------:|----------------------------------------:|-------------------------------:|---------------------------------:|
| T1     | mean graft                     |                        6 |                                   0.667 |                          0.5   |                            0.333 |
| T1     | population mix                 |                        6 |                                   0.625 |                          0.833 |                            0.333 |
| T1     | quantile graft                 |                        6 |                                   0.75  |                          0     |                            0     |
| T1     | rowwise average                |                        6 |                                   0.583 |                          0.167 |                            0.167 |
| T2     | random coordinate transfer     |                        6 |                                   0.625 |                          0.5   |                            0.833 |
| T2     | raw-expression Hungarian       |                        6 |                                   0.708 |                          0     |                            0     |
| T2     | same-index coordinate transfer |                        6 |                                   0.708 |                          0     |                            0     |
| T2     | spatial transplant             |                        6 |                                   0.708 |                          0     |                            0     |
| T3     | mean graft                     |                        6 |                                   0.75  |                          0.167 |                            0.5   |
| T3     | population mix                 |                        6 |                                   0.667 |                          0.833 |                            0.167 |
| T3     | rowwise average                |                        6 |                                   0.667 |                          0.667 |                            0.167 |

These controls were defined by the organizers for scorer stress testing. They were not designed around the ensemble methods here.

The public mini bundle does not contain the two earlier stages needed to reconstruct `pseudobulk_shift` honestly, or a second knockout for a non-leaking `shift_transfer` test. Those published baselines are left out rather than approximated.

## Raw outputs

Every pair, metric, and method is in `atlas_results/`.

```bash
pip install -r requirements.txt
python regime_map.py --out-dir regime_results
python ensemble_atlas.py --regime-dir regime_results --out-dir atlas_results
```
