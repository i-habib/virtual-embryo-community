"""Tests for build.py on a small synthetic board. Run: python -m pytest -q test_build.py"""
import math

import pytest

import build as B

METRICS = {
    "alpha": {"label": "Alpha", "weight": 0.6},
    "beta": {"label": "Beta", "weight": 0.4},
}


def make_rows():
    # 12 teams. alpha skills fall with rank; beta is 100 for the first four teams.
    rows = []
    for i in range(12):
        rank = i + 1
        rows.append({
            "name": f"team<{rank}>",
            "track": "agent" if rank % 3 == 0 else "human",
            "rank": rank,
            "metrics": {
                "alpha": 100.0 - 2.0 * i,
                "beta": 100.0 if i < 4 else 90.0 - i,
            },
        })
    for r in rows:
        r["headline"] = sum(METRICS[k]["weight"] * r["metrics"][k] for k in METRICS)
    return rows


def test_percentile_linear_interpolation():
    assert B.percentile([1, 2, 3, 4, 5], 90) == pytest.approx(4.6)
    assert B.percentile([1, 2, 3, 4, 5], 10) == pytest.approx(1.4)
    assert B.percentile([7], 90) == 7


def test_spread_points_and_headroom_are_weighted():
    ranked = make_rows()
    st = B.metric_stats(ranked, "alpha", 0.6)
    top20 = [100.0 - 2.0 * i for i in range(12)]  # only 12 teams, so the top 20 is all of them
    spread = B.percentile(top20, 90) - B.percentile(top20, 10)
    assert st["spread"] == pytest.approx(spread)
    assert st["spread_pts"] == pytest.approx(0.6 * spread)
    med10 = statistics_median([100.0 - 2.0 * i for i in range(10)])
    assert st["median10"] == pytest.approx(med10)
    assert st["headroom"] == pytest.approx((100.0 - med10) * 0.6)


def statistics_median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def test_saturation_share_uses_top_50_threshold():
    ranked = make_rows()
    # beta is >= 99.5 for teams 1 to 4 only, out of 12 teams in the top 50 window.
    st = B.metric_stats(ranked, "beta", 0.4)
    assert st["saturated"] == pytest.approx(4 / 12)
    # A skill of 99.4 does not count as saturated.
    ranked[0]["metrics"]["beta"] = 99.4
    assert B.metric_stats(ranked, "beta", 0.4)["saturated"] == pytest.approx(3 / 12)


def test_gap_rows_are_points_behind_median_largest_first():
    ranked = make_rows()
    med10 = {k: B.metric_stats(ranked, k, m["weight"])["median10"] for k, m in METRICS.items()}
    last = ranked[-1]  # rank 12, outside the top 10, so the median is not its own
    gaps = B.gap_rows(last, med10, METRICS)
    points = [g[3] for g in gaps]
    assert points == sorted(points, reverse=True)
    for key, skill, median, pts in gaps:
        assert skill == last["metrics"][key]
        assert pts == pytest.approx((median - skill) * METRICS[key]["weight"])
    # A team at the top-10 median on every metric is 0 behind everywhere.
    leader = dict(ranked[0], metrics={k: med10[k] for k in METRICS})
    assert all(abs(g[3]) < 1e-9 for g in B.gap_rows(leader, med10, METRICS))


def test_gap_rows_negative_when_ahead():
    med10 = {"alpha": 50.0, "beta": 50.0}
    team = {"metrics": {"alpha": 80.0, "beta": 20.0}}
    gaps = {g[0]: g[3] for g in B.gap_rows(team, med10, METRICS)}
    assert gaps["alpha"] == pytest.approx(-30.0 * 0.6)
    assert gaps["beta"] == pytest.approx(30.0 * 0.4)


def test_headline_check_detects_mismatch():
    ranked = make_rows()
    chk = B.headline_check(ranked, METRICS)
    assert chk["max"] < 1e-9 and chk["over"] == 0
    ranked[3]["headline"] += 0.5
    chk = B.headline_check(ranked, METRICS)
    assert chk["over"] == 1
    assert chk["max"] == pytest.approx(0.5)


def test_track_medians_use_top_20_within_track():
    ranked = make_rows()
    humans = [r for r in ranked if r["track"] == "human"]
    agents = [r for r in ranked if r["track"] == "agent"]
    tm = B.track_medians(ranked)
    assert tm["human"][0] == len(humans)
    assert tm["agent"][0] == len(agents)
    assert tm["human"][1] == pytest.approx(statistics_median([r["headline"] for r in humans]))


def test_jitter_is_deterministic_and_in_unit_interval():
    values = [B.jitter(f"team {i}") for i in range(50)]
    assert all(0.0 <= v < 1.0 for v in values)
    assert values == [B.jitter(f"team {i}") for i in range(50)]


def test_strip_svg_escapes_names_and_marks_tracks():
    svg = B.strip_svg("Alpha", [("team<1> & co", "agent", 60.0), ("b", "human", 80.0)], 70.0, 50.0)
    assert "team<1>" not in svg and "team&lt;1&gt; &amp; co" in svg
    assert 'class="agent"' in svg and 'class="human"' in svg
    assert 'class="floor"' in svg  # dashed floor line, styled by the page CSS


def test_skill_missing_value_counts_as_zero():
    assert B.skill({"metrics": {"alpha": None}}, "alpha") == 0.0
    assert B.skill({"metrics": {"alpha": float("nan")}}, "alpha") == 0.0
    assert B.skill({"metrics": {"alpha": 42}}, "alpha") == 42.0


def test_percentile_rejects_empty():
    with pytest.raises(ValueError):
        B.percentile([], 50)


def test_history_chart_draws_one_path_per_rank():
    rows_a = [{"rank": r, "headline": 80.0 - r} for r in (1, 10, 50)]
    rows_b = [{"rank": r, "headline": 79.0 - r} for r in (1, 10, 50)]
    series = [("2026-10-15", {"rows": rows_a}), ("2026-10-17", {"rows": rows_b})]
    svg = B.history_svg(series)
    assert svg.count('class="hist"') == 3
    assert svg.count("M") == 3
    assert "10-17" in svg  # the later snapshot date is labelled on the axis


def test_fmt_utc():
    assert B.fmt_utc("2026-10-15T00:47:50+00:00") == "2026-10-15 00:47 UTC"
    assert B.fmt_utc("not a date") == "not a date"
