# Ensemble Lab results

Scorer pinned to `aristoteleo/veckit@46d41e63f42a9aab815db20b742feeccd249cb17`.

These are controlled, target-aware experiments on the organizers' public mini examples. They test what a composition operation preserves; they are not hidden-board estimates.

## T1: mean versus population structure

A has the target pseudobulk mean but collapses every cell to that mean. B adds a positive gene-wise offset to the target, changing pseudobulk while leaving the centered cell cloud unchanged. Mean grafting combines A's mean with B's population structure. A zero floor removes float32 roundoff at target-zero entries.

| candidate                |   de_score |   de_direction |   energy_distance |    mmd_u |   variogram |   pb_rel_err |   library_size_ratio |   variance_ratio |   composition_JSD |   pseudobulk_pearson |   _de_raw |   _de_chance |   _de_chance_unif |   _n_up |   _n_dn |
|:-------------------------|-----------:|---------------:|------------------:|---------:|------------:|-------------:|---------------------:|-----------------:|------------------:|---------------------:|----------:|-------------:|------------------:|--------:|--------:|
| A_correct_mean_collapsed |     0.5152 |         1      |           25.082  |  0.26126 |    0.018838 |        0     |                0.751 |                0 |            0.0131 |               1      |    0.5152 |            0 |             0.001 |      18 |      15 |
| B_structure_wrong_mean   |     0.3636 |         0.6173 |           49.219  |  0.20065 |    0.048504 |        1.063 |                2.941 |                1 |            0.2786 |               0.9851 |    0.3636 |            0 |             0.001 |      18 |      15 |
| mean_graft               |     0.5152 |         1      |           -0.8259 | -0.00813 |    0        |        0     |                1     |                1 |            0      |               1      |    0.5152 |            0 |             0.001 |      18 |      15 |

Diagnostics:
```json
{
  "offset_min": 0.25,
  "offset_max": 1.163951476220542,
  "clip_min": 0.0,
  "blend_expression_rmse_to_target": 2.056108595086253e-08,
  "blend_max_abs_expression_error": 4.76837158203125e-07,
  "blend_expression_min": 0.0
}
```

### Population-mixture sweep

| candidate          |   de_score |   de_direction |   energy_distance |   mmd_u |   variogram |   pb_rel_err |   library_size_ratio |   variance_ratio |   composition_JSD |   pseudobulk_pearson |   _de_raw |   _de_chance |   _de_chance_unif |   _n_up |   _n_dn |
|:-------------------|-----------:|---------------:|------------------:|--------:|------------:|-------------:|---------------------:|-----------------:|------------------:|---------------------:|----------:|-------------:|------------------:|--------:|--------:|
| mixture_alpha_0    |     0.3636 |         0.6173 |            49.219 | 0.20065 |    0.048504 |       1.063  |                2.941 |            1     |            0.2786 |               0.9851 |    0.3636 |            0 |             0.001 |      18 |      15 |
| mixture_alpha_0.25 |     0.3636 |         0.6418 |            26.579 | 0.09628 |    0.039244 |       0.796  |                2.938 |            1.101 |            0.1739 |               0.9901 |    0.3636 |            0 |             0.001 |      18 |      15 |
| mixture_alpha_0.5  |     0.4848 |         0.6814 |            15.175 | 0.06937 |    0.031193 |       0.5342 |                1.835 |            0.977 |            0.093  |               0.9948 |    0.4848 |            0 |             0.001 |      18 |      15 |
| mixture_alpha_0.75 |     0.5455 |         0.7804 |            14.38  | 0.11979 |    0.023885 |       0.266  |                0.751 |            0.619 |            0.0428 |               0.9984 |    0.5455 |            0 |             0.001 |      18 |      15 |
| mixture_alpha_1    |     0.5152 |         1      |            25.082 | 0.26126 |    0.018838 |       0      |                0.751 |            0     |            0.0131 |               1      |    0.5152 |            0 |             0.001 |      18 |      15 |

The mixture sweep interpolates between complete cells from A and B rather than grafting one factor.

## T1: marginals versus rank structure

A preserves every gene's empirical marginal values but independently shuffles each gene across cells. B preserves target within-gene ranks while applying a positive gene-wise affine distortion. Quantile grafting assigns A's values according to B's ranks.

| candidate                       |   de_score |   de_direction |   energy_distance |    mmd_u |   variogram |   pb_rel_err |   library_size_ratio |   variance_ratio |   composition_JSD |   pseudobulk_pearson |   _de_raw |   _de_chance |   _de_chance_unif |   _n_up |   _n_dn |
|:--------------------------------|-----------:|---------------:|------------------:|---------:|------------:|-------------:|---------------------:|-----------------:|------------------:|---------------------:|----------:|-------------:|------------------:|--------:|--------:|
| A_correct_marginals_shuffled    |     0.5152 |         1      |          -0.36227 |  0.24614 |    0.000167 |       0      |                0.999 |            1     |            0.0132 |               1      |    0.5152 |            0 |             0.001 |      18 |      15 |
| B_correct_ranks_wrong_marginals |     0.1212 |         0.1822 |          36.03    |  0.05396 |    0.083147 |       0.8935 |                2.957 |            1.041 |            0.1292 |               0.9117 |    0.1212 |            0 |             0.001 |      18 |      15 |
| quantile_graft                  |     0.5152 |         1      |          -0.8259  | -0.00813 |    0        |       0      |                1     |            1     |            0      |               1      |    0.5152 |            0 |             0.001 |      18 |      15 |

Diagnostics:
```json
{
  "distorted_expression_min": 0.10000000039494497,
  "blend_expression_rmse_to_target": 0.0,
  "blend_max_abs_expression_error": 0.0,
  "blend_expression_min": 0.0
}
```

## T2: expression versus spatial assignment

A contains exact target expression with coordinates permuted across cells. B contains a coherent target point-cloud assignment but shifted expression and permuted rows. Spatial transplant matches cells in centered expression space and copies B's matched coordinates onto A's expression cells.

| candidate                     |   de_score |   de_direction |   energy_distance |    mmd_u |   variogram |   d2_shape |   sliced_wasserstein |   occupancy_dice |   scale_log_ratio |   count_log_ratio |   neighborhood_mmd |   pb_rel_err |   library_size_ratio |   variance_ratio |   composition_JSD |   pseudobulk_pearson |   morans_I_agreement |   _de_raw |   _de_chance |   _n_up |   _n_dn |   _sw_flip_spread |   _dice_voxel_over_nn |
|:------------------------------|-----------:|---------------:|------------------:|---------:|------------:|-----------:|---------------------:|-----------------:|------------------:|------------------:|-------------------:|-------------:|---------------------:|-----------------:|------------------:|---------------------:|---------------------:|----------:|-------------:|--------:|--------:|------------------:|----------------------:|
| A_expression_wrong_locations  |     0.5102 |         1      |          -0.51578 | -0.00807 |     0       |    0.00213 |              0.03846 |           0.6275 |                 0 |                 0 |            0.13485 |       0      |                 1    |                1 |            0      |               1      |              -0.0957 |    0.7209 |       0.4302 |      86 |       0 |           0.03912 |                   1.9 |
| B_geometry_shifted_expression |     0.449  |         0.9934 |          13.8     |  0.14286 |     0.38415 |    0.00266 |              0       |           1      |                 0 |                 0 |            0.44293 |       1.4561 |                 6.46 |                1 |            0.0015 |               0.9667 |               1      |    0.686  |       0.4302 |      86 |       0 |           0.08091 |                   1.9 |
| spatial_transplant            |     0.5102 |         1      |          -0.51578 | -0.00807 |     0       |    0.00126 |              0       |           1      |                 0 |                 0 |           -0.00793 |       0      |                 1    |                1 |            0      |               1      |               1      |    0.7209 |       0.4302 |      86 |       0 |           0.08091 |                   1.9 |

Diagnostics:
```json
{
  "method": "spatial_transplant",
  "seed": 0,
  "n_out": 150,
  "assignment": "hungarian",
  "embedding_components": 24,
  "match_genes": 500,
  "max_match_genes": 2048,
  "mean_match_distance": 16.733196258544922,
  "p95_match_distance": 16.733200073242188,
  "max_match_distance": 16.733203887939453,
  "subsampled_a": false,
  "subsampled_b": false,
  "obs_source": "A",
  "coordinate_source": "B",
  "obs_location_metadata_may_be_stale": false,
  "blend_expression_rmse_to_target": 0.0,
  "blend_max_abs_expression_error": 0.0,
  "blend_expression_min": 0.0,
  "blend_coordinate_rmse_to_target": 5.0952253430226125e-06,
  "blend_max_coordinate_error": 2.8583225343936647e-05
}
```

## T3: perturbation mean versus cell-level structure

A has the target KO pseudobulk mean repeated across cells. B adds a positive gene-wise offset to the KO population, changing the response mean while leaving the centered KO cell cloud unchanged. Mean grafting restores A's mean and keeps B's cell-level structure.

| candidate                         |   de_score |   de_direction |   severity_slope |   energy_distance |    mmd_u |   variogram |   pb_rel_err |   library_size_ratio |   variance_ratio |   composition_JSD |   pseudobulk_pearson |   _de_raw |   _de_chance |   _n_up |   _n_dn |   _slope_r2 |   d2_shape |   sliced_wasserstein |   occupancy_dice |   scale_log_ratio |   count_log_ratio |   neighborhood_mmd |   _sw_flip_spread |   _dice_voxel_over_nn |
|:----------------------------------|-----------:|---------------:|-----------------:|------------------:|---------:|------------:|-------------:|---------------------:|-----------------:|------------------:|---------------------:|----------:|-------------:|--------:|--------:|------------:|-----------:|---------------------:|-----------------:|------------------:|------------------:|-------------------:|------------------:|----------------------:|
| A_correct_mean_response_collapsed |     0.641  |          1     |           0      |          16.418   |  0.27015 |     0.1135  |       0      |                0.131 |                0 |            0.0069 |                1     |    0.6818 |       0.1136 |      35 |       9 |       1     |    0.00273 |                    0 |                1 |                 0 |                 0 |            0.33905 |           0.05966 |                     2 |
| B_structure_shifted_response      |     0.4872 |          0.889 |           0.6657 |           8.0459  |  0.09182 |     0.27678 |       0.9867 |                3.979 |                1 |            0.0412 |                0.979 |    0.5455 |       0.1136 |      35 |       9 |       0.084 |    0.00273 |                    0 |                1 |                 0 |                 0 |            0.33358 |           0.05966 |                     2 |
| mean_graft                        |     0.641  |          1     |           0      |          -0.53215 | -0.00804 |     0       |       0      |                1     |                1 |            0      |                1     |    0.6818 |       0.1136 |      35 |       9 |       1     |    0.00273 |                    0 |                1 |                 0 |                 0 |           -0.00799 |           0.05966 |                     2 |

Diagnostics:
```json
{
  "offset_min": 0.25,
  "offset_max": 1.8822239605895543,
  "clip_min": 0.0,
  "blend_expression_rmse_to_target": 6.574683220423031e-08,
  "blend_max_abs_expression_error": 9.5367431640625e-07,
  "blend_expression_min": 0.0
}
```

## Reproduce

```bash
pip install -r requirements.txt
python run_lab.py --out-dir results
```
