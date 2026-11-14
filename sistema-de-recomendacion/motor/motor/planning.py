"""Puente entre Orbivia y el planificador CP-SAT (`crew_planner`).

Construye la entrada del día con:
- las tareas del catálogo del entorno de la misión;
- el estado de cada astronauta (mediciones del día, sin ánimo, NLP, voz,
  personalidad, ciclo ni grafo social);
- los límites semanales (60 h, dos jornadas de 10 h) y la regla de que la
  investigación especializada no se reasigna (`crew_planner.policy`);

y devuelve tres alternativas, cada una con asignaciones, comparativa de carga,
ventajas, inconvenientes y la explicación de cada cambio respecto al plan de
referencia (el que se haría con todos en su línea base).

Interfaces preparadas para ampliar (no activas en la demo):
`best_time_slot`, `eva_pairs_by_sleep_sync` y `fatigue_projection_7d`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from crew_planner.catalog import load_catalog, planner_tasks_for_day
from crew_planner.config import PlannerConfig, load_config
from crew_planner.inputs import PlanningInput
from crew_planner.model import DAY_S, Astronaut, Baseline, Measurement
from crew_planner.options import plan_options
from crew_planner.policy import apply_weekly_limits, lock_specialized, specialist_owner

Document = dict[str, Any]
H = 3600.0

# Parámetros de estado que el planificador admite (config/default.toml) y de dónde salen.
STATE_PARAMETERS = (
    "sleep_duration_h", "sleep_quality", "pvt_lapses", "fatigue_self",
    "grip_strength", "spo2", "resting_hr", "work_hours_3d",
)
BASELINE_PARAMETERS = ("pvt_lapses", "grip_strength", "resting_hr")
FORBIDDEN_STATE = {"mood", "cohesion", "nlp", "acoustic", "social", "centrality", "cycle"}

DISADVANTAGES = (
    ("covered", False, "Cubre menos tareas aplazables"),
    ("adequacy", False, "Peor adecuación media al estado de cada astronauta"),
    ("uncertainty", True, "Depende más de datos desconocidos o poco fiables"),
    ("load_spread_h", True, "Carga menos repartida entre la tripulación"),
    ("max_load_vs_target", True, "Alguien queda más por encima de su carga objetivo"),
    ("repetition", True, "Menos rotación de actividades"),
)


def _crew(environment: str, catalog, day: int, states: Mapping[str, Mapping[str, float]],
          baselines: Mapping[str, Mapping[str, tuple[float, float]]],
          exercise: Mapping[str, Sequence[str]], source: str) -> list[Astronaut]:
    env = catalog.environments[environment]
    ref = day * DAY_S
    crew = []
    for a, quals in env["crew"].items():
        state = states.get(a, {})
        bad = {k for k in state if any(word in k for word in FORBIDDEN_STATE)}
        if bad:
            raise ValueError(f"Parámetros no admitidos en el planificador: {sorted(bad)}")
        measurements = [
            Measurement(p, float(state[p]), ref - 2 * H, source)
            for p in STATE_PARAMETERS if state.get(p) is not None
        ]
        base = [Baseline(p, m, s) for p, (m, s) in (baselines.get(a) or {}).items() if p in BASELINE_PARAMETERS]
        unavailable = []
        if exercise.get(a):
            unavailable.append(tuple(exercise[a]))
        crew.append(Astronaut.from_dict({
            "id": a, "qualifications": list(quals), "work": [env["workday"]],
            "sleep": [["00:00", "07:00"], ["23:00", "24:00"]],
            "unavailable": [list(u) for u in unavailable],
            "measurements": [m.to_dict() for m in measurements],
            "baselines": [b.to_dict() for b in base],
        }))
    return crew


def build_problem(environment: str, day: int, states, baselines, exercise, worked_last6,
                  config: PlannerConfig, source: str = "orbivia") -> tuple[PlanningInput, list[Document]]:
    catalog = load_catalog()
    crew = _crew(environment, catalog, day, states, baselines, exercise, source)
    crew, limits = apply_weekly_limits(crew, worked_last6, config.limits.max_work_h)
    tasks, _ = planner_tasks_for_day(catalog, environment, day, [a.id for a in crew])
    categories = {t["task_id"]: t["category"] for t in catalog.environment_tasks(environment)}
    quals = {a.id: a.qualifications for a in crew}
    owners = {}
    for t in catalog.environment_tasks(environment):
        if t["category"] == "science":
            owner = specialist_owner(
                {"task_id": t["task_id"],
                 "technical_requirements": t["technical_requirements"]["required_qualifications"]}, quals)
            if owner:
                owners[t["task_id"]] = owner
    tasks = lock_specialized(tasks, categories, owners)
    limits_doc = [
        {"astronaut": l.astronaut, "hours_last_6_days": l.hours_last_6_days,
         "long_days_last_6_days": l.long_days_last_6_days, "max_today_h": l.max_today_h, "reason": l.reason}
        for l in limits
    ]
    return PlanningInput(day=day, crew=tuple(crew), tasks=tuple(tasks)), limits_doc


def _assignments(plan: Document) -> dict[str, tuple[str, ...]]:
    out = {e["task"]: (e["astronaut"],) for e in plan.get("individual", [])}
    out.update({e["task"]: tuple(e["members"]) for e in plan.get("collective", [])})
    return out


def _names(plan: Document) -> dict[str, str]:
    return {e["task"]: e["name"] for e in plan.get("individual", []) + plan.get("collective", [])}


def _changes(original: Document | None, plan: Document) -> list[Document]:
    """Cambios respecto al plan de referencia, con una explicación neutra.

    La explicación no menciona valores de salud ni motivos: solo el criterio
    operativo (adecuación a los requisitos, reparto de carga o rotación)."""
    if not original:
        return []
    before, after, names = _assignments(original), _assignments(plan), _names(plan)
    entries = {e["task"]: e for e in plan.get("individual", []) + plan.get("collective", [])}
    out = []
    for task in sorted(set(before) | set(after)):
        if before.get(task) == after.get(task):
            continue
        entry = entries.get(task, {})
        why = "mejor adecuación de los requisitos de la tarea al estado operativo de hoy"
        if entry.get("repetition_recent", 0) == 0 and plan["option"]["profile"] == "rotation":
            why = "rotación de actividades y reparto de la carga"
        out.append({
            "task": task, "name": names.get(task, task),
            "from": list(before.get(task, ())), "to": list(after.get(task, ())),
            "explanation": why if task in after else "tarea aplazable que hoy no se cubre",
        })
    return out


def _disadvantages(plans: list[Document]) -> None:
    for plan in plans:
        m = plan["option"]["metrics"]
        out = []
        for key, higher_is_worse, text in DISADVANTAGES:
            values = [p["option"]["metrics"].get(key) for p in plans if p["option"]["metrics"].get(key) is not None]
            if m.get(key) is None or len(values) < 2 or max(values) == min(values):
                continue
            worst = max(values) if higher_is_worse else min(values)
            if m[key] == worst:
                out.append(text)
        plan["option"]["disadvantages"] = out or ["Sin inconvenientes destacables frente a las otras opciones"]


def _workload(plan: Document, original: Document | None) -> Document:
    now = {a: w["hours"] for a, w in plan["global"]["workload"].items()}
    ref = {a: w["hours"] for a, w in (original or plan)["global"]["workload"].items()} if original and original.get("status") == "ok" else {}
    return {a: {"hours": h, "reference_hours": ref.get(a), "delta_h": round(h - ref[a], 2) if a in ref else None}
            for a, h in now.items()}


def generate(environment: str, day: int, states, baselines, exercise, worked_last6,
             config: PlannerConfig | None = None) -> Document:
    config = config or load_config(env={})
    problem, limits = build_problem(environment, day, states, baselines, exercise, worked_last6, config)
    # Referencia: todos en su línea base (sin ajuste por estado) para medir la perturbación
    nominal_states = {a: {"sleep_duration_h": 7.5, "sleep_quality": 85, "fatigue_self": 2.0, "spo2": 97.5,
                          "work_hours_3d": 24.0,
                          **{p: m for p, (m, _) in (baselines.get(a) or {}).items() if p in BASELINE_PARAMETERS}}
                      for a in states}
    reference_problem, _ = build_problem(environment, day, nominal_states, baselines, exercise, worked_last6,
                                         config, source="reference")
    from crew_planner.planner import plan_day
    original = plan_day(reference_problem, config)
    original = original if original.get("status") == "ok" else None

    doc = plan_options(problem, config)
    doc["weekly_limits"] = limits
    doc["social_graph_used"] = False
    if doc.get("status") != "ok":
        doc["original"] = original
        return doc
    _disadvantages(doc["plans"])
    for plan in doc["plans"]:
        plan["option"]["changes_vs_original"] = _changes(original, plan)
        plan["option"]["workload_comparison"] = _workload(plan, original)
    doc["original"] = original
    return doc


def crew_view(plan: Document) -> Document:
    """Lo que ve la tripulación y el comandante: tareas, personas y horario,
    ventajas, inconvenientes y cambios, sin valores de salud ni justificaciones."""
    entries = sorted(plan.get("individual", []) + plan.get("collective", []), key=lambda e: (e["start"], e["task"]))
    o = plan["option"]
    return {
        "id": o["id"], "label": o["label"], "description": o["description"],
        "assignments": [
            {"task": e["task"], "name": e["name"], "start": e["start"], "end": e["end"],
             "people": [e["astronaut"]] if "astronaut" in e else list(e["members"]), "text": e["crew_text"]}
            for e in entries
        ],
        "workload": o.get("workload_comparison", {}),
        "advantages": o.get("advantages", []),
        "disadvantages": o.get("disadvantages", []),
        "changes": o.get("changes_vs_original", []),
        "pending": plan["global"].get("pending", []),
    }


# --- interfaces extensibles (no activas) ------------------------------------------------


def best_time_slot(astronaut_id: str, chronotype: str | None, pvt_by_hour: Mapping[int, float]) -> None:
    """Franja óptima según cronotipo y PVT-B. Pendiente: requiere PVT-B a varias horas."""
    raise NotImplementedError("Franja óptima: pendiente de datos de PVT-B por hora")


def eva_pairs_by_sleep_sync(sleep_midpoints_h: Mapping[str, float]) -> None:
    """Parejas para EVA por sincronía de sueño (solo sueño, nunca el grafo social)."""
    raise NotImplementedError("Parejas para EVA: pendiente de validar el criterio con el equipo médico")


def fatigue_projection_7d(history: Sequence[Mapping[str, float]]) -> None:
    """Proyección de fatiga a siete días. Pendiente: modelo de proyección sin validar."""
    raise NotImplementedError("Proyección a 7 días: pendiente")
