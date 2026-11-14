"""Varios planes alternativos del día, entre los que elige la tripulación con el control.

Cada plan:

- cumple las mismas restricciones duras y pasa el mismo verificador independiente;
- se optimiza con su propio enfoque (multiplicadores sobre los pesos globales);
- difiere de los planes anteriores en al menos `min_difference` asignaciones.
  Si no es posible, se reduce la diferencia exigida; si ni siquiera cabe una,
  se devuelven menos planes y se dice por qué.

La comparación entre planes usa métricas que no dependen de los pesos
(adecuación, incertidumbre, repetición, reparto, interacción), para que sea
justa con todos los enfoques.
"""

from dataclasses import replace
from statistics import mean
from typing import Any

from .config import PlanProfile, PlannerConfig
from .context import build_context
from .diagnosis import conflict_core, uncoverable
from .eligibility import Assignment, verify_plan
from .explain import build_plan
from .inputs import PlanningInput
from .optimizer import PlanModel
from .planner import PlanVerificationError, _failure

Document = dict[str, Any]
LETTERS = "ABCDEFGHIJ"


def _profile_config(config: PlannerConfig, profile: PlanProfile) -> PlannerConfig:
    return replace(config, weights=profile.apply(config.weights))


def _solve_distinct(ctx, previous: list[set[tuple[str, tuple[str, ...]]]], wanted: int):
    """Resuelve exigiendo diferir en `d` asignaciones de cada plan anterior, con d decreciente."""
    for d in range(wanted, 0, -1):
        model = PlanModel(ctx)
        for chosen in previous:
            keys = [k for k, o in model.options.items() if (o.task, o.members) in chosen]
            if keys:
                model.model.add(sum(model.z[k] for k in keys) <= len(keys) - d)
        solution = model.solve()
        if solution.feasible:
            return solution, d
    return None, 0


def _assignments(plan: Document) -> dict[str, tuple[str, ...]]:
    out = {e["task"]: (e["astronaut"],) for e in plan["individual"]}
    out.update({e["task"]: tuple(e["members"]) for e in plan["collective"]})
    return out


def _metrics(plan: Document) -> Document:
    """Métricas independientes de los pesos, para comparar planes con enfoques distintos."""
    members = [m for e in plan["individual"] for m in [e]] + [
        m for e in plan["collective"] for m in e["members_detail"]
    ]
    workload = plan["global"]["workload"]
    loads = [w["load"] for w in workload.values()]
    relative = [w["load"] / w["target_load"] for w in workload.values() if w["target_load"] > 0]
    teams = [e["interaction"]["score"] for e in plan["collective"]
             if e.get("interaction") and e["interaction"]["score"] is not None]
    return {
        "adequacy": round(mean(m["adequacy"] for m in members), 4) if members else None,
        "uncertainty": round(mean(m["uncertainty"] for m in members), 4) if members else None,
        "repetition": round(mean(m["repetition_recent"] for m in members), 4) if members else None,
        "load_spread_h": round(max(loads) - min(loads), 3) if loads else None,
        "max_load_vs_target": round(max(relative), 3) if relative else None,
        "team_interaction": round(mean(teams), 4) if teams else None,
        "inclusion": len(plan["global"]["social"]["inclusion"]),
        "covered": len(plan["global"]["covered"]),
    }


# (métrica, mejor si es más alta, diferencia mínima para destacarla, texto, formato)
_HIGHLIGHTS = (
    ("covered", True, 1, "Cubre más tareas", "{:.0f}"),
    ("adequacy", True, 0.01, "Mejor adecuación al estado de cada astronauta", "{:.0%}"),
    ("uncertainty", False, 0.01, "Menos dependencia de datos desconocidos o poco fiables", "{:.0%}"),
    ("load_spread_h", False, 0.1, "Carga más repartida entre la tripulación", "{:.2f} h de diferencia"),
    ("max_load_vs_target", False, 0.02, "Nadie queda tan por encima de su carga objetivo", "{:.0%} del objetivo como máximo"),
    ("repetition", False, 0.02, "Más rotación de actividades", "{:.0%} de repetición reciente"),
    ("team_interaction", True, 0.03, "Equipos con más interacción observada", "{:.2f}"),
    ("inclusion", True, 1, "Más oportunidades de colaboración en tareas de baja carga", "{:.0f}"),
)


def _advantages(plans: list[Document]) -> None:
    """Escribe en cada plan las métricas en las que es el mejor, con una diferencia apreciable."""
    for plan in plans:
        plan["option"]["advantages"] = []
    if len(plans) < 2:
        return
    worst_somewhere = set()
    for key, higher, margin, text, fmt in _HIGHLIGHTS:
        values = [(p["option"]["metrics"][key], i) for i, p in enumerate(plans) if p["option"]["metrics"][key] is not None]
        if len(values) < 2:
            continue
        ranked = sorted(values, key=lambda v: -v[0] if higher else v[0])
        (best, winner), (runner_up, _) = ranked[0], ranked[1]
        if abs(best - runner_up) >= margin - 1e-9:
            plans[winner]["option"]["advantages"].append(
                f"{text}: {fmt.format(best)} frente a {fmt.format(runner_up)}"
            )
        worst, loser = ranked[-1]
        if abs(worst - ranked[-2][0]) >= margin - 1e-9:
            worst_somewhere.add(loser)
    for i, plan in enumerate(plans):
        if plan["option"]["advantages"]:
            continue
        plan["option"]["advantages"].append(
            "Compromiso entre objetivos: no es el peor en ninguna de las métricas comparadas"
            if i not in worst_somewhere else
            "Sin ventaja apreciable en las métricas comparadas: ofrece un reparto distinto de personas"
        )


def _differences(base: Document, other: Document) -> list[Document]:
    a, b = _assignments(base), _assignments(other)
    out = []
    for task in sorted(set(a) | set(b)):
        if a.get(task) != b.get(task):
            out.append({"task": task, "in_A": list(a.get(task, ())), "here": list(b.get(task, ()))})
    return out


def plan_options(problem: PlanningInput, config: PlannerConfig, count: int | None = None) -> Document:
    """Hasta `count` planes alternativos (por defecto, alternatives.count)."""
    alt = config.alternatives
    count = count or alt.count
    if not 1 <= count <= len(alt.profiles):
        raise ValueError(f"Se pueden pedir entre 1 y {len(alt.profiles)} planes")

    base_ctx = build_context(problem, config)
    missing = uncoverable(base_ctx, PlanModel(base_ctx))
    if missing:
        return _failure(base_ctx, "infeasible", missing)

    plans: list[Document] = []
    chosen_sets: list[set[tuple[str, tuple[str, ...]]]] = []
    notes: list[str] = []
    for index, profile in enumerate(alt.profiles[:count]):
        ctx = build_context(problem, _profile_config(config, profile))
        solution, applied = _solve_distinct(ctx, chosen_sets, alt.min_difference)
        if solution is None:
            if not plans:
                # Ni el primer plan es factible: diagnóstico completo, como en plan_day
                stages = PlanModel(base_ctx).solve().stages
                return _failure(base_ctx, "infeasible", conflict_core(base_ctx), stages)
            notes.append(
                f"No existe un plan '{profile.label}' que difiera de los anteriores en al menos una "
                "asignación: se proponen solo los distintos."
            )
            break
        if index and applied < alt.min_difference:
            notes.append(
                f"El plan '{profile.label}' solo puede diferir en {applied} asignación(es) de los anteriores."
            )
        assignments = [Assignment(c.option.task, c.option.members, c.start_s) for c in solution.chosen]
        violations = verify_plan(problem.crew, problem.tasks, ctx.states, config, assignments)
        if violations:
            detail = "; ".join(f"{v.code}: {v.detail}" for v in violations)
            raise PlanVerificationError(f"El plan {profile.label} incumple restricciones duras: {detail}")
        plan = build_plan(ctx, solution, violations)
        plan["option"] = {
            "id": LETTERS[index],
            "profile": profile.id,
            "label": profile.label,
            "description": profile.description,
            "weights": dict(vars(ctx.config.weights)),
            "min_difference_applied": applied if index else None,
        }
        plans.append(plan)
        chosen_sets.append({(c.option.task, c.option.members) for c in solution.chosen})

    for plan in plans:
        plan["option"]["metrics"] = _metrics(plan)
    _advantages(plans)
    for plan in plans[1:]:
        plan["option"]["differences_vs_A"] = _differences(plans[0], plan)

    return {
        "status": "ok",
        "day": problem.day,
        "config_version": config.version,
        "plans": plans,
        "notes": notes,
        "decision": {
            "status": "pending",
            "note": "La tripulación, con el control de misión, elige uno de los planes o los rechaza indicando el motivo.",
        },
    }
