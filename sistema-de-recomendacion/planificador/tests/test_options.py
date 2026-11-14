"""Planes alternativos: validez, diversidad, comparación y salida."""

import json
from dataclasses import replace

import pytest

from conftest import astronaut, task
from crew_planner.__main__ import main
from crew_planner.config import Alternatives, PlanProfile, load_config
from crew_planner.inputs import from_dict
from crew_planner.model import ValidationError
from crew_planner.options import _assignments, plan_options
from crew_planner.planner import plan_day
from crew_planner.report import CREW, GROUND, render_options_html
from crew_planner.simulation import SCENARIOS, environment_input, simulate


@pytest.fixture(scope="module")
def isolation(config):
    raw = SCENARIOS["isolation"](10, 42)
    return plan_options(from_dict(raw), config), raw


def test_three_valid_and_distinct_plans(isolation, config):
    doc, raw = isolation
    assert doc["status"] == "ok" and len(doc["plans"]) == 3
    mandatory = {t["id"] for t in raw["tasks"] if t.get("mandatory", True)}
    seen = []
    for plan, letter in zip(doc["plans"], "ABC"):
        assert plan["status"] == "ok" and plan["global"]["violations"] == []
        assert plan["option"]["id"] == letter
        assert mandatory <= set(plan["global"]["covered"])
        current = set(_assignments(plan).items())
        for previous in seen:
            assert len(previous - current) >= config.alternatives.min_difference
        seen.append(current)


def test_plan_a_is_the_single_plan(isolation, config):
    doc, raw = isolation
    single = plan_day(from_dict(raw), config)
    assert _assignments(doc["plans"][0]) == _assignments(single)


def test_each_plan_explains_itself(isolation):
    doc, _ = isolation
    for plan in doc["plans"]:
        o = plan["option"]
        assert o["label"] and o["description"] and o["advantages"]
        assert set(o["metrics"]) >= {"adequacy", "uncertainty", "load_spread_h", "repetition", "team_interaction"}
    for plan in doc["plans"][1:]:
        assert plan["option"]["differences_vs_A"]
    assert doc["decision"]["status"] == "pending"
    # La opción de reparto es la que mejor reparte la carga en este escenario
    rotation = doc["plans"][2]
    assert any("Carga más repartida" in a for a in rotation["option"]["advantages"])


def test_profiles_change_the_weights(isolation, config):
    doc, _ = isolation
    best_fit = doc["plans"][1]["option"]["weights"]
    assert best_fit["alpha_state"] == 2 * config.weights.alpha_state


def test_fewer_plans_when_no_alternative_exists(config):
    p = from_dict({"day": 10, "crew": [astronaut("A1")], "tasks": [task("T1")]})
    doc = plan_options(p, config)
    assert doc["status"] == "ok" and len(doc["plans"]) == 1
    assert doc["notes"] and "solo los distintos" in doc["notes"][0]


def test_diversity_is_relaxed_before_giving_up(config):
    # Dos personas y dos tareas: solo hay dos repartos posibles, que difieren en 2 asignaciones
    p = from_dict({"day": 10, "crew": [astronaut("A1"), astronaut("A2")],
                   "tasks": [task("T1", earliest="08:00", latest="09:00"),
                             task("T2", earliest="08:00", latest="09:00")]})
    doc = plan_options(p, replace(config, alternatives=replace(config.alternatives, min_difference=3)))
    assert len(doc["plans"]) == 2
    assert doc["plans"][1]["option"]["min_difference_applied"] == 2
    assert any("solo puede diferir" in n for n in doc["notes"])


def test_infeasible_day_reports_conflicts(config):
    doc = plan_options(from_dict(SCENARIOS["infeasible"](10, 42)), config)
    assert doc["status"] == "infeasible" and doc["conflicts"][0]["kind"] == "conflict"


def test_count_limits(config):
    p = from_dict(SCENARIOS["nominal"](10, 42))
    assert len(plan_options(p, config, count=2)["plans"]) == 2
    with pytest.raises(ValueError):
        plan_options(p, config, count=4)


def test_every_environment_gets_three_options(config):
    for env in ("iss", "moon", "mars", "satellite"):
        doc = plan_options(from_dict(environment_input(env, 2)), config)
        assert doc["status"] == "ok" and len(doc["plans"]) == 3, env
        assert all(p["global"]["violations"] == [] for p in doc["plans"])


# --- configuración -------------------------------------------------------------------------


def test_alternatives_config():
    config = load_config(env={"CP_ALTERNATIVES_COUNT": "2", "CP_ALTERNATIVES_MIN_DIFFERENCE": "4"})
    assert config.alternatives.count == 2 and config.alternatives.min_difference == 4
    with pytest.raises(ValidationError, match="peso desconocido"):
        PlanProfile("x", "X", "", {"alpha_magic": 2.0})
    with pytest.raises(ValidationError, match="count"):
        Alternatives(count=5)
    with pytest.raises(ValidationError, match="count"):
        load_config(env={"CP_ALTERNATIVES_COUNT": "9"})


# --- salida ----------------------------------------------------------------------------------


def test_options_report_for_ground_and_crew(isolation):
    doc, raw = isolation
    ground = render_options_html(doc, raw, GROUND)
    assert "Comparación" in ground and ground.count('class="plan-option"') == 3
    assert "Opción C · Reparto y rotación" in ground
    crew = render_options_html(doc, raw, CREW).lower()
    assert crew.count('class="plan-option"') == 3
    for word in ("comparación", "interacci", "inclusi", "coste", "capacidad", "justific", "grafo"):
        assert word not in crew, word


def test_cli_returns_options_by_default(tmp_path):
    source = tmp_path / "in.json"
    source.write_text(json.dumps(SCENARIOS["nominal"](10, 42)))
    out = tmp_path / "plans.json"
    assert main([str(source), "--out", str(out)]) == 0
    assert len(json.loads(out.read_text())["plans"]) == 3
    assert main([str(source), "--out", str(out), "--plans", "1"]) == 0
    assert "plans" not in json.loads(out.read_text())


def test_simulation_executes_the_chosen_plan(config):
    days = simulate(2, config, "nominal", options=3, choose=2)
    assert days[0]["executed"] == "C"
    did = {(task, people[0]) for task, people in _assignments(days[0]["plans"][2]).items() if len(people) == 1}
    # El día 2 se planifica con el historial del plan C: quien repite su tarea lo arrastra
    repeats = [e for p in days[1]["plans"] for e in p["individual"] if (e["task"], e["astronaut"]) in did]
    assert repeats and all(e["repetition_recent"] > 0 for e in repeats)
    fresh = [e for p in days[1]["plans"] for e in p["individual"] if (e["task"], e["astronaut"]) not in did]
    assert all(e["repetition_recent"] == 0 for e in fresh)
