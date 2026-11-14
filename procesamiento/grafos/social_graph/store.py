"""Persistencia: checkpoint del acumulador e histórico de resultados diarios.

El resultado de un día y el checkpoint posterior se guardan juntos. Así, tras un
reinicio, un día nunca queda cerrado a medias ni se cierra dos veces.
"""

import json
import os
from collections.abc import Mapping
from typing import Any, Protocol

Document = dict[str, Any]


class Store(Protocol):
    def load_checkpoint(self) -> Document | None: ...

    def save_checkpoint(self, state: Document) -> None: ...

    def save_day(self, day: int, result: Document, state: Document) -> None:
        """Guarda el resultado del día y el checkpoint en una sola operación atómica."""
        ...

    def load_days(self, last: int | None = None) -> list[Document]:
        """Resultados diarios en orden cronológico; los `last` más recientes si se indica."""
        ...


class MemoryStore:
    """Almacén en memoria, para tests y pruebas locales.

    Serializa a JSON en cada operación, igual que haría la base de datos, para
    detectar pronto cualquier valor no serializable.
    """

    def __init__(self) -> None:
        self._checkpoint: str | None = None
        self._days: dict[int, str] = {}

    def load_checkpoint(self) -> Document | None:
        return json.loads(self._checkpoint) if self._checkpoint is not None else None

    def save_checkpoint(self, state: Document) -> None:
        self._checkpoint = json.dumps(state, allow_nan=False)

    def save_day(self, day: int, result: Document, state: Document) -> None:
        encoded = json.dumps(result, allow_nan=False)
        self.save_checkpoint(state)
        self._days[day] = encoded

    def load_days(self, last: int | None = None) -> list[Document]:
        days = sorted(self._days)
        if last is not None:
            days = days[-last:]
        return [json.loads(self._days[d]) for d in days]


_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS biometrics;
CREATE TABLE IF NOT EXISTS biometrics.social_graph_daily_result (
    day integer PRIMARY KEY,
    params_version text NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS biometrics.social_graph_checkpoint (
    id smallint PRIMARY KEY CHECK (id = 1),
    state jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""

_UPSERT_CHECKPOINT = """
INSERT INTO biometrics.social_graph_checkpoint (id, state) VALUES (1, %s)
ON CONFLICT (id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()
"""

_UPSERT_DAY = """
INSERT INTO biometrics.social_graph_daily_result (day, params_version, result) VALUES (%s, %s, %s)
ON CONFLICT (day) DO UPDATE
SET params_version = EXCLUDED.params_version, result = EXCLUDED.result, created_at = now()
"""


class PostgresStore:
    """Almacén en el PostgreSQL de Orbivia, en el esquema propio `social_graph`.

    Crea sus tablas al arrancar: los scripts de base-de-datos/init solo se
    ejecutan sobre un directorio de datos vacío.
    """

    def __init__(self, **connect_kwargs: Any) -> None:
        self._connect_kwargs = connect_kwargs
        with self._connect() as connection:
            connection.execute(_SCHEMA_SQL)

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "PostgresStore":
        return cls(
            host=env["POSTGRES_HOST"],
            port=int(env.get("POSTGRES_PORT", "5432")),
            dbname=env["POSTGRES_DB"],
            user=env["POSTGRES_USER"],
            password=env["POSTGRES_PASSWORD"],
            connect_timeout=3,
        )

    def _connect(self):
        import psycopg

        return psycopg.connect(**self._connect_kwargs)

    @staticmethod
    def _jsonb(document: Document):
        from psycopg.types.json import Jsonb

        return Jsonb(document, dumps=lambda obj: json.dumps(obj, allow_nan=False))

    def load_checkpoint(self) -> Document | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM biometrics.social_graph_checkpoint WHERE id = 1"
            ).fetchone()
        return row[0] if row else None

    def save_checkpoint(self, state: Document) -> None:
        with self._connect() as connection:
            connection.execute(_UPSERT_CHECKPOINT, (self._jsonb(state),))

    def save_day(self, day: int, result: Document, state: Document) -> None:
        # Una sola transacción: el bloque `with` confirma al salir o deshace si falla
        with self._connect() as connection:
            connection.execute(_UPSERT_DAY, (day, result["params_version"], self._jsonb(result)))
            connection.execute(_UPSERT_CHECKPOINT, (self._jsonb(state),))

    def load_days(self, last: int | None = None) -> list[Document]:
        query = "SELECT result FROM biometrics.social_graph_daily_result ORDER BY day DESC"
        params: tuple = ()
        if last is not None:
            query += " LIMIT %s"
            params = (last,)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [row[0] for row in reversed(rows)]
