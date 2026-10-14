import json
import math
import os
from pathlib import Path

import pytest

from vec_metric_lens import (
    BOARDS,
    anchored_board,
    board_score,
    check_anchors,
    counterfactuals,
    main,
    metric_skill,
    read_index,
)

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "example_t3.json"
REAL_INDEX = os.environ.get("VEC_PANELS_INDEX")


def _index_from_builtin():
    return {
        board: {"anchors": {m: {"floor": s["floor"], "ceiling": s["ceiling"]}
                            for m, s in bspec["metrics"].items()}}
        for board, bspec in BOARDS.items()
    }


def _write_index(tmp_path, index):
    path = tmp_path / "index.json"
    path.write_text(json.dumps(index))
    return path


def _assert_floor_ceiling_reconstruct(board, spec):
    floors = {k: v["floor"] for k, v in spec["metrics"].items()}
    ceilings = {k: v["ceiling"] for k, v in spec["metrics"].items()}
    assert math.isclose(board_score(floors, board, {board: spec})["score"], 50.0, abs_tol=1e-9), board
    assert math.isclose(board_score(ceilings, board, {board: spec})["score"], 100.0, abs_tol=1e-8), board


def test_floor_is_50_each_metric():
    for board, bspec in BOARDS.items():
        metrics = {k: v["floor"] for k, v in bspec["metrics"].items()}
        assert math.isclose(board_score(metrics, board)["score"], 50.0, abs_tol=1e-9), board


def test_ceiling_is_100_each_metric():
    for board, bspec in BOARDS.items():
        metrics = {k: v["ceiling"] for k, v in bspec["metrics"].items()}
        assert math.isclose(board_score(metrics, board)["score"], 100.0, abs_tol=1e-8), board


def test_beating_ceiling_clips():
    s = metric_skill(2.0, BOARDS["T1:val"]["metrics"]["de_score"])
    assert s == 1.0


def test_abs_metric_treats_sign_symmetrically():
    spec = BOARDS["T3:gata4"]["metrics"]["severity_slope"]
    assert math.isclose(metric_skill(0.5, spec), metric_skill(-0.5, spec))


def test_scale_log_ratio_treats_sign_symmetrically_on_both_embryo_and_heart():
    for board in ("T2:embryo:val_interp", "T2:heart:val_interp"):
        spec = BOARDS[board]["metrics"]["scale_log_ratio"]
        assert math.isclose(metric_skill(0.3, spec), metric_skill(-0.3, spec)), board


def test_skill_is_clipped_at_one_for_abs_and_lower_metrics():
    # Zero is better than any positive ceiling on these metrics, so skill is clipped to 1.
    assert metric_skill(0.0, BOARDS["T3:gata4"]["metrics"]["severity_slope"]) == 1.0
    assert metric_skill(0.0, BOARDS["T1:val"]["metrics"]["mmd_u"]) == 1.0


def test_nan_inf_none_and_bool_score_zero():
    spec = BOARDS["T1:val"]["metrics"]["de_score"]
    for raw in (float("nan"), float("inf"), None, True, "0.5"):
        assert metric_skill(raw, spec) == 0.0, raw


def test_builtin_anchors_are_ordered_correctly():
    for board, bspec in BOARDS.items():
        for name, spec in bspec["metrics"].items():
            check_anchors(spec, f"{board} {name}")


def test_index_anchors_reconstruct_50_and_100(tmp_path):
    index = read_index(str(_write_index(tmp_path, _index_from_builtin())))
    for board in BOARDS:
        _assert_floor_ceiling_reconstruct(board, anchored_board(index, board))


def test_index_replaces_anchors_but_keeps_weights_and_directions(tmp_path):
    index = _index_from_builtin()
    index["T3:gata4"]["anchors"]["de_score"]["ceiling"] = 0.5
    loaded = read_index(str(_write_index(tmp_path, index)))
    spec = anchored_board(loaded, "T3:gata4")["metrics"]["de_score"]
    assert spec["ceiling"] == 0.5
    assert spec["weight"] == BOARDS["T3:gata4"]["metrics"]["de_score"]["weight"]
    assert spec["direction"] == "higher"
    assert math.isclose(board_score({"de_score": 0.5}, "T3:gata4", {"T3:gata4": anchored_board(loaded, "T3:gata4")})["rows"][0]["points"], 30.0)


def test_index_missing_metric_anchor_is_error(tmp_path):
    index = _index_from_builtin()
    del index["T1:val"]["anchors"]["variogram"]
    loaded = read_index(str(_write_index(tmp_path, index)))
    with pytest.raises(ValueError, match="variogram"):
        anchored_board(loaded, "T1:val")


def test_index_board_without_weights_is_error(tmp_path):
    index = _index_from_builtin()
    index["T9:future_test"] = index["T1:val"]
    loaded = read_index(str(_write_index(tmp_path, index)))
    with pytest.raises(ValueError, match="no weights"):
        anchored_board(loaded, "T9:future_test")


def test_index_inverted_anchors_are_rejected(tmp_path):
    index = _index_from_builtin()
    index["T1:val"]["anchors"]["de_score"] = {"floor": 0.9, "ceiling": 0.5}
    loaded = read_index(str(_write_index(tmp_path, index)))
    with pytest.raises(ValueError, match="ceiling must be better"):
        anchored_board(loaded, "T1:val")


def test_index_non_finite_anchor_is_rejected(tmp_path):
    index = _index_from_builtin()
    index["T1:val"]["anchors"]["mmd_u"]["ceiling"] = None
    loaded = read_index(str(_write_index(tmp_path, index)))
    with pytest.raises(ValueError, match="finite"):
        anchored_board(loaded, "T1:val")


def test_counterfactual_gain_equals_points_left():
    metrics = json.loads(EXAMPLE.read_text())["metrics"]
    base = board_score(metrics, "T3:gata4")
    left = {r["metric"]: r["max_points"] - r["points"] for r in base["rows"]}
    for c in counterfactuals(metrics, "T3:gata4"):
        assert math.isclose(c["gain"], left[c["metric"]], abs_tol=1e-9), c["metric"]


def test_counterfactual_does_not_move_metric_back_from_beyond_ceiling():
    metrics = json.loads(EXAMPLE.read_text())["metrics"]
    metrics["de_score"] = 0.95  # above the T3 ceiling of 0.8696
    cf = {c["metric"]: c for c in counterfactuals(metrics, "T3:gata4")}
    assert cf["de_score"]["new_raw"] == 0.95
    assert cf["de_score"]["gain"] == pytest.approx(0.0)


def test_counterfactual_keeps_sign_for_abs_metric():
    metrics = json.loads(EXAMPLE.read_text())["metrics"]
    cf = {c["metric"]: c for c in counterfactuals(metrics, "T3:gata4")}
    assert cf["severity_slope"]["new_raw"] == pytest.approx(-0.0088)


def test_cli_index_end_to_end(tmp_path, capsys):
    index = _index_from_builtin()
    index["T3:gata4"]["anchors"]["mmd_u"]["ceiling"] = 0.0005
    path = _write_index(tmp_path, index)
    main([str(EXAMPLE), "--board", "T3:gata4", "--index", str(path)])
    out = capsys.readouterr().out
    assert "Reconstructed public validation score" in out
    assert str(path) in out


def test_cli_rejects_board_with_no_weights(tmp_path):
    index = _index_from_builtin()
    index["T9:future_test"] = index["T1:val"]
    path = _write_index(tmp_path, index)
    with pytest.raises(SystemExit):
        main([str(EXAMPLE), "--board", "T9:future_test", "--index", str(path)])


def test_cli_json_output_is_strict(tmp_path):
    metrics = json.loads(EXAMPLE.read_text())
    metrics["metrics"]["variogram"] = float("nan")
    inp = tmp_path / "nan.json"
    inp.write_text(json.dumps(metrics))  # json.dumps writes NaN as a bare token, which load_metrics accepts
    out = tmp_path / "analysis.json"
    main([str(inp), "--board", "T3:gata4", "--json", str(out)])
    text = out.read_text()
    assert "NaN" not in text
    json.loads(text, parse_constant=lambda c: pytest.fail(f"non-strict JSON constant {c}"))


@pytest.mark.skipif(not REAL_INDEX, reason="set VEC_PANELS_INDEX to a local copy of panels/index.json")
def test_real_index_matches_builtin_anchors():
    index = read_index(REAL_INDEX)
    for board, bspec in BOARDS.items():
        spec = anchored_board(index, board)
        for name, m in bspec["metrics"].items():
            assert spec["metrics"][name]["floor"] == m["floor"], (board, name)
            assert spec["metrics"][name]["ceiling"] == m["ceiling"], (board, name)
        _assert_floor_ceiling_reconstruct(board, spec)
