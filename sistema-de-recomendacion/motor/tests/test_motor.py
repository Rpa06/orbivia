import ast
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from colapso.vector import BY_NAME, N_FIELDS
from motor import actions, alerts, availability, planning

TODAY = date(2026, 11, 14)


def vec(**named) -> tuple[float, ...]:
    v = [math.nan] * N_FIELDS
    for name, value in named.items():
        v[BY_NAME[name].index] = value
    return tuple(v)


def history(days: int, **per_day) -> dict:
    """per_day[name] = función del índice de día (0 = el más antiguo)."""
    out = {}
    for k in range(days):
        d = TODAY - timedelta(days=days - 1 - k)
        out[d] = vec(**{n: f(k) for n, f in per_day.items()})
    return out


# --- alertas --------------------------------------------------------------------------


def test_c1_needs_three_consecutive_days():
    h = history(5, sleep_duration_z=lambda k: -2.5 if k >= 2 else 0.0)
    ev = alerts.evaluate(h, TODAY, mission_day=30, adaptation_days=10)
    assert [(a.criterion, a.area) for a in ev.alerts] == [("C1", "fatigue_sleep")]
    h2 = history(5, sleep_duration_z=lambda k: -2.5 if k >= 3 else 0.0)
    assert not [a for a in alerts.evaluate(h2, TODAY, 30, 10).alerts if a.criterion == "C1"]


def test_c1_suppressed_during_adaptation():
    h = history(5, sleep_duration_z=lambda k: -3.0)
    ev = alerts.evaluate(h, TODAY, mission_day=4, adaptation_days=10)
    assert not ev.alerts and ev.suppressed


def test_c2_progressive_deterioration_over_14_days():
    h = history(14, grip_strength_z=lambda k: -0.12 * k)  # nunca cruza -2σ
    ev = alerts.evaluate(h, TODAY, 40, 10)
    c2 = [a for a in ev.alerts if a.criterion == "C2"]
    assert c2 and c2[0].variables == ("grip_strength_z",) and c2[0].detail["window_days"] == 14
    assert not [a for a in ev.alerts if a.criterion == "C1"]


def test_c3_combined_signals_below_threshold():
    h = history(3, sleep_duration_z=lambda k: -1.4, checkin_mood_z=lambda k: -1.3,
                social_centrality_z=lambda k: -1.6)
    ev = alerts.evaluate(h, TODAY, 40, 10)
    c3 = [a for a in ev.alerts if a.criterion == "C3"]
    assert {a.area for a in c3} == {"fatigue_sleep", "psychological", "social_team"}


def test_c3_needs_three_days_and_two_areas():
    one_day = history(3, sleep_duration_z=lambda k: -1.5 if k == 2 else 0.0, checkin_mood_z=lambda k: -1.5 if k == 2 else 0.0,
                      social_centrality_z=lambda k: -1.5 if k == 2 else 0.0)
    assert not [a for a in alerts.evaluate(one_day, TODAY, 40, 10).alerts if a.criterion == "C3"]
    one_area = history(3, grip_strength_z=lambda k: -1.5, spo2_z=lambda k: -1.5, sleep_hrv_z=lambda k: -1.5)
    assert not [a for a in alerts.evaluate(one_area, TODAY, 40, 10).alerts if a.criterion == "C3"]


def test_noise_rarely_alerts():
    """Con ruido N(0,1) en los 20 campos, casi nunca hay avisos (sin tendencias reales)."""
    import random
    rng = random.Random(3)
    days = [TODAY - timedelta(days=29 - k) for k in range(30)]
    total = 0
    for trial in range(20):
        h = {d: tuple(rng.gauss(0, 1) for _ in range(N_FIELDS)) for d in days}
        total += len(alerts.evaluate(h, TODAY, 40, 10).alerts)
    assert total <= 6  # menos de un aviso cada tres tripulantes-día con ruido puro


def test_isolated_value_never_alerts():
    h = history(3, pvt_rt_z=lambda k: 4.0 if k == 2 else 0.0)
    assert alerts.evaluate(h, TODAY, 40, 10).alerts == []


def test_c4_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_HISTORICAL_VECTOR_MATCH", raising=False)
    ev = alerts.evaluate(history(1), TODAY, 40, 10)
    assert ev.c4 == {"enabled": False, "status": "disabled"}
    monkeypatch.setenv("ENABLE_HISTORICAL_VECTOR_MATCH", "true")
    assert alerts.evaluate(history(1), TODAY, 40, 10).c4["status"] == "insufficient_history"


# --- disponibilidad -------------------------------------------------------------------


def test_availability_is_100_at_baseline_and_penalises_beyond_1_5_sigma():
    base = availability.compute(vec(sleep_duration_z=0.0, grip_strength_z=0.0))
    assert base.score == 100
    mild = availability.compute(vec(sleep_duration_z=-1.4))
    strong = availability.compute(vec(sleep_duration_z=-2.0))
    assert mild.areas["fatigue_sleep"] == pytest.approx(100 - 25 * 1.4, abs=0.1)
    assert strong.areas["fatigue_sleep"] == pytest.approx(100 - 25 * (2.0 + 1.5 * 0.5), abs=0.1)


def test_self_report_weight_halved_with_high_social_desirability():
    v = vec(checkin_mood_z=-2.0, pvt_rt_z=0.0, checkin_fatigue_z=0.0)
    normal = availability.compute(v)
    low_reliability = availability.compute(v, social_desirability_high=True)
    weights = {c["field"]: c["weight"] for c in low_reliability.audit["contributions"] if "weight" in c}
    assert weights["checkin_mood_z"] == 0.5 and weights["pvt_rt_z"] == 1.0
    assert normal.areas["psychological"] == low_reliability.areas["psychological"]  # única fuente del área


def test_known_reason_ignores_subjective_drop_only():
    v = vec(checkin_mood_z=-2.5, pvt_rt_z=2.5)
    with_reason = availability.compute(v, known_reason=True)
    without = availability.compute(v)
    assert with_reason.areas["psychological"] == 100
    assert without.areas["psychological"] < 100
    assert with_reason.areas["fatigue_sleep"] == without.areas["fatigue_sleep"]  # objetivo intacto


def test_availability_reason_is_general():
    r = availability.compute(vec(social_centrality_z=-3.0))
    assert r.reason_category == "isolation"
    r = availability.compute(vec(nlp_anxiety_z=3.0))
    assert r.reason_category == "medical_followup"  # nunca detalle psicológico al comandante


def test_availability_does_not_touch_private_cycle():
    for module in (availability, alerts, planning):
        source = Path(module.__file__).read_text()
        assert "private_cycle" not in source.replace("no tiene acceso", "")
        tree = ast.parse(source)
        imported = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
        imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not any("cycle" in (m or "") or "social_graph" in (m or "") for m in imported)


# --- acciones y cooldown -----------------------------------------------------------------


def test_actions_and_cooldown():
    a = [alerts.Alert("C1", "fatigue_sleep", ("sleep_duration_z",), {"values_sigma": [2.1, 2.3, 2.5]}, "")]
    proposed = actions.actions_for(a)
    sig, codes = next(iter(proposed.items()))
    assert {"LOAD_ADJUST", "RECOVERY", "LIGHT_EXPOSURE"} <= set(codes)
    sev = actions.severity(a)
    first = actions.apply_cooldown(proposed, sev, {})
    assert all(d.notify and d.status == "new" for d in first)
    active = {(sig, c): sev for c in codes}
    stable = actions.apply_cooldown(proposed, sev - 0.1, active)
    assert all(not d.notify and d.status == "cooldown" for d in stable)
    worse = actions.apply_cooldown(proposed, sev + 1.0, active)
    assert all(d.notify and d.status == "worsening" for d in worse)


# --- planificación -------------------------------------------------------------------------


def _states(tired: str | None = None):
    states = {}
    for a in ("A1", "A2", "A3", "A4"):
        states[a] = {"sleep_duration_h": 7.4, "sleep_quality": 85, "pvt_lapses": 2, "fatigue_self": 2,
                     "grip_strength": 40, "spo2": 97, "resting_hr": 60, "work_hours_3d": 24}
    if tired:
        states[tired].update(sleep_duration_h=4.5, pvt_lapses=8, fatigue_self=4.5)
    return states


BASE = {a: {"pvt_lapses": (2.0, 1.0), "grip_strength": (40.0, 3.0), "resting_hr": (60.0, 4.0)}
        for a in ("A1", "A2", "A3", "A4")}


@pytest.fixture(scope="module")
def doc():
    return planning.generate("moon", 12, _states("A2"), BASE, {}, {"A1": [10, 10, 9, 9, 9, 9]})


def test_three_valid_plans_with_explanations(doc):
    assert doc["status"] == "ok" and len(doc["plans"]) == 3
    assert doc["social_graph_used"] is False
    for plan in doc["plans"]:
        o = plan["option"]
        assert o["advantages"] and o["disadvantages"]
        assert "changes_vs_original" in o and "workload_comparison" in o
        view = planning.crew_view(plan)
        assert view["assignments"]
        text = repr(view).lower()
        for word in ("sleep_duration", "pvt", "fatigue_self", "justification", "grafo"):
            assert word not in text


def test_weekly_limit_applied(doc):
    a1 = next(l for l in doc["weekly_limits"] if l["astronaut"] == "A1")
    assert a1["max_today_h"] == pytest.approx(4.0)
    for plan in doc["plans"]:
        assert plan["global"]["workload"]["A1"]["hours"] <= 4.0 + 1e-6


def test_science_never_reassigned(doc):
    from crew_planner.catalog import load_catalog
    catalog = load_catalog()
    science = {t["task_id"] for t in catalog.environment_tasks("moon") if t["category"] == "science"}
    owners = set()
    for plan in doc["plans"]:
        for e in plan["individual"]:
            base = e["task"].split(":")[0]
            if base in science:
                owners.add((base, e["astronaut"]))
    # cada experimento lo hace siempre la misma persona en las tres opciones
    by_task = {}
    for task, who in owners:
        by_task.setdefault(task, set()).add(who)
    assert all(len(w) == 1 for w in by_task.values())


def test_forbidden_state_is_rejected():
    states = _states()
    states["A1"]["mood"] = 1
    with pytest.raises(ValueError, match="no admitidos"):
        planning.generate("moon", 12, states, BASE, {}, {})
