#!/usr/bin/env python3
"""Compare validation-pair and test-pair rankings of the candidates, and score two-slot selection rules.

    python analyse.py --config configs/heart_now.json [--val-pair val] [--test-pair test]

Reads only the cached scores in results/scores.jsonl and writes results/analysis.json and report.html.
Anchors are computed per pair and per seed as the board does: floor = copy_last's metric value on that
pair, ceiling = the split-half ceiling. Skill is metric-lens' metric_skill; headline is the board weighting.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import kendalltau, rankdata, spearmanr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str((HERE.parent / "metric-lens").resolve()))

import vec_metric_lens as vml  # noqa: E402
from config import CEILING, load_config, pair_signature  # noqa: E402
from methods import candidates  # noqa: E402

RULES = {
    "R1": "top-2 by validation headline",
    "R2": "top-1 by validation, plus the best validation candidate from a different family",
    "R3": "top-1 by validation, plus the most dissimilar of the validation top-5",
}
DROP_FRACTION = 0.2
FAMILY_COLOURS = {"copy_last": "#333333", "drift": "#1f77b4", "composition": "#2ca02c", "growth": "#9467bd",
                  "combo": "#ff7f0e", "degraded": "#d62728"}


# ----------------------------------------------------------------- loading

def load_records(results: Path, cfg: dict, pairs: list[str]) -> dict:
    """Records for this config whose pair signature matches the current config, keyed by (pair, candidate, seed)."""
    sigs = {p: pair_signature(cfg, p) for p in pairs}
    out = {}
    for line in results.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec["config"] != cfg["name"] or rec["pair"] not in sigs or rec["signature"] != sigs[rec["pair"]]:
            continue
        out[(rec["pair"], rec["candidate"], rec["seed"])] = rec
    return out


def _num(x) -> float:
    return float(x) if vml._is_number(x) else float("nan")


def anchored_metric(metric: str, board: str, floor: float, ceiling: float) -> dict:
    spec = dict(vml.BOARDS[board]["metrics"][metric])
    spec["floor"] = float(floor)
    spec["ceiling"] = float(ceiling)
    vml.check_anchors(spec, f"{board} {metric} (local anchors)")
    return spec


class PairTable:
    """Raw metrics, per-seed skills, headlines, fingerprints and pseudobulk for every candidate on one pair."""

    def __init__(self, records: dict, pair: str, board: str, names: list[str], families: dict, seeds: list[int]):
        self.pair, self.board, self.names, self.seeds = pair, board, names, seeds
        self.families = [families[n] for n in names]
        self.metrics = list(vml.BOARDS[board]["metrics"].keys())
        C, S, M = len(names), len(seeds), len(self.metrics)
        raw = np.full((C, S, M), np.nan)
        self.fp = [[None] * S for _ in range(C)]
        pb = None
        for ci, c in enumerate(names):
            for si, s in enumerate(seeds):
                rec = records[(pair, c, s)]
                for mi, m in enumerate(self.metrics):
                    raw[ci, si, mi] = _num(rec["metrics"].get(m))
                self.fp[ci][si] = rec["fingerprint"]
                row = np.asarray(rec["pb"], dtype=np.float64)
                if pb is None:
                    pb = np.zeros((C, S, row.size))
                pb[ci, si] = row
        self.pb = pb  # (C, S, genes)
        base = names.index("copy_last")
        self.floor = raw[base].copy()  # (S, M): copy_last on each seed
        self.ceiling = np.array([[_num(records[(pair, CEILING, s)]["metrics"].get(m)) for m in self.metrics]
                                 for s in seeds])  # (S, M)
        self.skill = np.zeros((C, S, M))
        for si in range(S):
            for mi, m in enumerate(self.metrics):
                spec = anchored_metric(m, board, self.floor[si, mi], self.ceiling[si, mi])
                for ci in range(C):
                    self.skill[ci, si, mi] = vml.metric_skill(raw[ci, si, mi], spec)
        self.weights = np.array([vml.BOARDS[board]["metrics"][m]["weight"] for m in self.metrics])
        self.headline = 100.0 * (self.skill * self.weights).sum(axis=2)  # (C, S)
        self.raw = raw

    def dissimilarity(self) -> np.ndarray:
        """Mean absolute difference of per-gene pseudobulk between candidates, averaged over seeds."""
        p = self.pb.mean(axis=1)
        return np.abs(p[:, None, :] - p[None, :, :]).mean(axis=2)

    def distinct_predictions(self) -> dict:
        groups = defaultdict(list)
        for ci, n in enumerate(self.names):
            groups[tuple(self.fp[ci])].append(n)
        return {"distinct": len(groups), "candidates": len(self.names),
                "identical_groups": [g for g in groups.values() if len(g) > 1]}


# ----------------------------------------------------------------- statistics

def average_ranks(x: np.ndarray) -> np.ndarray:
    return rankdata(x, method="average")


def rank_corr(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        return float("nan"), float("nan")
    return float(spearmanr(x, y).statistic), float(kendalltau(x, y).statistic)


def bootstrap_corr(Hv: np.ndarray, Ht: np.ndarray, draws: int, rng) -> dict:
    """Resample seeds with replacement; the same seed indices are used for both pairs."""
    S = Hv.shape[1]
    rhos, taus = [], []
    for _ in range(draws):
        idx = rng.integers(0, S, S)
        r, k = rank_corr(Hv[:, idx].mean(axis=1), Ht[:, idx].mean(axis=1))
        if not math.isnan(r):
            rhos.append(r)
            taus.append(k)

    def interval(v):
        return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v else [None, None]

    return {"spearman_ci": interval(rhos), "kendall_ci": interval(taus),
            "valid_draws": len(rhos), "draws": draws}


def pick_two(rule: str, hv: np.ndarray, u: np.ndarray, families: list[str], dissim: np.ndarray) -> list[int]:
    """Indices into the kept set of the candidates a rule submits. u is a random key that breaks exact ties."""
    order = np.lexsort((u, -hv))
    top1 = int(order[0])
    if rule == "R1":
        return [int(i) for i in order[:2]]
    if rule == "R2":
        other = [int(i) for i in order[1:] if families[i] != families[top1]]
        return [top1, other[0] if other else int(order[1])]
    if rule == "R3":
        pool = [int(i) for i in order[1:5]]
        dists = np.array([dissim[top1, j] for j in pool])
        return [top1, pool[int(np.lexsort((u[pool], -dists))[0])]]
    raise ValueError(f"unknown rule {rule}")


def rule_draws(Hv: np.ndarray, Ht: np.ndarray, names: list[str], families: list[str], dissim: np.ndarray,
               rule: str, draws: int, rng, perturb: bool) -> dict:
    """Regret of one rule over repeated draws. Perturbed draws resample seeds and drop 20% of candidates."""
    C, S = Hv.shape
    regrets, picked = [], Counter()
    for _ in range(draws):
        if perturb:
            seed_idx = rng.integers(0, S, S)
            keep = np.sort(rng.choice(C, size=C - int(round(DROP_FRACTION * C)), replace=False))
        else:
            seed_idx = np.arange(S)
            keep = np.arange(C)
        hv = Hv[keep][:, seed_idx].mean(axis=1)
        ht = Ht[keep][:, seed_idx].mean(axis=1)
        u = rng.random(len(keep))
        fams = [families[i] for i in keep]
        picks = pick_two(rule, hv, u, fams, dissim[np.ix_(keep, keep)])
        regrets.append(float(ht.max() - ht[picks].max()))
        picked.update(names[keep[p]] for p in picks)
    r = np.array(regrets)
    return {"mean": float(r.mean()), "sd": float(r.std(ddof=1)) if len(r) > 1 else 0.0,
            "p5": float(np.percentile(r, 5)), "p95": float(np.percentile(r, 95)),
            "share_zero": float((r < 1e-9).mean()), "draws": draws,
            "pick_share": {k: v / draws for k, v in picked.most_common(6)}}  # share of draws submitting it


# ----------------------------------------------------------------- analysis

def analyse(cfg: dict, records: dict, val_name: str, test_name: str, draws: int, boot_draws: int,
            rng_seed: int, veckit_version: str) -> dict:
    seeds = cfg["seeds"]
    objs = candidates()
    names = [c.name for c in objs]
    families = {c.name: c.family for c in objs}
    vp, tp = cfg["pairs"][val_name], cfg["pairs"][test_name]
    if vp["board"] != tp["board"]:
        raise SystemExit("validation and test pairs must use the same board for a headline comparison")
    val = PairTable(records, val_name, vp["board"], names, families, seeds)
    test = PairTable(records, test_name, tp["board"], names, families, seeds)
    rng = np.random.default_rng(rng_seed)
    Hv, Ht = val.headline, test.headline
    mv, mt = Hv.mean(axis=1), Ht.mean(axis=1)
    rv, rt = average_ranks(-mv), average_ranks(-mt)  # 1 = best
    cand = [{"name": n, "family": families[n],
             "val_mean": float(mv[i]), "val_sd": float(Hv[i].std(ddof=1)),
             "test_mean": float(mt[i]), "test_sd": float(Ht[i].std(ddof=1)),
             "val_rank": float(rv[i]), "test_rank": float(rt[i]),
             "val_by_seed": [float(x) for x in Hv[i]], "test_by_seed": [float(x) for x in Ht[i]]}
            for i, n in enumerate(names)]
    rho, tau = rank_corr(mv, mt)
    corr = {"spearman": rho, "kendall": tau, **bootstrap_corr(Hv, Ht, boot_draws, rng)}

    per_metric = []
    for mi, m in enumerate(val.metrics):
        r, _ = rank_corr(val.skill[:, :, mi].mean(axis=1), test.skill[:, :, mi].mean(axis=1))
        per_metric.append({"metric": m, "spearman": r})

    dissim = val.dissimilarity()
    rules = {}
    for key in RULES:
        rules[key] = {
            "label": RULES[key],
            "full_set": rule_draws(Hv, Ht, names, val.families, dissim, key, draws, rng, perturb=False),
            "perturbed": rule_draws(Hv, Ht, names, val.families, dissim, key, draws, rng, perturb=True),
        }

    anchors = {m: {"floor": float(val.floor[:, mi].mean()), "ceiling": float(val.ceiling[:, mi].mean())}
               for mi, m in enumerate(val.metrics)}

    def pair_info(spec, table):
        base = table.names.index("copy_last")
        identical = [table.names[i] for i in range(len(table.names))
                     if i != base and table.fp[i] == table.fp[base]]
        return {"inputs": spec["inputs"], "target": spec["target"], "task": spec["task"],
                "distinct_predictions": table.distinct_predictions(),
                "identical_to_copy_last": identical,
                "distinct_headline_values": int(len(np.unique(np.round(table.headline.mean(axis=1), 6))))}

    top_val = mv.max()
    tied = [i for i in range(len(names)) if np.isclose(mv[i], top_val)]
    tied_test = mt[tied]
    val_tie = {"headline": float(top_val), "candidates": [names[i] for i in tied],
               "test_mean_of_tied": float(tied_test.mean()), "test_best_in_tie": float(tied_test.max()),
               "test_best_overall": float(mt.max())}

    return {
        "config": cfg["name"], "board": vp["board"], "veckit": veckit_version, "seeds": seeds,
        "val_top_tie": val_tie,
        "subsample_cells": cfg["subsample_cells"], "val_pair": val_name, "test_pair": test_name,
        "step_days": {"val": cfg["stages"][vp["target"]]["time"] - cfg["stages"][vp["inputs"][-1]]["time"],
                      "test": cfg["stages"][tp["target"]]["time"] - cfg["stages"][tp["inputs"][-1]]["time"]},
        "pairs": {val_name: pair_info(vp, val), test_name: pair_info(tp, test)},
        "anchors": anchors, "candidates": cand, "correlation": corr,
        "per_metric": per_metric, "rules": rules, "rng_seed": rng_seed,
        "rule_draws": draws, "bootstrap_draws": boot_draws,
        "n_inputs": {"val": len(vp["inputs"]), "test": len(tp["inputs"])},
    }


# ----------------------------------------------------------------- plain English

def _f(x, nd=2):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def plain_english(res: dict) -> list[str]:
    v, t = res["pairs"][res["val_pair"]], res["pairs"][res["test_pair"]]
    C = len(res["candidates"])
    by_val = sorted(res["candidates"], key=lambda c: (-c["val_mean"], c["val_rank"]))
    by_test = sorted(res["candidates"], key=lambda c: (-c["test_mean"], c["test_rank"]))
    rules = res["rules"]
    best_rule = min(rules, key=lambda k: rules[k]["perturbed"]["mean"])
    n_ident = len(v["identical_to_copy_last"]) + 1
    tie = res["val_top_tie"]
    one_input = res["n_inputs"]["val"] == 1
    paras = [
        f"Validation pair ({res['val_pair']}: inputs {', '.join(v['inputs'])}, target {v['target']}, "
        f"{res['n_inputs']['val']} input stage{'s' if res['n_inputs']['val'] != 1 else ''}). "
        f"{n_ident} of the {C} candidates, copy_last included, share copy_last's expression matrix, and the validation side has "
        f"{v['distinct_predictions']['distinct']} distinct expression matrices in total (growth changes only coordinates, "
        f"so the count ignores it)."
        + (f" The validation headline ties {len(tie['candidates'])} candidates at {_f(tie['headline'])}."
           if len(tie["candidates"]) > 1 else " No two candidates tie on the top validation headline.")
        + (" With one input stage every trend estimate is zero, which explains the ties." if one_input else ""),
        f"Test pair ({res['test_pair']}: inputs {', '.join(t['inputs'])}, target {t['target']}, "
        f"{res['n_inputs']['test']} input stages): {t['distinct_predictions']['distinct']} distinct expression matrices "
        f"among {C} candidates. The best candidate on test is {by_test[0]['name']} "
        f"({_f(by_test[0]['test_mean'])}), and {by_test[-1]['name']} is worst ({_f(by_test[-1]['test_mean'])}).",
        f"Top three on validation: " + "; ".join(f"{c['name']} ({_f(c['val_mean'])})" for c in by_val[:3])
        + ". Top three on test: " + "; ".join(f"{c['name']} ({_f(c['test_mean'])})" for c in by_test[:3]) + ".",
        f"Across candidates, the Spearman correlation between validation and test headlines is "
        f"{_f(res['correlation']['spearman'], 3)} (Kendall tau-b {_f(res['correlation']['kendall'], 3)}). The "
        f"seed-bootstrap 95% intervals are {_f(res['correlation']['spearman_ci'][0], 3)} to "
        f"{_f(res['correlation']['spearman_ci'][1], 3)} for Spearman and {_f(res['correlation']['kendall_ci'][0], 3)} to "
        f"{_f(res['correlation']['kendall_ci'][1], 3)} for Kendall. These intervals reflect seed resampling only. They do "
        f"not reflect the choice of pseudo pair or the candidate set.",
        "Two-slot regret, perturbed draws (mean; 5th to 95th percentile): "
        + "; ".join(f"{k} {_f(rules[k]['perturbed']['mean'])} ({_f(rules[k]['perturbed']['p5'])} to "
                    f"{_f(rules[k]['perturbed']['p95'])})" for k in rules)
        + f". The lowest mean regret is {best_rule} in this run.",
    ]
    return paras


def limits(res: dict) -> list[str]:
    out = [
        f"One pseudo pair per side, heart only. The validation step is {res['step_days']['val']:g} days, with "
        f"{res['n_inputs']['val']} input stages, and the test step is {res['step_days']['test']:g} days, with "
        f"{res['n_inputs']['test']} input stages. Real steps are 1 day (validation) and 2 days (test).",
        f"Each stage was subsampled to {res['subsample_cells']} cells. Headlines are noisier than on full stages, and "
        "3 seeds give little information about seed noise.",
        "Candidate families are simple shifts, resamplings and rescalings. A real submission uses a learned model, so these "
        "rankings do not transfer one-for-one to model rankings.",
        "Degraded controls shrink each cell toward the per-gene mean of the predicted cells. This is one reading of "
        "'shrunk toward the population mean'.",
        "Local anchors come from split-half scores within one pseudo target. They are not the organisers' ceilings.",
    ]
    return out


# ----------------------------------------------------------------- figures and report

def _png(fig) -> str:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def figures(res: dict) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = res["candidates"]
    out = {}
    fig, ax = plt.subplots(figsize=(7.4, 5.2))
    for r in rows:
        ax.errorbar(r["val_mean"], r["test_mean"], xerr=r["val_sd"], yerr=r["test_sd"], fmt="o", ms=6,
                    color=FAMILY_COLOURS[r["family"]], capsize=2, lw=1)
        ax.annotate(r["name"], (r["val_mean"], r["test_mean"]), textcoords="offset points", xytext=(5, 4),
                    fontsize=6.5)
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, label=f) for f, c in FAMILY_COLOURS.items()
               if any(r["family"] == f for r in rows)]
    ax.legend(handles=handles, fontsize=7, loc="best")
    ax.set_xlabel(f"{res['val_pair']} pair headline (mean over seeds, bars = 1 sd)")
    ax.set_ylabel(f"{res['test_pair']} pair headline (mean over seeds, bars = 1 sd)")
    ax.set_title("Candidate headlines on the two pairs")
    ax.grid(alpha=0.3)
    out["scatter"] = _png(fig)

    fig, ax = plt.subplots(figsize=(6.4, 5.0))
    n = len(rows)
    for r in rows:
        ax.plot([0, 1], [r["val_rank"], r["test_rank"]], color=FAMILY_COLOURS[r["family"]], lw=1.2, alpha=0.8)
        ax.annotate(r["name"], (0, r["val_rank"]), textcoords="offset points", xytext=(-4, 0), ha="right",
                    va="center", fontsize=6)
        ax.annotate(r["name"], (1, r["test_rank"]), textcoords="offset points", xytext=(4, 0), ha="left",
                    va="center", fontsize=6)
    ax.set_xticks([0, 1])
    ax.set_xticklabels([f"{res['val_pair']} rank", f"{res['test_pair']} rank"])
    ax.set_xlim(-1.1, 2.1)
    ax.set_ylim(n + 0.6, 0.4)
    ax.set_ylabel("rank (1 = best; ties averaged)")
    ax.set_title("Rank bump chart")
    out["bump"] = _png(fig)

    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    keys = list(res["rules"])
    p = [res["rules"][k]["perturbed"] for k in keys]
    means = [x["mean"] for x in p]
    # Error bars are clipped at zero: with a skewed regret distribution the 95th percentile can sit below the mean.
    ax.bar(keys, means, yerr=[[max(0.0, x["mean"] - x["p5"]) for x in p],
                              [max(0.0, x["p95"] - x["mean"]) for x in p]],
           capsize=4, color=["#7f7f7f", "#1f77b4", "#2ca02c"][: len(keys)])
    ax.set_ylabel("regret (headline points)")
    ax.set_title("Regret of two-slot rules (bar = mean; whiskers = 5th to 95th percentile)")
    ax.grid(axis="y", alpha=0.3)
    out["regret"] = _png(fig)
    return out


def build_report(res: dict, figs: dict) -> str:
    e = html.escape
    v, t = res["val_pair"], res["test_pair"]
    cand_rows = "".join(
        f"<tr><td>{e(c['name'])}</td><td>{e(c['family'])}</td>"
        f"<td>{_f(c['val_mean'])} &plusmn; {_f(c['val_sd'])}</td><td>{c['val_rank']:.1f}</td>"
        f"<td>{_f(c['test_mean'])} &plusmn; {_f(c['test_sd'])}</td><td>{c['test_rank']:.1f}</td></tr>"
        for c in res["candidates"])
    corr = res["correlation"]
    metric_rows = "".join(f"<tr><td>{e(m['metric'])}</td><td>{_f(m['spearman'], 3)}</td></tr>"
                          for m in res["per_metric"])
    rule_rows = "".join(
        f"<tr><td>{k}: {e(r['label'])}</td><td>{_f(r['full_set']['mean'])}</td>"
        f"<td>{_f(r['perturbed']['mean'])}</td><td>{_f(r['perturbed']['sd'])}</td>"
        f"<td>{_f(r['perturbed']['p5'])} to {_f(r['perturbed']['p95'])}</td>"
        f"<td>{_f(r['perturbed']['share_zero'], 3)}</td></tr>"
        for k, r in res["rules"].items())
    anchor_rows = "".join(f"<tr><td>{e(m)}</td><td>{_f(a['floor'], 4)}</td><td>{_f(a['ceiling'], 4)}</td></tr>"
                          for m, a in res["anchors"].items())
    dv, dt = res["pairs"][v]["distinct_predictions"], res["pairs"][t]["distinct_predictions"]
    img = lambda k: f'<img alt="{e(k)} figure" src="data:image/png;base64,{figs[k]}" style="max-width:100%">'
    css = ("body{font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;"
           "color:#1a1a1a;line-height:1.5}table{border-collapse:collapse;margin:10px 0 18px;font-size:13px}"
           "td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}th{background:#f3f3f3}"
           "h1{font-size:22px}h2{font-size:17px;margin-top:28px}code{font-size:12px}")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Val-to-test transfer</title><style>{css}</style></head><body>
<h1>Does a validation-pair ranking carry over to a test-pair ranking?</h1>
<p>Config <code>{e(res['config'])}</code>. Board <code>{e(res['board'])}</code>, task T2 heart. Scorer veckit
commit <code>{e(res['veckit'])}</code>. Seeds {res['seeds']}. Each stage subsampled to {res['subsample_cells']} cells.
Validation pair <code>{e(v)}</code>: inputs {e(', '.join(res['pairs'][v]['inputs']))}, target
{e(res['pairs'][v]['target'])}, step {res['step_days']['val']:g} days. Test pair <code>{e(t)}</code>: inputs
{e(', '.join(res['pairs'][t]['inputs']))}, target {e(res['pairs'][t]['target'])}, step {res['step_days']['test']:g} days.</p>

<h2>Summary</h2>
{''.join(f'<p>{e(p)}</p>' for p in plain_english(res))}

<h2>Candidates</h2>
<p>Headline = board weights on the eight T2 heart metrics, skill from metric-lens with per-seed local anchors
(floor = copy_last, ceiling = split-half). Mean &plusmn; sd over {len(res['seeds'])} seeds. Ranks average ties.</p>
<table><tr><th>Candidate</th><th>Family</th><th>{e(v)} headline</th><th>{e(v)} rank</th>
<th>{e(t)} headline</th><th>{e(t)} rank</th></tr>{cand_rows}</table>
{img('scatter')}
{img('bump')}

<h2>Rank agreement</h2>
<table><tr><th>Statistic</th><th>Estimate</th><th>95% interval (seed bootstrap)</th></tr>
<tr><td>Spearman rho</td><td>{_f(corr['spearman'], 3)}</td><td>{_f(corr['spearman_ci'][0], 3)} to {_f(corr['spearman_ci'][1], 3)}</td></tr>
<tr><td>Kendall tau-b</td><td>{_f(corr['kendall'], 3)}</td><td>{_f(corr['kendall_ci'][0], 3)} to {_f(corr['kendall_ci'][1], 3)}</td></tr></table>
<p>{corr['draws']} bootstrap draws, {corr['valid_draws']} valid (a draw is invalid when one side is constant).</p>

<h2>Per-metric transfer</h2>
<p>Spearman correlation, across candidates, of each metric's mean skill on the two pairs. n/a means the metric is
constant across the validation candidates, so no rank correlation exists for it.</p>
<table><tr><th>Metric</th><th>Spearman</th></tr>{metric_rows}</table>

<h2>Two-slot rules</h2>
<p>Regret = best test headline among the candidates kept in a draw, minus the best test headline among the two
submitted. Full set: all candidates and seeds, ties broken at random ({res['rule_draws']} draws). Perturbed: seeds
resampled with replacement, {int(DROP_FRACTION * 100)}% of candidates dropped at random, ties broken at random
({res['rule_draws']} draws).</p>
<table><tr><th>Rule</th><th>Regret, full set</th><th>Regret, perturbed mean</th><th>sd</th>
<th>5th to 95th percentile</th><th>Share of draws with zero regret</th></tr>{rule_rows}</table>
{img('regret')}

<h2>Anchors and degeneracy</h2>
<p>Local anchors on the validation pair, mean over seeds. Distinct predictions: {dv['distinct']} of {dv['candidates']}
on {e(v)}, {dt['distinct']} of {dt['candidates']} on {e(t)}.</p>
<table><tr><th>Metric</th><th>Floor (copy_last)</th><th>Ceiling (split-half)</th></tr>{anchor_rows}</table>

<h2>Limits</h2>
<ul>{''.join(f'<li>{e(x)}</li>' for x in limits(res))}</ul>
</body></html>
"""


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--results", type=Path, default=HERE / "results" / "scores.jsonl")
    ap.add_argument("--val-pair", default="val")
    ap.add_argument("--test-pair", default="test")
    ap.add_argument("--rule-draws", type=int, default=500)
    ap.add_argument("--bootstrap-draws", type=int, default=2000)
    ap.add_argument("--rng-seed", type=int, default=20261020)
    ap.add_argument("--analysis", type=Path, default=HERE / "results" / "analysis.json")
    ap.add_argument("--report", type=Path, default=HERE / "report.html")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    records = load_records(args.results, cfg, [args.val_pair, args.test_pair])
    version = next(iter(records.values()))["veckit"]
    res = analyse(cfg, records, args.val_pair, args.test_pair, args.rule_draws, args.bootstrap_draws,
                  args.rng_seed, version)
    args.analysis.parent.mkdir(parents=True, exist_ok=True)
    args.analysis.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(build_report(res, figures(res)), encoding="utf-8")
    print(f"wrote {args.analysis} and {args.report}")


if __name__ == "__main__":
    main()
