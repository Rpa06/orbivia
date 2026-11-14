"""Reglas previas al optimizador: límites semanales e investigación especializada."""

import pytest

from conftest import astronaut, task
from crew_planner.inputs import from_dict
from crew_planner.model import Astronaut, Task
from crew_planner.planner import plan_day
from crew_planner.policy import (
    apply_weekly_limits, is_reassignable, lock_specialized, specialist_owner, weekly_limit,
)


def test_weekly_limit_caps_the_day_at_60_hours():
    limit = weekly_limit("A1", [9, 9, 9, 9, 9, 9], daily_max_h=8.0)  # 54 h en 6 días
    assert limit.max_today_h == pytest.approx(6.0)
    assert "60 h" in limit.reason


def test_no_more_than_two_long_days():
    limit = weekly_limit("A1", [10, 10, 4, 4, 4, 4], daily_max_h=12.0)
    assert limit.long_days_last_6_days == 2
    assert limit.max_today_h < 10.0


def test_one_long_day_still_allows_another():
    limit = weekly_limit("A1", [10, 4, 4, 4, 4, 4], daily_max_h=12.0)
    assert limit.max_today_h == pytest.approx(12.0) and limit.reason == ""


def test_apply_weekly_limits_and_planner_respects_them(config):
    crew = [Astronaut.from_dict(astronaut("A1")), Astronaut.from_dict(astronaut("A2"))]
    limited, limits = apply_weekly_limits(crew, {"A1": [10, 10, 10, 10, 10, 9.5]}, config.limits.max_work_h)
    assert limited[0].max_work_h == pytest.approx(0.5)
    assert limited[1].max_work_h is None
    raw = {
        "day": 10,
        "crew": [a.to_dict() for a in limited],
        "tasks": [task("T1", duration_min=60, requirements=[])],
    }
    plan = plan_day(from_dict(raw), config)
    assert plan["status"] == "ok"
    assert [e["astronaut"] for e in plan["individual"]] == ["A2"]


def test_specialized_science_is_never_reassigned():
    crew = {"A1": ["payload_operations"], "A2": ["payload_operations", "eva_certified"]}
    science = {"task_id": "S1", "category": "science", "technical_requirements": ["payload_operations"]}
    assert specialist_owner(science, crew) == "A1"
    tasks = [Task.from_dict(task("S1", requirements=[])), Task.from_dict(task("M1", requirements=[]))]
    locked = lock_specialized(tasks, {"S1": "science", "M1": "maintenance"}, {"S1": "A1"})
    assert locked[0].only_for == frozenset({"A1"})
    assert locked[1].only_for == frozenset()
    assert not is_reassignable("science") and is_reassignable("maintenance")


def test_specialized_without_owner_is_left_out():
    tasks = [Task.from_dict(task("S1", requirements=[]))]
    assert lock_specialized(tasks, {"S1": "science"}, {}) == []
