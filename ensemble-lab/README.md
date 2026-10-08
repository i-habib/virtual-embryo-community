# Virtual Embryo Ensemble Atlas

When does combining two Virtual Embryo predictions help, and when does it make things worse?

This repo studies that question with the public `veckit` scorer. It varies different kinds of error in two parent predictions, combines them in several ways, and records which official metrics improve or degrade.

The experiments use the organizers' public mini examples. They do not use leaderboard feedback or hidden targets.

## Start here

- **[ATLAS_RESULTS.md](ATLAS_RESULTS.md)** — comparisons across ensemble methods, parent-file diagnostics, and organizer-defined control pairs.
- **[REGIME_RESULTS.md](REGIME_RESULTS.md)** — 5×5 grids showing where mean graft, quantile graft, and spatial transplant keep helping as both parents get worse.
- **[RESULTS.md](RESULTS.md)** — small exact checks showing what each operation preserves.

## What the expanded run found

The organizer-defined control pairs are much less clean than the constructed phase diagrams, which is useful.

- On the six T1 control pairs, **quantile graft** matched the better parent on 75% of the primary metrics on average and never became worse than both parents on any primary metric.
- **Mean graft** matched the better parent on about 67% of T1 primary metrics on average, but 2/6 pairs had at least one metric worse than both parents. On T3, that happened on 3/6 pairs.
- On the six T2 control pairs, **random coordinate transfer** had at least one metric worse than both parents on 5/6 pairs. Spatial transplant, raw-expression Hungarian matching, and same-index transfer did not have a worse-than-both metric in this small control set, and they tied surprisingly often.
- On the fixed 3×3 T1 grids, mean graft and quantile graft matched or beat the better parent on every primary metric at all nine tested points. Whole-cell mixing often kept the MMD result but consistently lost the better parent's DE-direction and gene-covariation results.

The T2 ties are a useful negative result too: these controlled examples do not show that spatial transplant is uniquely better than simpler coordinate-transfer rules.

## What the Atlas tests

### Where each method works

The 5×5 grids vary two errors independently. For example, the mean-graft experiment varies error in the prediction supplying the mean and error in the prediction supplying cell-level structure. The same idea is used for gene marginals versus ranks and expression versus spatial matching.

This exposes both useful regions and failure regions instead of showing only one successful example.

### Which metrics move

The Atlas records each official metric separately. An ensemble can improve cell-state distribution while hurting DE, or improve spatial assignment while leaving global geometry unchanged. The tables therefore report metric-by-metric behavior rather than reducing everything to one score.

### Simple alternatives

The main methods are compared with straightforward alternatives:

- whole-cell mixing
- rowwise averaging when rows are deliberately aligned
- moving a prediction halfway toward the other parent's mean
- raw-expression Hungarian matching
- random coordinate transfer
- same-index coordinate transfer

These comparisons run on a fixed 3×3 low/medium/high subset of the controlled grids, giving nine operating points per experiment rather than one selected example.

### Organizer-defined controls

The Atlas tests every pair among four public organizer-defined rows for each task:

- **T1:** `copy_last`, `ctrl_one_cell`, `ctrl_scale_ref`, `ctrl_shrink_ref`
- **T2:** `copy_last`, `ctrl_scale_ref`, `ctrl_squashed_ref`, `ctrl_random_cube`
- **T3:** `wt_identity`, `ctrl_scale_wt`, `ctrl_shrink_wt`, `ctrl_random_dir`

That gives six parent pairs per task. These controls were designed by the organizers to stress the scorer, so they give a useful check outside the error patterns constructed for the ensemble experiments. For the randomized controls, this repo follows the published construction and uses a fixed local seed so reruns are deterministic.

The public mini bundle does not contain the two earlier stages needed to reconstruct `pseudobulk_shift` honestly, or a second knockout for a non-leaking `shift_transfer` test. Those are left out.

## Parent-file diagnostics

The repo also measures differences that can be computed from the two predictions alone, before seeing a target:

- mean disagreement
- variance and covariance disagreement
- average per-gene Wasserstein distance
- cell-count mismatch
- spatial-shape disagreement
- expression-matching ambiguity
- mutual nearest-neighbor rate

`ATLAS_RESULTS.md` reports descriptive Spearman correlations between these quantities and ensemble results on the controlled grids. It does **not** report p-values: the 25 grid points reuse the same five A and five B variants, so they are not independent samples. The median splits are also described only as patterns in these experiments, not as universal decision thresholds.

## Reproduce

```bash
git clone https://github.com/i-habib/virtual-embryo-community
cd virtual-embryo-community/ensemble-lab
pip install -r requirements.txt

# exact operator checks
python run_lab.py --out-dir results

# 5x5 error grids
python regime_map.py --out-dir regime_results

# method comparisons, parent diagnostics, and organizer controls
python ensemble_atlas.py --regime-dir regime_results --out-dir atlas_results
```

All studies pin:

```text
aristoteleo/veckit@46d41e63f42a9aab815db20b742feeccd249cb17
```

GitHub Actions reruns the studies and commits the result tables and figures.

The companion [Virtual Embryo Submission Blender](../submission-blender/) is the reusable tool for composing prediction files. This repo is the empirical study of when those kinds of ensembles help.
