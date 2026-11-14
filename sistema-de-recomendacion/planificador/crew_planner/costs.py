"""Costes blandos: adecuación, incertidumbre, repetición y carga (diseño, sección 4).

Todo devuelve valores en [0, 1] con su desglose, para poder explicar cada
asignación. Las restricciones duras no están aquí: ver eligibility.py.
"""

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .config import PlannerConfig
from .history import History
from .model import HIGHER_BETTER, LOWER_BETTER, Astronaut, ParameterSpec, Requirement, Task
from .state import StateValue, normalize_natural, uncertainty_of


# --- adecuación e incertidumbre -----------------------------------------------


def deficit(z: float, t_min: float | None, t_max: float | None) -> float:
    """Déficit unilateral: estar mejor de lo requerido no penaliza."""
    below = t_min - z if t_min is not None else 0.0
    above = z - t_max if t_max is not None else 0.0
    return max(0.0, below, above)


def effective_weights(
    requirements: Sequence[Requirement], catalog: Mapping[str, ParameterSpec], max_share: float
) -> dict[str, float]:
    """Pesos q_jk con el peso de cada dominio limitado.

    Si un dominio supera `max_share` del peso total de la tarea, sus pesos se
    escalan hasta esa fracción del total original. Así varias variables
    correlacionadas del mismo dominio (p. ej. tres de sueño) no cuentan como
    evidencias independientes. Con un solo dominio no cambia nada tras normalizar.
    """
    weights = {r.parameter: r.weight for r in requirements if r.weight > 0}
    total = sum(weights.values())
    if total <= 0:
        return weights
    by_domain: dict[str, float] = defaultdict(float)
    for pid, w in weights.items():
        by_domain[catalog[pid].domain] += w
    out = {}
    for pid, w in weights.items():
        domain_total = by_domain[catalog[pid].domain]
        cap = max_share * total
        out[pid] = w * cap / domain_total if domain_total > cap else w
    return out


@dataclass(frozen=True)
class ParameterFit:
    parameter: str
    weight: float
    known: bool
    status: str
    deficit: float | None
    uncertainty: float
    natural: float | None


@dataclass(frozen=True)
class Adequacy:
    distance: float      # D_ij ∈ [0, 1], solo con parámetros conocidos
    uncertainty: float   # U_ij ∈ [0, 1]
    parameters: tuple[ParameterFit, ...]

    @property
    def unknown(self) -> list[str]:
        return [p.parameter for p in self.parameters if not p.known]


def adequacy(
    task: Task, state: Mapping[str, StateValue], catalog: Mapping[str, ParameterSpec], config: PlannerConfig
) -> Adequacy:
    q = effective_weights(task.requirements, catalog, config.adequacy.max_domain_share)
    fits = []
    num = den_known = num_u = den_all = 0.0
    for req in task.requirements:
        value = state[req.parameter]
        weight = q.get(req.parameter, 0.0)
        u = uncertainty_of(value)
        d = None
        if value.known:
            spec = catalog[req.parameter]
            t_min = normalize_natural(spec, req.min) if req.min is not None else None
            t_max = normalize_natural(spec, req.max) if req.max is not None else None
            d = deficit(value.z, t_min, t_max)
            num += weight * d * d
            den_known += weight
        num_u += weight * u
        den_all += weight
        fits.append(ParameterFit(req.parameter, weight, value.known, value.status, d, u, value.natural))
    return Adequacy(
        distance=math.sqrt(num / den_known) if den_known > 0 else 0.0,
        uncertainty=num_u / den_all if den_all > 0 else 0.0,
        parameters=tuple(fits),
    )


# --- repetición ----------------------------------------------------------------


def repetition(history: History, astronaut: str, task: Task, day: int, config: PlannerConfig) -> float:
    """R_ij ∈ [0, 1]: cuánto ha hecho esta categoría recientemente, con decaimiento.

    1 si la hizo todos los días de la ventana, 0 si ninguno. Un día cuenta una
    vez aunque la hiciera varias veces.
    """
    window, tau = config.repetition.window_days, config.repetition.tau_days
    days = {
        e.day for e in history.for_astronaut(astronaut, day, window) if e.category == task.category
    }
    weight = {d: math.exp(-(day - d) / tau) for d in range(day - window, day)}
    return sum(weight[d] for d in days) / sum(weight.values())


def monotony(task: Task, config: PlannerConfig) -> float:
    """λ_j = 1 − I_j: las tareas más importantes apenas se penalizan por repetirse."""
    return 1.0 - config.importance.normalize(task.importance)


# --- coste individual ----------------------------------------------------------


@dataclass(frozen=True)
class IndividualCost:
    state: float        # α_estado · I_j · D_ij
    repetition: float   # α_rep · λ_j · R_ij
    uncertainty: float  # α_inc · I_j · U_ij
    adequacy: Adequacy
    repetition_raw: float
    importance: float

    @property
    def total(self) -> float:
        return self.state + self.repetition + self.uncertainty


def individual_cost(
    task: Task,
    astronaut: str,
    state: Mapping[str, StateValue],
    history: History,
    day: int,
    config: PlannerConfig,
) -> IndividualCost:
    w = config.weights
    importance = config.importance.normalize(task.importance)
    fit = adequacy(task, state, config.parameters, config)
    r = repetition(history, astronaut, task, day, config)
    return IndividualCost(
        state=w.alpha_state * importance * fit.distance,
        repetition=w.alpha_repetition * monotony(task, config) * r,
        uncertainty=w.alpha_uncertainty * importance * fit.uncertainty,
        adequacy=fit,
        repetition_raw=r,
        importance=importance,
    )


# --- carga ---------------------------------------------------------------------


def task_load(task: Task) -> float:
    """w_j en horas equivalentes: cuenta el tiempo y lo pondera por la intensidad.

    Una tarea de intensidad 0 vale la mitad de su duración y una de intensidad 1,
    la duración completa: el tiempo ocupado también es carga.
    """
    return task.duration_min / 60.0 * (0.5 + 0.5 * task.intensity)


def capacity(state: Mapping[str, StateValue], catalog: Mapping[str, ParameterSpec], config: PlannerConfig) -> float:
    """g_i ∈ [capacity_min, 1] a partir de los parámetros de fatiga conocidos.

    Si no se conoce ninguno se toma el valor conservador capacity_min: no saber
    nunca equivale a estar descansado.
    """
    goodness = []
    for pid, spec in catalog.items():
        value = state.get(pid)
        if spec.domain != "fatigue" or value is None or not value.known:
            continue
        if spec.kind == HIGHER_BETTER:
            goodness.append(value.z)
        elif spec.kind == LOWER_BETTER:
            goodness.append(1.0 - value.z)
    g_min = config.workload.capacity_min
    if not goodness:
        return g_min
    return g_min + (1.0 - g_min) * sum(goodness) / len(goodness)


def target_shares(available_h: Mapping[str, float], capacities: Mapping[str, float]) -> dict[str, float]:
    """s_i = h_i·g_i / Σ h·g: parte de la carga total que corresponde a cada uno."""
    raw = {a: available_h[a] * capacities[a] for a in available_h}
    total = sum(raw.values())
    if total <= 0:
        return dict.fromkeys(available_h, 0.0)
    return {a: v / total for a, v in raw.items()}


def equity_cost(loads: Mapping[str, float], shares: Mapping[str, float], config: PlannerConfig,
                reference_h: float) -> float:
    """C_equidad para unas cargas dadas, con la misma fórmula que el optimizador.

    Desviación de cada uno respecto a su carga objetivo más β por la diferencia
    entre el más y el menos cargado (en carga relativa a su cuota). Sirve para
    explicar y para verificar el resultado del optimizador.
    """
    total = sum(loads.values())
    deviation = sum(abs(loads[a] - shares[a] * total) for a in loads)
    relative = [loads[a] / shares[a] for a in loads if shares[a] > 0]
    spread = max(relative) - min(relative) if relative else 0.0
    return config.weights.alpha_equity * deviation / reference_h + config.weights.beta_spread * spread / reference_h


def history_load(history: History, astronaut: Astronaut, day: int, days: int = 3) -> float:
    """Carga de los últimos días según el historial, para informar en la salida."""
    return sum(
        e.duration_min / 60.0 * (0.5 + 0.5 * e.intensity)
        for e in history.for_astronaut(astronaut.id, day, days)
    )
