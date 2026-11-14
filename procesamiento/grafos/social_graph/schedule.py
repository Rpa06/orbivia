"""Días de misión y horarios individuales de sueño, trabajo y ocio.

El ocio es el complemento de la unión de sueño y trabajo dentro del día. Calcularlo
por conjuntos (y no como T_día − T_sueño − T_trabajo) evita descontar dos veces
cuando sueño y trabajo se solapan o cruzan el corte del día.
"""

import math
import random
from collections.abc import Iterator, Mapping, Sequence
from typing import Protocol

from .intervals import Interval, clip, complement, total, union
from .params import DAY_S

KINDS = ("sleep", "work")


def day_index(t: float, cutoff_s: float) -> int:
    """Día de misión al que pertenece el instante t."""
    return math.floor((t - cutoff_s) / DAY_S)


def day_window(day: int, cutoff_s: float) -> Interval:
    start = day * DAY_S + cutoff_s
    return (start, start + DAY_S)


def split_by_day(start: float, end: float, cutoff_s: float) -> Iterator[tuple[int, float, float]]:
    """Parte [start, end) en tramos, uno por cada día de misión que toca."""
    while start < end:
        day = day_index(start, cutoff_s)
        piece_end = min(end, day_window(day, cutoff_s)[1])
        yield day, start, piece_end
        start = piece_end


class Schedule(Protocol):
    """Fuente de horarios. Devuelve los intervalos que tocan la ventana pedida."""

    def sleep(self, astronaut: str, window: Interval) -> list[Interval]: ...

    def work(self, astronaut: str, window: Interval) -> list[Interval]: ...


def leisure(schedule: Schedule, astronaut: str, window: Interval) -> list[Interval]:
    busy = union(schedule.sleep(astronaut, window), schedule.work(astronaut, window))
    return complement(busy, window)


def leisure_time(schedule: Schedule, astronaut: str, window: Interval) -> float:
    return total(leisure(schedule, astronaut, window))


class FixedSchedule:
    """Horario diario fijo por astronauta, con variación diaria opcional.

    `blocks[astronauta][tipo]` es una lista de (inicio, fin) en segundos desde
    medianoche. Si fin <= inicio el bloque cruza la medianoche. Con `jitter_s > 0`
    cada bloque se desplaza cada día una cantidad uniforme en ±jitter_s,
    determinista para una misma semilla.
    """

    def __init__(
        self,
        blocks: Mapping[str, Mapping[str, Sequence[tuple[float, float]]]],
        jitter_s: float = 0.0,
        seed: int = 0,
    ) -> None:
        for astronaut, kinds in blocks.items():
            unknown = set(kinds) - set(KINDS)
            if unknown:
                raise ValueError(f"Tipos de bloque desconocidos para {astronaut}: {unknown}")
        self._blocks = blocks
        self._jitter_s = jitter_s
        self._seed = seed

    @property
    def astronauts(self) -> list[str]:
        return list(self._blocks)

    def _shift(self, astronaut: str, kind: str, calendar_day: int, k: int) -> float:
        if self._jitter_s <= 0:
            return 0.0
        rng = random.Random(f"{self._seed}|{astronaut}|{kind}|{calendar_day}|{k}")
        return rng.uniform(-self._jitter_s, self._jitter_s)

    def _intervals(self, astronaut: str, kind: str, window: Interval) -> list[Interval]:
        blocks = self._blocks.get(astronaut, {}).get(kind, ())
        first = math.floor(window[0] / DAY_S) - 1
        last = math.floor(window[1] / DAY_S) + 1
        out: list[Interval] = []
        for calendar_day in range(first, last + 1):
            for k, (start, end) in enumerate(blocks):
                duration = (end - start) % DAY_S or DAY_S
                begin = calendar_day * DAY_S + start + self._shift(astronaut, kind, calendar_day, k)
                out.append((begin, begin + duration))
        return clip(out, *window)

    def sleep(self, astronaut: str, window: Interval) -> list[Interval]:
        return self._intervals(astronaut, "sleep", window)

    def work(self, astronaut: str, window: Interval) -> list[Interval]:
        return self._intervals(astronaut, "work", window)
