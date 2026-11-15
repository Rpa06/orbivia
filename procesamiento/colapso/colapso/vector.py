"""Vector de Estado Colapsado: esquema formal, serialización y validación.

20 valores float32 en little-endian = 80 bytes exactos por astronauta y día.
El identificador del astronauta, la fecha del ciclo, la versión del esquema y
las máscaras de ausentes y de origen simulado son metadatos externos al vector
(columnas de `biometrics.daily_vector`), para que el vector ocupe 80 bytes.

Cada campo es una puntuación z frente a la línea base individual que
corresponda (terrestre o de adaptación), salvo `self_perception_gap`, que es
una diferencia de puntuaciones z. Un dato ausente se codifica como NaN y se
marca en `missing_mask`.

`direction` indica qué es empeorar para el cálculo de alertas y disponibilidad:
+1 si más es mejor, -1 si más es peor, 0 si cualquier alejamiento cuenta.

Decisiones de agregación (documentadas en docs/vector_estado_colapsado.md):
- Sueño: un solo campo, la duración estimada. La eficiencia y la fragmentación
  se quedan en el resumen de sueño (`biometrics.sleep_session_summary`).
- Biomarcadores físicos: cuatro campos (agarre, SpO2, FC y VFC nocturnas). Peso,
  radiación, tensión, temperatura y capacidad pulmonar no entran en el vector:
  se guardan en `biometrics.measurements` y se vigilan aparte. No se combinan
  variables físicas distintas en un mismo campo.
- Acústica: dos campos de openSMILE eGeMAPS (F0 media y duración media de las
  pausas sin voz).
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

SCHEMA_VERSION = 1
N_FIELDS = 20
VECTOR_BYTES = 80
_FORMAT = "<20f"

AREAS = ("medical", "fatigue_sleep", "psychological", "social_team")


@dataclass(frozen=True)
class Field:
    index: int
    name: str
    source: str        # de dónde sale el valor bruto
    unit: str          # unidad del valor bruto antes de normalizar
    direction: int     # +1 más es mejor, -1 más es peor, 0 bilateral
    area: str          # área NASA para la nota de disponibilidad
    self_report: bool  # autoinforme: pesa la mitad si la deseabilidad social es alta
    carry_days: int    # forward-fill máximo; 0 = debe medirse en su ciclo de 24 h
    critical: bool     # se evalúa en C1 (desviación aguda)
    description: str


FIELDS: tuple[Field, ...] = (
    Field(0, "sleep_duration_z", "sleep_duration_h", "h", +1, "fatigue_sleep", False, 0, True,
          "Sueño estimado de la noche anterior (actigrafía del módulo de sueño)"),
    Field(1, "pvt_rt_z", "pvt_mean_rt_ms", "ms", -1, "fatigue_sleep", False, 0, True,
          "Tiempo de reacción medio del PVT-B (fatiga objetiva)"),
    Field(2, "self_perception_gap", "derived", "z", -1, "fatigue_sleep", False, 0, True,
          "Brecha de autopercepción: z(PVT-B) - z(cansancio declarado); > 0 = rinde peor de lo que declara"),
    Field(3, "checkin_sleep_z", "checkin.sleep", "1-5", +1, "fatigue_sleep", True, 0, False,
          "Check-in: calidad de sueño declarada"),
    Field(4, "checkin_fatigue_z", "checkin.fatigue", "1-5", -1, "fatigue_sleep", True, 0, False,
          "Check-in: cansancio declarado (5 = muy cansado)"),
    Field(5, "checkin_workload_z", "checkin.workload", "1-5", -1, "fatigue_sleep", True, 0, False,
          "Check-in: carga de trabajo percibida (5 = muy alta)"),
    Field(6, "checkin_mood_z", "checkin.mood", "1-5", +1, "psychological", True, 0, False,
          "Check-in: ánimo declarado"),
    Field(7, "checkin_cohesion_z", "checkin.cohesion", "1-5", +1, "social_team", True, 0, False,
          "Check-in: convivencia declarada"),
    Field(8, "grip_strength_z", "grip_strength_kg", "kg", +1, "medical", False, 0, True,
          "Fuerza de agarre (PING diario)"),
    Field(9, "spo2_z", "spo2_pct", "%", +1, "medical", False, 0, True,
          "Saturación de oxígeno (PING diario)"),
    Field(10, "sleep_heart_rate_z", "sleep_heart_rate_bpm", "bpm", -1, "medical", False, 0, True,
          "Frecuencia cardíaca media nocturna"),
    Field(11, "sleep_hrv_z", "sleep_hrv_ms", "ms", +1, "medical", False, 0, True,
          "Variabilidad de la frecuencia cardíaca nocturna"),
    Field(12, "social_centrality_z", "social_centrality", "0-1", +1, "social_team", False, 0, True,
          "Centralidad en el grafo de ocio compartido (solo vigilancia, nunca reparto)"),
    Field(13, "circadian_desync_z", "circadian_desync_h", "h", -1, "social_team", False, 0, True,
          "Distancia del punto medio del sueño a la mediana de la tripulación"),
    Field(14, "nlp_neutral_z", "nlp.neutral", "0-1", +1, "psychological", False, 3, False,
          "Confianza del modelo de texto: neutral (no es una escala clínica)"),
    Field(15, "nlp_low_mood_z", "nlp.low_mood", "0-1", -1, "psychological", False, 3, True,
          "Confianza del modelo de texto: ánimo bajo (no es una escala clínica)"),
    Field(16, "nlp_anxiety_z", "nlp.anxiety", "0-1", -1, "psychological", False, 3, True,
          "Confianza del modelo de texto: ansiedad (no es una escala clínica)"),
    Field(17, "nlp_stable_z", "nlp.stable", "0-1", +1, "psychological", False, 3, False,
          "Confianza del modelo de texto: estable (no es una escala clínica)"),
    Field(18, "acoustic_f0_z", "acoustic.f0_mean", "semitonos", 0, "psychological", False, 3, False,
          "F0 media (openSMILE eGeMAPS F0semitoneFrom27.5Hz_sma3nz_amean)"),
    Field(19, "acoustic_pause_z", "acoustic.pause_mean_s", "s", -1, "psychological", False, 3, True,
          "Duración media de pausas sin voz (openSMILE eGeMAPS MeanUnvoicedSegmentLength)"),
)

assert len(FIELDS) == N_FIELDS and [f.index for f in FIELDS] == list(range(N_FIELDS))
BY_NAME = {f.name: f for f in FIELDS}
NLP_FIELDS = tuple(f.index for f in FIELDS if f.name.startswith("nlp_"))
ACOUSTIC_FIELDS = tuple(f.index for f in FIELDS if f.name.startswith("acoustic_"))
CHECKIN_FIELDS = tuple(f.index for f in FIELDS if f.name.startswith("checkin_"))


class VectorError(ValueError):
    pass


@dataclass(frozen=True)
class CollapsedVector:
    """Vector de un astronauta y un ciclo, con sus metadatos externos."""

    astronaut_id: str
    cycle_date: str            # ISO 8601 (AAAA-MM-DD)
    values: tuple[float, ...]  # 20 valores; NaN = ausente
    simulated_mask: int = 0
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if len(self.values) != N_FIELDS:
            raise VectorError(f"El vector debe tener {N_FIELDS} valores, tiene {len(self.values)}")
        if not self.astronaut_id:
            raise VectorError("Falta el identificador del astronauta")
        for i, v in enumerate(self.values):
            if not isinstance(v, (int, float)) or math.isinf(v):
                raise VectorError(f"Campo {FIELDS[i].name}: valor no válido {v!r}")
        # Redondeo a float32 para que el objeto coincida con lo que se guarda
        object.__setattr__(self, "values", unpack(pack(self.values)))

    @property
    def missing_mask(self) -> int:
        return missing_mask(self.values)

    def to_bytes(self) -> bytes:
        return pack(self.values)

    def as_dict(self) -> dict[str, float | None]:
        return {f.name: (None if math.isnan(v) else v) for f, v in zip(FIELDS, self.values)}

    def embedding(self) -> list[float]:
        """Para pgvector (C4): los ausentes cuentan como 0 (en la línea base)."""
        return [0.0 if math.isnan(v) else float(v) for v in self.values]


def pack(values: Sequence[float]) -> bytes:
    if len(values) != N_FIELDS:
        raise VectorError(f"El vector debe tener {N_FIELDS} valores")
    data = struct.pack(_FORMAT, *[float(v) for v in values])
    if len(data) != VECTOR_BYTES:  # no debería pasar nunca
        raise VectorError(f"El vector serializado ocupa {len(data)} bytes, no {VECTOR_BYTES}")
    return data


def unpack(data: bytes) -> tuple[float, ...]:
    if len(data) != VECTOR_BYTES:
        raise VectorError(f"Un vector serializado ocupa {VECTOR_BYTES} bytes, no {len(data)}")
    return struct.unpack(_FORMAT, data)


def missing_mask(values: Sequence[float]) -> int:
    mask = 0
    for i, v in enumerate(values):
        if math.isnan(v):
            mask |= 1 << i
    return mask


def from_named(astronaut_id: str, cycle_date: str, named: Mapping[str, float | None],
               simulated: set[str] | None = None) -> CollapsedVector:
    unknown = set(named) - set(BY_NAME)
    if unknown:
        raise VectorError(f"Campos desconocidos: {sorted(unknown)}")
    values = tuple(math.nan if named.get(f.name) is None else float(named[f.name]) for f in FIELDS)
    sim_mask = 0
    for name in simulated or ():
        sim_mask |= 1 << BY_NAME[name].index
    return CollapsedVector(astronaut_id, cycle_date, values, sim_mask)


def deterioration(field: Field, value: float) -> float:
    """Cuánto empeora un campo, en desviaciones típicas: > 0 es peor que la línea base."""
    if math.isnan(value):
        return math.nan
    if field.direction == 0:
        return abs(value)
    return -field.direction * value


def schema_document() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "dtype": "float32",
        "byte_order": "little",
        "bytes": VECTOR_BYTES,
        "fields": [
            {"index": f.index, "name": f.name, "source": f.source, "unit": f.unit,
             "direction": f.direction, "area": f.area, "self_report": f.self_report,
             "carry_days": f.carry_days, "critical": f.critical, "description": f.description}
            for f in FIELDS
        ],
        "external_metadata": ["astronaut_id", "cycle_date", "schema_version", "missing_mask", "simulated_mask"],
    }
