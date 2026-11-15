"""Almacén duradero. La parte de PostgreSQL solo se ejecuta si hay POSTGRES_HOST."""

import os
import uuid

import pytest

from sleep_stream.store import MemoryStore, PostgresStore

from conftest import T0, LocalRun, record


def summary_for(astronaut, session, start=T0, hr=60):
    run = LocalRun(start=start)
    run.session.astronaut_id, run.session.session_id = astronaut, session
    run.feed([record(start + k, heart_rate=hr, movement=0.02) for k in range(0, 600, 10)])
    return run.seal(start + 600)


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        yield MemoryStore(), f"ASTRO_{uuid.uuid4().hex[:8]}"
        return
    if not os.environ.get("POSTGRES_HOST"):
        pytest.skip("PostgreSQL no configurado (POSTGRES_HOST)")
    store = PostgresStore.from_env()
    astronaut = f"TEST_{uuid.uuid4().hex[:8]}"
    yield store, astronaut
    with store._connect() as connection:
        connection.execute("DELETE FROM biometrics.sleep_session_summary WHERE astronaut_id = %s", (astronaut,))


def test_summary_roundtrip(store):
    store, astronaut = store
    summary = summary_for(astronaut, "SLEEP_001")
    assert store.save_summary(summary) == summary
    assert store.get_summary(astronaut, "SLEEP_001") == summary
    assert store.get_summary(astronaut, "SLEEP_404") is None


def test_saving_twice_keeps_the_first_summary(store):
    store, astronaut = store
    first = summary_for(astronaut, "SLEEP_001", hr=60)
    other = summary_for(astronaut, "SLEEP_001", hr=80)
    store.save_summary(first)
    assert store.save_summary(other) == first
    assert store.get_summary(astronaut, "SLEEP_001") == first


def test_history_is_per_astronaut_and_chronological(store):
    store, astronaut = store
    store.save_summary(summary_for(astronaut, "SLEEP_002", start=T0 + 86400))
    store.save_summary(summary_for(astronaut, "SLEEP_001", start=T0))
    store.save_summary(summary_for(astronaut + "X", "SLEEP_009", start=T0))
    try:
        history = store.list_sessions(astronaut)
        assert [h["sleep_session_id"] for h in history] == ["SLEEP_001", "SLEEP_002"]
        assert all(h["astronaut_id"] == astronaut and h["status"] == "completed" for h in history)
        assert history[0]["sleep_summary_vector"]["mean_heart_rate"] == pytest.approx(60.0)
    finally:
        if isinstance(store, PostgresStore):
            with store._connect() as connection:
                connection.execute("DELETE FROM biometrics.sleep_session_summary WHERE astronaut_id = %s", (astronaut + "X",))
