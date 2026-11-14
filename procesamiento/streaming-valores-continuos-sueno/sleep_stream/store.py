"""Almacenamiento duradero de los resúmenes de sesión.

Redis solo guarda el estado temporal. El resumen final vive en PostgreSQL, en
el esquema propio `sleep`. Guardar es idempotente: si la sesión ya tiene
resumen se conserva el primero y se devuelve ese.
"""

import json
import os
from collections.abc import Mapping
from typing import Any, Protocol

Document = dict[str, Any]


def _brief(summary: Document) -> Document:
    meta = summary["session_metadata"]
    return {
        "astronaut_id": summary["astronaut_id"],
        "sleep_session_id": summary["sleep_session_id"],
        "status": "completed",
        "start_timestamp": meta["start_timestamp"],
        "end_timestamp": meta["end_timestamp"],
        "total_observations": meta["total_observations"],
        "anomalies_count": meta["anomalies_count"],
        "sleep_summary_vector": summary["sleep_summary_vector"],
    }


class SummaryStore(Protocol):
    def save_summary(self, summary: Document) -> Document:
        """Guarda el resumen si la sesión no tenía uno. Devuelve el que queda guardado."""
        ...

    def get_summary(self, astronaut_id: str, session_id: str) -> Document | None: ...

    def list_sessions(self, astronaut_id: str) -> list[Document]:
        """Sesiones completadas de un astronauta, de la más antigua a la más reciente."""
        ...


class MemoryStore:
    """Almacén en memoria, para tests y simulaciones. Serializa a JSON como la base de datos."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], str] = {}

    def save_summary(self, summary: Document) -> Document:
        key = (summary["astronaut_id"], summary["sleep_session_id"])
        self._rows.setdefault(key, json.dumps(summary, allow_nan=False))
        return json.loads(self._rows[key])

    def get_summary(self, astronaut_id: str, session_id: str) -> Document | None:
        row = self._rows.get((astronaut_id, session_id))
        return json.loads(row) if row is not None else None

    def list_sessions(self, astronaut_id: str) -> list[Document]:
        rows = [json.loads(row) for (astronaut, _), row in self._rows.items() if astronaut == astronaut_id]
        return [_brief(row) for row in sorted(rows, key=lambda r: r["session_metadata"]["start_timestamp"])]


_SCHEMA_SQL = """
-- El esquema lo crea base-de-datos/init; solo se crea aquí si falta (sin pedir
-- privilegios de CREATE sobre la base de datos al rol del servicio).
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'biometrics') THEN
        CREATE SCHEMA biometrics;
    END IF;
END $$;
CREATE TABLE IF NOT EXISTS biometrics.sleep_session_summary (
    astronaut_id text NOT NULL,
    sleep_session_id text NOT NULL,
    start_ts double precision NOT NULL,
    end_ts double precision NOT NULL,
    config_version text NOT NULL,
    summary jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (astronaut_id, sleep_session_id)
);
CREATE INDEX IF NOT EXISTS sleep_session_summary_by_start
    ON biometrics.sleep_session_summary (astronaut_id, start_ts);
"""

_INSERT = """
INSERT INTO biometrics.sleep_session_summary
    (astronaut_id, sleep_session_id, start_ts, end_ts, config_version, summary)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (astronaut_id, sleep_session_id) DO NOTHING
"""

_SELECT = """
SELECT summary FROM biometrics.sleep_session_summary WHERE astronaut_id = %s AND sleep_session_id = %s
"""


class PostgresStore:
    """Almacén en el PostgreSQL de Orbivia. Crea sus tablas al arrancar: los scripts
    de base-de-datos/init solo se ejecutan sobre un directorio de datos vacío."""

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

    def save_summary(self, summary: Document) -> Document:
        from psycopg.types.json import Jsonb

        meta = summary["session_metadata"]
        key = (summary["astronaut_id"], summary["sleep_session_id"])
        document = Jsonb(summary, dumps=lambda obj: json.dumps(obj, allow_nan=False))
        # Una sola transacción: el bloque `with` confirma al salir o deshace si falla
        with self._connect() as connection:
            connection.execute(_INSERT, (*key, meta["start_timestamp"], meta["end_timestamp"],
                                         meta["config_version"], document))
            return connection.execute(_SELECT, key).fetchone()[0]

    def get_summary(self, astronaut_id: str, session_id: str) -> Document | None:
        with self._connect() as connection:
            row = connection.execute(_SELECT, (astronaut_id, session_id)).fetchone()
        return row[0] if row else None

    def list_sessions(self, astronaut_id: str) -> list[Document]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT summary FROM biometrics.sleep_session_summary WHERE astronaut_id = %s ORDER BY start_ts",
                (astronaut_id,),
            ).fetchall()
        return [_brief(row[0]) for row in rows]
