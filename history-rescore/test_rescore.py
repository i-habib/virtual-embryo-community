"""Tests for history-rescore. The scorer is mocked; no veckit is needed.

Run from this folder:  python -m pytest -q
"""
import csv
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "metric-lens"))

import rescore as rs  # noqa: E402
import vec_metric_lens as ml  # noqa: E402

INDEX_SNAPSHOT = HERE / "demo" / "index_snapshot.json"
NODE = shutil.which("node")


def index_from_metric_lens():
    """An index.json-shaped dict whose anchors equal metric-lens's copy, for every known board."""
    out = {}
    for key, b in ml.BOARDS.items():
        task = key.split(":")[0]
        parts = key.split(":")
        entry = {
            "key": key, "task": task, "split": parts[-1], "setting": None, "target_ko": None,
            "min_cells": 1, "max_cells": 10**9,
            "anchors": {m: {"floor": s["floor"], "ceiling": s["ceiling"]} for m, s in b["metrics"].items()},
        }
        if task == "T2":
            entry["setting"] = parts[1]
        if task == "T3":
            entry["target_ko"] = parts[1]
        out[key] = entry
    return out


# ---------------------------------------------------------------- CSV parsing and board guessing

def test_read_submissions_handles_quotes_blanks_and_scores(tmp_path):
    p = tmp_path / "submissions.csv"
    p.write_text(
        "submitted,task,file,board,board_score\n"
        '2026-10-01 10:00,"T2 · heart","pred, run 1.h5ad",T2:heart:val_interp,61.5\n'
        "2026-10-02 10:00,T1,pred_t1.h5ad,,\n"
        "2026-10-03 10:00,T3,pred_t3.h5ad,T3:gata4,n/a\n",
        encoding="utf-8",
    )
    rows = rs.read_submissions(p)
    assert [r["file"] for r in rows] == ["pred, run 1.h5ad", "pred_t1.h5ad", "pred_t3.h5ad"]
    assert rows[0]["board_score"] == 61.5
    assert rows[1]["board"] == "" and rows[1]["board_score"] is None
    assert rows[2]["board_score"] is None  # non-numeric score is kept as missing, not an error


def test_read_submissions_guess_blank_fills_only_blanks(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("submitted,task,file,board,board_score\n"
                 "x,T1,a.h5ad,,1\nx,T1,b.h5ad,T1:val,2\n", encoding="utf-8")
    rows = rs.read_submissions(p, guess_blank=True)
    assert rows[0]["board"] == "T1:val" and rows[1]["board"] == "T1:val"


def test_read_submissions_rejects_missing_column(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("submitted,task,file,board\n", encoding="utf-8")
    with pytest.raises(ValueError, match="board_score"):
        rs.read_submissions(p)


@pytest.mark.parametrize("task,file_name,expected", [
    ("T1", "anything.h5ad", "T1:val"),
    ("T2 · embryo", "e75_run.h5ad", "T2:embryo:val_interp"),
    ("T2 · heart", "pred_E8.5_interp.h5ad", "T2:heart:val_interp"),
    ("T2 · heart", "pred_interp_v2.h5ad", "T2:heart:val_interp"),
    ("T2 · heart", "pred_E10.5_extrap.h5ad", "T2:heart:val_extrap"),
    ("T2 · heart", "pred_plain.h5ad", ""),                 # neither word: set by hand
    ("T2 · heart", "E8.5_and_E10.5.h5ad", ""),             # both words: set by hand
    ("T3", "gata4_try.h5ad", "T3:gata4"),
    ("T9", "x.h5ad", ""),
    ("", "x.h5ad", ""),
])
def test_guess_board(task, file_name, expected):
    assert rs.guess_board(task, file_name) == expected


# ---------------------------------------------------------------- headline and weights

def test_headline_equals_metric_lens_for_fixed_metrics():
    index = index_from_metric_lens()
    fixed = {
        "T1:val": {"de_score": 0.41, "de_direction": 0.66, "mmd_u": 0.02, "variogram": 0.0009},
        "T2:embryo:val_interp": {"de_score": 0.3, "de_direction": 0.5, "mmd_u": 0.1, "variogram": 0.02,
                                 "d2_shape": 0.01, "occupancy_dice": 0.72, "scale_log_ratio": -0.1,
                                 "neighborhood_mmd": 0.05},
        "T3:gata4": {"de_score": 0.2, "de_direction": 0.4, "severity_slope": -1.2, "mmd_u": 0.01,
                     "variogram": 0.004},
    }
    for key, metrics in fixed.items():
        mine = rs.board_headline(metrics, index[key], key)["headline"]
        theirs = ml.board_score(metrics, key)["score"]
        assert math.isclose(mine, theirs, rel_tol=0, abs_tol=1e-9), key


def test_missing_and_nan_metrics_count_as_zero_skill():
    index = index_from_metric_lens()
    key = "T1:val"
    m = {"de_score": float("nan"), "de_direction": None, "mmd_u": 0.01}  # variogram missing
    h = rs.board_headline(m, index[key], key)
    assert h["skills"]["de_score"] == 0.0
    assert h["skills"]["de_direction"] == 0.0
    assert h["skills"]["variogram"] == 0.0
    assert math.isclose(h["headline"], ml.board_score(m, key)["score"], abs_tol=1e-9)


def test_index_anchors_are_the_ones_used():
    index = index_from_metric_lens()
    key = "T1:val"
    m = {"de_score": 0.5, "de_direction": 0.5, "mmd_u": 0.03, "variogram": 0.001}
    base = rs.board_headline(m, index[key], key)["headline"]
    shifted = json.loads(json.dumps(index))
    shifted[key]["anchors"]["de_score"]["ceiling"] = 0.6
    assert rs.board_headline(m, shifted[key], key)["headline"] != base


def test_weights_key_for_test_phase_alias():
    entry = {"task": "T2", "setting": "heart", "split": "test_extrap", "target_ko": None}
    assert rs.weights_key_for("T2:heart:test_extrap", entry, {}) == "T2:heart:val_extrap"
    entry = {"task": "T1", "setting": None, "split": "test", "target_ko": None}
    assert rs.weights_key_for("T1:test", entry, {}) == "T1:val"
    entry = {"task": "T2", "setting": "heart", "split": "test", "target_ko": None}
    with pytest.raises(ValueError, match="weights_from"):
        rs.weights_key_for("T2:heart:test", entry, {})
    assert rs.weights_key_for("T2:heart:test", entry, {"weights_from": "T2:heart:val_interp"}) == "T2:heart:val_interp"


# ---------------------------------------------------------------- Spearman

def test_spearman_with_ties_matches_scipy():
    scipy_stats = pytest.importorskip("scipy.stats")
    x = [1, 2, 2, 3, 5, 5, 5, 8]
    y = [0.1, 0.4, 0.2, 0.2, 0.9, 0.7, 0.7, 1.2]
    rho, n = rs.spearman(x, y)
    expected = scipy_stats.spearmanr(x, y).statistic
    assert n == 8
    assert math.isclose(rho, expected, abs_tol=1e-12)


def test_spearman_small_and_constant_inputs_are_none():
    assert rs.spearman([1, 2], [2, 1]) == (None, 2)
    assert rs.spearman([1, 1, 1], [1, 2, 3])[0] is None
    # only two pairs survive the NaN and None filter, so no rho is reported
    assert rs.spearman([1, None, 3, 4], [1, 2, float("nan"), 4]) == (None, 2)


def test_average_ranks():
    assert rs.average_ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


# ---------------------------------------------------------------- boards.json

def test_load_boards_resolves_paths_and_skips_comments(tmp_path):
    (tmp_path / "rel").mkdir()
    b = tmp_path / "boards.json"
    b.write_text(json.dumps({
        "_note": "ignored",
        "T2:heart:val_interp": {"target": "rel/t.h5ad", "reference": "rel/r.h5ad", "setting": "heart"},
        "T3:gata4": {"target": "/abs/t.h5ad", "wt": "rel/w.h5ad"},
    }), encoding="utf-8")
    boards = rs.load_boards(b)
    assert set(boards) == {"T2:heart:val_interp", "T3:gata4"}
    assert boards["T2:heart:val_interp"]["target"] == (tmp_path / "rel" / "t.h5ad").resolve()
    assert boards["T3:gata4"]["reference"] == (tmp_path / "rel" / "w.h5ad").resolve()
    assert boards["T3:gata4"]["fraction"] == rs.DEFAULT_FRACTION


def test_working_copy_flag_skips_second_subsample(tmp_path, monkeypatch):
    """A release that is already a 10% working copy gets fraction 1.0 instead of a second 10% draw."""
    (tmp_path / "t.h5ad").write_bytes(b"t")
    (tmp_path / "r.h5ad").write_bytes(b"r")
    b = tmp_path / "boards.json"
    b.write_text(json.dumps({"T1:val": {"target": "t.h5ad", "reference": "r.h5ad",
                                         "reference_is_working_copy": True}}), encoding="utf-8")
    cfg = rs.load_boards(b)["T1:val"]
    assert cfg["reference_is_working_copy"] is True and cfg["target_is_working_copy"] is False
    cfg.update(target_sha="a", reference_sha="b")
    seen = []

    def fake(spec):
        seen.append((Path(spec["src"]).name, spec["fraction"], spec["half"]))
        Path(spec["out"]).write_bytes(b"x")
        return {"n_source": 1, "n_after_fraction": 1, "n_written": 1}

    monkeypatch.setattr(rs, "run_worker", fake)
    rs.ensure_working("T1:val", cfg, 0, tmp_path / "work")
    assert ("r.h5ad", 1.0, False) in seen and ("t.h5ad", cfg["fraction"], True) in seen


def test_load_boards_rejects_bad_setting(tmp_path):
    b = tmp_path / "boards.json"
    b.write_text(json.dumps({"T2:liver:val": {"target": "a", "reference": "b"}}), encoding="utf-8")
    with pytest.raises(ValueError):
        rs.load_boards(b)


# ---------------------------------------------------------------- finding files

def test_resolve_missing_identical_and_ambiguous(tmp_path):
    a = tmp_path / "a" / "dup_same.h5ad"
    b = tmp_path / "b" / "dup_same.h5ad"
    c = tmp_path / "a" / "clash.h5ad"
    d = tmp_path / "b" / "clash.h5ad"
    for p in (a, b):
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(b"same bytes")
    c.write_bytes(b"old version")
    d.write_bytes(b"new version")
    import os
    os.utime(c, (1_000_000_000, 1_000_000_000))  # make c the older file
    res = rs.resolve_files(["nope.h5ad", "dup_same.h5ad", "clash.h5ad"],
                           [tmp_path / "a", tmp_path / "b"], [])
    assert res["nope.h5ad"].status == "missing" and res["nope.h5ad"].path is None
    assert res["dup_same.h5ad"].status == "found_identical_copies"
    assert res["clash.h5ad"].status == "ambiguous_newest"
    assert res["clash.h5ad"].path == d.resolve() or res["clash.h5ad"].path == d
    assert "newest used" in res["clash.h5ad"].note


def test_prefer_dir_resolves_ambiguity(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "x.h5ad").write_bytes(b"one")
    (tmp_path / "b" / "x.h5ad").write_bytes(b"two")
    res = rs.resolve_files(["x.h5ad"], [tmp_path / "a", tmp_path / "b"], [tmp_path / "a"])["x.h5ad"]
    assert res.status == "found" and res.path.parent.name == "a"


# ---------------------------------------------------------------- pipeline with a mocked scorer

def _write_fixture(tmp_path, n_rows=3):
    search = tmp_path / "team"
    search.mkdir()
    for name in ("p1.h5ad", "p2.h5ad"):
        (search / name).write_bytes(name.encode() * 10)
    # boards.json points at tiny files that exist; the scorer is mocked, so their content is irrelevant.
    (tmp_path / "t.h5ad").write_bytes(b"target")
    (tmp_path / "r.h5ad").write_bytes(b"reference")
    boards = tmp_path / "boards.json"
    boards.write_text(json.dumps({
        "T1:val": {"target": "t.h5ad", "reference": "r.h5ad"},
    }), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(json.dumps(index_from_metric_lens()), encoding="utf-8")
    subs = tmp_path / "submissions.csv"
    lines = ["submitted,task,file,board,board_score",
             "2026-10-01,T1,p1.h5ad,T1:val,40.0",
             "2026-10-02,T1,p2.h5ad,T1:val,55.0",
             "2026-10-03,T1,gone.h5ad,T1:val,10.0"]
    if n_rows > 3:
        lines.append("2026-10-04,T1,p1.h5ad,,40.0")
    subs.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return subs, search, boards, index


def _fake_worker(calls):
    def fake(spec):
        calls.append(spec)
        if spec["op"] != "score":
            raise AssertionError("only score jobs expected in full protocol")
        seed = spec["seed"]
        # deterministic metrics that depend on the file name and seed
        name_len = len(Path(spec["input"]).name)
        metrics = {"de_score": 0.5 + 0.01 * name_len, "de_direction": 0.6 + seed * 0.001,
                   "mmd_u": 0.02, "variogram": 0.001}
        return {"metrics": metrics, "meta": {"prediction_cells": 150}, "peak_rss_mb": 1.0}
    return fake


def test_pipeline_resumes_from_cache_and_reports(tmp_path, monkeypatch):
    subs, search, boards, index = _write_fixture(tmp_path, n_rows=4)
    out = tmp_path / "results"
    calls = []
    monkeypatch.setattr(rs, "run_worker", _fake_worker(calls))
    monkeypatch.setattr(rs, "scorer_signature", lambda: "test-scorer-sig")
    argv = ["--submissions", str(subs), "--search", str(search), "--boards", str(boards),
            "--index", str(index), "--protocol", "full", "--seeds", "2", "--out", str(out)]
    assert rs.main(argv) == 0
    first_calls = len(calls)
    assert first_calls == 2 * 2  # two found files, two seeds each; the missing and blank rows are not scored

    cache_lines = (out / "scores.jsonl").read_text().splitlines()
    assert len(cache_lines) == 4

    # a second run with the same inputs does no scoring
    calls.clear()
    assert rs.main(argv) == 0
    assert calls == []

    rows = list(csv.DictReader((out / "rescore.csv").open()))
    statuses = {r["file"] + "|" + r["board"]: r["status"] for r in rows}
    assert statuses["gone.h5ad|T1:val"] == "missing_file"
    assert statuses["p1.h5ad|"] == "no_board"
    assert statuses["p1.h5ad|T1:val"] == "scored"
    report = (out / "RESCORE.md").read_text()
    assert "## T1:val" in report
    assert "Spearman rho" in report
    assert "n/a" in report  # the de_score values are identical for p1 and p2, so their rho is undefined
    assert "gone.h5ad" in report


def test_scoring_error_is_reported_and_not_cached(tmp_path, monkeypatch):
    subs, search, boards, index = _write_fixture(tmp_path)
    out = tmp_path / "results"

    def failing(spec):
        raise rs.WorkerError("gene panel mismatch")

    monkeypatch.setattr(rs, "run_worker", failing)
    monkeypatch.setattr(rs, "scorer_signature", lambda: "test-scorer-sig")
    rc = rs.main(["--submissions", str(subs), "--search", str(search), "--boards", str(boards),
                  "--index", str(index), "--protocol", "full", "--seeds", "1", "--out", str(out)])
    assert rc == 0
    rows = list(csv.DictReader((out / "rescore.csv").open()))
    assert {r["status"] for r in rows if r["file"] == "p1.h5ad" and r["board"]} == {"scoring_error"}
    assert not (out / "scores.jsonl").exists() or (out / "scores.jsonl").read_text() == ""


def test_board_protocol_uses_working_copies(tmp_path, monkeypatch):
    """Board protocol builds a 10% reference and a half-A target per seed, then scores against them."""
    subs, search, boards, index = _write_fixture(tmp_path)
    out = tmp_path / "results"
    seen = []

    def fake(spec):
        if spec["op"] == "subsample":
            # stand in for the real subsample: write the file so the next step can see it exists
            Path(spec["out"]).write_bytes(b"working " + spec["op"].encode())
            res = {"n_source": 10, "n_after_fraction": 1, "n_written": 1}
            Path(spec["result_path"]).write_text(json.dumps(res))
            return res
        seen.append(spec)
        return _fake_worker([])(spec)

    monkeypatch.setattr(rs, "run_worker", fake)
    monkeypatch.setattr(rs, "scorer_signature", lambda: "test-scorer-sig")
    rc = rs.main(["--submissions", str(subs), "--search", str(search), "--boards", str(boards),
                  "--index", str(index), "--protocol", "board", "--seeds", "2", "--out", str(out)])
    assert rc == 0
    assert len(seen) == 4
    for spec in seen:
        assert Path(spec["target"]).name == "target_halfA.h5ad"
        assert Path(spec["reference"]).name == "reference_working.h5ad"


def test_subsample_is_seeded_and_half_splits(tmp_path):
    anndata = pytest.importorskip("anndata")
    import numpy as np
    from scipy import sparse

    X = sparse.csr_matrix(np.arange(200, dtype=np.float32).reshape(50, 4))
    a = anndata.AnnData(X=X)
    a.obs["celltype"] = [f"c{i % 3}" for i in range(50)]
    src = tmp_path / "src.h5ad"
    a.write_h5ad(src)
    d1, d2, d3 = tmp_path / "w1.h5ad", tmp_path / "w2.h5ad", tmp_path / "w3.h5ad"
    i1 = rs.subsample_h5ad(src, d1, fraction=0.2, seed=0, stream=0, half=False)
    assert i1["n_after_fraction"] == 10 and i1["n_written"] == 10
    rs.subsample_h5ad(src, d2, fraction=0.2, seed=0, stream=0, half=False)
    rs.subsample_h5ad(src, d3, fraction=0.2, seed=1, stream=0, half=False)
    x1 = anndata.read_h5ad(d1)
    x2 = anndata.read_h5ad(d2)
    x3 = anndata.read_h5ad(d3)
    assert list(x1.obs_names) == list(x2.obs_names)            # same seed, same cells
    assert list(x1.obs_names) != list(x3.obs_names)            # different seed, different cells
    assert x1.var_names.tolist() == a.var_names.tolist()
    assert "celltype" in x1.obs.columns
    half = tmp_path / "half.h5ad"
    ih = rs.subsample_h5ad(src, half, fraction=0.2, seed=0, stream=0, half=True)
    assert ih["n_written"] == 5
    assert set(anndata.read_h5ad(half).obs_names) <= set(x1.obs_names)


# ---------------------------------------------------------------- validator and export JS

def test_validator_adds_comparisons(tmp_path, monkeypatch):
    subs, search, boards, index = _write_fixture(tmp_path)
    out = tmp_path / "results"
    v = tmp_path / "validator.csv"
    v.write_text("file,board,value\np1.h5ad,T1:val,0.3\np2.h5ad,T1:val,0.9\n", encoding="utf-8")
    monkeypatch.setattr(rs, "run_worker", _fake_worker([]))
    monkeypatch.setattr(rs, "scorer_signature", lambda: "test-scorer-sig")
    rs.main(["--submissions", str(subs), "--search", str(search), "--boards", str(boards),
             "--index", str(index), "--protocol", "full", "--seeds", "1", "--out", str(out),
             "--local-validator", str(v)])
    assert "Local validator column" in (out / "RESCORE.md").read_text()


def _node_available():
    return NODE is not None


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_export_js_guess_matches_python():
    cases = [
        ("T1", "anything.h5ad"), ("T2 · embryo", "e75.h5ad"),
        ("T2 · heart", "pred_E8.5_interp.h5ad"), ("T2 · heart", "pred_interp_v2.h5ad"),
        ("T2 · heart", "pred_E10.5_extrap.h5ad"), ("T2 · heart", "pred_plain.h5ad"),
        ("T2 · heart", "E8.5_and_E10.5.h5ad"), ("T3", "gata4.h5ad"), ("T9", "x.h5ad"), ("", "x.h5ad"),
        ("T1 ", "x.h5ad"), ("t2 heart", "E10.5.h5ad"),
    ]
    js = (
        "const api = require(process.argv[1]);"
        "const cases = JSON.parse(process.argv[2]);"
        "console.log(JSON.stringify(cases.map(([t, f]) => api.guessBoard(t, f))));"
    )
    proc = subprocess.run([NODE, "-e", js, str(HERE / "export_submissions.js"), json.dumps(cases)],
                          capture_output=True, text=True, check=True)
    js_out = json.loads(proc.stdout)
    py_out = [rs.guess_board(t, f) for t, f in cases]
    assert js_out == py_out


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_export_js_parses_table_and_writes_csv():
    """Fake DOM objects with the same querySelectorAll/textContent surface the script uses."""
    spec = {"kids": {
        "thead th": [{"text": h} for h in ["Submitted", "Task", "File", "Status", "Score"]],
        "tbody tr": [{"kids": {"td": [{"text": v} for v in vals]}} for vals in [
            ["2026-10-01", "T2 · heart", "pred_E8.5.h5ad", "Scored", "61.5"],
            ["2026-10-02", "T1", "pred, two.h5ad", "Scored\nsome detail", "40.2"],
            ["2026-10-03", "T1", "pending.h5ad", "Pending", ""],
            ["2026-10-04", "T3", "bad.h5ad", "Scored", "n/a"],
            ["2026-10-05", "T2 · heart", "pred_plain.h5ad", "Scored", "33"],
        ]]}}
    js = (
        "const api = require(process.argv[1]);"
        "const t = JSON.parse(process.argv[2]);"
        "function build(spec) {"
        "  const el = { textContent: spec.text || '' };"
        "  el.querySelectorAll = (sel) => ((spec.kids && spec.kids[sel]) || []).map(build);"
        "  return el;"
        "}"
        "const r = api.parseRows(build(t));"
        "console.log(JSON.stringify({rows: r.rows, skipped: r.skipped, csv: api.toCsv(r.rows)}));"
    )
    proc = subprocess.run([NODE, "-e", js, str(HERE / "export_submissions.js"), json.dumps(spec)],
                          capture_output=True, text=True, check=True)
    got = json.loads(proc.stdout)
    assert [r["file"] for r in got["rows"]] == ["pred_E8.5.h5ad", "pred, two.h5ad", "pred_plain.h5ad"]
    assert got["rows"][0]["board"] == "T2:heart:val_interp"
    assert got["rows"][1]["board"] == "T1:val"
    assert got["rows"][1]["board_score"] == "40.2"
    assert got["rows"][2]["board"] == ""                      # blank: check by hand
    assert got["skipped"] == {"unscored": 1, "noScore": 1}
    assert got["csv"].splitlines()[0] == "submitted,task,file,board,board_score"
    assert '"pred, two.h5ad"' in got["csv"]
