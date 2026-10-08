# Ensemble regime-map results

Scorer pinned to `aristoteleo/veckit@46d41e63f42a9aab815db20b742feeccd249cb17`.

These use the organizers' public mini targets. `RESULTS.md` contains the exact preservation/integration checks. The experiments here deliberately make both parents imperfect.

The heatmaps report the fraction of primary metrics where the blend matches or beats the better parent. A value of 1.0 means there is no primary-metric tradeoff relative to choosing whichever parent was better metric by metric.

## Official floor baselines

The challenge defines `copy_last` as the T1/T2 floor and `wt_identity` as the T3 floor.

| task     | baseline    |   de_score |   de_direction |   mmd_u |   variogram |
|:---------|:------------|-----------:|---------------:|--------:|------------:|
| T1       | copy_last   |          0 |              0 | 0.07716 |    0.00187  |
| T2-heart | copy_last   |          0 |              0 | 0.29037 |    0.098139 |
| T3       | wt_identity |          0 |              0 | 0.04623 |    0.032556 |

## Mean graft

Summary: `{"imperfect_grid_points": 24, "points_preserving_best_on_all_primary_metrics": 19, "points_preserving_best_on_at_least_half": 24, "points_with_any_strict_win_vs_both": 24, "points_worse_than_both_on_any_primary_metric": 0, "min_best_preserved_fraction": 0.75}`

![Mean graft regime map](regime_results/mean_regime.png)

## Quantile graft

Summary: `{"imperfect_grid_points": 24, "points_preserving_best_on_all_primary_metrics": 19, "points_preserving_best_on_at_least_half": 19, "points_with_any_strict_win_vs_both": 19, "points_worse_than_both_on_any_primary_metric": 0, "min_best_preserved_fraction": 0.0}`

![Quantile graft regime map](regime_results/quantile_regime.png)

## Spatial transplant

Summary: `{"imperfect_grid_points": 24, "points_preserving_best_on_all_primary_metrics": 20, "points_preserving_best_on_at_least_half": 24, "points_with_any_strict_win_vs_both": 24, "points_worse_than_both_on_any_primary_metric": 3, "min_best_preserved_fraction": 0.625}`

![Spatial transplant regime map](regime_results/spatial_regime.png)

### Hungarian versus greedy

|   matching_noise | assignment   |   coordinate_rmse |   mean_match_distance |   sliced_wasserstein |   occupancy_dice |   neighborhood_mmd |
|-----------------:|:-------------|------------------:|----------------------:|---------------------:|-----------------:|-------------------:|
|              0   | hungarian    |       5.09523e-06 |              16.795   |                    0 |                1 |           -0.00389 |
|              0   | greedy       |       5.09523e-06 |              16.795   |                    0 |                1 |           -0.00389 |
|              0.1 | hungarian    |       5.09523e-06 |               3.17632 |                    0 |                1 |           -0.00389 |
|              0.1 | greedy       |       5.09523e-06 |               3.17632 |                    0 |                1 |           -0.00389 |
|              0.3 | hungarian    |       5.09523e-06 |               3.88354 |                    0 |                1 |           -0.00389 |
|              0.3 | greedy       |       5.09523e-06 |               3.88354 |                    0 |                1 |           -0.00389 |
|              0.6 | hungarian    |       5.09523e-06 |               5.53865 |                    0 |                1 |           -0.00389 |
|              0.6 | greedy       |      81.7486      |               5.91216 |                    0 |                1 |            0.00119 |
|              1   | hungarian    |       5.09523e-06 |               7.76761 |                    0 |                1 |           -0.00389 |
|              1   | greedy       |     133.802       |               9.28761 |                    0 |                1 |            0.02416 |

## Population mixtures

Whole-cell mixtures have no factor-preservation guarantee. The table varies parent complementarity and alpha directly.

|   complementarity_severity |   alpha |   primary_wins_vs_both |   primary_best_preserved |   primary_worse_than_best |   primary_losses_vs_both |   primary_best_preserved_fraction |
|---------------------------:|--------:|-----------------------:|-------------------------:|--------------------------:|-------------------------:|----------------------------------:|
|                       0.25 |    0.25 |                      0 |                        0 |                         4 |                        1 |                              0    |
|                       0.25 |    0.5  |                      1 |                        1 |                         3 |                        1 |                              0.25 |
|                       0.25 |    0.75 |                      2 |                        2 |                         2 |                        0 |                              0.5  |
|                       0.5  |    0.25 |                      1 |                        1 |                         3 |                        0 |                              0.25 |
|                       0.5  |    0.5  |                      1 |                        1 |                         3 |                        0 |                              0.25 |
|                       0.5  |    0.75 |                      1 |                        1 |                         3 |                        0 |                              0.25 |
|                       0.75 |    0.25 |                      1 |                        1 |                         3 |                        0 |                              0.25 |
|                       0.75 |    0.5  |                      1 |                        1 |                         3 |                        0 |                              0.25 |
|                       0.75 |    0.75 |                      1 |                        2 |                         2 |                        0 |                              0.5  |

## Raw outputs

Every grid cell and parent/blend metric is in `regime_results/`. Reproduce with:

```bash
pip install -r requirements.txt
python regime_map.py --out-dir regime_results
```
