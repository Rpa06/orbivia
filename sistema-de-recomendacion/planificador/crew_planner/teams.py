"""Equipos candidatos para tareas colectivas, compatibilidad e inclusión.

- Los requisitos operativos filtran: solo se forman equipos de personas
  elegibles, con el tamaño pedido, que cumplen las cualificaciones de equipo y
  que comparten un tramo libre suficiente.
- La compatibilidad K(G) entra en el coste de todas las tareas colectivas.
- La inclusión solo cuenta en tareas colectivas de baja carga.

La información social son patrones de proximidad observados en ocio; no se
interpreta como afinidad, emoción ni capacidad de colaborar.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from statistics import median

from social_graph.intervals import Interval, intersect

from .config import PlannerConfig
from .model import Astronaut, Task, ValidationError
from .social import SocialSnapshot

_EPS = 1e-6


def is_low_load(task: Task, config: PlannerConfig) -> bool:
    """Tarea colectiva de baja carga: la única en la que cuenta la inclusión."""
    return (
        task.collective
        and task.low_load is not False
        and not task.demanding
        and task.intensity <= config.low_load.max_intensity + _EPS
        and config.importance.normalize(task.importance) <= config.low_load.max_importance + _EPS
    )


def social_active(snapshot: SocialSnapshot | None, plan_day: int, config: PlannerConfig) -> tuple[bool, str]:
    """Si se usan los objetivos sociales hoy, y por qué no si no se usan."""
    if snapshot is None:
        return False, "no hay grafo social disponible"
    if not snapshot.usable_for(plan_day, config.social):
        return False, f"el grafo social más reciente es del día {snapshot.day} y no es reciente"
    if snapshot.crew_drop:
        return False, "descenso de interacción de toda la tripulación: no se usa para formar equipos"
    return True, ""


@dataclass(frozen=True)
class Compatibility:
    score: float | None             # K(G); None si ninguna pareja es evaluable
    evaluable_pairs: int
    pairs: int
    pair_weights: tuple[tuple[str, str, float | None], ...]


def team_compatibility(members: Sequence[str], snapshot: SocialSnapshot | None) -> Compatibility:
    """K(G): media de W̄ sobre las parejas evaluables del equipo."""
    pairs = list(combinations(sorted(members), 2))
    weights = [(a, b, snapshot.weight(a, b) if snapshot else None) for a, b in pairs]
    known = [w for _, _, w in weights if w is not None]
    return Compatibility(
        score=sum(known) / len(known) if known else None,
        evaluable_pairs=len(known),
        pairs=len(pairs),
        pair_weights=tuple(weights),
    )


def reference_compatibility(snapshot: SocialSnapshot | None) -> float | None:
    """K_ref: mediana de W̄ de la tripulación."""
    known = snapshot.known_weights() if snapshot else []
    return median(known) if known else None


def compatibility_cost(
    task: Task, compat: Compatibility, k_ref: float | None, active: bool, config: PlannerConfig
) -> float:
    """C_comp = γ · I_j · (K_ref − K(G)). Neutro (0) si falta cualquier dato."""
    if not active or compat.score is None or k_ref is None:
        return 0.0
    return config.weights.gamma * config.importance.normalize(task.importance) * (k_ref - compat.score)


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


def has_anchor(members: Sequence[str], need: Mapping[str, float]) -> bool:
    """El equipo incluye a alguien sin señales: nunca solo personas señaladas."""
    return any(need.get(m, 0.0) == 0.0 for m in members)


def inclusion_members(
    task: Task, members: Sequence[str], need: Mapping[str, float], active: bool, config: PlannerConfig
) -> list[str]:
    """Quién obtendría el premio de inclusión con este equipo en esta tarea."""
    if not active or not is_low_load(task, config) or not has_anchor(members, need):
        return []
    return [m for m in members if need.get(m, 0.0) > 0]
