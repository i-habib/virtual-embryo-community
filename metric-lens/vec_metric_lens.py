#!/usr/bin/env python3
"""VEC Metric Lens

Explain Virtual Embryo Challenge validation-board scores from a raw `veckit`
metrics JSON. Uses only the public validation anchors and weights published by
the organizers. It never touches hidden data and is not a score predictor for
hidden test boards.

Usage:
    python vec_metric_lens.py --board T3:gata4 result.json
    python vec_metric_lens.py --board T2:heart:val_interp result.json --markdown report.md
"""
from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Dict, Any

# Public validation anchors from virtualembryo.ai/challenge/evaluation, read 2026-09-16.
# Direction meanings:
#   higher: larger raw value is better
#   lower: smaller raw value is better
#   abs_lower: score abs(raw); closer to zero is better
BOARDS: Dict[str, Dict[str, Any]] = {
    "T1:val": {
        "metrics": {
            "de_score":         {"floor": 0.0,      "ceiling": 0.8464,   "direction": "higher",    "weight": 0.25, "label": "DES / DE gene recovery"},
            "de_direction":     {"floor": 0.0,      "ceiling": 0.7901,   "direction": "higher",    "weight": 0.25, "label": "DCS / change direction"},
            "mmd_u":            {"floor": 0.08359,  "ceiling": 0.00406,  "direction": "lower",     "weight": 0.30, "label": "MMD / cell-state distribution"},
            "variogram":        {"floor": 0.005219, "ceiling": 0.000158, "direction": "lower",     "weight": 0.20, "label": "CSS / co-expression structure"},
        }
    },
    "T2:embryo:val_interp": {
        "metrics": {
            "de_score":         {"floor": 0.0,      "ceiling": 0.8413,   "direction": "higher",    "weight": 0.125,      "label": "DES / expression change"},
            "de_direction":     {"floor": 0.0,      "ceiling": 0.9185,   "direction": "higher",    "weight": 0.125,      "label": "DCS / expression direction"},
            "mmd_u":            {"floor": 0.08571,  "ceiling": 0.00307,  "direction": "lower",     "weight": 0.15,       "label": "MMD / cell-state distribution"},
            "variogram":        {"floor": 0.053533, "ceiling": 0.001264, "direction": "lower",     "weight": 0.10,       "label": "CSS / co-expression structure"},
            "d2_shape":         {"floor": 0.05306,  "ceiling": 0.00268,  "direction": "lower",     "weight": 1/12,       "label": "SDD / tissue shape"},
            "occupancy_dice":   {"floor": 0.7047,   "ceiling": 0.7661,   "direction": "higher",    "weight": 1/12,       "label": "ODS / occupied volume"},
            "scale_log_ratio":  {"floor": -0.3063,  "ceiling": 0.0053,   "direction": "abs_lower", "weight": 1/12,       "label": "TSR / tissue scale"},
            "neighborhood_mmd": {"floor": 0.21105,  "ceiling": 0.01128,  "direction": "lower",     "weight": 0.25,       "label": "NFS / local spatial organization"},
        }
    },
    "T2:heart:val_extrap": {
        "metrics": {
            "de_score":         {"floor": 0.0,      "ceiling": 0.942,    "direction": "higher",    "weight": 0.125, "label": "DES / expression change"},
            "de_direction":     {"floor": 0.0,      "ceiling": 0.9915,   "direction": "higher",    "weight": 0.125, "label": "DCS / expression direction"},
            "mmd_u":            {"floor": 0.02455,  "ceiling": 0.00011,  "direction": "lower",     "weight": 0.15,  "label": "MMD / cell-state distribution"},
            "variogram":        {"floor": 0.031712, "ceiling": 0.000696, "direction": "lower",     "weight": 0.10,  "label": "CSS / co-expression structure"},
            "d2_shape":         {"floor": 0.00933,  "ceiling": 0.00342,  "direction": "lower",     "weight": 1/12,  "label": "SDD / tissue shape"},
            "occupancy_dice":   {"floor": 0.7747,   "ceiling": 0.9465,   "direction": "higher",    "weight": 1/12,  "label": "ODS / occupied volume"},
            "scale_log_ratio":  {"floor": -0.268,   "ceiling": 0.0074,   "direction": "abs_lower", "weight": 1/12,  "label": "TSR / tissue scale"},
            "neighborhood_mmd": {"floor": 0.07184,  "ceiling": 0.0004,   "direction": "lower",     "weight": 0.25,       "label": "NFS / local spatial organization"},
        }
    },
    "T2:heart:val_interp": {
        "metrics": {
            "de_score":         {"floor": 0.0,      "ceiling": 0.8182,   "direction": "higher",    "weight": 0.125, "label": "DES / expression change"},
            "de_direction":     {"floor": 0.0,      "ceiling": 0.9553,   "direction": "higher",    "weight": 0.125, "label": "DCS / expression direction"},
            "mmd_u":            {"floor": 0.0207,   "ceiling": 0.00087,  "direction": "lower",     "weight": 0.15,  "label": "MMD / cell-state distribution"},
            "variogram":        {"floor": 0.023828, "ceiling": 0.001021, "direction": "lower",     "weight": 0.10,  "label": "CSS / co-expression structure"},
            "d2_shape":         {"floor": 0.03079,  "ceiling": 0.00412,  "direction": "lower",     "weight": 1/12,  "label": "SDD / tissue shape"},
            "occupancy_dice":   {"floor": 0.6748,   "ceiling": 0.8796,   "direction": "higher",    "weight": 1/12,  "label": "ODS / occupied volume"},
            "scale_log_ratio":  {"floor": 0.3284,   "ceiling": -0.0119,  "direction": "abs_lower", "weight": 1/12,  "label": "TSR / tissue scale"},
            "neighborhood_mmd": {"floor": 0.05728,  "ceiling": 0.00432,  "direction": "lower",     "weight": 0.25,       "label": "NFS / local spatial organization"},
        }
    },
    "T3:gata4": {
        "metrics": {
            "de_score":       {"floor": 0.0,       "ceiling": 0.8696,   "direction": "higher",    "weight": 0.30, "label": "DES / response gene recovery"},
            "de_direction":   {"floor": 0.0,       "ceiling": 0.9247,   "direction": "higher",    "weight": 0.25, "label": "DCS / response direction"},
            "severity_slope": {"floor": -6.9078,   "ceiling": -0.0088,  "direction": "abs_lower", "weight": 0.25, "label": "PSS / response magnitude"},
            "mmd_u":          {"floor": 0.03141,   "ceiling": 0.00039,  "direction": "lower",     "weight": 0.12, "label": "MMD / cell-state distribution"},
            "variogram":      {"floor": 0.032212,  "ceiling": 0.000737, "direction": "lower",     "weight": 0.08, "label": "CSS / co-expression structure"},
        }
    },
}


def _scored_value(x: float, direction: str) -> float:
    return abs(x) if direction == "abs_lower" else x


def metric_skill(raw: float | None, spec: Dict[str, Any]) -> float:
    """Published hyperbolic skill: floor=0.5, ceiling=1, missing=0."""
    if raw is None or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        return 0.0
    direction = spec["direction"]
    m = _scored_value(float(raw), direction)
    floor = _scored_value(float(spec["floor"]), direction)
    ceil = _scored_value(float(spec["ceiling"]), direction)

    if direction == "higher":
        d = ceil - m
        d_floor = ceil - floor
    else:  # lower or abs_lower
        d = m - ceil
        d_floor = floor - ceil

    # If a metric beats the empirical half-vs-half ceiling, public rules clip skill to 1.
    if d <= 0:
        return 1.0
    if d_floor <= 0:
        raise ValueError(f"Invalid anchors for {spec}")
    return min(d_floor / (d_floor + d), 1.0)


def board_score(metrics: Dict[str, Any], board: str) -> Dict[str, Any]:
    spec = BOARDS[board]["metrics"]
    rows = []
    total = 0.0
    for name, mspec in spec.items():
        raw = metrics.get(name)
        skill = metric_skill(raw, mspec)
        contribution = 100.0 * mspec["weight"] * skill
        total += contribution
        rows.append({
            "metric": name,
            "label": mspec["label"],
            "raw": raw,
            "skill": skill,
            "weight": mspec["weight"],
            "points": contribution,
            "max_points": 100.0 * mspec["weight"],
        })
    return {"board": board, "score": total, "rows": rows}


def _raw_at_fraction_to_ceiling(raw: float | None, spec: Dict[str, Any], frac: float) -> float:
    if raw is None or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        # For a missing metric, use the empirical ceiling as the counterfactual.
        return float(spec["ceiling"])
    x = float(raw)
    if spec["direction"] != "abs_lower":
        return x + frac * (float(spec["ceiling"]) - x)
    cur_abs = abs(x)
    ceil_abs = abs(float(spec["ceiling"]))
    new_abs = cur_abs + frac * (ceil_abs - cur_abs)
    sign = -1.0 if x < 0 else (1.0 if x > 0 else (-1.0 if float(spec["ceiling"]) < 0 else 1.0))
    return sign * new_abs


def counterfactuals(metrics: Dict[str, Any], board: str, frac: float = 1.0):
    base = board_score(metrics, board)["score"]
    out = []
    for name, mspec in BOARDS[board]["metrics"].items():
        alt = deepcopy(metrics)
        alt[name] = _raw_at_fraction_to_ceiling(metrics.get(name), mspec, frac)
        s = board_score(alt, board)["score"]
        out.append({"metric": name, "new_raw": alt[name], "new_score": s, "gain": s - base})
    return sorted(out, key=lambda r: r["gain"], reverse=True)


def load_metrics(path: Path) -> Dict[str, Any]:
    obj = json.loads(path.read_text())
    if "metrics" in obj and isinstance(obj["metrics"], dict):
        return obj["metrics"]
    if isinstance(obj, dict):
        return obj
    raise ValueError("Expected a JSON object or a veckit result with a top-level 'metrics' object")


def render_markdown(metrics: Dict[str, Any], board: str) -> str:
    result = board_score(metrics, board)
    gains = counterfactuals(metrics, board, frac=1.0)
    lines = [
        f"# VEC Metric Lens — `{board}`",
        "",
        f"**Reconstructed public validation score: {result['score']:.2f} / 100**",
        "",
        "> Uses the organizers' published validation anchors and task weights. This is an explanation of a known local/validation metric vector, not a predictor of the hidden test score.",
        "",
        "## Score breakdown",
        "",
        "| Metric | Raw | Skill | Weight | Points | Points left |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in result["rows"]:
        raw = "missing" if r["raw"] is None else f"{r['raw']:.6g}" if isinstance(r["raw"], (int, float)) else str(r["raw"])
        lines.append(f"| {r['metric']} — {r['label']} | {raw} | {r['skill']:.3f} | {100*r['weight']:.1f}% | {r['points']:.2f} | {r['max_points']-r['points']:.2f} |")
    lines += ["", "## If one metric were fixed", "", "For each row below, every metric is held fixed except one. That one metric is moved to its published validation ceiling:", "", "| Rank | Metric | Score after fix | Gain |", "|---:|---|---:|---:|"]
    for i, g in enumerate(gains, 1):
        lines.append(f"| {i} | {g['metric']} | {g['new_score']:.2f} | +{g['gain']:.2f} |")
    lines += [
        "",
        "## A few cautions",
        "",
        "- A floor-like model is around 50 because each metric's floor maps to skill 0.5.",
        "- The ceiling is an empirical split-half estimate, not a theoretical maximum; beating it clips that metric's skill to 1.",
        "- `scale_log_ratio` and `severity_slope` are scored by absolute value before the lower-is-better transform.",
        "- Missing/NaN scored metrics count as skill 0 under the published rules.",
        "- Improving a public-validation bottleneck can still fail to transfer to the hidden test target.",
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="veckit result JSON or a bare metrics JSON object")
    ap.add_argument("--board", required=True, choices=sorted(BOARDS))
    ap.add_argument("--markdown", type=Path, help="write a Markdown report")
    ap.add_argument("--json", dest="json_out", type=Path, help="write machine-readable analysis JSON")
    args = ap.parse_args()

    metrics = load_metrics(args.input)
    result = board_score(metrics, args.board)
    result["counterfactual_ceiling"] = counterfactuals(metrics, args.board, 1.0)
    text = render_markdown(metrics, args.board)
    print(text)
    if args.markdown:
        args.markdown.write_text(text)
    if args.json_out:
        args.json_out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
