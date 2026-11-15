import numpy as np
import pytest

from social_graph.params import Params
from social_graph.validation import PositionSample, pair_distances, pair_key, parse_sample
from social_graph.weights import (
    WEIGHT_FUNCTIONS,
    alignment,
    get_weight_fn,
    r_leisure,
    r_overlap,
)

CREW = ["A", "B", "C"]


def test_parse_valid_sample():
    sample, issues = parse_sample({"t": 10, "positions": {"A": [0, 0, 0], "B": [3, 4, 0]}}, CREW)
    assert issues == []
    assert sample.t == 10.0
    assert sample.positions == {"A": (0.0, 0.0, 0.0), "B": (3.0, 4.0, 0.0), "C": None}


@pytest.mark.parametrize(
    "raw",
    [None, [], {"positions": {}}, {"t": "x", "positions": {}}, {"t": float("nan"), "positions": {}},
     {"t": 1}, {"t": True, "positions": {}}],
)
def test_parse_rejects_unusable_messages(raw):
    sample, issues = parse_sample(raw, CREW)
    assert sample is None and issues


def test_invalid_positions_become_missing_not_invented():
    raw = {"t": 1, "positions": {"A": [0, 0], "B": [0, "x", 0], "C": [0, float("inf"), 0], "Z": [0, 0, 0]}}
    sample, issues = parse_sample(raw, CREW)
    assert sample.positions == {"A": None, "B": None, "C": None}
    assert len(issues) == 4


def test_pair_distances_only_for_valid_pairs():
    sample = PositionSample(1.0, {"A": (0, 0, 0), "B": (3, 4, 0), "C": None})
    assert pair_distances(sample) == {("A", "B"): 5.0}
    assert pair_key("B", "A") == ("A", "B")


def test_reference_example_r_leisure():
    # A con 4 h de ocio, B con 8 h, 1 h compartida
    assert r_leisure(3600, 4 * 3600, 8 * 3600) == pytest.approx(0.1875)


def test_r_leisure_factorizes_into_overlap_and_alignment():
    i, ti, tj, o = 3600.0, 4 * 3600.0, 8 * 3600.0, 4 * 3600.0
    assert r_overlap(i, o) * alignment(o, ti, tj) == pytest.approx(r_leisure(i, ti, tj))


@pytest.mark.parametrize("i,ti,tj", [(0, 1, 1), (10, 10, 10), (5, 5, 500), (1, 7200, 30)])
def test_r_bounds(i, ti, tj):
    # I <= min(T_i, T_j) implica R en [0, 1]
    assert 0 <= r_leisure(i, ti, tj) <= 1
    assert 0 <= r_overlap(i, min(ti, tj)) <= 1


def test_undefined_r_is_nan_not_zero():
    assert np.isnan(r_overlap(0, 0))
    assert np.isnan(r_leisure(0, 0, 3600))


@pytest.mark.parametrize("name", WEIGHT_FUNCTIONS)
@pytest.mark.parametrize("kappa", [0.15, 0.3, 1.0])
def test_weight_functions_are_normalized_and_monotone(name, kappa):
    fn = get_weight_fn(name, kappa)
    r = np.linspace(0, 1, 201)
    w = fn(r)
    assert w[0] == pytest.approx(0)
    assert w[-1] == pytest.approx(1)
    assert np.all(np.diff(w) > 0)
    assert np.all((w >= 0) & (w <= 1 + 1e-12))


def test_exponential_matches_design_table():
    fn = get_weight_fn("exp", 0.3)
    assert fn(0.2) == pytest.approx(0.505, abs=1e-3)
    assert fn(0.1) == pytest.approx(0.294, abs=1e-3)


def test_unknown_weight_function():
    with pytest.raises(ValueError):
        get_weight_fn("cubica", 0.3)


@pytest.mark.parametrize(
    "kwargs",
    [{"d_in_m": 3, "d_out_m": 2}, {"kappa": 0}, {"normalization": "x"}, {"day_cutoff_s": 90000},
     {"max_gap_s": 0}, {"min_coverage": 2}],
)
def test_params_validation(kwargs):
    with pytest.raises(ValueError):
        Params(**kwargs)
