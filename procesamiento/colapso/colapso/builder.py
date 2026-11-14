"""Construcción del vector de un día a partir de las observaciones de un astronauta.

Funciones puras: la lectura de la base de datos está en `motor.pipeline`.

Entradas:
- `raw[source]`: observaciones brutas por fecha de ciclo (unidades físicas o 1-5).
- `baselines[source]`: (terrestre, adaptación) de ese astronauta y esa variable.
- `media_z[field]`: puntuaciones z ya calculadas contra la línea base de cada
  pregunta de la entrevista (NLP y acústica), por fecha de la entrevista.

Reglas de vigencia (forward-fill controlado):
- Variables diarias y de sueño: solo valen en su ciclo de 24 h.
- NLP y acústica: valen hasta `audio_interval_days` días (la entrevista es periódica).
- Las variables semanales fuera del vector se vigilan con `stats.forward_fill`
  (máximo 7 días; después, aviso de protocolo).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from .stats import Baseline, choose_baseline, forward_fill, zscore
from .vector import FIELDS, CollapsedVector

GAP = "self_perception_gap"


@dataclass
class BuildResult:
    vector: CollapsedVector
    details: dict[str, dict] = field(default_factory=dict)


def build_vector(
    astronaut_id: str,
    today: date,
    mission_day: int,
    adaptation_days: int,
    raw: Mapping[str, Mapping[date, float]],
    baselines: Mapping[str, tuple[Baseline | None, Baseline | None]],
    media_z: Mapping[str, Mapping[date, float]] | None = None,
    media_carry_days: int = 3,
    simulated_sources: set[str] | frozenset[str] = frozenset(),
) -> BuildResult:
    media_z = media_z or {}
    values: list[float] = [math.nan] * len(FIELDS)
    details: dict[str, dict] = {}
    simulated: set[str] = set()

    for f in FIELDS:
        if f.name == GAP:
            continue
        if f.source.startswith(("nlp.", "acoustic.")):
            filled = forward_fill(media_z.get(f.name, {}), today, media_carry_days)
            values[f.index] = filled.value
            details[f.name] = {"z": _clean(filled.value), "measured_on": _iso(filled.measured_on),
                               "carried": filled.carried, "age_days": filled.age_days,
                               "baseline": "per_question"}
        else:
            filled = forward_fill(raw.get(f.source, {}), today, f.carry_days)
            terrestrial, adaptation = baselines.get(f.source, (None, None))
            base = choose_baseline(terrestrial, adaptation, mission_day, adaptation_days)
            z = zscore(filled.value, base)
            values[f.index] = z
            details[f.name] = {"raw": _clean(filled.value), "z": _clean(z),
                               "baseline": base.kind if base else None,
                               "measured_on": _iso(filled.measured_on), "carried": filled.carried}
        if f.source in simulated_sources and not math.isnan(values[f.index]):
            simulated.add(f.name)

    # Brecha de autopercepción: rendimiento objetivo frente a cansancio declarado,
    # ambos como desviación de su línea base. > 0: rinde peor de lo que declara.
    gap_field = next(f for f in FIELDS if f.name == GAP)
    z_rt = values[1]
    z_fatigue = values[4]
    gap = z_rt - z_fatigue if not (math.isnan(z_rt) or math.isnan(z_fatigue)) else math.nan
    values[gap_field.index] = gap
    details[GAP] = {"z_pvt": _clean(z_rt), "z_fatigue_declared": _clean(z_fatigue), "value": _clean(gap)}
    if {"pvt_mean_rt_ms", "checkin.fatigue"} & set(simulated_sources) and not math.isnan(gap):
        simulated.add(GAP)

    vector = CollapsedVector(astronaut_id, today.isoformat(), tuple(values))
    sim_mask = 0
    for f in FIELDS:
        if f.name in simulated:
            sim_mask |= 1 << f.index
    vector = CollapsedVector(astronaut_id, today.isoformat(), vector.values, sim_mask)
    return BuildResult(vector, details)


def _clean(x: float | None) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None
