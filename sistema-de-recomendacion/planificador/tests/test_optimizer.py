"""Optimizador: casos pequeños con óptimo conocido, etapas, diagnóstico y salida."""

import json
from dataclasses import replace

import pytest

from conftest import DAY, H, astronaut, social_doc, task
from crew_planner.__main__ import main
from crew_planner.inputs import from_dict
from crew_planner.model import parse_clock
from crew_planner.planner import plan_day

REF = 10 * DAY


def sleep(value, age_h=2.0):
    return {"parameter": "sleep_duration_h", "value": value, "measured_at": REF - age_h * H, "source": "watch"}


def problem(crew, tasks, social=None, history=None):
    return from_dict({"day": 10, "crew": crew, "tasks": tasks, "social": social, "history": history or []})


def with_weights(config, **weights):
    return replace(config, weights=replace(config.weights, **weights))


def assigned(plan):
    out = {e["task"]: (e["astronaut"],) for e in plan["individual"]}
    out.update({e["task"]: tuple(e["members"]) for e in plan["collective"]})
    return out


def stable(plan):
    """Plan sin tiempos de cálculo, para comparar ejecuciones."""
    copy = json.loads(json.dumps(plan))
    for stage in copy["global"]["solver"]:
        stage.pop("wall_time_s")
    return copy


# --- óptimo conocido --------------------------------------------------------------------


def test_rested_astronaut_gets_the_task(config):
    p = problem(
        [astronaut("A1", measurements=[sleep(4)]), astronaut("A2", measurements=[sleep(8)])],
        [task("T1", requirements=[{"parameter": "sleep_duration_h", "min": 7}])],
    )
    plan = plan_day(p, config)
    assert plan["status"] == "ok"
    assert assigned(plan) == {"T1": ("A2",)}
    entry = plan["individual"][0]
    assert entry["adequacy"] == 1.0
    assert entry["alternatives"][0]["members"] == ["A1"] and entry["alternatives"][0]["delta"] > 0
    assert plan["global"]["violations"] == []


def test_deterministic(config):
    crew = [astronaut(f"A{k}", measurements=[sleep(6 + k)]) for k in range(4)]
    tasks = [task(f"T{k}", duration_min=60 + 15 * k) for k in range(6)]
    first = plan_day(problem(crew, tasks), config)
    second = plan_day(problem(crew, tasks), config)
    assert stable(first) == stable(second)


def test_equity_spreads_identical_tasks(config):
    crew = [astronaut("A1"), astronaut("A2")]
    tasks = [task(f"T{k}") for k in range(4)]
    plan = plan_day(problem(crew, tasks), config)
    hours = {a: w["hours"] for a, w in plan["global"]["workload"].items()}
    assert hours == {"A1": 2.0, "A2": 2.0}


def test_equity_follows_capacity(config):
    tired = {"parameter": "fatigue_self", "value": 5, "measured_at": REF - H, "source": "checkin"}
    rested = {"parameter": "fatigue_self", "value": 1, "measured_at": REF - H, "source": "checkin"}
    crew = [astronaut("A1", measurements=[sleep(8), tired]), astronaut("A2", measurements=[sleep(8), rested])]
    plan = plan_day(problem(crew, [task(f"T{k}") for k in range(6)]), config)
    w = plan["global"]["workload"]
    assert w["A2"]["load"] > w["A1"]["load"]


def test_optional_tasks_prioritized_by_importance(config):
    crew = [astronaut("A1", work=[["08:00", "09:00"]])]
    tasks = [
        task("LOW", importance=1, mandatory=False, earliest="08:00", latest="09:00"),
        task("HIGH", importance=4, mandatory=False, earliest="08:00", latest="09:00"),
    ]
    plan = plan_day(problem(crew, tasks), config)
    assert assigned(plan) == {"HIGH": ("A1",)}
    assert plan["global"]["pending"] == [{"task": "LOW", "mandatory": False, "reason": "aplazable y no cubierta"}]


def test_rest_after_demanding_task(config):
    crew = [astronaut("A1")]
    tasks = [
        task("HARD", demanding=True, earliest="08:00", latest="09:00"),
        task("NEXT", earliest="09:00", latest="16:00"),
    ]
    plan = plan_day(problem(crew, tasks), config)
    starts = {e["task"]: parse_clock(e["start"], "") for e in plan["individual"]}
    assert starts["NEXT"] >= 9 * H + config.limits.rest_after_demanding_min * 60


def test_shared_resource_never_overlaps(config):
    crew = [astronaut("A1"), astronaut("A2")]
    tasks = [task("T1", resources=["robot"], earliest="08:00", latest="10:00"),
             task("T2", resources=["robot"], earliest="08:00", latest="10:00")]
    plan = plan_day(problem(crew, tasks), config)
    starts = sorted(parse_clock(e["start"], "") for e in plan["individual"])
    assert starts[1] - starts[0] >= H


def test_weighted_mode(config):
    weighted = replace(config, stages=replace(config.stages, mode="weighted"))
    crew = [astronaut("A1"), astronaut("A2")]
    plan = plan_day(problem(crew, [task("T1"), task("T2", mandatory=False)]), weighted)
    assert plan["status"] == "ok" and plan["mode"] == "weighted"
    assert set(assigned(plan)) == {"T1", "T2"}


# --- compatibilidad e inclusión ----------------------------------------------------------


def team_world(statuses=None, intensity=0.2, importance=2):
    crew = [astronaut("A1"), astronaut("A2"), astronaut("A3")]
    # A1–A2 se relacionan mucho, A3 poco con ambos
    w = [[None, 0.8, 0.1], [0.8, None, 0.1], [0.1, 0.1, None]]
    social = social_doc(9, ["A1", "A2", "A3"], w, statuses)
    team = task("TEAM", kind="collective", min_people=2, max_people=2, intensity=intensity, importance=importance)
    return crew, [team], social


def test_compatibility_prefers_teams_that_interact(config):
    crew, tasks, social = team_world()
    plan = plan_day(problem(crew, tasks, social), config)
    assert assigned(plan) == {"TEAM": ("A1", "A2")}
    interaction = plan["collective"][0]["interaction"]
    assert interaction["score"] == 0.8 and interaction["used"]


def test_compatibility_can_be_switched_off(config):
    crew, tasks, social = team_world()
    # Sin γ, A3 es algo más adecuado y forma parte del equipo
    crew[0] = astronaut("A1", measurements=[sleep(5)])
    tasks[0]["requirements"] = [{"parameter": "sleep_duration_h", "min": 7}]
    on = plan_day(problem(crew, tasks, social), with_weights(config, gamma=2.0))
    off = plan_day(problem(crew, tasks, social), with_weights(config, gamma=0.0))
    assert assigned(on) == {"TEAM": ("A1", "A2")}
    assert assigned(off) == {"TEAM": ("A2", "A3")}


def test_inclusion_in_low_load_task_within_epsilon(config):
    crew, tasks, social = team_world({"A3": "review"})
    cfg = with_weights(config, gamma=0.02)  # la compatibilidad apenas pesa: cabe en ε
    plan = plan_day(problem(crew, tasks, social), cfg)
    members = assigned(plan)["TEAM"]
    assert "A3" in members and plan["collective"][0]["inclusion"] == ["A3"]
    assert plan["global"]["social"]["inclusion"] == ["A3"]
    # La garantía de ε: frente al mismo caso sin inclusión
    base = plan_day(problem(crew, tasks, social), with_weights(cfg, mu=0.0))
    op = lambda p: p["global"]["costs"]["total"] - p["global"]["costs"]["integration"]
    floor = cfg.weights.gamma * cfg.importance.normalize(2) * (1 - 0.1)
    slack = max(cfg.stages.epsilon * (op(base) + floor), cfg.stages.epsilon_abs)
    assert op(plan) <= op(base) + slack + 1e-6


def test_no_inclusion_when_it_costs_too_much(config):
    crew, tasks, social = team_world({"A3": "review"})
    plan = plan_day(problem(crew, tasks, social), with_weights(config, gamma=2.0))
    assert assigned(plan) == {"TEAM": ("A1", "A2")}
    assert plan["global"]["social"]["inclusion"] == []


def test_no_inclusion_in_demanding_tasks(config):
    crew, tasks, social = team_world({"A3": "review"}, intensity=0.9)
    plan = plan_day(problem(crew, tasks, social), with_weights(config, gamma=0.02))
    assert plan["collective"][0]["low_load"] is False
    assert plan["global"]["social"]["inclusion"] == []


def test_crew_text_never_mentions_social_indicators(config):
    crew, tasks, social = team_world({"A3": "review"})
    plan = plan_day(problem(crew, tasks, social), with_weights(config, gamma=0.02))
    for entry in plan["collective"] + plan["individual"]:
        text = entry["crew_text"].lower()
        for word in ("interacci", "inclusi", "aisla", "integraci", "review", "grafo"):
            assert word not in text


# --- sin solución -----------------------------------------------------------------------


def test_no_candidates_is_explained(config):
    p = problem([astronaut("A1", qualifications=[]), astronaut("A2", qualifications=[])],
                [task("EVA", qualifications=["eva"])])
    plan = plan_day(p, config)
    assert plan["status"] == "infeasible"
    conflict = plan["conflicts"][0]
    assert conflict["kind"] == "no_candidates" and conflict["tasks"] == ["EVA"]
    assert all("cualificación" in d["reasons"][0] for d in conflict["discarded"])
    assert plan["individual"] == [] and plan["collective"] == []


def test_conflict_core_is_minimal(config):
    crew = [astronaut("A1"), astronaut("A2", qualifications=[])]
    tasks = [
        task("T1", qualifications=["eva"], earliest="08:00", latest="09:00"),
        task("T2", qualifications=["eva"], earliest="08:00", latest="09:00"),
        task("T3"),  # sin relación con el conflicto
    ]
    plan = plan_day(problem(crew, tasks), config)
    assert plan["status"] == "infeasible"
    conflict = plan["conflicts"][0]
    assert conflict["kind"] == "conflict"
    assert sorted(conflict["tasks"]) == ["T1", "T2"]
    assert conflict["limits_of"] == []
    assert "aplazar T1 a otro día" in conflict["suggestions"]


def test_conflict_with_hour_limits(config):
    crew = [astronaut("A1", max_work_h=1.5), astronaut("A2", qualifications=[])]
    tasks = [task("T1", qualifications=["eva"]), task("T2", qualifications=["eva"])]
    plan = plan_day(problem(crew, tasks), config)
    conflict = plan["conflicts"][0]
    assert sorted(conflict["tasks"]) == ["T1", "T2"] and conflict["limits_of"] == ["A1"]


def test_critical_unknown_data_blocks_instead_of_assuming(config):
    req = [{"parameter": "spo2", "min": 94, "critical": True}]
    p = problem([astronaut("A1"), astronaut("A2")], [task("T1", requirements=req)])
    plan = plan_day(p, config)
    assert plan["status"] == "infeasible"
    assert "desconocido" in plan["conflicts"][0]["discarded"][0]["reasons"][0]


# --- línea de comandos ------------------------------------------------------------------


def test_cli(tmp_path, capsys):
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"day": 10, "crew": [astronaut("A1")], "tasks": [task("T1")]}))
    out = tmp_path / "plan.json"
    assert main([str(ok), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["status"] == "ok"

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"day": 10, "crew": [astronaut("A1", qualifications=[])],
                               "tasks": [task("T1", qualifications=["eva"])]}))
    assert main([str(bad), "--out", str(out)]) == 2

    broken = tmp_path / "broken.json"
    broken.write_text("{")
    assert main([str(broken)]) == 1
    assert "Entrada inválida" in capsys.readouterr().err


def test_invalid_solution_is_never_returned(config, monkeypatch):
    """Si el optimizador fallara, la verificación independiente lo detiene."""
    from crew_planner import planner
    from crew_planner.optimizer import Chosen, Solution, StageResult

    p = problem([astronaut("A1")], [task("T1"), task("T2")])

    def broken(self):
        o1, o2 = self.ctx.options["T1"][0], self.ctx.options["T2"][0]
        stage = [StageResult("operational", "OPTIMAL", 0.0, 0.0)]
        return Solution(True, [Chosen(o1, 8 * H), Chosen(o2, 8 * H)], stage)  # se solapan

    monkeypatch.setattr(planner.PlanModel, "solve", broken)
    with pytest.raises(planner.PlanVerificationError, match="overlap"):
        plan_day(p, config)
