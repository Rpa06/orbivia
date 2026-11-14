import os

import psycopg
import redis
from fastapi import Depends, FastAPI, HTTPException

from sleep_stream.api import router as sleep_router

from . import auth, cycle, ingest, plans, views

app = FastAPI(title="Orbivia API", version="0.2.0",
              description="Apoyo operativo a la decisión. No diagnostica ni trata enfermedades.")

app.include_router(auth.router)
app.include_router(ingest.router)
app.include_router(views.router)
app.include_router(plans.router)
app.include_router(cycle.router)
# Módulo de sueño: lo alimentan los sensores y lo consulta el médico de a bordo
app.include_router(sleep_router, prefix="/api/v1",
                   dependencies=[Depends(auth.require("sensor", "flight_surgeon"))])
# El router HTTP de procesamiento/texto (POST /audio/transcriptions) no se monta: devolvía la
# transcripción al cliente. El audio entra por /api/v1/ingest/media y se procesa en worker-ml.


@app.get("/health/live")
@app.get("/api/health/live", include_in_schema=False)
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
@app.get("/api/health/ready", include_in_schema=False)
def readiness() -> dict[str, str]:
    try:
        with psycopg.connect(
            host=os.environ["POSTGRES_HOST"],
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ.get("ORBIVIA_DB_API_USER", "orbivia_api"),
            password=os.environ["ORBIVIA_DB_API_PASSWORD"],
            connect_timeout=3,
        ) as connection:
            connection.execute("SELECT 1")

        redis.Redis(
            host=os.environ["REDIS_HOST"],
            port=int(os.environ.get("REDIS_PORT", "6379")),
            socket_connect_timeout=3,
            socket_timeout=3,
        ).ping()
        redis.Redis(
            host=os.environ.get("MEDIA_REDIS_HOST", "media-broker"),
            port=int(os.environ.get("MEDIA_REDIS_PORT", "6379")),
            socket_connect_timeout=3,
            socket_timeout=3,
        ).ping()
    except (KeyError, ValueError, psycopg.Error, redis.RedisError) as error:
        raise HTTPException(status_code=503, detail="Dependencia no disponible") from error

    return {"status": "ready"}
