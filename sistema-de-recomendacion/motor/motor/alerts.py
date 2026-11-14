"""Evaluación multicriterio de avisos (README, sección 2.B).

Un aviso nunca se dispara por un único dato aislado:

- C1 Desviación aguda: un campo crítico empeora más de 2σ respecto a su línea
  base tres días seguidos.
- C2 Deterioro progresivo: pendiente móvil de empeoramiento sostenida en la
  ventana de 14 o de 30 días, aunque el valor diario no cruce el umbral.
- C3 Combinación de señales: al menos tres campos empeoran más de 1σ el mismo
  día, sin que ninguno cruce 2σ por sí solo.
- C4 Similitud histórica: preparado y desactivado (ENABLE_HISTORICAL_VECTOR_MATCH).
  Requiere vectores de misiones anteriores etiquetados; no se simula.

Los avisos son operativos: indican qué área vigilar, no diagnostican.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from colapso.stats import rolling_slope
from colapso.vector import FIELDS, deterioration

C1_SIGMA = 2.0
C1_DAYS = 3
C2_WINDOWS = ((14, 0.08, 10), (30, 0.04, 20))  # (días, pendiente mínima σ/día, puntos mínimos)
C3_SIGMA = 1.0
C3_MIN_FIELDS = 3

REFERENCES = {
    "C1": "±2σ respecto a la línea base individual durante 3 días seguidos (README §2.B)",
    "C2": "Pendiente móvil sostenida a 14 o 30 días (README §2.B)",
    "C3": "Empeoramiento simultáneo de varias señales, ninguna sobre 2σ (README §2.B)",
    "C4": "Similitud coseno con estados históricos, pgvector (README §2.B, función futura)",
}


@dataclass(frozen=True)
class Alert:
    criterion: str
    area: str
    variables: tuple[str, ...]
    detail: Mapping
    reference: str


@dataclass
class AlertEvaluation:
    alerts: list[Alert] = field(default_factory=list)
    suppressed: list[dict] = field(default_factory=list)   # por línea base de adaptación
    c4: dict = field(default_factory=dict)


def historical_match_enabled() -> bool:
    return os.environ.get("ENABLE_HISTORICAL_VECTOR_MATCH", "false").strip().lower() in ("1", "true", "yes")


def _series(history: Mapping[date, Sequence[float]], index: int) -> dict[date, float]:
    return {d: deterioration(FIELDS[index], v[index]) for d, v in history.items()}


def evaluate(history: Mapping[date, Sequence[float]], today: date, mission_day: int,
             adaptation_days: int) -> AlertEvaluation:
    """`history`: vectores de un astronauta por fecha (incluido hoy)."""
    result = AlertEvaluation()
    if today not in history:
        return result
    in_adaptation = adaptation_days > 0 and mission_day <= adaptation_days

    # C1
    for f in FIELDS:
        if not f.critical:
            continue
        s = _series(history, f.index)
        days = [today - timedelta(days=k) for k in range(C1_DAYS)]
        vals = [s.get(d, math.nan) for d in days]
        if all(not math.isnan(v) and v > C1_SIGMA for v in vals):
            alert = Alert("C1", f.area, (f.name,), {
                "values_sigma": [round(v, 2) for v in reversed(vals)],
                "threshold_sigma": C1_SIGMA, "days": C1_DAYS,
            }, REFERENCES["C1"])
            if in_adaptation:
                result.suppressed.append({"criterion": "C1", "field": f.name, "reason": "fase de adaptación"})
            else:
                result.alerts.append(alert)

    # C2
    for f in FIELDS:
        s = _series(history, f.index)
        for days, min_slope, min_points in C2_WINDOWS:
            pts = [((d - today).days, s.get(d, math.nan))
                   for d in (today - timedelta(days=k) for k in range(days - 1, -1, -1))]
            slope, n = rolling_slope(pts)
            if n < min_points or math.isnan(slope) or slope < min_slope:
                continue
            half = days // 2
            first, n1 = rolling_slope(pts[:half])
            second, n2 = rolling_slope(pts[half:])
            sustained = (not math.isnan(first) and not math.isnan(second) and first > 0 and second > 0)
            if not sustained:
                continue
            if in_adaptation:
                result.suppressed.append({"criterion": "C2", "field": f.name, "reason": "fase de adaptación"})
                break
            result.alerts.append(Alert("C2", f.area, (f.name,), {
                "window_days": days, "slope_sigma_per_day": round(slope, 4),
                "min_slope": min_slope, "points": n,
            }, REFERENCES["C2"]))
            break

    # C3
    today_vals = {f.name: deterioration(f, history[today][f.index]) for f in FIELDS}
    worsening = sorted(n for n, v in today_vals.items() if not math.isnan(v) and C3_SIGMA < v <= C1_SIGMA)
    if len(worsening) >= C3_MIN_FIELDS and not in_adaptation:
        areas = sorted({next(f.area for f in FIELDS if f.name == n) for n in worsening})
        for area in areas:
            result.alerts.append(Alert("C3", area, tuple(worsening), {
                "fields": {n: round(today_vals[n], 2) for n in worsening},
                "threshold_sigma": C3_SIGMA, "min_fields": C3_MIN_FIELDS,
            }, REFERENCES["C3"]))

    result.c4 = {"enabled": historical_match_enabled(), "status": "disabled"}
    if historical_match_enabled():
        result.c4["status"] = "insufficient_history"
    return result


def c4_query(limit: int = 5) -> str:
    """Consulta preparada para C4 (distancia coseno con pgvector). Solo se usa si
    ENABLE_HISTORICAL_VECTOR_MATCH=true y existe un histórico etiquetado de otras
    misiones, que esta demo no tiene."""
    return (
        "SELECT astronaut_id, cycle_date, embedding <=> %s::vector AS cosine_distance "
        "FROM biometrics.daily_vector WHERE cycle_date < %s "
        f"ORDER BY embedding <=> %s::vector LIMIT {int(limit)}"
    )
