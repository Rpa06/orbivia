"""Modelo de datos: validación y conversión a JSON."""

import json

import pytest

from conftest import astronaut, task
from crew_planner.model import (
    Astronaut, Measurement, ParameterSpec, Requirement, Task, TeamQualification,
    ValidationError, format_clock, parse_clock,
)


def test_clock_roundtrip():
    assert parse_clock("08:30", "x") == 8.5 * 3600
    assert parse_clock("24:00", "x") == 86400
    assert format_clock(parse_clock("17:45", "x")) == "17:45"
    for bad in ("25:00", "8h", "08:60", "-01:00"):
        with pytest.raises(ValidationError):
            parse_clock(bad, "x")


def test_astronaut_roundtrip():
    a = Astronaut.from_dict(astronaut())
    again = Astronaut.from_dict(json.loads(json.dumps(a.to_dict())))
    assert again == a
    assert a.qualifications == frozenset({"eva"})
    assert a.work == ((8 * 3600.0, 16 * 3600.0),)


def test_astronaut_requires_work_schedule_and_disjoint_spans():
    with pytest.raises(ValidationError, match="horario de trabajo"):
        Astronaut.from_dict(astronaut(work=[]))
    with pytest.raises(ValidationError, match="solapados"):
        Astronaut.from_dict(astronaut(work=[["08:00", "12:00"], ["11:00", "14:00"]]))
    with pytest.raises(ValidationError, match="invertido"):
        Astronaut.from_dict(astronaut(unavailable=[["12:00", "10:00"]]))


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError, match="Campos desconocidos"):
        Astronaut.from_dict(astronaut(qualificatons=["eva"]))
    with pytest.raises(ValidationError, match="Campos desconocidos"):
        Task.from_dict(task(importanse=3))


def test_latest_measurement():
    raw = astronaut(measurements=[
        {"parameter": "spo2", "value": 97, "measured_at": 100, "source": "oximetro"},
        {"parameter": "spo2", "value": 95, "measured_at": 200, "source": "oximetro"},
    ])
    a = Astronaut.from_dict(raw)
    assert a.latest("spo2").value == 95
    assert a.latest("grip_strength") is None  # desconocido: no se rellena


def test_measurement_validation():
    with pytest.raises(ValidationError):
        Measurement("spo2", float("nan"), 0, "x")
    with pytest.raises(ValidationError, match="confidence"):
        Measurement("spo2", 97, 0, "x", confidence=1.5)
    with pytest.raises(ValidationError, match="source"):
        Measurement("spo2", 97, 0, "")
    assert Measurement("spo2", 97, 0, "x").confidence is None  # nunca se inventa


def test_parameter_spec_validation():
    with pytest.raises(ValidationError, match="lo y hi"):
        ParameterSpec("x", "higher_better", "minmax", 24, "sleep")
    with pytest.raises(ValidationError, match="lo < hi"):
        ParameterSpec("x", "higher_better", "minmax", 24, "sleep", lo=5, hi=5)
    with pytest.raises(ValidationError, match="domain"):
        ParameterSpec("x", "higher_better", "baseline_z", 24, "mood")
    ParameterSpec("x", "range", "baseline_z", 24, "physical")


def test_requirement_validation():
    with pytest.raises(ValidationError, match="min, max"):
        Requirement("spo2")
    with pytest.raises(ValidationError, match="min <= max"):
        Requirement("spo2", min=99, max=90)
    with pytest.raises(ValidationError, match="crítico"):
        Requirement("spo2", min=90, weight=0)
    assert Requirement("spo2", min=90, weight=0, critical=True).critical


def test_task_roundtrip_and_defaults():
    t = Task.from_dict(task())
    assert t.category == "T1"
    assert (t.min_people, t.max_people) == (1, 1)
    assert t.mandatory
    again = Task.from_dict(json.loads(json.dumps(t.to_dict())))
    assert again == t


def test_task_validation():
    with pytest.raises(ValidationError, match="no cabe"):
        Task.from_dict(task(duration_min=120, earliest="08:00", latest="09:00"))
    with pytest.raises(ValidationError, match="individual es de una persona"):
        Task.from_dict(task(max_people=2))
    with pytest.raises(ValidationError, match="colectiva"):
        Task.from_dict(task(kind="collective", min_people=1, max_people=1))
    with pytest.raises(ValidationError, match="low_load"):
        Task.from_dict(task(low_load=True))
    with pytest.raises(ValidationError, match="repetidos"):
        Task.from_dict(task(requirements=[{"parameter": "spo2", "min": 90}, {"parameter": "spo2", "max": 99}]))
    with pytest.raises(ValidationError, match="más personas"):
        Task.from_dict(task(
            kind="collective", min_people=2, max_people=2,
            team_qualifications=[{"qualification": "eva", "count": 3}],
        ))


def test_team_qualification():
    eva, none = frozenset({"eva"}), frozenset()
    assert TeamQualification("eva", "all").satisfied_by([eva, eva])
    assert not TeamQualification("eva", "all").satisfied_by([eva, none])
    assert TeamQualification("eva", "at_least", 1).satisfied_by([eva, none])
    assert not TeamQualification("eva", "at_least", 2).satisfied_by([eva, none])
