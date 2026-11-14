"""IsolationAnalyzer: indicadores de integración social y su evolución.

Produce un indicador estimativo, nunca un diagnóstico. Trabaja solo con los
resultados diarios (matriz, máscara y tiempos), no con posiciones.

Combina varias señales (docs/social_graph_design.md, sección 5):

- Descenso respecto a la línea base individual, en al menos dos indicadores.
- Integración baja frente al resto de la tripulación, sin depender de línea base.
- Aislamiento estructural en el grafo suavizado de varios días.

La falta de datos nunca cuenta como aislamiento: los días no evaluables se omiten.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any

Document = dict[str, Any]

INDICATORS = ("intensity", "accompanied", "degree", "diversity")

NORMAL = "normal"
FOLLOW_UP = "follow_up"  # seguimiento: una señal activa
REVIEW = "review"  # revisión por el equipo en Tierra: dos señales o aislamiento estructural
WARMING_UP = "warming_up"
NO_DATA = "no_data"
NOT_EVALUABLE = "not_evaluable"

SUSTAINED_DROP = "sustained_drop"
TREND = "trend"
LOW_VS_CREW = "low_vs_crew"
STRUCTURAL = "structural_isolation"
_BASELINE_SIGNALS = {SUSTAINED_DROP, TREND}


@dataclass(frozen=True)
class IsolationConfig:
    warmup_days: int = 7
    window_days: int = 21
    lag_days: int = 5
    z_alert: float = -2.5
    z_trend: float = -2.0
    persist_k: int = 3
    persist_m: int = 5
    min_indicators: int = 2
    crew_ratio_min: float = 0.5
    crew_k: int = 5
    crew_m: int = 7
    crew_drop_z: float = -2.0
    edge_min_w: float = 0.1
    smooth_days: int = 7
    scale_floor_rel: float = 0.1
    scale_floor_abs: float = 0.02


def day_indicators(doc: Document, edge_min_w: float) -> dict[str, dict[str, float | None] | None]:
    """Indicadores del día por astronauta. None si el astronauta no es evaluable."""
    crew = doc["crew"]
    out: dict[str, dict[str, float | None] | None] = {}
    for i, astronaut in enumerate(crew):
        if doc["node_status"][i] != "ok":
            out[astronaut] = None
            continue
        weights = [
            doc["weights"][i][j] for j in range(len(crew)) if j != i and doc["evaluable"][i][j]
        ]
        strength = sum(weights)
        diversity = None
        if strength > 0:
            shares = [w / strength for w in weights if w > 0]
            entropy = -sum(p * math.log(p) for p in shares)
            # Número efectivo de compañeros, como fracción de los evaluables
            diversity = math.exp(entropy) / len(weights)
        out[astronaut] = {
            "intensity": doc["strength_norm"][i],
            "accompanied": doc["accompanied"][i],
            "degree": sum(w >= edge_min_w for w in weights) / len(weights),
            "diversity": diversity,
        }
    return out


def smoothed_weights(docs: Sequence[Document]) -> list[list[float | None]]:
    """Media de W por pareja sobre los días en que fue evaluable. None si nunca lo fue."""
    n = len(docs[-1]["crew"])
    out: list[list[float | None]] = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            values = [d["weights"][i][j] for d in docs if d["evaluable"][i][j]]
            out[i][j] = sum(values) / len(values) if values else None
    return out


def _robust_z(value: float, baseline: Sequence[float], config: IsolationConfig) -> float:
    center = median(baseline)
    mad = median(abs(x - center) for x in baseline)
    scale = max(1.4826 * mad, config.scale_floor_rel * abs(center), config.scale_floor_abs)
    return (value - center) / scale


class IsolationAnalyzer:
    def __init__(self, config: IsolationConfig | None = None) -> None:
        self.config = config or IsolationConfig()

    def analyze(self, history: Sequence[Document]) -> list[Document]:
        """Evalúa todo el histórico en orden y devuelve una valoración por día."""
        config = self.config
        docs = sorted(history, key=lambda d: d["day"])
        # Por astronauta, sus días evaluables ya procesados
        past: dict[str, list[dict[str, Any]]] = {}
        crew_scores: list[float | None] = []
        out: list[Document] = []

        for index, doc in enumerate(docs):
            crew = doc["crew"]
            day = doc["day"]
            values = day_indicators(doc, config.edge_min_w)

            raw_z: dict[str, dict[str, float | None]] = {}
            for astronaut in crew:
                raw_z[astronaut] = self._z_scores(
                    values[astronaut], past.get(astronaut, []), day
                )

            smoothed = smoothed_weights(docs[max(0, index - config.smooth_days + 1): index + 1])

            # Indicador de tripulación: si la mayoría baja a la vez, es un fenómeno
            # de grupo y no se convierte en señales individuales
            composites = [
                median(zs) for zs in ([z for z in raw_z[a].values() if z is not None] for a in crew) if zs
            ]
            crew_score = median(composites) if len(composites) >= max(2, len(crew) // 2) else None
            crew_scores.append(crew_score)
            recent_crew = [s for s in crew_scores[-config.persist_m:] if s is not None]
            crew_drop = bool(sum(s <= config.crew_drop_z for s in recent_crew) >= config.persist_k)

            astronauts: dict[str, Document] = {}
            for i, astronaut in enumerate(crew):
                node_status = doc["node_status"][i]
                if values[astronaut] is None:
                    astronauts[astronaut] = {
                        "status": NO_DATA if node_status == "no_data" else NOT_EVALUABLE,
                        "signals": [], "score": None, "indicators": {},
                    }
                    continue

                # Se descuenta el descenso común: si todos bajan, no es algo individual
                adjusted: dict[str, float | None] = {}
                for name in INDICATORS:
                    z = raw_z[astronaut][name]
                    others = [
                        raw_z[b][name] for b in crew if b != astronaut and raw_z[b][name] is not None
                    ]
                    common = min(0.0, median(others)) if len(others) >= 2 else 0.0
                    adjusted[name] = None if z is None else z - common

                c_values = [
                    values[b]["accompanied"] for b in crew
                    if b != astronaut and values[b] is not None and values[b]["accompanied"] is not None
                ]
                own_c = values[astronaut]["accompanied"]
                low_today = (
                    own_c is not None and len(c_values) >= 2
                    and own_c < config.crew_ratio_min * median(c_values)
                )

                entry = {
                    "day": day, "values": values[astronaut], "z": adjusted,
                    "low_vs_crew": bool(low_today), "flagged": False,
                }
                recent = past.get(astronaut, []) + [entry]
                signals = self._signals(recent, smoothed[i], crew_drop)
                families = len({"baseline" if s in _BASELINE_SIGNALS else s for s in signals})
                defined = [z for z in adjusted.values() if z is not None]
                if STRUCTURAL in signals or families >= 2:
                    status = REVIEW
                elif families == 1:
                    status = FOLLOW_UP
                elif not defined:
                    status = WARMING_UP
                else:
                    status = NORMAL
                entry["flagged"] = status in (FOLLOW_UP, REVIEW)
                past.setdefault(astronaut, []).append(entry)

                astronauts[astronaut] = {
                    "status": status,
                    "signals": signals,
                    "score": median(defined) if defined else None,
                    "indicators": {
                        name: {"value": values[astronaut][name], "z": adjusted[name]}
                        for name in INDICATORS
                    },
                }

            out.append({
                "day": day,
                "crew": {"score": crew_score, "drop": crew_drop},
                "astronauts": astronauts,
            })
        return out

    def _z_scores(
        self, values: dict[str, float | None] | None, past: list[dict[str, Any]], day: int
    ) -> dict[str, float | None]:
        config = self.config
        scores: dict[str, float | None] = dict.fromkeys(INDICATORS)
        if values is None:
            return scores
        # Línea base: días anteriores con retraso y sin los ya señalados, para que
        # una deriva lenta no se convierta en la nueva normalidad
        pool = [e for e in past if e["day"] <= day - config.lag_days - 1 and not e["flagged"]]
        pool = pool[-config.window_days:]
        for name in INDICATORS:
            baseline = [e["values"][name] for e in pool if e["values"][name] is not None]
            if values[name] is not None and len(baseline) >= config.warmup_days:
                scores[name] = _robust_z(values[name], baseline, config)
        return scores

    def _signals(
        self, entries: list[dict[str, Any]], smoothed_row: list[float | None], crew_drop: bool
    ) -> list[str]:
        config = self.config
        signals = []
        window = entries[-config.persist_m:]
        sustained = trending = 0
        for name in INDICATORS:
            zs = [e["z"][name] for e in window if e["z"][name] is not None]
            if sum(z <= config.z_alert for z in zs) >= config.persist_k:
                sustained += 1
            if len(zs) >= config.persist_m and median(zs) <= config.z_trend:
                trending += 1
        if sustained >= config.min_indicators:
            signals.append(SUSTAINED_DROP)
        if trending >= config.min_indicators:
            signals.append(TREND)
        if sum(e["low_vs_crew"] for e in entries[-config.crew_m:]) >= config.crew_k:
            signals.append(LOW_VS_CREW)
        known = [w for w in smoothed_row if w is not None]
        if known and all(w < config.edge_min_w for w in known) and not crew_drop:
            signals.append(STRUCTURAL)
        return signals
