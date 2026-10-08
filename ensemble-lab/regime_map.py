from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import anndata as ad
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from run_lab import (
    VECKIT_COMMIT,
    dense,
    download_public_samples,
    make_like,
    positive_offset,
    save_and_score,
)
from vec_blender.methods import (
    mean_graft,
    population_mix,
    quantile_graft,
    spatial_transplant,
)


T1_PRIMARY = {
    "de_score": "high",
    "de_direction": "high",
    "mmd_u": "low",
    "variogram": "low",
}
T2_PRIMARY = {
    **T1_PRIMARY,
    "d2_shape": "low",
    "sliced_wasserstein": "low",
    "occupancy_dice": "high",
    "neighborhood_mmd": "low",
}

MEAN_LEVELS = (0.0, 0.1, 0.3, 0.6, 1.2)
RESIDUAL_LEVELS = (0.0, 0.1, 0.3, 0.6, 1.0)
MARGINAL_LEVELS = (0.0, 0.1, 0.3, 0.6, 1.2)
RANK_LEVELS = (0.0, 0.1, 0.3, 0.6, 1.0)
SPATIAL_EXPRESSION_LEVELS = (0.0, 0.1, 0.3, 0.6, 1.0)
SPATIAL_NOISE_LEVELS = (0.0, 0.1, 0.3, 0.6, 1.0)


def align_source(source: ad.AnnData, target: ad.AnnData) -> ad.AnnData:
    genes = list(map(str, target.var_names))
    if set(map(str, source.var_names)) != set(genes):
        raise ValueError("source and target do not share the same gene set")
    return source[:, genes]


def gene_shuffle(X: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.empty_like(X)
    for j in range(X.shape[1]):
        out[:, j] = X[rng.permutation(X.shape[0]), j]
    return out


def partial_rank_corruption(
    X: np.ndarray, fraction: float, seed: int
) -> np.ndarray:
    if fraction <= 0:
        return X.copy()
    rng = np.random.default_rng(seed)
    out = X.copy()
    n = X.shape[0]
    k = max(2, min(n, int(round(fraction * n))))
    for j in range(X.shape[1]):
        idx = rng.choice(n, size=k, replace=False)
        out[idx, j] = X[rng.permutation(idx), j]
    return out


def compare_to_parents(a: dict, b: dict, blend: dict, directions: dict) -> dict:
    strict_wins = 0
    preserves_best = 0
    worse_than_both = 0

    for metric, direction in directions.items():
        av, bv, cv = map(float, (a[metric], b[metric], blend[metric]))
        tol = 1e-8 * max(1.0, abs(av), abs(bv), abs(cv))

        if direction == "high":
            best = max(av, bv)
            worst = min(av, bv)
            strict_wins += int(cv > best + tol)
            preserves_best += int(cv >= best - tol)
            worse_than_both += int(cv < worst - tol)
        else:
            best = min(av, bv)
            worst = max(av, bv)
            strict_wins += int(cv < best - tol)
            preserves_best += int(cv <= best + tol)
            worse_than_both += int(cv > worst + tol)

    n = len(directions)
    return {
        "primary_wins_vs_both": strict_wins,
        "primary_best_preserved": preserves_best,
        "primary_worse_than_best": n - preserves_best,
        "primary_losses_vs_both": worse_than_both,
        "primary_win_fraction": strict_wins / n,
        "primary_best_preserved_fraction": preserves_best / n,
    }


def score_pred(
    pred: ad.AnnData,
    *,
    name: str,
    task: str,
    work: Path,
    target: Path,
    reference: Path | None = None,
    wt: Path | None = None,
) -> dict:
    return save_and_score(
        pred,
        name=name,
        task=task,
        work=work,
        target=target,
        reference=reference,
        wt=wt,
    )


def baseline_rows(samples: dict[str, Path], work: Path) -> list[dict]:
    rows = []

    target = ad.read_h5ad(samples["sample_9.5.h5ad"])
    ref = align_source(ad.read_h5ad(samples["sample_8.5.h5ad"]), target)
    pred = make_like(target, dense(ref), prefix="copy_last_t1")
    score = score_pred(
        pred,
        name="copy_last_T1",
        task="T1",
        work=work,
        target=samples["sample_9.5.h5ad"],
        reference=samples["sample_8.5.h5ad"],
    )
    rows.append({"task": "T1", "baseline": "copy_last", **score})

    target = ad.read_h5ad(samples["sample_heart_9.5.h5ad"])
    ref = align_source(ad.read_h5ad(samples["sample_heart_9.25.h5ad"]), target)
    pred = make_like(
        target,
        dense(ref),
        coords=np.asarray(ref.obsm["spatial_3D"])[:, :3],
        prefix="copy_last_t2",
    )
    score = score_pred(
        pred,
        name="copy_last_T2",
        task="T2",
        work=work,
        target=samples["sample_heart_9.5.h5ad"],
        reference=samples["sample_heart_9.25.h5ad"],
    )
    rows.append({"task": "T2-heart", "baseline": "copy_last", **score})

    target = ad.read_h5ad(samples["sample_mab21l2_ko.h5ad"])
    wt = align_source(ad.read_h5ad(samples["sample_wt.h5ad"]), target)
    coords = (
        np.asarray(wt.obsm["spatial_3D"])[:, :3]
        if "spatial_3D" in wt.obsm
        else None
    )
    pred = make_like(target, dense(wt), coords=coords, prefix="wt_identity")
    score = score_pred(
        pred,
        name="wt_identity_T3",
        task="T3",
        work=work,
        target=samples["sample_mab21l2_ko.h5ad"],
        wt=samples["sample_wt.h5ad"],
    )
    rows.append({"task": "T3", "baseline": "wt_identity", **score})
    return rows


def t1_mean_regime(samples: dict[str, Path], work: Path) -> list[dict]:
    target_path = samples["sample_9.5.h5ad"]
    reference_path = samples["sample_8.5.h5ad"]
    target = ad.read_h5ad(target_path)
    X = dense(target)
    mu = X.mean(0)
    residual = X - mu
    offset = positive_offset(X)
    shuffled = gene_shuffle(X, 1101)

    donors = {
        level: make_like(
            target,
            mu[None, :]
            + 0.25 * residual
            + level * offset[None, :],
            prefix=f"mean_A_{level}",
        )
        for level in MEAN_LEVELS
    }
    carriers = {
        level: make_like(
            target,
            (1 - level) * X
            + level * shuffled
            + 1.5 * offset[None, :],
            prefix=f"mean_B_{level}",
        )
        for level in RESIDUAL_LEVELS
    }

    donor_scores = {
        level: score_pred(
            donors[level],
            name=f"mean_A_{level}",
            task="T1",
            work=work,
            target=target_path,
            reference=reference_path,
        )
        for level in MEAN_LEVELS
    }
    carrier_scores = {
        level: score_pred(
            carriers[level],
            name=f"mean_B_{level}",
            task="T1",
            work=work,
            target=target_path,
            reference=reference_path,
        )
        for level in RESIDUAL_LEVELS
    }

    rows = []
    for mean_error in MEAN_LEVELS:
        for residual_error in RESIDUAL_LEVELS:
            blend = mean_graft(
                donors[mean_error], carriers[residual_error], clip_min=0
            ).adata
            blend_score = score_pred(
                blend,
                name=f"mean_blend_m{mean_error}_r{residual_error}",
                task="T1",
                work=work,
                target=target_path,
                reference=reference_path,
            )
            comparison = compare_to_parents(
                donor_scores[mean_error],
                carrier_scores[residual_error],
                blend_score,
                T1_PRIMARY,
            )
            rows.append(
                {
                    "mean_error_level": mean_error,
                    "residual_error_level": residual_error,
                    **comparison,
                    "blend_rmse_to_target": float(
                        np.sqrt(np.mean((dense(blend) - X) ** 2))
                    ),
                    **{f"blend_{k}": blend_score[k] for k in T1_PRIMARY},
                    **{f"A_{k}": donor_scores[mean_error][k] for k in T1_PRIMARY},
                    **{
                        f"B_{k}": carrier_scores[residual_error][k]
                        for k in T1_PRIMARY
                    },
                }
            )
    return rows


def t1_quantile_regime(samples: dict[str, Path], work: Path) -> list[dict]:
    target_path = samples["sample_9.5.h5ad"]
    reference_path = samples["sample_8.5.h5ad"]
    target = ad.read_h5ad(target_path)
    X = dense(target)
    offset = positive_offset(X)
    scrambled = gene_shuffle(X, 2201)
    g = X.shape[1]
    slope = 0.2 + 0.8 * (np.arange(g) + 1) / g
    bad_scale = 0.65 + 0.7 * (np.arange(g) + 1) / g

    donors = {
        level: make_like(
            target,
            scrambled * (1 + level * slope[None, :])
            + level * 0.4 * offset[None, :],
            prefix=f"quant_A_{level}",
        )
        for level in MARGINAL_LEVELS
    }
    carriers = {
        level: make_like(
            target,
            partial_rank_corruption(
                X, level, 2300 + int(level * 1000)
            )
            * bad_scale[None, :]
            + 0.8 * offset[None, :],
            prefix=f"quant_B_{level}",
        )
        for level in RANK_LEVELS
    }

    donor_scores = {
        level: score_pred(
            donors[level],
            name=f"quant_A_{level}",
            task="T1",
            work=work,
            target=target_path,
            reference=reference_path,
        )
        for level in MARGINAL_LEVELS
    }
    carrier_scores = {
        level: score_pred(
            carriers[level],
            name=f"quant_B_{level}",
            task="T1",
            work=work,
            target=target_path,
            reference=reference_path,
        )
        for level in RANK_LEVELS
    }

    rows = []
    for marginal_error in MARGINAL_LEVELS:
        for rank_error in RANK_LEVELS:
            blend = quantile_graft(
                donors[marginal_error], carriers[rank_error]
            ).adata
            blend_score = score_pred(
                blend,
                name=f"quant_blend_m{marginal_error}_r{rank_error}",
                task="T1",
                work=work,
                target=target_path,
                reference=reference_path,
            )
            comparison = compare_to_parents(
                donor_scores[marginal_error],
                carrier_scores[rank_error],
                blend_score,
                T1_PRIMARY,
            )
            rows.append(
                {
                    "marginal_error_level": marginal_error,
                    "rank_corruption_fraction": rank_error,
                    **comparison,
                    "blend_rmse_to_target": float(
                        np.sqrt(np.mean((dense(blend) - X) ** 2))
                    ),
                    **{f"blend_{k}": blend_score[k] for k in T1_PRIMARY},
                    **{
                        f"A_{k}": donor_scores[marginal_error][k]
                        for k in T1_PRIMARY
                    },
                    **{
                        f"B_{k}": carrier_scores[rank_error][k]
                        for k in T1_PRIMARY
                    },
                }
            )
    return rows


def t2_spatial_regime(
    samples: dict[str, Path], work: Path
) -> tuple[list[dict], list[dict]]:
    target_path = samples["sample_heart_9.5.h5ad"]
    reference_path = samples["sample_heart_9.25.h5ad"]
    target = ad.read_h5ad(target_path)
    X = dense(target)
    coords = np.asarray(target.obsm["spatial_3D"], dtype=float)[:, :3]
    shuffled = gene_shuffle(X, 3301)
    rng = np.random.default_rng(3302)
    coord_perm = rng.permutation(len(X))
    row_perm = rng.permutation(len(X))
    std = np.std(X, axis=0)
    shift = 0.35 + 0.55 * std

    expression_donors = {
        level: make_like(
            target,
            (1 - level) * X + level * shuffled,
            coords=coords[coord_perm],
            prefix=f"spatial_A_{level}",
        )
        for level in SPATIAL_EXPRESSION_LEVELS
    }

    geometry_carriers = {}
    for level in SPATIAL_NOISE_LEVELS:
        noise_rng = np.random.default_rng(3400 + int(level * 1000))
        noise = noise_rng.normal(
            scale=level * (0.05 + std), size=X.shape
        )
        expression = np.maximum(X + shift[None, :] + noise, 0)[row_perm]
        geometry_carriers[level] = make_like(
            target,
            expression,
            coords=coords[row_perm],
            prefix=f"spatial_B_{level}",
        )

    donor_scores = {
        level: score_pred(
            expression_donors[level],
            name=f"spatial_A_{level}",
            task="T2",
            work=work,
            target=target_path,
            reference=reference_path,
        )
        for level in SPATIAL_EXPRESSION_LEVELS
    }
    carrier_scores = {
        level: score_pred(
            geometry_carriers[level],
            name=f"spatial_B_{level}",
            task="T2",
            work=work,
            target=target_path,
            reference=reference_path,
        )
        for level in SPATIAL_NOISE_LEVELS
    }

    rows = []
    for expression_error in SPATIAL_EXPRESSION_LEVELS:
        for matching_noise in SPATIAL_NOISE_LEVELS:
            blend = spatial_transplant(
                expression_donors[expression_error],
                geometry_carriers[matching_noise],
                assignment="hungarian",
                n_components=24,
            ).adata
            blend_score = score_pred(
                blend,
                name=f"spatial_blend_e{expression_error}_n{matching_noise}",
                task="T2",
                work=work,
                target=target_path,
                reference=reference_path,
            )
            comparison = compare_to_parents(
                donor_scores[expression_error],
                carrier_scores[matching_noise],
                blend_score,
                T2_PRIMARY,
            )
            coordinate_error = (
                np.asarray(blend.obsm["spatial_3D"], dtype=float) - coords
            )
            rows.append(
                {
                    "expression_corruption": expression_error,
                    "matching_noise": matching_noise,
                    **comparison,
                    "coordinate_rmse": float(
                        np.sqrt(np.mean(coordinate_error**2))
                    ),
                    **{f"blend_{k}": blend_score[k] for k in T2_PRIMARY},
                    **{
                        f"A_{k}": donor_scores[expression_error][k]
                        for k in T2_PRIMARY
                    },
                    **{
                        f"B_{k}": carrier_scores[matching_noise][k]
                        for k in T2_PRIMARY
                    },
                }
            )

    assignment_rows = []
    expression_error = 0.1
    for matching_noise in SPATIAL_NOISE_LEVELS:
        for method in ("hungarian", "greedy"):
            result = spatial_transplant(
                expression_donors[expression_error],
                geometry_carriers[matching_noise],
                assignment=method,
                n_components=24,
            )
            score = score_pred(
                result.adata,
                name=f"assign_{method}_n{matching_noise}",
                task="T2",
                work=work,
                target=target_path,
                reference=reference_path,
            )
            coordinate_error = (
                np.asarray(result.adata.obsm["spatial_3D"], dtype=float) - coords
            )
            assignment_rows.append(
                {
                    "matching_noise": matching_noise,
                    "assignment": method,
                    "coordinate_rmse": float(
                        np.sqrt(np.mean(coordinate_error**2))
                    ),
                    "mean_match_distance": result.report["mean_match_distance"],
                    **{k: score[k] for k in T2_PRIMARY},
                }
            )
    return rows, assignment_rows


def mixture_regime(samples: dict[str, Path], work: Path) -> list[dict]:
    target_path = samples["sample_9.5.h5ad"]
    reference_path = samples["sample_8.5.h5ad"]
    target = ad.read_h5ad(target_path)
    X = dense(target)
    mu = X.mean(0)
    residual = X - mu
    offset = positive_offset(X)
    shuffled = gene_shuffle(X, 4401)
    rows = []

    for severity in (0.25, 0.5, 0.75):
        A = make_like(
            target,
            mu[None, :]
            + (1 - severity) * residual
            + 0.1 * offset[None, :],
            prefix=f"mix_A_{severity}",
        )
        B = make_like(
            target,
            (1 - 0.15 * severity) * X
            + 0.15 * severity * shuffled
            + (1.4 * severity) * offset[None, :],
            prefix=f"mix_B_{severity}",
        )
        score_a = score_pred(
            A,
            name=f"mix_A_{severity}",
            task="T1",
            work=work,
            target=target_path,
            reference=reference_path,
        )
        score_b = score_pred(
            B,
            name=f"mix_B_{severity}",
            task="T1",
            work=work,
            target=target_path,
            reference=reference_path,
        )

        for alpha in (0.25, 0.5, 0.75):
            blend = population_mix(
                A, B, alpha=alpha, n_out=target.n_obs, seed=17
            ).adata
            blend_score = score_pred(
                blend,
                name=f"mix_s{severity}_a{alpha}",
                task="T1",
                work=work,
                target=target_path,
                reference=reference_path,
            )
            comparison = compare_to_parents(
                score_a, score_b, blend_score, T1_PRIMARY
            )
            rows.append(
                {
                    "complementarity_severity": severity,
                    "alpha": alpha,
                    **comparison,
                    **{f"blend_{k}": blend_score[k] for k in T1_PRIMARY},
                    **{f"A_{k}": score_a[k] for k in T1_PRIMARY},
                    **{f"B_{k}": score_b[k] for k in T1_PRIMARY},
                }
            )
    return rows


def heatmap(
    df: pd.DataFrame,
    row: str,
    col: str,
    title: str,
    out: Path,
) -> None:
    pivot = (
        df.pivot(
            index=row,
            columns=col,
            values="primary_best_preserved_fraction",
        )
        .sort_index()
        .sort_index(axis=1)
    )
    fig, ax = plt.subplots(figsize=(6.2, 4.8))
    im = ax.imshow(pivot.values, vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(pivot.columns)), [str(x) for x in pivot.columns])
    ax.set_yticks(range(len(pivot.index)), [str(x) for x in pivot.index])
    ax.set_xlabel(col.replace("_", " "))
    ax.set_ylabel(row.replace("_", " "))
    ax.set_title(title)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            ax.text(
                j,
                i,
                f"{pivot.iloc[i, j]:.2f}",
                ha="center",
                va="center",
            )
    fig.colorbar(
        im,
        ax=ax,
        label="fraction of primary metrics matching or beating better parent",
    )
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def summarize_grid(df: pd.DataFrame, level_columns: list[str]) -> dict:
    exact = np.ones(len(df), dtype=bool)
    for column in level_columns:
        exact &= np.asarray(df[column]) == 0
    imperfect = df.loc[~exact]
    return {
        "imperfect_grid_points": int(len(imperfect)),
        "points_preserving_best_on_all_primary_metrics": int(
            (imperfect.primary_best_preserved_fraction == 1).sum()
        ),
        "points_preserving_best_on_at_least_half": int(
            (imperfect.primary_best_preserved_fraction >= 0.5).sum()
        ),
        "points_with_any_strict_win_vs_both": int(
            (imperfect.primary_wins_vs_both > 0).sum()
        ),
        "points_worse_than_both_on_any_primary_metric": int(
            (imperfect.primary_losses_vs_both > 0).sum()
        ),
        "min_best_preserved_fraction": float(
            imperfect.primary_best_preserved_fraction.min()
        ),
    }


def write_outputs(
    out_dir: Path,
    baselines: list[dict],
    mean_rows: list[dict],
    quantile_rows: list[dict],
    spatial_rows: list[dict],
    assignment_rows: list[dict],
    mixture_rows: list[dict],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = {
        "official_floor_baselines": pd.DataFrame(baselines),
        "mean_regime": pd.DataFrame(mean_rows),
        "quantile_regime": pd.DataFrame(quantile_rows),
        "spatial_regime": pd.DataFrame(spatial_rows),
        "spatial_assignment": pd.DataFrame(assignment_rows),
        "mixture_regime": pd.DataFrame(mixture_rows),
    }
    for name, frame in frames.items():
        frame.to_csv(out_dir / f"{name}.csv", index=False)

    heatmap(
        frames["mean_regime"],
        "mean_error_level",
        "residual_error_level",
        "Mean graft: imperfect complementarity",
        out_dir / "mean_regime.png",
    )
    heatmap(
        frames["quantile_regime"],
        "marginal_error_level",
        "rank_corruption_fraction",
        "Quantile graft: imperfect complementarity",
        out_dir / "quantile_regime.png",
    )
    heatmap(
        frames["spatial_regime"],
        "expression_corruption",
        "matching_noise",
        "Spatial transplant: imperfect complementarity",
        out_dir / "spatial_regime.png",
    )

    summary = {
        "mean_graft": summarize_grid(
            frames["mean_regime"],
            ["mean_error_level", "residual_error_level"],
        ),
        "quantile_graft": summarize_grid(
            frames["quantile_regime"],
            ["marginal_error_level", "rank_corruption_fraction"],
        ),
        "spatial_transplant": summarize_grid(
            frames["spatial_regime"],
            ["expression_corruption", "matching_noise"],
        ),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )

    baselines = frames["official_floor_baselines"]
    assignments = frames["spatial_assignment"]
    mixtures = frames["mixture_regime"]
    md = [
        "# Ensemble regime-map results",
        "",
        f"Scorer pinned to `aristoteleo/veckit@{VECKIT_COMMIT}`.",
        "",
        "These use the organizers' public mini targets. `RESULTS.md` contains the exact preservation/integration checks. The experiments here deliberately make both parents imperfect.",
        "",
        "The heatmaps report the fraction of primary metrics where the blend matches or beats the better parent. A value of 1.0 means there is no primary-metric tradeoff relative to choosing whichever parent was better metric by metric.",
        "",
        "## Official floor baselines",
        "",
        "The challenge defines `copy_last` as the T1/T2 floor and `wt_identity` as the T3 floor.",
        "",
        baselines[
            ["task", "baseline", "de_score", "de_direction", "mmd_u", "variogram"]
        ].to_markdown(index=False),
        "",
        "## Mean graft",
        "",
        f"Summary: `{json.dumps(summary['mean_graft'])}`",
        "",
        "![Mean graft regime map](regime_results/mean_regime.png)",
        "",
        "## Quantile graft",
        "",
        f"Summary: `{json.dumps(summary['quantile_graft'])}`",
        "",
        "![Quantile graft regime map](regime_results/quantile_regime.png)",
        "",
        "## Spatial transplant",
        "",
        f"Summary: `{json.dumps(summary['spatial_transplant'])}`",
        "",
        "![Spatial transplant regime map](regime_results/spatial_regime.png)",
        "",
        "### Hungarian versus greedy",
        "",
        assignments[
            [
                "matching_noise",
                "assignment",
                "coordinate_rmse",
                "mean_match_distance",
                "sliced_wasserstein",
                "occupancy_dice",
                "neighborhood_mmd",
            ]
        ].to_markdown(index=False),
        "",
        "## Population mixtures",
        "",
        "Whole-cell mixtures have no factor-preservation guarantee. The table varies parent complementarity and alpha directly.",
        "",
        mixtures[
            [
                "complementarity_severity",
                "alpha",
                "primary_wins_vs_both",
                "primary_best_preserved",
                "primary_worse_than_best",
                "primary_losses_vs_both",
                "primary_best_preserved_fraction",
            ]
        ].to_markdown(index=False),
        "",
        "## Raw outputs",
        "",
        "Every grid cell and parent/blend metric is in `regime_results/`. Reproduce with:",
        "",
        "```bash",
        "pip install -r requirements.txt",
        "python regime_map.py --out-dir regime_results",
        "```",
        "",
    ]
    Path("REGIME_RESULTS.md").write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir", type=Path, default=Path(".cache/public_samples")
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("regime_results")
    )
    args = parser.parse_args()

    samples = download_public_samples(args.data_dir)
    with tempfile.TemporaryDirectory(prefix="vec_regime_") as tmp:
        work = Path(tmp)
        baselines = baseline_rows(samples, work)
        mean_rows = t1_mean_regime(samples, work)
        quantile_rows = t1_quantile_regime(samples, work)
        spatial_rows, assignment_rows = t2_spatial_regime(samples, work)
        mixture_rows = mixture_regime(samples, work)

    write_outputs(
        args.out_dir,
        baselines,
        mean_rows,
        quantile_rows,
        spatial_rows,
        assignment_rows,
        mixture_rows,
    )


if __name__ == "__main__":
    main()
