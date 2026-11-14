"""Tabla comparativa de requisitos e informe de calibración del catálogo.

    python -m crew_planner.catalog_report --out ../../docs/task_requirements_table.md

Se genera a partir del catálogo: no se edita a mano.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from .catalog import COGNITIVE, ENVIRONMENTS, PHYSICAL, TEAM, Catalog, load_catalog, load_mapping, derive_requirements

SHORT = {
    "physical_effort": "Esf", "endurance": "Res", "mobility": "Mov", "coordination": "Coo",
    "physical_precision": "Pre", "fatigue_tolerance": "Fat", "recovery_requirement": "Rec",
    "concentration": "Con", "cognitive_load": "Car", "working_memory": "Mem", "decision_making": "Dec",
    "attention_to_detail": "Det", "problem_solving": "Pro", "stress_tolerance": "Est*", "multitasking": "Mul",
    "team_coordination": "Coord", "communication_requirement": "Com*", "interdependence": "Interd",
    "leadership_requirement": "Lid*",
}
ENV_NAMES = {"iss": "ISS", "moon": "Luna", "mars": "Marte", "satellite": "Satélites"}


def _v(x: float) -> str:
    return f"{x:.2f}".lstrip("0") if x < 1 else "1"


def render(catalog: Catalog) -> str:
    mapping = load_mapping()
    tasks = catalog.all_tasks()
    out = [
        "# Catálogo de tareas: tabla comparativa de requisitos",
        "",
        "Generado con `python -m crew_planner.catalog_report`; no editar a mano. Metodología en "
        "[task_catalog_methodology.md](task_catalog_methodology.md).",
        "",
        "**Todas las puntuaciones son estimaciones teóricas del modelo Orbivia** (escala 0-1). NASA no publica "
        "puntuaciones de exigencia por tarea. Las columnas con asterisco son descriptivas: no se comparan con el "
        "estado del astronauta.",
        "",
        "Leyenda. Físicas: " + ", ".join(f"{SHORT[d]} = {d}" for d in PHYSICAL) + ". Cognitivas: "
        + ", ".join(f"{SHORT[d]} = {d}" for d in COGNITIVE) + ".",
        "",
        "## Resumen",
        "",
        "| Entorno | Tareas | Individuales | Colectivas | Críticas | EVA | Sin tripulación | Real | Planificada | Conceptual |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for env in ENVIRONMENTS:
        ts = catalog.environment_tasks(env)
        src = Counter(t["source_type"] for t in ts)
        out.append(
            f"| {ENV_NAMES[env]} | {len(ts)} | {sum(t['type'] == 'individual' for t in ts)} | "
            f"{sum(t['type'] == 'collective' for t in ts)} | {sum(t['safety_critical'] for t in ts)} | "
            f"{sum(t['requires_eva'] for t in ts)} | {sum(t['crew_role'] == 'none' for t in ts)} | "
            f"{src['real']} | {src['planned']} | {src['conceptual']} |"
        )

    for env in ENVIRONMENTS:
        out += ["", f"## {ENV_NAMES[env]}", "",
                "| Tarea | Nombre | Tipo | Modo | Perfil | " + " | ".join(SHORT[d] for d in PHYSICAL + COGNITIVE) + " | Conf. |",
                "|" + "---|" * (6 + len(PHYSICAL) + len(COGNITIVE))]
        for t in catalog.environment_tasks(env):
            meta = t["requirements_metadata"]
            mode = t["execution_mode"] if t["crew_role"] != "operator" else "operador"
            if t["requirements"] is None:
                values = ["—"] * (len(PHYSICAL) + len(COGNITIVE))
            else:
                values = [_v(t["requirements"]["physical"][d]) for d in PHYSICAL]
                values += [_v(t["requirements"]["cognitive"][d]) for d in COGNITIVE]
            kind = "col" if t["type"] == "collective" else "ind"
            mark = " ⚠" if t["safety_critical"] else ""
            out.append(f"| {t['task_id']}{mark} | {t['name']} | {kind} | {mode} | {meta['profile']} | "
                       + " | ".join(values) + f" | {meta['confidence']:.2f} |")
    out += ["", "⚠ = crítica para la seguridad."]

    out += ["", "## Tareas colectivas: coordinación del equipo", "",
            "Ordenadas por interdependencia, que escala el peso de la compatibilidad social en el optimizador.", "",
            "| Tarea | Nombre | Equipo | " + " | ".join(SHORT[d] for d in TEAM) + " |", "|---|---|---|---|---|---|---|"]
    collective = sorted((t for t in tasks if t["type"] == "collective" and t["crew_role"] != "none"),
                        key=lambda t: (-t["team_requirements"]["interdependence"], t["task_id"]))
    for t in collective:
        team = t["team_requirements"]
        out.append(f"| {t['task_id']} | {t['name']} | {t['min_crew']}–{t['max_crew']} | "
                   + " | ".join(_v(team[d]) for d in TEAM) + " |")

    out += ["", "## Cualificaciones obligatorias", "",
            "Restricciones duras: sin ellas la tarea no es asignable. Vocabulario genérico de Orbivia, "
            "pendiente de validar frente a las certificaciones reales de cada programa.", "",
            "| Cualificación | Tareas |", "|---|---|"]
    by_qual: dict[str, list[str]] = {}
    for t in tasks:
        for q in t["technical_requirements"]["required_qualifications"]:
            by_qual.setdefault(q, []).append(t["task_id"])
    for q in sorted(by_qual):
        out.append(f"| {catalog.qualifications[q]['name']} (`{q}`) | {len(by_qual[q])}: {', '.join(by_qual[q])} |")

    out += ["", "## Requisitos sobre el astronauta en las tareas críticas", "",
            "Traducción de los vectores con `config/requirement_mapping.toml`. **Duro** = restricción de "
            "seguridad: si no se cumple, o el dato es desconocido, la persona no es elegible.", "",
            "| Tarea | Requisitos |", "|---|---|"]
    for t in tasks:
        if not t["safety_critical"] or t["requirements"] is None:
            continue
        reqs = derive_requirements(t, mapping)
        text = "; ".join(
            f"{d.requirement.parameter} {'≥' if d.requirement.min is not None else '≤'} "
            f"{d.requirement.min if d.requirement.min is not None else d.requirement.max:g}"
            + (" **duro**" if d.requirement.critical else "")
            for d in reqs
        )
        out.append(f"| {t['task_id']} | {text or '—'} |")

    out += ["", "## Informe de calibración", "",
            "Ninguna puntuación es oficial: todas necesitan validación con expertos (equipo médico, "
            "instructores de EVA y operaciones de misión) y, cuando existan, con datos de rendimiento reales.",
            "",
            "Prioridad de calibración: primero las tareas críticas para la seguridad con menor confianza, "
            "porque sus umbrales derivados son restricciones duras.", "",
            "| Prioridad | Tarea | Nombre | Crítica | Confianza | Ajustes sobre el perfil |", "|---|---|---|---|---|---|"]
    ranked = sorted((t for t in tasks if t["requirements"] is not None),
                    key=lambda t: (not t["safety_critical"], t["requirements_metadata"]["confidence"], t["task_id"]))
    for k, t in enumerate(ranked, 1):
        meta = t["requirements_metadata"]
        adj = "; ".join(f"{a['dimension']} {a['profile_value']}→{a['value']}: {a['reason']}" for a in meta["adjustments"])
        out.append(f"| {k} | {t['task_id']} | {t['name']} | {'sí' if t['safety_critical'] else 'no'} | "
                   f"{meta['confidence']:.2f} | {adj or '—'} |")
    out += ["", "Además, todas las duraciones son estimaciones configurables, salvo el ejercicio de la ISS, "
            "derivado del protocolo de unas dos horas diarias que describe la CSA.", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crew_planner.catalog_report")
    parser.add_argument("--out", help="fichero Markdown de salida; por defecto, la salida estándar")
    args = parser.parse_args(argv)
    text = render(load_catalog())
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
