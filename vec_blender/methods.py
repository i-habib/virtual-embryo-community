from __future__ import annotations

from dataclasses import dataclass

import anndata as ad
import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from .io import build_output, dense_x, spatial_coords, validate_pair


@dataclass
class BlendResult:
    adata: ad.AnnData
    report: dict


def _choice(rng: np.random.Generator, n_source: int, n_take: int) -> np.ndarray:
    return rng.choice(n_source, size=n_take, replace=n_take > n_source)


def population_mix(
    a: ad.AnnData,
    b: ad.AnnData,
    *,
    alpha: float = 0.5,
    n_out: int | None = None,
    seed: int = 0,
) -> BlendResult:
    """Sample cells from A and B, preserving each sampled cell as a whole."""
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be in [0, 1]")
    a, b = validate_pair(a, b)

    if n_out is None:
        n_out = int(round(alpha * a.n_obs + (1.0 - alpha) * b.n_obs))
    if n_out <= 0:
        raise ValueError("n_out must be positive")

    n_a = int(round(alpha * n_out))
    n_b = n_out - n_a
    rng = np.random.default_rng(seed)
    ia = _choice(rng, a.n_obs, n_a)
    ib = _choice(rng, b.n_obs, n_b)

    XA = dense_x(a)[ia]
    XB = dense_x(b)[ib]
    X = np.concatenate([XA, XB], axis=0)

    ca = spatial_coords(a)
    cb = spatial_coords(b)
    if (ca is None) != (cb is None):
        raise ValueError(
            "Population mixing requires both submissions to either contain "
            "spatial_3D or both omit it"
        )
    coords = None
    if ca is not None:
        coords = np.concatenate([ca[ia], cb[ib]], axis=0)

    out = build_output(X, a, coords=coords, obs_indices=None, obs_prefix="mix")
    out.uns["vec_blender"].update(
        {
            "method": "population_mix",
            "alpha": float(alpha),
            "seed": int(seed),
            "n_from_a": int(n_a),
            "n_from_b": int(n_b),
        }
    )
    return BlendResult(
        out,
        {
            "method": "population_mix",
            "alpha": float(alpha),
            "seed": int(seed),
            "n_out": int(n_out),
            "n_from_a": int(n_a),
            "n_from_b": int(n_b),
        },
    )


def mean_graft(
    mean_donor: ad.AnnData,
    structure_carrier: ad.AnnData,
    *,
    clip_min: float | None = None,
) -> BlendResult:
    """Give B's centered cell cloud A's per-gene mean.

    Before optional clipping, the output mean equals A's mean exactly while
    B's centered residual matrix is unchanged.
    """
    a, b = validate_pair(mean_donor, structure_carrier)
    XA = dense_x(a)
    XB = dense_x(b)

    mu_a = XA.mean(axis=0)
    mu_b = XB.mean(axis=0)
    X = XB + (mu_a - mu_b)
    if clip_min is not None:
        X = np.maximum(X, float(clip_min))

    coords = spatial_coords(b)
    out = build_output(
        X,
        b,
        coords=coords,
        obs_indices=np.arange(b.n_obs),
        obs_prefix="mean_graft",
    )
    stored = {"method": "mean_graft"}
    if clip_min is not None:
        stored["clip_min"] = float(clip_min)
    out.uns["vec_blender"].update(stored)

    mean_error = float(np.max(np.abs(X.mean(axis=0) - mu_a)))
    negative_fraction = float(np.mean(X < 0))
    return BlendResult(
        out,
        {
            "method": "mean_graft",
            "clip_min": clip_min,
            "max_abs_mean_error": mean_error,
            "negative_fraction": negative_fraction,
            "structure_cells": int(b.n_obs),
        },
    )


def _empirical_quantile_map(source: np.ndarray, carrier: np.ndarray) -> np.ndarray:
    """Map carrier ranks to source's empirical marginal distribution."""
    n_src, g = source.shape
    n_car = carrier.shape[0]
    out = np.empty_like(carrier, dtype=np.float64)

    for j in range(g):
        s = np.sort(source[:, j], kind="mergesort")
        order = np.argsort(carrier[:, j], kind="mergesort")
        if n_src == n_car:
            mapped = s
        else:
            q = (np.arange(n_car, dtype=np.float64) + 0.5) / n_car
            xp = (np.arange(n_src, dtype=np.float64) + 0.5) / n_src
            mapped = np.interp(q, xp, s, left=s[0], right=s[-1])
        out[order, j] = mapped
    return out


def quantile_graft(
    marginal_donor: ad.AnnData,
    rank_carrier: ad.AnnData,
) -> BlendResult:
    """Use A's per-gene marginals with B's within-gene cell ranks."""
    a, b = validate_pair(marginal_donor, rank_carrier)
    XA = dense_x(a)
    XB = dense_x(b)
    X = _empirical_quantile_map(XA, XB)

    coords = spatial_coords(b)
    out = build_output(
        X,
        b,
        coords=coords,
        obs_indices=np.arange(b.n_obs),
        obs_prefix="quantile_graft",
    )
    out.uns["vec_blender"].update({"method": "quantile_graft"})

    if a.n_obs == b.n_obs:
        marginal_error = max(
            float(np.max(np.abs(np.sort(X[:, j]) - np.sort(XA[:, j]))))
            for j in range(a.n_vars)
        )
    else:
        marginal_error = None

    return BlendResult(
        out,
        {
            "method": "quantile_graft",
            "cells": int(b.n_obs),
            "exact_empirical_marginals": bool(a.n_obs == b.n_obs),
            "max_sorted_marginal_error": marginal_error,
        },
    )


def _embed_for_matching(
    XA: np.ndarray, XB: np.ndarray, n_components: int
) -> tuple[np.ndarray, np.ndarray]:
    A0 = XA - XA.mean(axis=0, keepdims=True)
    B0 = XB - XB.mean(axis=0, keepdims=True)
    Z = np.vstack([A0, B0])
    Z = StandardScaler(with_mean=True, with_std=True).fit_transform(Z)

    max_components = min(n_components, Z.shape[1], Z.shape[0] - 1)
    if max_components < 1:
        raise ValueError("Not enough cells/genes for expression-space matching")
    Z = PCA(n_components=max_components, svd_solver="auto").fit_transform(Z)
    return Z[: len(XA)], Z[len(XA) :]


def _hungarian_match(ZA: np.ndarray, ZB: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    aa = np.sum(ZA * ZA, axis=1)[:, None]
    bb = np.sum(ZB * ZB, axis=1)[None, :]
    cost = np.maximum(aa + bb - 2.0 * ZA @ ZB.T, 0.0)
    rows, cols = linear_sum_assignment(cost)
    order = np.argsort(rows)
    cols = cols[order]
    d = np.sqrt(cost[rows[order], cols])
    return cols.astype(int), d


def _greedy_unique_match(
    ZA: np.ndarray, ZB: np.ndarray, *, candidate_k: int = 32
) -> tuple[np.ndarray, np.ndarray]:
    n = len(ZA)
    k = min(max(2, candidate_k), n)
    nn = NearestNeighbors(n_neighbors=k).fit(ZB)
    dist, ind = nn.kneighbors(ZA)

    priority = np.argsort(dist[:, 0])[::-1]
    used = np.zeros(n, dtype=bool)
    match = np.full(n, -1, dtype=int)
    mdist = np.full(n, np.nan, dtype=float)

    for i in priority:
        chosen = -1
        chosen_dist = np.inf
        for d, j in zip(dist[i], ind[i]):
            if not used[j]:
                chosen = int(j)
                chosen_dist = float(d)
                break
        if chosen < 0:
            remaining = np.flatnonzero(~used)
            if len(remaining) == 0:
                raise RuntimeError("greedy matcher exhausted all geometry slots")
            delta = ZB[remaining] - ZA[i]
            dd = np.einsum("ij,ij->i", delta, delta)
            pos = int(np.argmin(dd))
            chosen = int(remaining[pos])
            chosen_dist = float(np.sqrt(dd[pos]))
        match[i] = chosen
        mdist[i] = chosen_dist
        used[chosen] = True

    return match, mdist


def spatial_transplant(
    expression_donor: ad.AnnData,
    geometry_carrier: ad.AnnData,
    *,
    n_out: int | None = None,
    seed: int = 0,
    n_components: int = 24,
    assignment: str = "auto",
    exact_limit: int = 2500,
) -> BlendResult:
    """Keep A expression rows and place them into B's spatial slots."""
    a, b = validate_pair(expression_donor, geometry_carrier)
    Cb = spatial_coords(b)
    if Cb is None:
        raise ValueError("geometry carrier B must contain obsm['spatial_3D']")

    if n_out is None:
        n_out = min(a.n_obs, b.n_obs)
    if n_out <= 1 or n_out > min(a.n_obs, b.n_obs):
        raise ValueError(
            "n_out must be >1 and cannot exceed the smaller submission cell count"
        )

    rng = np.random.default_rng(seed)
    ia = (
        np.arange(a.n_obs)
        if n_out == a.n_obs
        else np.sort(rng.choice(a.n_obs, n_out, replace=False))
    )
    ib = (
        np.arange(b.n_obs)
        if n_out == b.n_obs
        else np.sort(rng.choice(b.n_obs, n_out, replace=False))
    )

    XA = dense_x(a)[ia]
    XB = dense_x(b)[ib]
    ZA, ZB = _embed_for_matching(XA, XB, n_components=n_components)

    if assignment == "auto":
        assignment_used = "hungarian" if n_out <= exact_limit else "greedy"
    elif assignment in {"hungarian", "greedy"}:
        assignment_used = assignment
    else:
        raise ValueError("assignment must be 'auto', 'hungarian', or 'greedy'")

    if assignment_used == "hungarian":
        match, distances = _hungarian_match(ZA, ZB)
    else:
        match, distances = _greedy_unique_match(ZA, ZB)

    matched_b = ib[match]
    coords = Cb[matched_b]
    out = build_output(
        XA,
        a,
        coords=coords,
        obs_indices=ia,
        obs_prefix="spatial_transplant",
    )
    out.uns["vec_blender"].update(
        {
            "method": "spatial_transplant",
            "seed": int(seed),
            "assignment": assignment_used,
            "n_components": int(min(n_components, ZA.shape[1])),
            "expression_source": "A",
            "coordinate_source": "B",
        }
    )

    report = {
        "method": "spatial_transplant",
        "seed": int(seed),
        "n_out": int(n_out),
        "assignment": assignment_used,
        "embedding_components": int(ZA.shape[1]),
        "mean_match_distance": float(np.mean(distances)),
        "p95_match_distance": float(np.quantile(distances, 0.95)),
        "max_match_distance": float(np.max(distances)),
        "subsampled_a": bool(n_out != a.n_obs),
        "subsampled_b": bool(n_out != b.n_obs),
    }
    return BlendResult(out, report)
