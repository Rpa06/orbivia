import logging
import os
import signal
import time

import redis

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(os.environ.get("WORKER_NAME", "worker"))
stopping = False


def stop_worker(_signum: int, _frame: object) -> None:
    global stopping
    stopping = True


signal.signal(signal.SIGTERM, stop_worker)
signal.signal(signal.SIGINT, stop_worker)

client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "broker"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    socket_connect_timeout=3,
    socket_timeout=3,
)

while not stopping:
    try:
        client.ping()
        logger.info("Worker preparado; la lógica de procesamiento aún no está implementada")
        while not stopping:
            time.sleep(30)
    except redis.RedisError:
        logger.exception("No se pudo conectar con Redis; se reintentará en 5 segundos")
        time.sleep(5)

