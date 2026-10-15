import numpy as np
import pytest

import analyse as A
import vec_metric_lens as vml
from stages import split_half


T2 = "T2:heart:val_extrap"


def test_t2_heart_weights_sum_to_one():
    total = sum(m["weight"] for m in vml.BOARDS[T2]["metrics"].values())
    assert total == pytest.approx(1.0)


def _anchors_for(direction):
    """Floor and ceiling of a valid local anchor pair for a metric direction."""
    if direction == "higher":
        return 0.05, 0.9
    if direction == "lower":
        return 0.5, 0.1
    return -0.5, -0.01  # abs_lower


def test_copy_last_gets_headline_fifty_when_floors_are_its_own_values():
    total = 0.0
    for name, spec in vml.BOARDS[T2]["metrics"].items():
        floor, ceiling = _anchors_for(spec["direction"])
        local = A.anchored_metric(name, T2, floor, ceiling)
        total += 100 * spec["weight"] * vml.metric_skill(floor, local)
    assert total == pytest.approx(50.0)


def test_value_at_ceiling_gets_full_headline():
    total = 0.0
    for name, spec in vml.BOARDS[T2]["metrics"].items():
        floor, ceiling = _anchors_for(spec["direction"])
        local = A.anchored_metric(name, T2, floor, ceiling)
        total += 100 * spec["weight"] * vml.metric_skill(ceiling, local)
    assert total == pytest.approx(100.0)


def test_inverted_anchor_is_rejected():
    with pytest.raises(ValueError):
        A.anchored_metric("mmd_u", T2, floor=0.01, ceiling=0.05)  # lower is better, so this ceiling is worse


def test_split_half_is_disjoint_and_complete():
    a, b = split_half(101, seed=4)
    assert len(a) == 50 and len(b) == 51
    assert set(a).isdisjoint(b)
    assert set(a) | set(b) == set(range(101))
    a2, _ = split_half(101, seed=4)
    assert np.array_equal(a, a2)


def test_rank_correlation_known_cases():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert A.rank_corr(x, x * 10)[0] == pytest.approx(1.0)
    assert A.rank_corr(x, -x)[0] == pytest.approx(-1.0)
    assert np.isnan(A.rank_corr(x, np.ones(4))[0])


def test_r1_takes_two_highest_validation_values():
    hv = np.array([10.0, 30.0, 20.0, 5.0])
    picks = A.pick_two("R1", hv, np.zeros(4), ["a"] * 4, np.zeros((4, 4)))
    assert picks == [1, 2]


def test_ties_are_broken_by_the_random_key():
    hv = np.array([50.0, 50.0, 50.0])
    picks = A.pick_two("R1", hv, np.array([0.9, 0.1, 0.5]), ["a"] * 3, np.zeros((3, 3)))
    assert picks == [1, 2]


def test_r2_takes_best_from_a_different_family():
    hv = np.array([30.0, 25.0, 20.0])
    fams = ["drift", "drift", "composition"]
    picks = A.pick_two("R2", hv, np.zeros(3), fams, np.zeros((3, 3)))
    assert picks == [0, 2]


def test_r3_takes_most_dissimilar_of_top_five():
    hv = np.array([60.0, 50.0, 49.0, 48.0, 47.0, 10.0])
    dissim = np.zeros((6, 6))
    dissim[0, 3] = dissim[3, 0] = 2.0
    dissim[0, 4] = dissim[4, 0] = 9.0  # most dissimilar within the top five
    dissim[0, 5] = dissim[5, 0] = 99.0  # outside the top five, so never chosen
    picks = A.pick_two("R3", hv, np.zeros(6), ["a"] * 6, dissim)
    assert picks == [0, 4]


def test_full_set_regret_is_zero_when_validation_and_test_agree():
    rng = np.random.default_rng(0)
    H = rng.random((8, 3)) * 100
    names = [f"c{i}" for i in range(8)]
    fams = ["a"] * 8
    res = A.rule_draws(H, H, names, fams, np.zeros((8, 8)), "R1", draws=30, rng=rng, perturb=False)
    assert res["mean"] == pytest.approx(0.0)
    assert res["share_zero"] == pytest.approx(1.0)


def test_regret_known_value():
    Hv = np.array([[10.0], [20.0], [30.0]])
    Ht = np.array([[90.0], [40.0], [60.0]])
    rng = np.random.default_rng(0)
    res = A.rule_draws(Hv, Ht, ["x", "y", "z"], ["a", "b", "c"], np.zeros((3, 3)), "R1", draws=5,
                       rng=rng, perturb=False)
    # R1 picks z (val 30) and y (val 20). Best test is x (90), so regret = 90 - 60 = 30.
    assert res["mean"] == pytest.approx(30.0)
