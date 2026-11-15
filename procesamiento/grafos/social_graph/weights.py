"""Normalización R y funciones de peso W: [0, 1] -> [0, 1].

Todas las funciones de peso son monótonas crecientes con W(0) = 0 y W(1) = 1.
"""

from collections.abc import Callable

import numpy as np

WeightFn = Callable[[np.ndarray], np.ndarray]


def harmonic_mean(a: float, b: float) -> float:
    return 2 * a * b / (a + b) if a > 0 and b > 0 else 0.0


def r_leisure(interaction: float, leisure_i: float, leisure_j: float) -> float:
    """R_ocio = (I/T_i + I/T_j) / 2 = I / H(T_i, T_j)."""
    if leisure_i <= 0 or leisure_j <= 0:
        return float("nan")
    return (interaction / leisure_i + interaction / leisure_j) / 2


def r_overlap(interaction: float, overlap_observed: float) -> float:
    """R_solape = I / O_obs: fracción del ocio simultáneo observado que pasan juntos."""
    if overlap_observed <= 0:
        return float("nan")
    return interaction / overlap_observed


def alignment(overlap: float, leisure_i: float, leisure_j: float) -> float:
    """A = O / H(T_i, T_j): cuánto coinciden los ocios. R_ocio = R_solape · A."""
    h = harmonic_mean(leisure_i, leisure_j)
    return overlap / h if h > 0 else float("nan")


def _exp(kappa: float) -> WeightFn:
    return lambda r: -np.expm1(-r / kappa) / -np.expm1(-1 / kappa)


def _tanh(kappa: float) -> WeightFn:
    return lambda r: np.tanh(r / kappa) / np.tanh(1 / kappa)


def _log1p(kappa: float) -> WeightFn:
    return lambda r: np.log1p(r / kappa) / np.log1p(1 / kappa)


def _hill(kappa: float, n: float = 1.0) -> WeightFn:
    # Renormalizada para valer 1 en R = 1; kappa hace de constante de semisaturación
    return lambda r: (r**n / (r**n + kappa**n)) * (1 + kappa**n)


_FACTORIES: dict[str, Callable[[float], WeightFn]] = {
    "exp": _exp,
    "linear": lambda _kappa: lambda r: r,
    "tanh": _tanh,
    "log1p": _log1p,
    "hill": _hill,
    "sqrt": lambda _kappa: np.sqrt,
}

WEIGHT_FUNCTIONS = tuple(_FACTORIES)


def get_weight_fn(name: str, kappa: float) -> WeightFn:
    if name not in _FACTORIES:
        raise ValueError(f"Función de peso desconocida: {name}. Opciones: {WEIGHT_FUNCTIONS}")
    fn = _FACTORIES[name](kappa)
    return lambda r: np.asarray(fn(np.asarray(r, dtype=float)), dtype=float)
