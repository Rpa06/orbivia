"""Reglas de Orbivia que se aplican antes de llamar al optimizador.

1. Límites semanales de carga (NASA-STD-3001, según el README de Orbivia):
   - como máximo 60 horas de trabajo en 7 días;
   - como máximo dos jornadas de 10 horas o más en 7 días (la tercera ya es
     sobrecarga crítica).
   Se traducen a un tope de horas para el día que se planifica
   (`Astronaut.max_work_h`), que el optimizador respeta como restricción dura.

2. Solo se reparten tareas comunes y de mantenimiento. La investigación
   científica especializada (categoría `science` del catálogo) nunca se
   reasigna: queda fijada a su responsable (`Task.only_for`).

Estas funciones son deterministas y no usan el grafo social.
"""

import zlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from .model import Astronaut, Task

WEEK_MAX_H = 60.0
LONG_DAY_H = 10.0
MAX_LONG_DAYS = 2
_EPS = 1e-6

# Categorías del catálogo que la tripulación se puede repartir
REASSIGNABLE_CATEGORIES = frozenset({
    "maintenance", "logistics", "operations", "infrastructure", "safety", "exploration",
})
SPECIALIZED_CATEGORIES = frozenset({"science"})


@dataclass(frozen=True)
class WeeklyLimit:
    astronaut: str
    hours_last_6_days: float
    long_days_last_6_days: int
    max_today_h: float
    reason: str


def weekly_limit(astronaut: str, last_6_days_h: Sequence[float], daily_max_h: float) -> WeeklyLimit:
    """Horas máximas para hoy dadas las horas trabajadas en los 6 días anteriores.

    Con los 6 días anteriores y hoy se completa una ventana móvil de 7 días.
    """
    hours = [max(0.0, float(h)) for h in last_6_days_h][-6:]
    total = sum(hours)
    long_days = sum(1 for h in hours if h >= LONG_DAY_H - _EPS)
    cap = daily_max_h
    reasons = []
    remaining = WEEK_MAX_H - total
    if remaining < cap:
        cap = max(0.0, remaining)
        reasons.append(f"lleva {total:.1f} h en 6 días: le quedan {cap:.1f} h hasta las 60 h semanales")
    if long_days >= MAX_LONG_DAYS and cap >= LONG_DAY_H:
        cap = LONG_DAY_H - 0.25
        reasons.append(f"ya tiene {long_days} jornadas de 10 h o más esta semana")
    return WeeklyLimit(astronaut, round(total, 2), long_days, round(cap, 2), "; ".join(reasons))


def apply_weekly_limits(
    crew: Iterable[Astronaut], worked: Mapping[str, Sequence[float]], daily_max_h: float
) -> tuple[list[Astronaut], list[WeeklyLimit]]:
    """Devuelve la tripulación con `max_work_h` ajustado y el detalle de cada límite.

    Un astronauta que ya no puede trabajar hoy queda con 0,25 h para no romper
    la validación del modelo (max_work_h > 0); ninguna tarea dura tan poco.
    """
    out, limits = [], []
    for a in crew:
        own_max = a.max_work_h if a.max_work_h is not None else daily_max_h
        limit = weekly_limit(a.id, worked.get(a.id, ()), own_max)
        limits.append(limit)
        cap = max(limit.max_today_h, 0.25)
        out.append(replace(a, max_work_h=cap) if cap < own_max - _EPS else a)
    return out, limits


def specialist_owner(task: Mapping, crew: Mapping[str, Iterable[str]]) -> str | None:
    """Responsable fijo de una tarea especializada entre quienes tienen todas las
    cualificaciones que pide, elegido de forma estable por el id de la tarea
    (CRC32), para repartir los experimentos entre especialistas. Es una convención
    documentada de la demo: el catálogo no trae el responsable de cada experimento.
    No depende del estado del día: el responsable no cambia aunque cambie el estado."""
    needed = set(task.get("technical_requirements") or ())
    qualified = sorted(a for a in crew if needed <= set(crew[a]))
    if not qualified:
        return None
    key = str(task.get("task_id", ""))
    return qualified[zlib.crc32(key.encode()) % len(qualified)]


def lock_specialized(
    tasks: Iterable[Task], catalog_categories: Mapping[str, str], owners: Mapping[str, str]
) -> list[Task]:
    """Fija las tareas de investigación especializada a su responsable.

    `catalog_categories` va del id de tarea del catálogo a su categoría; `owners`
    del id de tarea del catálogo al responsable. Una tarea especializada sin
    responsable se excluye del reparto: nadie más puede hacerla.
    """
    out = []
    for t in tasks:
        base = t.category or t.id
        category = catalog_categories.get(base, "")
        if category in SPECIALIZED_CATEGORIES:
            owner = owners.get(base)
            if owner is None:
                continue
            if t.only_for and owner not in t.only_for:
                continue
            out.append(replace(t, only_for=frozenset({owner})))
        else:
            out.append(t)
    return out


def is_reassignable(category: str) -> bool:
    return category in REASSIGNABLE_CATEGORIES
