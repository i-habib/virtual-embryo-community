# Ensemble Atlas

Scorer pinned to `aristoteleo/veckit@46d41e63f42a9aab815db20b742feeccd249cb17`.

This is the behavior study around ensembling, separate from the Blender implementation. The public mini targets are used only to measure outcomes after the ensemble is formed. Parent diagnostics use the two prediction files alone.

## Metric transfer matrix

Each entry is the fraction of tested regimes where the method matched or beat the better parent on that metric. This makes tradeoffs visible instead of hiding them in one scalar score.

| method             |   d2_shape |   de_direction |   de_score |   mmd_u |   neighborhood_mmd |   occupancy_dice |   sliced_wasserstein |   variogram |
|:-------------------|-----------:|---------------:|-----------:|--------:|-------------------:|-----------------:|---------------------:|------------:|
| mean_graft         |     nan    |            1   |      1     |   0.8   |                nan |           nan    |               nan    |         1   |
| population_mix     |     nan    |            0   |      0.222 |   0.889 |                nan |           nan    |               nan    |         0   |
| quantile_graft     |     nan    |            0.8 |      0.8   |   0.8   |                nan |           nan    |               nan    |         0.8 |
| spatial_transplant |       0.84 |            1   |      1     |   1     |                  1 |             0.92 |                 0.92 |         1   |

## Target-free parent diagnostics

Diagnostics include mean disagreement, variance/covariance disagreement, marginal Wasserstein distance, cell-count mismatch, and for spatial pairs, expression-matching ambiguity and mutual-nearest-neighbor rate. The table below shows the three strongest Spearman associations per method with preservation of the better parent's primary metrics.

| method             | diagnostic              |   n |   spearman_rho |   p_value |
|:-------------------|:------------------------|----:|---------------:|----------:|
| mean_graft         | variance_disagreement   |  25 |        -0.5205 |    0.0076 |
| mean_graft         | marginal_wasserstein    |  25 |         0.1735 |    0.4068 |
| mean_graft         | mean_disagreement       |  25 |        -0.0486 |    0.8176 |
| population_mix     | mean_disagreement       |   9 |         0.2205 |    0.5686 |
| population_mix     | variance_disagreement   |   9 |         0.2205 |    0.5686 |
| population_mix     | covariance_disagreement |   9 |         0.2205 |    0.5686 |
| quantile_graft     | variance_disagreement   |  25 |        -0.7057 |    0.0001 |
| quantile_graft     | mean_disagreement       |  25 |         0.3536 |    0.083  |
| quantile_graft     | covariance_disagreement |  25 |        -0.1109 |    0.5975 |
| spatial_transplant | assignment_ambiguity    |  25 |        -0.5957 |    0.0017 |
| spatial_transplant | mutual_nn_fraction      |  25 |         0.5866 |    0.0021 |
| spatial_transplant | marginal_wasserstein    |  25 |         0.3826 |    0.0591 |

These are exploratory correlations on controlled public-mini grids, not universal thresholds. `diagnostic_bins.csv` gives the median-split success/failure rates used for the provisional decision map.

## Simple ensemble baselines

The Blender operators are compared with obvious alternatives: whole-cell mixing, rowwise averaging where rows are deliberately aligned, a half pseudobulk shift, raw-expression Hungarian matching, random coordinate transfer, and same-index coordinate transfer.

| experiment       | method                         |   primary_best_preserved_fraction |   primary_win_fraction |   primary_losses_vs_both |
|:-----------------|:-------------------------------|----------------------------------:|-----------------------:|-------------------------:|
| T1_mean_pair     | mean_graft                     |                             1     |                  0.5   |                        0 |
| T1_mean_pair     | population_mix_0.5             |                             0.25  |                  0.25  |                        0 |
| T1_mean_pair     | rowwise_average                |                             0     |                  0     |                        0 |
| T1_mean_pair     | half_pseudobulk_shift          |                             0     |                  0     |                        0 |
| T1_quantile_pair | quantile_graft                 |                             1     |                  0.5   |                        0 |
| T1_quantile_pair | population_mix_0.5             |                             0.25  |                  0.25  |                        0 |
| T1_quantile_pair | rowwise_average                |                             0     |                  0     |                        0 |
| T1_quantile_pair | half_pseudobulk_shift          |                             0.25  |                  0.25  |                        0 |
| T2_spatial_pair  | spatial_transplant             |                             1     |                  0.25  |                        0 |
| T2_spatial_pair  | raw_expression_hungarian       |                             1     |                  0.25  |                        0 |
| T2_spatial_pair  | random_coordinate_transfer     |                             0.875 |                  0.125 |                        0 |
| T2_spatial_pair  | same_index_coordinate_transfer |                             1     |                  0.125 |                        0 |

## Organizer reference-row pairs

These are reconstructed from reference-row definitions published by the organizers and the same public mini bundle. They are not competitive model pairs. They are useful because they were not designed as inverse transformations for an ensemble operator.

| task   | parent_A       | parent_B          | method                         |   primary_best_preserved_fraction |   primary_win_fraction |   primary_losses_vs_both |
|:-------|:---------------|:------------------|:-------------------------------|----------------------------------:|-----------------------:|-------------------------:|
| T1     | copy_last      | ctrl_one_cell     | mean_graft                     |                             0.5   |                  0     |                        0 |
| T1     | copy_last      | ctrl_one_cell     | quantile_graft                 |                             0.5   |                  0     |                        0 |
| T1     | copy_last      | ctrl_one_cell     | population_mix_0.5             |                             0.25  |                  0.25  |                        1 |
| T1     | copy_last      | ctrl_one_cell     | rowwise_average                |                             0.5   |                  0     |                        0 |
| T1     | copy_last      | ctrl_scale_ref    | mean_graft                     |                             0.75  |                  0.5   |                        0 |
| T1     | copy_last      | ctrl_scale_ref    | quantile_graft                 |                             1     |                  0     |                        0 |
| T1     | copy_last      | ctrl_scale_ref    | population_mix_0.5             |                             0.75  |                  0.5   |                        0 |
| T1     | copy_last      | ctrl_scale_ref    | rowwise_average                |                             0.5   |                  0     |                        0 |
| T1     | ctrl_one_cell  | ctrl_scale_ref    | mean_graft                     |                             1     |                  0.75  |                        0 |
| T1     | ctrl_one_cell  | ctrl_scale_ref    | quantile_graft                 |                             1     |                  0     |                        0 |
| T1     | ctrl_one_cell  | ctrl_scale_ref    | population_mix_0.5             |                             1     |                  0.75  |                        0 |
| T1     | ctrl_one_cell  | ctrl_scale_ref    | rowwise_average                |                             0.75  |                  0.25  |                        1 |
| T2     | ctrl_scale_ref | ctrl_squashed_ref | spatial_transplant             |                             0.625 |                  0     |                        0 |
| T2     | ctrl_scale_ref | ctrl_squashed_ref | random_coordinate_transfer     |                             0.375 |                  0.125 |                        1 |
| T2     | ctrl_scale_ref | ctrl_squashed_ref | same_index_coordinate_transfer |                             0.625 |                  0     |                        0 |
| T3     | wt_identity    | ctrl_scale_wt     | mean_graft                     |                             0.8   |                  0.4   |                        0 |
| T3     | wt_identity    | ctrl_scale_wt     | population_mix_0.5             |                             0.4   |                  0.2   |                        2 |
| T3     | wt_identity    | ctrl_scale_wt     | rowwise_average                |                             0.8   |                  0.2   |                        0 |

The mini bundle does not contain the two preceding stages required to reconstruct the organizer's `pseudobulk_shift` T1/T2 baseline honestly, nor a distinct held-out knockout for a non-leaking `shift_transfer` test. Those baselines are therefore not fabricated here.

## Reproduce

```bash
pip install -r requirements.txt
python regime_map.py --out-dir regime_results
python ensemble_atlas.py --regime-dir regime_results --out-dir atlas_results
```

The same analysis is designed to be rerun once validation ground truth is released in the final phase, so the diagnostic rules can be checked outside these controlled mini examples.
