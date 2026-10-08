from __future__ import annotations

import argparse
import itertools
import tempfile
from pathlib import Path

import anndata as ad
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.stats import spearmanr, wasserstein_distance
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors

from regime_map import (
    T1_PRIMARY,
    T2_PRIMARY,
    align_source,
    compare_to_parents,
    gene_shuffle,
    partial_rank_corruption,
    score_pred,
)
from run_lab import (
    VECKIT_COMMIT,
    dense,
    download_public_samples,
    make_like,
    positive_offset,
)
from vec_blender.methods import (
    mean_graft,
    population_mix,
    quantile_graft,
    spatial_transplant,
)

T3_PRIMARY = {
    "de_score": "high",
    "de_direction": "high",
    "severity_slope": "high",
    "mmd_u": "low",
}

GRID_LEVELS = (0.1, 0.3, 0.6)
DIAGNOSTICS = (
    "mean_disagreement",
    "variance_disagreement",
    "covariance_disagreement",
    "marginal_wasserstein",
    "cell_count_log_ratio",
    "spatial_shape_disagreement",
    "assignment_ambiguity",
    "mutual_nn_fraction",
)


def _selected_genes(XA: np.ndarray, XB: np.ndarray, n: int = 48) -> np.ndarray:
    g = XA.shape[1]
    if g <= n:
        return np.arange(g)
    v = np.var(XA, axis=0) + np.var(XB, axis=0)
    return np.sort(np.argpartition(v, -n)[-n:])


def _covariance_disagreement(A: np.ndarray, B: np.ndarray) -> float:
    ca = np.cov(A, rowvar=False)
    cb = np.cov(B, rowvar=False)
    denom = np.linalg.norm(ca, ord="fro") + np.linalg.norm(cb, ord="fro") + 1e-12
    return float(2.0 * np.linalg.norm(ca - cb, ord="fro") / denom)


def _shape_signature(C: np.ndarray) -> np.ndarray:
    C = np.asarray(C, dtype=float)[:, :3]
    C = C - C.mean(axis=0, keepdims=True)
    eig = np.maximum(np.linalg.eigvalsh(np.cov(C, rowvar=False)), 0)
    eig /= eig.sum() + 1e-12
    radius = np.linalg.norm(C, axis=1)
    q = np.quantile(radius / (np.mean(radius) + 1e-12), [0.1, 0.25, 0.5, 0.75, 0.9])
    return np.concatenate([eig, q])


def _assignment_diagnostics(A: np.ndarray, B: np.ndarray) -> tuple[float, float]:
    idx = _selected_genes(A, B, n=64)
    A = A[:, idx]
    B = B[:, idx]
    A0 = A - A.mean(0, keepdims=True)
    B0 = B - B.mean(0, keepdims=True)
    Z = np.vstack([A0, B0])
    scale = Z.std(0)
    scale[scale < 1e-7] = 1.0
    Z /= scale[None, :]
    k = min(16, Z.shape[1], Z.shape[0] - 1)
    if k < 1 or min(len(A), len(B)) < 2:
        return float("nan"), float("nan")
    Z = PCA(n_components=k, random_state=0).fit_transform(Z)
    ZA, ZB = Z[: len(A)], Z[len(A):]
    dist, ind = NearestNeighbors(n_neighbors=2).fit(ZB).kneighbors(ZA)
    ambiguity = float(np.mean(dist[:, 0] / (dist[:, 1] + 1e-12)))
    nearest_b = ind[:, 0]
    nearest_a = NearestNeighbors(n_neighbors=1).fit(ZA).kneighbors(
        ZB, return_distance=False
    )[:, 0]
    mutual = float(np.mean([nearest_a[j] == i for i, j in enumerate(nearest_b)]))
    return ambiguity, mutual


def pair_diagnostics(a: ad.AnnData, b: ad.AnnData) -> dict:
    genes = list(map(str, a.var_names))
    if set(genes) != set(map(str, b.var_names)):
        raise ValueError("diagnostics require the same gene set")
    b = b[:, genes]
    A, B = dense(a), dense(b)
    idx = _selected_genes(A, B)
    As, Bs = A[:, idx], B[:, idx]

    ma, mb = A.mean(0), B.mean(0)
    va, vb = A.var(0), B.var(0)
    mean_scale = np.linalg.norm(0.5 * (ma + mb)) + 1e-12
    ws = [wasserstein_distance(As[:, j], Bs[:, j]) for j in range(As.shape[1])]
    pooled = float(np.mean(np.sqrt(0.5 * (As.var(0) + Bs.var(0)))) + 1e-12)

    out = {
        "mean_disagreement": float(np.linalg.norm(ma - mb) / mean_scale),
        "variance_disagreement": float(
            np.mean(np.abs(np.log((va + 1e-6) / (vb + 1e-6))))
        ),
        "covariance_disagreement": _covariance_disagreement(As, Bs),
        "marginal_wasserstein": float(np.mean(ws) / pooled),
        "cell_count_log_ratio": float(
            abs(np.log((a.n_obs + 1e-12) / (b.n_obs + 1e-12)))
        ),
        "spatial_shape_disagreement": float("nan"),
        "assignment_ambiguity": float("nan"),
        "mutual_nn_fraction": float("nan"),
    }
    if "spatial_3D" in a.obsm and "spatial_3D" in b.obsm:
        sa = _shape_signature(np.asarray(a.obsm["spatial_3D"]))
        sb = _shape_signature(np.asarray(b.obsm["spatial_3D"]))
        out["spatial_shape_disagreement"] = float(np.linalg.norm(sa - sb))
        ambiguity, mutual = _assignment_diagnostics(A, B)
        out["assignment_ambiguity"] = ambiguity
        out["mutual_nn_fraction"] = mutual
    return out


def _mean_parents(target: ad.AnnData, levels=GRID_LEVELS):
    X = dense(target)
    mu = X.mean(0)
    residual = X - mu
    offset = positive_offset(X)
    shuffled = gene_shuffle(X, 1101)
    A = {
        x: make_like(
            target,
            mu[None, :] + 0.25 * residual + x * offset[None, :],
            prefix=f"mean_A_{x}",
        )
        for x in levels
    }
    B = {
        y: make_like(
            target,
            (1 - y) * X + y * shuffled + 1.5 * offset[None, :],
            prefix=f"mean_B_{y}",
        )
        for y in levels
    }
    return A, B


def _quantile_parents(target: ad.AnnData, levels=GRID_LEVELS):
    X = dense(target)
    offset = positive_offset(X)
    scrambled = gene_shuffle(X, 2201)
    g = X.shape[1]
    slope = 0.2 + 0.8 * (np.arange(g) + 1) / g
    bad_scale = 0.65 + 0.7 * (np.arange(g) + 1) / g
    A = {
        x: make_like(
            target,
            scrambled * (1 + x * slope[None, :]) + x * 0.4 * offset[None, :],
            prefix=f"quant_A_{x}",
        )
        for x in levels
    }
    B = {
        y: make_like(
            target,
            partial_rank_corruption(X, y, 2300 + int(y * 1000))
            * bad_scale[None, :]
            + 0.8 * offset[None, :],
            prefix=f"quant_B_{y}",
        )
        for y in levels
    }
    return A, B


def _spatial_parents(target: ad.AnnData, levels=GRID_LEVELS):
    X = dense(target)
    coords = np.asarray(target.obsm["spatial_3D"], dtype=float)[:, :3]
    shuffled = gene_shuffle(X, 3301)
    rng = np.random.default_rng(3302)
    coord_perm = rng.permutation(len(X))
    row_perm = rng.permutation(len(X))
    std = np.std(X, axis=0)
    shift = 0.35 + 0.55 * std
    A = {
        x: make_like(
            target,
            (1 - x) * X + x * shuffled,
            coords=coords[coord_perm],
            prefix=f"spatial_A_{x}",
        )
        for x in levels
    }
    B = {}
    for y in levels:
        noise = np.random.default_rng(3400 + int(y * 1000)).normal(
            scale=y * (0.05 + std), size=X.shape
        )
        expr = np.maximum(X + shift[None, :] + noise, 0)[row_perm]
        B[y] = make_like(
            target, expr, coords=coords[row_perm], prefix=f"spatial_B_{y}"
        )
    return A, B


def _arithmetic_average(
    a: ad.AnnData,
    b: ad.AnnData,
    template: ad.AnnData,
    prefix: str,
    coords=None,
) -> ad.AnnData:
    if a.shape != b.shape:
        raise ValueError("rowwise arithmetic average requires equal shapes")
    X = np.maximum(0.5 * (dense(a) + dense(b)), 0)
    return make_like(template, X, coords=coords, prefix=prefix)


def _partial_mean_shift(
    a: ad.AnnData,
    b: ad.AnnData,
    template: ad.AnnData,
    prefix: str,
    fraction: float = 0.5,
) -> ad.AnnData:
    B = dense(b)
    delta = dense(a).mean(0) - B.mean(0)
    X = np.maximum(B + fraction * delta[None, :], 0)
    coords = (
        np.asarray(b.obsm["spatial_3D"])[:, :3] if "spatial_3D" in b.obsm else None
    )
    return make_like(template, X, coords=coords, prefix=prefix)


def _raw_hungarian_spatial(
    a: ad.AnnData, b: ad.AnnData, template: ad.AnnData, prefix: str
) -> ad.AnnData:
    A, B = dense(a), dense(b)
    idx = _selected_genes(A, B, n=64)
    A, B = A[:, idx], B[:, idx]
    scale = np.vstack([A, B]).std(0)
    scale[scale < 1e-7] = 1.0
    A, B = A / scale[None, :], B / scale[None, :]
    cost = np.maximum(
        np.sum(A * A, 1)[:, None] + np.sum(B * B, 1)[None, :] - 2 * A @ B.T,
        0,
    )
    rows, cols = linear_sum_assignment(cost)
    match = np.empty(len(rows), dtype=int)
    match[rows] = cols
    C = np.asarray(b.obsm["spatial_3D"], dtype=float)[:, :3]
    return make_like(template, dense(a), coords=C[match], prefix=prefix)


def _random_spatial(
    a: ad.AnnData,
    b: ad.AnnData,
    template: ad.AnnData,
    prefix: str,
    seed: int,
) -> ad.AnnData:
    C = np.asarray(b.obsm["spatial_3D"], dtype=float)[:, :3]
    perm = np.random.default_rng(seed).permutation(len(C))
    return make_like(template, dense(a), coords=C[perm], prefix=prefix)


def descriptive_diagnostics(samples: dict[str, Path], regime_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Target-free parent summaries, then descriptive association with scorer outcomes."""
    target1 = ad.read_h5ad(samples["sample_9.5.h5ad"])
    target2 = ad.read_h5ad(samples["sample_heart_9.5.h5ad"])

    def load_rows(method, file_name, keys, Amap, Bmap):
        frame = pd.read_csv(regime_dir / file_name)
        rows = []
        for _, r in frame.iterrows():
            a = Amap[float(r[keys[0]])]
            b = Bmap[float(r[keys[1]])]
            rows.append(
                {
                    "method": method,
                    **{k: r[k] for k in keys},
                    **pair_diagnostics(a, b),
                    "better_parent_preserved_fraction": r[
                        "primary_best_preserved_fraction"
                    ],
                    "strict_win_fraction": r["primary_win_fraction"],
                    "losses_vs_both": r["primary_losses_vs_both"],
                }
            )
        return rows

    mean_levels = (0.0, 0.1, 0.3, 0.6, 1.2)
    residual_levels = (0.0, 0.1, 0.3, 0.6, 1.0)
    marginal_levels = (0.0, 0.1, 0.3, 0.6, 1.2)
    rank_levels = (0.0, 0.1, 0.3, 0.6, 1.0)
    spatial_levels = (0.0, 0.1, 0.3, 0.6, 1.0)

    mean_a, _ = _mean_parents(target1, levels=mean_levels)
    X = dense(target1)
    shuffled = gene_shuffle(X, 1101)
    offset = positive_offset(X)
    mean_b = {
        y: make_like(
            target1,
            (1 - y) * X + y * shuffled + 1.5 * offset[None, :],
            prefix=f"mean_B_{y}",
        )
        for y in residual_levels
    }

    quant_a, _ = _quantile_parents(target1, levels=marginal_levels)
    bad_scale = 0.65 + 0.7 * (np.arange(X.shape[1]) + 1) / X.shape[1]
    quant_b = {
        y: make_like(
            target1,
            partial_rank_corruption(X, y, 2300 + int(y * 1000))
            * bad_scale[None, :]
            + 0.8 * offset[None, :],
            prefix=f"quant_B_{y}",
        )
        for y in rank_levels
    }

    spatial_a, spatial_b = _spatial_parents(target2, levels=spatial_levels)

    rows = []
    rows += load_rows(
        "mean graft",
        "mean_regime.csv",
        ["mean_error_level", "residual_error_level"],
        mean_a,
        mean_b,
    )
    rows += load_rows(
        "quantile graft",
        "quantile_regime.csv",
        ["marginal_error_level", "rank_corruption_fraction"],
        quant_a,
        quant_b,
    )
    rows += load_rows(
        "spatial transplant",
        "spatial_regime.csv",
        ["expression_corruption", "matching_noise"],
        spatial_a,
        spatial_b,
    )
    diag = pd.DataFrame(rows)

    assoc = []
    for method, group in diag.groupby("method"):
        for col in DIAGNOSTICS:
            sub = group[[col, "better_parent_preserved_fraction"]].dropna()
            if len(sub) < 4 or sub[col].nunique() < 2:
                continue
            rho = float(
                spearmanr(sub[col], sub["better_parent_preserved_fraction"]).statistic
            )
            assoc.append(
                {
                    "method": method,
                    "diagnostic": col,
                    "n_grid_points": len(sub),
                    "spearman_rho": rho,
                }
            )
    associations = pd.DataFrame(assoc)

    bins = []
    for method, group in diag.groupby("method"):
        c = associations[associations.method == method]
        if c.empty:
            continue
        top = c.loc[c.spearman_rho.abs().idxmax()]
        col = str(top.diagnostic)
        sub = group[
            [
                col,
                "better_parent_preserved_fraction",
                "strict_win_fraction",
                "losses_vs_both",
            ]
        ].dropna()
        threshold = float(sub[col].median())
        for label, part in (
            ("lower half", sub[sub[col] <= threshold]),
            ("upper half", sub[sub[col] > threshold]),
        ):
            if part.empty:
                continue
            bins.append(
                {
                    "method": method,
                    "diagnostic": col,
                    "grid_median": threshold,
                    "group": label,
                    "n_grid_points": len(part),
                    "mean_better_parent_preserved_fraction": float(
                        part["better_parent_preserved_fraction"].mean()
                    ),
                    "mean_strict_win_fraction": float(part["strict_win_fraction"].mean()),
                    "fraction_with_any_loss_vs_both": float(
                        (part["losses_vs_both"] > 0).mean()
                    ),
                }
            )
    return diag, associations, pd.DataFrame(bins)


def _parent_scores_from_regime(
    regime: pd.DataFrame,
    x_col: str,
    y_col: str,
    x: float,
    y: float,
    metrics: dict,
) -> tuple[dict, dict]:
    r = regime[
        np.isclose(regime[x_col], x) & np.isclose(regime[y_col], y)
    ].iloc[0]
    sa = {m: float(r[f"A_{m}"]) for m in metrics}
    sb = {m: float(r[f"B_{m}"]) for m in metrics}
    return sa, sb


def comparator_grid_study(
    samples: dict[str, Path], regime_dir: Path, work: Path
) -> pd.DataFrame:
    """Compare simple choices on a fixed 3x3 low/medium/high slice."""
    rows = []

    target_path = samples["sample_9.5.h5ad"]
    ref_path = samples["sample_8.5.h5ad"]
    target = ad.read_h5ad(target_path)

    mean_regime = pd.read_csv(regime_dir / "mean_regime.csv")
    Amap, Bmap = _mean_parents(target)
    for x, y in itertools.product(GRID_LEVELS, repeat=2):
        A, B = Amap[x], Bmap[y]
        sa, sb = _parent_scores_from_regime(
            mean_regime,
            "mean_error_level",
            "residual_error_level",
            x,
            y,
            T1_PRIMARY,
        )
        candidates = {
            "mean graft": mean_graft(A, B, clip_min=0).adata,
            "population mix": population_mix(
                A, B, alpha=0.5, n_out=target.n_obs, seed=801
            ).adata,
            "rowwise average": _arithmetic_average(
                A, B, target, f"cmp_mean_avg_{x}_{y}"
            ),
            "half mean shift": _partial_mean_shift(
                A, B, target, f"cmp_mean_shift_{x}_{y}", 0.5
            ),
        }
        for method, pred in candidates.items():
            sc = score_pred(
                pred,
                name=f"cmp_mean_{x}_{y}_{method.replace(' ', '_')}",
                task="T1",
                work=work,
                target=target_path,
                reference=ref_path,
            )
            rows.append(
                {
                    "experiment": "T1 mean/structure",
                    "level_A": x,
                    "level_B": y,
                    "method": method,
                    **compare_to_parents(sa, sb, sc, T1_PRIMARY),
                    **{f"metric_{m}": sc[m] for m in T1_PRIMARY},
                    **{f"A_{m}": sa[m] for m in T1_PRIMARY},
                    **{f"B_{m}": sb[m] for m in T1_PRIMARY},
                }
            )

    quant_regime = pd.read_csv(regime_dir / "quantile_regime.csv")
    Amap, Bmap = _quantile_parents(target)
    for x, y in itertools.product(GRID_LEVELS, repeat=2):
        A, B = Amap[x], Bmap[y]
        sa, sb = _parent_scores_from_regime(
            quant_regime,
            "marginal_error_level",
            "rank_corruption_fraction",
            x,
            y,
            T1_PRIMARY,
        )
        candidates = {
            "quantile graft": quantile_graft(A, B).adata,
            "population mix": population_mix(
                A, B, alpha=0.5, n_out=target.n_obs, seed=802
            ).adata,
            "rowwise average": _arithmetic_average(
                A, B, target, f"cmp_quant_avg_{x}_{y}"
            ),
            "half mean shift": _partial_mean_shift(
                A, B, target, f"cmp_quant_shift_{x}_{y}", 0.5
            ),
        }
        for method, pred in candidates.items():
            sc = score_pred(
                pred,
                name=f"cmp_quant_{x}_{y}_{method.replace(' ', '_')}",
                task="T1",
                work=work,
                target=target_path,
                reference=ref_path,
            )
            rows.append(
                {
                    "experiment": "T1 marginals/ranks",
                    "level_A": x,
                    "level_B": y,
                    "method": method,
                    **compare_to_parents(sa, sb, sc, T1_PRIMARY),
                    **{f"metric_{m}": sc[m] for m in T1_PRIMARY},
                    **{f"A_{m}": sa[m] for m in T1_PRIMARY},
                    **{f"B_{m}": sb[m] for m in T1_PRIMARY},
                }
            )

    target_path = samples["sample_heart_9.5.h5ad"]
    ref_path = samples["sample_heart_9.25.h5ad"]
    target2 = ad.read_h5ad(target_path)
    spatial_regime = pd.read_csv(regime_dir / "spatial_regime.csv")
    Amap, Bmap = _spatial_parents(target2)
    for x, y in itertools.product(GRID_LEVELS, repeat=2):
        A, B = Amap[x], Bmap[y]
        sa, sb = _parent_scores_from_regime(
            spatial_regime,
            "expression_corruption",
            "matching_noise",
            x,
            y,
            T2_PRIMARY,
        )
        candidates = {
            "spatial transplant": spatial_transplant(
                A, B, assignment="hungarian", n_components=24
            ).adata,
            "raw-expression Hungarian": _raw_hungarian_spatial(
                A, B, target2, f"cmp_spatial_raw_{x}_{y}"
            ),
            "random coordinate transfer": _random_spatial(
                A, B, target2, f"cmp_spatial_random_{x}_{y}", seed=803
            ),
            "same-index coordinate transfer": make_like(
                target2,
                dense(A),
                coords=np.asarray(B.obsm["spatial_3D"])[:, :3],
                prefix=f"cmp_spatial_same_{x}_{y}",
            ),
        }
        for method, pred in candidates.items():
            safe_name = method.replace(" ", "_").replace("-", "_")
            sc = score_pred(
                pred,
                name=f"cmp_spatial_{x}_{y}_{safe_name}",
                task="T2",
                work=work,
                target=target_path,
                reference=ref_path,
            )
            rows.append(
                {
                    "experiment": "T2 expression/space",
                    "level_A": x,
                    "level_B": y,
                    "method": method,
                    **compare_to_parents(sa, sb, sc, T2_PRIMARY),
                    **{f"metric_{m}": sc[m] for m in T2_PRIMARY},
                    **{f"A_{m}": sa[m] for m in T2_PRIMARY},
                    **{f"B_{m}": sb[m] for m in T2_PRIMARY},
                }
            )
    return pd.DataFrame(rows)


def _score_controls(
    controls: dict[str, ad.AnnData],
    *,
    task: str,
    work: Path,
    target: Path,
    reference: Path | None = None,
    wt: Path | None = None,
) -> dict[str, dict]:
    return {
        name: score_pred(
            pred,
            name=f"control_{task}_{name}",
            task=task,
            work=work,
            target=target,
            reference=reference,
            wt=wt,
        )
        for name, pred in controls.items()
    }


def organizer_control_pairs(samples: dict[str, Path], work: Path) -> pd.DataFrame:
    """All pairings of organizer-defined controls reconstructible from the mini bundle."""
    rows = []

    target_path = samples["sample_9.5.h5ad"]
    ref_path = samples["sample_8.5.h5ad"]
    target = ad.read_h5ad(target_path)
    ref = align_source(ad.read_h5ad(ref_path), target)
    R = dense(ref)
    t1 = {
        "copy_last": make_like(target, R, prefix="t1_copy"),
        "ctrl_one_cell": make_like(
            target,
            np.repeat(R.mean(0)[None, :], target.n_obs, axis=0),
            prefix="t1_one",
        ),
        "ctrl_scale_ref": make_like(target, 2.0 * R, prefix="t1_scale"),
        "ctrl_shrink_ref": make_like(target, 0.99 * R, prefix="t1_shrink"),
    }
    scores = _score_controls(
        t1, task="T1", work=work, target=target_path, reference=ref_path
    )
    for left, right in itertools.combinations(t1, 2):
        A, B = t1[left], t1[right]
        candidates = {
            "mean graft": mean_graft(A, B, clip_min=0).adata,
            "quantile graft": quantile_graft(A, B).adata,
            "population mix": population_mix(
                A, B, alpha=0.5, n_out=target.n_obs, seed=901
            ).adata,
            "rowwise average": _arithmetic_average(
                A, B, target, f"org_t1_avg_{left}_{right}"
            ),
        }
        for method, pred in candidates.items():
            sc = score_pred(
                pred,
                name=f"org_t1_{left}_{right}_{method.replace(' ', '_')}",
                task="T1",
                work=work,
                target=target_path,
                reference=ref_path,
            )
            rows.append(
                {
                    "task": "T1",
                    "parent_A": left,
                    "parent_B": right,
                    "method": method,
                    **compare_to_parents(scores[left], scores[right], sc, T1_PRIMARY),
                }
            )

    target_path = samples["sample_heart_9.5.h5ad"]
    ref_path = samples["sample_heart_9.25.h5ad"]
    target2 = ad.read_h5ad(target_path)
    ref2 = align_source(ad.read_h5ad(ref_path), target2)
    R2 = dense(ref2)
    C = np.asarray(ref2.obsm["spatial_3D"], dtype=float)[:, :3]
    target_C = np.asarray(target2.obsm["spatial_3D"], dtype=float)[:, :3]
    center = C.mean(0, keepdims=True)
    squashed = (C - center) * np.array([4.0, 1.0, 0.25])[None, :] + center
    lo, hi = target_C.min(0), target_C.max(0)
    cube = np.random.default_rng(0).uniform(lo, hi, size=C.shape)
    t2 = {
        "copy_last": make_like(target2, R2, coords=C, prefix="t2_copy"),
        "ctrl_scale_ref": make_like(target2, 2.0 * R2, coords=C, prefix="t2_scale"),
        "ctrl_squashed_ref": make_like(
            target2, R2, coords=squashed, prefix="t2_squashed"
        ),
        "ctrl_random_cube": make_like(target2, R2, coords=cube, prefix="t2_cube"),
    }
    scores = _score_controls(
        t2, task="T2", work=work, target=target_path, reference=ref_path
    )
    for pair_index, (left, right) in enumerate(itertools.combinations(t2, 2)):
        A, B = t2[left], t2[right]
        candidates = {
            "spatial transplant": spatial_transplant(
                A, B, assignment="hungarian", n_components=24
            ).adata,
            "raw-expression Hungarian": _raw_hungarian_spatial(
                A, B, target2, f"org_t2_raw_{pair_index}"
            ),
            "random coordinate transfer": _random_spatial(
                A, B, target2, f"org_t2_random_{pair_index}", seed=910 + pair_index
            ),
            "same-index coordinate transfer": make_like(
                target2,
                dense(A),
                coords=np.asarray(B.obsm["spatial_3D"])[:, :3],
                prefix=f"org_t2_same_{pair_index}",
            ),
        }
        for method, pred in candidates.items():
            safe_name = method.replace(" ", "_").replace("-", "_")
            sc = score_pred(
                pred,
                name=f"org_t2_{pair_index}_{safe_name}",
                task="T2",
                work=work,
                target=target_path,
                reference=ref_path,
            )
            rows.append(
                {
                    "task": "T2",
                    "parent_A": left,
                    "parent_B": right,
                    "method": method,
                    **compare_to_parents(scores[left], scores[right], sc, T2_PRIMARY),
                }
            )

    target_path = samples["sample_mab21l2_ko.h5ad"]
    wt_path = samples["sample_wt.h5ad"]
    target3 = ad.read_h5ad(target_path)
    wt = align_source(ad.read_h5ad(wt_path), target3)
    W = dense(wt)
    Cwt = (
        np.asarray(wt.obsm["spatial_3D"], dtype=float)[:, :3]
        if "spatial_3D" in wt.obsm
        else None
    )
    true_shift = dense(target3).mean(0) - W.mean(0)
    random_dir = np.random.default_rng(0).normal(size=true_shift.shape)
    random_dir *= np.linalg.norm(true_shift) / (np.linalg.norm(random_dir) + 1e-12)
    random_response = np.maximum(W + random_dir[None, :], 0)
    t3 = {
        "wt_identity": make_like(target3, W, coords=Cwt, prefix="t3_wt"),
        "ctrl_scale_wt": make_like(target3, 2.0 * W, coords=Cwt, prefix="t3_scale"),
        "ctrl_shrink_wt": make_like(
            target3, 0.75 * W, coords=Cwt, prefix="t3_shrink"
        ),
        "ctrl_random_dir": make_like(
            target3, random_response, coords=Cwt, prefix="t3_random_dir"
        ),
    }
    scores = _score_controls(
        t3, task="T3", work=work, target=target_path, wt=wt_path
    )
    for pair_index, (left, right) in enumerate(itertools.combinations(t3, 2)):
        A, B = t3[left], t3[right]
        candidates = {
            "mean graft": mean_graft(A, B, clip_min=0).adata,
            "population mix": population_mix(
                A, B, alpha=0.5, n_out=target3.n_obs, seed=920 + pair_index
            ).adata,
            "rowwise average": _arithmetic_average(
                A, B, target3, f"org_t3_avg_{pair_index}", coords=Cwt
            ),
        }
        for method, pred in candidates.items():
            sc = score_pred(
                pred,
                name=f"org_t3_{pair_index}_{method.replace(' ', '_')}",
                task="T3",
                work=work,
                target=target_path,
                wt=wt_path,
            )
            rows.append(
                {
                    "task": "T3",
                    "parent_A": left,
                    "parent_B": right,
                    "method": method,
                    **compare_to_parents(scores[left], scores[right], sc, T3_PRIMARY),
                }
            )

    return pd.DataFrame(rows)


def metric_transfer_from_comparators(comparators: pd.DataFrame) -> pd.DataFrame:
    rows = []
    experiment_metrics = {
        "T1 mean/structure": T1_PRIMARY,
        "T1 marginals/ranks": T1_PRIMARY,
        "T2 expression/space": T2_PRIMARY,
    }
    for (experiment, method), group in comparators.groupby(["experiment", "method"]):
        metrics = experiment_metrics[experiment]
        for metric, direction in metrics.items():
            a = group[f"A_{metric}"].to_numpy(float)
            b = group[f"B_{metric}"].to_numpy(float)
            c = group[f"metric_{metric}"].to_numpy(float)
            tol = 1e-8 * np.maximum(1.0, np.maximum(np.abs(a), np.abs(b)))
            if direction == "high":
                best, worst = np.maximum(a, b), np.minimum(a, b)
                preserved = c >= best - tol
                beat = c > best + tol
                loss = c < worst - tol
            else:
                best, worst = np.minimum(a, b), np.maximum(a, b)
                preserved = c <= best + tol
                beat = c < best - tol
                loss = c > worst + tol
            rows.append(
                {
                    "experiment": experiment,
                    "method": method,
                    "metric": metric,
                    "n_grid_points": len(group),
                    "preserve_better_parent_fraction": float(np.mean(preserved)),
                    "beat_both_fraction": float(np.mean(beat)),
                    "worse_than_both_fraction": float(np.mean(loss)),
                }
            )
    return pd.DataFrame(rows)


def organizer_summary(organizer: pd.DataFrame) -> pd.DataFrame:
    return (
        organizer.groupby(["task", "method"], as_index=False)
        .agg(
            organizer_pairs_tested=("parent_A", "size"),
            mean_better_parent_preserved_fraction=(
                "primary_best_preserved_fraction",
                "mean",
            ),
            fraction_with_any_strict_win=(
                "primary_wins_vs_both",
                lambda x: float(np.mean(np.asarray(x) > 0)),
            ),
            fraction_with_any_loss_vs_both=(
                "primary_losses_vs_both",
                lambda x: float(np.mean(np.asarray(x) > 0)),
            ),
        )
        .sort_values(["task", "method"])
    )


def plot_associations(
    diag: pd.DataFrame, associations: pd.DataFrame, out_dir: Path
) -> None:
    for method, group in associations.groupby("method"):
        top = group.loc[group.spearman_rho.abs().idxmax()]
        col = str(top.diagnostic)
        sub = diag[diag.method == method][
            [col, "better_parent_preserved_fraction"]
        ].dropna()
        fig, ax = plt.subplots(figsize=(5.5, 4.1))
        ax.scatter(sub[col], sub["better_parent_preserved_fraction"])
        ax.set_xlabel(col.replace("_", " "))
        ax.set_ylabel("fraction of primary metrics matching better parent")
        ax.set_ylim(-0.05, 1.05)
        ax.set_title(method)
        fig.tight_layout()
        fig.savefig(
            out_dir / f"association_{method.replace(' ', '_')}.png", dpi=160
        )
        plt.close(fig)


def write_report(
    out_dir: Path,
    diag: pd.DataFrame,
    associations: pd.DataFrame,
    bins: pd.DataFrame,
    comparators: pd.DataFrame,
    transfer: pd.DataFrame,
    organizer: pd.DataFrame,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    diag.to_csv(out_dir / "parent_diagnostics.csv", index=False)
    associations.to_csv(out_dir / "diagnostic_associations.csv", index=False)
    bins.to_csv(out_dir / "diagnostic_halves.csv", index=False)
    comparators.to_csv(out_dir / "comparison_grid.csv", index=False)
    transfer.to_csv(out_dir / "metric_transfer_matrix.csv", index=False)
    organizer.to_csv(out_dir / "organizer_control_pairs.csv", index=False)

    summary = organizer_summary(organizer)
    summary.to_csv(out_dir / "organizer_control_summary.csv", index=False)
    plot_associations(diag, associations, out_dir)

    top_assoc = (
        associations.assign(abs_rho=associations.spearman_rho.abs())
        .sort_values(["method", "abs_rho"], ascending=[True, False])
        .groupby("method")
        .head(2)
    )

    transfer_table = transfer.pivot_table(
        index=["experiment", "method"],
        columns="metric",
        values="preserve_better_parent_fraction",
    )

    md = [
        "# Ensemble Atlas results",
        "",
        f"Scorer pinned to `aristoteleo/veckit@{VECKIT_COMMIT}`.",
        "",
        "The public mini targets are used to score outcomes. The parent diagnostics below use only the two prediction files.",
        "",
        "## Parent differences and ensemble results",
        "",
        "These Spearman correlations are descriptive. The 25 points in each controlled grid reuse the same five A variants and five B variants, so they are not independent samples and no inferential p-values are reported.",
        "",
        top_assoc[["method", "diagnostic", "n_grid_points", "spearman_rho"]]
        .round(3)
        .to_markdown(index=False),
        "",
        "The numeric cutoffs in `diagnostic_halves.csv` are medians of these controlled grids. They show the direction of the relationship in this experiment; they are not universal thresholds.",
        "",
        "## Simple methods across a fixed 3×3 grid",
        "",
        "Each comparison method is run at all nine combinations of low (0.1), medium (0.3), and high (0.6) error in the existing controlled experiments.",
        "",
        transfer_table.round(3).to_markdown(),
        "",
        "The table reports the fraction of the nine grid points where a method matched or beat the better parent on each metric.",
        "",
        "## Organizer-defined controls",
        "",
        "All six pairs are tested for each task using four organizer-defined rows that can be reconstructed from the public mini bundle:",
        "",
        "- T1: `copy_last`, `ctrl_one_cell`, `ctrl_scale_ref`, `ctrl_shrink_ref`",
        "- T2: `copy_last`, `ctrl_scale_ref`, `ctrl_squashed_ref`, `ctrl_random_cube`",
        "- T3: `wt_identity`, `ctrl_scale_wt`, `ctrl_shrink_wt`, `ctrl_random_dir`",
        "",
        summary.round(3).to_markdown(index=False),
        "",
        "These controls were defined by the organizers for scorer stress testing. They were not designed around the ensemble methods here.",
        "",
        "The public mini bundle does not contain the two earlier stages needed to reconstruct `pseudobulk_shift` honestly, or a second knockout for a non-leaking `shift_transfer` test. Those published baselines are left out rather than approximated.",
        "",
        "## Raw outputs",
        "",
        "Every pair, metric, and method is in `atlas_results/`.",
        "",
        "```bash",
        "pip install -r requirements.txt",
        "python regime_map.py --out-dir regime_results",
        "python ensemble_atlas.py --regime-dir regime_results --out-dir atlas_results",
        "```",
        "",
    ]
    Path("ATLAS_RESULTS.md").write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir", type=Path, default=Path(".cache/public_samples")
    )
    parser.add_argument(
        "--regime-dir", type=Path, default=Path("regime_results")
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("atlas_results")
    )
    args = parser.parse_args()

    samples = download_public_samples(args.data_dir)
    diag, associations, bins = descriptive_diagnostics(samples, args.regime_dir)

    with tempfile.TemporaryDirectory(prefix="vec_atlas_") as tmp:
        work = Path(tmp)
        comparators = comparator_grid_study(samples, args.regime_dir, work)
        organizer = organizer_control_pairs(samples, work)

    transfer = metric_transfer_from_comparators(comparators)
    write_report(
        args.out_dir,
        diag,
        associations,
        bins,
        comparators,
        transfer,
        organizer,
    )


if __name__ == "__main__":
    main()
