"""Equipos candidatos para tareas colectivas.

Los requisitos operativos filtran: solo se forman equipos de personas
elegibles, con el tamaño pedido, que cumplen las cualificaciones de equipo y
que comparten un tramo libre suficiente.

El grafo social no interviene: Orbivia prohíbe usarlo para repartir, agrupar o
separar a la tripulación. Este módulo solo reutiliza el álgebra de intervalos
de `social_graph.intervals`, que es aritmética de tramos horarios y no contiene
datos sociales.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from social_graph.intervals import Interval, intersect

from .config import PlannerConfig
from .model import Astronaut, Task, ValidationError

_EPS = 1e-6


def is_low_load(task: Task, config: PlannerConfig) -> bool:
    """Tarea colectiva de baja carga (informativo en la salida)."""
    return (
        task.collective
        and task.low_load is not False
        and not task.demanding
        and task.intensity <= config.low_load.max_intensity + _EPS
        and config.importance.normalize(task.importance) <= config.low_load.max_importance + _EPS
    )


def common_free(free: Mapping[str, Sequence[Interval]], members: Sequence[str]) -> list[Interval]:
    common = list(free[members[0]])
    for m in members[1:]:
        common = intersect(common, free[m])
    return common


@dataclass(frozen=True)
class TeamCandidate:
    task: str
    members: tuple[str, ...]
    common_free: tuple[Interval, ...]


def candidate_teams(
    task: Task,
    eligible: Sequence[Astronaut],
    free: Mapping[str, Sequence[Interval]],
    config: PlannerConfig,
) -> list[TeamCandidate]:
    """Todos los equipos admisibles de la tarea, en orden estable.

    Con tripulaciones pequeñas se enumeran; si salen más de
    `solver.max_team_candidates` se avisa con un error en vez de truncar en
    silencio.
    """
    people = sorted(eligible, key=lambda a: a.id)
    out = []
    for size in range(task.min_people, min(task.max_people, len(people)) + 1):
        for group in combinations(people, size):
            if not all(tq.satisfied_by([a.qualifications for a in group]) for tq in task.team_qualifications):
                continue
            ids = tuple(a.id for a in group)
            shared = common_free(free, ids)
            if not any(e - s >= task.duration_s - _EPS for s, e in shared):
                continue
            out.append(TeamCandidate(task.id, ids, tuple(shared)))
            if len(out) > config.solver.max_team_candidates:
                raise ValidationError(
                    f"Tarea {task.id}: más de {config.solver.max_team_candidates} equipos posibles. "
                    "Reduce max_people o sube solver.max_team_candidates"
                )
    return out
