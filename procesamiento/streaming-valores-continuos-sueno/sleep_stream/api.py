"""Endpoints de sueño para la API de Orbivia (se incluyen como router).

    POST /sleep/sessions                                  iniciar una sesión
    POST /sleep/records                                   enviar uno o varios registros
    GET  /sleep/sessions/{astronauta}/{sesión}            estado del procesamiento
    POST /sleep/sessions/{astronauta}/{sesión}/end        finalizar
    GET  /sleep/sessions/{astronauta}/{sesión}/summary    vector y resumen
    GET  /sleep/sessions/{astronauta}/{sesión}/measurements   mediciones para el planificador
    GET  /sleep/astronauts/{astronauta}/sessions          historial

La API solo valida y encola: el trabajo lo hace el servicio `worker-stream`.
"""

import os
from typing import Any

import redis
from fastapi import APIRouter, Body, Depends, HTTPException

from .config import load_settings
from .integration import planner_measurements
from .processor import SessionConflict, SleepProcessor
from .records import Rejected
from .store import PostgresStore

router = APIRouter(prefix="/sleep", tags=["sleep"])

_processor: SleepProcessor | None = None


def get_processor() -> SleepProcessor:
    global _processor
    if _processor is None:
        client = redis.Redis(
            host=os.environ["REDIS_HOST"],
            port=int(os.environ.get("REDIS_PORT", "6379")),
            socket_connect_timeout=3,
            socket_timeout=5,
        )
        _processor = SleepProcessor(client, PostgresStore.from_env(), load_settings(os.environ))
    return _processor


def _guard(call, *args, **kwargs):
    """Traduce los errores del módulo a respuestas HTTP."""
    try:
        return call(*args, **kwargs)
    except Rejected as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": error.detail}) from error
    except SessionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except redis.RedisError as error:
        raise HTTPException(status_code=503, detail="Redis no disponible") from error


def _status_or_404(processor: SleepProcessor, astronaut_id: str, session_id: str) -> dict[str, Any]:
    status = _guard(processor.status, astronaut_id, session_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Sesión desconocida")
    return status


def _summary(processor: SleepProcessor, astronaut_id: str, session_id: str) -> dict[str, Any]:
    summary = _guard(processor.get_summary, astronaut_id, session_id)
    if summary is None:
        status = _status_or_404(processor, astronaut_id, session_id)
        raise HTTPException(status_code=409, detail={"message": "El resumen aún no está disponible",
                                                     "status": status["status"]})
    return summary


@router.post("/sessions", status_code=201)
def start_session(body: dict[str, Any] = Body(...),
                  processor: SleepProcessor = Depends(get_processor)) -> dict[str, Any]:
    return _guard(processor.start_session, body)


@router.post("/records", status_code=202)
def submit_records(body: dict[str, Any] | list[dict[str, Any]] = Body(...),
                   processor: SleepProcessor = Depends(get_processor)) -> dict[str, Any]:
    records = body if isinstance(body, list) else [body]
    if any(item.get("type", "record") != "record" for item in records):
        raise HTTPException(status_code=422, detail="Este endpoint solo admite registros")
    return {"queued": len(_guard(processor.submit_many, records))}


@router.get("/sessions/{astronaut_id}/{session_id}")
def session_status(astronaut_id: str, session_id: str,
                   processor: SleepProcessor = Depends(get_processor)) -> dict[str, Any]:
    return _status_or_404(processor, astronaut_id, session_id)


@router.post("/sessions/{astronaut_id}/{session_id}/end", status_code=202)
def end_session(astronaut_id: str, session_id: str, body: dict[str, Any] | None = Body(default=None),
                processor: SleepProcessor = Depends(get_processor)) -> dict[str, Any]:
    _status_or_404(processor, astronaut_id, session_id)
    _guard(processor.end_session, astronaut_id, session_id, (body or {}).get("end_timestamp"))
    return _status_or_404(processor, astronaut_id, session_id)


@router.get("/sessions/{astronaut_id}/{session_id}/summary")
def session_summary(astronaut_id: str, session_id: str,
                    processor: SleepProcessor = Depends(get_processor)) -> dict[str, Any]:
    return _summary(processor, astronaut_id, session_id)


@router.get("/sessions/{astronaut_id}/{session_id}/measurements")
def session_measurements(astronaut_id: str, session_id: str,
                         processor: SleepProcessor = Depends(get_processor)) -> list[dict[str, Any]]:
    summary = _summary(processor, astronaut_id, session_id)
    return planner_measurements(summary, processor.cfg.mission_epoch_s)


@router.get("/astronauts/{astronaut_id}/sessions")
def astronaut_sessions(astronaut_id: str,
                       processor: SleepProcessor = Depends(get_processor)) -> list[dict[str, Any]]:
    return _guard(processor.list_sessions, astronaut_id)
