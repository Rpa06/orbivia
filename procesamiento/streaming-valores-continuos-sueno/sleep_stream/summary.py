"""Resumen de una sesión y vector de sueño.

Se distinguen tres cosas, que no se mezclan:

1. `metrics`: estadísticas agregadas de cada métrica biométrica, en su unidad.
2. `sleep_summary_vector`: las dimensiones del vector, en unidades físicas.
3. `normalized_vector`: las mismas dimensiones normalizadas. Solo se normaliza
   lo que tiene una transformación definida: puntuación z respecto a la línea
   base individual si se aportó al iniciar la sesión, o identidad para las
   dimensiones que ya son una fracción 0-1. Lo demás queda sin normalizar, con
   su motivo; no se inventan rangos ni se asume qué dirección es "mejor".

Una dimensión que no se puede calcular vale None, nunca 0.
"""

from typing import Any

from .config import Settings
from .engine import Session
from .stats import Agg

SCHEMA_VERSION = 1

# (dimensión, unidad, descripción)
VECTOR_SPEC: tuple[tuple[str, str, str], ...] = (
    ("time_in_bed_h", "h", "Duración de la sesión: fin menos inicio"),
    ("estimated_sleep_h", "h", "Minutos sin actividad (actigrafía); no hay estadios de sueño"),
    ("sleep_efficiency", "0-1", "Minutos sin actividad entre minutos con dato de movimiento"),
    ("sleep_fragmentation", "episodios/h", "Rachas de actividad por hora con dato de movimiento"),
    ("mean_heart_rate", "bpm", "Media de la frecuencia cardíaca"),
    ("mean_hrv", "ms", "Media de la variabilidad de la frecuencia cardíaca"),
    ("mean_spo2", "%", "Media de la saturación de oxígeno"),
    ("mean_respiratory_rate", "rpm", "Media de la frecuencia respiratoria"),
    ("mean_skin_temperature", "degC", "Media de la temperatura cutánea"),
    ("movement_level", "a.u.", "Media del movimiento"),
    ("hrv_trend", "ms/h", "Pendiente de la variabilidad cardíaca a lo largo de la sesión"),
    ("measurement_completeness", "0-1", "Valores válidos entre valores esperados"),
)

_MEANS = {
    "mean_heart_rate": "heart_rate",
    "mean_hrv": "heart_rate_variability",
    "mean_spo2": "spo2",
    "mean_respiratory_rate": "respiratory_rate",
    "mean_skin_temperature": "skin_temperature",
}
_FRACTIONS = ("sleep_efficiency", "measurement_completeness")


def _mean(session: Session, metric: str) -> float | None:
    agg = session.total.get(metric)
    return agg.mean if agg is not None and agg.n else None


def expected_records(session: Session) -> int | None:
    """Registros que deberían haber llegado, si se declaró el periodo de muestreo."""
    if session.sample_period_s is None or session.end_ts is None:
        return None
    return max(int((session.end_ts - session.start_ts) / session.sample_period_s), 1)


def completeness(session: Session) -> dict[str, float | None]:
    """Fracción de valores válidos por métrica esperada.

    Con periodo de muestreo declarado, el denominador son los registros que
    debieron llegar (cuenta también los que nunca llegaron). Sin él, los
    registros recibidos.
    """
    expected = expected_records(session)
    out: dict[str, float | None] = {}
    for name in session.expected:
        agg = session.total.get(name)
        valid = agg.n if agg else 0
        denominator = expected if expected is not None else session.counters["accepted"]
        out[name] = min(valid / denominator, 1.0) if denominator else None
    return out


def sleep_metrics(session: Session, cfg: Settings) -> dict[str, Any]:
    epoch = cfg.levels_s[0]
    activity = session.activity
    scored, active = activity["scored"], activity["active"]
    still = scored - active
    return {
        "time_in_bed_s": session.end_ts - session.start_ts,
        "epoch_s": epoch,
        "scored_epochs": scored,
        "active_epochs": active,
        "unknown_epochs": activity["unknown"],
        "activity_bouts": activity["bouts"],
        "estimated_sleep_s": still * epoch if scored else None,
        "sleep_efficiency": still / scored if scored else None,
        "fragmentation_per_h": activity["bouts"] / (scored * epoch / 3600.0) if scored else None,
        "activity_coverage": scored / (scored + activity["unknown"]) if scored + activity["unknown"] else None,
    }


def build_vector(session: Session, sleep: dict[str, Any], complete: dict[str, float | None]) -> dict[str, float | None]:
    known = [value for value in complete.values() if value is not None]
    hrv_slope = session.trend["heart_rate_variability"].slope if "heart_rate_variability" in session.trend else None
    vector: dict[str, float | None] = {
        "time_in_bed_h": sleep["time_in_bed_s"] / 3600.0,
        "estimated_sleep_h": None if sleep["estimated_sleep_s"] is None else sleep["estimated_sleep_s"] / 3600.0,
        "sleep_efficiency": sleep["sleep_efficiency"],
        "sleep_fragmentation": sleep["fragmentation_per_h"],
        "movement_level": _mean(session, "movement"),
        "hrv_trend": None if hrv_slope is None else hrv_slope * 3600.0,
        "measurement_completeness": sum(known) / len(known) if known else None,
    }
    for dimension, metric in _MEANS.items():
        vector[dimension] = _mean(session, metric)
    return {name: vector[name] for name, _, _ in VECTOR_SPEC}


def normalize_vector(vector: dict[str, float | None], session: Session) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, value in vector.items():
        baseline = session.baselines["vector"].get(name)
        if value is None:
            out[name] = {"value": None, "status": "missing", "method": None}
        elif baseline is not None:
            out[name] = {"value": (value - baseline["mean"]) / baseline["sd"],
                         "status": "known", "method": "baseline_z"}
        elif name in _FRACTIONS:
            out[name] = {"value": value, "status": "known", "method": "identity"}
        else:
            out[name] = {"value": None, "status": "no_baseline", "method": "baseline_z"}
    return out


def _timeline_entry(entry: dict[str, Any]) -> dict[str, Any]:
    metrics = {}
    for name, agg in sorted(entry["window"].items()):
        metrics[name] = {
            "n": agg.n,
            "mean": agg.mean if agg.n else None,
            "std": agg.std,
            "min": agg.min,
            "max": agg.max,
            "missing": agg.missing,
            "invalid": agg.invalid,
        }
    return {"start": entry["start"], "size_s": entry["size_s"], "metrics": metrics}


def check_consistency(session: Session, timeline: list[dict[str, Any]]) -> bool:
    """La fusión de todas las ventanas debe dar el acumulador global."""
    merged: dict[str, Agg] = {}
    for entry in timeline:
        for name, agg in entry["window"].items():
            merged.setdefault(name, Agg()).merge(agg)
    if set(merged) != set(session.total):
        return False
    for name, total in session.total.items():
        other = merged[name]
        if (other.n, other.missing, other.invalid, other.min, other.max) != (
            total.n, total.missing, total.invalid, total.min, total.max
        ):
            return False
        if total.n and abs(other.mean - total.mean) > 1e-9 * max(1.0, abs(total.mean)):
            return False
    return True


def build_summary(session: Session, timeline: list[dict[str, Any]],
                  anomalies: list[dict[str, Any]], cfg: Settings) -> dict[str, Any]:
    specs = cfg.specs
    complete = completeness(session)
    sleep = sleep_metrics(session, cfg)
    vector = build_vector(session, sleep, complete)

    metrics = {}
    for name in sorted(session.total):
        agg = session.total[name]
        stats = agg.stats(specs.get(name))
        slope = session.trend[name].slope if name in session.trend else None
        stats["trend_per_h"] = None if slope is None else slope * 3600.0
        stats["unit"] = specs[name].unit if name in specs else None
        stats["completeness"] = complete.get(name)
        metrics[name] = stats

    expected = expected_records(session)
    counters = session.counters
    missing_values = sum(agg.missing for agg in session.total.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "astronaut_id": session.astronaut_id,
        "sleep_session_id": session.session_id,
        "sleep_summary_vector": vector,
        "vector_spec": [{"name": n, "unit": u, "description": d} for n, u, d in VECTOR_SPEC],
        "normalized_vector": normalize_vector(vector, session),
        "metrics": metrics,
        "sleep": sleep,
        "timeline": [_timeline_entry(entry) for entry in timeline],
        "anomalies": anomalies,
        "session_metadata": {
            "start_timestamp": session.start_ts,
            "end_timestamp": session.end_ts,
            "total_observations": counters["accepted"],
            "expected_observations": expected,
            "missing_observations": None if expected is None else max(expected - counters["accepted"], 0),
            "missing_values": missing_values,
            "invalid_values": sum(agg.invalid for agg in session.total.values()),
            "invalid_reasons": session.invalid_reasons,
            "duplicates": counters["duplicates"],
            "out_of_order": counters["out_of_order"],
            "late_into_coarser_window": counters["late_coarse"],
            "rejected": counters["rejected"],
            "rejections": session.rejections,
            "anomalies_count": len(anomalies),
            "anomalous_samples": session.anomalies["samples"],
            "anomalies_dropped": session.anomalies["dropped"],
            "aggregates_consistent": check_consistency(session, timeline),
            "config_version": cfg.version,
            "processing_status": "completed",
        },
    }
