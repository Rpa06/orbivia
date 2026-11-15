"""Nota de disponibilidad (0-100) a partir de las desviaciones individuales.

Fórmula (auditable, se guarda el desglose en `biometrics.availability.audit`):

1. Para cada campo del vector, empeoramiento s = desviación en σ en la
   dirección mala (ver `colapso.vector.deterioration`). Si s <= 0 no penaliza.
2. Penalización del campo: p(s) = max(0, s) + 1.5 · max(0, s - 1.5).
   Las desviaciones por encima de 1,5σ pesan 2,5 veces más.
3. Peso del campo: 1. Los campos de autoinforme (check-in) pesan 0,5 si la
   deseabilidad social del astronauta es alta (baseline_profile).
4. "Motivo conocido": ese día las caídas de los campos de autoinforme no
   penalizan. Los campos objetivos no cambian.
5. Nota de cada área NASA (médico, fatiga y sueño, psicológico, social y
   equipo) = max(0, 100 - 25 · media ponderada de p). Sin datos, el área no puntúa.
6. Nota global = media de las áreas con datos.

El ciclo menstrual no entra en ningún paso: este módulo no tiene acceso a él.
El grafo social solo aporta su campo de centralidad a la vigilancia del área
social; la nota no se usa para formar ni separar equipos.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from colapso.vector import AREAS, FIELDS, deterioration

SIGMA_KNEE = 1.5
KNEE_EXTRA = 1.5
AREA_SCALE = 25.0
SELF_REPORT_LOW_RELIABILITY_WEIGHT = 0.5

# Motivo general que puede ver el comandante (README §2.F): sin detalle psicológico.
REASONS = {
    "fatigue_sleep": "fatigue",
    "social_team": "isolation",
    "medical": "medical_followup",
    "psychological": "medical_followup",
}


def penalty(s: float) -> float:
    if math.isnan(s) or s <= 0:
        return 0.0
    return s + KNEE_EXTRA * max(0.0, s - SIGMA_KNEE)


@dataclass(frozen=True)
class Availability:
    score: float | None
    areas: dict[str, float | None]
    reason_category: str
    audit: dict


def compute(values: Sequence[float], social_desirability_high: bool = False,
            known_reason: bool = False) -> Availability:
    per_area: dict[str, list[tuple[float, float]]] = {a: [] for a in AREAS}
    contributions = []
    for f in FIELDS:
        v = values[f.index]
        s = deterioration(f, v)
        if math.isnan(s):
            contributions.append({"field": f.name, "area": f.area, "status": "missing"})
            continue
        weight = 1.0
        notes = []
        if f.self_report and social_desirability_high:
            weight = SELF_REPORT_LOW_RELIABILITY_WEIGHT
            notes.append("autoinforme al 50 % por deseabilidad social alta")
        p = penalty(s)
        if f.self_report and known_reason and s > 0:
            p = 0.0
            notes.append("caída subjetiva con motivo conocido: no penaliza")
        if f.name == "checkin_workload_z" and s > 0:
            notes.append("carga")
        per_area[f.area].append((weight, p))
        contributions.append({"field": f.name, "area": f.area, "sigma": round(s, 3), "weight": weight,
                              "penalty": round(p, 3), "notes": notes})

    areas: dict[str, float | None] = {}
    for area, items in per_area.items():
        if not items:
            areas[area] = None
            continue
        total_w = sum(w for w, _ in items)
        mean_p = sum(w * p for w, p in items) / total_w
        areas[area] = round(max(0.0, 100.0 - AREA_SCALE * mean_p), 1)

    scored = [v for v in areas.values() if v is not None]
    score = round(sum(scored) / len(scored), 1) if scored else None

    reason = "none"
    if score is not None:
        worst_area = min((a for a in areas if areas[a] is not None), key=lambda a: areas[a])
        if areas[worst_area] < 85:
            reason = REASONS[worst_area]
            workload = next((c for c in contributions if c["field"] == "checkin_workload_z"), None)
            if worst_area == "fatigue_sleep" and workload and workload.get("penalty", 0) > 1.0:
                reason = "workload"

    return Availability(score, areas, reason, {
        "formula": "p(s)=max(0,s)+1.5*max(0,s-1.5); area=max(0,100-25*media_ponderada(p)); nota=media(areas)",
        "social_desirability_high": social_desirability_high,
        "known_reason": known_reason,
        "contributions": contributions,
    })
