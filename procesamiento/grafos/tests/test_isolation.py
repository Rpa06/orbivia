"""IsolationAnalyzer sobre resultados diarios construidos a mano."""

import numpy as np
import pytest

from social_graph.isolation import (
    FOLLOW_UP,
    LOW_VS_CREW,
    NO_DATA,
    NORMAL,
    NOT_EVALUABLE,
    REVIEW,
    STRUCTURAL,
    WARMING_UP,
    IsolationAnalyzer,
    IsolationConfig,
    day_indicators,
    smoothed_weights,
)

CREW = ["A", "B", "C", "D"]


def make_doc(day, weights, accompanied=None, node_status=None, evaluable=None):
    w = np.array(weights, dtype=float)
    n = len(w)
    ev = np.array(evaluable, dtype=bool) if evaluable is not None else ~np.eye(n, dtype=bool)
    w = np.where(ev, w, 0.0)
    counts = ev.sum(axis=1)
    strength_norm = [w[i].sum() / counts[i] if counts[i] else None for i in range(n)]
    return {
        "day": day,
        "crew": CREW[:n],
        "weights": w.tolist(),
        "evaluable": ev.tolist(),
        "strength_norm": strength_norm,
        "accompanied": list(accompanied) if accompanied is not None else [0.5] * n,
        "node_status": list(node_status) if node_status is not None else ["ok"] * n,
    }


def uniform(value, n=4):
    w = np.full((n, n), value)
    np.fill_diagonal(w, 0)
    return w


def noisy_history(days, rng, base=0.5):
    docs = []
    for day in range(days):
        noise = rng.normal(0, 0.03, (4, 4))
        w = np.clip(uniform(base) + (noise + noise.T) / 2, 0, 1)
        np.fill_diagonal(w, 0)
        docs.append(make_doc(day, w, accompanied=np.clip(0.5 + rng.normal(0, 0.03, 4), 0, 1)))
    return docs


def last_status(docs, astronaut="A", config=None):
    return IsolationAnalyzer(config).analyze(docs)[-1]["astronauts"][astronaut]


def test_indicators_of_a_uniform_day():
    values = day_indicators(make_doc(0, uniform(0.4)), edge_min_w=0.1)["A"]
    assert values["intensity"] == pytest.approx(0.4)
    assert values["degree"] == 1.0
    assert values["diversity"] == pytest.approx(1.0)  # reparte por igual entre los 3


def test_diversity_drops_when_time_concentrates_on_one_partner():
    w = np.zeros((4, 4))
    w[0, 1] = w[1, 0] = 0.9
    w[0, 2] = w[2, 0] = 0.01
    values = day_indicators(make_doc(0, w), edge_min_w=0.1)
    assert values["A"]["diversity"] < 0.4
    assert values["A"]["degree"] == pytest.approx(1 / 3)
    assert values["D"]["diversity"] is None  # sin interacciones: no definida, no cero


def test_missing_partners_are_excluded_not_counted_as_zero():
    ev = ~np.eye(4, dtype=bool)
    ev[0, 3] = ev[3, 0] = False
    values = day_indicators(make_doc(0, uniform(0.4), evaluable=ev), edge_min_w=0.1)["A"]
    assert values["intensity"] == pytest.approx(0.4)
    assert values["degree"] == 1.0


def test_smoothed_weights_average_only_evaluable_days():
    ev = ~np.eye(4, dtype=bool)
    ev[0, 1] = ev[1, 0] = False
    docs = [make_doc(0, uniform(0.2)), make_doc(1, uniform(0.6)), make_doc(2, uniform(0.9), evaluable=ev)]
    smoothed = smoothed_weights(docs)
    assert smoothed[0][1] == pytest.approx(0.4)
    assert smoothed[0][2] == pytest.approx((0.2 + 0.6 + 0.9) / 3)
    assert smoothed[0][0] is None


def test_warming_up_until_baseline_exists():
    docs = noisy_history(20, np.random.default_rng(0))
    result = IsolationAnalyzer().analyze(docs)
    statuses = [r["astronauts"]["A"]["status"] for r in result]
    # 7 días de calentamiento + 5 de retraso
    assert statuses[:12] == [WARMING_UP] * 12
    assert statuses[12:] == [NORMAL] * 8
    assert result[5]["astronauts"]["A"]["score"] is None
    assert result[-1]["astronauts"]["A"]["score"] is not None


def test_sustained_individual_drop_is_flagged_and_then_reviewed():
    rng = np.random.default_rng(1)
    docs = noisy_history(20, rng)
    for day in range(20, 30):
        w = uniform(0.5)
        w[0, :] = w[:, 0] = 0.12  # A cae con todos; sigue por encima del umbral de arista
        np.fill_diagonal(w, 0)
        docs.append(make_doc(day, w, accompanied=[0.1, 0.5, 0.5, 0.5]))
    result = IsolationAnalyzer().analyze(docs)
    statuses = [r["astronauts"]["A"]["status"] for r in result]
    assert statuses[19] == NORMAL
    assert statuses[22] in (FOLLOW_UP, REVIEW)  # 3 de 5 días
    assert statuses[-1] == REVIEW  # descenso propio + bajo frente a la tripulación
    assert all(r["astronauts"]["B"]["status"] == NORMAL for r in result[12:])
    assert result[-1]["astronauts"]["A"]["indicators"]["intensity"]["z"] < -2.5


def test_single_bad_day_is_not_flagged():
    docs = noisy_history(20, np.random.default_rng(2))
    w = uniform(0.5)
    w[0, :] = w[:, 0] = 0.1
    np.fill_diagonal(w, 0)
    docs.append(make_doc(20, w, accompanied=[0.1, 0.5, 0.5, 0.5]))
    assert last_status(docs)["status"] == NORMAL


def test_no_data_days_are_never_isolation():
    docs = noisy_history(20, np.random.default_rng(3))
    for day in range(20, 30):
        ev = ~np.eye(4, dtype=bool)
        ev[0, :] = ev[:, 0] = False
        docs.append(make_doc(day, uniform(0.5), node_status=["no_data", "ok", "ok", "ok"], evaluable=ev))
    result = IsolationAnalyzer().analyze(docs)
    assert all(r["astronauts"]["A"]["status"] == NO_DATA for r in result[20:])
    assert all(r["astronauts"]["A"]["signals"] == [] for r in result[20:])
    # Al volver los datos con su conducta habitual, sigue normal
    docs.append(make_doc(30, uniform(0.5)))
    assert last_status(docs)["status"] == NORMAL


def test_not_evaluable_is_reported_as_such():
    doc = make_doc(0, uniform(0.5), node_status=["not_evaluable", "ok", "ok", "ok"])
    assert last_status([doc])["status"] == NOT_EVALUABLE


def test_low_versus_crew_needs_no_baseline():
    docs = [make_doc(day, uniform(0.5), accompanied=[0.1, 0.5, 0.6, 0.5]) for day in range(5)]
    status = last_status(docs)
    assert status["status"] == FOLLOW_UP
    assert status["signals"] == [LOW_VS_CREW]
    assert last_status(docs[:4])["status"] == WARMING_UP  # 4 días: aún no es persistente


def test_structural_isolation_goes_to_review():
    w = uniform(0.5)
    w[0, :] = w[:, 0] = 0.02
    docs = [make_doc(day, w) for day in range(3)]
    status = last_status(docs)
    assert STRUCTURAL in status["signals"]
    assert status["status"] == REVIEW
    assert last_status(docs, "B")["status"] == WARMING_UP


def test_crew_wide_drop_is_not_individual():
    rng = np.random.default_rng(4)
    docs = noisy_history(20, rng)
    for day in range(20, 30):
        docs.append(make_doc(day, uniform(0.15), accompanied=[0.15] * 4))
    result = IsolationAnalyzer().analyze(docs)
    assert result[-1]["crew"]["drop"] is True
    assert result[19]["crew"]["drop"] is False
    for astronaut in CREW:
        assert result[-1]["astronauts"][astronaut]["status"] == NORMAL


def test_thresholds_are_configurable():
    docs = [make_doc(day, uniform(0.5), accompanied=[0.1, 0.5, 0.6, 0.5]) for day in range(5)]
    strict = IsolationConfig(crew_ratio_min=0.1)
    assert last_status(docs, config=strict)["status"] == WARMING_UP
