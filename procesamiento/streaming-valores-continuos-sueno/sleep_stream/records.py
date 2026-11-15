"""Formato y validación de los mensajes de entrada.

Tres tipos de mensaje, todos con `astronaut_id` y `sleep_session_id`:

    {"type": "start", "start_timestamp": 1794672000, ...}       inicio de sesión
    {"timestamp": 1794672060, "metrics": {"heart_rate": 58}}     registro (por defecto)
    {"type": "end", "end_timestamp": 1794700800}                 fin de sesión

Un mensaje mal formado se rechaza entero con un código. Dentro de un registro
válido, cada métrica se clasifica por separado como válida, ausente o inválida:
una métrica mala no descarta las demás, y una ausente nunca se cuenta como valor.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import ID_PATTERN, MetricSpec

RECORD, START, END = "record", "start", "end"

OK, MISSING, INVALID = "ok", "missing", "invalid"

# Un epoch en segundos no llega a 1e11 hasta el año 5138: algo mayor son milisegundos
MAX_EPOCH_S = 1e11


class Rejected(Exception):
    """Mensaje que no se puede procesar. `code` es estable; `detail`, para humanos."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Message:
    type: str
    astronaut_id: str
    session_id: str
    timestamp: float | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    units: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_timestamp(value: Any, name: str = "timestamp") -> float:
    if not _is_number(value):
        raise Rejected("bad_timestamp", f"{name} debe ser un número finito: {value!r}")
    if value <= 0:
        raise Rejected("bad_timestamp", f"{name} debe ser > 0")
    if value >= MAX_EPOCH_S:
        raise Rejected("timestamp_unit", f"{name} parece estar en milisegundos; se esperan segundos")
    return float(value)


def _baselines(raw: Any) -> dict[str, dict[str, dict[str, float]]]:
    """{"metrics": {métrica: {mean, sd}}, "vector": {dimensión: {mean, sd}}}"""
    if raw is None:
        return {"metrics": {}, "vector": {}}
    if not isinstance(raw, Mapping) or set(raw) - {"metrics", "vector"}:
        raise Rejected("bad_baselines", "baselines admite las claves 'metrics' y 'vector'")
    out: dict[str, dict[str, dict[str, float]]] = {"metrics": {}, "vector": {}}
    for group in out:
        entries = raw.get(group) or {}
        if not isinstance(entries, Mapping):
            raise Rejected("bad_baselines", f"baselines.{group} debe ser un objeto")
        for name, item in entries.items():
            ok = (isinstance(item, Mapping) and _is_number(item.get("mean"))
                  and _is_number(item.get("sd")) and item["sd"] > 0)
            if not ok:
                raise Rejected("bad_baselines", f"baselines.{group}.{name} necesita mean y sd > 0")
            out[group][str(name)] = {"mean": float(item["mean"]), "sd": float(item["sd"])}
    return out


def parse_message(data: Any) -> Message:
    if not isinstance(data, Mapping):
        raise Rejected("bad_structure", "el mensaje debe ser un objeto JSON")
    kind = data.get("type", RECORD)
    if kind not in (RECORD, START, END):
        raise Rejected("bad_type", f"type desconocido: {kind!r}")
    ids = []
    for key in ("astronaut_id", "sleep_session_id"):
        value = data.get(key)
        if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
            raise Rejected(f"bad_{key}", f"{key} inválido o ausente: {value!r}")
        ids.append(value)

    if kind == START:
        options: dict[str, Any] = {"baselines": _baselines(data.get("baselines"))}
        expected = data.get("expected_metrics")
        if expected is not None:
            if (not isinstance(expected, list) or not expected
                    or not all(isinstance(m, str) and ID_PATTERN.fullmatch(m) for m in expected)):
                raise Rejected("bad_expected_metrics", "expected_metrics debe ser una lista de nombres")
            options["expected_metrics"] = sorted(set(expected))
        period = data.get("sample_period_s")
        if period is not None:
            if not _is_number(period) or period <= 0:
                raise Rejected("bad_sample_period", "sample_period_s debe ser > 0")
            options["sample_period_s"] = float(period)
        return Message(START, ids[0], ids[1], parse_timestamp(data.get("start_timestamp"), "start_timestamp"),
                       options=options)

    if kind == END:
        end = data.get("end_timestamp")
        return Message(END, ids[0], ids[1], None if end is None else parse_timestamp(end, "end_timestamp"))

    metrics = data.get("metrics")
    if not isinstance(metrics, Mapping) or not metrics:
        raise Rejected("bad_metrics", "metrics debe ser un objeto con al menos una métrica")
    units = data.get("units") or {}
    if not isinstance(units, Mapping):
        raise Rejected("bad_units", "units debe ser un objeto {métrica: unidad}")
    return Message(RECORD, ids[0], ids[1], parse_timestamp(data.get("timestamp")), metrics, units)


def classify(present: bool, value: Any, spec: MetricSpec | None, unit: Any = None) -> tuple[str, Any]:
    """Estado de una métrica dentro de un registro: (OK, valor), (MISSING, None) o (INVALID, motivo)."""
    if not present or value is None:
        return MISSING, None
    if spec is not None and unit is not None and unit != spec.unit:
        return INVALID, "unit_mismatch"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return INVALID, "bad_type"
    if not math.isfinite(value):
        return INVALID, "not_finite"
    if spec is not None and not spec.valid_min <= value <= spec.valid_max:
        return INVALID, "out_of_range"
    return OK, float(value)
