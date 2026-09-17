import math
from vec_metric_lens import BOARDS, metric_skill, board_score


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
