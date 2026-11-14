"""Vector de estado normalizado de cada astronauta.

Para cada parámetro del catálogo se toma la última medición y se decide si es
conocida. Un parámetro es desconocido si no hay medición, si ha caducado o, para
los que se comparan con la línea base, si falta la línea base. Lo desconocido
nunca se rellena: se informa con su motivo.

Escalas:

- natural: unidades físicas (`minmax`) o puntuación z (`baseline_z`). En ella se
  expresan los umbrales de las tareas y se comprueban los requisitos críticos.
- normalizada `z ∈ [0, 1]`: la que usa la distancia. `minmax` recorta al rango
  fisiológico; `baseline_z` recorta la puntuación z a ±3 y la lleva a [0, 1].
"""

from collections.abc import Mapping
from dataclasses import dataclass

from .model import BASELINE_Z, Astronaut, ParameterSpec

KNOWN = "known"
MISSING = "missing"      # nunca medido
STALE = "stale"          # medido, pero fuera de su vigencia
NO_BASELINE = "no_baseline"  # se compara con la línea base y no la hay

Z_CLIP = 3.0


@dataclass(frozen=True)
class StateValue:
    parameter: str
    status: str
    raw: float | None = None
    natural: float | None = None
    z: float | None = None
    confidence: float | None = None
    age_h: float | None = None
    source: str | None = None

    @property
    def known(self) -> bool:
        return self.status == KNOWN


def _clip01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def normalize_natural(spec: ParameterSpec, natural: float) -> float:
    """Escala natural -> [0, 1]. Sirve igual para valores y para umbrales."""
    if spec.normalization == BASELINE_Z:
        return (min(max(natural, -Z_CLIP), Z_CLIP) + Z_CLIP) / (2 * Z_CLIP)
    return _clip01((natural - spec.lo) / (spec.hi - spec.lo))


def parameter_state(astronaut: Astronaut, spec: ParameterSpec, reference_s: float) -> StateValue:
    m = astronaut.latest(spec.id)
    if m is None:
        return StateValue(spec.id, MISSING)
    age_h = (reference_s - m.measured_at) / 3600.0
    base = {"raw": m.value, "confidence": m.confidence, "age_h": age_h, "source": m.source}
    if age_h > spec.validity_h:
        return StateValue(spec.id, STALE, **base)
    if spec.normalization == BASELINE_Z:
        baseline = astronaut.baselines.get(spec.id)
        if baseline is None:
            return StateValue(spec.id, NO_BASELINE, **base)
        natural = (m.value - baseline.mean) / baseline.sd
    else:
        natural = m.value
    return StateValue(spec.id, KNOWN, natural=natural, z=normalize_natural(spec, natural), **base)


def astronaut_state(
    astronaut: Astronaut, catalog: Mapping[str, ParameterSpec], reference_s: float
) -> dict[str, StateValue]:
    """Estado de todos los parámetros del catálogo, conocidos o no."""
    return {pid: parameter_state(astronaut, spec, reference_s) for pid, spec in catalog.items()}


def uncertainty_of(value: StateValue) -> float:
    """u_ik: 1 si es desconocido, 1 − confianza si la fuente la da, 0 si no la da.

    No se inventa una degradación gradual por antigüedad: dentro de la vigencia el
    dato vale; fuera, es desconocido.
    """
    if not value.known:
        return 1.0
    return 1.0 - value.confidence if value.confidence is not None else 0.0
