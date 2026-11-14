"""Configuración: fichero TOML con sobrescritura por variables de entorno CP_*.

Los pesos se cambian sin tocar el código: en el fichero, o con
CP_<SECCIÓN>_<CLAVE> (por ejemplo CP_WEIGHTS_GAMMA=0.5).
"""

import hashlib
import json
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from .model import ParameterSpec, ValidationError

DEFAULT_FILE = Path(__file__).resolve().parent.parent / "config" / "default.toml"


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


@dataclass(frozen=True)
class Weights:
    alpha_state: float = 1.0
    alpha_repetition: float = 0.3
    alpha_uncertainty: float = 0.5
    alpha_equity: float = 0.5
    beta_spread: float = 0.5
    gamma: float = 0.3
    mu: float = 0.2

    def __post_init__(self) -> None:
        for f in fields(self):
            _check(getattr(self, f.name) >= 0, f"weights.{f.name} debe ser >= 0")


@dataclass(frozen=True)
class Stages:
    mode: str = "lexicographic"
    epsilon: float = 0.05
    epsilon_abs: float = 0.2  # tolerancia absoluta: con una tripulación sana el óptimo es casi 0
    uncovered_penalty: float = 10.0  # solo en modo weighted: coste por tarea aplazable sin cubrir

    def __post_init__(self) -> None:
        _check(self.mode in ("lexicographic", "weighted"), "stages.mode debe ser lexicographic o weighted")
        _check(0 <= self.epsilon <= 1, "stages.epsilon debe estar en [0, 1]")
        _check(self.epsilon_abs >= 0, "stages.epsilon_abs debe ser >= 0")
        _check(self.uncovered_penalty >= 0, "stages.uncovered_penalty debe ser >= 0")


@dataclass(frozen=True)
class Importance:
    scale_min: float = 1
    scale_max: float = 5

    def __post_init__(self) -> None:
        _check(self.scale_min < self.scale_max, "importance: se requiere scale_min < scale_max")

    def normalize(self, raw: float) -> float:
        """Escala configurada -> (0, 1]. El mínimo de la escala no vale 0: toda tarea importa algo."""
        _check(self.scale_min <= raw <= self.scale_max, f"Importancia {raw} fuera de la escala")
        steps = self.scale_max - self.scale_min + 1
        return (raw - self.scale_min + 1) / steps


@dataclass(frozen=True)
class Repetition:
    window_days: int = 14
    tau_days: float = 3.0

    def __post_init__(self) -> None:
        _check(self.window_days >= 1, "repetition.window_days debe ser >= 1")
        _check(self.tau_days > 0, "repetition.tau_days debe ser > 0")


@dataclass(frozen=True)
class Adequacy:
    max_domain_share: float = 0.5

    def __post_init__(self) -> None:
        _check(0 < self.max_domain_share <= 1, "adequacy.max_domain_share debe estar en (0, 1]")


@dataclass(frozen=True)
class Workload:
    capacity_min: float = 0.5

    def __post_init__(self) -> None:
        _check(0 < self.capacity_min <= 1, "workload.capacity_min debe estar en (0, 1]")


@dataclass(frozen=True)
class Limits:
    slot_min: int = 15
    max_work_h: float = 8.0
    max_demanding_per_day: int = 2
    rest_after_demanding_min: float = 30

    def __post_init__(self) -> None:
        _check(self.slot_min >= 1 and 1440 % self.slot_min == 0, "limits.slot_min debe dividir el día")
        _check(0 < self.max_work_h <= 24, "limits.max_work_h fuera de (0, 24]")
        _check(self.max_demanding_per_day >= 0, "limits.max_demanding_per_day debe ser >= 0")
        _check(self.rest_after_demanding_min >= 0, "limits.rest_after_demanding_min debe ser >= 0")


@dataclass(frozen=True)
class LowLoad:
    max_intensity: float = 0.4
    max_importance: float = 0.6

    def __post_init__(self) -> None:
        _check(0 <= self.max_intensity <= 1, "low_load.max_intensity debe estar en [0, 1]")
        _check(0 < self.max_importance <= 1, "low_load.max_importance debe estar en (0, 1]")


@dataclass(frozen=True)
class Social:
    max_age_days: int = 2
    need_review: float = 1.0
    need_follow_up: float = 0.5

    def __post_init__(self) -> None:
        _check(self.max_age_days >= 1, "social.max_age_days debe ser >= 1")
        _check(0 <= self.need_follow_up <= self.need_review <= 1, "social: se requiere 0 <= follow_up <= review <= 1")


@dataclass(frozen=True)
class Solver:
    seed: int = 42
    workers: int = 1
    time_limit_s: float = 20.0
    max_team_candidates: int = 500

    def __post_init__(self) -> None:
        _check(self.workers >= 1, "solver.workers debe ser >= 1")
        _check(self.time_limit_s > 0, "solver.time_limit_s debe ser > 0")
        _check(self.max_team_candidates >= 1, "solver.max_team_candidates debe ser >= 1")


SECTIONS: dict[str, type] = {
    "weights": Weights,
    "stages": Stages,
    "importance": Importance,
    "repetition": Repetition,
    "adequacy": Adequacy,
    "workload": Workload,
    "limits": Limits,
    "low_load": LowLoad,
    "social": Social,
    "solver": Solver,
}


@dataclass(frozen=True)
class PlannerConfig:
    weights: Weights = field(default_factory=Weights)
    stages: Stages = field(default_factory=Stages)
    importance: Importance = field(default_factory=Importance)
    repetition: Repetition = field(default_factory=Repetition)
    adequacy: Adequacy = field(default_factory=Adequacy)
    workload: Workload = field(default_factory=Workload)
    limits: Limits = field(default_factory=Limits)
    low_load: LowLoad = field(default_factory=LowLoad)
    social: Social = field(default_factory=Social)
    solver: Solver = field(default_factory=Solver)
    parameters: Mapping[str, ParameterSpec] = field(default_factory=dict)

    @property
    def version(self) -> str:
        """Huella corta y estable de toda la configuración, para la salida."""
        payload = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {name: asdict(getattr(self, name)) for name in SECTIONS}
        out["parameters"] = [self.parameters[k].to_dict() for k in sorted(self.parameters)]
        return out


def _coerce(value: Any, default: Any, name: str) -> Any:
    """Convierte al tipo del valor por defecto; los textos vienen del entorno."""
    if isinstance(default, bool):
        if isinstance(value, str):
            lowered = value.strip().lower()
            _check(lowered in ("true", "false", "1", "0"), f"{name} debe ser true o false")
            return lowered in ("true", "1")
        return bool(value)
    if isinstance(default, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise ValidationError(f"{name} debe ser numérico: {value!r}") from error
        if isinstance(default, int):
            _check(number.is_integer(), f"{name} debe ser entero: {value!r}")
            return int(number)
        return number
    return str(value)


def _section(cls: type, raw: Mapping[str, Any], env: Mapping[str, str], name: str) -> Any:
    _check(isinstance(raw, Mapping), f"[{name}] debe ser una tabla")
    defaults = cls()
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    _check(not unknown, f"Claves desconocidas en [{name}]: {sorted(unknown)}")
    values = {}
    for f in fields(cls):
        default = getattr(defaults, f.name)
        key = f"CP_{name}_{f.name}".upper()
        if env.get(key, "") != "":
            values[f.name] = _coerce(env[key], default, key)
        elif f.name in raw:
            values[f.name] = _coerce(raw[f.name], default, f"{name}.{f.name}")
    return replace(defaults, **values)


def load_config(path: str | Path | None = None, env: Mapping[str, str] | None = None) -> PlannerConfig:
    """Lee la configuración. Orden de prioridad: entorno, fichero, valores por defecto."""
    env = dict(env or {})
    path = Path(path or env.get("CP_CONFIG_FILE") or DEFAULT_FILE)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ValidationError(f"{path}: TOML inválido: {error}") from error

    unknown = set(raw) - set(SECTIONS) - {"parameters"}
    _check(not unknown, f"Secciones desconocidas en {path.name}: {sorted(unknown)}")
    sections = {name: _section(cls, raw.get(name, {}), env, name) for name, cls in SECTIONS.items()}

    specs = [ParameterSpec.from_dict(p) for p in raw.get("parameters", ())]
    ids = [s.id for s in specs]
    _check(len(set(ids)) == len(ids), f"Parámetros repetidos en {path.name}")
    return PlannerConfig(**sections, parameters={s.id: s for s in specs})
