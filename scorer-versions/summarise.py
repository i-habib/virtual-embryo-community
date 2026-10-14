#!/usr/bin/env python3
"""Write RESULTS.md from results/grid.csv and variants.json. Standard library only; every number printed here
is computed from grid.csv at run time.

    python summarise.py
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRID = HERE / "results" / "grid.csv"
REGISTRY = HERE / "variants.json"
OUT = HERE / "RESULTS.md"

MAIN = "git-main-cc3859a"
TOL = 1e-12
ROT_TOL = 1e-9
ROT_METRICS = ("occupancy_dice", "sliced_wasserstein")
TASKS = [("T1", "T1 (sample_8.5 -> sample_9.5)"),
         ("T2", "T2 heart, 150-cell samples"),
         ("T3", "T3 (sample_wt vs sample_mab21l2_ko)"),
         ("REAL", "T2 heart, real-scale check (3,000 cells of the released E9.5 MERFISH file)")]


def num(s: str):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def short(v: str) -> str:
    return v.replace("git-", "g").replace("pypi-", "p")


def load():
    values: dict = defaultdict(lambda: defaultdict(dict))   # values[variant][case][metric] = str
    cost: dict = defaultdict(dict)                          # cost[variant][case] = (runtime, rss)
    errors: dict = defaultdict(list)
    order: list[str] = []
    cases: list[str] = []
    with open(GRID, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            v, c, m = row["variant"], row["case"], row["metric"]
            if v not in order:
                order.append(v)
            if c not in cases:
                cases.append(c)
            cost[v][c] = (float(row["runtime_s"]), float(row["peak_rss_mb"]))
            if m == "__error__":
                errors[v].append((c, row["value"]))
            else:
                values[v][c][m] = row["value"]
    return values, cost, errors, order, cases


def task_cases(cases: list[str], task: str) -> list[str]:
    return [c for c in cases if c.split("/")[0] == task]


def diff_stats(values, variant: str, cs: list[str], metric: str):
    """(max abs numeric diff vs main, cases differing, cases absent, cases compared) for one metric."""
    max_d, n_diff, n_absent = 0.0, 0, 0
    for c in cs:
        a = values[MAIN][c].get(metric)
        b = values[variant][c].get(metric)
        if a is None and b is None:
            continue
        if a is None or b is None:
            n_absent += 1
            continue
        fa, fb = num(a), num(b)
        if fa is None or fb is None:
            if a != b:
                n_diff += 1
                max_d = math.inf
            continue
        if math.isnan(fa) or math.isnan(fb):
            if not (math.isnan(fa) and math.isnan(fb)):
                n_diff += 1
                max_d = math.inf
            continue
        d = abs(fa - fb)
        if d > TOL:
            n_diff += 1
            max_d = max(max_d, d)
    return max_d, n_diff, n_absent


def metrics_in(values, variants: list[str], cs: list[str]) -> list[str]:
    seen: set[str] = set()
    for v in variants:
        for c in cs:
            seen.update(values[v][c].keys())
    return sorted(seen)


def fmt(x: float) -> str:
    if math.isinf(x):
        return "text or NaN differs"
    return f"{x:.4g}"


def ran(values, variants, cs):
    """Variants that have at least one case from this task (others were not run for it)."""
    return [v for v in variants if any(c in values[v] for c in cs)]


def section_differences(values, others, cases, task, title, lines):
    cs = task_cases(cases, task)
    if not cs:
        return
    others = [v for v in ran(values, others, cs)]
    lines.append(f"### {title}")
    lines.append("")
    lines.append(f"Cases: {len(cs)}. Each cell: max absolute difference from `{MAIN}` over the cases where the "
                 "metric differs, then the number of differing cases, and any cases where it is absent.")
    lines.append("")
    rows = []
    shown_variants: list[str] = []
    for m in metrics_in(values, [MAIN] + others, cs):
        cells = {}
        for v in others:
            max_d, n_diff, n_absent = diff_stats(values, v, cs, m)
            if n_diff or n_absent:
                parts = []
                if n_diff:
                    parts.append(f"max {fmt(max_d)}, {n_diff}/{len(cs)} cases")
                if n_absent:
                    parts.append(f"absent in {n_absent}/{len(cs)} cases")
                cells[v] = "; ".join(parts)
                if v not in shown_variants:
                    shown_variants.append(v)
        if cells:
            rows.append((m, cells))
    if not rows:
        lines.append("No metric differs from main for this task.")
        lines.append("")
        return
    shown_variants.sort(key=others.index)
    lines.append("| metric | " + " | ".join(short(v) for v in shown_variants) + " |")
    lines.append("|---" * (len(shown_variants) + 1) + "|")
    for m, cells in rows:
        lines.append(f"| `{m}` | " + " | ".join(cells.get(v, "=") for v in shown_variants) + " |")
    unchanged = [v for v in others if v not in shown_variants]
    lines.append("")
    lines.append("Variants with no difference from main in this task: " +
                 (", ".join(f"`{v}`" for v in unchanged) if unchanged else "none") + ".")
    lines.append("")


def rotation_rows(values, variants, prefix: str, cases):
    rows = []
    for v in variants:
        for metric in ROT_METRICS:
            ident = values[v].get(f"{prefix}/identity", {}).get(metric)
            if ident is None:
                continue
            base = num(ident)
            changed = []
            for k in range(12):
                r = values[v].get(f"{prefix}/rot{k:02d}", {}).get(metric)
                if r is None:
                    continue
                if abs(num(r) - base) > ROT_TOL:
                    changed.append(abs(num(r) - base))
            mir = values[v].get(f"{prefix}/mirror_z", {}).get(metric)
            mir_delta = abs(num(mir) - base) if mir is not None else None
            rows.append((v, metric, base, len(changed), max(changed) if changed else 0.0, mir_delta))
    return rows


def section_rotation(values, variants, prefix: str, title: str, cases, lines):
    rows = rotation_rows(values, variants, prefix, cases)
    if not rows:
        return
    lines.append(f"### {title}")
    lines.append("")
    lines.append("Reference is the unrotated target (`{0}/identity`). A rotation counts as changing the metric when "
                 "its value differs from that reference by more than {1:g}. Mirror is z -> -z.".format(prefix, ROT_TOL))
    lines.append("")
    lines.append("| variant | metric | unrotated value | rotations changing it (of 12) | max change over rotations "
                 "| change under mirror |")
    lines.append("|---|---|---|---|---|---|")
    for v, metric, base, n, mx, mir in rows:
        mir_s = "n/a" if mir is None else f"{mir:.4g}"
        lines.append(f"| `{v}` | `{metric}` | {base:.6g} | {n} | {mx:.4g} | {mir_s} |")
    lines.append("")


def section_unique(values, variants, cases, task, title, lines):
    cs = task_cases(cases, task)
    if not cs:
        return
    variants = ran(values, variants, cs)
    lines.append(f"### {title}")
    lines.append("")
    rows = []
    for m in metrics_in(values, variants, cs):
        reporters = [v for v in variants if any(m in values[v][c] for c in cs)]
        if len(reporters) != len(variants):
            missing = [v for v in variants if v not in reporters]
            rows.append((m, reporters, missing))
    if not rows:
        lines.append("Every variant reports the same metric names for this task.")
        lines.append("")
        return
    lines.append("| metric | reported by | not reported by |")
    lines.append("|---|---|---|")
    for m, rep, miss in rows:
        lines.append(f"| `{m}` | {', '.join(f'`{v}`' for v in rep)} | {', '.join(f'`{v}`' for v in miss)} |")
    lines.append("")


def ran_for(cost, variants, cases, task):
    """Variants that have at least one recorded run for this task's cases."""
    cs = set(task_cases(cases, task))
    return [v for v in variants if cs & set(cost[v])]


def main() -> None:
    values, cost, errors, order, cases = load()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    variants = [v for v in order]
    others = [v for v in variants if v != MAIN]

    lines = ["# RESULTS", "",
             "Generated by `summarise.py` from `results/grid.csv` (variant, case, metric, value, runtime_s, "
             "peak_rss_mb) and `variants.json` (the variant table). Every measured number below comes from grid.csv. Seed 0 everywhere. Reference variant for "
             "differences: `" + MAIN + "`.", ""]

    lines.append("## Variants in this run")
    lines.append("")
    lines.append("| variant | origin | date | issue #7 fix | scoring files byte-identical to |")
    lines.append("|---|---|---|---|---|")
    for v in variants:
        r = registry["variants"][v]
        same = ", ".join(f"`{x}`" for x in r["identical_scoring_modules_to"]) or "none"
        lines.append(f"| `{v}` | {r['origin']} | {r['date']} | {'yes' if r['issue7_fix'] else 'no'} | {same} |")
    lines.append("")

    lines.append("## Metrics that differ from main, per task")
    lines.append("")
    for task, title in TASKS:
        ran = ran_for(cost, variants, cases, task)
        section_differences(values, [v for v in others if v in ran], cases, task, title, lines)

    lines.append("## Rotation check (occupancy_dice and sliced_wasserstein)")
    lines.append("")
    section_rotation(values, variants, "T2", "T2 heart, 150-cell samples", cases, lines)
    section_rotation(values, ran_for(cost, variants, cases, "REAL"), "REAL", "T2 heart, real-scale check (3,000 cells of the released E9.5 MERFISH file)", cases, lines)

    lines.append("## Metrics not reported by every variant")
    lines.append("")
    for task, title in TASKS:
        section_unique(values, ran_for(cost, variants, cases, task), cases, task, title, lines)

    lines.append("## Run cost and errors")
    lines.append("")
    lines.append("| variant | cases run | errors | sum of runtimes (s) | max peak RSS (MB) |")
    lines.append("|---|---|---|---|---|")
    for v in variants:
        rts = [cost[v][c][0] for c in cost[v]]
        rss = [cost[v][c][1] for c in cost[v]]
        lines.append(f"| `{v}` | {len(rts)} | {len(errors[v])} | {sum(rts):.1f} | {max(rss):.1f} |")
    lines.append("")
    for v in variants:
        for c, msg in errors[v]:
            lines.append(f"- error `{v}` `{c}`: {msg}")
    lines.append("")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
