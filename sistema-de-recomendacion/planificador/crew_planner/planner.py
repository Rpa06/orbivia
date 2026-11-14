"""Planificación de un día de principio a fin.

entrada -> contexto -> comprobación previa -> optimizador -> verificación -> salida

Un plan que no supera la verificación independiente nunca se devuelve como
válido: es un error del sistema y se lanza como tal.
"""

from typing import Any

from .config import PlannerConfig
from .context import build_context
from .diagnosis import conflict_core, uncoverable
from .eligibility import Assignment, verify_plan
from .explain import build_plan
from .inputs import PlanningInput
from .optimizer import PlanModel

Document = dict[str, Any]


class PlanVerificationError(RuntimeError):
    """El optimizador devolvió un plan que incumple una restricción dura."""


def _failure(ctx, status: str, conflicts: list[Document], stages=()) -> Document:
    return {
        "status": status,
        "day": ctx.problem.day,
        "config_version": ctx.config.version,
        "individual": [],
        "collective": [],
        "conflicts": conflicts,
        "global": {
            "warnings": ctx.warnings,
            "solver": [{"stage": s.name, "status": s.status} for s in stages],
            "note": "No se ha relajado ninguna restricción. Las sugerencias requieren una decisión humana.",
        },
    }


def plan_day(problem: PlanningInput, config: PlannerConfig) -> Document:
    ctx = build_context(problem, config)
    model = PlanModel(ctx)

    missing = uncoverable(ctx, model)
    if missing:
        return _failure(ctx, "infeasible", missing)

    solution = model.solve()
    if not solution.feasible:
        last = solution.stages[-1].status if solution.stages else ""
        if last == "INFEASIBLE":
            return _failure(ctx, "infeasible", conflict_core(ctx), solution.stages)
        # Sin respuesta en el tiempo límite: no es lo mismo que no haber solución
        return _failure(ctx, "timeout", [{
            "kind": "timeout",
            "summary": f"El optimizador no encontró solución en {config.solver.time_limit_s:g} s",
            "suggestions": ["subir solver.time_limit_s"],
        }], solution.stages)

    assignments = [Assignment(c.option.task, c.option.members, c.start_s) for c in solution.chosen]
    violations = verify_plan(problem.crew, problem.tasks, ctx.states, config, assignments)
    if violations:
        detail = "; ".join(f"{v.code}: {v.detail}" for v in violations)
        raise PlanVerificationError(f"El plan incumple restricciones duras: {detail}")
    return build_plan(ctx, solution, violations)
