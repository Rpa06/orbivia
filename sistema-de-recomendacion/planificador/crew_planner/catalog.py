"""Catálogo de tareas por entorno de misión (ISS, Luna, Marte, satélites).

- Carga y valida el catálogo JSON de `catalog/`.
- Elige las tareas de un día según su frecuencia, el plan de la misión y los eventos.
- Traduce cada tarea a una `model.Task` del planificador: los vectores de exigencia
  0-1 se convierten en requisitos sobre las mediciones del astronauta con la tabla
  configurable `config/requirement_mapping.toml`.

El optimizador no cambia al cambiar de entorno: solo cambian las tareas que recibe.
Ver docs/task_catalog_methodology.md.
"""

import json
import math
import tomllib
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import (
    COLLECTIVE, INDIVIDUAL, Requirement, Task, ValidationError, check_id, parse_clock,
)

ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = ROOT / "catalog"
MAPPING_FILE = ROOT / "config" / "requirement_mapping.toml"

ENVIRONMENTS = ("iss", "moon", "mars", "satellite")
PHYSICAL = ("physical_effort", "endurance", "mobility", "coordination", "physical_precision",
            "fatigue_tolerance", "recovery_requirement")
COGNITIVE = ("concentration", "cognitive_load", "working_memory", "decision_making",
             "attention_to_detail", "problem_solving", "stress_tolerance", "multitasking")
TEAM = ("team_coordination", "communication_requirement", "interdependence", "leadership_requirement")
FREQUENCIES = ("daily", "weekly", "periodic", "event_based", "contingency", "mission_specific")
SOURCE_TYPES = ("real", "planned", "conceptual")
EXECUTION_MODES = ("human", "robotic", "remote_controlled")
CREW_ROLES = ("performer", "operator", "none")
EVIDENCE_TYPES = ("official", "derived", "theoretical")
CALIBRATION_TOLERANCE = 0.15  # desviación máxima respecto al perfil sin un ajuste justificado

REQUIRED_FIELDS = (
    "task_id", "name", "description", "environment", "category", "type", "importance",
    "duration_minutes", "min_crew", "max_crew", "frequency", "execution_mode", "crew_role",
    "safety_critical", "requires_eva", "technical_requirements", "constraints", "requirements",
    "requirements_metadata", "source_type", "nasa_reference",
)

Document = dict[str, Any]


# --- carga ----------------------------------------------------------------------


@dataclass(frozen=True)
class Catalog:
    tasks: Mapping[str, list[Document]]          # entorno -> tareas
    profiles: Mapping[str, Document]
    references: Mapping[str, Document]
    qualifications: Mapping[str, Document]
    environments: Mapping[str, Document]

    def environment_tasks(self, environment: str) -> list[Document]:
        if environment not in self.tasks:
            raise KeyError(f"Entorno desconocido {environment!r}; disponibles: {', '.join(self.tasks)}")
        return self.tasks[environment]

    def task(self, task_id: str) -> Document:
        for tasks in self.tasks.values():
            for t in tasks:
                if t["task_id"] == task_id:
                    return t
        raise KeyError(task_id)

    def all_tasks(self) -> list[Document]:
        return [t for env in ENVIRONMENTS for t in self.tasks.get(env, [])]


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValidationError(f"{path.name}: JSON inválido: {error}") from error


def load_catalog(directory: str | Path = CATALOG_DIR) -> Catalog:
    directory = Path(directory)
    tasks = {}
    for env in ENVIRONMENTS:
        path = directory / "tasks" / f"{env}.json"
        if path.exists():
            data = _read(path)
            if data.get("environment") != env:
                raise ValidationError(f"{path.name}: environment debe ser {env!r}")
            tasks[env] = data["tasks"]
    profiles_doc = _read(directory / "profiles.json")
    return Catalog(
        tasks=tasks,
        profiles=profiles_doc["profiles"],
        references={r["id"]: r for r in _read(directory / "references.json")["references"]},
        qualifications={q["id"]: q for q in _read(directory / "qualifications.json")["qualifications"]},
        environments=_read(directory / "environments.json")["environments"],
    )


# --- traducción a requisitos -------------------------------------------------------


@dataclass(frozen=True)
class Mapping_:
    min_demand: float
    critical_from: float
    demanding_recovery_from: float
    mandatory_from_importance: float
    mapping: Mapping[str, tuple[str, ...]]
    thresholds: Mapping[str, Document]


def load_mapping(path: str | Path = MAPPING_FILE) -> Mapping_:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    general = raw["general"]
    for dim in raw["mapping"]:
        if dim not in PHYSICAL + COGNITIVE:
            raise ValidationError(f"requirement_mapping: dimensión desconocida {dim!r}")
    for dim in ("stress_tolerance",):
        if dim in raw["mapping"]:
            raise ValidationError(f"requirement_mapping: {dim} es descriptiva y no puede traducirse")
    for param, spec in raw["thresholds"].items():
        levels = spec["levels"]
        if spec["bound"] not in ("min", "max") or len(levels) < 1:
            raise ValidationError(f"requirement_mapping: umbrales inválidos para {param}")
        demands = [d for d, _ in levels]
        if demands != sorted(demands):
            raise ValidationError(f"requirement_mapping: niveles de {param} desordenados")
    return Mapping_(
        min_demand=general["min_demand"],
        critical_from=general["critical_from"],
        demanding_recovery_from=general["demanding_recovery_from"],
        mandatory_from_importance=general["mandatory_from_importance"],
        mapping={k: tuple(v) for k, v in raw["mapping"].items()},
        thresholds=raw["thresholds"],
    )


def _interpolate(levels: list[list[float]], demand: float) -> float:
    if demand <= levels[0][0]:
        return levels[0][1]
    for (d0, v0), (d1, v1) in zip(levels, levels[1:]):
        if d0 <= demand <= d1:
            return v0 + (v1 - v0) * (demand - d0) / (d1 - d0)
    return levels[-1][1]


@dataclass(frozen=True)
class DerivedRequirement:
    requirement: Requirement
    drivers: tuple[str, ...]  # dimensiones que lo originan


def derive_requirements(task: Document, mapping: Mapping_) -> list[DerivedRequirement]:
    """Requisitos sobre parámetros de estado a partir del vector de exigencia.

    Por parámetro se toma la mayor demanda de las dimensiones que lo condicionan,
    para no contar varias veces evidencias correlacionadas.
    """
    vectors = task.get("requirements")
    if not vectors:
        return []
    demands = {**vectors["physical"], **vectors["cognitive"]}
    by_param: dict[str, tuple[float, list[str]]] = {}
    for dim, params in mapping.mapping.items():
        demand = demands.get(dim, 0.0)
        if demand < mapping.min_demand:
            continue
        for param in params:
            best, drivers = by_param.get(param, (0.0, []))
            by_param[param] = (max(best, demand), drivers + [dim])
    out = []
    for param in sorted(by_param):
        demand, drivers = by_param[param]
        spec = mapping.thresholds[param]
        value = round(_interpolate(spec["levels"], demand), 3)
        critical = bool(task["safety_critical"]) and demand >= mapping.critical_from
        req = Requirement(
            parameter=param,
            min=value if spec["bound"] == "min" else None,
            max=value if spec["bound"] == "max" else None,
            weight=round(demand, 3),
            critical=critical,
        )
        out.append(DerivedRequirement(req, tuple(sorted(set(drivers)))))
    return out


def is_crew_task(task: Document) -> bool:
    """Las tareas robóticas o de Tierra no se asignan a la tripulación."""
    return task["crew_role"] in ("performer", "operator")


def to_planner_tasks(
    task: Document, mapping: Mapping_, workday: tuple[float, float], crew: Iterable[str]
) -> list[Task]:
    """Una tarea del catálogo como tareas del planificador (varias si es por astronauta)."""
    vectors = task["requirements"]
    phys, cog = vectors["physical"], vectors["cognitive"]
    team = task.get("team_requirements") or {}
    derived = [d.requirement for d in derive_requirements(task, mapping)]
    common = dict(
        name=task["name"],
        kind=COLLECTIVE if task["type"] == "collective" else INDIVIDUAL,
        importance=task["importance"],
        duration_min=task["duration_minutes"],
        earliest=workday[0],
        latest=workday[1],
        category=task["task_id"],
        requirements=tuple(derived),
        qualifications=frozenset(task["technical_requirements"]["required_qualifications"]),
        min_people=task["min_crew"],
        max_people=task["max_crew"],
        intensity=round(max(phys["physical_effort"], cog["cognitive_load"]), 3),
        demanding=bool(task["requires_eva"]) or phys["recovery_requirement"] >= mapping.demanding_recovery_from,
        mandatory=bool(task["safety_critical"]) or task["importance"] >= mapping.mandatory_from_importance,
        resources=frozenset(task.get("resources", ())),
        interdependence=team.get("interdependence"),
    )
    if task.get("per_astronaut"):
        return [Task(id=f"{task['task_id']}:{a}", only_for=frozenset({a}), **common) for a in crew]
    return [Task(id=task["task_id"], **common)]


# --- selección del día ---------------------------------------------------------------


def _cycle(spec: Mapping[str, Any] | None, day: int) -> list[str]:
    if not spec or not spec.get("days"):
        return []
    return list(spec["days"].get(str(day % spec["cycle_days"]), []))


def _offset(task_id: str, every: int) -> int:
    """Desfase estable por tarea, para que las periódicas no caigan todas el mismo día."""
    return zlib.crc32(task_id.encode()) % every


@dataclass
class DaySelection:
    environment: str
    day: int
    scheduled: list[Document] = field(default_factory=list)
    automated: list[Document] = field(default_factory=list)  # robóticas o de Tierra
    reasons: dict[str, str] = field(default_factory=dict)


def select_day(catalog: Catalog, environment: str, day: int,
               extra_events: Iterable[str] = ()) -> DaySelection:
    """Tareas que tocan un día de misión. La frecuencia no es un calendario de NASA."""
    env = catalog.environments[environment]
    planned = set(_cycle(env.get("mission_plan"), day))
    events = set(_cycle(env.get("events"), day)) | set(extra_events)
    out = DaySelection(environment, day)
    for task in catalog.environment_tasks(environment):
        f = task["frequency"]
        kind, tid = f["kind"], task["task_id"]
        if kind == "daily":
            reason = "diaria"
        elif kind == "weekly" and day % 7 == f["weekday"]:
            reason = "semanal"
        elif kind == "periodic" and (day + _offset(tid, f["every_days"])) % f["every_days"] == 0:
            reason = f"cada {f['every_days']} días"
        elif kind == "mission_specific" and tid in planned:
            reason = "plan de la misión"
        elif kind in ("event_based", "contingency") and tid in events:
            reason = "evento" if kind == "event_based" else "contingencia"
        else:
            continue
        out.reasons[tid] = reason
        (out.scheduled if is_crew_task(task) else out.automated).append(task)
    return out


def planner_tasks_for_day(catalog: Catalog, environment: str, day: int, crew: Iterable[str],
                          mapping: Mapping_ | None = None, extra_events: Iterable[str] = ()
                          ) -> tuple[list[Task], DaySelection]:
    mapping = mapping or load_mapping()
    env = catalog.environments[environment]
    workday = (parse_clock(env["workday"][0], "workday"), parse_clock(env["workday"][1], "workday"))
    selection = select_day(catalog, environment, day, extra_events)
    crew = list(crew)
    tasks = [t for doc in selection.scheduled for t in to_planner_tasks(doc, mapping, workday, crew)]
    return tasks, selection


# --- validación ------------------------------------------------------------------------


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_task(task: Document, catalog: Catalog, environment: str) -> list[str]:
    tid = task.get("task_id", "?")
    errors: list[str] = []

    def err(message: str) -> None:
        errors.append(f"{tid}: {message}")

    missing = [f for f in REQUIRED_FIELDS if f not in task]
    if missing:
        return [f"{tid}: faltan campos {missing}"]
    try:
        check_id(tid, "task_id")
    except ValidationError as error:
        err(str(error))
    if task["environment"] != environment:
        err(f"environment {task['environment']!r} no coincide con el fichero {environment!r}")
    if not tid.startswith({"iss": "ISS_", "moon": "MOON_", "mars": "MARS_", "satellite": "SAT_"}[environment]):
        err("el prefijo del identificador no corresponde al entorno")

    # Tipo y tamaño del equipo
    if task["type"] not in ("individual", "collective"):
        err("type debe ser individual o collective")
    lo, hi = task["min_crew"], task["max_crew"]
    if not (isinstance(lo, int) and isinstance(hi, int) and 1 <= lo <= hi):
        err("se requiere 1 <= min_crew <= max_crew")
    elif task["type"] == "individual" and hi != 1:
        err("una tarea individual es de una persona")
    elif task["type"] == "collective" and hi < 2:
        err("una tarea colectiva admite al menos dos personas")
    if task.get("per_astronaut") and task["type"] != "individual":
        err("per_astronaut solo tiene sentido en tareas individuales")
    if not (_number(task["importance"]) and 1 <= task["importance"] <= 5):
        err("importance debe estar en [1, 5]")
    if not (_number(task["duration_minutes"]) and task["duration_minutes"] > 0):
        err("duration_minutes debe ser > 0")

    # Frecuencia
    f = task["frequency"]
    kind = f.get("kind") if isinstance(f, Mapping) else None
    if kind not in FREQUENCIES:
        err(f"frecuencia inválida {f!r}")
    elif kind == "weekly" and f.get("weekday") not in range(7):
        err("una frecuencia semanal necesita weekday en 0-6")
    elif kind == "periodic" and not (isinstance(f.get("every_days"), int) and f["every_days"] >= 2):
        err("una frecuencia periódica necesita every_days >= 2")

    # Modo de ejecución
    if task["execution_mode"] not in EXECUTION_MODES:
        err(f"execution_mode inválido {task['execution_mode']!r}")
    if task["crew_role"] not in CREW_ROLES:
        err(f"crew_role inválido {task['crew_role']!r}")
    if task["execution_mode"] == "human" and task["crew_role"] != "performer":
        err("una tarea humana la realiza la tripulación (crew_role performer)")
    if task["execution_mode"] == "robotic" and task["crew_role"] != "none":
        err("una tarea robótica no tiene exigencias directas para la tripulación (crew_role none)")

    # Cualificaciones: restricción dura, separada de las puntuaciones
    tech = task["technical_requirements"]
    for q in tech.get("required_qualifications", []) + tech.get("recommended_competencies", []):
        if q not in catalog.qualifications:
            err(f"cualificación desconocida {q!r}")

    # Restricciones duras
    constraints = task["constraints"]
    for hc in constraints.get("hard_constraints", []):
        if not hc.get("type") or hc.get("evidence") not in EVIDENCE_TYPES:
            err("restricción dura sin tipo o sin tipo de evidencia")
        for ref in hc.get("sources", []):
            if ref not in catalog.references:
                err(f"referencia desconocida {ref!r} en una restricción dura")
    if task["requires_eva"] and not task["safety_critical"]:
        err("una EVA debe ser crítica para la seguridad")
    if task["requires_eva"] and task["min_crew"] < 2:
        err("una EVA requiere al menos dos personas")

    # Vectores de exigencia
    vectors = task["requirements"]
    meta = task["requirements_metadata"]
    if is_crew_task(task):
        if not isinstance(vectors, Mapping):
            err("una tarea de la tripulación necesita vectores de exigencia")
        else:
            for group, dims in (("physical", PHYSICAL), ("cognitive", COGNITIVE)):
                values = vectors.get(group) or {}
                if set(values) != set(dims):
                    err(f"el vector {group} debe tener exactamente {list(dims)}")
                for dim, value in values.items():
                    if not (_number(value) and 0 <= value <= 1):
                        err(f"{group}.{dim} fuera de [0, 1] o no numérico: {value!r}")
            extra = set(vectors) - {"physical", "cognitive"}
            if extra:
                err(f"los vectores solo contienen puntuaciones; sobran {sorted(extra)}")
            errors += [f"{tid}: {e}" for e in _calibration(task, catalog)]
    elif vectors is not None:
        err("una tarea robótica o de Tierra no lleva vectores de exigencia humanos")

    if task["type"] == "collective":
        team = task.get("team_requirements")
        if not isinstance(team, Mapping) or set(team) != set(TEAM):
            err(f"una tarea colectiva necesita team_requirements con {list(TEAM)}")
        else:
            for dim, value in team.items():
                if not (_number(value) and 0 <= value <= 1):
                    err(f"team_requirements.{dim} fuera de [0, 1]")

    # Metadatos y trazabilidad
    if meta.get("evidence_type") not in EVIDENCE_TYPES:
        err("requirements_metadata.evidence_type inválido")
    if not (_number(meta.get("confidence")) and 0 <= meta["confidence"] <= 1):
        err("requirements_metadata.confidence debe estar en [0, 1]")
    if not meta.get("justification"):
        err("falta la justificación de los requisitos")
    if meta.get("profile") not in catalog.profiles:
        err(f"perfil desconocido {meta.get('profile')!r}")
    if task["source_type"] not in SOURCE_TYPES:
        err(f"source_type inválido {task['source_type']!r}")
    refs = task["nasa_reference"]
    if task["source_type"] in ("real", "planned") and not refs:
        err("una tarea real o planificada necesita al menos una referencia")
    for ref in list(refs) + list(meta.get("sources", [])):
        if ref not in catalog.references:
            err(f"referencia desconocida {ref!r}")
    if meta.get("evidence_type") == "official":
        if not any(catalog.references[r]["evidence_kind"] in ("standard", "mission_flown")
                   for r in meta.get("sources", []) if r in catalog.references):
            err("evidencia 'official' sin una fuente oficial identificable")
    return errors


def _calibration(task: Document, catalog: Catalog) -> list[str]:
    """Cada valor sigue a su perfil salvo ajuste justificado, y el ajuste coincide con el valor."""
    meta = task["requirements_metadata"]
    profile = catalog.profiles.get(meta.get("profile"))
    if profile is None:
        return []
    base = {**dict(zip(PHYSICAL, profile["physical"])), **dict(zip(COGNITIVE, profile["cognitive"]))}
    adjusted = {}
    errors = []
    for adj in meta.get("adjustments", []):
        if not adj.get("reason"):
            errors.append(f"ajuste de {adj.get('dimension')} sin motivo")
        adjusted[adj.get("dimension")] = adj.get("value")
    values = {**task["requirements"]["physical"], **task["requirements"]["cognitive"]}
    for dim, value in values.items():
        if dim in adjusted:
            if adjusted[dim] != value:
                errors.append(f"el ajuste de {dim} ({adjusted[dim]}) no coincide con el valor ({value})")
        elif abs(value - base[dim]) > CALIBRATION_TOLERANCE + 1e-9:
            errors.append(f"{dim} se aparta del perfil {meta['profile']} sin ajuste justificado")
    return errors


def validate_catalog(catalog: Catalog, mapping: Mapping_ | None = None) -> list[str]:
    """Todas las comprobaciones. Devuelve la lista de errores (vacía si es válido)."""
    mapping = mapping or load_mapping()
    errors: list[str] = []
    seen: dict[str, str] = {}
    for env in ENVIRONMENTS:
        if env not in catalog.tasks:
            errors.append(f"Falta el catálogo del entorno {env}")
            continue
        for task in catalog.tasks[env]:
            tid = task.get("task_id")
            if tid in seen:
                errors.append(f"{tid}: identificador repetido ({seen[tid]} y {env})")
            seen[tid] = env
            task_errors = validate_task(task, catalog, env)
            errors += task_errors
            # Compatibilidad con el optimizador: debe traducirse sin errores
            if not task_errors and is_crew_task(task):
                try:
                    to_planner_tasks(task, mapping, (0.0, 86400.0), ["X1"])
                except ValidationError as error:
                    errors.append(f"{tid}: no se traduce al planificador: {error}")
    for ref_id, ref in catalog.references.items():
        if ref.get("verified") not in ("existence", "not_public"):
            errors.append(f"Referencia {ref_id}: verified debe ser existence o not_public")
        if ref.get("verified") == "existence" and not ref.get("url"):
            errors.append(f"Referencia {ref_id}: sin URL")
    errors += _validate_environments(catalog)
    return errors


def _validate_environments(catalog: Catalog) -> list[str]:
    errors = []
    for env, spec in catalog.environments.items():
        tasks = {t["task_id"]: t for t in catalog.tasks.get(env, [])}
        for key, kinds in (("mission_plan", ("mission_specific",)), ("events", ("event_based", "contingency"))):
            block = spec.get(key) or {}
            for day, ids in (block.get("days") or {}).items():
                if not 0 <= int(day) < block["cycle_days"]:
                    errors.append(f"{env}.{key}: día {day} fuera del ciclo")
                for tid in ids:
                    if tid not in tasks:
                        errors.append(f"{env}.{key}: tarea desconocida {tid}")
                    elif tasks[tid]["frequency"]["kind"] not in kinds:
                        errors.append(f"{env}.{key}: {tid} no tiene frecuencia {'/'.join(kinds)}")
        held = {q for quals in spec["crew"].values() for q in quals}
        for q in held - set(catalog.qualifications):
            errors.append(f"{env}: la tripulación tiene una cualificación desconocida {q!r}")
        for task in tasks.values():
            for q in task["technical_requirements"]["required_qualifications"]:
                holders = sum(q in quals for quals in spec["crew"].values())
                if is_crew_task(task) and holders < task["min_crew"]:
                    errors.append(f"{env}: {task['task_id']} necesita {task['min_crew']} personas con {q} y hay {holders}")
    return errors
