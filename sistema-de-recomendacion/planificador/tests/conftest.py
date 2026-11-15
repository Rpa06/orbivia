"""Constructores de datos de prueba en el formato JSON de entrada."""

import pytest

from crew_planner.config import load_config

H = 3600.0
DAY = 86400.0


def astronaut(id_: str = "A1", **overrides) -> dict:
    raw = {
        "id": id_,
        "qualifications": ["eva"],
        "work": [["08:00", "16:00"]],
        "sleep": [["00:00", "06:00"], ["22:00", "24:00"]],
        "measurements": [
            {"parameter": "sleep_duration_h", "value": 7.5, "measured_at": 10 * DAY - 2 * H, "source": "watch"},
        ],
        "baselines": [{"parameter": "pvt_lapses", "mean": 2.0, "sd": 1.0}],
    }
    raw.update(overrides)
    return raw


def task(id_: str = "T1", **overrides) -> dict:
    raw = {
        "id": id_,
        "name": "Mantenimiento",
        "kind": "individual",
        "importance": 3,
        "duration_min": 60,
        "earliest": "08:00",
        "latest": "16:00",
        "requirements": [{"parameter": "sleep_duration_h", "min": 6}],
    }
    raw.update(overrides)
    return raw


def social_doc(day: int, crew: list[str], weights: list[list], statuses: dict | None = None,
               drop: bool = False) -> dict:
    """Documento diario mínimo con la forma que guarda el servicio social-graph."""
    statuses = statuses or {}
    return {
        "day": day,
        "crew": crew,
        "params_version": "test",
        "isolation": {
            "day": day,
            "crew": {"score": None, "drop": drop},
            "structure": {"smoothed_weights": weights},
            "astronauts": {
                a: {"status": statuses.get(a, "normal"), "signals": [], "score": None, "indicators": {}}
                for a in crew
            },
        },
    }


@pytest.fixture(scope="session")
def config():
    return load_config(env={})
