"""Punto de entrada: python -m social_graph"""

import logging
import os
import signal

from .config import Settings, load_settings
from .graph import GraphExporter
from .isolation import IsolationAnalyzer
from .recommender import CollaborationRecommender
from .schedule import Schedule
from .service import SocialGraphService
from .simulator import PositionSimulator, SimulationSource, build_scenario
from .sources import RedisStreamSource, SampleSource
from .store import PostgresStore

logger = logging.getLogger("social-graph")


def build_source(settings: Settings) -> tuple[SampleSource, Schedule]:
    """Fuente de datos y horario que le corresponde."""
    if settings.source == "redis":
        import redis

        client = redis.Redis(
            host=os.environ.get("REDIS_HOST", "broker"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            socket_connect_timeout=3,
        )
        return RedisStreamSource(client, settings.stream), settings.build_schedule()

    # En simulación el horario lo define el escenario: es el que siguen los astronautas simulados
    scenario = build_scenario(settings.sim_scenario, settings.crew, settings.sim_seed)
    if settings.sim_period_s > settings.params.max_gap_s:
        logger.warning(
            "SG_SIM_SAMPLE_PERIOD_S (%.0f s) supera SG_MAX_GAP_S (%.0f s): no se observará nada",
            settings.sim_period_s, settings.params.max_gap_s,
        )
    simulator = PositionSimulator(scenario, settings.sim_seed, settings.params.day_cutoff_s)
    source = SimulationSource(
        simulator, settings.sim_period_s, settings.sim_speedup, settings.sim_days
    )
    logger.info("Escenario simulado: %s. %s", scenario.name, scenario.description)
    return source, scenario.schedule


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

    source, schedule = build_source(settings)
    service = SocialGraphService(
        crew=settings.crew,
        schedule=schedule,
        params=settings.params,
        source=source,
        store=PostgresStore.from_env(),
        checkpoint_every_s=settings.checkpoint_every_s,
        analyzer=IsolationAnalyzer(settings.isolation),
        exporter=GraphExporter(settings.output_dir, settings.layout, settings.layout_seed),
        recommender=CollaborationRecommender(settings.recommender),
    )
    logger.info(
        "Servicio iniciado: fuente=%s tripulación=%s parámetros=%s",
        settings.source, ",".join(settings.crew), service.params_version,
    )
    service.run(should_stop=lambda: stopping)
    logger.info("Servicio detenido; checkpoint guardado")


if __name__ == "__main__":
    main()
