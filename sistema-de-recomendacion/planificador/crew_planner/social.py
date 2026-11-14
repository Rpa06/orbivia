"""Adaptador de solo lectura de las salidas del grafo social.

Lee el documento diario que guarda el servicio social-graph en
`social_graph.daily_result.result` (o un volcado JSON de ese documento). No
modifica el grafo ni repite sus cálculos: toma la matriz suavizada de 7 días y
el estado de integración que ya produce el `IsolationAnalyzer`.

Solo se interpretan patrones de interacción observados. Una pareja sin datos
devuelve None, nunca 0.
"""

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Social
from .model import ValidationError

# Estados del IsolationAnalyzer (procesamiento/grafos/social_graph/isolation.py)
REVIEW = "review"
FOLLOW_UP = "follow_up"
KNOWN_STATUSES = {"normal", FOLLOW_UP, REVIEW, "warming_up", "no_data", "not_evaluable"}

_TOL = 1e-9


@dataclass(frozen=True)
class SocialSnapshot:
    """Lo que el planificador necesita del grafo de un día."""

    day: int
    crew: tuple[str, ...]
    weights: tuple[tuple[float | None, ...], ...]  # W̄ suavizado; None si nunca fue evaluable
    status: Mapping[str, str]
    signals: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    crew_drop: bool = False
    params_version: str | None = None

    def __post_init__(self) -> None:
        n = len(self.crew)
        if len(set(self.crew)) != n:
            raise ValidationError("Grafo social: tripulación con identificadores repetidos")
        if len(self.weights) != n or any(len(row) != n for row in self.weights):
            raise ValidationError("Grafo social: la matriz no es N×N")
        for i in range(n):
            if self.weights[i][i] not in (None, 0, 0.0):
                raise ValidationError(f"Grafo social: diagonal no nula en {self.crew[i]}")
            for j in range(i + 1, n):
                a, b = self.weights[i][j], self.weights[j][i]
                if (a is None) != (b is None) or (a is not None and abs(a - b) > _TOL):
                    raise ValidationError(
                        f"Grafo social: matriz no simétrica en {self.crew[i]}–{self.crew[j]}"
                    )
                if a is not None and not (math.isfinite(a) and -_TOL <= a <= 1 + _TOL):
                    raise ValidationError(
                        f"Grafo social: peso fuera de [0, 1] en {self.crew[i]}–{self.crew[j]}: {a}"
                    )
        unknown = {s for s in self.status.values() if s not in KNOWN_STATUSES}
        if unknown:
            raise ValidationError(f"Grafo social: estados desconocidos {sorted(unknown)}")

    def weight(self, a: str, b: str) -> float | None:
        """W̄ de la pareja. None si no es evaluable o alguien no está en el grafo."""
        if a == b or a not in self.crew or b not in self.crew:
            return None
        return self.weights[self.crew.index(a)][self.crew.index(b)]

    def known_weights(self) -> list[float]:
        n = len(self.crew)
        return [w for i in range(n) for j in range(i + 1, n) if (w := self.weights[i][j]) is not None]

    def age(self, plan_day: int) -> int:
        return plan_day - self.day

    def usable_for(self, plan_day: int, config: Social) -> bool:
        """Solo vale un grafo de un día anterior y reciente."""
        return 1 <= self.age(plan_day) <= config.max_age_days


def from_daily_result(doc: Mapping[str, Any]) -> SocialSnapshot:
    """Construye la instantánea a partir del documento diario del servicio social-graph."""
    try:
        isolation = doc["isolation"]
        structure = isolation["structure"]
        crew = tuple(doc["crew"])
        weights = tuple(
            tuple(None if (w is None or i == j) else float(w) for j, w in enumerate(row))
            for i, row in enumerate(structure["smoothed_weights"])
        )
        astronauts = isolation["astronauts"]
        status = {a: astronauts[a]["status"] for a in crew}
        signals = {a: tuple(astronauts[a].get("signals", ())) for a in crew}
        crew_drop = bool(isolation.get("crew", {}).get("drop", False))
        day = int(doc["day"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationError(
            "El documento no es un resultado diario del grafo social con valoración de "
            f"aislamiento (falta o es inválido {error})"
        ) from error
    return SocialSnapshot(
        day=day, crew=crew, weights=weights, status=status, signals=signals,
        crew_drop=crew_drop, params_version=doc.get("params_version"),
    )


def latest_before(docs: Iterable[Mapping[str, Any]], plan_day: int) -> SocialSnapshot | None:
    """El documento más reciente anterior al día planificado, si hay alguno."""
    candidates = [d for d in docs if isinstance(d.get("day"), int) and d["day"] < plan_day]
    if not candidates:
        return None
    return from_daily_result(max(candidates, key=lambda d: d["day"]))


def load_snapshot(path: str | Path) -> SocialSnapshot:
    """Lee un volcado JSON de `daily_result.result`.

    Los ficheros `day_NNNN.json` de volumenes/social-graph son la exportación del
    panel y no llevan la matriz suavizada: no sirven aquí.
    """
    return from_daily_result(json.loads(Path(path).read_text(encoding="utf-8")))


_LATEST_SQL = (
    "SELECT result FROM social_graph.daily_result WHERE day < %s ORDER BY day DESC LIMIT 1"
)


def load_from_postgres(
    plan_day: int, env: Mapping[str, str], connect: Any = None
) -> SocialSnapshot | None:
    """Último resultado del servicio social-graph anterior al día planificado.

    Solo lee. Devuelve None si el esquema no existe todavía o no hay días cerrados:
    sin grafo, el planificador desactiva los objetivos sociales y lo dice.
    """
    if connect is None:
        import psycopg

        connect = psycopg.connect
    try:
        with connect(
            host=env.get("POSTGRES_HOST", "localhost"),
            port=int(env.get("POSTGRES_PORT", "5432")),
            dbname=env.get("POSTGRES_DB", "orbivia"),
            user=env.get("POSTGRES_USER", "orbivia"),
            password=env.get("POSTGRES_PASSWORD", ""),
            connect_timeout=3,
        ) as connection:
            row = connection.execute(_LATEST_SQL, (plan_day,)).fetchone()
    except Exception as error:  # noqa: BLE001 - se informa del motivo, no se oculta
        if type(error).__name__ == "UndefinedTable":
            return None
        raise
    return from_daily_result(row[0]) if row else None


def integration_need(
    snapshot: SocialSnapshot | None, crew: Sequence[str], config: Social
) -> dict[str, float]:
    """Indicador A_i ∈ [0, 1] por astronauta, a partir del estado del analizador.

    El estado ya exige persistencia (varios días), así que una observación
    puntual no produce A_i > 0. Sin grafo, o con descenso de toda la
    tripulación, A_i = 0 para todos: no es algo individual.
    """
    need = dict.fromkeys(crew, 0.0)
    if snapshot is None or snapshot.crew_drop:
        return need
    for astronaut in crew:
        status = snapshot.status.get(astronaut)
        if status == REVIEW:
            need[astronaut] = config.need_review
        elif status == FOLLOW_UP:
            need[astronaut] = config.need_follow_up
    return need
