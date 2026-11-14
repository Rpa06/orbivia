"""Conexiones a PostgreSQL por rol de base de datos (privilegio mínimo).

- api:    autenticación, ingesta y lecturas filtradas por rol de aplicación.
- engine: colapso diario, alertas, disponibilidad y planificador. Sin acceso a
          private_cycle ni a vault_identity.
- cycle:  solo private_cycle.

Cada credencial llega por variables de entorno. Si falta, la operación devuelve 503.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg
import redis
from fastapi import HTTPException

ROLES = {
    "api": ("ORBIVIA_DB_API_USER", "orbivia_api", "ORBIVIA_DB_API_PASSWORD"),
    "engine": ("ORBIVIA_DB_ENGINE_USER", "orbivia_engine", "ORBIVIA_DB_ENGINE_PASSWORD"),
    "cycle": ("ORBIVIA_DB_CYCLE_USER", "orbivia_cycle", "ORBIVIA_DB_CYCLE_PASSWORD"),
}


def connect(role: str, autocommit: bool = False) -> psycopg.Connection:
    user_var, default_user, password_var = ROLES[role]
    password = os.environ.get(password_var)
    if not password:
        raise HTTPException(status_code=503, detail=f"Credencial de base de datos no configurada ({role})")
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "db"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "orbivia"),
        user=os.environ.get(user_var, default_user),
        password=password,
        connect_timeout=3,
        autocommit=autocommit,
    )


@contextmanager
def transaction(role: str):
    try:
        conn = connect(role)
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="Base de datos no disponible") from error
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def redis_client(db_env: str = "REDIS") -> redis.Redis:
    return redis.Redis(
        host=os.environ.get(f"{db_env}_HOST", "broker"),
        port=int(os.environ.get(f"{db_env}_PORT", "6379")),
        socket_connect_timeout=3,
        socket_timeout=5,
    )


def media_redis() -> redis.Redis:
    """Redis efímero para multimedia: sin AOF ni RDB, en RAM (servicio media-broker)."""
    return redis_client("MEDIA_REDIS")
