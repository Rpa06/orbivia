"""Escenarios del enunciado con la tripulación sintética (Fase 5).

Cada test comprueba que el plan respeta todas las restricciones (el verificador
independiente no encuentra violaciones) y que el comportamiento tiene sentido.
"""

import json
from collections import Counter
from dataclasses import replace

import pytest

from crew_planner.simulation import SCENARIOS, main, scenario_input, simulate, summary
from crew_planner.planner import plan_day


def run(name, config):
    return plan_day(scenario_input(name), config)


def tasks_of(plan, astronaut):
    out = [e["task"] for e in plan["individual"] if e["astronaut"] == astronaut]
    out += [e["task"] for e in plan["collective"] if astronaut in e["members"]]
    return out


def who(plan, task_id):
    for e in plan["individual"]:
        if e["task"] == task_id:
            return {e["astronaut"]}
    for e in plan["collective"]:
        if e["task"] == task_id:
            return set(e["members"])
    return set()


def weights(config, **kw):
    return replace(config, weights=replace(config.weights, **kw))


@pytest.mark.parametrize("name", [n for n in SCENARIOS if n != "infeasible"])
def test_every_scenario_produces_a_valid_plan(name, config):
    plan = run(name, config)
    assert plan["status"] == "ok"
    assert plan["global"]["violations"] == []
    assert plan["global"]["proven_optimal"]
    # Todas las obligatorias quedan cubiertas
    covered = set(plan["global"]["covered"])
    mandatory = {t.id for t in scenario_input(name).tasks if t.mandatory}
    assert mandatory <= covered


def test_high_fatigue(config):
    plan = run("high_fatigue", config)
    assert not {"EVA_PREP", "LIFE_SUPPORT"} & set(tasks_of(plan, "A2"))
    entry = next(e for e in plan["individual"] if e["task"] == "EVA_PREP")
    assert any(d["astronaut"] == "A2" for d in entry["not_eligible"])
    w = plan["global"]["workload"]
    others = [w[a]["capacity"] for a in w if a != "A2"]
    assert w["A2"]["capacity"] < min(others)
    assert w["A2"]["target_load"] < min(w[a]["target_load"] for a in w if a != "A2")


def test_incomplete_data(config):
    plan = run("incomplete_data", config)
    assert plan["global"]["uncertainty"]["unknown_parameters"]["A3"] == sorted(config.parameters)
    # Nada con requisitos críticos: un dato ausente nunca vale como sano
    critical = {t.id for t in scenario_input("incomplete_data").tasks if any(r.critical for r in t.requirements)}
    assert not critical & set(tasks_of(plan, "A3"))
    assert plan["global"]["workload"]["A3"]["capacity"] == config.workload.capacity_min
    for e in plan["collective"]:
        if "A3" in e["members"]:
            detail = next(m for m in e["members_detail"] if m["astronaut"] == "A3")
            if detail["parameters"]:
                assert detail["uncertainty"] > 0 and "desconocidos" in e["justification"]


def test_critical_task_goes_to_whoever_meets_all_thresholds(config):
    plan = run("critical_task", config)
    assert who(plan, "EVA_PREP") == {"A1"}  # aunque la hizo ayer
    entry = next(e for e in plan["individual"] if e["task"] == "EVA_PREP")
    assert entry["cost"]["repetition"] == 0.0
    reasons = {d["astronaut"]: " ".join(d["reasons"]) for d in entry["not_eligible"]}
    assert "fatigue_self" in reasons["A2"] and "sleep_duration_h" in reasons["A5"]


@pytest.mark.parametrize("w", [
    {}, {"alpha_state": 5.0}, {"alpha_state": 0.0, "alpha_equity": 0.0, "beta_spread": 0.0},
    {"gamma": 3.0}, {"alpha_repetition": 5.0, "alpha_uncertainty": 0.0},
])
def test_unqualified_never_assigned(config, w):
    plan = run("unqualified", weights(config, **w))
    assert "A4" not in who(plan, "ROBOTIC_ARM")
    for task in scenario_input("unqualified").tasks:
        for a in who(plan, task.id):
            person = next(x for x in scenario_input("unqualified").crew if x.id == a)
            assert task.qualifications <= person.qualifications


def test_repetition_rotates_unless_only_one_qualified(config):
    plan = run("repetition", config)
    assert who(plan, "GALLEY") != {"A5"}
    assert who(plan, "MEDICAL_CHECK") == {"A4"}  # único cualificado: conserva la tarea
    medical = next(e for e in plan["individual"] if e["task"] == "MEDICAL_CHECK")
    assert medical["repetition_recent"] > 0.5 and medical["cost"]["repetition"] > 0
    # La rotación la produce el término de repetición: A5 sería tan buena opción como cualquiera
    galley = next(e for e in plan["individual"] if e["task"] == "GALLEY")
    a5 = next(alt for alt in galley["alternatives"] if alt["members"] == ["A5"]) if any(
        alt["members"] == ["A5"] for alt in galley["alternatives"]) else None
    assert a5 is None or a5["delta"] > 0


def test_isolation_inclusion_only_in_low_load_tasks(config):
    plan = run("isolation", config)
    assert plan["global"]["social"]["inclusion"] == ["A6"]
    for e in plan["collective"]:
        if "A6" in e["inclusion"]:
            assert e["low_load"]
        assert "A6" not in e["crew_text"] or "inclus" not in e["crew_text"].lower()
    demanding = {t.id for t in scenario_input("isolation").tasks if not t.collective or t.intensity > 0.4}
    included_in = [e["task"] for e in plan["collective"] if "A6" in e["inclusion"]]
    assert included_in and not set(included_in) & demanding


def test_isolation_without_graph_is_neutral(config):
    raw = SCENARIOS["isolation"](10, 42)
    raw["social"] = None
    from crew_planner.inputs import from_dict

    plan = plan_day(from_dict(raw), config)
    assert plan["global"]["social"]["used"] is False
    assert plan["global"]["social"]["inclusion"] == []
    assert all(e["cost"]["compatibility"] == 0 for e in plan["collective"])


def test_workload_imbalance_is_reduced_by_equity(config):
    def spread(plan):
        w = plan["global"]["workload"]
        return max(x["load"] for x in w.values()) - min(x["load"] for x in w.values())

    on = run("workload_imbalance", config)
    off = run("workload_imbalance", weights(config, alpha_equity=0.0, beta_spread=0.0))
    assert spread(on) < spread(off)
    a1 = on["global"]["workload"]["A1"]
    assert a1["load"] <= a1["target_load"] + 0.25


def test_infeasible_scenario_reports_minimal_conflict(config):
    plan = run("infeasible", config)
    assert plan["status"] == "infeasible"
    conflict = plan["conflicts"][0]
    assert conflict["kind"] == "conflict"
    assert sorted(conflict["tasks"]) == ["EVA_PREP", "EVA_PREP_2"]
    assert all(d["eligible"] == ["A1"] for d in conflict["details"])
    assert plan["individual"] == [] and plan["collective"] == []


def test_multi_day_rotation_and_validity(config):
    plans = simulate(7, config)
    assert all(p["status"] == "ok" and p["global"]["violations"] == [] for p in plans)
    galley = [next(iter(who(p, "GALLEY"))) for p in plans]
    assert all(a != b for a, b in zip(galley, galley[1:]))  # nadie dos días seguidos
    assert max(Counter(galley).values()) <= 2


def test_simulation_is_reproducible(config):
    def strip(plans):
        out = json.loads(json.dumps(plans))
        for p in out:
            for s in p["global"]["solver"]:
                s.pop("wall_time_s")
        return out

    assert strip(simulate(3, config)) == strip(simulate(3, config))


def test_simulation_cli(tmp_path, capsys, config):
    assert main(["--scenario", "nominal", "--days", "2", "--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        f"plan_{d}{suffix}" for d in ("0010", "0011")
        for suffix in (".html", ".json", "_tripulacion.html")
    ]
    assert "Día 11: ok" in capsys.readouterr().out
    assert main(["--scenario", "infeasible"]) == 2
    assert "conflicto" in summary(run("infeasible", config))
