"""Candidate prediction families for the pseudo-pair study.

Each candidate maps (input stages, earliest first; target time; seed) to a predicted Stage with the
same genes. Trend-based families estimate a per-day rate from the last two input stages. With a
single input stage no rate exists, so they return the last stage unchanged (identical to copy_last).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

import numpy as np
from scipy.special import logsumexp

from stages import Stage

FAMILIES = ("copy_last", "drift", "composition", "growth", "combo", "degraded")


def _pred(X, coords, ct, genes, t, has_coords=True) -> Stage:
    return Stage(name="pred", time=float(t), X=np.asarray(X, dtype=np.float32),
                 coords=np.asarray(coords, dtype=np.float32), ct=np.asarray(ct), genes=genes,
                 has_coords=has_coords)


def _gene_mean(stage: Stage) -> np.ndarray:
    return stage.X.mean(axis=0, dtype=np.float64)


def _rate_of_mean(stages: List[Stage]) -> np.ndarray:
    """Per-day, per-gene change of the mean expression, from the last two input stages."""
    prev, last = stages[-2], stages[-1]
    return (_gene_mean(last) - _gene_mean(prev)) / (last.time - prev.time)


def _rms_radius(coords: np.ndarray) -> float:
    c = coords.mean(axis=0, dtype=np.float64)
    return float(np.sqrt(((coords - c) ** 2).sum(axis=1).mean()))


def _growth_factor(stages: List[Stage], target_time: float, s: float) -> float:
    """Coordinate scale factor: (per-day RMS-radius ratio) ** (s * dt), where dt is days past the last stage.
    Stages without coordinates (T1 pairs) and single-stage inputs give no trend, so the factor is 1."""
    if len(stages) < 2 or not stages[-1].has_coords or not stages[-2].has_coords:
        return 1.0
    prev, last = stages[-2], stages[-1]
    per_day = np.log(_rms_radius(last.coords) / _rms_radius(prev.coords)) / (last.time - prev.time)
    return float(np.exp(s * per_day * (target_time - last.time)))


def _scale_about_centroid(coords: np.ndarray, factor: float) -> np.ndarray:
    c = coords.mean(axis=0, dtype=np.float64)
    return c + factor * (coords.astype(np.float64) - c)


def copy_last(stages: List[Stage], target_time: float, seed: int) -> Stage:
    last = stages[-1]
    return _pred(last.X, last.coords, last.ct, last.genes, target_time, last.has_coords)


def drift(stages: List[Stage], target_time: float, seed: int, a: float) -> Stage:
    """Last-stage cells shifted by a * (per-day mean change) * dt, clipped at zero."""
    last = stages[-1]
    X = last.X.astype(np.float64)
    if len(stages) >= 2:
        X = X + a * _rate_of_mean(stages) * (target_time - last.time)
    return _pred(np.maximum(X, 0.0), last.coords, last.ct, last.genes, target_time, last.has_coords)


def _composition_resample(stages: List[Stage], target_time: float, s: float, seed: int):
    """Resample last-stage cells (with replacement) so cell-type proportions follow the trend of
    per-day log-proportions from the last two stages, scaled by s. Returns (X, coords, ct)."""
    last = stages[-1]
    if len(stages) < 2:
        return last.X, last.coords, last.ct
    prev = stages[-2]
    dt = target_time - last.time
    cats = np.unique(np.concatenate([last.ct, prev.ct]))
    K = len(cats)
    n_last = np.array([(last.ct == c).sum() for c in cats], dtype=np.float64)
    n_prev = np.array([(prev.ct == c).sum() for c in cats], dtype=np.float64)
    # Add-one smoothing over the union of labels keeps every log-proportion finite.
    p_last = (n_last + 1.0) / (n_last.sum() + K)
    p_prev = (n_prev + 1.0) / (n_prev.sum() + K)
    rate = (np.log(p_last) - np.log(p_prev)) / (last.time - prev.time)
    z = np.log(p_last) + s * rate * dt
    present = n_last > 0  # only labels present in the last stage can be resampled
    z = np.where(present, z, -np.inf)
    q = np.exp(z - logsumexp(z[present]))
    type_idx = np.searchsorted(cats, last.ct)
    w = q[type_idx] / n_last[type_idx]
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(last), size=len(last), replace=True, p=w / w.sum())
    return last.X[idx], last.coords[idx], last.ct[idx]


def composition(stages: List[Stage], target_time: float, seed: int, s: float) -> Stage:
    X, coords, ct = _composition_resample(stages, target_time, s, seed)
    return _pred(X, coords, ct, stages[-1].genes, target_time, stages[-1].has_coords)


def growth(stages: List[Stage], target_time: float, seed: int, s: float) -> Stage:
    last = stages[-1]
    f = _growth_factor(stages, target_time, s)
    coords = _scale_about_centroid(last.coords, f) if last.has_coords else last.coords
    return _pred(last.X, coords, last.ct, last.genes, target_time, last.has_coords)


def combo(stages: List[Stage], target_time: float, seed: int, s: float, a: float = 1.0,
          growth_s: float | None = None) -> Stage:
    """Composition resampling first, then the drift shift (rate from the input stages), then optional growth."""
    last = stages[-1]
    X, coords, ct = _composition_resample(stages, target_time, s, seed)
    X = X.astype(np.float64)
    if len(stages) >= 2:
        X = np.maximum(X + a * _rate_of_mean(stages) * (target_time - last.time), 0.0)
    if growth_s is not None and last.has_coords:
        coords = _scale_about_centroid(coords, _growth_factor(stages, target_time, growth_s))
    return _pred(X, coords, ct, last.genes, target_time, last.has_coords)


def shrink(pred: Stage, b: float) -> Stage:
    """Degraded control: each cell moves a fraction b of the way to the population mean (the per-gene mean
    over the predicted cells). The mean expression is kept; cell-to-cell variation is removed."""
    mu = _gene_mean(pred)
    X = (1.0 - b) * pred.X.astype(np.float64) + b * mu
    return _pred(X, pred.coords, pred.ct, pred.genes, pred.time, pred.has_coords)


@dataclass(frozen=True)
class Candidate:
    name: str
    family: str
    fn: Callable[[List[Stage], float, int], Stage]


def candidates() -> List[Candidate]:
    out = [Candidate("copy_last", "copy_last", copy_last)]
    for a in (0.5, 1.0, 1.5):
        out.append(Candidate(f"drift:a={a}", "drift",
                             lambda st, t, sd, a=a: drift(st, t, sd, a)))
    for s in (0.5, 1.0):
        out.append(Candidate(f"composition:s={s}", "composition",
                             lambda st, t, sd, s=s: composition(st, t, sd, s)))
    for s in (0.5, 1.0):
        out.append(Candidate(f"growth:s={s}", "growth",
                             lambda st, t, sd, s=s: growth(st, t, sd, s)))
    for s in (0.5, 1.0):
        out.append(Candidate(f"combo:composition={s}+drift=1.0", "combo",
                             lambda st, t, sd, s=s: combo(st, t, sd, s, a=1.0)))
    for s in (0.5, 1.0):
        out.append(Candidate(f"combo:composition={s}+drift=1.0+growth={s}", "combo",
                             lambda st, t, sd, s=s: combo(st, t, sd, s, a=1.0, growth_s=s)))
    for b in (0.2, 0.5):
        out.append(Candidate(f"degraded:drift=1.0+shrink={b}", "degraded",
                             lambda st, t, sd, b=b: shrink(drift(st, t, sd, 1.0), b)))
    for b in (0.2, 0.5):
        out.append(Candidate(f"degraded:composition=1.0+shrink={b}", "degraded",
                             lambda st, t, sd, b=b: shrink(composition(st, t, sd, 1.0), b)))
    return out


def candidate_map() -> dict:
    return {c.name: c for c in candidates()}


def predict(name: str, stages: List[Stage], target_time: float, seed: int) -> Stage:
    cands = candidate_map()
    if name not in cands:
        raise KeyError(f"unknown candidate {name!r}")
    return cands[name].fn(stages, float(target_time), int(seed))
