"""Operaciones con conjuntos de intervalos semiabiertos [inicio, fin).

Todas las funciones devuelven listas normalizadas: ordenadas, sin intervalos
vacíos y sin solapes. Así una duración nunca se cuenta dos veces.
"""

from collections.abc import Iterable

Interval = tuple[float, float]


def normalize(intervals: Iterable[Interval]) -> list[Interval]:
    """Ordena, descarta vacíos y fusiona intervalos que se solapan o se tocan."""
    merged: list[Interval] = []
    for start, end in sorted((a, b) for a, b in intervals if b > a):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def total(intervals: Iterable[Interval]) -> float:
    """Duración total de la unión de los intervalos."""
    return sum(end - start for start, end in normalize(intervals))


def clip(intervals: Iterable[Interval], start: float, end: float) -> list[Interval]:
    """Recorta los intervalos a la ventana [start, end)."""
    return normalize((max(a, start), min(b, end)) for a, b in intervals)


def union(*sets: Iterable[Interval]) -> list[Interval]:
    return normalize(iv for s in sets for iv in s)


def intersect(x: Iterable[Interval], y: Iterable[Interval]) -> list[Interval]:
    """Instantes que pertenecen a los dos conjuntos."""
    xs, ys = normalize(x), normalize(y)
    out: list[Interval] = []
    i = j = 0
    while i < len(xs) and j < len(ys):
        start = max(xs[i][0], ys[j][0])
        end = min(xs[i][1], ys[j][1])
        if end > start:
            out.append((start, end))
        if xs[i][1] < ys[j][1]:
            i += 1
        else:
            j += 1
    return out


def complement(intervals: Iterable[Interval], window: Interval) -> list[Interval]:
    """Instantes de la ventana que no pertenecen a ningún intervalo."""
    out: list[Interval] = []
    cursor = window[0]
    for start, end in clip(intervals, *window):
        if start > cursor:
            out.append((cursor, start))
        cursor = end
    if cursor < window[1]:
        out.append((cursor, window[1]))
    return out
