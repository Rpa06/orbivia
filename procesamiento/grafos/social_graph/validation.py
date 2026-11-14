"""Validación de instantáneas de posición y cálculo de distancias por pareja."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any

Position = tuple[float, float, float]


@dataclass(frozen=True)
class PositionSample:
    """Posiciones de la tripulación en un instante. None = sin dato válido."""

    t: float
    positions: Mapping[str, Position | None]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_position(value: Any) -> Position | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        return None
    if not all(_is_number(c) for c in value):
        return None
    return (float(value[0]), float(value[1]), float(value[2]))


def parse_sample(raw: Any, crew: Sequence[str]) -> tuple[PositionSample | None, list[str]]:
    """Convierte un mensaje en una muestra válida.

    Devuelve (muestra, incidencias). La muestra es None si el mensaje entero es
    inservible. Una posición inválida se convierte en None (sin dato) y se anota:
    nunca se sustituye por un valor inventado.
    """
    issues: list[str] = []
    if not isinstance(raw, Mapping):
        return None, ["mensaje no es un objeto"]
    t = raw.get("t")
    if not _is_number(t):
        return None, ["timestamp ausente o no numérico"]
    raw_positions = raw.get("positions")
    if not isinstance(raw_positions, Mapping):
        return None, ["campo positions ausente o inválido"]

    known = set(crew)
    for astronaut in raw_positions:
        if astronaut not in known:
            issues.append(f"astronauta desconocido: {astronaut}")

    positions: dict[str, Position | None] = {}
    for astronaut in crew:
        value = raw_positions.get(astronaut)
        if value is None:
            positions[astronaut] = None
            continue
        position = _parse_position(value)
        if position is None:
            issues.append(f"posición inválida: {astronaut}")
        positions[astronaut] = position
    return PositionSample(t=float(t), positions=positions), issues


def pair_key(a: str, b: str) -> tuple[str, str]:
    """Clave única y simétrica de una pareja."""
    return (a, b) if a < b else (b, a)


def pair_distances(sample: PositionSample) -> dict[tuple[str, str], float]:
    """Distancia euclídea de cada pareja con posición válida en los dos."""
    valid = {a: p for a, p in sample.positions.items() if p is not None}
    return {pair_key(a, b): math.dist(valid[a], valid[b]) for a, b in combinations(valid, 2)}
