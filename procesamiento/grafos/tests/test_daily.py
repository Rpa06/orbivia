"""Cierre del día: matriz, máscara de no evaluables y casos de datos."""

import numpy as np
import pytest

from conftest import H, apart, run_day, standard_schedule, together
from social_graph.daily import INTERACTION, NO_DATA, NOT_EVALUABLE, OK, ZERO
from social_graph.params import Params
from social_graph.schedule import FixedSchedule
from social_graph.weights import WEIGHT_FUNCTIONS, get_weight_fn

A, B, C = 0, 1, 2


def contact(crew, group, start, end):
    base = apart(crew)
    return lambda t: together(base, group) if start <= t < end else base


def assert_valid_matrix(result):
    w = result.weights
    assert w.shape == (len(result.crew),) * 2
    assert np.array_equal(w, w.T)
    assert np.all(np.diag(w) == 0)
    assert np.all((w >= 0) & (w <= 1))
    assert np.array_equal(result.evaluable, result.evaluable.T)
    assert not result.evaluable.diagonal().any()
    assert np.all(w[~result.evaluable] == 0)
    assert result.bound_violations == 0


def test_matrix_is_symmetric_zero_diagonal_and_bounded(crew):
    result = run_day(crew, standard_schedule(crew), contact(crew, ["A", "B"], 17 * H, 18 * H))
    assert_valid_matrix(result)
    assert result.status[A, B] == INTERACTION
    assert result.status[A, C] == ZERO
    assert result.weights[A, C] == 0 and result.evaluable[A, C]
    # 1 h de 8 h de ocio simultáneo
    assert result.r_overlap[A, B] == pytest.approx(1 / 8, abs=1e-3)
    assert result.weights[A, B] == pytest.approx(get_weight_fn("exp", 0.3)(1 / 8), abs=2e-3)
    assert result.node_status == [OK, OK, OK]


def test_reference_example_end_to_end():
    # A: ocio 16–20 (4 h). B: ocio 14–22 (8 h). Juntos 1 h.
    crew = ["A", "B"]
    schedule = FixedSchedule(
        {
            "A": {"sleep": [(22 * H, 6 * H)], "work": [(6 * H, 16 * H), (20 * H, 22 * H)]},
            "B": {"sleep": [(22 * H, 6 * H)], "work": [(6 * H, 14 * H)]},
        }
    )
    params = Params(normalization="leisure")
    result = run_day(crew, schedule, contact(crew, crew, 17 * H, 18 * H), params)
    assert result.leisure_s.tolist() == pytest.approx([4 * H, 8 * H])
    assert result.interaction_s[A, B] == pytest.approx(3600.0)
    assert result.r_leisure[A, B] == pytest.approx(0.1875)
    assert result.r_overlap[A, B] == pytest.approx(0.25, abs=1e-3)
    assert result.alignment[A, B] == pytest.approx(0.75)
    assert result.weights[A, B] == pytest.approx(get_weight_fn("exp", 0.3)(0.1875))
    assert_valid_matrix(result)


def test_always_together_gives_r_one(crew):
    result = run_day(crew, standard_schedule(crew), lambda t: together(apart(crew), crew))
    assert_valid_matrix(result)
    assert result.r_overlap[A, B] == pytest.approx(1.0)
    assert result.weights[A, B] == pytest.approx(1.0)
    assert result.strength.tolist() == pytest.approx([2.0, 2.0, 2.0])
    assert result.strength_norm.tolist() == pytest.approx([1.0, 1.0, 1.0])
    assert result.accompanied[A] == pytest.approx(1.0, abs=0.01)


def test_sensor_gap_does_not_lower_r(crew):
    # Siempre juntos, pero A pierde el sensor 2 h de su ocio
    def positions(t):
        p = together(apart(crew), crew)
        if 17 * H <= t < 19 * H:
            p["A"] = None
        return p

    result = run_day(crew, standard_schedule(crew), positions)
    assert_valid_matrix(result)
    assert result.coverage[A, B] == pytest.approx(0.75, abs=0.01)
    assert result.r_overlap[A, B] == pytest.approx(1.0, abs=0.01)
    assert result.status[A, B] == INTERACTION
    assert result.coverage[B, C] == pytest.approx(1.0, abs=0.01)


def test_missing_data_is_not_isolation(crew):
    # B no tiene sensor en todo el día
    def positions(t):
        p = together(apart(crew), ["A", "C"]) if 17 * H <= t < 18 * H else apart(crew)
        p["B"] = None
        return p

    result = run_day(crew, standard_schedule(crew), positions)
    assert_valid_matrix(result)
    assert result.status[A, B] == NO_DATA and result.status[B, C] == NO_DATA
    assert result.status[A, C] == INTERACTION
    assert result.node_status[B] == NO_DATA
    assert np.isnan(result.strength_norm[B])
    assert np.isnan(result.accompanied[B])
    # A y C se evalúan solo con la pareja que tiene datos: sin dividir por N − 1
    assert result.strength_norm[A] == pytest.approx(result.weights[A, C])


def test_low_coverage_pair_is_not_evaluable(crew):
    # A solo tiene sensor 1 h de las 8 h de ocio
    def positions(t):
        p = apart(crew)
        if not 17 * H <= t < 18 * H:
            p["A"] = None
        return p

    result = run_day(crew, standard_schedule(crew), positions)
    assert result.status[A, B] == NOT_EVALUABLE
    assert result.node_status[A] == NOT_EVALUABLE
    assert result.status[B, C] == ZERO


def test_astronaut_without_leisure_is_not_evaluable():
    crew = ["A", "B", "C"]
    blocks = {a: {"sleep": [(22 * H, 6 * H)], "work": [(8 * H, 16 * H)]} for a in crew}
    blocks["C"] = {"sleep": [(22 * H, 6 * H)], "work": [(6 * H, 22 * H)]}  # 0 h de ocio
    result = run_day(crew, FixedSchedule(blocks), contact(crew, crew, 17 * H, 18 * H))
    assert_valid_matrix(result)
    assert result.leisure_s[C] == 0
    assert result.status[A, C] == NOT_EVALUABLE and result.status[B, C] == NOT_EVALUABLE
    assert result.node_status[C] == NOT_EVALUABLE
    assert result.status[A, B] == INTERACTION


def test_disjoint_leisure_depends_on_normalization():
    crew = ["A", "B"]
    schedule = FixedSchedule(
        {
            "A": {"sleep": [(22 * H, 6 * H)], "work": [(6 * H, 16 * H)]},  # ocio 16–22
            "B": {"sleep": [(14 * H, 22 * H)], "work": [(22 * H, 6 * H)]},  # ocio 06–14
        }
    )
    positions = lambda t: together(apart(crew), crew)
    by_overlap = run_day(crew, schedule, positions, Params(normalization="overlap"))
    by_leisure = run_day(crew, schedule, positions, Params(normalization="leisure"))
    # Sin ocio común: por solape no se puede decir nada; por ocio es un cero legítimo
    assert by_overlap.status[A, B] == NOT_EVALUABLE
    assert by_leisure.status[A, B] == ZERO
    assert by_overlap.alignment[A, B] == 0


@pytest.mark.parametrize("name", WEIGHT_FUNCTIONS)
def test_weight_function_is_swappable(crew, name):
    params = Params(weight_fn=name)
    result = run_day(crew, standard_schedule(crew), contact(crew, ["A", "B"], 17 * H, 19 * H), params)
    assert_valid_matrix(result)
    assert result.weights[A, B] == pytest.approx(get_weight_fn(name, 0.3)(0.25), abs=3e-3)


def test_no_samples_at_all(crew):
    result = run_day(crew, standard_schedule(crew), lambda t: {a: None for a in crew})
    assert_valid_matrix(result)
    assert all(s == NO_DATA for s in result.node_status)
    assert result.status[A, B] == NO_DATA
    assert not result.evaluable.any()
