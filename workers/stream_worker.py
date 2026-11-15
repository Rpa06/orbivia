"""worker-stream: consumidor de Redis Streams de sueño y colapso diario programado.

- Hilo principal: el procesador de sueño (`sleep_stream.worker`), sin cambios.
- Hilo secundario: cada mañana (DAILY_COLLAPSE_HOUR, hora UTC) ejecuta el colapso
  diario y genera los tres planes si todavía no existen para ese día. El mismo
  trabajo se puede lanzar a mano con POST /api/v1/ops/trigger-daily-collapse.

Usa el rol de base de datos `orbivia_engine`, sin acceso a private_cycle.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date, datetime, timezone

import psycopg
import redis

from motor import pipeline
from sleep_stream import worker as sleep_worker

logger = logging.getLogger("worker-stream.daily")


def _today() -> date:
    raw = os.environ.get("ORBIVIA_TODAY")
    return date.fromisoformat(raw) if raw else datetime.now(timezone.utc).date()


def _connect() -> psycopg.Connection:
    return psycopg.connect(host=os.environ.get("POSTGRES_HOST", "db"),
                           port=int(os.environ.get("POSTGRES_PORT", "5432")),
                           dbname=os.environ.get("POSTGRES_DB", "orbivia"),
                           user=os.environ.get("ORBIVIA_DB_ENGINE_USER", "orbivia_engine"),
                           password=os.environ["ORBIVIA_DB_ENGINE_PASSWORD"], connect_timeout=5)


def daily_loop() -> None:
    hour = int(os.environ.get("DAILY_COLLAPSE_HOUR", "6"))
    interval = float(os.environ.get("DAILY_COLLAPSE_CHECK_S", "300"))
    cache = redis.Redis(host=os.environ.get("REDIS_HOST", "broker"), port=int(os.environ.get("REDIS_PORT", "6379")),
                        socket_connect_timeout=3, socket_timeout=5)
    while True:
        try:
            day = _today()
            if datetime.now(timezone.utc).hour >= hour:
                with _connect() as conn:
                    has_mission = conn.execute("SELECT 1 FROM operations.mission WHERE id = 1").fetchone()
                    done = conn.execute("SELECT 1 FROM operations.plan_runs WHERE plan_date = %s", (day,)).fetchone()
                if has_mission and not done:
                    with _connect() as conn:
                        summary = pipeline.run_daily_collapse(conn, day, cache)
                    with _connect() as conn:
                        plans = pipeline.generate_plans(conn, day)
                    logger.info("Colapso diario %s: %d astronautas; planes %s", day,
                                len(summary["astronauts"]), plans.get("status"))
        except Exception:
            logger.exception("Colapso diario no ejecutado; se reintentará")
        time.sleep(interval)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if os.environ.get("DAILY_COLLAPSE_ENABLED", "true").lower() in ("1", "true", "yes"):
        threading.Thread(target=daily_loop, name="daily-collapse", daemon=True).start()
    sleep_worker.main()


if __name__ == "__main__":
    main()
