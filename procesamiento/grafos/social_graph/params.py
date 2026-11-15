"""Parámetros del modelo. Todos los tiempos en segundos y las distancias en metros."""

from dataclasses import dataclass

DAY_S = 86400.0

NORMALIZATIONS = ("overlap", "leisure")


@dataclass(frozen=True)
class Params:
    # Histéresis de proximidad
    d_in_m: float = 2.0
    d_out_m: float = 2.5
    min_dwell_s: float = 60.0
    max_gap_s: float = 60.0
    # Día de misión: segundos desde medianoche en que se corta el día
    day_cutoff_s: float = 4 * 3600.0
    # Normalización y peso
    normalization: str = "overlap"
    weight_fn: str = "exp"
    kappa: float = 0.3
    # Umbrales de evaluabilidad
    min_leisure_s: float = 1800.0
    min_overlap_s: float = 1800.0
    min_coverage: float = 0.5

    def __post_init__(self) -> None:
        if self.d_in_m <= 0 or self.d_out_m < self.d_in_m:
            raise ValueError("Se requiere 0 < d_in_m <= d_out_m")
        if self.min_dwell_s < 0 or self.max_gap_s <= 0:
            raise ValueError("Se requiere min_dwell_s >= 0 y max_gap_s > 0")
        if not 0 <= self.day_cutoff_s < DAY_S:
            raise ValueError("day_cutoff_s debe estar en [0, 86400)")
        if self.normalization not in NORMALIZATIONS:
            raise ValueError(f"normalization debe ser una de {NORMALIZATIONS}")
        if self.kappa <= 0:
            raise ValueError("kappa debe ser > 0")
        if not 0 <= self.min_coverage <= 1:
            raise ValueError("min_coverage debe estar en [0, 1]")
