"""Utilidades comunes: horarios de ejemplo y generación de instantáneas."""

from collections.abc import Callable, Iterable

import pytest

from social_graph.daily import DayResult, close_day
from social_graph.params import Params
from social_graph.schedule import FixedSchedule
from social_graph.tracker import InteractionTracker
from social_graph.validation import PositionSample

H = 3600.0
FAR = 100.0  # separación entre astronautas "lejos"

# Sueño 22:00–06:00 (cruza la medianoche), trabajo 08:00–16:00.
# Con el corte a las 04:00, el ocio del día es 06–08 y 16–22: 8 h.
STANDARD = {"sleep": [(22 * H, 6 * H)], "work": [(8 * H, 16 * H)]}


def standard_schedule(crew: Iterable[str]) -> FixedSchedule:
    return FixedSchedule({a: STANDARD for a in crew})


def apart(crew: Iterable[str]) -> dict[str, tuple[float, float, float]]:
    """Todos lejos de todos."""
    return {a: (k * FAR, 0.0, 0.0) for k, a in enumerate(crew)}


def together(base: dict, group: Iterable[str], gap: float = 1.0) -> dict:
    """Coloca al grupo en fila, separados `gap` metros, lejos del resto."""
    out = dict(base)
    for k, a in enumerate(group):
        out[a] = (-1000.0 + k * gap, 0.0, 0.0)
    return out


def feed(
    tracker: InteractionTracker,
    start: float,
    end: float,
    period: float,
    positions_at: Callable[[float], dict],
) -> None:
    """Envía instantáneas en [start, end) cada `period` segundos."""
    k = 0
    while start + k * period < end:
        t = start + k * period
        tracker.add_sample(PositionSample(t=t, positions=positions_at(t)))
        k += 1


def run_day(
    crew: list[str],
    schedule,
    positions_at: Callable[[float], dict],
    params: Params | None = None,
    period: float = 30.0,
    day: int = 0,
) -> DayResult:
    """Simula un día completo de misión y lo cierra."""
    params = params or Params()
    tracker = InteractionTracker(crew, schedule, params)
    start = day * 86400.0 + params.day_cutoff_s
    feed(tracker, start, start + 86400.0 + period, period, positions_at)
    return close_day(day, crew, tracker.pop_day(day), schedule, params)


@pytest.fixture
def crew() -> list[str]:
    return ["A", "B", "C"]
