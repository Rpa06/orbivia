"""Simulación reproducible con una tripulación ficticia y datos sintéticos.

Todo lo que genera este módulo es inventado y está marcado como tal
(`source = "synthetic:..."`). Sirve para validar el planificador, no describe a
ninguna persona.

Uso:
    python -m crew_planner.simulation --scenario high_fatigue --days 1
    python -m crew_planner.simulation --scenario nominal --days 7 --out plans/
"""

import argparse
import copy
import json
import random
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import PlannerConfig, load_config
from .history import History, HistoryEntry
from .inputs import PlanningInput, from_dict
from .planner import plan_day

Document = dict[str, Any]
DAY_S = 86400.0
H = 3600.0

CREW = ("A1", "A2", "A3", "A4", "A5", "A6")
QUALIFICATIONS = {
    "A1": ["eva", "medical"],
    "A2": ["eva", "robotics"],
    "A3": ["robotics", "life_support"],
    "A4": ["medical", "life_support"],
    "A5": ["eva", "life_support"],
    "A6": ["robotics", "medical"],
}
# Ejercicio diario fijo a distinta hora para cada uno (README.md.2.0: compromiso fijo)
EXERCISE = {"A1": "09:00", "A2": "10:00", "A3": "11:00", "A4": "14:00", "A5": "15:00", "A6": "16:00"}

BASELINES = {
    "pvt_lapses": (2.0, 1.0),
    "grip_strength": (42.0, 3.0),
    "resting_hr": (60.0, 4.0),
}



def _clock(hours: float) -> str:
    return f"{int(hours):02d}:{int(round(hours % 1 * 60)):02d}"


def _astronaut(a: str, day: int, rng: random.Random) -> Document:
    ex = float(EXERCISE[a].split(":")[0])
    return {
        "id": a,
        "qualifications": QUALIFICATIONS[a],
        "work": [["08:00", "17:00"]],
        "sleep": [["00:00", "07:00"], ["23:00", "24:00"]],
        "unavailable": [["12:00", "13:00"], [EXERCISE[a], _clock(ex + 1)]],
        "measurements": _measurements(day, rng),
        "baselines": [{"parameter": p, "mean": mu, "sd": sd} for p, (mu, sd) in BASELINES.items()],
    }


def _measurements(day: int, rng: random.Random) -> list[Document]:
    """Mediciones sintéticas de un astronauta en buen estado, marcadas como tales."""
    ref = day * DAY_S

    def m(parameter: str, value: float, age_h: float = 1.0, confidence: float | None = None) -> Document:
        out = {"parameter": parameter, "value": round(value, 3), "measured_at": ref - age_h * H,
               "source": "synthetic:" + parameter}
        if confidence is not None:
            out["confidence"] = confidence
        return out

    mean_pvt, sd_pvt = BASELINES["pvt_lapses"]
    mean_grip, sd_grip = BASELINES["grip_strength"]
    mean_hr, sd_hr = BASELINES["resting_hr"]
    return [
        m("sleep_duration_h", rng.uniform(7.0, 8.2), age_h=2),
        m("sleep_quality", rng.uniform(80, 92), age_h=2, confidence=0.8),
        m("pvt_lapses", mean_pvt + rng.uniform(-0.8, 0.8) * sd_pvt),
        m("fatigue_self", rng.uniform(1.5, 2.5)),
        m("grip_strength", mean_grip + rng.uniform(-0.8, 0.8) * sd_grip),
        m("spo2", rng.uniform(96, 99)),
        m("resting_hr", mean_hr + rng.uniform(-0.8, 0.8) * sd_hr),
        m("work_hours_3d", rng.uniform(20, 25)),
    ]


def task_catalog() -> list[Document]:
    """Tareas comunes y de mantenimiento de un día (README.md.2.0: no la investigación propia)."""
    return [
        {
            "id": "EVA_PREP", "name": "Preparación de EVA", "kind": "individual", "importance": 5,
            "duration_min": 90, "earliest": "08:00", "latest": "12:00", "intensity": 0.8, "demanding": True,
            "qualifications": ["eva"], "resources": ["airlock"],
            "requirements": [
                {"parameter": "sleep_duration_h", "min": 6.5, "critical": True, "weight": 2},
                {"parameter": "fatigue_self", "max": 3, "critical": True, "weight": 2},
                {"parameter": "pvt_lapses", "max": 1.5, "critical": True},
                {"parameter": "spo2", "min": 94, "critical": True},
                {"parameter": "grip_strength", "min": -1},
            ],
        },
        {
            "id": "ROBOTIC_ARM", "name": "Operación del brazo robótico", "kind": "individual", "importance": 4,
            "duration_min": 120, "earliest": "08:00", "latest": "17:00", "intensity": 0.5,
            "qualifications": ["robotics"], "resources": ["robot_arm"],
            "requirements": [
                {"parameter": "pvt_lapses", "max": 1.0, "weight": 2},
                {"parameter": "sleep_duration_h", "min": 6},
            ],
        },
        {
            "id": "MEDICAL_CHECK", "name": "Revisión médica rutinaria", "kind": "individual", "importance": 3,
            "duration_min": 45, "earliest": "08:00", "latest": "17:00", "intensity": 0.2,
            "qualifications": ["medical"],
            "requirements": [{"parameter": "pvt_lapses", "max": 2}],
        },
        {
            "id": "LIFE_SUPPORT", "name": "Mantenimiento de soporte vital", "kind": "collective", "importance": 4,
            "duration_min": 90, "earliest": "08:00", "latest": "17:00", "intensity": 0.6,
            "min_people": 2, "max_people": 2,
            "team_qualifications": [{"qualification": "life_support", "mode": "at_least", "count": 1}],
            "requirements": [
                {"parameter": "fatigue_self", "max": 4, "critical": True},
                {"parameter": "grip_strength", "min": -1.5},
            ],
        },
        {
            "id": "EXPERIMENT_SETUP", "name": "Montaje de experimento", "kind": "collective", "importance": 3,
            "duration_min": 60, "earliest": "08:00", "latest": "17:00", "intensity": 0.5,
            "min_people": 2, "max_people": 2,
            "requirements": [{"parameter": "pvt_lapses", "max": 2}],
        },
        {
            "id": "INVENTORY", "name": "Inventario de suministros", "kind": "collective", "importance": 2,
            "duration_min": 60, "earliest": "08:00", "latest": "17:00", "intensity": 0.2,
            "min_people": 2, "max_people": 3,
        },
        {
            "id": "GALLEY", "name": "Preparación de comidas", "kind": "individual", "importance": 2,
            "category": "galley", "duration_min": 60, "earliest": "11:00", "latest": "12:00", "intensity": 0.3,
        },
        {
            "id": "CLEANING", "name": "Limpieza de módulos", "kind": "individual", "importance": 1,
            "duration_min": 45, "earliest": "08:00", "latest": "17:00", "intensity": 0.3, "mandatory": False,
        },
    ]



def base_input(day: int = 10, seed: int = 42) -> Document:
    rng = random.Random(f"{seed}|{day}")
    return {
        "day": day,
        "crew": [_astronaut(a, day, rng) for a in CREW],
        "tasks": task_catalog(),
        "history": [],
    }


# --- escenarios -------------------------------------------------------------------


def _set(raw: Document, astronaut: str, parameter: str, value: float) -> None:
    for a in raw["crew"]:
        if a["id"] == astronaut:
            for m in a["measurements"]:
                if m["parameter"] == parameter:
                    m["value"] = value
                    return
    raise KeyError((astronaut, parameter))


def _crew(raw: Document, astronaut: str) -> Document:
    return next(a for a in raw["crew"] if a["id"] == astronaut)


def _history(astronaut: str, task: str, category: str, days, duration: float = 60) -> list[Document]:
    return [{"day": d, "astronaut": astronaut, "task_id": task, "category": category,
             "duration_min": duration, "intensity": 0.3} for d in days]


def nominal(day: int, seed: int) -> Document:
    return base_input(day, seed)


def high_fatigue(day: int, seed: int) -> Document:
    """A2 ha dormido poco y declara mucho cansancio."""
    raw = base_input(day, seed)
    _set(raw, "A2", "sleep_duration_h", 4.5)
    _set(raw, "A2", "fatigue_self", 4.5)
    _set(raw, "A2", "work_hours_3d", 33)
    return raw


def incomplete_data(day: int, seed: int) -> Document:
    """A3 no tiene ninguna medición vigente."""
    raw = base_input(day, seed)
    _crew(raw, "A3")["measurements"] = []
    return raw


def critical_task(day: int, seed: int) -> Document:
    """Solo A1 cumple los umbrales de EVA_PREP, y además la hizo ayer."""
    raw = base_input(day, seed)
    _set(raw, "A1", "sleep_duration_h", 8.0)
    _set(raw, "A1", "fatigue_self", 1.5)
    _set(raw, "A2", "fatigue_self", 3.6)
    _set(raw, "A5", "sleep_duration_h", 6.0)
    raw["history"] = _history("A1", "EVA_PREP", "EVA_PREP", [day - 1], 90)
    return raw


def unqualified(day: int, seed: int) -> Document:
    """A4 tiene la mejor condición física, pero no está cualificado en robótica."""
    raw = base_input(day, seed)
    _set(raw, "A4", "pvt_lapses", 0.5)
    _set(raw, "A4", "sleep_duration_h", 8.2)
    return raw


def repetition(day: int, seed: int) -> Document:
    """A5 ha preparado la comida los últimos 6 días; A4 es la única persona médica disponible."""
    raw = base_input(day, seed)
    raw["history"] = _history("A5", "GALLEY", "galley", range(day - 6, day))
    raw["history"] += _history("A4", "MEDICAL_CHECK", "MEDICAL_CHECK", range(day - 6, day), 45)
    for a in ("A1", "A6"):  # quedan sin cualificación médica en este escenario
        _crew(raw, a)["qualifications"] = [q for q in _crew(raw, a)["qualifications"] if q != "medical"]
    return raw


def workload_imbalance(day: int, seed: int) -> Document:
    """A1 es la persona más adecuada para casi todo, pero acumula horas y cansancio."""
    raw = base_input(day, seed)
    for a in raw["crew"]:
        a["qualifications"] = ["eva", "medical", "robotics", "life_support"] if a["id"] == "A1" else a["qualifications"]
    _set(raw, "A1", "pvt_lapses", 0.2)
    _set(raw, "A1", "sleep_duration_h", 8.2)
    _set(raw, "A1", "work_hours_3d", 32)
    _set(raw, "A1", "fatigue_self", 2.9)
    return raw


def infeasible(day: int, seed: int) -> Document:
    """Dos EVA obligatorias en la misma mañana; solo A1 está en condiciones de hacerlas."""
    raw = critical_task(day, seed)
    second = copy.deepcopy(next(t for t in raw["tasks"] if t["id"] == "EVA_PREP"))
    second.update({"id": "EVA_PREP_2", "name": "Segunda preparación de EVA"})
    raw["tasks"].append(second)
    return raw


SCENARIOS: dict[str, Callable[[int, int], Document]] = {
    "nominal": nominal,
    "high_fatigue": high_fatigue,
    "incomplete_data": incomplete_data,
    "critical_task": critical_task,
    "unqualified": unqualified,
    "repetition": repetition,
    "workload_imbalance": workload_imbalance,
    "infeasible": infeasible,
}


def environment_input(environment: str, day: int = 10, seed: int = 42,
                      extra_events: tuple[str, ...] = (), catalog=None) -> Document:
    """Entrada de un día con las tareas del catálogo de un entorno (ISS, Luna, Marte, satélites).

    La tripulación y sus mediciones son sintéticas; las tareas salen del catálogo
    según su frecuencia, el plan de la misión y los eventos del día.
    """
    from .catalog import load_catalog, planner_tasks_for_day

    catalog = catalog or load_catalog()
    env = catalog.environments[environment]
    rng = random.Random(f"{seed}|{environment}|{day}")
    crew_ids = tuple(env["crew"])
    tasks, selection = planner_tasks_for_day(catalog, environment, day, crew_ids, extra_events=extra_events)
    return {
        "day": day,
        "crew": [
            {
                "id": a,
                "qualifications": quals,
                "work": [env["workday"]],
                "sleep": [["00:00", "07:00"], ["23:00", "24:00"]],
                "measurements": _measurements(day, rng),
                "baselines": [{"parameter": p, "mean": mu, "sd": sd} for p, (mu, sd) in BASELINES.items()],
            }
            for a, quals in env["crew"].items()
        ],
        "tasks": [t.to_dict() for t in tasks],
        "history": [],
        "meta": {
            "environment": environment,
            "environment_name": env["name"],
            "scheduled": {t["task_id"]: selection.reasons[t["task_id"]] for t in selection.scheduled},
            "automated": [
                {"task_id": t["task_id"], "name": t["name"], "execution_mode": t["execution_mode"]}
                for t in selection.automated
            ],
        },
    }


def scenario_input(name: str, day: int = 10, seed: int = 42) -> PlanningInput:
    if name not in SCENARIOS:
        raise KeyError(f"Escenario desconocido {name!r}; disponibles: {', '.join(SCENARIOS)}")
    return from_dict(SCENARIOS[name](day, seed))


# --- varios días --------------------------------------------------------------------


def history_from_plan(plan: Document, tasks: dict[str, Document]) -> list[HistoryEntry]:
    out = []
    for entry in plan.get("individual", []) + plan.get("collective", []):
        t = tasks[entry["task"]]
        members = [entry["astronaut"]] if "astronaut" in entry else entry["members"]
        for a in members:
            out.append(HistoryEntry(
                day=plan["day"], astronaut=a, task_id=t["id"], category=t.get("category") or t["id"],
                duration_min=t["duration_min"], intensity=t.get("intensity", 0.5),
                demanding=t.get("demanding", False),
            ))
    return out


def day_input(day: int, seed: int, scenario: str = "nominal", environment: str | None = None,
              extra_events: tuple[str, ...] = ()) -> Document:
    if environment:
        return environment_input(environment, day, seed, extra_events)
    return SCENARIOS[scenario](day, seed)


def simulate(days: int, config: PlannerConfig, scenario: str = "nominal", first_day: int = 10,
             seed: int = 42, environment: str | None = None,
             extra_events: tuple[str, ...] = (), options: int | None = None,
             choose: int = 0) -> list[Document]:
    """Planifica `days` días seguidos; el plan de cada día pasa al historial del siguiente.

    Con `options` > 1 cada día es un documento con varios planes alternativos y se da
    por ejecutado el de índice `choose` (0 = opción A).
    """
    from .options import plan_options

    history = History()
    out = []
    for day in range(first_day, first_day + days):
        raw = day_input(day, seed, scenario, environment, extra_events)
        raw["history"] = [e.to_dict() for e in history.entries] + raw.get("history", [])
        problem = from_dict(raw)
        doc = plan_options(problem, config, options) if options and options > 1 else plan_day(problem, config)
        if raw.get("meta"):
            doc["meta"] = raw["meta"]
        out.append(doc)
        executed = doc
        if "plans" in doc:
            executed = doc["plans"][min(choose, len(doc["plans"]) - 1)] if doc["status"] == "ok" else doc
            doc["executed"] = executed["option"]["id"] if doc["status"] == "ok" else None
        if executed["status"] == "ok":
            history = history.extend(history_from_plan(executed, {t["id"]: t for t in raw["tasks"]}))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crew_planner.simulation", description="Simulación con datos sintéticos")
    parser.add_argument("--scenario", default="nominal", choices=list(SCENARIOS))
    parser.add_argument("--environment", choices=["iss", "moon", "mars", "satellite"],
                        help="usar el catálogo de tareas de un entorno de misión en vez de un escenario")
    parser.add_argument("--event", action="append", default=[],
                        help="tarea de evento o contingencia que se dispara cada día simulado (repetible)")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--first-day", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--config")
    parser.add_argument("--out", help="carpeta donde guardar un plan JSON por día")
    parser.add_argument("--plans", type=int, help="planes alternativos por día (por defecto alternatives.count)")
    parser.add_argument("--choose", default="A", help="plan que se da por ejecutado cada día (A, B, C...)")
    args = parser.parse_args(argv)

    import os

    config = load_config(args.config, env=os.environ)
    count = args.plans or config.alternatives.count
    choose = max(0, "ABCDEFGHIJ".find(args.choose.upper()))
    docs = simulate(args.days, config, args.scenario, first_day=args.first_day, seed=args.seed,
                    environment=args.environment, extra_events=tuple(args.event),
                    options=count, choose=choose)
    from .report import CREW, GROUND, render_html, render_options_html

    render = render_options_html if count > 1 else render_html
    for doc in docs:
        if args.out:
            folder = Path(args.out)
            folder.mkdir(parents=True, exist_ok=True)
            name = f"plan_{doc['day']:04d}"
            (folder / f"{name}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
            # El horario de cada astronauta solo depende del escenario (o entorno) y del día
            raw = day_input(doc["day"], args.seed, args.scenario, args.environment, tuple(args.event))
            (folder / f"{name}.html").write_text(render(doc, raw, GROUND), encoding="utf-8")
            (folder / f"{name}_tripulacion.html").write_text(render(doc, raw, CREW), encoding="utf-8")
        print(summary_options(doc) if "plans" in doc else summary(doc))
    return 0 if all(d["status"] == "ok" for d in docs) else 2


def summary_options(doc: Document) -> str:
    """Resumen de un día con varios planes: el plan A completo y en qué cambian los demás."""
    if doc["status"] != "ok":
        return summary(doc)
    plans = doc["plans"]
    first = dict(plans[0], meta=doc.get("meta"))
    lines = [summary(first).replace(": ok", f": {len(plans)} planes (se ejecuta {doc.get('executed', 'A')})", 1)]
    for plan in plans:
        o = plan["option"]
        lines.append(f"  Opción {o['id']} · {o['label']}: " + "; ".join(o["advantages"]))
        for d in o.get("differences_vs_A", []):
            lines.append(f"      {d['task']:<17} {' + '.join(d['in_A']) or '—'} → {' + '.join(d['here']) or '—'}")
    lines += [f"  Nota: {n}" for n in doc.get("notes", [])]
    return "\n".join(lines)


def summary(plan: Document) -> str:
    """Resumen legible de un plan, para la terminal."""
    meta = plan.get("meta") or {}
    where = f" · {meta['environment_name']}" if meta.get("environment_name") else ""
    lines = [f"Día {plan['day']}{where}: {plan['status']}"]
    for e in sorted(plan["individual"] + plan["collective"], key=lambda e: (e["start"], e["task"])):
        who = e.get("astronaut") or " + ".join(e["members"])
        lines.append(f"  {e['start']}–{e['end']}  {e['task']:<17} {who}")
    if plan["status"] == "ok":
        g = plan["global"]
        lines.append("  carga: " + ", ".join(f"{a} {w['load']:.2f}/{w['target_load']:.2f}" for a, w in g["workload"].items()))
        if g["pending"]:
            lines.append("  pendientes: " + ", ".join(p["task"] for p in g["pending"]))
        lines.append(f"  coste total: {g['costs']['total']:.3f}")
    if meta.get("automated"):
        lines.append("  sin tripulación (robótica o Tierra): " + ", ".join(a["task_id"] for a in meta["automated"]))
    for c in plan.get("conflicts", []):
        lines.append(f"  conflicto: {c['summary']}")
        lines.append(f"  sugerencias: {'; '.join(c['suggestions'])}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
