"""Utilidades comunes: ejecución del motor sin Redis y acceso a un Redis real.

Los tests de Redis usan la base 15 y un prefijo único por test, y al terminar
borran solo sus claves: nunca tocan los datos de un despliegue en marcha.
Si Redis no responde se omiten con un motivo claro.
"""

import os
import statistics
import uuid

import pytest

from sleep_stream.config import Settings
from sleep_stream.engine import FINALIZING, Engine, MemoryWindows
from sleep_stream.records import Rejected, parse_message

T0 = 1794672000  # inicio de sesión de los ejemplos; múltiplo de 1800


def record(ts, astronaut="ASTRO_001", session="SLEEP_001", **metrics):
    return {"astronaut_id": astronaut, "sleep_session_id": session, "timestamp": ts, "metrics": metrics}


class LocalRun:
    """Hace de backend en memoria: admite, deduplica y aplica registros."""

    def __init__(self, cfg=None, start=T0, **options):
        self.cfg = cfg or Settings()
        self.engine = Engine(self.cfg)
        start_message = parse_message({"type": "start", "astronaut_id": "ASTRO_001",
                                       "sleep_session_id": "SLEEP_001", "start_timestamp": start, **options})
        self.session = self.engine.new_session(start_message)
        self.windows = MemoryWindows()
        self.seen = set()
        self.anomalies = []

    def feed(self, records, advance_every=1):
        for count, raw in enumerate(records, 1):
            self.session.counters["received"] += 1
            try:
                message = parse_message(raw)
                position = self.engine.check(self.session, message.timestamp)
            except Rejected as error:
                self.session.reject(error.code)
                continue
            if position in self.seen:
                self.session.counters["duplicates"] += 1
                continue
            self.seen.add(position)
            self.engine.apply(self.session, self.windows, message, self.anomalies)
            if count % advance_every == 0:
                self.engine.advance(self.session, self.windows, self.anomalies)
        self.engine.advance(self.session, self.windows, self.anomalies)
        return self

    def seal(self, end_ts):
        from sleep_stream.summary import build_summary

        self.session.status = FINALIZING
        self.session.end_ts = end_ts
        timeline = self.engine.seal(self.session, self.windows, self.anomalies)
        return build_summary(self.session, timeline, self.anomalies, self.cfg)

    def window_counts(self):
        return [len(self.windows.starts(level)) for level in range(len(self.cfg.levels_s))]


def truth(records, metric):
    """Estadísticas exactas de una métrica calculadas con todos los registros."""
    values = [r["metrics"][metric] for r in records if r["metrics"].get(metric) is not None]
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "std": statistics.stdev(values),
        "min": min(values),
        "max": max(values),
    }


@pytest.fixture
def redis_client():
    import redis

    client = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"),
                         port=int(os.environ.get("REDIS_PORT", "6379")),
                         db=int(os.environ.get("SLEEP_TEST_REDIS_DB", "15")),
                         socket_connect_timeout=2)
    try:
        client.ping()
    except redis.RedisError as error:
        pytest.skip(f"Redis no disponible: {error}")
    return client


@pytest.fixture
def prefix(redis_client):
    name = f"test:sleep:{uuid.uuid4().hex[:12]}"
    yield name
    keys = list(redis_client.scan_iter(match=f"{name}:*", count=1000))
    if keys:
        redis_client.delete(*keys)
