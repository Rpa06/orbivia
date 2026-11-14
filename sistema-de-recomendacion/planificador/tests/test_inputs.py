"""Carga de la entrada diaria y validación cruzada con la configuración."""

import json

import pytest

from conftest import DAY, H, astronaut, social_doc, task
from crew_planner.inputs import from_dict, load_input, validate
from crew_planner.model import ValidationError

W = [[None, 0.4], [0.4, None]]


def raw(**overrides) -> dict:
    data = {
        "day": 10,
        "crew": [astronaut("A1"), astronaut("A2", qualifications=[])],
        "tasks": [task("T1"), task("T2", kind="collective", min_people=2, max_people=2)],
        "history": [{"day": 9, "astronaut": "A1", "task_id": "T1", "category": "T1", "duration_min": 60}],
        "social": social_doc(9, ["A1", "A2"], W),
    }
    data.update(overrides)
    return data


def test_load_valid_input(tmp_path, config):
    path = tmp_path / "in.json"
    path.write_text(json.dumps(raw()))
    problem, warnings = load_input(path, config)
    assert problem.day == 10 and len(problem.crew) == 2 and len(problem.tasks) == 2
    assert problem.social.weight("A1", "A2") == 0.4
    assert problem.reference_s == 10 * DAY
    assert problem.astronaut("A2").qualifications == frozenset()
    assert warnings == []


def test_optional_parts(config):
    problem = from_dict(raw(history=None, social=None))
    assert len(problem.history) == 0 and problem.social is None
    assert validate(problem, config) == []


def test_unknown_parameters_are_errors(config):
    bad = raw(tasks=[task(requirements=[{"parameter": "mood", "min": 3}])])
    with pytest.raises(ValidationError, match="desconocido 'mood'"):
        validate(from_dict(bad), config)
    bad = raw(crew=[astronaut(measurements=[{"parameter": "mood", "value": 3, "measured_at": 0, "source": "x"}])])
    with pytest.raises(ValidationError, match="desconocido 'mood'"):
        validate(from_dict(bad), config)


def test_future_measurement_is_an_error(config):
    future = astronaut(measurements=[
        {"parameter": "spo2", "value": 97, "measured_at": 10 * DAY + H, "source": "x"},
    ])
    with pytest.raises(ValidationError, match="posterior"):
        validate(from_dict(raw(crew=[future])), config)
    # Con un instante de referencia posterior, la misma medición es válida
    validate(from_dict(raw(crew=[future], as_of=10 * DAY + 2 * H)), config)


def test_duplicates_and_history_from_the_future(config):
    with pytest.raises(ValidationError, match="Astronautas repetidos"):
        validate(from_dict(raw(crew=[astronaut("A1"), astronaut("A1")])), config)
    with pytest.raises(ValidationError, match="Tareas repetidas"):
        validate(from_dict(raw(tasks=[task("T1"), task("T1")])), config)
    late = [{"day": 10, "astronaut": "A1", "task_id": "T1", "category": "T1", "duration_min": 60}]
    with pytest.raises(ValidationError, match="posteriores"):
        validate(from_dict(raw(history=late)), config)


def test_importance_out_of_scale(config):
    with pytest.raises(ValidationError, match="escala"):
        validate(from_dict(raw(tasks=[task(importance=9)])), config)


def test_warnings(config):
    data = raw(
        tasks=[
            task("T1", requirements=[{"parameter": "fatigue_self", "min": 2}]),
            task("T2", kind="collective", min_people=3, max_people=3),
        ],
        social=social_doc(5, ["A1", "X1"], W),
    )
    warnings = validate(from_dict(data), config)
    text = " | ".join(warnings)
    assert "solo tiene mínimo" in text
    assert "pide 3 personas" in text
    assert "sin datos de A2" in text
    assert "no se usará" in text


def test_unknown_top_level_keys():
    with pytest.raises(ValidationError, match="Claves desconocidas"):
        from_dict(raw(tareas=[]))
    with pytest.raises(ValidationError, match="Falta 'tasks'"):
        from_dict({"day": 1, "crew": []})
