"""Configuración del servicio por variables de entorno (prefijo SG_)."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .isolation import IsolationConfig
from .params import DAY_S, Params
from .recommender import RecommenderConfig
from .schedule import KINDS, FixedSchedule

DEFAULT_CREW = ("A1", "A2", "A3", "A4", "A5", "A6")
# Horario por defecto: sueño 22:00–06:00 y trabajo 08:00–16:00 (8 h de ocio)
DEFAULT_BLOCKS = {"sleep": [("22:00", "06:00")], "work": [("08:00", "16:00")]}

Blocks = dict[str, dict[str, list[tuple[float, float]]]]


def parse_time_of_day(text: str) -> float:
    """'HH:MM' -> segundos desde medianoche."""
    try:
        hours, minutes = text.strip().split(":")
        seconds = int(hours) * 3600 + int(minutes) * 60
    except ValueError as error:
        raise ValueError(f"Hora inválida (se espera HH:MM): {text!r}") from error
    if not 0 <= seconds < DAY_S:
        raise ValueError(f"Hora fuera de rango: {text!r}")
    return float(seconds)


def parse_blocks(raw: Mapping[str, Mapping[str, list]]) -> Blocks:
    """Convierte {astronauta: {tipo: [[inicio, fin], ...]}} con horas 'HH:MM'."""
    blocks: Blocks = {}
    for astronaut, kinds in raw.items():
        unknown = set(kinds) - set(KINDS)
        if unknown:
            raise ValueError(f"Tipos de bloque desconocidos para {astronaut}: {sorted(unknown)}")
        blocks[astronaut] = {
            kind: [(parse_time_of_day(a), parse_time_of_day(b)) for a, b in spans]
            for kind, spans in kinds.items()
        }
    return blocks


def params_version(params: Params) -> str:
    """Huella corta y estable de los parámetros, para el histórico."""
    payload = json.dumps(asdict(params), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Settings:
    params: Params = field(default_factory=Params)
    crew: tuple[str, ...] = DEFAULT_CREW
    blocks: Blocks = field(default_factory=dict)
    schedule_jitter_s: float = 0.0
    schedule_seed: int = 42
    source: str = "simulation"
    stream: str = "orbivia:positions"
    checkpoint_every_s: float = 30.0
    isolation: IsolationConfig = field(default_factory=IsolationConfig)
    recommender: RecommenderConfig = field(default_factory=RecommenderConfig)
    # Grafo para Tierra
    layout: str = "spring"
    layout_seed: int = 42
    output_dir: str | None = None
    heartbeat_file: str | None = None
    # Simulación
    sim_scenario: str = "homogeneous"
    sim_seed: int = 42
    sim_period_s: float = 10.0
    sim_speedup: float = 3600.0
    sim_days: int | None = 60

    def build_schedule(self) -> FixedSchedule:
        return FixedSchedule(self.blocks, jitter_s=self.schedule_jitter_s, seed=self.schedule_seed)


def load_settings(env: Mapping[str, str]) -> Settings:
    defaults = Params()

    def number(name: str, default: float) -> float:
        value = env.get(name)
        if value is None or value == "":
            return default
        try:
            return float(value)
        except ValueError as error:
            raise ValueError(f"{name} debe ser numérico: {value!r}") from error

    cutoff = env.get("SG_DAY_CUTOFF")
    params = Params(
        d_in_m=number("SG_D_IN_M", defaults.d_in_m),
        d_out_m=number("SG_D_OUT_M", defaults.d_out_m),
        min_dwell_s=number("SG_MIN_DWELL_S", defaults.min_dwell_s),
        max_gap_s=number("SG_MAX_GAP_S", defaults.max_gap_s),
        day_cutoff_s=parse_time_of_day(cutoff) if cutoff else defaults.day_cutoff_s,
        normalization=env.get("SG_NORMALIZATION") or defaults.normalization,
        weight_fn=env.get("SG_WEIGHT_FN") or defaults.weight_fn,
        kappa=number("SG_KAPPA", defaults.kappa),
        min_leisure_s=number("SG_MIN_LEISURE_S", defaults.min_leisure_s),
        min_overlap_s=number("SG_MIN_OVERLAP_S", defaults.min_overlap_s),
        min_coverage=number("SG_MIN_COVERAGE", defaults.min_coverage),
    )

    crew_text = env.get("SG_CREW")
    crew = tuple(a.strip() for a in crew_text.split(",") if a.strip()) if crew_text else DEFAULT_CREW
    if len(crew) < 2:
        raise ValueError("SG_CREW necesita al menos dos astronautas")

    if env.get("SG_SCHEDULE_FILE"):
        raw_blocks = json.loads(Path(env["SG_SCHEDULE_FILE"]).read_text(encoding="utf-8"))
    elif env.get("SG_SCHEDULE_JSON"):
        raw_blocks = json.loads(env["SG_SCHEDULE_JSON"])
    else:
        raw_blocks = {}
    # Quien no tenga horario propio usa el horario por defecto
    blocks = parse_blocks({a: raw_blocks.get(a, DEFAULT_BLOCKS) for a in crew})

    iso = IsolationConfig()
    isolation = IsolationConfig(
        warmup_days=int(number("SG_BASELINE_WARMUP_DAYS", iso.warmup_days)),
        window_days=int(number("SG_BASELINE_WINDOW_DAYS", iso.window_days)),
        lag_days=int(number("SG_BASELINE_LAG_DAYS", iso.lag_days)),
        z_alert=number("SG_ALERT_Z", iso.z_alert),
        persist_k=int(number("SG_ALERT_K", iso.persist_k)),
        persist_m=int(number("SG_ALERT_M", iso.persist_m)),
        crew_ratio_min=number("SG_CREW_RATIO_MIN", iso.crew_ratio_min),
        edge_min_w=number("SG_EDGE_MIN_W", iso.edge_min_w),
        smooth_days=int(number("SG_SMOOTH_DAYS", iso.smooth_days)),
        min_modularity=number("SG_MIN_MODULARITY", iso.min_modularity),
    )
    rec = RecommenderConfig()
    sizes = env.get("SG_REC_GROUP_SIZES")
    try:
        group_sizes = tuple(int(x) for x in sizes.split(",")) if sizes else rec.group_sizes
    except ValueError as error:
        raise ValueError(f"SG_REC_GROUP_SIZES debe ser una lista de enteros: {sizes!r}") from error
    if any(size < 2 or size > 3 for size in group_sizes):
        raise ValueError("SG_REC_GROUP_SIZES solo admite grupos de 2 o 3")
    recommender = RecommenderConfig(
        max_per_day=int(number("SG_REC_MAX_PER_DAY", rec.max_per_day)),
        max_per_person_week=int(number("SG_REC_MAX_PER_PERSON_WEEK", rec.max_per_person_week)),
        min_window_s=number("SG_REC_MIN_WINDOW_S", rec.min_window_s),
        max_leisure_fraction=number("SG_REC_MAX_LEISURE_FRACTION", rec.max_leisure_fraction),
        group_sizes=group_sizes,
    )
    sim_days = env.get("SG_SIM_DAYS")
    layout = env.get("SG_LAYOUT") or "spring"
    if layout not in ("spring", "circular"):
        raise ValueError(f"SG_LAYOUT debe ser 'spring' o 'circular': {layout!r}")

    source = env.get("SG_SOURCE") or "simulation"
    if source not in ("simulation", "redis"):
        raise ValueError(f"SG_SOURCE debe ser 'simulation' o 'redis': {source!r}")

    return Settings(
        params=params,
        crew=crew,
        blocks=blocks,
        schedule_jitter_s=number("SG_SCHEDULE_JITTER_S", 0.0),
        schedule_seed=int(number("SG_SCHEDULE_SEED", 42)),
        source=source,
        stream=env.get("SG_STREAM") or "orbivia:positions",
        checkpoint_every_s=number("SG_CHECKPOINT_EVERY_S", 30.0),
        isolation=isolation,
        recommender=recommender,
        layout=layout,
        layout_seed=int(number("SG_LAYOUT_SEED", 42)),
        output_dir=env.get("SG_OUTPUT_DIR") or None,
        heartbeat_file=env.get("SG_HEARTBEAT_FILE") or None,
        sim_scenario=env.get("SG_SIM_SCENARIO") or "homogeneous",
        sim_seed=int(number("SG_SIM_SEED", 42)),
        sim_period_s=number("SG_SIM_SAMPLE_PERIOD_S", 10.0),
        sim_speedup=number("SG_SIM_SPEEDUP", 3600.0),
        # Por defecto 60 días, para que una demo olvidada no llene el disco; 0 = sin límite
        sim_days=(int(sim_days) or None) if sim_days else 60,
    )
