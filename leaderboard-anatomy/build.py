#!/usr/bin/env python3
"""Build index.html from the snapshots written by fetch.py (standard library only).

Per board, from the latest snapshot:
  * the top-20 spread of each metric, in headline points,
  * saturation in the top 50 and headroom above the top-10 median,
  * one strip plot per metric for the top 50,
  * a team lookup (points behind the top-10 median, by metric),
  * median headline by track, and a history chart once two snapshots exist.

Weights, directions and labels come from ../metric-lens/vec_metric_lens.py.
"""
from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import math
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
SNAP_ROOT = HERE / "snapshots"
OUT_HTML = HERE / "index.html"
LENS_PATH = HERE.parent / "metric-lens" / "vec_metric_lens.py"

BOARD_ORDER = ["T1:val", "T2:heart:val_interp", "T2:heart:val_extrap", "T2:embryo:val_interp", "T3:gata4"]
TOP_SPREAD = 20      # "Where the top 20 separate"
TOP_STRIP = 50       # strip plots, saturation share
TOP_MEDIAN = 10      # reference median for headroom and lookup
SATURATED_AT = 99.5
FLOOR_DEFAULT = 50.0  # copy_last floor skill, used if the snapshot has no copy_last row
HEADLINE_TOL = 0.001

CSS = """
:root{--bg:#fff;--ink:#1f1f1f;--muted:#666;--rule:#e3e3e3;--human:#3b6ea5;--agent:#c0573e;--grey:#8a8a8a}
@media (prefers-color-scheme: dark){:root{--bg:#141414;--ink:#e8e8e8;--muted:#a0a0a0;--rule:#2c2c2c;--human:#7ca7d6;--agent:#e8836a;--grey:#7a7a7a}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;font-variant-numeric:tabular-nums}
main{max-width:980px;margin:0 auto;padding:24px 16px 72px;text-align:left}
h1{font-size:20px;font-weight:600;margin:0 0 6px}
h2{font-size:17px;font-weight:600;margin:0;padding-top:28px;border-top:1px solid var(--rule)}
h3{font-size:15px;font-weight:600;margin:26px 0 6px}
p{margin:6px 0}
.muted{color:var(--muted)}
.small{font-size:13px}
nav ul{list-style:none;margin:14px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:4px 18px}
nav a{color:var(--ink)}
section{margin-top:8px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:6px 8px 6px 0;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-weight:600;color:var(--muted)}
td.n,th.n{text-align:right;padding-left:12px}
td.key{color:var(--muted);font-size:12px}
.strips{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,430px),1fr));gap:14px 24px;margin-top:8px}
figure{margin:0}
figcaption{font-size:13px;margin-bottom:0}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{fill:var(--muted);font-size:11px}
.dot.human,circle.human{fill:var(--human)}
.dot.agent,circle.agent{fill:var(--agent)}
circle.other{fill:var(--grey)}
circle{fill-opacity:.85}
.tick{stroke:var(--ink);stroke-width:1.5}
.floor{stroke:var(--grey);stroke-width:1;stroke-dasharray:3 3}
.axis{stroke:var(--rule);stroke-width:1}
.hist{fill:none;stroke-width:1.5}
.legend{font-size:13px;color:var(--muted);margin:8px 0 0}
.sw{display:inline-block;width:9px;height:9px;border-radius:50%;margin:0 4px 0 12px;vertical-align:0}
input[type=search]{font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--rule);padding:6px 8px;width:min(100%,380px)}
.lookup-out{margin-top:10px}
footer{margin-top:48px;border-top:1px solid var(--rule);padding-top:12px;font-size:13px;color:var(--muted)}
"""

JS = """
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("lookup-data").textContent);
  function el(tag, text, cls) {
    var e = document.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }
  function f1(x) { return Number(x).toFixed(1); }
  Object.keys(data.boards).forEach(function (key) {
    var board = data.boards[key];
    var root = document.querySelector('[data-board="' + key + '"]');
    if (!root) return;
    var input = root.querySelector("input[type=search]");
    var out = root.querySelector(".lookup-out");
    var teams = new Map();
    board.teams.forEach(function (t) { if (!teams.has(t.name)) teams.set(t.name, t); });
    function render() {
      var q = input.value.trim();
      out.textContent = "";
      if (!q) return;
      var t = teams.get(q);
      if (!t) {
        out.appendChild(el("p", "No team with this exact name in the top " + board.teams.length + " on this board.", "muted"));
        return;
      }
      out.appendChild(el("p", "Rank " + t.rank + " · " + t.track + " · headline " + f1(t.headline)));
      var table = el("table");
      var thead = el("tr");
      ["Metric", "Weight", "Team skill", "Top-10 median", "Points behind"].forEach(function (h, i) {
        thead.appendChild(el("th", h, i ? "n" : null));
      });
      table.appendChild(el("thead")).appendChild(thead);
      var tbody = el("tbody");
      var total = 0;
      t.gaps.forEach(function (g) {
        var m = board.metrics[g[0]];
        var tr = el("tr");
        tr.appendChild(el("td", m[0]));
        tr.appendChild(el("td", f1(m[1] * 100) + "%", "n"));
        tr.appendChild(el("td", f1(g[1]), "n"));
        tr.appendChild(el("td", f1(board.med10[g[0]]), "n"));
        tr.appendChild(el("td", f1(g[2]), "n"));
        if (g[2] > 0) total += g[2];
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      var wrap = el("div", null, "scroll");
      wrap.appendChild(table);
      out.appendChild(wrap);
      out.appendChild(el("p", "Points behind = (top-10 median minus team skill) x weight. Positive means behind that median on the metric; negative means ahead. Sum of the positive values: " + f1(total) + " points. Rows are sorted by points behind.", "small muted"));
    }
    input.addEventListener("input", render);
    input.addEventListener("change", render);
  });
})();
"""


# ---------- loading ----------

def load_board_specs() -> Dict[str, Dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("vec_metric_lens", LENS_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load weights from {LENS_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.BOARDS


def snapshot_dates() -> List[str]:
    if not SNAP_ROOT.is_dir():
        return []
    return sorted(p.name for p in SNAP_ROOT.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))


def board_file(key: str) -> str:
    return key.replace(":", "_") + ".json"


def load_series(key: str) -> List[Tuple[str, Dict[str, Any]]]:
    """(date, parsed snapshot) for every date that has this board, oldest first."""
    out = []
    for d in snapshot_dates():
        p = SNAP_ROOT / d / board_file(key)
        if p.is_file():
            out.append((d, json.loads(p.read_text(encoding="utf-8"))))
    return out


def load_overall() -> Optional[Tuple[str, Dict[str, Any]]]:
    for d in reversed(snapshot_dates()):
        p = SNAP_ROOT / d / "overall.json"
        if p.is_file():
            return d, json.loads(p.read_text(encoding="utf-8"))
    return None


# ---------- statistics ----------

def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def skill(row: Dict[str, Any], key: str) -> float:
    """Metric skill as reported. A missing value counts as 0, as in metric-lens."""
    v = row.get("metrics", {}).get(key)
    return float(v) if is_number(v) else 0.0


def percentile(values: Sequence[float], p: float) -> float:
    """Linear interpolation between order statistics (same as numpy's default)."""
    s = sorted(values)
    if not s:
        raise ValueError("percentile of an empty list")
    k = (len(s) - 1) * p / 100.0
    f = math.floor(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def headline_check(rows: Sequence[Dict[str, Any]], metrics: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    """Reported headline minus sum of weight x skill, per row."""
    diffs = []
    for r in rows:
        pred = sum(m["weight"] * skill(r, k) for k, m in metrics.items())
        diffs.append(abs(float(r["headline"]) - pred))
    return {
        "n": len(diffs),
        "max": max(diffs) if diffs else 0.0,
        "mean": sum(diffs) / len(diffs) if diffs else 0.0,
        "over": sum(1 for d in diffs if d > HEADLINE_TOL),
    }


def metric_stats(ranked: Sequence[Dict[str, Any]], key: str, weight: float) -> Dict[str, float]:
    top_spread = ranked[:TOP_SPREAD]
    top_strip = ranked[:TOP_STRIP]
    top_med = ranked[:TOP_MEDIAN]
    s_spread = [skill(r, key) for r in top_spread]
    s_strip = [skill(r, key) for r in top_strip]
    s_med = [skill(r, key) for r in top_med]
    med10 = statistics.median(s_med)
    spread = percentile(s_spread, 90) - percentile(s_spread, 10)
    return {
        "median20": statistics.median(s_spread),
        "spread": spread,
        "spread_pts": spread * weight,
        "saturated": sum(1 for s in s_strip if s >= SATURATED_AT) / len(s_strip),
        "median10": med10,
        "headroom": (100.0 - med10) * weight,
    }


def gap_rows(team: Dict[str, Any], med10: Dict[str, float], metrics: Dict[str, Dict[str, Any]]) -> List[Tuple[str, float, float, float]]:
    """(metric key, team skill, median, points behind) for each metric, largest points behind first.

    Points behind = (top-10 median skill - team skill) x weight. Negative means ahead.
    """
    out = []
    for k, m in metrics.items():
        s = skill(team, k)
        out.append((k, s, med10[k], (med10[k] - s) * m["weight"]))
    return sorted(out, key=lambda g: g[3], reverse=True)


def track_medians(ranked: Sequence[Dict[str, Any]]) -> Dict[str, Tuple[int, Optional[float]]]:
    out = {}
    for track in ("human", "agent"):
        sub = [r for r in ranked if r.get("track") == track][:TOP_SPREAD]
        out[track] = (len(sub), statistics.median(float(r["headline"]) for r in sub) if sub else None)
    return out


def jitter(name: str) -> float:
    """Deterministic value in [0, 1) from the team name."""
    return int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16) / 0x100000000


# ---------- rendering helpers ----------

def esc(x: Any) -> str:
    return html.escape(str(x), quote=True)


def f1(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.1f}"


def pct(x: float) -> str:
    return f"{100.0 * x:.1f}%"


def fmt_utc(stamp: Any) -> str:
    """'2026-10-15T00:47:50+00:00' becomes '2026-10-15 00:47 UTC'. Unparseable input is shown as is."""
    try:
        t = datetime.fromisoformat(str(stamp))
    except ValueError:
        return str(stamp)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def slug(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", key)


def track_class(track: Any) -> str:
    return track if track in ("human", "agent") else "other"


def strip_svg(label: str, team_points: List[Tuple[str, str, float]], med10: float, floor: float) -> str:
    W, H, x0, x1 = 430, 66, 10, 420

    def X(v: float) -> float:
        return x0 + max(0.0, min(100.0, v)) / 100.0 * (x1 - x0)

    parts = [f'<line class="axis" x1="{x0}" y1="46" x2="{x1}" y2="46"/>']
    parts.append(f'<line class="floor" x1="{X(floor):.1f}" y1="4" x2="{X(floor):.1f}" y2="46"/>')
    for name, track, s in team_points:
        cy = 8 + jitter(name) * 32
        parts.append(
            f'<circle class="{track_class(track)}" cx="{X(s):.1f}" cy="{cy:.1f}" r="3.2">'
            f"<title>{esc(name)}: {s:.1f}</title></circle>"
        )
    parts.append(f'<line class="tick" x1="{X(med10):.1f}" y1="2" x2="{X(med10):.1f}" y2="46"/>')
    for v in (0, 50, 100):
        anchor = "start" if v == 0 else ("end" if v == 100 else "middle")
        parts.append(f'<text x="{X(v):.1f}" y="60" text-anchor="{anchor}">{v}</text>')
    body = "".join(parts)
    return (
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(label)}: team skills, top 50">{body}</svg>'
    )


def history_svg(series: List[Tuple[str, Dict[str, Any]]]) -> str:
    dates = [datetime.fromisoformat(d).replace(tzinfo=timezone.utc) for d, _ in series]
    span_days = max((dates[-1] - dates[0]).days, 1)
    ranks = [(1, "rank 1", "var(--ink)"), (10, "rank 10", "var(--grey)"), (50, "rank 50", "var(--muted)")]
    pts: Dict[int, List[Tuple[float, float]]] = {r: [] for r, _, _ in ranks}
    for (d, obj), dt_ in zip(series, dates):
        by_rank = {int(r["rank"]): float(r["headline"]) for r in obj["rows"]}
        for r, _, _ in ranks:
            if r in by_rank:
                pts[r].append(((dt_ - dates[0]).days, by_rank[r]))
    all_vals = [v for lst in pts.values() for _, v in lst]
    if not all_vals:
        return ""
    lo, hi = math.floor(min(all_vals)) - 2, math.ceil(max(all_vals)) + 2
    W, H, x0, x1, y0, y1 = 430, 170, 36, 420, 12, 140

    def X(d: float) -> float:
        return x0 + d / span_days * (x1 - x0)

    def Y(v: float) -> float:
        return y1 - (v - lo) / (hi - lo) * (y1 - y0)

    parts = [f'<line class="axis" x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}"/>']
    for v in (lo, (lo + hi) / 2, hi):
        parts.append(f'<text x="{x0 - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:.0f}</text>')
    for (r, label, colour) in ranks:
        lst = pts[r]
        if not lst:
            continue
        path = " ".join(f"{'M' if i == 0 else 'L'}{X(d):.1f},{Y(v):.1f}" for i, (d, v) in enumerate(lst))
        parts.append(f'<path class="hist" style="stroke:{colour}" d="{path}"/>')
        d_last, v_last = lst[-1]
        parts.append(f'<text x="{X(d_last) + 6:.1f}" y="{Y(v_last) + 4:.1f}" style="fill:{colour}">{label}</text>')
    for (d, _), dt_ in zip(series, dates):
        off = (dt_ - dates[0]).days
        parts.append(f'<text x="{X(off):.1f}" y="{y1 + 16}" text-anchor="middle">{esc(d[5:])}</text>')
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Headline of rank 1, 10 and 50 over snapshot dates">{"".join(parts)}</svg>'


# ---------- sections ----------

def render_board(key: str, label: str, specs: Dict[str, Dict[str, Any]], overall: Optional[Tuple[str, Dict[str, Any]]],
                 series: List[Tuple[str, Dict[str, Any]]], lookup: Dict[str, Any]) -> str:
    sid = slug(key)
    date_s, obj = series[-1]
    rows = [dict(r, name=r["team"]) for r in obj["rows"]]  # snapshot field "team" becomes "name" here
    ranked = sorted(rows, key=lambda r: int(r["rank"]))
    metrics = {k: {"label": v["label"], "weight": float(v["weight"])} for k, v in specs[key]["metrics"].items()}

    seen = {k for r in rows for k in r.get("metrics", {})}
    if seen != set(metrics):
        print(f"warning: {key}: metric keys in snapshot {sorted(seen)} differ from metric-lens {sorted(metrics)}", file=sys.stderr)

    stats = {k: metric_stats(ranked, k, m["weight"]) for k, m in metrics.items()}
    order = sorted(metrics, key=lambda k: stats[k]["spread_pts"], reverse=True)
    ref = {r.get("name"): r for r in obj.get("reference", []) if isinstance(r, dict)}
    copy_last = (ref.get("copy_last") or {}).get("metrics") or {}
    floors = {k: float(copy_last.get(k, FLOOR_DEFAULT)) for k in metrics}

    n_scored = None
    if overall is not None:
        ov_rows = overall[1].get("rows", [])
        n_scored = sum(1 for r in ov_rows if r.get("boards", {}).get(key) is not None)
    names = [r["name"] for r in ranked]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        print(f"warning: {key}: duplicate team names {dupes[:5]}; lookup uses the first", file=sys.stderr)

    med10_map = {k: stats[k]["median10"] for k in metrics}
    chk = headline_check(rows, metrics)
    tm = track_medians(ranked)
    ov_text = f" The overall file lists {n_scored} teams with a score on this board." if n_scored else ""

    out = [f'<section id="{sid}" data-board="{esc(key)}">']
    out.append(f'<h2>{esc(label)}</h2>')
    out.append(f'<p class="muted small">{esc(obj.get("phase_label") or obj.get("phase") or "")}. '
               f'{len(rows)} teams shown. The board endpoint returns only its top 200.{esc(ov_text)} '
               f'Board updated {esc(fmt_utc(obj.get("updated_at")))}. Snapshot {esc(date_s)}.</p>')

    # 2. table
    out.append('<h3>Where the top 20 separate</h3>')
    out.append('<p class="small muted">Skill is the 0 to 100 value the board reports for each metric. '
               'Spread is P90 minus P10 of the top 20 on that metric. Spread points is the spread times the metric weight: '
               'headline points on which the top 20 differ. Saturated is the share of the top 50 at skill 99.5 or more. '
               'Headroom is what a team at the top-10 median could still add on that metric. Sorted by spread points.</p>')
    out.append('<div class="scroll"><table><thead><tr>'
               '<th>Metric</th><th class="n">Weight</th><th class="n">Top-20 median</th><th class="n">Top-20 spread</th>'
               '<th class="n">Spread points</th><th class="n">Saturated</th><th class="n">Headroom points</th>'
               '</tr></thead><tbody>')
    for k in order:
        s = stats[k]
        out.append(
            f'<tr><td>{esc(metrics[k]["label"])} <span class="key">{esc(k)}</span></td>'
            f'<td class="n">{pct(metrics[k]["weight"])}</td>'
            f'<td class="n">{f1(s["median20"])}</td>'
            f'<td class="n">{f1(s["spread"])}</td>'
            f'<td class="n">{f1(s["spread_pts"])}</td>'
            f'<td class="n">{pct(s["saturated"])}</td>'
            f'<td class="n">{f1(s["headroom"])}</td></tr>'
        )
    out.append('</tbody></table></div>')
    hc = (f'Check: reported headline minus the sum of weight times skill has largest absolute difference '
          f'{chk["max"]:.4f} over {chk["n"]} teams (mean {chk["mean"]:.4f}).')
    if chk["over"]:
        hc += (f' {chk["over"]} teams differ by more than {HEADLINE_TOL}. The points on this page use the skills, '
               f'so they do not add exactly to the reported headline for those teams.')
    out.append(f'<p class="small muted">{esc(hc)}</p>')

    # 3. strips
    out.append('<h3>Where the top 50 sit on each metric</h3>')
    out.append('<p class="small muted">One dot per team in the top 50, placed by skill. Vertical position comes from a '
               'fixed hash of the team name, only to separate dots; it carries no meaning. Tick: top-10 median. '
               'Dashed line: copy_last floor from the snapshot.</p>')
    out.append('<p class="legend"><span class="sw" style="background:var(--human)"></span>human'
               '<span class="sw" style="background:var(--agent)"></span>agent</p>')
    out.append('<div class="strips">')
    top50 = ranked[:TOP_STRIP]
    for k in order:
        pts = [(r["name"], r.get("track", ""), skill(r, k)) for r in top50]
        out.append('<figure>')
        out.append(f'<figcaption>{esc(metrics[k]["label"])} <span class="muted">weight {pct(metrics[k]["weight"])}, '
                   f'spread {f1(stats[k]["spread_pts"])} pts</span></figcaption>')
        out.append(strip_svg(metrics[k]["label"], pts, stats[k]["median10"], floors[k]))
        out.append('</figure>')
    out.append('</div>')

    # 4. lookup
    out.append('<h3>Team lookup</h3>')
    out.append('<p class="small muted">Type a team name from this board. Points behind compare the team with the '
               'top-10 median on each metric. Teams outside the top 200 are not in the data.</p>')
    list_id = f"teams-{sid}"
    out.append(f'<input type="search" list="{esc(list_id)}" aria-label="Team name" placeholder="Team name">')
    out.append(f'<datalist id="{esc(list_id)}">' + "".join(f'<option value="{esc(n)}"></option>' for n in dict.fromkeys(names)) + '</datalist>')
    out.append('<div class="lookup-out" aria-live="polite"></div>')

    idx = {k: i for i, k in enumerate(metrics)}
    lookup["boards"][key] = {
        "label": label,
        "metrics": [[metrics[k]["label"], metrics[k]["weight"]] for k in metrics],
        "med10": [round(med10_map[k], 4) for k in metrics],
        "teams": [
            {
                "name": r["name"],
                "track": r.get("track", ""),
                "rank": r["rank"],
                "headline": float(r["headline"]),
                # [metric index, team skill, points behind], largest points behind first
                "gaps": [[idx[k], round(s_, 4), round(p, 4)] for k, s_, _, p in gap_rows(r, med10_map, metrics)],
            }
            for r in ranked
        ],
    }

    # 5. tracks
    out.append('<h3>Human and agent tracks</h3>')
    hm, am = tm["human"], tm["agent"]
    out.append(f'<p>Median headline of the top 20 human teams: {f1(hm[1])} (n={hm[0]}). '
               f'Top 20 agent teams: {f1(am[1])} (n={am[0]}).</p>')

    # reference rows
    refs = [r for r in obj.get("reference", []) if isinstance(r, dict)]
    if refs:
        bits = " · ".join(f'{esc(r.get("name"))} {f1(float(r.get("headline", 0)))}' for r in refs)
        out.append(f'<p class="small muted">Reference rows (headline): {bits}.</p>')

    # 6. history
    out.append('<h3>Over time</h3>')
    if len(series) > 1:
        out.append(f'<p class="small muted">Headline of rank 1, 10 and 50 by snapshot date, {esc(series[0][0])} to {esc(series[-1][0])}.</p>')
        out.append(history_svg(series))
    else:
        out.append(f'<p class="small muted">One snapshot so far ({esc(date_s)}). This chart appears once a second '
                   f'daily snapshot exists.</p>')
    out.append('</section>')
    return "\n".join(out)


def render_missing(key: str, label: str) -> str:
    return (f'<section id="{slug(key)}"><h2>{esc(label)}</h2>'
            f'<p class="muted">No snapshot for this board yet. Run fetch.py.</p></section>')


def render_page(sections: List[str], nav: List[Tuple[str, str]], lookup: Dict[str, Any], built: str, dates: List[str]) -> str:
    nav_html = "".join(f'<li><a href="#{esc(slug(k))}">{esc(lbl)}</a></li>' for k, lbl in nav)
    data_json = json.dumps(lookup, ensure_ascii=True, separators=(",", ":"))
    data_json = data_json.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    span = "no snapshots" if not dates else (f"snapshot {dates[0]}" if len(dates) == 1 else f"snapshots {dates[0]} to {dates[-1]}")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Virtual Embryo leaderboards: where teams separate</title>
<meta name="description" content="Per-metric spread and headroom across the top teams on each Virtual Embryo Challenge validation board.">
<style>{CSS}</style>
</head>
<body>
<main>
<header>
<h1>Virtual Embryo leaderboards: where teams separate</h1>
<p>For each validation board, this page shows which metrics the top teams have already maxed out, which ones
separate them, and how far any team is behind the top-10 median on each metric.</p>
<p class="small muted">Built {esc(built)} from public leaderboard data, {esc(span)}. Not affiliated with the organisers.
Method and limits: README.md.</p>
<nav><ul>{nav_html}</ul></nav>
</header>
{"".join(sections)}
<footer>Generated by build.py from snapshots/. Skill values are as the board reports them. Validation phase only.</footer>
</main>
<script type="application/json" id="lookup-data">{data_json}</script>
<script>{JS}</script>
</body>
</html>
"""


def main() -> int:
    specs = load_board_specs()
    overall = load_overall()
    lookup: Dict[str, Any] = {"boards": {}}
    sections: List[str] = []
    nav: List[Tuple[str, str]] = []
    labels = {b.get("key"): b.get("label") for b in (overall[1].get("boards", []) if overall else [])}
    all_dates: set = set()

    for key in BOARD_ORDER:
        label = labels.get(key) or key
        nav.append((key, label))
        series = load_series(key)
        all_dates.update(d for d, _ in series)
        if not series:
            sections.append(render_missing(key, label))
            continue
        sections.append(render_board(key, label, specs, overall, series, lookup))
        print(f"built  {key}: {len(series[-1][1]['rows'])} rows from {series[-1][0]}, {len(series)} snapshot(s)")

    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = render_page(sections, nav, lookup, built, sorted(all_dates))
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"wrote  {OUT_HTML.name} ({len(page)} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
