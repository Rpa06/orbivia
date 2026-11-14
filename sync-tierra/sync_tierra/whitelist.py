"""Lista blanca de lo que puede salir hacia Tierra.

Solo vectores diarios de 80 bytes con sus metadatos y las métricas numéricas
acústicas y del modelo de texto autorizadas para el equipo médico en Tierra.

Nunca sale: audio, vídeo, transcripciones, registro del ciclo ni nada del esquema
private_cycle. El rol de base de datos de este servicio (orbivia_sync) ni siquiera
puede leer esos datos; esta lista es una segunda barrera.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

RECORD_FIELDS = frozenset({
    "astronaut_id", "cycle_date", "schema_version", "vector_b64", "missing_mask", "simulated_mask",
    "interviews",
})
INTERVIEW_FIELDS = frozenset({"question_id", "acoustic", "nlp"})
ACOUSTIC_FIELDS = frozenset({"f0_mean", "pause_mean_s", "voiced_segments_per_s", "loudness_mean", "duration_s"})
NLP_FIELDS = frozenset({"neutral", "low_mood", "anxiety", "stable"})


class ForbiddenField(ValueError):
    pass


def _numbers(mapping: dict | None, allowed: frozenset[str], where: str) -> dict[str, float] | None:
    if not mapping:
        return None
    extra = set(mapping) - allowed
    if extra:
        raise ForbiddenField(f"{where}: campos no autorizados {sorted(extra)}")
    out = {}
    for k, v in mapping.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ForbiddenField(f"{where}.{k}: solo se envían números")
        out[k] = float(v)
    return out


def build_record(astronaut_id: str, cycle_date: str, schema_version: int, vector: bytes,
                 missing_mask: int, simulated_mask: int, interviews: list[dict]) -> dict[str, Any]:
    if len(vector) != 80:
        raise ForbiddenField("El vector debe ocupar 80 bytes")
    record = {
        "astronaut_id": astronaut_id,
        "cycle_date": cycle_date,
        "schema_version": int(schema_version),
        "vector_b64": base64.b64encode(vector).decode(),
        "missing_mask": int(missing_mask),
        "simulated_mask": int(simulated_mask),
        "interviews": [
            {"question_id": i.get("question_id"),
             "acoustic": _numbers(i.get("acoustic"), ACOUSTIC_FIELDS, "acoustic"),
             "nlp": _numbers(i.get("nlp"), NLP_FIELDS, "nlp")}
            for i in interviews
        ],
    }
    validate(record)
    return record


def validate(record: dict) -> None:
    extra = set(record) - RECORD_FIELDS
    if extra:
        raise ForbiddenField(f"Campos no autorizados: {sorted(extra)}")
    for interview in record.get("interviews", []):
        if set(interview) - INTERVIEW_FIELDS:
            raise ForbiddenField("Entrevista con campos no autorizados")
    text = json.dumps(record).lower()
    for word in ("transcript", "menstr", "private_cycle", "\"audio\"", "\"video\"", "\"payload\""):
        if word in text:
            raise ForbiddenField(f"Contenido prohibido en el envío: {word}")


def digest(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
