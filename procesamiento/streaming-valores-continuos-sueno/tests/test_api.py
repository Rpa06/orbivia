"""Endpoints de sueño y puente con el planificador, sobre un Redis real."""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sleep_stream.api import get_processor, router
from sleep_stream.config import Settings
from sleep_stream.integration import planner_measurements
from sleep_stream.processor import SleepProcessor
from sleep_stream.store import MemoryStore

from conftest import T0, LocalRun, record

SESSION = "/sleep/sessions/ASTRO_001/SLEEP_001"


@pytest.fixture
def processor(redis_client, prefix):
    return SleepProcessor(redis_client, MemoryStore(),
                          replace(Settings(prefix=prefix), mission_epoch_s=float(T0 - 86400)))


@pytest.fixture
def client(processor):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_processor] = lambda: processor
    return TestClient(app)


def night(minutes=60):
    return [record(T0 + 60 * m + s, heart_rate=58 + m % 4, heart_rate_variability=70, spo2=98,
                   respiratory_rate=14, skin_temperature=33.8, movement=0.9 if m in (20, 21) else 0.02)
            for m in range(minutes) for s in range(0, 60, 10)]


def test_full_flow_through_the_api(client, processor):
    start = {"astronaut_id": "ASTRO_001", "sleep_session_id": "SLEEP_001", "start_timestamp": T0,
             "sample_period_s": 10}
    response = client.post("/sleep/sessions", json=start)
    assert response.status_code == 201 and response.json()["status"] == "active"
    assert client.post("/sleep/sessions", json=start).status_code == 201  # repetir no cambia nada
    assert client.post("/sleep/sessions", json={**start, "start_timestamp": T0 + 5}).status_code == 409

    records = night()
    assert client.post("/sleep/records", json=records[0]).json() == {"queued": 1}
    assert client.post("/sleep/records", json=records[1:]).json() == {"queued": len(records) - 1}

    processor.drain("worker")
    status = client.get(SESSION).json()
    assert status["counters"]["accepted"] == len(records)
    assert client.get(f"{SESSION}/summary").status_code == 409  # aún sin finalizar

    response = client.post(f"{SESSION}/end", json={"end_timestamp": T0 + 3600})
    assert response.status_code == 202
    processor.drain("worker")

    summary = client.get(f"{SESSION}/summary").json()
    assert summary["astronaut_id"] == "ASTRO_001" and summary["sleep_session_id"] == "SLEEP_001"
    assert summary["sleep_summary_vector"]["time_in_bed_h"] == pytest.approx(1.0)
    assert summary["sleep_summary_vector"]["measurement_completeness"] == pytest.approx(1.0)
    assert summary["session_metadata"]["processing_status"] == "completed"

    history = client.get("/sleep/astronauts/ASTRO_001/sessions").json()
    assert [(h["sleep_session_id"], h["status"]) for h in history] == [("SLEEP_001", "completed")]
    assert client.get("/sleep/astronauts/ASTRO_002/sessions").json() == []


def test_measurements_follow_the_planner_contract(client, processor):
    client.post("/sleep/sessions", json={"astronaut_id": "ASTRO_001", "sleep_session_id": "SLEEP_001",
                                         "start_timestamp": T0})
    client.post("/sleep/records", json=night())
    client.post(f"{SESSION}/end", json={"end_timestamp": T0 + 3600})
    processor.drain("worker")

    measurements = client.get(f"{SESSION}/measurements").json()
    by_parameter = {m["parameter"]: m for m in measurements}
    # Solo los parámetros de sueño del catálogo del planificador
    assert set(by_parameter) == {"sleep_duration_h", "sleep_quality"}
    for item in measurements:
        # Campos de crew_planner.model.Measurement, ni uno más
        assert set(item) == {"parameter", "value", "measured_at", "source", "confidence"}
        assert item["source"] == "sleep_stream:actigraphy"
        assert 0.0 <= item["confidence"] <= 1.0
        assert item["measured_at"] == 86400 + 3600  # segundos de misión, no epoch
    assert by_parameter["sleep_duration_h"]["value"] == pytest.approx(58 / 60)
    assert 0.0 <= by_parameter["sleep_duration_h"]["value"] <= 12.0  # rango del catálogo
    assert by_parameter["sleep_quality"]["value"] == pytest.approx(100 * 58 / 60)


def test_no_movement_data_means_no_sleep_measurements():
    run = LocalRun().feed([record(T0 + k, heart_rate=60) for k in range(0, 1800, 10)])
    assert planner_measurements(run.seal(T0 + 1800)) == []


def test_partial_movement_data_lowers_confidence():
    records = [record(T0 + 60 * m, heart_rate=60, movement=0.02) for m in range(30)]
    records += [record(T0 + 60 * m, heart_rate=60) for m in range(30, 60)]
    measurements = planner_measurements(LocalRun().feed(records).seal(T0 + 3600))
    assert {m["confidence"] for m in measurements} == {0.5}


def test_invalid_requests_are_refused_with_a_reason(client):
    client.post("/sleep/sessions", json={"astronaut_id": "ASTRO_001", "sleep_session_id": "SLEEP_001",
                                         "start_timestamp": T0})
    bad = client.post("/sleep/records", json={"astronaut_id": "ASTRO_001", "timestamp": T0, "metrics": {"x": 1}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_sleep_session_id"
    # Un lote con un registro malo no encola ninguno
    batch = [record(T0 + 1, heart_rate=60), record("mañana", heart_rate=60)]
    assert client.post("/sleep/records", json=batch).status_code == 422
    assert client.get(SESSION).json()["counters"]["received"] == 0
    assert client.post("/sleep/records", json={"type": "end", "astronaut_id": "ASTRO_001",
                                               "sleep_session_id": "SLEEP_001"}).status_code == 422
    assert client.post("/sleep/sessions", json={"astronaut_id": "ASTRO_001"}).status_code == 422
    assert client.get("/sleep/sessions/ASTRO_404/SLEEP_001").status_code == 404
    assert client.get("/sleep/sessions/ASTRO_404/SLEEP_001/summary").status_code == 404
    assert client.post("/sleep/sessions/ASTRO_404/SLEEP_001/end").status_code == 404
    assert client.get("/sleep/sessions/ASTRO:1/SLEEP_001").status_code == 422
