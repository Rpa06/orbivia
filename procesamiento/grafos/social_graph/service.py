"""Servicio vivo: consume posiciones, acumula el día, lo cierra y sobrevive a reinicios.

El reloj es el de los datos: un día se cierra cuando llega una muestra posterior
al corte, no cuando lo dice el reloj del contenedor. Eso permite acelerar la demo
y hace que el resultado sea reproducible.
"""

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from .config import params_version
from .daily import close_day
from .graph import GraphExporter
from .isolation import IsolationAnalyzer
from .params import Params
from .schedule import Schedule
from .sources import SampleSource
from .store import Document, Store
from .tracker import InteractionTracker
from .validation import parse_sample

logger = logging.getLogger(__name__)

STATE_VERSION = 1
QUALITY_KEYS = ("invalid_messages", "position_issues", "discarded_samples", "long_gaps")

DayHook = Callable[[Document], None]


class SocialGraphService:
    def __init__(
        self,
        crew: Sequence[str],
        schedule: Schedule,
        params: Params,
        source: SampleSource,
        store: Store,
        checkpoint_every_s: float = 30.0,
        max_empty_days: int = 30,
        clock: Callable[[], float] = time.monotonic,
        on_day_closed: Sequence[DayHook] = (),
        analyzer: IsolationAnalyzer | None = None,
        exporter: GraphExporter | None = None,
        history_days: int = 60,
    ) -> None:
        self.crew = list(crew)
        self.schedule = schedule
        self.params = params
        self.params_version = params_version(params)
        self.source = source
        self.store = store
        self.checkpoint_every_s = checkpoint_every_s
        self.max_empty_days = max_empty_days
        self._clock = clock
        self._hooks = list(on_day_closed)
        self._analyzer = analyzer
        self._exporter = exporter
        self._history_days = history_days
        self.tracker = InteractionTracker(self.crew, schedule, params)
        self.cursor: dict[str, Any] | None = None
        self._quality: dict[int, dict[str, int]] = {}
        self._intervals_seen = 0
        self._warned_sampling = False

    # --- estado ---------------------------------------------------------------

    def state(self) -> Document:
        return {
            "version": STATE_VERSION,
            "crew": self.crew,
            "params_version": self.params_version,
            "cursor": self.cursor,
            "tracker": self.tracker.to_state(),
            "quality": {str(day): counts for day, counts in self._quality.items()},
        }

    def restore(self) -> bool:
        """Recupera el estado del último checkpoint. Devuelve True si había uno válido."""
        state = self.store.load_checkpoint()
        if state is None:
            logger.info("Sin checkpoint previo: se empieza de cero")
            return False
        if state.get("version") != STATE_VERSION or state.get("crew") != self.crew:
            logger.warning(
                "El checkpoint no corresponde a esta tripulación o versión: se ignora"
            )
            return False
        if state.get("params_version") != self.params_version:
            logger.warning(
                "Los parámetros han cambiado desde el checkpoint (%s -> %s); "
                "el día en curso mezcla ambos",
                state.get("params_version"), self.params_version,
            )
        self.tracker = InteractionTracker.from_state(
            self.crew, self.schedule, self.params, state["tracker"]
        )
        self.cursor = state["cursor"]
        self._quality = {int(day): counts for day, counts in state["quality"].items()}
        logger.info(
            "Estado recuperado: última muestra t=%s, días abiertos %s",
            self.tracker.last_sample_t, self.tracker.open_days(),
        )
        return True

    def checkpoint(self) -> None:
        self.store.save_checkpoint(self.state())

    # --- bucle ----------------------------------------------------------------

    def run(self, should_stop: Callable[[], bool] = lambda: False) -> None:
        self.restore()
        last_checkpoint = self._clock()
        try:
            for message in self.source.stream(self.cursor):
                if message is not None:
                    self.process(*message)
                if should_stop():
                    break
                if self._clock() - last_checkpoint >= self.checkpoint_every_s:
                    self.checkpoint()
                    last_checkpoint = self._clock()
        finally:
            # También al parar con SIGTERM: el reinicio retoma donde se quedó
            self.checkpoint()

    def process(self, message_id: str, raw: Any) -> None:
        sample, issues = parse_sample(raw, self.crew)
        day = self.tracker.current_day
        if sample is None:
            self._count(day, "invalid_messages")
            logger.debug("Mensaje %s descartado: %s", message_id, issues)
            self.cursor = {"id": message_id, "t": self.tracker.last_sample_t}
            return

        previous_t = self.tracker.last_sample_t
        accepted = self.tracker.add_sample(sample)
        day = self.tracker.current_day
        if issues:
            self._count(day, "position_issues", len(issues))
        if not accepted:
            self._count(day, "discarded_samples")
        elif previous_t is not None:
            self._check_sampling(day, sample.t - previous_t)
        self.cursor = {"id": message_id, "t": self.tracker.last_sample_t}
        self._close_finished_days()

    def _count(self, day: int | None, key: str, amount: int = 1) -> None:
        if day is None:
            return
        counts = self._quality.setdefault(day, dict.fromkeys(QUALITY_KEYS, 0))
        counts[key] += amount

    def _check_sampling(self, day: int | None, dt: float) -> None:
        self._intervals_seen += 1
        if dt <= self.params.max_gap_s:
            self._warned_sampling = True  # hay intervalos válidos: no es un problema de configuración
            return
        self._count(day, "long_gaps")
        if not self._warned_sampling and self._intervals_seen >= 10:
            self._warned_sampling = True
            logger.warning(
                "Las muestras llegan más separadas (%.0f s) que el hueco máximo (%.0f s): "
                "no se observará nada. Revisa SG_MAX_GAP_S o la frecuencia de muestreo",
                dt, self.params.max_gap_s,
            )

    # --- cierre de día --------------------------------------------------------

    def _close_finished_days(self) -> None:
        current = self.tracker.current_day
        if current is None:
            return
        closed = self.tracker.closed_through
        start = closed + 1 if closed is not None else min(self.tracker.open_days(), default=current)
        if current - start > self.max_empty_days:
            logger.warning(
                "Salto de %s días sin datos: solo se cierran los últimos %s",
                current - start, self.max_empty_days,
            )
            start = current - self.max_empty_days
        for day in range(start, current):
            self._close_day(day)

    def _close_day(self, day: int) -> None:
        totals = self.tracker.pop_day(day)
        result = close_day(day, self.crew, totals, self.schedule, self.params)
        document = result.to_dict()
        document["params_version"] = self.params_version
        document["quality"].update(self._quality.pop(day, dict.fromkeys(QUALITY_KEYS, 0)))
        history: list[Document] = []
        if self._analyzer is not None or self._exporter is not None:
            history = self.store.load_days(last=self._history_days)
            history = [d for d in history if d["day"] < day and d["crew"] == self.crew]
        if self._analyzer is not None:
            document["isolation"] = self._analyzer.analyze(history + [document])[-1]
        if self._exporter is not None:
            previous = history[-1].get("graph") if history else None
            document["graph"] = self._exporter.export(document, previous)
        for hook in self._hooks:
            hook(document)
        self.store.save_day(day, document, self.state())
        logger.info(
            "Día %s cerrado: %s muestras, %s parejas evaluables",
            day, totals.n_samples, int(result.evaluable.sum() // 2),
        )
