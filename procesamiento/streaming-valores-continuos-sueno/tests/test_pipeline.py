"""Flujo completo sobre un Redis real: ingesta, colapso, finalización y recuperación."""

import json
import random
import threading
from dataclasses import replace

import pytest
import redis

from sleep_stream.config import Settings
from sleep_stream.processor import SessionConflict, SleepProcessor
from sleep_stream.simulate import night_records, profile_for
from sleep_stream.store import MemoryStore

from conftest import T0, record, truth

HOUR = 3600


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def make(redis_client, prefix, store):
    def factory(client=None, **overrides):
        return SleepProcessor(client or redis_client, store, replace(Settings(prefix=prefix), **overrides))

    return factory


def start(processor, astronaut="ASTRO_001", session="SLEEP_001", start_ts=T0, **options):
    return processor.start_session({"astronaut_id": astronaut, "sleep_session_id": session,
                                    "start_timestamp": start_ts, **options})


def night(astronaut="ASTRO_001", session="SLEEP_001", hours=1.0, period=2, seed=1, index=0, start_ts=T0):
    records, _ = night_records(astronaut, session, start_ts, int(hours * HOUR), period, seed=seed,
                               profile=profile_for(index))
    return records


def assert_matches_truth(summary, records):
    for metric in ("heart_rate", "heart_rate_variability", "spo2", "respiratory_rate", "skin_temperature"):
        exact, got = truth(records, metric), summary["metrics"][metric]
        assert got["valid_count"] == exact["n"], metric
        assert got["mean"] == pytest.approx(exact["mean"], rel=1e-10), metric
        assert got["std"] == pytest.approx(exact["std"], rel=1e-8), metric
        assert (got["min"], got["max"]) == (exact["min"], exact["max"]), metric
    assert summary["session_metadata"]["aggregates_consistent"] is True


# --- un astronauta --------------------------------------------------------------------


def test_one_astronaut_end_to_end(make, redis_client, store):
    processor = make()
    start(processor, sample_period_s=2)
    records = night()
    processor.submit_many(records)
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + HOUR)
    processor.drain("c1")

    summary = processor.get_summary("ASTRO_001", "SLEEP_001")
    assert_matches_truth(summary, records)
    assert summary["session_metadata"]["total_observations"] == len(records)
    assert summary["session_metadata"]["processing_status"] == "completed"
    assert store.get_summary("ASTRO_001", "SLEEP_001") == summary

    keys = processor.keys
    # Los registros originales ya no están en Redis; solo quedan los agregados finales
    assert redis_client.xlen(keys.ingest) == 0
    status = processor.status("ASTRO_001", "SLEEP_001")
    assert status["status"] == "completed"
    assert status["stored_aggregates"] == {"60": 0, "300": 0, "900": 0, "1800": 2}
    # Aviso al sistema principal, una sola vez
    notices = redis_client.xrange(keys.summaries)
    assert [(n[1][b"astronaut_id"], n[1][b"sleep_session_id"]) for n in notices] == [(b"ASTRO_001", b"SLEEP_001")]
    # El estado temporal caduca; el resumen duradero no depende de Redis
    assert 0 < redis_client.ttl(keys.session("ASTRO_001", "SLEEP_001")) <= processor.cfg.completed_ttl_s
    assert 0 < redis_client.ttl(keys.summary("ASTRO_001", "SLEEP_001")) <= processor.cfg.summary_ttl_s


def test_active_session_keeps_no_ttl_and_bounded_aggregates(make, redis_client):
    processor = make()
    start(processor)
    records = night(hours=8, period=30)
    peak = 0
    for begin in range(0, len(records), 40):
        processor.submit_many(records[begin:begin + 40])
        processor.drain("c1")
        status = processor.status("ASTRO_001", "SLEEP_001")
        peak = max(peak, sum(status["stored_aggregates"].values()))
        assert redis_client.xlen(processor.keys.ingest) == 0
    assert peak <= 60  # frente a 960 registros originales
    assert status["status"] == "active"
    assert redis_client.ttl(processor.keys.session("ASTRO_001", "SLEEP_001")) == -1


def test_summary_is_not_visible_before_completion(make):
    processor = make()
    start(processor)
    processor.submit_many(night(hours=0.2))
    processor.drain("c1")
    assert processor.get_summary("ASTRO_001", "SLEEP_001") is None
    assert processor.status("ASTRO_001", "SLEEP_001")["summary_available"] is False
    assert processor.status("ASTRO_999", "SLEEP_001") is None


# --- varios astronautas ---------------------------------------------------------------


def test_five_astronauts_concurrently_never_mix(make):
    crew = [f"ASTRO_{k + 1:03d}" for k in range(5)]
    data = {a: night(a, hours=1, period=2, seed=10 + k, index=k) for k, a in enumerate(crew)}
    stop = threading.Event()
    errors = []

    def produce(astronaut):
        try:
            processor = make()
            start(processor, astronaut)
            records = data[astronaut]
            for begin in range(0, len(records), 100):
                processor.submit_many(records[begin:begin + 100])
            processor.end_session(astronaut, "SLEEP_001", T0 + HOUR)
        except Exception as error:  # pragma: no cover - solo si el test falla
            errors.append(error)

    def consume(name):
        try:
            processor = make(batch_count=200)
            while not stop.is_set():
                processor.process(processor.read(name, block_ms=50))
                processor.finalize_ready()
        except Exception as error:  # pragma: no cover
            errors.append(error)

    consumers = [threading.Thread(target=consume, args=(f"c{k}",)) for k in range(3)]
    producers = [threading.Thread(target=produce, args=(a,)) for a in crew]
    for thread in consumers + producers:
        thread.start()
    for thread in producers:
        thread.join()
    checker = make()
    for _ in range(600):
        if all(checker.get_summary(a, "SLEEP_001") for a in crew):
            break
        stop.wait(0.05)
    stop.set()
    for thread in consumers:
        thread.join()
    assert errors == []

    means = []
    for astronaut in crew:
        summary = checker.get_summary(astronaut, "SLEEP_001")
        assert summary["astronaut_id"] == astronaut
        assert_matches_truth(summary, data[astronaut])
        assert summary["session_metadata"]["duplicates"] == 0
        means.append(summary["sleep_summary_vector"]["mean_heart_rate"])
    assert means == sorted(means) and len(set(means)) == 5  # perfiles distintos, resultados distintos


def test_sessions_end_at_different_times(make):
    processor = make()
    start(processor, "ASTRO_001")
    start(processor, "ASTRO_002")
    first, second = night("ASTRO_001", hours=1, index=0), night("ASTRO_002", hours=2, index=1)
    processor.submit_many(first)
    processor.submit_many(second[:len(second) // 2])
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + HOUR)
    processor.drain("c1")
    assert processor.get_summary("ASTRO_001", "SLEEP_001") is not None
    assert processor.status("ASTRO_002", "SLEEP_001")["status"] == "active"

    processor.submit_many(second[len(second) // 2:])
    processor.end_session("ASTRO_002", "SLEEP_001", T0 + 2 * HOUR)
    processor.drain("c1")
    assert_matches_truth(processor.get_summary("ASTRO_002", "SLEEP_001"), second)
    assert_matches_truth(processor.get_summary("ASTRO_001", "SLEEP_001"), first)


def test_two_sessions_of_the_same_astronaut_are_independent(make):
    processor = make()
    day = 86400
    one = night(session="SLEEP_001", seed=1)
    two = night(session="SLEEP_002", seed=2, index=3, start_ts=T0 + day)
    start(processor, session="SLEEP_001")
    start(processor, session="SLEEP_002", start_ts=T0 + day)
    mixed = one + two
    random.Random(5).shuffle(mixed)  # las dos sesiones entrelazadas en el stream
    processor.submit_many(mixed)
    processor.drain("c1")
    history = processor.list_sessions("ASTRO_001")
    assert [(h["sleep_session_id"], h["status"]) for h in history] == [("SLEEP_001", "active"), ("SLEEP_002", "active")]

    processor.end_session("ASTRO_001", "SLEEP_001", T0 + HOUR)
    processor.end_session("ASTRO_001", "SLEEP_002", T0 + day + HOUR)
    processor.drain("c1")
    assert_matches_truth(processor.get_summary("ASTRO_001", "SLEEP_001"), one)
    assert_matches_truth(processor.get_summary("ASTRO_001", "SLEEP_002"), two)
    history = processor.list_sessions("ASTRO_001")
    assert [(h["sleep_session_id"], h["status"]) for h in history] == [("SLEEP_001", "completed"), ("SLEEP_002", "completed")]
    assert processor.list_sessions("ASTRO_002") == []


def test_start_is_idempotent_and_conflicts_are_refused(make):
    processor = make()
    first = start(processor)
    assert start(processor)["start_timestamp"] == first["start_timestamp"]
    with pytest.raises(SessionConflict):
        start(processor, start_ts=T0 + 60)


# --- desorden y duplicados --------------------------------------------------------------


def test_out_of_order_stream_gives_the_same_summary(make):
    records = night(hours=2, period=5)
    ordered = make()
    start(ordered, session="ORDERED")
    ordered.submit_many([{**r, "sleep_session_id": "ORDERED"} for r in records])
    ordered.end_session("ASTRO_001", "ORDERED", T0 + 2 * HOUR)

    shuffled = [{**r, "sleep_session_id": "SHUFFLED"} for r in records]
    rng = random.Random(3)
    for begin in range(0, len(shuffled), 15):
        chunk = shuffled[begin:begin + 15]
        rng.shuffle(chunk)
        shuffled[begin:begin + 15] = chunk
    start(ordered, session="SHUFFLED")
    ordered.submit_many(shuffled)
    ordered.end_session("ASTRO_001", "SHUFFLED", T0 + 2 * HOUR)
    ordered.drain("c1")

    a = ordered.get_summary("ASTRO_001", "ORDERED")
    b = ordered.get_summary("ASTRO_001", "SHUFFLED")
    assert b["session_metadata"]["out_of_order"] > 0
    assert_matches_truth(b, records)
    for metric in a["metrics"]:
        assert (b["metrics"][metric]["first"], b["metrics"][metric]["last"]) == (
            a["metrics"][metric]["first"], a["metrics"][metric]["last"])


def test_duplicates_are_ignored_even_after_their_window_collapsed(make):
    processor = make()
    start(processor)
    records = night(hours=2, period=5)
    processor.submit_many(records)
    processor.drain("c1")
    # Reenvío de la primera media hora: sus ventanas de 1 min ya no existen
    again = records[:360]
    processor.submit_many(again)
    processor.submit_many(again[:50])
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + 2 * HOUR)
    processor.drain("c1")
    summary = processor.get_summary("ASTRO_001", "SLEEP_001")
    assert summary["session_metadata"]["duplicates"] == 410
    assert summary["session_metadata"]["total_observations"] == len(records)
    assert_matches_truth(summary, records)


# --- rechazos -----------------------------------------------------------------------------


def test_bad_messages_go_to_the_dead_stream_without_blocking_anyone(make, redis_client):
    processor = make()
    start(processor, "ASTRO_001")
    keys = processor.keys
    redis_client.xadd(keys.ingest, {"data": "esto no es JSON"})
    redis_client.xadd(keys.ingest, {"otro_campo": "x"})
    redis_client.xadd(keys.ingest, {"data": json.dumps(record(T0 + 5, astronaut="ASTRO_404", heart_rate=60))})
    redis_client.xadd(keys.ingest, {"data": json.dumps(record(T0 - 50, heart_rate=60))})
    redis_client.xadd(keys.ingest, {"data": json.dumps({"astronaut_id": "ASTRO_001", "timestamp": T0})})
    good = [record(T0 + k, heart_rate=60 + k % 3, movement=0.02) for k in range(100)]
    processor.submit_many(good)
    processor.drain("c1")

    reasons = sorted(entry[1][b"reason"].decode() for entry in redis_client.xrange(keys.dead))
    assert reasons == ["bad_json", "bad_json", "bad_sleep_session_id", "before_start", "unknown_session"]
    status = processor.status("ASTRO_001", "SLEEP_001")
    assert status["counters"]["accepted"] == 100
    assert status["rejections"] == {"before_start": 1}
    # Nada queda pendiente ni se pierde en silencio
    assert redis_client.xpending(keys.ingest, processor.cfg.group)["pending"] == 0


def test_records_after_completion_are_rejected_and_do_not_change_the_summary(make, redis_client):
    processor = make()
    start(processor)
    records = night(hours=0.5)
    processor.submit_many(records)
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + 1800)
    processor.drain("c1")
    before = processor.get_summary("ASTRO_001", "SLEEP_001")
    processor.submit(record(T0 + 100, heart_rate=200))
    processor.drain("c1")
    assert processor.get_summary("ASTRO_001", "SLEEP_001") == before
    last = redis_client.xrevrange(processor.keys.dead, count=1)[0][1]
    assert last[b"reason"] == b"session_closed"


# --- finalización -------------------------------------------------------------------------


def test_finalizing_twice_gives_one_result(make, redis_client, store):
    processor = make()
    start(processor)
    processor.submit_many(night(hours=0.5))
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + 1800)
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + 1700)  # señal repetida, con otro fin
    processor.drain("c1")
    first = processor.get_summary("ASTRO_001", "SLEEP_001")
    assert first["session_metadata"]["end_timestamp"] == T0 + 1800

    processor.end_session("ASTRO_001", "SLEEP_001")
    processor.drain("c1")
    assert processor.try_finalize("ASTRO_001", "SLEEP_001") == first
    assert processor.get_summary("ASTRO_001", "SLEEP_001") == first
    assert len(store.list_sessions("ASTRO_001")) == 1
    assert redis_client.xlen(processor.keys.summaries) == 1


def test_end_without_timestamp_uses_the_last_data(make):
    processor = make()
    start(processor)
    processor.submit_many([record(T0 + k, heart_rate=60, movement=0.02) for k in range(0, 900, 5)])
    processor.end_session("ASTRO_001", "SLEEP_001")
    processor.drain("c1")
    summary = processor.get_summary("ASTRO_001", "SLEEP_001")
    assert summary["session_metadata"]["end_timestamp"] == T0 + 895


def test_simultaneous_finalization_of_several_sessions(make, redis_client, store):
    crew = [f"ASTRO_{k + 1:03d}" for k in range(4)]
    setup = make()
    for k, astronaut in enumerate(crew):
        start(setup, astronaut)
        setup.submit_many(night(astronaut, hours=0.5, index=k))
        setup.end_session(astronaut, "SLEEP_001", T0 + 1800)
    for entries in iter(lambda: setup.read("c1"), []):
        setup.process(entries)
    assert redis_client.scard(setup.keys.finalizing) == 4

    barrier = threading.Barrier(6)
    errors = []

    def finalize():
        try:
            processor = make()
            barrier.wait()
            processor.finalize_ready()
        except Exception as error:  # pragma: no cover
            errors.append(error)

    threads = [threading.Thread(target=finalize) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    notices = [entry[1][b"astronaut_id"].decode() for entry in redis_client.xrange(setup.keys.summaries)]
    assert sorted(notices) == crew  # un aviso por sesión, aunque seis hilos lo intentaran
    assert redis_client.scard(setup.keys.finalizing) == 0
    assert all(len(store.list_sessions(a)) == 1 for a in crew)


def test_summary_waits_for_durable_storage(make, redis_client, store, monkeypatch):
    processor = make()
    start(processor)
    processor.submit_many(night(hours=0.5))
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + 1800)

    def down(_summary):
        raise ConnectionError("PostgreSQL no responde")

    monkeypatch.setattr(store, "save_summary", down)
    processor.drain("c1")
    keys = processor.keys
    status = processor.status("ASTRO_001", "SLEEP_001")
    assert status["status"] == "sealed" and status["summary_available"] is False
    assert processor.get_summary("ASTRO_001", "SLEEP_001") is None
    # Sin copia duradera no se pone caducidad a nada ni se avisa
    assert redis_client.ttl(keys.session("ASTRO_001", "SLEEP_001")) == -1
    assert redis_client.ttl(keys.summary("ASTRO_001", "SLEEP_001")) == -1
    assert redis_client.xlen(keys.summaries) == 0

    monkeypatch.undo()
    assert processor.finalize_ready() == [("ASTRO_001", "SLEEP_001")]
    assert processor.get_summary("ASTRO_001", "SLEEP_001") == store.get_summary("ASTRO_001", "SLEEP_001")


# --- interrupciones y recuperación ------------------------------------------------------------


def reference_summary(make, records, session="REFERENCE"):
    processor = make()
    start(processor, session=session)
    processor.submit_many([{**r, "sleep_session_id": session} for r in records])
    processor.end_session("ASTRO_001", session, T0 + HOUR)
    processor.drain("ref")
    return processor.get_summary("ASTRO_001", session)


def same_result(a, b):
    """Mismo resumen salvo el identificador de sesión."""
    return {**a, "sleep_session_id": None} == {**b, "sleep_session_id": None}


def same_statistics(a, b):
    """Mismas estadísticas y misma actigrafía, aunque los datos llegaran en otro orden."""
    for metric, stats in a["metrics"].items():
        other = b["metrics"][metric]
        for key in ("valid_count", "missing_count", "invalid_count", "min", "max", "first", "last"):
            assert other[key] == stats[key], (metric, key)
        assert other["mean"] == pytest.approx(stats["mean"], rel=1e-10)
        assert other["std"] == pytest.approx(stats["std"], rel=1e-8)
    assert a["sleep"] == b["sleep"]


def test_crashed_consumer_messages_are_reclaimed(make, redis_client):
    records, injected = night_records("ASTRO_001", "SLEEP_001", T0, HOUR, 2, seed=1)
    expected = reference_summary(make, records)

    processor = make(batch_count=60)
    start(processor)
    processor.submit_many(records[:600])
    for _ in range(4):
        processor.process(processor.read("survivor"))
    lost = processor.read("crashed")  # este consumidor lee 2 min de datos y muere sin confirmarlos
    assert len(lost) == 60
    processor.process(processor.read("survivor"))  # los demás siguen
    processor.submit_many(records[600:])
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + HOUR)
    for entries in iter(lambda: processor.read("survivor"), []):
        processor.process(entries)

    # El fin ha llegado, pero faltan los mensajes del consumidor caído: no se finaliza
    assert processor.finalize_ready() == []
    assert processor.status("ASTRO_001", "SLEEP_001")["status"] == "finalizing"
    assert processor.status("ASTRO_001", "SLEEP_001")["counters"]["accepted"] == len(records) - 60

    assert processor.recover("survivor", min_idle_ms=0) == 60
    assert processor.finalize_ready() == [("ASTRO_001", "SLEEP_001")]
    summary = processor.get_summary("ASTRO_001", "SLEEP_001")
    assert summary["session_metadata"]["total_observations"] == len(records)
    assert_matches_truth(summary, records)
    assert redis_client.xpending(processor.keys.ingest, processor.cfg.group)["pending"] == 0
    # Los picos inyectados siguen detectados
    episodes = [a for a in summary["anomalies"] if a["metric"] == "heart_rate"]
    for begin, end in injected["spikes"]:
        assert any(a["start_ts"] < end and a["end_ts"] >= begin for a in episodes)
    assert expected["session_metadata"]["total_observations"] == len(records)


def test_reclaimed_within_the_fine_window_retention_changes_nothing(make):
    """Si lo reclamado llega antes de que su minuto se colapse (15 min de datos),
    el resultado es el mismo que sin la caída, actigrafía incluida."""
    records = night()
    expected = reference_summary(make, records)

    processor = make(batch_count=60)
    start(processor)
    processor.submit_many(records)
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + HOUR)
    for _ in range(4):
        processor.process(processor.read("survivor"))
    assert len(processor.read("crashed")) == 60
    processor.process(processor.read("survivor"))  # 2 min de datos más
    assert processor.recover("survivor", min_idle_ms=0) == 60
    processor.drain("survivor")
    same_statistics(expected, processor.get_summary("ASTRO_001", "SLEEP_001"))


def test_data_reclaimed_very_late_keeps_statistics_but_not_its_minutes(make):
    """Límite documentado: lo que llega después de colapsarse su minuto cuenta en
    todas las estadísticas, pero ese minuto queda sin clasificar en la actigrafía."""
    records = night()
    processor = make(batch_count=300)
    start(processor)
    processor.submit_many(records)
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + HOUR)
    assert len(processor.read("crashed")) == 300  # los 10 primeros minutos
    for entries in iter(lambda: processor.read("survivor"), []):
        processor.process(entries)
    assert processor.recover("survivor", min_idle_ms=0) == 300
    assert processor.finalize_ready() == [("ASTRO_001", "SLEEP_001")]
    summary = processor.get_summary("ASTRO_001", "SLEEP_001")
    assert_matches_truth(summary, records)
    assert summary["session_metadata"]["late_into_coarser_window"] > 0
    assert summary["sleep"]["unknown_epochs"] == 10


class FlakyRedis:
    """Cliente que corta la conexión justo al confirmar la n-ésima transacción."""

    def __init__(self, client, fail_on):
        self._client = client
        self._fail_on = set(fail_on)
        self.transactions = 0
        self.failures = 0

    def __getattr__(self, name):
        return getattr(self._client, name)

    def pipeline(self, *args, **kwargs):
        pipe = self._client.pipeline(*args, **kwargs)
        if kwargs.get("transaction", True):
            real_execute = pipe.execute

            def execute(*a, **k):
                self.transactions += 1
                if self.transactions in self._fail_on:
                    self.failures += 1
                    pipe.reset()
                    raise redis.ConnectionError("corte de conexión simulado")
                return real_execute(*a, **k)

            pipe.execute = execute
        return pipe


def test_connection_lost_mid_transaction_loses_and_duplicates_nothing(make, redis_client):
    records = night()
    expected = reference_summary(make, records)

    flaky = FlakyRedis(redis_client, fail_on={3, 4, 9})
    processor = make(client=flaky, batch_count=250)
    start(processor)
    processor.submit_many(records)
    processor.end_session("ASTRO_001", "SLEEP_001", T0 + HOUR)

    interruptions = 0
    for _ in range(100):
        try:
            # Como el servicio: retoma lo no confirmado y sigue leyendo
            processor.process(processor.read_own_pending("c1"))
            entries = processor.read("c1")
            if not entries:
                processor.finalize_ready()
                if processor.get_summary("ASTRO_001", "SLEEP_001"):
                    break
                continue
            processor.process(entries)
        except redis.ConnectionError:
            interruptions += 1
    assert interruptions == flaky.failures == 3
    assert same_result(processor.get_summary("ASTRO_001", "SLEEP_001"), expected)


def test_processor_restart_continues_from_redis_state(make):
    records = night()
    expected = reference_summary(make, records)

    first = make(batch_count=200)
    start(first)
    first.submit_many(records[:900])
    for entries in iter(lambda: first.read("c1"), []):
        first.process(entries)
    del first  # el proceso muere; no queda nada en memoria

    second = make(batch_count=200)
    assert second.status("ASTRO_001", "SLEEP_001")["counters"]["accepted"] == 900
    second.submit_many(records[900:])
    second.end_session("ASTRO_001", "SLEEP_001", T0 + HOUR)
    second.drain("c1")
    assert same_result(second.get_summary("ASTRO_001", "SLEEP_001"), expected)


def test_redelivered_message_is_not_applied_twice(make, redis_client):
    """Aunque Redis reentregue un mensaje ya aplicado, el mapa de duplicados lo frena."""
    processor = make()
    start(processor)
    records = [record(T0 + k, heart_rate=60 + k % 5, movement=0.02) for k in range(50)]
    ids = processor.submit_many(records)
    entries = processor.read("c1")
    processor.process(entries)
    processor.process(entries)  # el mismo lote otra vez
    status = processor.status("ASTRO_001", "SLEEP_001")
    assert status["counters"]["accepted"] == 50 and status["counters"]["duplicates"] == 50
    assert len(ids) == 50


def test_poison_message_is_set_aside_after_repeated_deliveries(make, redis_client, monkeypatch):
    processor = make()
    start(processor, "ASTRO_001")
    start(processor, "ASTRO_002")
    processor.submit(record(T0 + 1, astronaut="ASTRO_001", heart_rate=60))
    processor.submit(record(T0 + 1, astronaut="ASTRO_002", heart_rate=70))

    real = processor._apply_group

    def failing(astronaut, session, items, strict=False):
        if astronaut == "ASTRO_001":
            raise RuntimeError("fallo interno simulado")
        return real(astronaut, session, items, strict)

    monkeypatch.setattr(processor, "_apply_group", failing)
    processor.process(processor.read("c1"))
    # El otro astronauta no se ve afectado
    assert processor.status("ASTRO_002", "SLEEP_001")["counters"]["accepted"] == 1
    for _ in range(6):
        processor.recover("c1", min_idle_ms=0)
    dead = redis_client.xrange(processor.keys.dead)
    assert [entry[1][b"reason"] for entry in dead] == [b"processing_error"]
    assert redis_client.xpending(processor.keys.ingest, processor.cfg.group)["pending"] == 0


def test_keys_of_different_sessions_never_collide(make):
    keys = make().keys
    built = {keys.session(a, s) for a, s in [("A", "B_C"), ("A_B", "C"), ("A", "B"), ("A.B", "C")]}
    assert len(built) == 4
