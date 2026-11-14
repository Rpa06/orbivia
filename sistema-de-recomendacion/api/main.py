import os

import psycopg
import redis
from fastapi import FastAPI, HTTPException

from sleep_stream.api import router as sleep_router

app = FastAPI(title="Orbivia API", version="0.1.0")
app.include_router(sleep_router)


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def readiness() -> dict[str, str]:
    try:
        with psycopg.connect(
            host=os.environ["POSTGRES_HOST"],
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            connect_timeout=3,
        ) as connection:
            connection.execute("SELECT 1")

        redis.Redis(
            host=os.environ["REDIS_HOST"],
            port=int(os.environ.get("REDIS_PORT", "6379")),
            socket_connect_timeout=3,
            socket_timeout=3,
        ).ping()
    except (KeyError, ValueError, psycopg.Error, redis.RedisError) as error:
        raise HTTPException(status_code=503, detail="Dependencia no disponible") from error

    return {"status": "ready"}
