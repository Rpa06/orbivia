"""Punto de entrada: python -m social_graph"""

import logging
import os
import signal

from .config import load_settings
from .service import SocialGraphService
from .sources import RedisStreamSource, SampleSource
from .store import PostgresStore

logger = logging.getLogger("social-graph")


def build_source(settings) -> SampleSource:
    if settings.source == "redis":
        import redis

        client = redis.Redis(
            host=os.environ.get("REDIS_HOST", "broker"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            socket_connect_timeout=3,
        )
        return RedisStreamSource(client, settings.stream)
    raise NotImplementedError("La fuente de simulación se añade con el simulador (Fase 4)")


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = load_settings(os.environ)
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    service = SocialGraphService(
        crew=settings.crew,
        schedule=settings.build_schedule(),
        params=settings.params,
        source=build_source(settings),
        store=PostgresStore.from_env(),
        checkpoint_every_s=settings.checkpoint_every_s,
    )
    logger.info(
        "Servicio iniciado: fuente=%s tripulación=%s parámetros=%s",
        settings.source, ",".join(settings.crew), service.params_version,
    )
    service.run(should_stop=lambda: stopping)
    logger.info("Servicio detenido; checkpoint guardado")


if __name__ == "__main__":
    main()
