"""Estadística incremental: Welford, z-scores, ventanas móviles, pendiente y forward-fill.

Todo es determinista y sin dependencias externas.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

WINDOWS = (7, 14, 30)


# --- Welford -------------------------------------------------------------------------


@dataclass(frozen=True)
class Welford:
    """Acumulador de Welford (media y varianza en una pasada, numéricamente estable)."""

    n: int = 0
    mean: float = 0.0
    m2: float = 0.0
    last_date: date | None = None

    def add(self, x: float, on: date | None = None) -> "Welford":
        """Añade una observación. Con `on`, un día ya contado no se vuelve a contar,
        para que re-ejecutar el colapso de un día no mezcle ciclos."""
        if x is None or math.isnan(x):
            return self
        if on is not None and self.last_date is not None and on <= self.last_date:
            return self
        n = self.n + 1
        delta = x - self.mean
        mean = self.mean + delta / n
        m2 = self.m2 + delta * (x - mean)
        return replace(self, n=n, mean=mean, m2=m2, last_date=on or self.last_date)

    @property
    def variance(self) -> float:
        return self.m2 / (self.n - 1) if self.n > 1 else math.nan

    @property
    def sd(self) -> float:
        v = self.variance
        return math.sqrt(v) if not math.isnan(v) else math.nan

    def merge(self, other: "Welford") -> "Welford":
        """Combinación de Chan et al. de dos acumuladores disjuntos."""
        if other.n == 0:
            return self
        if self.n == 0:
            return other
        n = self.n + other.n
        delta = other.mean - self.mean
        mean = self.mean + delta * other.n / n
        m2 = self.m2 + other.m2 + delta * delta * self.n * other.n / n
        last = max(d for d in (self.last_date, other.last_date) if d) if (self.last_date or other.last_date) else None
        return Welford(n, mean, m2, last)


# --- líneas base y z-scores ------------------------------------------------------------


@dataclass(frozen=True)
class Baseline:
    mean: float
    sd: float
    p05: float | None = None
    p50: float | None = None
    p95: float | None = None
    n: int = 0
    kind: str = "terrestrial"


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Percentil con interpolación lineal (como numpy, método 'linear')."""
    if not sorted_values:
        return math.nan
    pos = (len(sorted_values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(sorted_values[lo])
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo))


def baseline_from(values: Iterable[float], kind: str = "terrestrial", min_sd: float = 1e-6) -> Baseline:
    data = sorted(v for v in values if v is not None and not math.isnan(v))
    if len(data) < 2:
        raise ValueError("Hacen falta al menos dos observaciones para una línea base")
    acc = Welford()
    for v in data:
        acc = acc.add(v)
    return Baseline(acc.mean, max(acc.sd, min_sd), percentile(data, 0.05), percentile(data, 0.5),
                    percentile(data, 0.95), acc.n, kind)


def zscore(x: float | None, baseline: Baseline | None) -> float:
    if x is None or baseline is None or math.isnan(x) or baseline.sd <= 0:
        return math.nan
    return (x - baseline.mean) / baseline.sd


def choose_baseline(terrestrial: Baseline | None, adaptation: Baseline | None,
                    mission_day: int, adaptation_days: int) -> Baseline | None:
    """Durante la fase operativa se usa la de adaptación si existe; la terrestre
    queda siempre como referencia de largo plazo."""
    if adaptation is not None and adaptation_days > 0 and mission_day > adaptation_days:
        return adaptation
    return terrestrial


# --- series temporales -----------------------------------------------------------------


def rolling_slope(points: Sequence[tuple[int, float]]) -> tuple[float, int]:
    """Pendiente por mínimos cuadrados (unidades por día) y número de puntos válidos."""
    valid = [(x, y) for x, y in points if y is not None and not math.isnan(y)]
    n = len(valid)
    if n < 2:
        return math.nan, n
    mx = sum(x for x, _ in valid) / n
    my = sum(y for _, y in valid) / n
    sxx = sum((x - mx) ** 2 for x, _ in valid)
    if sxx == 0:
        return math.nan, n
    sxy = sum((x - mx) * (y - my) for x, y in valid)
    return sxy / sxx, n


def window_stats(series: Mapping[date, float], today: date, days: int) -> dict[str, float | int]:
    """Media, pendiente y recuento de una ventana de `days` días que acaba hoy."""
    points = [((d - today).days, series.get(d, math.nan)) for d in
              (today - timedelta(days=k) for k in range(days - 1, -1, -1))]
    values = [y for _, y in points if not math.isnan(y)]
    slope, n = rolling_slope(points)
    return {
        "days": days,
        "n": n,
        "mean": sum(values) / len(values) if values else math.nan,
        "slope": slope,
    }


@dataclass(frozen=True)
class Filled:
    value: float
    measured_on: date | None
    age_days: int | None
    carried: bool
    protocol_warning: bool   # se superó la vigencia máxima sin nueva medición


def forward_fill(observations: Mapping[date, float], today: date, max_carry_days: int) -> Filled:
    """Valor vigente hoy con forward-fill controlado.

    - max_carry_days = 0: solo vale una medición del propio ciclo de 24 h.
    - max_carry_days = 7: variables semanales; más allá hay aviso de protocolo.
    Nunca se usan mediciones futuras.
    """
    past = [d for d, v in observations.items() if d <= today and v is not None and not math.isnan(v)]
    if not past:
        return Filled(math.nan, None, None, False, max_carry_days > 0)
    last = max(past)
    age = (today - last).days
    if age == 0:
        return Filled(float(observations[last]), last, 0, False, False)
    if age <= max_carry_days:
        return Filled(float(observations[last]), last, age, True, False)
    return Filled(math.nan, last, age, False, max_carry_days > 0)
