"""Acumuladores estadísticos incrementales y fusionables.

`Agg` resume una métrica en una ventana sin guardar las observaciones:

- recuento, media y suma de cuadrados centrada (Welford) -> varianza exacta;
- mínimo, máximo, primera y última observación (con su instante);
- recuento de ausentes e inválidos, separados de los válidos;
- histograma de bins fijos -> percentiles aproximados (error <= ancho de bin).

Dos `Agg` se funden con las fórmulas de Chan et al.: el resultado es el mismo
que si se hubieran visto todas las observaciones juntas. En particular la media
fundida pondera por recuento; no es la media de las medias.
"""

import math
from typing import Any

from .config import MetricSpec


class Agg:
    __slots__ = ("n", "mean", "m2", "min", "max", "first", "first_ts", "last", "last_ts",
                 "missing", "invalid", "hist")

    def __init__(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.min: float | None = None
        self.max: float | None = None
        self.first: float | None = None
        self.first_ts: float | None = None
        self.last: float | None = None
        self.last_ts: float | None = None
        self.missing = 0
        self.invalid = 0
        self.hist: dict[int, int] = {}

    # --- actualización ---------------------------------------------------------

    def add(self, value: float, ts: float, spec: MetricSpec | None = None) -> None:
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (value - self.mean)
        if self.min is None or value < self.min:
            self.min = value
        if self.max is None or value > self.max:
            self.max = value
        if self.first_ts is None or ts < self.first_ts:
            self.first, self.first_ts = value, ts
        if self.last_ts is None or ts >= self.last_ts:
            self.last, self.last_ts = value, ts
        if spec is not None:
            index = spec.bin_of(value)
            self.hist[index] = self.hist.get(index, 0) + 1

    def merge(self, other: "Agg") -> None:
        """Incorpora `other`. Equivale a haber visto sus observaciones una a una."""
        self.missing += other.missing
        self.invalid += other.invalid
        if other.n == 0:
            return
        if self.n == 0:
            self.n, self.mean, self.m2 = other.n, other.mean, other.m2
            self.min, self.max = other.min, other.max
            self.first, self.first_ts = other.first, other.first_ts
            self.last, self.last_ts = other.last, other.last_ts
            self.hist = dict(other.hist)
            return
        total = self.n + other.n
        delta = other.mean - self.mean
        self.m2 += other.m2 + delta * delta * self.n * other.n / total
        self.mean += delta * other.n / total
        self.n = total
        self.min = min(self.min, other.min)
        self.max = max(self.max, other.max)
        if other.first_ts < self.first_ts:
            self.first, self.first_ts = other.first, other.first_ts
        if other.last_ts >= self.last_ts:
            self.last, self.last_ts = other.last, other.last_ts
        for index, count in other.hist.items():
            self.hist[index] = self.hist.get(index, 0) + count

    # --- lectura ---------------------------------------------------------------

    @property
    def variance(self) -> float | None:
        """Varianza muestral (n − 1). None con menos de dos observaciones."""
        if self.n < 2:
            return None
        return max(self.m2, 0.0) / (self.n - 1)

    @property
    def std(self) -> float | None:
        variance = self.variance
        return None if variance is None else math.sqrt(variance)

    def quantile(self, q: float, spec: MetricSpec | None) -> float | None:
        """Cuantil aproximado a partir del histograma, interpolando dentro del bin."""
        if spec is None or self.n == 0 or not self.hist:
            return None
        target = q * self.n
        seen = 0
        for index in sorted(self.hist):
            count = self.hist[index]
            if seen + count >= target:
                inside = (target - seen) / count
                value = spec.hist_min + (index + inside) * spec.bin_width
                return min(max(value, self.min), self.max)
            seen += count
        return self.max

    def stats(self, spec: MetricSpec | None = None) -> dict[str, Any]:
        """Resumen legible. Lo que no se puede calcular va como None, nunca como 0."""
        empty = self.n == 0
        return {
            "count": self.n + self.missing + self.invalid,
            "valid_count": self.n,
            "missing_count": self.missing,
            "invalid_count": self.invalid,
            "mean": None if empty else self.mean,
            "std": self.std,
            "min": self.min,
            "max": self.max,
            "first": self.first,
            "last": self.last,
            "p05": self.quantile(0.05, spec),
            "median": self.quantile(0.5, spec),
            "p95": self.quantile(0.95, spec),
        }

    # --- serialización compacta --------------------------------------------------

    def dump(self) -> list[Any]:
        hist: list[int] = []
        for index in sorted(self.hist):
            hist += (index, self.hist[index])
        return [self.n, self.mean, self.m2, self.min, self.max, self.first, self.first_ts,
                self.last, self.last_ts, self.missing, self.invalid, hist]

    @classmethod
    def load(cls, raw: list[Any]) -> "Agg":
        agg = cls()
        (agg.n, agg.mean, agg.m2, agg.min, agg.max, agg.first, agg.first_ts,
         agg.last, agg.last_ts, agg.missing, agg.invalid, hist) = raw
        agg.hist = dict(zip(hist[::2], hist[1::2]))
        return agg


class Trend:
    """Pendiente de una métrica frente al tiempo por mínimos cuadrados, incremental.

    Mantiene la covarianza tiempo-valor y la varianza del tiempo con la misma
    recurrencia que Welford. No depende del orden de llegada.
    """

    __slots__ = ("n", "mean_t", "mean_x", "c_tx", "m2_t")

    def __init__(self, raw: list[float] | None = None) -> None:
        self.n, self.mean_t, self.mean_x, self.c_tx, self.m2_t = raw or [0, 0.0, 0.0, 0.0, 0.0]

    def add(self, t: float, x: float) -> None:
        self.n += 1
        dt = t - self.mean_t
        self.mean_t += dt / self.n
        self.mean_x += (x - self.mean_x) / self.n
        self.c_tx += dt * (x - self.mean_x)
        self.m2_t += dt * (t - self.mean_t)

    @property
    def slope(self) -> float | None:
        """Unidades de la métrica por segundo. None si no hay recorrido temporal."""
        if self.n < 2 or self.m2_t <= 0:
            return None
        return self.c_tx / self.m2_t

    def dump(self) -> list[float]:
        return [self.n, self.mean_t, self.mean_x, self.c_tx, self.m2_t]


class Ewma:
    """Media y varianza exponenciales, con olvido según el tiempo transcurrido.

    Sirve de referencia local para detectar anomalías: durante la noche las
    constantes derivan, así que la media de toda la sesión no es buena referencia.
    """

    __slots__ = ("n", "mean", "var", "last_ts")

    def __init__(self, raw: list[Any] | None = None) -> None:
        self.n, self.mean, self.var, self.last_ts = raw or [0, 0.0, 0.0, None]

    def zscore(self, value: float, min_std: float, warmup_n: int) -> float | None:
        if self.n < warmup_n:
            return None
        return (value - self.mean) / max(math.sqrt(self.var), min_std)

    def std(self, min_std: float) -> float:
        return max(math.sqrt(self.var), min_std)

    def update(self, value: float, ts: float, halflife_s: float, warmup_n: int) -> None:
        if self.last_ts is not None and ts < self.last_ts:
            return  # un dato atrasado no mueve la referencia
        if self.n == 0:
            self.n, self.mean, self.var, self.last_ts = 1, value, 0.0, ts
            return
        alpha = 1.0 - math.exp(-math.log(2.0) * (ts - self.last_ts) / halflife_s)
        if self.n < warmup_n:
            alpha = max(alpha, 1.0 / (self.n + 1))
        diff = value - self.mean
        incr = alpha * diff
        self.mean += incr
        self.var = (1.0 - alpha) * (self.var + diff * incr)
        self.n += 1
        self.last_ts = ts

    def dump(self) -> list[Any]:
        return [self.n, self.mean, self.var, self.last_ts]
