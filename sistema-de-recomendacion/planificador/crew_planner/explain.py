"""Salida explicable del plan (diseño, sección 8).

Cada asignación lleva su desglose de coste, qué se cumple, qué datos faltan, las
alternativas más cercanas y los motivos de cada descarte. Hay dos textos:

- `justification`, para personal autorizado en Tierra, con cifras;
- `crew_text`, neutro: tarea, personas y horario, sin indicadores ni motivos.

Los costes se recalculan aquí en coma flotante con las mismas fórmulas que el
optimizador; no se leen de sus enteros escalados.
"""

from collections import defaultdict
from typing import Any

from .context import Option, PlanningContext
from .costs import equity_cost
from .model import Task, format_clock
from .optimizer import Chosen, Solution

Document = dict[str, Any]


def _round(x: float | None, digits: int = 4) -> float | None:
    return None if x is None else round(x, digits)


def _names(items) -> str:
    items = list(items)
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def _parameters(ctx: PlanningContext, astronaut: str, task: Task) -> list[Document]:
    fit = ctx.costs[(astronaut, task.id)].adequacy
    reqs = {r.parameter: r for r in task.requirements}
    return [
        {
            "parameter": p.parameter,
            "status": p.status,
            "value": _round(p.natural),
            "min": reqs[p.parameter].min,
            "max": reqs[p.parameter].max,
            "critical": reqs[p.parameter].critical,
            "weight": _round(p.weight),
            "deficit": _round(p.deficit),
        }
        for p in fit.parameters
    ]


def _member(ctx: PlanningContext, astronaut: str, task: Task) -> Document:
    cost = ctx.costs[(astronaut, task.id)]
    return {
        "astronaut": astronaut,
        "adequacy": _round(1 - cost.adequacy.distance),
        "distance": _round(cost.adequacy.distance),
        "uncertainty": _round(cost.adequacy.uncertainty),
        "unknown_parameters": cost.adequacy.unknown,
        "repetition_recent": _round(cost.repetition_raw),
        "cost": {
            "state": _round(cost.state),
            "repetition": _round(cost.repetition),
            "uncertainty": _round(cost.uncertainty),
            "total": _round(cost.total),
        },
        "parameters": _parameters(ctx, astronaut, task),
    }


def _not_eligible(ctx: PlanningContext, task: Task) -> list[Document]:
    return [
        {"astronaut": a.id, "reasons": [r.detail for r in ctx.eligibility[(a.id, task.id)].reasons]}
        for a in ctx.problem.crew if not ctx.eligibility[(a.id, task.id)].eligible
    ]


def _alternatives(ctx: PlanningContext, chosen: Option, limit: int = 2) -> list[Document]:
    others = sorted(
        (o for o in ctx.options[chosen.task] if o.members != chosen.members),
        key=lambda o: (o.operational, o.members),
    )[:limit]
    return [
        {"members": list(o.members), "cost": _round(o.operational),
         "delta": _round(o.operational - chosen.operational)}
        for o in others
    ]


def _individual(ctx: PlanningContext, c: Chosen) -> Document:
    task = ctx.problem.task(c.option.task)
    astronaut = c.option.members[0]
    member = _member(ctx, astronaut, task)
    start, end = format_clock(c.start_s), format_clock(c.start_s + task.duration_s)
    alternatives = _alternatives(ctx, c.option)

    parts = [f"{astronaut} realiza {task.name} de {start} a {end}."]
    parts.append(
        f"Cumple las cualificaciones exigidas ({_names(sorted(task.qualifications))})."
        if task.qualifications else "La tarea no exige cualificaciones."
    )
    short = [p["parameter"] for p in member["parameters"] if p["deficit"]]
    parts.append(
        f"Adecuación al perfil de la tarea: {member['adequacy']:.0%}"
        + (f", con déficit en {_names(short)}." if short else ", sin déficit en ningún requisito.")
    )
    if member["unknown_parameters"]:
        parts.append(f"Datos desconocidos (penalizados, no supuestos): {_names(member['unknown_parameters'])}.")
    if member["repetition_recent"]:
        parts.append(f"Repetición reciente de esta actividad: {member['repetition_recent']:.0%}.")
    if alternatives:
        alt = alternatives[0]
        if alt["delta"] < 0:
            parts.append(
                f"{_names(alt['members'])} tenía menor coste individual ({alt['delta']:+.3f}); se eligió "
                "esta opción por horarios, descansos o reparto de carga."
            )
        else:
            parts.append(f"Siguiente opción: {_names(alt['members'])} (+{alt['delta']:.3f} de coste).")
    else:
        parts.append("Es la única persona elegible.")

    return {
        "task": task.id,
        "name": task.name,
        "astronaut": astronaut,
        "start": start,
        "end": end,
        "mandatory": task.mandatory,
        "qualifications": sorted(task.qualifications),
        **{k: member[k] for k in ("adequacy", "distance", "uncertainty", "unknown_parameters",
                                    "repetition_recent", "cost", "parameters")},
        "alternatives": alternatives,
        "not_eligible": _not_eligible(ctx, task),
        "justification": " ".join(parts),
        "crew_text": f"{task.name}: {astronaut}, {start}–{end}.",
    }


def _collective(ctx: PlanningContext, c: Chosen) -> Document:
    task = ctx.problem.task(c.option.task)
    o = c.option
    start, end = format_clock(c.start_s), format_clock(c.start_s + task.duration_s)
    members = [_member(ctx, a, task) for a in o.members]
    alternatives = _alternatives(ctx, o)

    parts = [f"{_names(o.members)} realizan {task.name} de {start} a {end}."]
    if task.team_qualifications:
        parts.append("El equipo cumple las cualificaciones de equipo exigidas.")
    parts.append(f"Adecuación media de los miembros: {sum(m['adequacy'] for m in members) / len(members):.0%}.")
    unknown = [f"{m['astronaut']} ({_names(m['unknown_parameters'])})" for m in members if m["unknown_parameters"]]
    if unknown:
        parts.append(f"Datos desconocidos (penalizados, no supuestos): {'; '.join(unknown)}.")
    if alternatives:
        alt = alternatives[0]
        word = "menor" if alt["delta"] < 0 else "mayor"
        parts.append(f"Siguiente equipo: {_names(alt['members'])} ({word} coste operativo, {alt['delta']:+.3f}).")

    return {
        "task": task.id,
        "name": task.name,
        "members": list(o.members),
        "start": start,
        "end": end,
        "mandatory": task.mandatory,
        "team_qualifications": [q.to_dict() for q in task.team_qualifications],
        "operational_adequacy": _round(sum(m["adequacy"] for m in members) / len(members)),
        "cost": {
            "individual": _round(o.individual),
            "operational": _round(o.operational),
        },
        "low_load": ctx.low_load[task.id],
        "members_detail": members,
        "alternatives": alternatives,
        "not_eligible": _not_eligible(ctx, task),
        "justification": " ".join(parts),
        # Sin indicadores de estado ni motivos: nadie queda etiquetado
        "crew_text": f"{task.name}: {_names(o.members)}, {start}–{end}.",
    }


def build_plan(ctx: PlanningContext, solution: Solution, violations: list) -> Document:
    cfg = ctx.config
    crew = [a.id for a in ctx.problem.crew]
    chosen = sorted(solution.chosen, key=lambda c: (c.start_s, c.option.task))

    load = defaultdict(float)
    hours = defaultdict(float)
    demanding = defaultdict(int)
    tasks_of = defaultdict(list)
    for c in chosen:
        task = ctx.problem.task(c.option.task)
        for a in c.option.members:
            load[a] += ctx.loads[task.id]
            hours[a] += task.duration_min / 60.0
            demanding[a] += task.demanding
            tasks_of[a].append(task.id)
    loads = {a: load[a] for a in crew}
    total = sum(loads.values())

    individual = [_individual(ctx, c) for c in chosen if not ctx.problem.task(c.option.task).collective]
    collective = [_collective(ctx, c) for c in chosen if ctx.problem.task(c.option.task).collective]

    terms = defaultdict(float)
    for c in chosen:
        task = ctx.problem.task(c.option.task)
        members = c.option.members
        for a in members:
            cost = ctx.costs[(a, task.id)]
            terms["state"] += cost.state / len(members)
            terms["repetition"] += cost.repetition / len(members)
            terms["uncertainty"] += cost.uncertainty / len(members)
    terms["equity"] = equity_cost(loads, ctx.shares, cfg, cfg.limits.max_work_h)
    terms["total"] = sum(terms[k] for k in ("state", "repetition", "uncertainty", "equity"))

    covered = {c.option.task for c in chosen}
    unknown = {
        a: sorted(p for p, v in ctx.states[a].items() if not v.known) for a in crew
    }
    assigned_u = [
        ctx.costs[(a, c.option.task)].adequacy.uncertainty for c in chosen for a in c.option.members
    ]
    return {
        "status": "ok",
        "day": ctx.problem.day,
        "config_version": cfg.version,
        "mode": cfg.stages.mode,
        "individual": individual,
        "collective": collective,
        "global": {
            "workload": {
                a: {
                    "tasks": tasks_of[a],
                    "hours": round(hours[a], 2),
                    "load": round(loads[a], 3),
                    "target_load": round(ctx.shares[a] * total, 3),
                    "share": round(ctx.shares[a], 4),
                    "capacity": round(ctx.capacity[a], 3),
                    "available_h": round(ctx.available_h[a], 2),
                    "demanding": demanding[a],
                }
                for a in crew
            },
            "covered": sorted(covered),
            "pending": [
                {"task": t.id, "mandatory": t.mandatory,
                 "reason": "aplazable y no cubierta" if ctx.options[t.id] else "nadie puede hacerla hoy"}
                for t in ctx.problem.tasks if t.id not in covered
            ],
            "unassigned": [a for a in crew if not tasks_of[a]],
            "uncertainty": {
                "unknown_parameters": unknown,
                "mean_assigned": _round(sum(assigned_u) / len(assigned_u)) if assigned_u else None,
            },
            "costs": {k: _round(v) for k, v in terms.items()},
            # El grafo social no es una entrada del planificador (prohibido por diseño)
            "social_graph_used": False,
            "solver": [
                {"stage": s.name, "status": s.status, "objective": _round(s.objective, 6),
                 "wall_time_s": round(s.wall_time_s, 3)}
                for s in solution.stages
            ],
            "proven_optimal": all(s.optimal for s in solution.stages),
            "warnings": ctx.warnings,
            "violations": [{"code": v.code, "detail": v.detail} for v in violations],
        },
    }
