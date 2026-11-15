"""Capa conductual: check-in, PVT-B, entrevista, ejercicio y pregunta doble."""

from __future__ import annotations

import math
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Reutiliza la validación del check-in de procesamiento/test-cerrado (rama testPreguntasCerradas).
# En Docker, checkin.py se copia a la raíz de /app; en local se añade su carpeta al path.
_CERRADO = Path(__file__).resolve().parents[2] / "test-cerrado"
if _CERRADO.is_dir() and str(_CERRADO) not in sys.path:
    sys.path.append(str(_CERRADO))
import checkin as cerrado  # noqa: E402

CHECKIN_QUESTIONS = (
    ("sleep", "¿Cómo has dormido?", "1 = muy mal, 5 = muy bien"),
    ("fatigue", "¿Cuánto cansancio sientes?", "1 = nada, 5 = mucho"),
    ("workload", "¿Cómo es tu carga de trabajo?", "1 = muy baja, 5 = muy alta"),
    ("mood", "¿Qué tal tu ánimo?", "1 = muy bajo, 5 = muy bueno"),
    ("cohesion", "¿Qué tal la convivencia?", "1 = muy mala, 5 = muy buena"),
)
DOUBLE_QUESTION = "¿Qué nota crees que pondrá de media el resto del equipo?"

# Preguntas de la entrevista de audio (README, sección 2.C). Neutras y sin palabras negativas.
INTERVIEW_QUESTIONS = (
    "¿Cómo describirías tu día de ayer?",
    "¿En qué has estado pensando estos días?",
    "¿Qué has hecho en tus ratos libres?",
    "¿Cómo describirías el ambiente en la nave esta semana?",
    "¿Qué tienes previsto para los próximos días?",
    "Cuéntame cómo fue tu última conversación larga con alguien del equipo.",
    "¿Cómo ha ido tu trabajo esta semana?",
    "¿Qué has notado distinto en ti desde que empezó la misión?",
)

PVT_DURATION_S = 180.0
PVT_LAPSE_MS = 500.0
PVT_FALSE_START_MS = 100.0


def validate_checkin(astronaut_id: str, on: date, answers: dict[str, int],
                     estimated_team_mean: int | None = None) -> dict[str, int]:
    """Valida con el modelo de test-cerrado (1-5, enteros).

    test-cerrado pregunta por 'descanso' (`rested`, 5 = muy descansado); Orbivia
    registra 'cansancio' (5 = muy cansado), que es lo que pide el README. Se
    validan los mismos rangos y se guarda en la escala de cansancio.
    """
    required = [q for q, _, _ in CHECKIN_QUESTIONS]
    missing = [q for q in required if q not in answers]
    if missing:
        raise ValueError(f"Faltan respuestas: {missing}")
    fatigue = answers["fatigue"]
    # Se convierte a la escala de descanso de test-cerrado; un valor no entero se
    # pasa tal cual para que lo rechace su validación.
    rested = 6 - fatigue if type(fatigue) is int else fatigue
    cerrado.CheckIn(
        participant_id=astronaut_id, date=on,
        sleep_quality=answers["sleep"], rested=rested,
        workload=answers["workload"], mood=answers["mood"], team_cohesion=answers["cohesion"],
        estimated_team_mean=estimated_team_mean,
    )
    return {q: int(answers[q]) for q in required}


# --- PVT-B ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PvtScore:
    mean_rt_ms: float
    lapses: int
    false_starts: int
    trials: int
    duration_s: float


def score_pvt(reaction_times_ms: Sequence[float], duration_s: float, false_starts: int = 0) -> PvtScore:
    """PVT-B de 3 minutos. Lapsos: RT >= 500 ms (criterio habitual del PVT-B).
    Respuestas < 100 ms se cuentan como salidas en falso."""
    if duration_s <= 0:
        raise ValueError("La duración del test debe ser positiva")
    valid, extra_false = [], 0
    for rt in reaction_times_ms:
        if not isinstance(rt, (int, float)) or math.isnan(rt) or rt < 0 or rt > 30000:
            raise ValueError(f"Tiempo de reacción no válido: {rt!r}")
        if rt < PVT_FALSE_START_MS:
            extra_false += 1
        else:
            valid.append(float(rt))
    if not valid:
        raise ValueError("El PVT-B no tiene respuestas válidas")
    return PvtScore(
        mean_rt_ms=round(sum(valid) / len(valid), 2),
        lapses=sum(1 for rt in valid if rt >= PVT_LAPSE_MS),
        false_starts=false_starts + extra_false,
        trials=len(valid),
        duration_s=round(duration_s, 1),
    )


# --- entrevista de audio --------------------------------------------------------------


def interview_due(mission_day: int, interval_days: int = 3) -> bool:
    return interval_days >= 1 and mission_day >= 1 and (mission_day - 1) % interval_days == 0


def interview_question(mission_day: int, interval_days: int = 3) -> tuple[int, str]:
    """Pregunta que toca en la entrevista de ese ciclo. Rotan las ocho en orden."""
    session = max(0, (mission_day - 1) // max(1, interval_days))
    index = session % len(INTERVIEW_QUESTIONS)
    return index + 1, INTERVIEW_QUESTIONS[index]


# --- ejercicio --------------------------------------------------------------------------


def needs_implementation_intention(history: Iterable[tuple[date, bool]]) -> bool:
    """True si los dos últimos días registrados son omisiones consecutivas."""
    days = sorted(history)
    if len(days) < 2:
        return False
    (d1, done1), (d2, done2) = days[-2], days[-1]
    return (d2 - d1).days == 1 and not done1 and not done2


# --- pregunta doble ---------------------------------------------------------------------


@dataclass(frozen=True)
class DoubleQuestionResult:
    astronaut_id: str
    predicted_mean: int
    actual_peer_mean: float
    difference: float
    peers_count: int


def compare_double_question(answers: Sequence[tuple[str, int, int]], on: date) -> list[DoubleQuestionResult]:
    """`answers`: (astronauta, convivencia, media que predice). Reutiliza
    `compare_weekly_team_means` de test-cerrado. El resultado de cada persona
    solo se muestra a ella misma y al médico; nunca las respuestas de los demás."""
    entries = [
        cerrado.CheckIn(participant_id=a, date=on, sleep_quality=3, rested=3, workload=3, mood=3,
                        team_cohesion=cohesion, estimated_team_mean=predicted)
        for a, cohesion, predicted in answers
    ]
    return [
        DoubleQuestionResult(c.participant_id, c.predicted_mean, round(c.actual_peer_mean, 3),
                             round(c.difference, 3), c.peers_count)
        for c in cerrado.compare_weekly_team_means(entries, on)
    ]
