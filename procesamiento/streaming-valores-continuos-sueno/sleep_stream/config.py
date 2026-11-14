"""Configuración del módulo por variables de entorno (prefijo SLEEP_).

Todos los valores son puntos de partida de diseño, no requisitos de NASA ni
umbrales médicos. Los rangos de `MetricSpec` describen lo que el sensor puede
medir de forma plausible: un valor fuera de rango es un dato inválido, no un
hallazgo clínico.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Sin ':' para que una clave Redis no pueda confundir astronauta y sesión
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")


class ConfigError(ValueError):
    """Configuración inválida."""


def check_id(value: Any, what: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(f"{what} inválido: {value!r}")
    return value


@dataclass(frozen=True)
class MetricSpec:
    """Una métrica biométrica conocida.

    `valid_min`/`valid_max`: rango de plausibilidad del sensor, en `unit`.
    `hist_*`: histograma de bins fijos para los percentiles aproximados; los
    valores válidos fuera de él caen en el primer o el último bin.
    `min_std`: suelo de la desviación típica en la detección de anomalías
    (resolución del sensor), para que una señal cuantizada no dé z infinitas.
    """

    name: str
    unit: str
    valid_min: float
    valid_max: float
    hist_min: float
    hist_max: float
    hist_bins: int
    min_std: float

    def __post_init__(self) -> None:
        check_id(self.name, "Nombre de métrica")
        if not self.valid_min < self.valid_max:
            raise ConfigError(f"{self.name}: se requiere valid_min < valid_max")
        if not self.hist_min < self.hist_max or self.hist_bins < 1:
            raise ConfigError(f"{self.name}: histograma inválido")
        if not self.min_std > 0:
            raise ConfigError(f"{self.name}: min_std debe ser > 0")

    @property
    def bin_width(self) -> float:
        return (self.hist_max - self.hist_min) / self.hist_bins

    def bin_of(self, value: float) -> int:
        index = int((value - self.hist_min) / self.bin_width)
        return min(max(index, 0), self.hist_bins - 1)


DEFAULT_METRICS = (
    MetricSpec("heart_rate", "bpm", 20.0, 250.0, 30.0, 130.0, 100, 1.0),
    MetricSpec("heart_rate_variability", "ms", 0.0, 400.0, 0.0, 200.0, 100, 2.0),
    MetricSpec("spo2", "%", 50.0, 100.0, 80.0, 100.0, 40, 0.5),
    MetricSpec("respiratory_rate", "rpm", 2.0, 70.0, 5.0, 35.0, 60, 0.5),
    MetricSpec("skin_temperature", "degC", 20.0, 45.0, 28.0, 40.0, 120, 0.1),
    MetricSpec("movement", "a.u.", 0.0, 10.0, 0.0, 2.0, 100, 0.02),
)


@dataclass(frozen=True)
class Settings:
    metrics: tuple[MetricSpec, ...] = DEFAULT_METRICS

    # Ventanas: tamaño de cada nivel (s) y cuánto tiempo se conserva cada nivel,
    # medido hacia atrás desde el último dato, antes de fundirlo en el siguiente.
    # El último nivel se conserva hasta el final de la sesión.
    levels_s: tuple[int, ...] = (60, 300, 900, 1800)
    retain_s: tuple[int, ...] = (900, 3600, 7200)
    lateness_s: int = 120          # espera antes de dar por cerrado un minuto
    max_session_s: int = 86400     # duración máxima de una sesión
    dedup_resolution_s: float = 1.0  # dos registros en el mismo intervalo son el mismo

    # Anomalías estadísticas (no diagnósticos)
    ewma_halflife_s: float = 600.0
    z_threshold: float = 4.0
    warmup_n: int = 30
    baseline_z_threshold: float = 4.0
    episode_gap_s: float = 120.0
    max_anomalies: int = 200

    # Actigrafía: un minuto es "activo" si la media de movimiento supera el umbral
    activity_metric: str = "movement"
    activity_threshold: float = 0.3

    # Redis
    prefix: str = "orbivia:sleep"
    group: str = "sleep-processors"
    batch_count: int = 500
    block_ms: int = 1000
    claim_idle_ms: int = 30000
    dead_maxlen: int = 10000
    completed_ttl_s: int = 172800     # estado temporal tras persistir el resumen
    summary_ttl_s: int = 604800       # copia del resumen en Redis (el duradero está en Postgres)
    max_tx_retries: int = 20

    # Origen de los segundos de misión, en epoch Unix (para el planificador)
    mission_epoch_s: float = 0.0

    def __post_init__(self) -> None:
        if len(self.levels_s) < 1 or any(size <= 0 for size in self.levels_s):
            raise ConfigError("levels_s necesita al menos un tamaño positivo")
        for small, big in zip(self.levels_s, self.levels_s[1:]):
            if big <= small or big % small:
                raise ConfigError("Cada nivel debe ser múltiplo estricto del anterior")
        if len(self.retain_s) != len(self.levels_s) - 1:
            raise ConfigError("retain_s necesita un valor por cada nivel salvo el último")
        if self.retain_s and self.retain_s[0] < self.lateness_s + self.levels_s[0]:
            raise ConfigError("retain_s[0] debe cubrir lateness_s más una ventana del primer nivel")
        # Si un nivel grueso viviera menos que uno fino, el colapso dejaría ventanas huérfanas
        if any(later < earlier for earlier, later in zip(self.retain_s, self.retain_s[1:])):
            raise ConfigError("retain_s no puede decrecer")
        if self.dedup_resolution_s <= 0 or self.max_session_s <= 0:
            raise ConfigError("dedup_resolution_s y max_session_s deben ser > 0")
        names = [m.name for m in self.metrics]
        if len(set(names)) != len(names):
            raise ConfigError("Métricas repetidas")

    @property
    def specs(self) -> dict[str, MetricSpec]:
        return {m.name: m for m in self.metrics}

    @property
    def version(self) -> str:
        """Huella corta de los parámetros que afectan al resultado."""
        payload = asdict(self)
        for key in ("prefix", "group", "batch_count", "block_ms", "claim_idle_ms",
                    "dead_maxlen", "completed_ttl_s", "summary_ttl_s", "max_tx_retries"):
            payload.pop(key)
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def _ints(text: str, name: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in text.split(",") if x.strip())
    except ValueError as error:
        raise ConfigError(f"{name} debe ser una lista de enteros: {text!r}") from error


def load_metrics(raw: Any) -> tuple[MetricSpec, ...]:
    """Lista de objetos con los campos de `MetricSpec`."""
    if not isinstance(raw, list):
        raise ConfigError("El fichero de métricas debe ser una lista")
    try:
        return tuple(MetricSpec(**item) for item in raw)
    except TypeError as error:
        raise ConfigError(f"Métrica mal definida: {error}") from error


def load_settings(env: Mapping[str, str]) -> Settings:
    defaults = Settings()
    values: dict[str, Any] = {}

    def number(name: str, key: str, cast: type) -> None:
        text = env.get(name)
        if text is None or text == "":
            return
        try:
            values[key] = cast(text)
        except ValueError as error:
            raise ConfigError(f"{name} debe ser numérico: {text!r}") from error

    if env.get("SLEEP_METRICS_FILE"):
        raw = json.loads(Path(env["SLEEP_METRICS_FILE"]).read_text(encoding="utf-8"))
        values["metrics"] = load_metrics(raw)
    if env.get("SLEEP_LEVELS_S"):
        values["levels_s"] = _ints(env["SLEEP_LEVELS_S"], "SLEEP_LEVELS_S")
    if env.get("SLEEP_RETAIN_S"):
        values["retain_s"] = _ints(env["SLEEP_RETAIN_S"], "SLEEP_RETAIN_S")
    for name, key, cast in (
        ("SLEEP_LATENESS_S", "lateness_s", int),
        ("SLEEP_MAX_SESSION_S", "max_session_s", int),
        ("SLEEP_DEDUP_RESOLUTION_S", "dedup_resolution_s", float),
        ("SLEEP_EWMA_HALFLIFE_S", "ewma_halflife_s", float),
        ("SLEEP_Z_THRESHOLD", "z_threshold", float),
        ("SLEEP_WARMUP_N", "warmup_n", int),
        ("SLEEP_BASELINE_Z_THRESHOLD", "baseline_z_threshold", float),
        ("SLEEP_EPISODE_GAP_S", "episode_gap_s", float),
        ("SLEEP_MAX_ANOMALIES", "max_anomalies", int),
        ("SLEEP_ACTIVITY_THRESHOLD", "activity_threshold", float),
        ("SLEEP_BATCH_COUNT", "batch_count", int),
        ("SLEEP_BLOCK_MS", "block_ms", int),
        ("SLEEP_CLAIM_IDLE_MS", "claim_idle_ms", int),
        ("SLEEP_COMPLETED_TTL_S", "completed_ttl_s", int),
        ("SLEEP_SUMMARY_TTL_S", "summary_ttl_s", int),
        ("SLEEP_MISSION_EPOCH_S", "mission_epoch_s", float),
    ):
        number(name, key, cast)
    for name, key in (("SLEEP_ACTIVITY_METRIC", "activity_metric"),
                      ("SLEEP_PREFIX", "prefix"), ("SLEEP_GROUP", "group")):
        if env.get(name):
            values[key] = env[name]
    return Settings(**{**{f: getattr(defaults, f) for f in defaults.__dataclass_fields__}, **values})
