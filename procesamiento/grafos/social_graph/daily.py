"""Cierre del día: de los totales en bruto a la matriz diaria con su máscara.

Distingue cuatro casos por pareja y nunca interpreta la falta de datos como
ausencia de relación:

- interaction:    evaluable y con interacción.
- zero:           evaluable y sin interacción.
- no_data:        no hay datos de la pareja en su ocio simultáneo.
- not_evaluable:  ocio, solape o cobertura insuficientes para decir nada.
"""

import logging
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields
from typing import Any

import numpy as np

from .intervals import intersect, total
from .params import Params
from .schedule import Schedule, day_window, leisure
from .tracker import DayTotals
from .validation import pair_key
from .weights import alignment, get_weight_fn, r_leisure, r_overlap

logger = logging.getLogger(__name__)

INTERACTION = "interaction"
ZERO = "zero"
NO_DATA = "no_data"
NOT_EVALUABLE = "not_evaluable"
OK = "ok"

_EPS = 1e-9


@dataclass
class DayResult:
    """Resultado diario. Matrices N×N en el orden de `crew`; tiempos en segundos."""

    day: int
    crew: list[str]
    params: Params
    # Por astronauta
    leisure_s: np.ndarray
    leisure_observed_s: np.ndarray
    available_observed_s: np.ndarray  # ocio observado con algún otro también en ocio
    accompanied: np.ndarray  # C_i: fracción de ese ocio compartible con alguien cerca
    strength: np.ndarray  # S_i = Σ_j W_ij sobre parejas evaluables
    strength_norm: np.ndarray  # media de W_ij sobre parejas evaluables
    node_status: list[str]
    # Por pareja
    interaction_s: np.ndarray
    overlap_s: np.ndarray
    overlap_observed_s: np.ndarray
    coverage: np.ndarray
    r_overlap: np.ndarray
    r_leisure: np.ndarray
    alignment: np.ndarray
    status: np.ndarray  # matriz de cadenas; diagonal vacía
    evaluable: np.ndarray  # máscara booleana
    weights: np.ndarray  # W: simétrica, diagonal 0, en [0, 1]; 0 donde no es evaluable
    # Calidad de datos
    n_samples: int
    bound_violations: int

    def to_dict(self) -> dict[str, Any]:
        """Documento JSON para el histórico. Los valores no definidos van como null."""
        skip = {"params", "n_samples", "bound_violations"}
        doc = {f.name: _jsonable(getattr(self, f.name)) for f in fields(self) if f.name not in skip}
        doc["params"] = asdict(self.params)
        doc["quality"] = {"n_samples": self.n_samples, "bound_violations": self.bound_violations}
        return doc


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _pair_status(
    params: Params,
    leisure_i: float,
    leisure_j: float,
    overlap: float,
    observed: float,
    interaction: float,
) -> str:
    if leisure_i < params.min_leisure_s or leisure_j < params.min_leisure_s:
        return NOT_EVALUABLE
    if params.normalization == "overlap":
        if overlap < params.min_overlap_s:
            return NOT_EVALUABLE
        if observed <= 0:
            return NO_DATA
        if observed < params.min_overlap_s or observed / overlap < params.min_coverage:
            return NOT_EVALUABLE
    else:
        # Sin ocio simultáneo no pueden interactuar: es un cero legítimo
        if overlap > 0:
            if observed <= 0:
                return NO_DATA
            if observed / overlap < params.min_coverage:
                return NOT_EVALUABLE
    return INTERACTION if interaction > 0 else ZERO


def close_day(
    day: int,
    crew: Sequence[str],
    totals: DayTotals,
    schedule: Schedule,
    params: Params,
) -> DayResult:
    crew = list(crew)
    n = len(crew)
    window = day_window(day, params.day_cutoff_s)
    leisures = [leisure(schedule, a, window) for a in crew]
    leisure_s = np.array([total(x) for x in leisures], dtype=float)
    leisure_obs = np.array([totals.leisure_observed.get(a, 0.0) for a in crew], dtype=float)
    available_obs = np.array([totals.available_observed.get(a, 0.0) for a in crew], dtype=float)
    accompanied_s = np.array([totals.accompanied.get(a, 0.0) for a in crew], dtype=float)

    interaction = np.zeros((n, n))
    overlap = np.zeros((n, n))
    observed = np.zeros((n, n))
    coverage = np.full((n, n), np.nan)
    r_ov = np.full((n, n), np.nan)
    r_le = np.full((n, n), np.nan)
    align = np.full((n, n), np.nan)
    status = np.full((n, n), "", dtype=object)
    evaluable = np.zeros((n, n), dtype=bool)
    r_used = np.zeros((n, n))
    violations = 0

    for i in range(n):
        for j in range(i + 1, n):
            key = pair_key(crew[i], crew[j])
            i_ij = totals.interaction.get(key, 0.0)
            o_obs = totals.overlap_observed.get(key, 0.0)
            o_ij = total(intersect(leisures[i], leisures[j]))

            # Cota I <= O_obs <= O. Si falla hay un error de lógica: se avisa, no se oculta
            if i_ij > o_obs + _EPS or o_obs > o_ij + _EPS:
                violations += 1
                logger.error(
                    "Cota incumplida día %s pareja %s: I=%.3f O_obs=%.3f O=%.3f",
                    day, key, i_ij, o_obs, o_ij,
                )

            st = _pair_status(params, leisure_s[i], leisure_s[j], o_ij, o_obs, i_ij)
            values = (
                (interaction, i_ij),
                (overlap, o_ij),
                (observed, o_obs),
                (coverage, o_obs / o_ij if o_ij > 0 else np.nan),
                (r_ov, r_overlap(i_ij, o_obs)),
                (r_le, r_leisure(i_ij, leisure_s[i], leisure_s[j])),
                (align, alignment(o_ij, leisure_s[i], leisure_s[j])),
            )
            for matrix, value in values:
                matrix[i, j] = matrix[j, i] = value
            status[i, j] = status[j, i] = st
            if st in (INTERACTION, ZERO):
                evaluable[i, j] = evaluable[j, i] = True
                r = r_ov[i, j] if params.normalization == "overlap" else r_le[i, j]
                r = 0.0 if math.isnan(r) else r
                r_used[i, j] = r_used[j, i] = min(max(r, 0.0), 1.0)

    weights = np.where(evaluable, get_weight_fn(params.weight_fn, params.kappa)(r_used), 0.0)
    np.fill_diagonal(weights, 0.0)

    n_evaluable = evaluable.sum(axis=1)
    strength = weights.sum(axis=1)
    strength_norm = np.where(n_evaluable > 0, strength / np.maximum(n_evaluable, 1), np.nan)
    # Se divide por el ocio en que había alguien disponible: quien descansa cuando
    # los demás trabajan o duermen no está "solo" por elección
    enough_available = available_obs >= params.min_leisure_s
    c = np.where(enough_available, accompanied_s / np.maximum(available_obs, _EPS), np.nan)

    min_pairs = math.ceil((n - 1) / 2)
    node_status = []
    for i in range(n):
        if leisure_s[i] < params.min_leisure_s:
            node_status.append(NOT_EVALUABLE)
        elif leisure_obs[i] <= 0:
            node_status.append(NO_DATA)
        elif leisure_obs[i] / leisure_s[i] < params.min_coverage or n_evaluable[i] < min_pairs:
            node_status.append(NOT_EVALUABLE)
        else:
            node_status.append(OK)

    return DayResult(
        day=day,
        crew=crew,
        params=params,
        leisure_s=leisure_s,
        leisure_observed_s=leisure_obs,
        available_observed_s=available_obs,
        accompanied=c,
        strength=strength,
        strength_norm=strength_norm,
        node_status=node_status,
        interaction_s=interaction,
        overlap_s=overlap,
        overlap_observed_s=observed,
        coverage=coverage,
        r_overlap=r_ov,
        r_leisure=r_le,
        alignment=align,
        status=status,
        evaluable=evaluable,
        weights=weights,
        n_samples=totals.n_samples,
        bound_violations=violations,
    )
