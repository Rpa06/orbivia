"""Diagnóstico cuando no existe una planificación factible (diseño, sección 5.4).

1. Comprobación previa, sin optimizador: tareas obligatorias que nadie puede
   hacer, con el motivo de cada descarte.
2. Núcleo de conflicto: cada tarea obligatoria y los límites de cada persona se
   activan con un supuesto; CP-SAT devuelve un subconjunto que ya es infactible
   y se reduce quitando elementos uno a uno hasta que sea mínimo.

El sistema nunca relaja una restricción. Solo propone decisiones que no tocan
la seguridad (aplazar una tarea, ampliar su ventana) para que las tome una persona.
"""

from typing import Any

from ortools.sat.python import cp_model

from .context import PlanningContext
from .eligibility import NO_TIME
from .model import format_clock
from .optimizer import PlanModel

Document = dict[str, Any]


def _window(task) -> str:
    return f"{format_clock(task.earliest)}–{format_clock(task.latest)}"


def uncoverable(ctx: PlanningContext, model: PlanModel) -> list[Document]:
    """Tareas obligatorias sin ninguna opción posible, con su explicación."""
    out = []
    for task in ctx.problem.tasks:
        if not task.mandatory or model.task_keys[task.id]:
            continue
        eligible = ctx.eligible(task.id)
        discarded = [
            {"astronaut": a.id, "reasons": [r.detail for r in ctx.eligibility[(a.id, task.id)].reasons]}
            for a in ctx.problem.crew if a.id not in eligible
        ]
        if not eligible:
            summary = "nadie de la tripulación cumple las restricciones de la tarea"
        elif task.collective and len(eligible) < task.min_people:
            summary = f"pide al menos {task.min_people} personas y solo {len(eligible)} son elegibles"
        elif task.collective and ctx.options[task.id] == []:
            summary = (
                "con las personas elegibles no se puede formar un equipo que cumpla las "
                "cualificaciones de equipo y comparta un tramo libre suficiente"
            )
        else:
            summary = "ningún inicio cabe en los tramos libres con la resolución de la planificación"
        suggestions = [f"aplazar {task.id} a otro día"]
        if any(r.code == NO_TIME for a in ctx.problem.crew for r in ctx.eligibility[(a.id, task.id)].reasons):
            suggestions.append(f"ampliar la ventana de {task.id} ({_window(task)})")
        out.append({
            "kind": "no_candidates",
            "tasks": [task.id],
            "summary": f"{task.id}: {summary}",
            "eligible": eligible,
            "discarded": discarded,
            "suggestions": suggestions,
        })
    return out


def _infeasible(model: PlanModel, literals: list) -> bool:
    model.model.clear_assumptions()
    model.model.add_assumptions(literals)
    solver = model.solver(workers=1)  # la extracción de núcleos necesita un solo hilo
    return solver.solve(model.model) == cp_model.INFEASIBLE


def conflict_core(ctx: PlanningContext) -> list[Document]:
    """Conjunto mínimo de tareas obligatorias y límites que no pueden cumplirse a la vez."""
    model = PlanModel(ctx, coverage_assumptions=True)
    model.model.clear_objective()
    named = {lit.index: ("task", t) for t, lit in model.coverage_literals.items()}
    named.update({lit.index: ("limits", a) for a, lit in model.limit_literals.items()})
    literals = list(model.coverage_literals.values()) + list(model.limit_literals.values())

    model.model.add_assumptions(literals)
    solver = model.solver(workers=1)
    if solver.solve(model.model) != cp_model.INFEASIBLE:
        return []
    core_idx = set(solver.sufficient_assumptions_for_infeasibility())
    core = [lit for lit in literals if lit.index in core_idx] or literals

    # Reducción por eliminación: lo que queda es mínimo (quitar cualquiera lo hace factible)
    for lit in list(core):
        trial = [x for x in core if x is not lit]
        if trial and _infeasible(model, trial):
            core = trial

    tasks = [named[l.index][1] for l in core if named[l.index][0] == "task"]
    people = [named[l.index][1] for l in core if named[l.index][0] == "limits"]
    details = []
    for t in tasks:
        task = ctx.problem.task(t)
        details.append({
            "task": t,
            "window": _window(task),
            "duration_min": task.duration_min,
            "people": task.min_people,
            "eligible": ctx.eligible(t),
            "resources": sorted(task.resources),
        })
    parts = [f"las tareas obligatorias {', '.join(tasks)} no caben a la vez"]
    if people:
        parts.append(f"con los límites de horas y de tareas exigentes de {', '.join(people)}")
    else:
        parts.append("con los horarios, el descanso y los recursos de las personas elegibles")
    suggestions = [f"aplazar {t} a otro día" for t in tasks]
    suggestions += [f"ampliar la ventana de {t}" for t in tasks]
    return [{
        "kind": "conflict",
        "tasks": tasks,
        "limits_of": people,
        "summary": " ".join(parts),
        "details": details,
        "suggestions": suggestions,
    }]
