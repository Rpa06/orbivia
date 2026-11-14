"""Restricciones duras: quién puede hacer cada tarea y qué plan es válido.

Nada de esto tiene peso ni se relaja. Cada descarte lleva su motivo, para poder
explicar por qué alguien no recibió una tarea o por qué no hay solución.

`verify_plan` comprueba un plan completo de forma independiente del optimizador:
es la red de seguridad de los tests y de la salida.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from social_graph.intervals import Interval, complement, intersect, normalize, union

from .config import PlannerConfig
from .model import Astronaut, Task, format_clock
from .state import StateValue

# Motivos de no elegibilidad
QUALIFICATION = "qualification"
CRITICAL_UNMET = "critical_unmet"
CRITICAL_UNKNOWN = "critical_unknown"
NO_TIME = "no_time"
OVER_HOURS = "over_hours"
DEMANDING_LIMIT = "demanding_limit"

_EPS = 1e-6


@dataclass(frozen=True)
class Reason:
    code: str
    detail: str


@dataclass(frozen=True)
class Eligibility:
    astronaut: str
    task: str
    reasons: tuple[Reason, ...]
    free: tuple[Interval, ...]  # tramos libres dentro de la ventana de la tarea

    @property
    def eligible(self) -> bool:
        return not self.reasons


def free_time(astronaut: Astronaut) -> list[Interval]:
    """Horario de trabajo menos sueño y no disponibilidad."""
    busy = union(astronaut.sleep, astronaut.unavailable)
    return intersect(normalize(astronaut.work), complement(busy, (0.0, 86400.0)))


def max_hours(astronaut: Astronaut, config: PlannerConfig) -> float:
    return astronaut.max_work_h if astronaut.max_work_h is not None else config.limits.max_work_h


def _meets(natural: float, req) -> bool:
    return (req.min is None or natural >= req.min - _EPS) and (req.max is None or natural <= req.max + _EPS)


def eligibility(
    astronaut: Astronaut, task: Task, state: Mapping[str, StateValue], config: PlannerConfig
) -> Eligibility:
    reasons = []
    missing = sorted(task.qualifications - astronaut.qualifications)
    if missing:
        reasons.append(Reason(QUALIFICATION, f"le falta la cualificación {', '.join(missing)}"))

    for req in task.requirements:
        if not req.critical:
            continue
        value = state[req.parameter]
        if not value.known:
            # Un dato ausente nunca vale como sano
            reasons.append(Reason(CRITICAL_UNKNOWN, f"{req.parameter} es crítico y es desconocido ({value.status})"))
        elif not _meets(value.natural, req):
            bounds = " y ".join(
                text for text in (
                    f"≥ {req.min:g}" if req.min is not None else "",
                    f"≤ {req.max:g}" if req.max is not None else "",
                ) if text
            )
            reasons.append(Reason(CRITICAL_UNMET, f"{req.parameter} = {value.natural:.2f}, se exige {bounds}"))

    window = [(task.earliest, task.latest)]
    free = tuple(intersect(free_time(astronaut), window))
    if not any(end - start >= task.duration_s - _EPS for start, end in free):
        reasons.append(Reason(
            NO_TIME,
            f"no tiene {task.duration_min:g} min seguidos libres entre "
            f"{format_clock(task.earliest)} y {format_clock(task.latest)}",
        ))
    if task.duration_min / 60.0 > max_hours(astronaut, config) + _EPS:
        reasons.append(Reason(OVER_HOURS, "la tarea supera su máximo de horas del día"))
    if task.demanding and config.limits.max_demanding_per_day == 0:
        reasons.append(Reason(DEMANDING_LIMIT, "no se admiten tareas exigentes"))
    return Eligibility(astronaut.id, task.id, tuple(reasons), free)


# --- verificación de un plan completo -------------------------------------------


@dataclass(frozen=True)
class Assignment:
    task: str
    members: tuple[str, ...]
    start_s: float


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str


@dataclass
class _Timeline:
    spans: list[tuple[float, float, Task]] = field(default_factory=list)


def verify_plan(
    crew: Sequence[Astronaut],
    tasks: Sequence[Task],
    states: Mapping[str, Mapping[str, StateValue]],
    config: PlannerConfig,
    assignments: Sequence[Assignment],
) -> list[Violation]:
    """Todas las restricciones duras de la sección 4.8 sobre un plan dado."""
    by_id = {t.id: t for t in tasks}
    people = {a.id: a for a in crew}
    out: list[Violation] = []
    seen: dict[str, int] = defaultdict(int)
    timelines: dict[str, _Timeline] = defaultdict(_Timeline)
    resources: dict[str, list[tuple[float, float, str]]] = defaultdict(list)

    for a in assignments:
        task = by_id.get(a.task)
        if task is None:
            out.append(Violation("unknown_task", a.task))
            continue
        seen[task.id] += 1
        start, end = a.start_s, a.start_s + task.duration_s
        if len(set(a.members)) != len(a.members):
            out.append(Violation("team_size", f"{task.id}: miembros repetidos"))
        if not task.min_people <= len(a.members) <= task.max_people:
            out.append(Violation("team_size", f"{task.id}: {len(a.members)} personas fuera de [{task.min_people}, {task.max_people}]"))
        if start < task.earliest - _EPS or end > task.latest + _EPS:
            out.append(Violation("window", f"{task.id}: fuera de su ventana"))
        members = [people[m] for m in a.members if m in people]
        for m in a.members:
            if m not in people:
                out.append(Violation("unknown_astronaut", f"{task.id}: {m}"))
        for tq in task.team_qualifications:
            if not tq.satisfied_by([p.qualifications for p in members]):
                out.append(Violation("team_qualification", f"{task.id}: no cumple {tq.qualification} ({tq.mode})"))
        for person in members:
            check = eligibility(person, task, states[person.id], config)
            for reason in check.reasons:
                if reason.code != NO_TIME:  # el tiempo se comprueba con el inicio real
                    out.append(Violation(reason.code, f"{task.id}/{person.id}: {reason.detail}"))
            if not any(s <= start + _EPS and end <= e + _EPS for s, e in free_time(person)):
                out.append(Violation("availability", f"{task.id}/{person.id}: no está libre de {format_clock(start)} a {format_clock(end)}"))
            timelines[person.id].spans.append((start, end, task))
        for resource in task.resources:
            resources[resource].append((start, end, task.id))

    for task in tasks:
        if task.mandatory and seen[task.id] == 0:
            out.append(Violation("coverage", f"{task.id}: obligatoria y sin asignar"))
        if seen[task.id] > 1:
            out.append(Violation("coverage", f"{task.id}: asignada {seen[task.id]} veces"))

    rest_s = config.limits.rest_after_demanding_min * 60.0
    for person_id, timeline in timelines.items():
        spans = sorted(timeline.spans, key=lambda s: s[0])
        hours = sum(t.duration_min for _, _, t in spans) / 60.0
        if hours > max_hours(people[person_id], config) + _EPS:
            out.append(Violation("max_hours", f"{person_id}: {hours:.2f} h asignadas"))
        demanding = sum(t.demanding for _, _, t in spans)
        if demanding > config.limits.max_demanding_per_day:
            out.append(Violation("max_demanding", f"{person_id}: {demanding} tareas exigentes"))
        for (s1, e1, t1), (s2, _, t2) in zip(spans, spans[1:]):
            if s2 < e1 - _EPS:
                out.append(Violation("overlap", f"{person_id}: {t1.id} y {t2.id} se solapan"))
            elif t1.demanding and s2 - e1 < rest_s - _EPS:
                out.append(Violation("rest", f"{person_id}: sin descanso suficiente tras {t1.id}"))

    for resource, uses in resources.items():
        uses.sort()
        for (s1, e1, t1), (s2, _, t2) in zip(uses, uses[1:]):
            if s2 < e1 - _EPS:
                out.append(Violation("resource", f"{resource}: {t1} y {t2} se solapan"))
    return out
