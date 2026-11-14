"""Restricciones duras, verificador de planes, equipos y contexto."""

import random

import pytest

from conftest import DAY, H, astronaut, social_doc, task
from crew_planner.context import build_context
from crew_planner.eligibility import (
    CRITICAL_UNKNOWN, CRITICAL_UNMET, NO_TIME, QUALIFICATION, Assignment, eligibility, free_time,
    verify_plan,
)
from crew_planner.inputs import from_dict
from crew_planner.model import Astronaut, Task, ValidationError
from crew_planner.social import from_daily_result
from crew_planner.state import astronaut_state
from crew_planner.teams import (
    candidate_teams, compatibility_cost, has_anchor, inclusion_members, is_low_load,
    social_active, team_compatibility,
)

REF = 10 * DAY


def build(raw_astronaut, config):
    a = Astronaut.from_dict(raw_astronaut)
    return a, astronaut_state(a, config.parameters, REF)


def codes(result):
    return {r.code for r in result.reasons}


# --- elegibilidad ------------------------------------------------------------------


def test_qualification_is_hard(config):
    a, s = build(astronaut(qualifications=[]), config)
    t = Task.from_dict(task(qualifications=["eva"]))
    assert codes(eligibility(a, t, s, config)) == {QUALIFICATION}


def test_good_physiology_never_compensates_missing_qualification(config):
    rng = random.Random(0)
    t = Task.from_dict(task(qualifications=["robotics"]))
    for _ in range(50):
        perfect = [{"parameter": p, "value": v, "measured_at": REF - H, "source": "x"}
                   for p, v in (("sleep_duration_h", rng.uniform(7, 9)), ("spo2", 99))]
        a, s = build(astronaut(qualifications=["eva"], measurements=perfect), config)
        assert not eligibility(a, t, s, config).eligible


def test_critical_requirement_unmet_or_unknown(config):
    t = Task.from_dict(task(requirements=[{"parameter": "spo2", "min": 94, "critical": True}]))
    low, s_low = build(astronaut(measurements=[{"parameter": "spo2", "value": 90, "measured_at": REF - H, "source": "x"}]), config)
    unknown, s_unknown = build(astronaut(measurements=[]), config)
    stale, s_stale = build(astronaut(measurements=[{"parameter": "spo2", "value": 99, "measured_at": REF - 48 * H, "source": "x"}]), config)
    ok, s_ok = build(astronaut(measurements=[{"parameter": "spo2", "value": 97, "measured_at": REF - H, "source": "x"}]), config)
    assert codes(eligibility(low, t, s_low, config)) == {CRITICAL_UNMET}
    assert codes(eligibility(unknown, t, s_unknown, config)) == {CRITICAL_UNKNOWN}
    assert codes(eligibility(stale, t, s_stale, config)) == {CRITICAL_UNKNOWN}
    assert eligibility(ok, t, s_ok, config).eligible


def test_availability_and_sleep(config):
    a, s = build(astronaut(unavailable=[["08:00", "15:30"]]), config)
    assert free_time(a) == [(15.5 * H, 16 * H)]
    t = Task.from_dict(task(duration_min=60))
    assert codes(eligibility(a, t, s, config)) == {NO_TIME}
    rested, s_rested = build(astronaut(), config)
    night = Task.from_dict(task(earliest="01:00", latest="05:00"))
    assert codes(eligibility(rested, night, s_rested, config)) == {NO_TIME}  # duerme y no trabaja


def test_all_reasons_are_reported(config):
    a, s = build(astronaut(qualifications=[], measurements=[]), config)
    t = Task.from_dict(task(qualifications=["eva"], requirements=[{"parameter": "spo2", "min": 94, "critical": True}],
                            earliest="20:00", latest="22:00"))
    assert codes(eligibility(a, t, s, config)) == {QUALIFICATION, CRITICAL_UNKNOWN, NO_TIME}


# --- verificador ---------------------------------------------------------------------


@pytest.fixture
def world(config):
    crew = [Astronaut.from_dict(astronaut("A1")), Astronaut.from_dict(astronaut("A2"))]
    tasks = [
        Task.from_dict(task("T1", demanding=True, resources=["robot"])),
        Task.from_dict(task("T2", resources=["robot"], mandatory=False)),
        Task.from_dict(task("T3", kind="collective", min_people=2, max_people=2,
                            team_qualifications=[{"qualification": "eva", "mode": "all"}])),
    ]
    states = {a.id: astronaut_state(a, config.parameters, REF) for a in crew}
    return crew, tasks, states


def test_valid_plan_has_no_violations(world, config):
    crew, tasks, states = world
    plan = [Assignment("T1", ("A1",), 8 * H), Assignment("T3", ("A1", "A2"), 10 * H),
            Assignment("T2", ("A2",), 12 * H)]
    assert verify_plan(crew, tasks, states, config, plan) == []


@pytest.mark.parametrize("plan, code", [
    ([Assignment("T3", ("A1", "A2"), 10 * H)], "coverage"),
    ([Assignment("T1", ("A1",), 8 * H), Assignment("T1", ("A2",), 9 * H), Assignment("T3", ("A1", "A2"), 10 * H)], "coverage"),
    ([Assignment("T1", ("A1",), 8 * H), Assignment("T3", ("A1", "A2"), 8.5 * H)], "overlap"),
    ([Assignment("T1", ("A1",), 8 * H), Assignment("T3", ("A1", "A2"), 9 * H)], "rest"),
    ([Assignment("T1", ("A1",), 8 * H), Assignment("T2", ("A2",), 8.5 * H), Assignment("T3", ("A1", "A2"), 12 * H)], "resource"),
    ([Assignment("T1", ("A1",), 15.5 * H), Assignment("T3", ("A1", "A2"), 10 * H)], "window"),
    ([Assignment("T1", ("A1",), 8 * H), Assignment("T3", ("A1",), 10 * H)], "team_size"),
])
def test_violations_are_detected(world, config, plan, code):
    crew, tasks, states = world
    assert code in {v.code for v in verify_plan(crew, tasks, states, config, plan)}


def test_verifier_checks_qualifications_and_hours(world, config):
    crew, tasks, states = world
    crew = [crew[0], Astronaut.from_dict(astronaut("A2", qualifications=[], max_work_h=0.5))]
    states = {a.id: astronaut_state(a, config.parameters, REF) for a in crew}
    plan = [Assignment("T1", ("A1",), 8 * H), Assignment("T3", ("A1", "A2"), 10 * H)]
    found = {v.code for v in verify_plan(crew, tasks, states, config, plan)}
    assert {"team_qualification", "max_hours"} <= found


# --- equipos ---------------------------------------------------------------------------


def test_low_load_classification(config):
    collective = dict(kind="collective", min_people=2, max_people=3)
    assert is_low_load(Task.from_dict(task(**collective, intensity=0.3, importance=2)), config)
    assert not is_low_load(Task.from_dict(task(**collective, intensity=0.8, importance=2)), config)
    assert not is_low_load(Task.from_dict(task(**collective, intensity=0.3, importance=5)), config)
    assert not is_low_load(Task.from_dict(task(**collective, intensity=0.3, importance=2, demanding=True)), config)
    assert not is_low_load(Task.from_dict(task(**collective, intensity=0.3, importance=2, low_load=False)), config)
    assert not is_low_load(Task.from_dict(task(intensity=0.1, importance=1)), config)  # individual


def test_candidate_teams_respect_size_and_team_qualifications(config):
    crew = [Astronaut.from_dict(astronaut(f"A{k}", qualifications=["eva"] if k < 2 else [])) for k in range(4)]
    t = Task.from_dict(task(kind="collective", min_people=2, max_people=3,
                            team_qualifications=[{"qualification": "eva", "count": 2}]))
    free = {a.id: free_time(a) for a in crew}
    teams = candidate_teams(t, crew, free, config)
    assert all({"A0", "A1"} <= set(team.members) for team in teams)
    assert [team.members for team in teams] == [("A0", "A1"), ("A0", "A1", "A2"), ("A0", "A1", "A3")]


def test_candidate_teams_need_common_free_time(config):
    a = Astronaut.from_dict(astronaut("A1", work=[["08:00", "10:00"]]))
    b = Astronaut.from_dict(astronaut("A2", work=[["10:00", "12:00"]]))
    t = Task.from_dict(task(kind="collective", min_people=2, max_people=2, earliest="00:00", latest="24:00"))
    assert candidate_teams(t, [a, b], {x.id: free_time(x) for x in (a, b)}, config) == []


def test_candidate_cap_raises(config):
    from dataclasses import replace
    small = replace(config, solver=replace(config.solver, max_team_candidates=2))
    crew = [Astronaut.from_dict(astronaut(f"A{k}")) for k in range(4)]
    t = Task.from_dict(task(kind="collective", min_people=2, max_people=2))
    with pytest.raises(ValidationError, match="equipos posibles"):
        candidate_teams(t, crew, {a.id: free_time(a) for a in crew}, small)


def test_compatibility_ignores_unevaluable_pairs(config):
    snap = from_daily_result(social_doc(9, ["A1", "A2", "A3"],
                                        [[None, 0.8, None], [0.8, None, 0.2], [None, 0.2, None]]))
    full = team_compatibility(["A1", "A2", "A3"], snap)
    assert full.score == pytest.approx(0.5) and full.evaluable_pairs == 2 and full.pairs == 3
    assert team_compatibility(["A1", "A3"], snap).score is None
    t = Task.from_dict(task(kind="collective", min_people=2, max_people=3, importance=5))
    good = compatibility_cost(t, team_compatibility(["A1", "A2"], snap), 0.5, True, config)
    bad = compatibility_cost(t, team_compatibility(["A2", "A3"], snap), 0.5, True, config)
    assert good < 0 < bad
    assert compatibility_cost(t, team_compatibility(["A1", "A3"], snap), 0.5, True, config) == 0.0
    assert compatibility_cost(t, full, 0.5, False, config) == 0.0


def test_inclusion_only_low_load_and_with_anchor(config):
    need = {"A1": 0.0, "A2": 1.0, "A3": 0.5}
    easy = Task.from_dict(task(kind="collective", min_people=2, max_people=3, intensity=0.2, importance=2))
    hard = Task.from_dict(task(kind="collective", min_people=2, max_people=3, intensity=0.9, importance=2))
    assert inclusion_members(easy, ["A1", "A2"], need, True, config) == ["A2"]
    assert inclusion_members(hard, ["A1", "A2"], need, True, config) == []
    assert inclusion_members(easy, ["A2", "A3"], need, True, config) == []  # sin nadie sin señales
    assert inclusion_members(easy, ["A1", "A2"], need, False, config) == []
    assert has_anchor(["A1", "A2"], need) and not has_anchor(["A2", "A3"], need)


def test_social_active_rules(config):
    w = [[None, 0.4], [0.4, None]]
    assert social_active(None, 10, config)[0] is False
    assert social_active(from_daily_result(social_doc(9, ["A1", "A2"], w)), 10, config)[0] is True
    assert social_active(from_daily_result(social_doc(5, ["A1", "A2"], w)), 10, config)[0] is False
    assert social_active(from_daily_result(social_doc(9, ["A1", "A2"], w, drop=True)), 10, config)[0] is False


# --- contexto --------------------------------------------------------------------------


def test_context_builds_options(config):
    raw = {
        "day": 10,
        "crew": [astronaut("A1"), astronaut("A2"), astronaut("A3", qualifications=[])],
        "tasks": [
            task("T1", qualifications=["eva"]),
            task("T2", kind="collective", min_people=2, max_people=2, intensity=0.2, importance=2),
        ],
        "social": social_doc(9, ["A1", "A2", "A3"], [[None, 0.8, 0.1], [0.8, None, 0.1], [0.1, 0.1, None]],
                             {"A3": "review"}),
    }
    ctx = build_context(from_dict(raw), config)
    assert ctx.eligible("T1") == ["A1", "A2"]
    assert [o.members for o in ctx.options["T1"]] == [("A1",), ("A2",)]
    teams = {o.members: o for o in ctx.options["T2"]}
    assert set(teams) == {("A1", "A2"), ("A1", "A3"), ("A2", "A3")}
    assert teams[("A1", "A2")].compatibility_cost < teams[("A1", "A3")].compatibility_cost
    assert teams[("A1", "A3")].inclusion == ("A3",)
    assert ctx.low_load == {"T1": False, "T2": True}
    assert ctx.social_active and ctx.k_ref == pytest.approx(0.1)
    assert sum(ctx.shares.values()) == pytest.approx(1.0)
