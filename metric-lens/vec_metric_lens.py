#!/usr/bin/env python3
"""VEC Metric Lens

Explain a Virtual Embryo Challenge validation score from a raw `veckit`
metrics JSON. It uses the organizers' published floors, ceilings and weights,
reports how many points each metric contributes, and how many points each
metric could still add. It never reads hidden data and does not predict
hidden test scores.

Usage:
    python vec_metric_lens.py --board T3:gata4 result.json
    python vec_metric_lens.py --board T2:heart:val_interp result.json --markdown report.md
    python vec_metric_lens.py --board T1:val result.json \
        --index https://virtualembryo.ai/challenge/panels/index.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

BUILTIN_ANCHOR_SOURCE = "built-in table, transcribed 2026-09-16"
INDEX_TIMEOUT_S = 20

# Public validation anchors from virtualembryo.ai/challenge/evaluation, read 2026-09-16.
# Checked value by value against virtualembryo.ai/challenge/panels/index.json on 2026-10-14.
# Weights and directions exist only here; the index supplies floors and ceilings.
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


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def _scored_value(x: float, direction: str) -> float:
    return abs(x) if direction == "abs_lower" else x


def check_anchors(spec: Dict[str, Any], label: str) -> None:
    """Raise ValueError unless the ceiling is better than the floor under the metric's direction."""
    floor = _scored_value(float(spec["floor"]), spec["direction"])
    ceil = _scored_value(float(spec["ceiling"]), spec["direction"])
    ceiling_is_better = ceil > floor if spec["direction"] == "higher" else ceil < floor
    if not ceiling_is_better:
        raise ValueError(f"{label}: the ceiling must be better than the floor")


def metric_skill(raw: Any, spec: Dict[str, Any]) -> float:
    """Published hyperbolic skill: floor=0.5, ceiling=1, clipped at 1, missing or non-finite=0."""
    if not _is_number(raw):
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

    # A metric at or beyond the empirical ceiling gets full skill.
    if d <= 0:
        return 1.0
    if d_floor <= 0:
        raise ValueError(f"Invalid anchors for {spec}")
    return min(d_floor / (d_floor + d), 1.0)


def read_index(source: str) -> Dict[str, Any]:
    """Read a board contract such as panels/index.json from a local path or an http(s) URL."""
    if source.startswith(("http://", "https://")):
        # Some hosts reject the default urllib user agent, so send an explicit one.
        req = urllib.request.Request(source, headers={"User-Agent": "vec-metric-lens/0.2", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=INDEX_TIMEOUT_S) as resp:
            payload = resp.read()
    else:
        payload = Path(source).read_bytes()
    obj = json.loads(payload.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("index must be a JSON object keyed by board")
    return obj


def anchored_board(index: Dict[str, Any], board: str, boards: Dict[str, Any] = BOARDS) -> Dict[str, Any]:
    """Return one board from `boards` with its floors and ceilings taken from `index`.

    Weights, directions and labels are kept from `boards`. Every metric of the
    board must have anchors in the index. A gap is an error, not a silent
    fallback to the built-in values.
    """
    if board not in boards:
        raise ValueError(
            f"no weights or directions for {board!r} in this file, so it cannot be scored. "
            f"Add the board to BOARDS. Known boards: {', '.join(sorted(boards))}"
        )
    entry = index.get(board)
    if not isinstance(entry, dict) or not isinstance(entry.get("anchors"), dict):
        raise ValueError(f"index has no anchors for board {board!r}")
    anchors = entry["anchors"]
    out = deepcopy(boards[board])
    for name, mspec in out["metrics"].items():
        a = anchors.get(name)
        if not isinstance(a, dict):
            raise ValueError(f"index has no anchors for {board!r} metric {name!r}")
        for key in ("floor", "ceiling"):
            if not _is_number(a.get(key)):
                raise ValueError(f"{board!r} {name!r} {key} must be a finite number, got {a.get(key)!r}")
            mspec[key] = float(a[key])
        check_anchors(mspec, f"{board!r} {name!r}")
    return out


def board_score(metrics: Dict[str, Any], board: str, boards: Dict[str, Any] = BOARDS) -> Dict[str, Any]:
    spec = boards[board]["metrics"]
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


def _raw_at_fraction_to_ceiling(raw: Any, spec: Dict[str, Any], frac: float) -> float:
    ceiling = float(spec["ceiling"])
    if not _is_number(raw):
        # A missing or non-finite metric is counted at its ceiling, so its gain is its full point value.
        return ceiling
    x = float(raw)
    direction = spec["direction"]
    sx = _scored_value(x, direction)
    sc = _scored_value(ceiling, direction)
    at_or_past_ceiling = sx >= sc if direction == "higher" else sx <= sc
    if at_or_past_ceiling:
        # Already at full skill: keep the raw value rather than moving it back toward the ceiling.
        return x
    new_scored = sx + frac * (sc - sx)
    if direction == "abs_lower":
        # sx > sc >= 0 here, so x is nonzero and carries its sign.
        return math.copysign(new_scored, x)
    return new_scored


def counterfactuals(metrics: Dict[str, Any], board: str, frac: float = 1.0,
                    boards: Dict[str, Any] = BOARDS) -> List[Dict[str, Any]]:
    base = board_score(metrics, board, boards)["score"]
    out = []
    for name, mspec in boards[board]["metrics"].items():
        alt = dict(metrics)
        alt[name] = _raw_at_fraction_to_ceiling(metrics.get(name), mspec, frac)
        s = board_score(alt, board, boards)["score"]
        out.append({
            "metric": name,
            "current_raw": metrics.get(name),
            "new_raw": alt[name],
            "new_score": s,
            "gain": s - base,
        })
    return sorted(out, key=lambda r: r["gain"], reverse=True)


def load_metrics(path: Path) -> Dict[str, Any]:
    obj = json.loads(path.read_text())
    if isinstance(obj, dict) and isinstance(obj.get("metrics"), dict):
        return obj["metrics"]
    if isinstance(obj, dict):
        return obj
    raise ValueError("Expected a JSON object or a veckit result with a top-level 'metrics' object")


def _fmt_raw(raw: Any) -> str:
    if raw is None:
        return "missing"
    if _is_number(raw):
        return f"{float(raw):.6g}"
    return str(raw)


def _json_safe(obj: Any) -> Any:
    """Replace NaN and infinity with null so the JSON output is strict JSON."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def render_markdown(metrics: Dict[str, Any], board: str, boards: Dict[str, Any] = BOARDS,
                    anchor_source: str = BUILTIN_ANCHOR_SOURCE) -> str:
    result = board_score(metrics, board, boards)
    gains = counterfactuals(metrics, board, 1.0, boards)
    lines = [
        f"# VEC Metric Lens: `{board}`",
        "",
        f"**Reconstructed public validation score: {result['score']:.2f} / 100**",
        "",
        f"Anchors: {anchor_source}. Weights and directions: built into `vec_metric_lens.py`.",
        "",
        "> This explains a known validation metric vector. It is not a predictor of the hidden test score.",
        "",
        "## Score breakdown",
        "",
        "| Metric | Raw | Skill | Weight | Points | Points left |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in result["rows"]:
        lines.append(
            f"| {r['metric']} ({r['label']}) | {_fmt_raw(r['raw'])} | {r['skill']:.3f} | "
            f"{100 * r['weight']:.1f}% | {r['points']:.2f} | {r['max_points'] - r['points']:.2f} |"
        )
    lines += [
        "",
        "## If one metric were fixed",
        "",
        "For each row below, every other metric is held fixed. That one metric is moved to its published validation ceiling.",
        "",
        "| Rank | Metric | Score after fix | Gain |",
        "|---:|---|---:|---:|",
    ]
    for i, g in enumerate(gains, 1):
        lines.append(f"| {i} | {g['metric']} | {g['new_score']:.2f} | +{g['gain']:.2f} |")
    lines += [
        "",
        "## A few cautions",
        "",
        "- A model at every floor scores 50, and a model at every ceiling scores 100.",
        "- Ceilings are empirical split-half estimates, not theoretical maxima. A metric beyond its ceiling gets skill 1.",
        "- `scale_log_ratio` and `severity_slope` are scored on absolute value, because zero is best.",
        "- A missing or NaN metric gets skill 0. In the fixed-metric table it is counted at its ceiling.",
        "- Gains on this board do not guarantee gains on the hidden test target.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Explain a VEC validation score from a veckit metrics JSON.")
    ap.add_argument("input", type=Path, help="veckit result JSON or a bare metrics JSON object")
    ap.add_argument("--board", required=True, help="board key, for example T3:gata4")
    ap.add_argument(
        "--index",
        help="take floors and ceilings from index.json, as a local path or an http(s) URL. "
             "Weights and directions still come from this file.",
    )
    ap.add_argument("--markdown", type=Path, help="write a Markdown report")
    ap.add_argument("--json", dest="json_out", type=Path, help="write machine-readable analysis JSON")
    args = ap.parse_args(argv)

    boards: Dict[str, Any] = BOARDS
    anchor_source = BUILTIN_ANCHOR_SOURCE
    if args.index:
        try:
            index = read_index(args.index)
            boards = {args.board: anchored_board(index, args.board)}
        except (OSError, ValueError) as exc:
            ap.error(f"--index: {exc}")
        anchor_source = f"index {args.index}"
        unweighted = sorted(set(index) - set(BOARDS))
        if unweighted:
            print(f"note: index lists boards this file has no weights for: {', '.join(unweighted)}",
                  file=sys.stderr)
    elif args.board not in BOARDS:
        ap.error(f"unknown board {args.board!r}; choose one of: {', '.join(sorted(BOARDS))}")

    metrics = load_metrics(args.input)
    result = board_score(metrics, args.board, boards)
    result["anchor_source"] = anchor_source
    result["counterfactual_ceiling"] = counterfactuals(metrics, args.board, 1.0, boards)
    text = render_markdown(metrics, args.board, boards, anchor_source)
    print(text)
    if args.markdown:
        args.markdown.write_text(text)
    if args.json_out:
        args.json_out.write_text(json.dumps(_json_safe(result), indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
