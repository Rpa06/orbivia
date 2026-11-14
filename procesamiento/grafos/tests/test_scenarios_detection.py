"""El detector sobre escenarios simulados de 32 días, con semilla fija.

Debe saltar con la deriva y con la baja integración, y NO con la pérdida de
datos, el cambio de horario o un descenso de toda la tripulación.
"""

import pytest

from social_graph.isolation import (
    FOLLOW_UP,
    LOW_VS_CREW,
    NO_DATA,
    NORMAL,
    NOT_EVALUABLE,
    REVIEW,
    SUSTAINED_DROP,
    WARMING_UP,
    IsolationAnalyzer,
)
from test_simulator import CREW, simulate

DAYS = 32
TARGET = "A6"
FLAGGED = (FOLLOW_UP, REVIEW)


@pytest.fixture(scope="module")
def run():
    cache: dict[str, list[dict]] = {}

    def get(name: str) -> list[dict]:
        if name not in cache:
            cache[name] = [d["isolation"] for d in simulate(name, DAYS, analyzer=IsolationAnalyzer())]
        return cache[name]

    return get


def statuses(assessments: list[dict], astronaut: str) -> list[str]:
    return [a["astronauts"][astronaut]["status"] for a in assessments]


def signals(assessments: list[dict], astronaut: str) -> set[str]:
    return {s for a in assessments for s in a["astronauts"][astronaut]["signals"]}


def test_progressive_drift_is_detected(run):
    result = run("drift")
    target = statuses(result, TARGET)
    # La deriva va del día 10 al 25: nada antes, revisión al final
    assert not set(target[:10]) & set(FLAGGED)
    assert REVIEW in target[18:]
    assert target[-5:] == [REVIEW] * 5
    assert SUSTAINED_DROP in signals(result, TARGET)
    first = next(day for day, status in enumerate(target) if status in FLAGGED)
    assert 12 <= first <= 24
    for other in CREW[:-1]:
        assert not set(statuses(result, other)) & set(FLAGGED)


def test_low_integration_from_day_one_is_detected_without_baseline(run):
    result = run("low_integration")
    target = statuses(result, TARGET)
    assert all(status in FLAGGED for status in target[7:])
    assert LOW_VS_CREW in signals(result, TARGET)
    for other in CREW[:-1]:
        assert not set(statuses(result, other)) & set(FLAGGED)


def test_sensor_loss_never_triggers(run):
    result = run("sensor_loss")
    for astronaut in CREW:
        assert not set(statuses(result, astronaut)) & set(FLAGGED)
    target = statuses(result, TARGET)
    # Los días con el sensor fallando no se evalúan; no se interpretan como aislamiento
    assert set(target[12:23]) <= {NOT_EVALUABLE, NO_DATA}
    assert all(statuses(result, a)[15] == NO_DATA for a in CREW)
    assert target[-1] == NORMAL


def test_schedule_change_never_triggers(run):
    result = run("schedule_change")
    for astronaut in CREW:
        assert not set(statuses(result, astronaut)) & set(FLAGGED)
    assert statuses(result, TARGET)[-1] == NORMAL


def test_crew_wide_drop_is_reported_for_the_crew_not_for_individuals(run):
    result = run("crew_wide_drop")
    assert not any(a["crew"]["drop"] for a in result[:12])
    assert all(a["crew"]["drop"] for a in result[-8:])
    for astronaut in CREW:
        assert REVIEW not in statuses(result, astronaut)


def test_homogeneous_crew_raises_no_review(run):
    result = run("homogeneous")
    for astronaut in CREW:
        assert REVIEW not in statuses(result, astronaut)
        assert statuses(result, astronaut)[0] == WARMING_UP
    assert not any(a["crew"]["drop"] for a in result)
