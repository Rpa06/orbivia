"""CollaborationRecommender: propuestas de actividades conjuntas voluntarias.

Busca oportunidades de ampliar la convivencia (parejas con poca interacción,
grupos poco conectados, personas poco integradas) y propone parejas o tríos en
una ventana de ocio común. Son propuestas para que las revise un responsable de
misión, nunca asignaciones, y nunca tareas operativas.

Solo usa métricas observables del grafo y los horarios. Cada propuesta lleva dos
textos: una justificación numérica para Tierra y un texto neutro para la
tripulación, que no revela métricas ni motivos.
"""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from statistics import median
from typing import Any

from .intervals import Interval, intersect, total
from .params import DAY_S

Document = dict[str, Any]

WEAK_PAIR = "weak_pair"
LOW_INTEGRATION = "low_integration"
CROSS_COMMUNITY = "cross_community"
BRIDGE = "bridge"

_LOW_STATUSES = {"follow_up", "review"}
_SLOT_S = 900.0
_UNKNOWN_STATUSES = {"no_data", "not_evaluable"}

# (actividad, tamaños de grupo admitidos). El grafo no dice qué actividad conviene
# a quién: el tipo solo depende del tamaño y va rotando.
ACTIVITIES: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("ejercicio cooperativo", (2, 3)),
    ("simulación conjunta no crítica", (2, 3)),
    ("actividad de convivencia", (2, 3)),
    ("entrenamiento en equipo", (3,)),
    ("proyecto o experimento colaborativo", (2, 3)),
)


@dataclass(frozen=True)
class RecommenderConfig:
    max_per_day: int = 2
    max_per_person_week: int = 2
    week_days: int = 7
    min_window_s: float = 2700.0  # ventana de ocio común mínima; también la duración propuesta
    max_leisure_fraction: float = 0.33
    group_sizes: tuple[int, ...] = (2, 3)
    weak_w: float = 0.15
    bonus_low_integration: float = 0.5
    bonus_cross_community: float = 0.5
    bonus_bridge: float = 0.25
    penalty_recent: float = 0.5


def _clock(t: float) -> str:
    seconds = int(round(t % DAY_S))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def _names(members: Sequence[str]) -> str:
    return members[0] if len(members) == 1 else ", ".join(members[:-1]) + " y " + members[-1]


class CollaborationRecommender:
    def __init__(self, config: RecommenderConfig | None = None) -> None:
        self.config = config or RecommenderConfig()

    def recommend(
        self,
        assessment: Document,
        leisure: Mapping[str, Sequence[Interval]],
        target_day: int,
        history: Sequence[Document] = (),
    ) -> Document:
        """Propuestas para `target_day` a partir de la valoración del día anterior.

        `leisure` son los intervalos de ocio de cada astronauta ese día e
        `history` las propuestas anteriores (con `day` y `participants`).
        """
        config = self.config
        structure = assessment["structure"]
        crew = list(assessment["astronauts"])
        index = {a: i for i, a in enumerate(crew)}
        smoothed = structure["smoothed_weights"]
        status = {a: assessment["astronauts"][a]["status"] for a in crew}

        def weight(a: str, b: str) -> float | None:
            return smoothed[index[a]][index[b]]

        known = [w for a, b in combinations(crew, 2) if (w := weight(a, b)) is not None]
        crew_median = median(known) if known else None
        weak_limit = config.weak_w if crew_median is None else max(config.weak_w, 0.5 * crew_median)

        communities = structure["communities"] if structure["clear"] else []
        community_of = {a: k for k, members in enumerate(communities) for a in members}
        between = {
            (b["a"], b["b"]): b["mean_weight"] for b in structure["between_communities"]
        }
        low = {a for a in crew if status[a] in _LOW_STATUSES or a in structure["isolated"]}

        recent = Counter(
            a for p in history
            if target_day - config.week_days < p["day"] <= target_day
            for a in p["participants"]
        )

        # Parejas con poca interacción y sin ocio común: es un asunto de horarios
        schedule_issues = []
        for a, b in combinations(crew, 2):
            w = weight(a, b)
            if w is not None and w < weak_limit and self._window(leisure, (a, b)) is None:
                schedule_issues.append({"pair": [a, b], "reason": "no_common_leisure"})

        candidates = []
        for size in sorted(set(config.group_sizes)):
            for group in combinations(crew, size):
                candidate = self._evaluate(
                    group, weight, weak_limit, status, low, community_of, between,
                    structure["bridges"], leisure, crew_median,
                )
                if candidate is not None:
                    candidates.append(candidate)

        proposals: list[Document] = []
        used_today: set[str] = set()
        counts = Counter(recent)
        n_previous = len(history)
        while len(proposals) < config.max_per_day:
            best = None
            for candidate in candidates:
                members = candidate["participants"]
                if used_today & set(members):
                    continue
                if any(counts[a] >= config.max_per_person_week for a in members):
                    continue
                score = candidate["gain"] - config.penalty_recent * sum(
                    counts[a] for a in members
                ) / len(members)
                # Orden total y estable: puntuación, luego grupos pequeños, luego nombres
                key = (-round(score, 9), len(members), members)
                if best is None or key < best[0]:
                    best = (key, candidate, score)
            if best is None:
                break
            _, candidate, score = best
            members = candidate["participants"]
            proposals.append(self._proposal(
                candidate, score, target_day, assessment["day"], len(proposals),
                n_previous + len(proposals), {a: counts[a] for a in members},
            ))
            used_today |= set(members)
            counts.update(members)

        return {
            "day": target_day,
            "based_on_day": assessment["day"],
            "proposals": proposals,
            "schedule_issues": schedule_issues,
        }

    # --- evaluación de un grupo -----------------------------------------------

    def _window(
        self, leisure: Mapping[str, Sequence[Interval]], group: Sequence[str]
    ) -> Interval | None:
        """Ventana dentro del tramo de ocio común más largo, sin cargar a nadie."""
        config = self.config
        common = list(leisure.get(group[0], ()))
        for astronaut in group[1:]:
            common = intersect(common, leisure.get(astronaut, ()))
        for astronaut in group:
            own = total(leisure.get(astronaut, ()))
            if own <= 0 or config.min_window_s > config.max_leisure_fraction * own:
                return None
        fitting = [iv for iv in common if iv[1] - iv[0] >= config.min_window_s]
        if not fitting:
            return None
        # El tramo más largo (el primero si hay empate) deja más margen alrededor
        start, end = max(fitting, key=lambda iv: (iv[1] - iv[0], -iv[0]))
        rounded = math.ceil(start / _SLOT_S) * _SLOT_S  # hora en punto, y cuarto, y media...
        if rounded + config.min_window_s <= end:
            start = rounded
        return (start, start + config.min_window_s)

    def _evaluate(
        self, group, weight, weak_limit, status, low, community_of, between, bridges,
        leisure, crew_median,
    ) -> Document | None:
        config = self.config
        if any(status[a] in _UNKNOWN_STATUSES for a in group):
            return None  # sin datos no se sabe si hay algo que mejorar
        pairs = list(combinations(group, 2))
        weights = {pair: weight(*pair) for pair in pairs}
        if any(w is None for w in weights.values()):
            return None
        if len(group) >= 3 and all(a in low for a in group):
            return None  # al menos una persona bien conectada en cada trío

        reasons = []
        weak_pairs = [pair for pair in pairs if weights[pair] < weak_limit]
        if weak_pairs:
            reasons.append(WEAK_PAIR)
        low_members = [a for a in group if a in low]
        if low_members:
            reasons.append(LOW_INTEGRATION)
        spanned = sorted({community_of[a] for a in group if a in community_of})
        cross = None
        if len(spanned) >= 2:
            cross = between.get((spanned[0], spanned[1]))
            if cross is not None and cross < weak_limit:
                reasons.append(CROSS_COMMUNITY)
        bridge_members = [a for a in group if a in bridges]
        if CROSS_COMMUNITY in reasons and len(group) >= 3 and bridge_members:
            reasons.append(BRIDGE)
        if not reasons:
            return None  # grupo ya bien relacionado: no hay oportunidad

        window = self._window(leisure, group)
        if window is None:
            return None

        gain = sum(1 - w for w in weights.values()) / len(pairs)
        gain += config.bonus_low_integration * (LOW_INTEGRATION in reasons)
        gain += config.bonus_cross_community * (CROSS_COMMUNITY in reasons)
        gain += config.bonus_bridge * (BRIDGE in reasons)
        return {
            "participants": list(group),
            "window": window,
            "gain": gain,
            "reasons": reasons,
            "pair_weights": [
                {"pair": list(pair), "weight": weights[pair]} for pair in pairs
            ],
            "weak_pairs": [list(pair) for pair in weak_pairs],
            "low_members": low_members,
            "bridge_members": bridge_members if BRIDGE in reasons else [],
            "between_communities": cross if CROSS_COMMUNITY in reasons else None,
            "crew_median_weight": crew_median,
        }

    # --- redacción ------------------------------------------------------------

    def _proposal(
        self, candidate: Document, score: float, target_day: int, based_on_day: int,
        position: int, rotation: int, recent: dict[str, int],
    ) -> Document:
        members = candidate["participants"]
        start, end = candidate["window"]
        options = [name for name, sizes in ACTIVITIES if len(members) in sizes]
        activity = options[rotation % len(options)]
        span = f"{_clock(start)}–{_clock(end)}"

        parts = []
        for item in candidate["pair_weights"]:
            if item["pair"] in candidate["weak_pairs"]:
                parts.append(
                    f"{_names(item['pair'])}: peso de interacción {item['weight']:.2f} en los "
                    f"últimos días (mediana de la tripulación: {candidate['crew_median_weight']:.2f})."
                )
        if candidate["low_members"]:
            parts.append(
                f"Indicadores de integración por debajo de lo habitual: {_names(candidate['low_members'])}."
            )
        if candidate["between_communities"] is not None:
            parts.append(
                "Pertenecen a grupos con poca interacción entre sí "
                f"(peso medio entre grupos: {candidate['between_communities']:.2f})."
            )
        if candidate["bridge_members"]:
            parts.append(f"{_names(candidate['bridge_members'])} ya se relaciona con ambos grupos.")
        parts.append(f"Coinciden en ocio; ventana propuesta: {span}.")
        parts.append(
            "Propuestas en los últimos 7 días: "
            + ", ".join(f"{a} {recent[a]}" for a in members) + "."
        )

        return {
            "id": f"{target_day}-{position + 1}",
            "day": target_day,
            "based_on_day": based_on_day,
            "participants": members,
            "start_s": start,
            "end_s": end,
            "window": span,
            "activity": activity,
            "score": round(score, 4),
            "reasons": candidate["reasons"],
            "justification": " ".join(parts),
            # Texto para la tripulación: sin métricas ni motivos, para no etiquetar a nadie
            "crew_text": f"Propuesta voluntaria: {activity}, {_names(members)}, {span}.",
            "metrics": {
                "pair_weights": candidate["pair_weights"],
                "crew_median_weight": candidate["crew_median_weight"],
                "between_communities": candidate["between_communities"],
                "recent_proposals": recent,
            },
            "status": "proposed",
            "voluntary": True,
        }
