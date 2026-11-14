"""Modelo de datos: parámetros, mediciones, astronautas y tareas.

Estructuras inmutables con validación al construirlas y conversión a JSON.
Los tiempos de misión van en segundos; las horas del día, en segundos desde la
medianoche del día planificado (se escriben "HH:MM" en JSON).

Ningún valor se rellena ni se estima: un parámetro sin medición es desconocido.
"""

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

DAY_S = 86400.0

ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

# Tipo de parámetro: qué dirección es "mejor". Sirve para la capacidad relativa
# (fatiga) y para avisar de requisitos incoherentes; el déficit respecto a una
# tarea lo fija el propio requisito (mínimo, máximo o intervalo).
HIGHER_BETTER = "higher_better"
LOWER_BETTER = "lower_better"
RANGE = "range"
KINDS = (HIGHER_BETTER, LOWER_BETTER, RANGE)

# Normalización: por rango fisiológico fijo o respecto a la línea base propia
MINMAX = "minmax"
BASELINE_Z = "baseline_z"
NORMALIZATIONS = (MINMAX, BASELINE_Z)

DOMAINS = ("sleep", "fatigue", "cognitive", "physical")

INDIVIDUAL = "individual"
COLLECTIVE = "collective"
TASK_KINDS = (INDIVIDUAL, COLLECTIVE)

ALL = "all"
AT_LEAST = "at_least"


class ValidationError(ValueError):
    """Dato de entrada inválido. El mensaje dice qué y dónde."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _finite(value: Any, name: str) -> float:
    _check(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
        f"{name} debe ser un número finito: {value!r}",
    )
    return float(value)


def check_id(value: Any, what: str) -> str:
    _check(isinstance(value, str) and bool(ID_PATTERN.fullmatch(value)), f"{what} inválido: {value!r}")
    return value


def parse_clock(value: Any, name: str) -> float:
    """'HH:MM' -> segundos desde medianoche. Admite '24:00' como fin de día."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = _finite(value, name)
    else:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value).strip())
        _check(match is not None, f"{name}: hora inválida (se espera HH:MM): {value!r}")
        hours, minutes = int(match.group(1)), int(match.group(2))
        _check(minutes < 60, f"{name}: minutos fuera de rango: {value!r}")
        seconds = hours * 3600.0 + minutes * 60.0
    _check(0 <= seconds <= DAY_S, f"{name}: hora fuera del día: {value!r}")
    return seconds


def format_clock(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


# --- parámetros y mediciones ---------------------------------------------------


@dataclass(frozen=True)
class ParameterSpec:
    """Definición de un parámetro del vector de estado.

    `lo`/`hi` son el rango fisiológico para `minmax`. `validity_h` es cuánto
    tiempo vale una medición; pasado ese plazo el parámetro es desconocido.
    """

    id: str
    kind: str
    normalization: str
    validity_h: float
    domain: str
    unit: str = ""
    lo: float | None = None
    hi: float | None = None
    description: str = ""

    def __post_init__(self) -> None:
        check_id(self.id, "Identificador de parámetro")
        where = f"Parámetro {self.id}"
        _check(self.kind in KINDS, f"{where}: kind debe ser uno de {KINDS}")
        _check(self.normalization in NORMALIZATIONS, f"{where}: normalization debe ser una de {NORMALIZATIONS}")
        _check(self.domain in DOMAINS, f"{where}: domain debe ser uno de {DOMAINS}")
        _check(_finite(self.validity_h, f"{where}: validity_h") > 0, f"{where}: validity_h debe ser > 0")
        if self.normalization == MINMAX:
            _check(self.lo is not None and self.hi is not None, f"{where}: minmax necesita lo y hi")
            _check(_finite(self.lo, f"{where}: lo") < _finite(self.hi, f"{where}: hi"), f"{where}: se requiere lo < hi")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ParameterSpec":
        return cls(**_only(raw, cls, "parámetro"))

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)


@dataclass(frozen=True)
class Measurement:
    """Una medición. `confidence` solo si la fuente la da: nunca se inventa."""

    parameter: str
    value: float
    measured_at: float  # segundos de misión
    source: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        check_id(self.parameter, "Parámetro de la medición")
        where = f"Medición de {self.parameter}"
        object.__setattr__(self, "value", _finite(self.value, f"{where}: value"))
        object.__setattr__(self, "measured_at", _finite(self.measured_at, f"{where}: measured_at"))
        _check(isinstance(self.source, str) and self.source != "", f"{where}: falta source")
        if self.confidence is not None:
            c = _finite(self.confidence, f"{where}: confidence")
            _check(0 <= c <= 1, f"{where}: confidence debe estar en [0, 1]")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Measurement":
        return cls(**_only(raw, cls, "medición"))

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)


@dataclass(frozen=True)
class Baseline:
    """Línea base individual de un parámetro (media y desviación típica)."""

    parameter: str
    mean: float
    sd: float

    def __post_init__(self) -> None:
        check_id(self.parameter, "Parámetro de la línea base")
        _finite(self.mean, f"Línea base de {self.parameter}: mean")
        _check(_finite(self.sd, f"Línea base de {self.parameter}: sd") > 0, f"Línea base de {self.parameter}: sd debe ser > 0")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Baseline":
        return cls(**_only(raw, cls, "línea base"))

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)


# --- astronautas ---------------------------------------------------------------

Span = tuple[float, float]


def _spans(raw: Iterable[Any], where: str) -> tuple[Span, ...]:
    out = []
    for item in raw:
        _check(isinstance(item, (list, tuple)) and len(item) == 2, f"{where}: cada tramo es [inicio, fin]")
        start, end = parse_clock(item[0], where), parse_clock(item[1], where)
        _check(start < end, f"{where}: tramo vacío o invertido {item!r}")
        out.append((start, end))
    return tuple(sorted(out))


@dataclass(frozen=True)
class Astronaut:
    """Astronauta, identificado por un seudónimo.

    `unavailable` son tramos del día en que no puede recibir tareas, además de
    su horario de sueño. `work` es su horario de trabajo: fuera de él no se
    asignan tareas. `max_work_h` sustituye al límite general si se indica.
    """

    id: str
    qualifications: frozenset[str] = frozenset()
    work: tuple[Span, ...] = ()
    sleep: tuple[Span, ...] = ()
    unavailable: tuple[Span, ...] = ()
    measurements: tuple[Measurement, ...] = ()
    baselines: Mapping[str, Baseline] = field(default_factory=dict)
    max_work_h: float | None = None

    def __post_init__(self) -> None:
        check_id(self.id, "Identificador de astronauta")
        object.__setattr__(self, "qualifications", frozenset(self.qualifications))
        for q in self.qualifications:
            check_id(q, f"Cualificación de {self.id}")
        _check(len(self.work) > 0, f"Astronauta {self.id}: falta su horario de trabajo")
        for name in ("work", "sleep", "unavailable"):
            spans = getattr(self, name)
            for (_, end), (start, _) in zip(spans, spans[1:]):
                _check(end <= start, f"Astronauta {self.id}: tramos de {name} solapados")
        for key, baseline in self.baselines.items():
            _check(key == baseline.parameter, f"Astronauta {self.id}: línea base {key} mal indexada")
        if self.max_work_h is not None:
            _check(0 < _finite(self.max_work_h, f"{self.id}: max_work_h") <= 24, f"{self.id}: max_work_h fuera de (0, 24]")

    def latest(self, parameter: str) -> Measurement | None:
        """Última medición de un parámetro, sin mirar su vigencia."""
        found = [m for m in self.measurements if m.parameter == parameter]
        return max(found, key=lambda m: m.measured_at) if found else None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Astronaut":
        data = _only(raw, cls, "astronauta")
        where = f"Astronauta {data.get('id')!r}"
        for name in ("work", "sleep", "unavailable"):
            data[name] = _spans(data.get(name, ()), f"{where}: {name}")
        data["qualifications"] = frozenset(data.get("qualifications", ()))
        data["measurements"] = tuple(Measurement.from_dict(m) for m in data.get("measurements", ()))
        baselines = [Baseline.from_dict(b) for b in data.get("baselines", ())]
        _check(len({b.parameter for b in baselines}) == len(baselines), f"{where}: líneas base repetidas")
        data["baselines"] = {b.parameter: b for b in baselines}
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "qualifications": sorted(self.qualifications),
            "work": [[format_clock(a), format_clock(b)] for a, b in self.work],
            "sleep": [[format_clock(a), format_clock(b)] for a, b in self.sleep],
            "unavailable": [[format_clock(a), format_clock(b)] for a, b in self.unavailable],
            "measurements": [m.to_dict() for m in self.measurements],
            "baselines": [self.baselines[k].to_dict() for k in sorted(self.baselines)],
            "max_work_h": self.max_work_h,
        }


# --- tareas --------------------------------------------------------------------


@dataclass(frozen=True)
class Requirement:
    """Requisito de una tarea sobre un parámetro.

    Los umbrales van en la escala natural del parámetro: unidades físicas si se
    normaliza por rango, puntuación z si se normaliza por línea base. `critical`
    lo convierte en restricción dura: si no se cumple, o el dato es desconocido,
    el astronauta no es elegible.
    """

    parameter: str
    min: float | None = None
    max: float | None = None
    weight: float = 1.0
    critical: bool = False

    def __post_init__(self) -> None:
        check_id(self.parameter, "Parámetro del requisito")
        where = f"Requisito sobre {self.parameter}"
        _check(self.min is not None or self.max is not None, f"{where}: indica min, max o ambos")
        if self.min is not None:
            _finite(self.min, f"{where}: min")
        if self.max is not None:
            _finite(self.max, f"{where}: max")
        if self.min is not None and self.max is not None:
            _check(self.min <= self.max, f"{where}: se requiere min <= max")
        _check(_finite(self.weight, f"{where}: weight") >= 0, f"{where}: weight debe ser >= 0")
        _check(self.weight > 0 or self.critical, f"{where}: con weight 0 solo tiene sentido si es crítico")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Requirement":
        return cls(**_only(raw, cls, "requisito"))

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)


@dataclass(frozen=True)
class TeamQualification:
    """Cualificación exigida al equipo: a todos o al menos a `count` miembros."""

    qualification: str
    mode: str = AT_LEAST
    count: int = 1

    def __post_init__(self) -> None:
        check_id(self.qualification, "Cualificación de equipo")
        _check(self.mode in (ALL, AT_LEAST), f"Cualificación {self.qualification}: mode debe ser all o at_least")
        if self.mode == AT_LEAST:
            _check(isinstance(self.count, int) and self.count >= 1, f"Cualificación {self.qualification}: count >= 1")

    def satisfied_by(self, qualifications: Iterable[frozenset[str]]) -> bool:
        holders = [self.qualification in q for q in qualifications]
        return all(holders) if self.mode == ALL else sum(holders) >= self.count

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TeamQualification":
        return cls(**_only(raw, cls, "cualificación de equipo"))

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)


@dataclass(frozen=True)
class Task:
    """Tarea del día.

    - `importance` va en la escala configurada (por defecto 1–5).
    - `qualifications` y `requirements` se exigen a cada participante.
    - `team_qualifications` se exigen al equipo en conjunto.
    - `earliest`/`latest`: ventana en la que debe empezar y terminar.
    - `mandatory`: debe quedar cubierta hoy. Si no, es aplazable.
    - `resources`: dos tareas que comparten un recurso no pueden solaparse.
    - `low_load`: solo admite False, para excluir una tarea de las de baja carga.
    - `only_for`: si no está vacío, solo esas personas pueden hacerla (p. ej. el
      ejercicio diario de cada astronauta).
    - `interdependence` ∈ [0, 1]: cuánto depende el resultado de que el equipo
      funcione como uno. Escala el peso de la compatibilidad; None = 1.
    """

    id: str
    name: str
    kind: str
    importance: float
    duration_min: float
    earliest: float = 0.0
    latest: float = DAY_S
    category: str = ""
    requirements: tuple[Requirement, ...] = ()
    qualifications: frozenset[str] = frozenset()
    team_qualifications: tuple[TeamQualification, ...] = ()
    min_people: int = 1
    max_people: int = 1
    intensity: float = 0.5
    demanding: bool = False
    mandatory: bool = True
    resources: frozenset[str] = frozenset()
    low_load: bool | None = None
    only_for: frozenset[str] = frozenset()
    interdependence: float | None = None

    def __post_init__(self) -> None:
        check_id(self.id, "Identificador de tarea")
        where = f"Tarea {self.id}"
        if not self.category:
            object.__setattr__(self, "category", self.id)
        check_id(self.category, f"{where}: categoría")
        object.__setattr__(self, "qualifications", frozenset(self.qualifications))
        object.__setattr__(self, "resources", frozenset(self.resources))
        object.__setattr__(self, "only_for", frozenset(self.only_for))
        for a in self.only_for:
            check_id(a, f"{where}: only_for")
        if self.interdependence is not None:
            _check(0 <= _finite(self.interdependence, f"{where}: interdependence") <= 1,
                   f"{where}: interdependence debe estar en [0, 1]")
        _check(self.kind in TASK_KINDS, f"{where}: kind debe ser individual o collective")
        _finite(self.importance, f"{where}: importance")
        duration = _finite(self.duration_min, f"{where}: duration_min")
        _check(duration > 0, f"{where}: duration_min debe ser > 0")
        _check(0 <= self.earliest < self.latest <= DAY_S, f"{where}: ventana inválida")
        _check(duration * 60 <= self.latest - self.earliest, f"{where}: no cabe en su ventana")
        _check(
            isinstance(self.min_people, int) and isinstance(self.max_people, int)
            and 1 <= self.min_people <= self.max_people,
            f"{where}: se requiere 1 <= min_people <= max_people",
        )
        if self.kind == INDIVIDUAL:
            _check(self.max_people == 1, f"{where}: una tarea individual es de una persona")
            _check(not self.team_qualifications, f"{where}: una tarea individual no tiene cualificaciones de equipo")
        else:
            _check(self.max_people >= 2, f"{where}: una tarea colectiva admite al menos 2 personas")
        _check(0 <= _finite(self.intensity, f"{where}: intensity") <= 1, f"{where}: intensity debe estar en [0, 1]")
        params = [r.parameter for r in self.requirements]
        _check(len(set(params)) == len(params), f"{where}: requisitos repetidos")
        _check(self.low_load in (None, False), f"{where}: low_load solo puede forzarse a false")
        for tq in self.team_qualifications:
            if tq.mode == AT_LEAST:
                _check(tq.count <= self.max_people, f"{where}: {tq.qualification} exige más personas que max_people")

    @property
    def duration_s(self) -> float:
        return self.duration_min * 60.0

    @property
    def collective(self) -> bool:
        return self.kind == COLLECTIVE

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Task":
        data = _only(raw, cls, "tarea")
        where = f"Tarea {data.get('id')!r}"
        if "earliest" in data:
            data["earliest"] = parse_clock(data["earliest"], f"{where}: earliest")
        if "latest" in data:
            data["latest"] = parse_clock(data["latest"], f"{where}: latest")
        data["requirements"] = tuple(Requirement.from_dict(r) for r in data.get("requirements", ()))
        data["team_qualifications"] = tuple(
            TeamQualification.from_dict(q) for q in data.get("team_qualifications", ())
        )
        data["qualifications"] = frozenset(data.get("qualifications", ()))
        data["resources"] = frozenset(data.get("resources", ()))
        data["only_for"] = frozenset(data.get("only_for", ()))
        if data.get("kind") == INDIVIDUAL:
            data.setdefault("min_people", 1)
            data.setdefault("max_people", 1)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        out = _asdict(self)
        out["earliest"] = format_clock(self.earliest)
        out["latest"] = format_clock(self.latest)
        out["requirements"] = [r.to_dict() for r in self.requirements]
        out["team_qualifications"] = [q.to_dict() for q in self.team_qualifications]
        out["qualifications"] = sorted(self.qualifications)
        out["resources"] = sorted(self.resources)
        out["only_for"] = sorted(self.only_for)
        return out


# --- utilidades ----------------------------------------------------------------


def _only(raw: Mapping[str, Any], cls: type, what: str) -> dict[str, Any]:
    """Copia el diccionario rechazando campos desconocidos (erratas en el JSON)."""
    _check(isinstance(raw, Mapping), f"Se esperaba un objeto para {what}: {raw!r}")
    known = set(cls.__dataclass_fields__)
    unknown = set(raw) - known
    _check(not unknown, f"Campos desconocidos en {what} {raw.get('id', '')!r}: {sorted(unknown)}")
    return dict(raw)


def _asdict(obj: Any) -> dict[str, Any]:
    return {name: getattr(obj, name) for name in obj.__dataclass_fields__}
