"""Estado normalizado, adecuación, incertidumbre, repetición y carga."""

import itertools
import random

import pytest

from conftest import DAY, H, astronaut, task
from crew_planner.costs import (
    adequacy, capacity, deficit, effective_weights, equity_cost, individual_cost, monotony,
    repetition, target_shares, task_load,
)
from crew_planner.history import History, HistoryEntry
from crew_planner.model import Astronaut, Task
from crew_planner.state import KNOWN, MISSING, NO_BASELINE, STALE, astronaut_state, normalize_natural

REF = 10 * DAY


def m(parameter, value, age_h=1.0, confidence=None):
    raw = {"parameter": parameter, "value": value, "measured_at": REF - age_h * H, "source": "test"}
    if confidence is not None:
        raw["confidence"] = confidence
    return raw


def state_of(config, *measurements, baselines=None):
    a = Astronaut.from_dict(astronaut(measurements=list(measurements), baselines=baselines or []))
    return astronaut_state(a, config.parameters, REF)


# --- estado ----------------------------------------------------------------------


def test_known_missing_stale_and_no_baseline(config):
    s = state_of(config, m("sleep_duration_h", 7), m("spo2", 97, age_h=30), m("grip_strength", 40))
    assert s["sleep_duration_h"].status == KNOWN
    assert s["sleep_duration_h"].z == pytest.approx(7 / 12)
    assert s["spo2"].status == STALE and s["spo2"].z is None
    assert s["grip_strength"].status == NO_BASELINE
    assert s["fatigue_self"].status == MISSING


def test_baseline_z_normalization(config):
    s = state_of(config, m("pvt_lapses", 4), baselines=[{"parameter": "pvt_lapses", "mean": 2, "sd": 1}])
    assert s["pvt_lapses"].natural == pytest.approx(2.0)          # z = +2
    assert s["pvt_lapses"].z == pytest.approx((2 + 3) / 6)
    extreme = state_of(config, m("pvt_lapses", 50), baselines=[{"parameter": "pvt_lapses", "mean": 2, "sd": 1}])
    assert extreme["pvt_lapses"].z == 1.0                         # recortado a +3


def test_minmax_clips_to_physiological_range(config):
    spec = config.parameters["spo2"]
    assert normalize_natural(spec, 80) == 0.0
    assert normalize_natural(spec, 101) == 1.0


# --- adecuación --------------------------------------------------------------------


def test_deficit_is_one_sided():
    assert deficit(0.8, t_min=0.5, t_max=None) == 0.0    # mejor de lo pedido: sin coste
    assert deficit(0.3, t_min=0.5, t_max=None) == pytest.approx(0.2)
    assert deficit(0.9, t_min=None, t_max=0.6) == pytest.approx(0.3)
    assert deficit(0.5, t_min=0.4, t_max=0.6) == 0.0
    assert deficit(0.7, t_min=0.4, t_max=0.6) == pytest.approx(0.1)


def test_optimal_range_penalizes_both_sides(config):
    # Frecuencia cardíaca en reposo: más no es mejor
    t = Task.from_dict(task(requirements=[{"parameter": "resting_hr", "min": -1, "max": 1}]))
    base = [{"parameter": "resting_hr", "mean": 60, "sd": 5}]
    ok = adequacy(t, state_of(config, m("resting_hr", 62), baselines=base), config.parameters, config)
    high = adequacy(t, state_of(config, m("resting_hr", 75), baselines=base), config.parameters, config)
    low = adequacy(t, state_of(config, m("resting_hr", 45), baselines=base), config.parameters, config)
    assert ok.distance == 0.0
    assert high.distance > 0 and low.distance > 0
    assert high.distance == pytest.approx(low.distance)


def test_missing_data_never_improves_cost(config):
    """Propiedad central: quitar un dato nunca abarata la asignación."""
    t = Task.from_dict(task(importance=4, requirements=[
        {"parameter": "sleep_duration_h", "min": 6},
        {"parameter": "spo2", "min": 92},
        {"parameter": "fatigue_self", "max": 3},
    ]))
    rng = random.Random(1)
    for _ in range(200):
        values = [m("sleep_duration_h", rng.uniform(7, 12)), m("spo2", rng.uniform(95, 100)),
                  m("fatigue_self", rng.uniform(1, 2.5))]
        full = individual_cost(t, "A1", state_of(config, *values), History(), 10, config)
        for k in range(1, 4):
            for subset in itertools.combinations(values, 3 - k):
                partial = individual_cost(t, "A1", state_of(config, *subset), History(), 10, config)
                # Con datos sanos, cualquier hueco cuesta más
                assert partial.total > full.total - 1e-12


def test_uncertainty_uses_declared_confidence_only(config):
    t = Task.from_dict(task(requirements=[{"parameter": "spo2", "min": 92}]))
    no_conf = adequacy(t, state_of(config, m("spo2", 97)), config.parameters, config)
    conf = adequacy(t, state_of(config, m("spo2", 97, confidence=0.7)), config.parameters, config)
    missing = adequacy(t, state_of(config), config.parameters, config)
    assert no_conf.uncertainty == 0.0
    assert conf.uncertainty == pytest.approx(0.3)
    assert missing.uncertainty == 1.0 and missing.distance == 0.0
    assert missing.unknown == ["spo2"]


def test_domain_cap_limits_correlated_parameters(config):
    reqs = Task.from_dict(task(requirements=[
        {"parameter": "sleep_duration_h", "min": 6},
        {"parameter": "sleep_quality", "min": 70},
        {"parameter": "spo2", "min": 92},
    ])).requirements
    q = effective_weights(reqs, config.parameters, max_share=0.5)
    # Sueño tenía 2/3 del peso; se limita a la mitad del total original
    assert q["sleep_duration_h"] + q["sleep_quality"] == pytest.approx(1.5)
    assert q["spo2"] == 1.0


def test_bounds_of_cost_terms(config):
    t = Task.from_dict(task(importance=5, requirements=[{"parameter": "sleep_duration_h", "min": 12}]))
    worst = individual_cost(t, "A1", state_of(config, m("sleep_duration_h", 0)), History(), 10, config)
    assert worst.adequacy.distance == pytest.approx(1.0)
    assert worst.state == pytest.approx(config.weights.alpha_state)


# --- repetición --------------------------------------------------------------------


def entries(days, category="T1", astronaut="A1"):
    return [HistoryEntry(d, astronaut, category, category, 60) for d in days]


def test_repetition_bounds_and_recency(config):
    t = Task.from_dict(task())
    window = config.repetition.window_days
    assert repetition(History(), "A1", t, 20, config) == 0.0
    assert repetition(History(entries(range(20 - window, 20))), "A1", t, 20, config) == pytest.approx(1.0)
    recent = repetition(History(entries([19])), "A1", t, 20, config)
    old = repetition(History(entries([10])), "A1", t, 20, config)
    assert recent > old > 0
    assert repetition(History(entries([19], astronaut="A2")), "A1", t, 20, config) == 0.0
    assert repetition(History(entries([19], category="X")), "A1", t, 20, config) == 0.0
    assert repetition(History(entries([2])), "A1", t, 20, config) == 0.0  # fuera de la ventana


def test_critical_tasks_barely_penalize_repetition(config):
    assert monotony(Task.from_dict(task(importance=5)), config) == 0.0
    assert monotony(Task.from_dict(task(importance=1)), config) == pytest.approx(0.8)


# --- carga ---------------------------------------------------------------------------


def test_task_load_counts_time_and_intensity():
    assert task_load(Task.from_dict(task(duration_min=120, intensity=0))) == pytest.approx(1.0)
    assert task_load(Task.from_dict(task(duration_min=120, intensity=1))) == pytest.approx(2.0)


def test_capacity_is_conservative_without_fatigue_data(config):
    assert capacity(state_of(config), config.parameters, config) == config.workload.capacity_min
    rested = capacity(state_of(config, m("fatigue_self", 1), m("work_hours_3d", 0)), config.parameters, config)
    tired = capacity(state_of(config, m("fatigue_self", 5), m("work_hours_3d", 30)), config.parameters, config)
    assert rested == pytest.approx(1.0)
    assert config.workload.capacity_min <= tired < rested


def test_target_shares_and_equity(config):
    shares = target_shares({"A1": 8, "A2": 8}, {"A1": 1.0, "A2": 0.5})
    assert shares == pytest.approx({"A1": 2 / 3, "A2": 1 / 3})
    fair = equity_cost({"A1": 4, "A2": 2}, shares, config, reference_h=8)
    unfair = equity_cost({"A1": 2, "A2": 4}, shares, config, reference_h=8)
    assert fair == pytest.approx(0.0)
    assert unfair > fair
