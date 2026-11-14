"""Puente entre el resumen de sueño y el vector diario de estado de Orbivia.

El módulo de sueño no importa código del planificador: solo emite mediciones con
el formato que este ya acepta (`crew_planner.model.Measurement`):

    {"parameter", "value", "measured_at", "source", "confidence"}

Solo se emiten los dos parámetros del catálogo del planificador que este módulo
mide de verdad:

- `sleep_duration_h`: sueño estimado por actigrafía, en horas.
- `sleep_quality`: eficiencia del sueño en %, minutos sin actividad entre
  minutos con dato de movimiento.

No se emiten `spo2` ni `resting_hr`: en el catálogo son medidas diurnas (ping
diario y reposo despierto) y sus valores nocturnos no son equivalentes.

`confidence` es la fracción de minutos de la sesión con dato de movimiento: si
el sensor falló media noche, el planificador lo sabe.

Quien quiera el vector completo lo tiene en el resumen (`sleep_summary_vector`
y `normalized_vector`) y se entera de que existe por el stream de avisos
`{prefijo}:summaries`.
"""

from typing import Any

SOURCE = "sleep_stream:actigraphy"


def planner_measurements(summary: dict[str, Any], mission_epoch_s: float = 0.0) -> list[dict[str, Any]]:
    """Mediciones del resumen para el planificador.

    `mission_epoch_s`: epoch Unix del segundo 0 de la misión. El planificador
    trabaja en segundos de misión; con 0 los instantes pasan tal cual.
    """
    sleep = summary["sleep"]
    measured_at = summary["session_metadata"]["end_timestamp"] - mission_epoch_s
    confidence = sleep["activity_coverage"]
    out = []
    if sleep["estimated_sleep_s"] is not None:
        out.append({"parameter": "sleep_duration_h", "value": sleep["estimated_sleep_s"] / 3600.0})
    if sleep["sleep_efficiency"] is not None:
        out.append({"parameter": "sleep_quality", "value": 100.0 * sleep["sleep_efficiency"]})
    for item in out:
        item.update(measured_at=measured_at, source=SOURCE, confidence=confidence)
    return out
