from __future__ import annotations

import argparse
import json
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
    MARGINAL_LEVELS,
    MEAN_LEVELS,
    RANK_LEVELS,
    RESIDUAL_LEVELS,
    SPATIAL_EXPRESSION_LEVELS,
    SPATIAL_NOISE_LEVELS,
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


DIAGNOSTIC_COLUMNS = [
    "mean_disagreement",
    "variance_disagreement",
    "covariance_disagreement",
    "marginal_wasserstein",
    "cell_count_log_ratio",
    "spatial_shape_disagreement",
    "assignment_ambiguity",
    "mutual_nn_fraction",
]


def _selected_genes(XA: np.ndarray, XB: np.ndarray, n: int = 48) -> np.ndarray:
    g = XA.shape[1]
    if g <= n:
        return np.arange(g)
    va = np.var(XA, axis=0)
    vb = np.var(XB, axis=0)
    idx = np.argpartition(va + vb, -n)[-n:]
    return np.sort(idx)


def _covariance_disagreement(A: np.ndarray, B: np.ndarray) -> float:
    ca = np.cov(A, rowvar=False)
    cb = np.cov(B, rowvar=False)
    denom = np.linalg.norm(ca, ord="fro") + np.linalg.norm(cb, ord="fro") + 1e-12
    return float(2.0 * np.linalg.norm(ca - cb, ord="fro") / denom)


def _shape_signature(C: np.ndarray) -> np.ndarray:
    C = np.asarray(C, dtype=float)[:, :3]
    C = C - C.mean(axis=0, keepdims=True)
    eig = np.linalg.eigvalsh(np.cov(C, rowvar=False))
    eig = np.maximum(eig, 0)
    scale = eig.sum() + 1e-12
    eig = eig / scale
    radius = np.linalg.norm(C, axis=1)
    q = np.quantile(radius / (np.mean(radius) + 1e-12), [0.1, 0.25, 0.5, 0.75, 0.9])
    return np.concatenate([eig, q])


def _assignment_diagnostics(A: np.ndarray, B: np.ndarray) -> tuple[float, float]:
    idx = _selected_genes(A, B, n=64)
    A = A[:, idx]
    B = B[:, idx]
    A0 = A - A.mean(axis=0, keepdims=True)
    B0 = B - B.mean(axis=0, keepdims=True)
    Z = np.vstack([A0, B0])
    s = Z.std(axis=0)
    s[s < 1e-7] = 1.0
    Z = Z / s[None, :]
    k = min(16, Z.shape[1], Z.shape[0] - 1)
    if k < 1 or min(len(A), len(B)) < 2:
        return float("nan"), float("nan")
    Z = PCA(n_components=k, random_state=0).fit_transform(Z)
    ZA, ZB = Z[: len(A)], Z[len(A) :]
    nn_ab = NearestNeighbors(n_neighbors=2).fit(ZB)
    dist, ind = nn_ab.kneighbors(ZA)
    ambiguity = float(np.mean(dist[:, 0] / (dist[:, 1] + 1e-12)))
    nearest_b = ind[:, 0]
    nearest_a = NearestNeighbors(n_neighbors=1).fit(ZA).kneighbors(ZB, return_distance=False)[:, 0]
    mutual = np.mean([nearest_a[j] == i for i, j in enumerate(nearest_b)])
    return ambiguity, float(mutual)


def pair_diagnostics(a: ad.AnnData, b: ad.AnnData) -> dict:
    genes = list(map(str, a.var_names))
    if set(genes) != set(map(str, b.var_names)):
        raise ValueError("diagnostics require the same gene set")
    b = b[:, genes]
    A, B = dense(a), dense(b)
    idx = _selected_genes(A, B)
    As, Bs = A[:, idx], B[:, idx]
    ma, mb = A.mean(axis=0), B.mean(axis=0)
    va, vb = A.var(axis=0), B.var(axis=0)

    mean_scale = np.linalg.norm(0.5 * (ma + mb)) + 1e-12
    mean_disagreement = float(np.linalg.norm(ma - mb) / mean_scale)
    variance_disagreement = float(np.mean(np.abs(np.log((va + 1e-6) / (vb + 1e-6)))))
    cov_disagreement = _covariance_disagreement(As, Bs)
    ws = [wasserstein_distance(As[:, j], Bs[:, j]) for j in range(As.shape[1])]
    pooled_scale = float(np.mean(np.sqrt(0.5 * (As.var(0) + Bs.var(0)))) + 1e-12)
    marginal_ws = float(np.mean(ws) / pooled_scale)

    out = {
        "mean_disagreement": mean_disagreement,
        "variance_disagreement": variance_disagreement,
        "covariance_disagreement": cov_disagreement,
        "marginal_wasserstein": marginal_ws,
        "cell_count_log_ratio": float(abs(np.log((a.n_obs + 1e-12) / (b.n_obs + 1e-12)))),
        "spatial_shape_disagreement": float("nan"),
        "assignment_ambiguity": float("nan"),
        "mutual_nn_fraction": float("nan"),
    }

    if "spatial_3D" in a.obsm and "spatial_3D" in b.obsm:
        sa = _shape_signature(np.asarray(a.obsm["spatial_3D"]))
        sb = _shape_signature(np.asarray(b.obsm["spatial_3D"]))
        out["spatial_shape_disagreement"] = float(np.linalg.norm(sa - sb))
        amb, mutual = _assignment_diagnostics(A, B)
        out["assignment_ambiguity"] = amb
        out["mutual_nn_fraction"] = mutual
    return out


def _mean_parents(target: ad.AnnData):
    X = dense(target)
    mu = X.mean(0)
    residual = X - mu
    offset = positive_offset(X)
    shuffled = gene_shuffle(X, 1101)
    donors = {
        level: make_like(target, mu[None, :] + 0.25 * residual + level * offset[None, :], prefix=f"mean_A_{level}")
        for level in MEAN_LEVELS
    }
    carriers = {
        level: make_like(target, (1 - level) * X + level * shuffled + 1.5 * offset[None, :], prefix=f"mean_B_{level}")
        for level in RESIDUAL_LEVELS
    }
    return donors, carriers


def _quantile_parents(target: ad.AnnData):
    X = dense(target)
    offset = positive_offset(X)
    scrambled = gene_shuffle(X, 2201)
    g = X.shape[1]
    slope = 0.2 + 0.8 * (np.arange(g) + 1) / g
    bad_scale = 0.65 + 0.7 * (np.arange(g) + 1) / g
    donors = {
        level: make_like(target, scrambled * (1 + level * slope[None, :]) + level * 0.4 * offset[None, :], prefix=f"quant_A_{level}")
        for level in MARGINAL_LEVELS
    }
    carriers = {
        level: make_like(
            target,
            partial_rank_corruption(X, level, 2300 + int(level * 1000)) * bad_scale[None, :] + 0.8 * offset[None, :],
            prefix=f"quant_B_{level}",
        )
        for level in RANK_LEVELS
    }
    return donors, carriers


def _spatial_parents(target: ad.AnnData):
    X = dense(target)
    coords = np.asarray(target.obsm["spatial_3D"], dtype=float)[:, :3]
    shuffled = gene_shuffle(X, 3301)
    rng = np.random.default_rng(3302)
    coord_perm = rng.permutation(len(X))
    row_perm = rng.permutation(len(X))
    std = np.std(X, axis=0)
    shift = 0.35 + 0.55 * std
    donors = {
        level: make_like(target, (1 - level) * X + level * shuffled, coords=coords[coord_perm], prefix=f"spatial_A_{level}")
        for level in SPATIAL_EXPRESSION_LEVELS
    }
    carriers = {}
    for level in SPATIAL_NOISE_LEVELS:
        noise_rng = np.random.default_rng(3400 + int(level * 1000))
        noise = noise_rng.normal(scale=level * (0.05 + std), size=X.shape)
        expression = np.maximum(X + shift[None, :] + noise, 0)[row_perm]
        carriers[level] = make_like(target, expression, coords=coords[row_perm], prefix=f"spatial_B_{level}")
    return donors, carriers


def _mixture_parents(target: ad.AnnData):
    X = dense(target)
    mu = X.mean(0)
    residual = X - mu
    offset = positive_offset(X)
    shuffled = gene_shuffle(X, 4401)
    out = {}
    for severity in (0.25, 0.5, 0.75):
        A = make_like(target, mu[None, :] + (1 - severity) * residual + 0.1 * offset[None, :], prefix=f"mix_A_{severity}")
        B = make_like(target, (1 - 0.15 * severity) * X + 0.15 * severity * shuffled + (1.4 * severity) * offset[None, :], prefix=f"mix_B_{severity}")
        out[severity] = (A, B)
    return out


def diagnostic_table(samples: dict[str, Path], regime_dir: Path) -> pd.DataFrame:
    target_t1 = ad.read_h5ad(samples["sample_9.5.h5ad"])
    target_t2 = ad.read_h5ad(samples["sample_heart_9.5.h5ad"])
    mean_a, mean_b = _mean_parents(target_t1)
    quant_a, quant_b = _quantile_parents(target_t1)
    spatial_a, spatial_b = _spatial_parents(target_t2)
    mix = _mixture_parents(target_t1)

    chunks = []
    specs = [
        ("mean_graft", "mean_regime.csv", ["mean_error_level", "residual_error_level"], mean_a, mean_b),
        ("quantile_graft", "quantile_regime.csv", ["marginal_error_level", "rank_corruption_fraction"], quant_a, quant_b),
        ("spatial_transplant", "spatial_regime.csv", ["expression_corruption", "matching_noise"], spatial_a, spatial_b),
    ]
    for method, filename, keys, Amap, Bmap in specs:
        df = pd.read_csv(regime_dir / filename)
        rows = []
        for _, r in df.iterrows():
            a, b = Amap[float(r[keys[0]])], Bmap[float(r[keys[1]])]
            rows.append({"method": method, **{k: r[k] for k in keys}, **pair_diagnostics(a, b), "success_fraction": r["primary_best_preserved_fraction"], "strict_win_fraction": r["primary_win_fraction"], "losses_vs_both": r["primary_losses_vs_both"]})
        chunks.append(pd.DataFrame(rows))

    df = pd.read_csv(regime_dir / "mixture_regime.csv")
    rows = []
    for _, r in df.iterrows():
        a, b = mix[float(r["complementarity_severity"])]
        rows.append({"method": "population_mix", "complementarity_severity": r["complementarity_severity"], "alpha": r["alpha"], **pair_diagnostics(a, b), "success_fraction": r["primary_best_preserved_fraction"], "strict_win_fraction": r["primary_win_fraction"], "losses_vs_both": r["primary_losses_vs_both"]})
    chunks.append(pd.DataFrame(rows))
    return pd.concat(chunks, ignore_index=True, sort=False)


def diagnostic_correlations(diag: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for method, group in diag.groupby("method"):
        for col in DIAGNOSTIC_COLUMNS:
            sub = group[[col, "success_fraction"]].dropna()
            if len(sub) < 4 or sub[col].nunique() < 2:
                continue
            rho, p = spearmanr(sub[col], sub["success_fraction"])
            rows.append({"method": method, "diagnostic": col, "n": len(sub), "spearman_rho": float(rho), "p_value": float(p)})
    return pd.DataFrame(rows)


def decision_bins(diag: pd.DataFrame, corr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for method, cgroup in corr.groupby("method"):
        top = cgroup.reindex(cgroup.spearman_rho.abs().sort_values(ascending=False).index).head(2)
        mgroup = diag[diag.method == method]
        for _, cr in top.iterrows():
            col = cr.diagnostic
            sub = mgroup[[col, "success_fraction", "strict_win_fraction", "losses_vs_both"]].dropna()
            if len(sub) < 4:
                continue
            threshold = float(sub[col].median())
            for label, part in (("low", sub[sub[col] <= threshold]), ("high", sub[sub[col] > threshold])):
                if len(part) == 0:
                    continue
                rows.append({
                    "method": method,
                    "diagnostic": col,
                    "threshold_median": threshold,
                    "bin": label,
                    "n": len(part),
                    "mean_best_preserved_fraction": float(part.success_fraction.mean()),
                    "mean_strict_win_fraction": float(part.strict_win_fraction.mean()),
                    "failure_rate_any_loss_vs_both": float((part.losses_vs_both > 0).mean()),
                })
    return pd.DataFrame(rows)


def plot_top_diagnostics(diag: pd.DataFrame, corr: pd.DataFrame, out_dir: Path) -> None:
    for method, cgroup in corr.groupby("method"):
        top = cgroup.reindex(cgroup.spearman_rho.abs().sort_values(ascending=False).index).head(1)
        if len(top) == 0:
            continue
        col = str(top.iloc[0].diagnostic)
        sub = diag[diag.method == method][[col, "success_fraction"]].dropna()
        fig, ax = plt.subplots(figsize=(5.6, 4.2))
        ax.scatter(sub[col], sub.success_fraction)
        ax.set_xlabel(col.replace("_", " "))
        ax.set_ylabel("fraction of primary metrics preserving better parent")
        ax.set_ylim(-0.05, 1.05)
        ax.set_title(method.replace("_", " "))
        fig.tight_layout()
        fig.savefig(out_dir / f"diagnostic_{method}.png", dpi=160)
        plt.close(fig)


def metric_transfer(regime_dir: Path) -> pd.DataFrame:
    specs = [
        ("mean_graft", "mean_regime.csv", T1_PRIMARY),
        ("quantile_graft", "quantile_regime.csv", T1_PRIMARY),
        ("population_mix", "mixture_regime.csv", T1_PRIMARY),
        ("spatial_transplant", "spatial_regime.csv", T2_PRIMARY),
    ]
    rows = []
    for method, filename, metrics in specs:
        df = pd.read_csv(regime_dir / filename)
        for metric, direction in metrics.items():
            a, b, c = df[f"A_{metric}"].to_numpy(float), df[f"B_{metric}"].to_numpy(float), df[f"blend_{metric}"].to_numpy(float)
            scale = np.maximum(1.0, np.maximum(np.abs(a), np.abs(b)))
            tol = 1e-8 * scale
            if direction == "high":
                best, worst = np.maximum(a, b), np.minimum(a, b)
                preserved = c >= best - tol
                beat = c > best + tol
                loss = c < worst - tol
                signed = (c - best) / scale
            else:
                best, worst = np.minimum(a, b), np.maximum(a, b)
                preserved = c <= best + tol
                beat = c < best - tol
                loss = c > worst + tol
                signed = (best - c) / scale
            rows.append({
                "method": method,
                "metric": metric,
                "n": len(df),
                "preserve_better_parent_fraction": float(np.mean(preserved)),
                "beat_both_fraction": float(np.mean(beat)),
                "worse_than_both_fraction": float(np.mean(loss)),
                "mean_signed_gain_over_better_parent": float(np.mean(signed)),
            })
    return pd.DataFrame(rows)


def _arithmetic_average(a: ad.AnnData, b: ad.AnnData, template: ad.AnnData, prefix: str, coords=None) -> ad.AnnData:
    if a.shape != b.shape:
        raise ValueError("rowwise arithmetic average requires equal shapes")
    X = 0.5 * (dense(a) + dense(b))
    return make_like(template, np.maximum(X, 0), coords=coords, prefix=prefix)


def _partial_mean_shift(a: ad.AnnData, b: ad.AnnData, template: ad.AnnData, prefix: str, fraction: float = 0.5) -> ad.AnnData:
    B = dense(b)
    delta = dense(a).mean(0) - B.mean(0)
    X = np.maximum(B + fraction * delta[None, :], 0)
    coords = np.asarray(b.obsm["spatial_3D"])[:, :3] if "spatial_3D" in b.obsm else None
    return make_like(template, X, coords=coords, prefix=prefix)


def _raw_hungarian_spatial(a: ad.AnnData, b: ad.AnnData, template: ad.AnnData, prefix: str) -> ad.AnnData:
    A, B = dense(a), dense(b)
    idx = _selected_genes(A, B, n=64)
    A, B = A[:, idx], B[:, idx]
    scale = np.vstack([A, B]).std(0)
    scale[scale < 1e-7] = 1.0
    A, B = A / scale[None, :], B / scale[None, :]
    aa = np.sum(A * A, 1)[:, None]
    bb = np.sum(B * B, 1)[None, :]
    cost = np.maximum(aa + bb - 2 * A @ B.T, 0)
    rows, cols = linear_sum_assignment(cost)
    match = np.empty(len(rows), dtype=int)
    match[rows] = cols
    C = np.asarray(b.obsm["spatial_3D"], dtype=float)[:, :3]
    return make_like(template, dense(a), coords=C[match], prefix=prefix)


def _random_spatial(a: ad.AnnData, b: ad.AnnData, template: ad.AnnData, prefix: str, seed: int = 0) -> ad.AnnData:
    rng = np.random.default_rng(seed)
    C = np.asarray(b.obsm["spatial_3D"], dtype=float)[:, :3]
    return make_like(template, dense(a), coords=C[rng.permutation(len(C))], prefix=prefix)


def simple_comparator_study(samples: dict[str, Path], work: Path) -> pd.DataFrame:
    rows = []

    # T1 mean-complementarity pair: imperfect on both sides.
    target_path, ref_path = samples["sample_9.5.h5ad"], samples["sample_8.5.h5ad"]
    target = ad.read_h5ad(target_path)
    Amap, Bmap = _mean_parents(target)
    A, B = Amap[0.3], Bmap[0.3]
    sa = score_pred(A, name="cmp_mean_A", task="T1", work=work, target=target_path, reference=ref_path)
    sb = score_pred(B, name="cmp_mean_B", task="T1", work=work, target=target_path, reference=ref_path)
    candidates = {
        "mean_graft": mean_graft(A, B, clip_min=0).adata,
        "population_mix_0.5": population_mix(A, B, alpha=0.5, n_out=target.n_obs, seed=8).adata,
        "rowwise_average": _arithmetic_average(A, B, target, "cmp_avg"),
        "half_pseudobulk_shift": _partial_mean_shift(A, B, target, "cmp_half_shift", 0.5),
    }
    for method, pred in candidates.items():
        sc = score_pred(pred, name=f"cmp_mean_{method}", task="T1", work=work, target=target_path, reference=ref_path)
        rows.append({"experiment": "T1_mean_pair", "method": method, **compare_to_parents(sa, sb, sc, T1_PRIMARY), **{k: sc[k] for k in T1_PRIMARY}})

    # T1 quantile pair.
    Amap, Bmap = _quantile_parents(target)
    A, B = Amap[0.3], Bmap[0.3]
    sa = score_pred(A, name="cmp_quant_A", task="T1", work=work, target=target_path, reference=ref_path)
    sb = score_pred(B, name="cmp_quant_B", task="T1", work=work, target=target_path, reference=ref_path)
    candidates = {
        "quantile_graft": quantile_graft(A, B).adata,
        "population_mix_0.5": population_mix(A, B, alpha=0.5, n_out=target.n_obs, seed=9).adata,
        "rowwise_average": _arithmetic_average(A, B, target, "cmp_quant_avg"),
        "half_pseudobulk_shift": _partial_mean_shift(A, B, target, "cmp_quant_shift", 0.5),
    }
    for method, pred in candidates.items():
        sc = score_pred(pred, name=f"cmp_quant_{method}", task="T1", work=work, target=target_path, reference=ref_path)
        rows.append({"experiment": "T1_quantile_pair", "method": method, **compare_to_parents(sa, sb, sc, T1_PRIMARY), **{k: sc[k] for k in T1_PRIMARY}})

    # T2 spatial pair.
    target_path, ref_path = samples["sample_heart_9.5.h5ad"], samples["sample_heart_9.25.h5ad"]
    target2 = ad.read_h5ad(target_path)
    Amap, Bmap = _spatial_parents(target2)
    A, B = Amap[0.3], Bmap[0.6]
    sa = score_pred(A, name="cmp_spatial_A", task="T2", work=work, target=target_path, reference=ref_path)
    sb = score_pred(B, name="cmp_spatial_B", task="T2", work=work, target=target_path, reference=ref_path)
    candidates = {
        "spatial_transplant": spatial_transplant(A, B, assignment="hungarian", n_components=24).adata,
        "raw_expression_hungarian": _raw_hungarian_spatial(A, B, target2, "cmp_raw_hungarian"),
        "random_coordinate_transfer": _random_spatial(A, B, target2, "cmp_random", 11),
        "same_index_coordinate_transfer": make_like(target2, dense(A), coords=np.asarray(B.obsm["spatial_3D"])[:, :3], prefix="cmp_same_index"),
    }
    for method, pred in candidates.items():
        sc = score_pred(pred, name=f"cmp_spatial_{method}", task="T2", work=work, target=target_path, reference=ref_path)
        rows.append({"experiment": "T2_spatial_pair", "method": method, **compare_to_parents(sa, sb, sc, T2_PRIMARY), **{k: sc[k] for k in T2_PRIMARY}})

    return pd.DataFrame(rows)


def organizer_reference_pair_study(samples: dict[str, Path], work: Path) -> pd.DataFrame:
    """Pairs reconstructible from the public mini bundle and organizer reference-row definitions."""
    rows = []

    # T1 organizer reference rows: copy_last, ctrl_one_cell, ctrl_scale_ref, ctrl_shrink_ref.
    target_path, ref_path = samples["sample_9.5.h5ad"], samples["sample_8.5.h5ad"]
    target = ad.read_h5ad(target_path)
    ref = align_source(ad.read_h5ad(ref_path), target)
    R = dense(ref)
    refs = {
        "copy_last": make_like(target, R, prefix="ref_copy_last"),
        "ctrl_one_cell": make_like(target, np.repeat(R.mean(0)[None, :], target.n_obs, axis=0), prefix="ref_one_cell"),
        "ctrl_scale_ref": make_like(target, 2.0 * R, prefix="ref_scale"),
        "ctrl_shrink_ref": make_like(target, 0.99 * R, prefix="ref_shrink"),
    }
    for left, right in (("copy_last", "ctrl_one_cell"), ("copy_last", "ctrl_scale_ref"), ("ctrl_one_cell", "ctrl_scale_ref")):
        A, B = refs[left], refs[right]
        sa = score_pred(A, name=f"org_{left}", task="T1", work=work, target=target_path, reference=ref_path)
        sb = score_pred(B, name=f"org_{right}", task="T1", work=work, target=target_path, reference=ref_path)
        candidates = {
            "mean_graft": mean_graft(A, B, clip_min=0).adata,
            "quantile_graft": quantile_graft(A, B).adata,
            "population_mix_0.5": population_mix(A, B, alpha=0.5, n_out=target.n_obs, seed=13).adata,
            "rowwise_average": _arithmetic_average(A, B, target, f"org_avg_{left}_{right}"),
        }
        for method, pred in candidates.items():
            sc = score_pred(pred, name=f"org_{left}_{right}_{method}", task="T1", work=work, target=target_path, reference=ref_path)
            rows.append({"task": "T1", "parent_A": left, "parent_B": right, "method": method, **compare_to_parents(sa, sb, sc, T1_PRIMARY), **{k: sc[k] for k in T1_PRIMARY}})

    # T2: ctrl_scale_ref has bad expression but original geometry; ctrl_squashed_ref has reference expression but bad geometry.
    target_path, ref_path = samples["sample_heart_9.5.h5ad"], samples["sample_heart_9.25.h5ad"]
    target2 = ad.read_h5ad(target_path)
    ref2 = align_source(ad.read_h5ad(ref_path), target2)
    R2 = dense(ref2)
    C = np.asarray(ref2.obsm["spatial_3D"], dtype=float)[:, :3]
    center = C.mean(0, keepdims=True)
    squashed = (C - center) * np.array([4.0, 1.0, 0.25])[None, :] + center
    A = make_like(target2, 2.0 * R2, coords=C, prefix="org_t2_scale")
    B = make_like(target2, R2, coords=squashed, prefix="org_t2_squash")
    sa = score_pred(A, name="org_t2_scale", task="T2", work=work, target=target_path, reference=ref_path)
    sb = score_pred(B, name="org_t2_squash", task="T2", work=work, target=target_path, reference=ref_path)
    candidates = {
        "spatial_transplant": spatial_transplant(B, A, assignment="hungarian", n_components=24).adata,
        "random_coordinate_transfer": _random_spatial(B, A, target2, "org_t2_random", 21),
        "same_index_coordinate_transfer": make_like(target2, dense(B), coords=C, prefix="org_t2_same"),
    }
    for method, pred in candidates.items():
        sc = score_pred(pred, name=f"org_t2_{method}", task="T2", work=work, target=target_path, reference=ref_path)
        rows.append({"task": "T2", "parent_A": "ctrl_scale_ref", "parent_B": "ctrl_squashed_ref", "method": method, **compare_to_parents(sa, sb, sc, T2_PRIMARY), **{k: sc[k] for k in T2_PRIMARY}})

    # T3: wt_identity versus ctrl_scale_wt.
    target_path, wt_path = samples["sample_mab21l2_ko.h5ad"], samples["sample_wt.h5ad"]
    target3 = ad.read_h5ad(target_path)
    wt = align_source(ad.read_h5ad(wt_path), target3)
    Cwt = np.asarray(wt.obsm["spatial_3D"])[:, :3] if "spatial_3D" in wt.obsm else None
    A = make_like(target3, dense(wt), coords=Cwt, prefix="org_wt")
    B = make_like(target3, 2.0 * dense(wt), coords=Cwt, prefix="org_scale_wt")
    sa = score_pred(A, name="org_wt_identity", task="T3", work=work, target=target_path, wt=wt_path)
    sb = score_pred(B, name="org_ctrl_scale_wt", task="T3", work=work, target=target_path, wt=wt_path)
    t3_primary = {"de_score": "high", "de_direction": "high", "severity_slope": "high", "mmd_u": "low", "variogram": "low"}
    for method, pred in {
        "mean_graft": mean_graft(A, B, clip_min=0).adata,
        "population_mix_0.5": population_mix(A, B, alpha=0.5, n_out=target3.n_obs, seed=31).adata,
        "rowwise_average": _arithmetic_average(A, B, target3, "org_t3_avg", coords=Cwt),
    }.items():
        sc = score_pred(pred, name=f"org_t3_{method}", task="T3", work=work, target=target_path, wt=wt_path)
        rows.append({"task": "T3", "parent_A": "wt_identity", "parent_B": "ctrl_scale_wt", "method": method, **compare_to_parents(sa, sb, sc, t3_primary), **{k: sc[k] for k in t3_primary}})

    return pd.DataFrame(rows)


def write_report(out_dir: Path, diag: pd.DataFrame, corr: pd.DataFrame, bins: pd.DataFrame, transfer: pd.DataFrame, comparators: pd.DataFrame, organizer: pd.DataFrame) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    diag.to_csv(out_dir / "parent_diagnostics.csv", index=False)
    corr.to_csv(out_dir / "diagnostic_correlations.csv", index=False)
    bins.to_csv(out_dir / "diagnostic_bins.csv", index=False)
    transfer.to_csv(out_dir / "metric_transfer_matrix.csv", index=False)
    comparators.to_csv(out_dir / "simple_comparators.csv", index=False)
    organizer.to_csv(out_dir / "organizer_reference_pairs.csv", index=False)
    plot_top_diagnostics(diag, corr, out_dir)

    transfer_pivot = transfer.pivot(index="method", columns="metric", values="preserve_better_parent_fraction")
    comp_cols = ["experiment", "method", "primary_best_preserved_fraction", "primary_win_fraction", "primary_losses_vs_both"]
    org_cols = ["task", "parent_A", "parent_B", "method", "primary_best_preserved_fraction", "primary_win_fraction", "primary_losses_vs_both"]
    corr_show = corr.copy()
    corr_show["abs_rho"] = corr_show.spearman_rho.abs()
    corr_show = corr_show.sort_values(["method", "abs_rho"], ascending=[True, False]).groupby("method").head(3)

    md = [
        "# Ensemble Atlas",
        "",
        f"Scorer pinned to `aristoteleo/veckit@{VECKIT_COMMIT}`.",
        "",
        "This is the behavior study around ensembling, separate from the Blender implementation. The public mini targets are used only to measure outcomes after the ensemble is formed. Parent diagnostics use the two prediction files alone.",
        "",
        "## Metric transfer matrix",
        "",
        "Each entry is the fraction of tested regimes where the method matched or beat the better parent on that metric. This makes tradeoffs visible instead of hiding them in one scalar score.",
        "",
        transfer_pivot.round(3).to_markdown(),
        "",
        "## Target-free parent diagnostics",
        "",
        "Diagnostics include mean disagreement, variance/covariance disagreement, marginal Wasserstein distance, cell-count mismatch, and for spatial pairs, expression-matching ambiguity and mutual-nearest-neighbor rate. The table below shows the three strongest Spearman associations per method with preservation of the better parent's primary metrics.",
        "",
        corr_show[["method", "diagnostic", "n", "spearman_rho", "p_value"]].round(4).to_markdown(index=False),
        "",
        "These are exploratory correlations on controlled public-mini grids, not universal thresholds. `diagnostic_bins.csv` gives the median-split success/failure rates used for the provisional decision map.",
        "",
        "## Simple ensemble baselines",
        "",
        "The Blender operators are compared with obvious alternatives: whole-cell mixing, rowwise averaging where rows are deliberately aligned, a half pseudobulk shift, raw-expression Hungarian matching, random coordinate transfer, and same-index coordinate transfer.",
        "",
        comparators[comp_cols].round(3).to_markdown(index=False),
        "",
        "## Organizer reference-row pairs",
        "",
        "These are reconstructed from reference-row definitions published by the organizers and the same public mini bundle. They are not competitive model pairs. They are useful because they were not designed as inverse transformations for an ensemble operator.",
        "",
        organizer[org_cols].round(3).to_markdown(index=False),
        "",
        "The mini bundle does not contain the two preceding stages required to reconstruct the organizer's `pseudobulk_shift` T1/T2 baseline honestly, nor a distinct held-out knockout for a non-leaking `shift_transfer` test. Those baselines are therefore not fabricated here.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "pip install -r requirements.txt",
        "python regime_map.py --out-dir regime_results",
        "python ensemble_atlas.py --regime-dir regime_results --out-dir atlas_results",
        "```",
        "",
        "The same analysis is designed to be rerun once validation ground truth is released in the final phase, so the diagnostic rules can be checked outside these controlled mini examples.",
        "",
    ]
    Path("ATLAS_RESULTS.md").write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".cache/public_samples"))
    parser.add_argument("--regime-dir", type=Path, default=Path("regime_results"))
    parser.add_argument("--out-dir", type=Path, default=Path("atlas_results"))
    args = parser.parse_args()

    samples = download_public_samples(args.data_dir)
    diag = diagnostic_table(samples, args.regime_dir)
    corr = diagnostic_correlations(diag)
    bins = decision_bins(diag, corr)
    transfer = metric_transfer(args.regime_dir)
    with tempfile.TemporaryDirectory(prefix="vec_atlas_") as tmp:
        work = Path(tmp)
        comparators = simple_comparator_study(samples, work)
        organizer = organizer_reference_pair_study(samples, work)
    write_report(args.out_dir, diag, corr, bins, transfer, comparators, organizer)


if __name__ == "__main__":
    main()
