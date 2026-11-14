"""Entrada de un día de planificación y su validación cruzada.

Formato JSON:

    {
      "day": 12,                    día de misión que se planifica
      "as_of": 1036800.0,           opcional; instante (s de misión) de referencia
                                    para la vigencia de los datos. Por defecto, la
                                    medianoche del día planificado.
      "crew": [...],                astronautas (model.Astronaut)
      "tasks": [...],               tareas (model.Task)
      "history": [...],             opcional; historial (history.HistoryEntry)
    }

El grafo social NO es una entrada admitida: una entrada con la clave "social"
se rechaza. En Orbivia el grafo nunca se usa para repartir, agrupar ni separar
a la tripulación (README, sección 2.D).

Los errores de forma o de coherencia detienen la carga con un mensaje claro.
Lo que es dudoso pero válido se devuelve como aviso.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import PlannerConfig
from .history import History
from .model import (
    BASELINE_Z, DAY_S, HIGHER_BETTER, LOWER_BETTER, Astronaut, Task, ValidationError, _finite,
)

# "meta" es informativo (entorno, origen de las tareas): el planificador no lo usa
_KEYS = {"day", "as_of", "crew", "tasks", "history", "meta"}
FORBIDDEN_KEYS = {"social"}


@dataclass(frozen=True)
class PlanningInput:
    day: int
    crew: tuple[Astronaut, ...]
    tasks: tuple[Task, ...]
    history: History = field(default_factory=History)
    as_of_s: float | None = None

    @property
    def reference_s(self) -> float:
        """Instante respecto al que se mide la vigencia de los datos."""
        return self.as_of_s if self.as_of_s is not None else self.day * DAY_S

    @property
    def day_start_s(self) -> float:
        return self.day * DAY_S

    def astronaut(self, astronaut_id: str) -> Astronaut:
        for a in self.crew:
            if a.id == astronaut_id:
                return a
        raise KeyError(astronaut_id)

    def task(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(task_id)


def validate(problem: PlanningInput, config: PlannerConfig) -> list[str]:
    """Comprueba la coherencia entre entrada y configuración. Devuelve los avisos."""
    warnings: list[str] = []
    catalog = config.parameters

    if not isinstance(problem.day, int) or isinstance(problem.day, bool) or problem.day < 0:
        raise ValidationError("day debe ser un entero >= 0")
    if not problem.crew:
        raise ValidationError("La tripulación está vacía")
    ids = [a.id for a in problem.crew]
    if len(set(ids)) != len(ids):
        raise ValidationError("Astronautas repetidos en crew")
    task_ids = [t.id for t in problem.tasks]
    if len(set(task_ids)) != len(task_ids):
        raise ValidationError("Tareas repetidas en tasks")

    reference = problem.reference_s
    for astronaut in problem.crew:
        for m in astronaut.measurements:
            if m.parameter not in catalog:
                raise ValidationError(f"{astronaut.id}: parámetro desconocido {m.parameter!r}")
            # Un dato posterior al instante de referencia es un error de reloj, no un dato
            if m.measured_at > reference:
                raise ValidationError(
                    f"{astronaut.id}: medición de {m.parameter} posterior al instante de referencia"
                )
        for parameter in astronaut.baselines:
            if parameter not in catalog:
                raise ValidationError(f"{astronaut.id}: línea base de parámetro desconocido {parameter!r}")
            if catalog[parameter].normalization != BASELINE_Z:
                warnings.append(f"{astronaut.id}: línea base de {parameter} sin uso (se normaliza por rango)")

    for task in problem.tasks:
        config.importance.normalize(task.importance)  # lanza si está fuera de escala
        for req in task.requirements:
            spec = catalog.get(req.parameter)
            if spec is None:
                raise ValidationError(f"Tarea {task.id}: parámetro desconocido {req.parameter!r}")
            # Coherencia de dirección: no es un error, pero suele serlo
            if spec.kind == LOWER_BETTER and req.max is None:
                warnings.append(f"Tarea {task.id}: {req.parameter} es 'menos es mejor' y solo tiene mínimo")
            if spec.kind == HIGHER_BETTER and req.min is None:
                warnings.append(f"Tarea {task.id}: {req.parameter} es 'más es mejor' y solo tiene máximo")
        if task.min_people > len(problem.crew):
            warnings.append(f"Tarea {task.id}: pide {task.min_people} personas y la tripulación tiene {len(problem.crew)}")

    problem.history.check_before(problem.day)

    return warnings


def from_dict(raw: Mapping[str, Any]) -> PlanningInput:
    if not isinstance(raw, Mapping):
        raise ValidationError("La entrada debe ser un objeto JSON")
    forbidden = FORBIDDEN_KEYS & set(raw)
    if forbidden:
        raise ValidationError(
            "El grafo social no puede ser una entrada del planificador "
            f"(claves rechazadas: {sorted(forbidden)})"
        )
    unknown = set(raw) - _KEYS
    if unknown:
        raise ValidationError(f"Claves desconocidas en la entrada: {sorted(unknown)}")
    for key in ("day", "crew", "tasks"):
        if key not in raw:
            raise ValidationError(f"Falta {key!r} en la entrada")
    as_of = raw.get("as_of")
    return PlanningInput(
        day=raw["day"],
        crew=tuple(Astronaut.from_dict(a) for a in raw["crew"]),
        tasks=tuple(Task.from_dict(t) for t in raw["tasks"]),
        history=History.from_list(raw.get("history") or ()),
        as_of_s=None if as_of is None else _finite(as_of, "as_of"),
    )


def load_input(path: str | Path, config: PlannerConfig) -> tuple[PlanningInput, list[str]]:
    """Lee y valida un fichero de entrada. Devuelve la entrada y los avisos."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValidationError(f"{path}: JSON inválido: {error}") from error
    problem = from_dict(raw)
    return problem, validate(problem, config)
