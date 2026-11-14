"""Servicio que consume el stream de sueño: `python -m sleep_stream.worker`.

Bucle: retomar lo que este consumidor dejó a medias, leer mensajes nuevos,
aplicarlos, finalizar las sesiones listas, reclamar lo abandonado por otros
consumidores y recortar del stream lo ya confirmado. Si Redis o PostgreSQL no
responden, espera y reintenta; nada confirmado se pierde.
"""

import logging
import os
import signal
import socket
import time
from pathlib import Path

import redis

from .config import load_settings
from .processor import SleepProcessor
from .store import MemoryStore, PostgresStore

logger = logging.getLogger("sleep_stream.worker")
RETRY_S = 5.0
MAINTENANCE_S = 10.0


def build_processor(env=os.environ) -> SleepProcessor:
    client = redis.Redis(
        host=env.get("REDIS_HOST", "broker"),
        port=int(env.get("REDIS_PORT", "6379")),
        socket_connect_timeout=3,
        socket_timeout=10,
    )
    if env.get("POSTGRES_HOST"):
        store = PostgresStore.from_env(env)
    else:
        logger.warning("Sin POSTGRES_HOST: los resúmenes solo se guardan en memoria")
        store = MemoryStore()
    return SleepProcessor(client, store, load_settings(env))


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Un nombre por contenedor: dos réplicas no deben compartir consumidor
    consumer = os.environ.get("SLEEP_CONSUMER") or socket.gethostname()
    heartbeat = os.environ.get("SLEEP_HEARTBEAT_FILE")
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    processor = None
    while not stopping:
        try:
            if processor is None:
                processor = build_processor()
                processor.ensure_group()
                logger.info("Consumidor %s preparado (configuración %s)", consumer, processor.cfg.version)
            # Tras un reinicio, primero lo que este consumidor leyó y no confirmó
            processor.process(processor.read_own_pending(consumer))
            last_maintenance = 0.0
            while not stopping:
                handled = processor.process(processor.read(consumer, processor.cfg.block_ms))
                for astronaut, session in processor.finalize_ready():
                    logger.info("Resumen disponible: %s/%s", astronaut, session)
                now = time.monotonic()
                if now - last_maintenance >= MAINTENANCE_S:
                    recovered = processor.recover(consumer)
                    trimmed = processor.trim()
                    if recovered or trimmed:
                        logger.info("Recuperados %d mensajes; recortados %d del stream", recovered, trimmed)
                    last_maintenance = now
                if heartbeat:
                    Path(heartbeat).write_text(str(time.time()), encoding="utf-8")
                if handled:
                    logger.debug("Procesados %d mensajes", handled)
        except redis.RedisError:
            logger.exception("Redis no disponible; reintento en %.0f s", RETRY_S)
            processor = None
            time.sleep(RETRY_S)
        except Exception:
            # Típicamente PostgreSQL arrancando. El estado está en Redis: se reintenta
            logger.exception("Error inesperado; reintento en %.0f s", RETRY_S)
            processor = None
            time.sleep(RETRY_S)


if __name__ == "__main__":
    main()
