"""Simulador de posiciones de la tripulación.

Las posiciones son una función pura de (escenario, semilla, t): no hay estado
secuencial. Así un mismo instante produce siempre la misma instantánea, y el
servicio puede retomar la simulación tras un reinicio sin desviarse.

Modelo, deliberadamente simple: durante el sueño cada uno está en su litera y
durante el trabajo en su puesto. El ocio se divide en franjas; en cada franja un
astronauta decide, según su sociabilidad, ir a una zona común o quedarse solo, y
quienes van se agrupan según la afinidad del escenario.
"""

import math
import random
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .intervals import Interval
from .params import DAY_S
from .schedule import FixedSchedule, Schedule, SwitchingSchedule, day_index, day_window
from .sources import Message

Sociability = Callable[[str, int], float]  # (astronauta, día) -> prob. de ir a zona común
Affinity = Callable[[str, str, int], float]  # (a, b, día) -> tendencia a agruparse, en [0, 1]
SensorLoss = Callable[[str, int], float]  # (astronauta, día) -> prob. de perder un bloque


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    crew: tuple[str, ...]
    schedule: Schedule
    sociability: Sociability
    affinity: Affinity
    sensor_loss: SensorLoss = lambda _astronaut, _day: 0.0


def _mix(*values: int) -> int:
    """Semilla entera determinista a partir de varios enteros."""
    h = 0x9E3779B97F4A7C15
    for v in values:
        h = ((h ^ (v & 0xFFFFFFFFFFFF)) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


class PositionSimulator:
    N_AREAS = 3
    AREA_SPACING_M = 15.0
    GROUP_RADIUS_M = 0.5

    def __init__(
        self,
        scenario: Scenario,
        seed: int = 42,
        cutoff_s: float = 4 * 3600.0,
        slot_s: float = 900.0,
        loss_block_s: float = 600.0,
        noise_m: float = 0.05,
    ) -> None:
        self.scenario = scenario
        self.seed = seed
        self.cutoff_s = cutoff_s
        self.slot_s = slot_s
        self.loss_block_s = loss_block_s
        self.noise_m = noise_m
        self._index = {a: k for k, a in enumerate(scenario.crew)}
        self._busy_cache: dict[tuple[str, int], tuple[list[Interval], list[Interval]]] = {}
        self._slot_cache: dict[int, dict[str, tuple[float, float, float]]] = {}

    # --- actividad ------------------------------------------------------------

    def _busy(self, astronaut: str, day: int) -> tuple[list[Interval], list[Interval]]:
        key = (astronaut, day)
        if key not in self._busy_cache:
            if len(self._busy_cache) > 64:
                self._busy_cache.clear()
            window = day_window(day, self.cutoff_s)
            schedule = self.scenario.schedule
            self._busy_cache[key] = (
                schedule.sleep(astronaut, window),
                schedule.work(astronaut, window),
            )
        return self._busy_cache[key]

    def activity(self, astronaut: str, t: float) -> str:
        sleep, work = self._busy(astronaut, day_index(t, self.cutoff_s))
        if any(a <= t < b for a, b in sleep):
            return "sleep"
        if any(a <= t < b for a, b in work):
            return "work"
        return "leisure"

    # --- ocio -----------------------------------------------------------------

    def _slot_places(self, slot: int) -> dict[str, tuple[float, float, float]]:
        """Dónde pasaría cada astronauta esta franja si estuviera en ocio."""
        if slot in self._slot_cache:
            return self._slot_cache[slot]
        if len(self._slot_cache) > 256:
            self._slot_cache.clear()
        scenario = self.scenario
        day = day_index(slot * self.slot_s, self.cutoff_s)
        rng = random.Random(_mix(self.seed, slot))

        social = [a for a in scenario.crew if rng.random() < scenario.sociability(a, day)]
        rng.shuffle(social)
        groups: list[list[str]] = []
        for astronaut in social:
            best, best_affinity = None, -1.0
            for group in groups:
                mean = sum(scenario.affinity(astronaut, m, day) for m in group) / len(group)
                if mean > best_affinity:
                    best, best_affinity = group, mean
            if best is not None and rng.random() < best_affinity:
                best.append(astronaut)
            elif len(groups) < self.N_AREAS:
                groups.append([astronaut])
            # si no quedan zonas libres, se queda en su camarote

        places = {a: self._quarters(a) for a in scenario.crew}
        for k, group in enumerate(groups):
            for m, astronaut in enumerate(sorted(group)):
                angle = 2 * math.pi * m / len(group)
                places[astronaut] = (
                    k * self.AREA_SPACING_M + self.GROUP_RADIUS_M * math.cos(angle),
                    self.GROUP_RADIUS_M * math.sin(angle),
                    0.0,
                )
        self._slot_cache[slot] = places
        return places

    def _quarters(self, astronaut: str) -> tuple[float, float, float]:
        return (10.0 * self._index[astronaut], 20.0, 0.0)

    def _workstation(self, astronaut: str) -> tuple[float, float, float]:
        return (10.0 * self._index[astronaut], 40.0, 0.0)

    # --- instantáneas ---------------------------------------------------------

    def _is_lost(self, astronaut: str, t: float) -> bool:
        day = day_index(t, self.cutoff_s)
        probability = self.scenario.sensor_loss(astronaut, day)
        if probability <= 0:
            return False
        block = int(t // self.loss_block_s)
        return random.Random(_mix(self.seed, 7, self._index[astronaut], block)).random() < probability

    def positions(self, t: float) -> dict[str, list[float] | None]:
        slot = int(t // self.slot_s)
        out: dict[str, list[float] | None] = {}
        for astronaut in self.scenario.crew:
            if self._is_lost(astronaut, t):
                out[astronaut] = None
                continue
            activity = self.activity(astronaut, t)
            if activity == "sleep":
                place = self._quarters(astronaut)
            elif activity == "work":
                place = self._workstation(astronaut)
            else:
                place = self._slot_places(slot)[astronaut]
            rng = random.Random(_mix(self.seed, 11, self._index[astronaut], int(t * 1000)))
            out[astronaut] = [c + rng.gauss(0.0, self.noise_m) for c in place]
        return out

    def sample(self, t: float) -> dict[str, Any]:
        return {"t": t, "positions": self.positions(t)}


class SimulationSource:
    """Fuente de simulación para el servicio, con tiempo acelerado.

    `speedup` es cuántos segundos simulados pasan por segundo real; 0 o menos
    significa sin esperas (tests). Con `n_days` la simulación se detiene tras ese
    número de días y la fuente queda en pausa.
    """

    def __init__(
        self,
        simulator: PositionSimulator,
        period_s: float = 10.0,
        speedup: float = 3600.0,
        n_days: int | None = None,
        idle: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if period_s <= 0:
            raise ValueError("period_s debe ser > 0")
        self._simulator = simulator
        self._period_s = period_s
        self._speedup = speedup
        self._n_days = n_days
        self._idle = idle
        self._sleep = sleep

    def stream(self, cursor: Mapping[str, Any] | None) -> Iterator[Message | None]:
        start = self._simulator.cutoff_s
        last_t = (cursor or {}).get("t")
        # Índice de muestra entero: evita acumular error de coma flotante
        k = 0 if last_t is None else math.floor((last_t - start) / self._period_s + 1e-9) + 1
        end = None if self._n_days is None else start + self._n_days * DAY_S
        pause = self._period_s / self._speedup if self._speedup > 0 else 0.0
        while True:
            t = start + k * self._period_s
            if end is not None and t > end:
                break
            yield f"sim-{k}", self._simulator.sample(t)
            k += 1
            if pause:
                self._sleep(pause)
        while self._idle:
            self._sleep(1.0)
            yield None


# --- escenarios -----------------------------------------------------------------

H = 3600.0
BASE_SOCIABILITY = 0.6
BASE_AFFINITY = 0.7
SCHEDULE_JITTER_S = 600.0


def _blocks(crew: Sequence[str], shift_h: Mapping[str, float] | None = None,
            work_h: Mapping[str, float] | None = None) -> dict:
    """Horario estándar (sueño 22–06, trabajo 08–16), desplazable y con jornada variable."""
    shift_h, work_h = shift_h or {}, work_h or {}
    blocks = {}
    for astronaut in crew:
        s = shift_h.get(astronaut, 0.0) * H
        w = work_h.get(astronaut, 8.0) * H
        blocks[astronaut] = {
            "sleep": [((22 * H + s) % DAY_S, (6 * H + s) % DAY_S)],
            "work": [((8 * H + s) % DAY_S, (8 * H + s + w) % DAY_S)],
        }
    return blocks


def _schedule(crew: Sequence[str], seed: int, **kwargs: Any) -> FixedSchedule:
    return FixedSchedule(_blocks(crew, **kwargs), jitter_s=SCHEDULE_JITTER_S, seed=seed)


def _constant(value: float) -> Callable[..., float]:
    return lambda *_args: value


def _ramp(day: int, start_day: int, end_day: int, start: float, end: float) -> float:
    if day <= start_day:
        return start
    if day >= end_day:
        return end
    return start + (end - start) * (day - start_day) / (end_day - start_day)


def homogeneous(crew: Sequence[str], seed: int) -> Scenario:
    return Scenario(
        "homogeneous", "Tripulación homogénea: todos se relacionan por igual.",
        tuple(crew), _schedule(crew, seed), _constant(BASE_SOCIABILITY), _constant(BASE_AFFINITY),
    )


def low_integration(crew: Sequence[str], seed: int) -> Scenario:
    target = crew[-1]
    return Scenario(
        "low_integration", f"{target} está poco integrado desde el primer día.",
        tuple(crew), _schedule(crew, seed),
        lambda a, _d: 0.1 if a == target else BASE_SOCIABILITY, _constant(BASE_AFFINITY),
    )


def cliques(crew: Sequence[str], seed: int) -> Scenario:
    half = len(crew) // 2
    group = {a: (k < half) for k, a in enumerate(crew)}
    return Scenario(
        "cliques", "Dos subgrupos que casi no se mezclan.",
        tuple(crew), _schedule(crew, seed), _constant(BASE_SOCIABILITY),
        lambda a, b, _d: 0.95 if group[a] == group[b] else 0.03,
    )


def drift(crew: Sequence[str], seed: int) -> Scenario:
    target = crew[-1]
    return Scenario(
        "drift", f"{target} deriva progresivamente hacia el aislamiento (días 10 a 25).",
        tuple(crew), _schedule(crew, seed),
        lambda a, d: _ramp(d, 10, 25, BASE_SOCIABILITY, 0.03) if a == target else BASE_SOCIABILITY,
        _constant(BASE_AFFINITY),
    )


def unequal_leisure(crew: Sequence[str], seed: int) -> Scenario:
    work_h = {a: 4.0 + 7.0 * k / max(len(crew) - 1, 1) for k, a in enumerate(crew)}
    return Scenario(
        "unequal_leisure", "Jornadas de 4 a 11 h: ocios muy desiguales.",
        tuple(crew), _schedule(crew, seed, work_h=work_h),
        _constant(BASE_SOCIABILITY), _constant(BASE_AFFINITY),
    )


def shifted_schedules(crew: Sequence[str], seed: int) -> Scenario:
    half = len(crew) // 2
    shift_h = {a: 3.0 for a in crew[half:]}
    return Scenario(
        "shifted_schedules", "Dos turnos desfasados 3 h: poco ocio simultáneo entre turnos.",
        tuple(crew), _schedule(crew, seed, shift_h=shift_h),
        _constant(BASE_SOCIABILITY), _constant(BASE_AFFINITY),
    )


def schedule_change(crew: Sequence[str], seed: int, change_day: int = 12) -> Scenario:
    target = crew[-1]
    switch_t = day_window(change_day, 4 * H)[0]
    schedule = SwitchingSchedule(
        _schedule(crew, seed), _schedule(crew, seed, shift_h={target: 3.0}), switch_t
    )
    return Scenario(
        "schedule_change", f"{target} cambia de turno el día {change_day}; su conducta no cambia.",
        tuple(crew), schedule, _constant(BASE_SOCIABILITY), _constant(BASE_AFFINITY),
    )


def simultaneous(crew: Sequence[str], seed: int) -> Scenario:
    return Scenario(
        "simultaneous", "Actividades en grupo: interacciones múltiples simultáneas.",
        tuple(crew), _schedule(crew, seed), _constant(0.9), _constant(1.0),
    )


def sensor_loss(crew: Sequence[str], seed: int) -> Scenario:
    target = crew[-1]

    def loss(astronaut: str, day: int) -> float:
        if day == 15:
            return 1.0  # caída total de sensores un día entero
        if astronaut == target and 12 <= day <= 22:
            return 0.7
        return 0.02

    return Scenario(
        "sensor_loss", f"Fallos del sensor de {target} (días 12–22) y caída total el día 15.",
        tuple(crew), _schedule(crew, seed), _constant(BASE_SOCIABILITY), _constant(BASE_AFFINITY),
        loss,
    )


def crew_wide_drop(crew: Sequence[str], seed: int) -> Scenario:
    return Scenario(
        "crew_wide_drop", "Toda la tripulación reduce su vida social a la vez (días 12 a 16).",
        tuple(crew), _schedule(crew, seed),
        lambda _a, d: _ramp(d, 12, 16, BASE_SOCIABILITY, 0.2), _constant(BASE_AFFINITY),
    )


SCENARIOS: dict[str, Callable[[Sequence[str], int], Scenario]] = {
    builder.__name__: builder
    for builder in (
        homogeneous, low_integration, cliques, drift, unequal_leisure, shifted_schedules,
        schedule_change, simultaneous, sensor_loss, crew_wide_drop,
    )
}


def build_scenario(name: str, crew: Sequence[str], seed: int = 42) -> Scenario:
    if name not in SCENARIOS:
        raise ValueError(f"Escenario desconocido: {name}. Opciones: {sorted(SCENARIOS)}")
    return SCENARIOS[name](crew, seed)
