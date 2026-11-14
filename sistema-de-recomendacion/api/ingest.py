"""Ingesta: check-in, PVT-B, ejercicio, intenciones, pregunta doble, mediciones y multimedia.

El audio y el vídeo nunca se escriben en disco ni en PostgreSQL: la API los pasa
a un Redis Stream efímero (MAXLEN 10, instancia sin persistencia) y el worker-ml
los procesa en memoria. En PostgreSQL solo queda el estado del trabajo y los
números resultantes.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import redis
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request

from conductual import (
    CHECKIN_QUESTIONS, compare_double_question, interview_question, needs_implementation_intention,
    score_pvt, validate_checkin,
)

from .auth import Principal, current_principal, own_astronaut, require
from .common import MEASUREMENT_REGISTRY, PENDING_VALIDATION, mission, mission_day, parse_day, today
from .db import media_redis, transaction

router = APIRouter(prefix="/api/v1", tags=["ingest"])

MEDIA_STREAM = "orbivia:media"
MEDIA_MAXLEN = 10
MAX_MEDIA_BYTES = 12 * 1024 * 1024
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp4"}
VIDEO_TYPES = {"video/webm", "video/mp4"}


# --- check-in y PVT-B ---------------------------------------------------------------------


@router.post("/checkin", status_code=201)
def submit_checkin(body: dict = Body(...), p: Principal = Depends(require("astronaut"))) -> dict:
    astronaut = own_astronaut(p)
    day = today()
    try:
        answers = validate_checkin(astronaut, day, body.get("answers") or {}, body.get("predicted_team_mean"))
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    known = bool(body.get("known_reason", False))
    with transaction("api") as conn:
        if conn.execute("SELECT 1 FROM biometrics.checkins WHERE astronaut_id = %s AND cycle_date = %s",
                        (astronaut, day)).fetchone():
            raise HTTPException(status_code=409, detail="Ya has hecho el check-in de hoy")
        conn.execute(
            "INSERT INTO biometrics.checkins (astronaut_id, cycle_date, sleep, fatigue, workload, mood, cohesion, "
            "known_reason) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (astronaut, day, answers["sleep"], answers["fatigue"], answers["workload"], answers["mood"],
             answers["cohesion"], known))
        weekly = body.get("predicted_team_mean")
        if weekly is not None:
            iso = day.isocalendar()
            conn.execute(
                "INSERT INTO biometrics.weekly_double (astronaut_id, iso_year, iso_week, cohesion, predicted_team_mean) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (astronaut, iso[0], iso[1], answers["cohesion"], int(weekly)))
    # No se devuelve ningún resultado: el PVT-B empieza a continuación
    return {"status": "recorded", "next": "pvt", "pvt_duration_s": 180}


@router.post("/pvt", status_code=201)
def submit_pvt(body: dict = Body(...), p: Principal = Depends(require("astronaut"))) -> dict:
    astronaut = own_astronaut(p)
    day = today()
    try:
        score = score_pvt(body.get("reaction_times_ms") or [], float(body.get("duration_s", 0)),
                          int(body.get("false_starts", 0)))
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    with transaction("api") as conn:
        if not conn.execute("SELECT 1 FROM biometrics.checkins WHERE astronaut_id = %s AND cycle_date = %s",
                            (astronaut, day)).fetchone():
            raise HTTPException(status_code=409, detail="El PVT-B va después del check-in")
        conn.execute(
            "INSERT INTO biometrics.pvt_results (astronaut_id, cycle_date, mean_rt_ms, lapses, false_starts, trials, "
            "duration_s) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (astronaut_id, cycle_date) DO NOTHING",
            (astronaut, day, score.mean_rt_ms, score.lapses, score.false_starts, score.trials, score.duration_s))
    return {"status": "recorded", "mean_rt_ms": score.mean_rt_ms, "lapses": score.lapses,
            "trials": score.trials, "note": "Resultado tras completar el check-in. No es una valoración médica."}


@router.get("/checkin/today")
def checkin_today(p: Principal = Depends(require("astronaut"))) -> dict:
    astronaut = own_astronaut(p)
    day = today()
    with transaction("api") as conn:
        m = mission(conn)
        mday = mission_day(conn, day)
        done = conn.execute("SELECT 1 FROM biometrics.checkins WHERE astronaut_id = %s AND cycle_date = %s",
                            (astronaut, day)).fetchone() is not None
        pvt = conn.execute("SELECT 1 FROM biometrics.pvt_results WHERE astronaut_id = %s AND cycle_date = %s",
                           (astronaut, day)).fetchone() is not None
        iso = day.isocalendar()
        weekly_done = conn.execute(
            "SELECT 1 FROM biometrics.weekly_double WHERE astronaut_id = %s AND iso_year = %s AND iso_week = %s",
            (astronaut, iso[0], iso[1])).fetchone() is not None
    q_id, q_text = interview_question(mday, m["audio_interval_days"])
    return {
        "date": day.isoformat(), "mission_day": mday, "checkin_done": done, "pvt_done": pvt,
        "questions": [{"id": q, "text": t, "scale": s} for q, t, s in CHECKIN_QUESTIONS],
        "weekly_question_due": not weekly_done,
        "weekly_question": "¿Qué nota crees que pondrá de media el resto del equipo?",
        "interview": {"due": (mday - 1) % m["audio_interval_days"] == 0, "question_id": q_id, "question": q_text,
                      "interval_days": m["audio_interval_days"]},
    }


@router.get("/weekly-double/result")
def weekly_double_result(p: Principal = Depends(require("astronaut"))) -> dict:
    """Solo la comparación propia: nunca las respuestas de otros astronautas."""
    astronaut = own_astronaut(p)
    iso = today().isocalendar()
    with transaction("api") as conn:
        rows = conn.execute("SELECT astronaut_id, cohesion, predicted_team_mean FROM biometrics.weekly_double "
                            "WHERE iso_year = %s AND iso_week = %s", (iso[0], iso[1])).fetchall()
    results = {r.astronaut_id: r for r in compare_double_question([tuple(r) for r in rows], today())}
    mine = results.get(astronaut)
    if mine is None:
        return {"available": False, "reason": "faltan respuestas de la semana"}
    return {"available": True, "your_prediction": mine.predicted_mean,
            "team_mean_excluding_you": mine.actual_peer_mean, "difference": mine.difference,
            "peers": mine.peers_count}


# --- ejercicio e intenciones -----------------------------------------------------------------


@router.post("/exercise", status_code=201)
def log_exercise(body: dict = Body(...), p: Principal = Depends(require("astronaut"))) -> dict:
    astronaut = own_astronaut(p)
    day = today()
    done = bool(body.get("done"))
    minutes = body.get("minutes")
    with transaction("api") as conn:
        conn.execute(
            "INSERT INTO biometrics.exercise_log (astronaut_id, cycle_date, done, minutes) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (astronaut_id, cycle_date) DO UPDATE SET done = EXCLUDED.done, minutes = EXCLUDED.minutes",
            (astronaut, day, done, int(minutes) if minutes is not None else None))
        history = conn.execute("SELECT cycle_date, done FROM biometrics.exercise_log WHERE astronaut_id = %s "
                               "AND cycle_date >= %s", (astronaut, day - timedelta(days=7))).fetchall()
    return {"status": "recorded", "offer_implementation_intention": needs_implementation_intention(history)}


@router.get("/exercise")
def exercise_history(p: Principal = Depends(require("astronaut"))) -> dict:
    astronaut = own_astronaut(p)
    with transaction("api") as conn:
        rows = conn.execute("SELECT cycle_date, done, minutes FROM biometrics.exercise_log WHERE astronaut_id = %s "
                            "ORDER BY cycle_date DESC LIMIT 14", (astronaut,)).fetchall()
    history = [(d, done) for d, done, _ in rows]
    return {"history": [{"date": d.isoformat(), "done": done, "minutes": m} for d, done, m in rows],
            "offer_implementation_intention": needs_implementation_intention(history)}


@router.get("/intentions")
def list_intentions(p: Principal = Depends(require("astronaut"))) -> list[dict]:
    astronaut = own_astronaut(p)
    with transaction("api") as conn:
        rows = conn.execute("SELECT id, if_text, then_text, created_at FROM biometrics.implementation_intentions "
                            "WHERE astronaut_id = %s ORDER BY id DESC", (astronaut,)).fetchall()
    return [{"id": i, "if": a, "then": b, "created_at": c.isoformat()} for i, a, b, c in rows]


@router.post("/intentions", status_code=201)
def add_intention(body: dict = Body(...), p: Principal = Depends(require("astronaut"))) -> dict:
    astronaut = own_astronaut(p)
    if_text, then_text = str(body.get("if", "")).strip(), str(body.get("then", "")).strip()
    if not if_text or not then_text or len(if_text) > 300 or len(then_text) > 300:
        raise HTTPException(status_code=422, detail="Completa 'si pasa X' y 'haré Y' (máximo 300 caracteres)")
    with transaction("api") as conn:
        row = conn.execute("INSERT INTO biometrics.implementation_intentions (astronaut_id, if_text, then_text) "
                           "VALUES (%s, %s, %s) RETURNING id", (astronaut, if_text, then_text)).fetchone()
    return {"id": row[0]}


@router.delete("/intentions/{intention_id}")
def delete_intention(intention_id: int, p: Principal = Depends(require("astronaut"))) -> dict:
    astronaut = own_astronaut(p)
    with transaction("api") as conn:
        conn.execute("DELETE FROM biometrics.implementation_intentions WHERE id = %s AND astronaut_id = %s",
                     (intention_id, astronaut))
    return {"status": "deleted"}


# --- mediciones de los demás canales --------------------------------------------------------


@router.get("/ingest/registry")
def registry(p: Principal = Depends(current_principal)) -> dict:
    return {k: {"unit": u, "frequency": f, "validated_on_board": ok} for k, (u, f, ok) in MEASUREMENT_REGISTRY.items()}


@router.post("/ingest/measurements", status_code=202)
def ingest_measurements(items: list[dict] = Body(...), p: Principal = Depends(require("sensor", "flight_surgeon"))) -> dict:
    accepted, rejected = 0, []
    with transaction("api") as conn:
        for item in items[:500]:
            variable = item.get("variable")
            if variable not in MEASUREMENT_REGISTRY:
                rejected.append({"variable": variable, "reason": "variable desconocida"})
                continue
            unit, frequency, ok = MEASUREMENT_REGISTRY[variable]
            source = item.get("source", "sensor")
            if source not in ("sensor", "manual", "simulated"):
                rejected.append({"variable": variable, "reason": "origen no válido"})
                continue
            try:
                value = float(item["value"])
                day = parse_day(item.get("cycle_date"))
            except (KeyError, TypeError, ValueError, HTTPException):
                rejected.append({"variable": variable, "reason": "valor o fecha no válidos"})
                continue
            conn.execute(
                "INSERT INTO biometrics.measurements (astronaut_id, cycle_date, variable, value, unit, frequency, "
                "source, validated) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (astronaut_id, cycle_date, "
                "variable) DO UPDATE SET value = EXCLUDED.value, source = EXCLUDED.source, recorded_at = now()",
                (str(item.get("astronaut_id")), day, variable, value, unit, frequency, source,
                 ok and source == "sensor"))
            accepted += 1
    return {"accepted": accepted, "rejected": rejected,
            "pending_validation_variables": sorted(PENDING_VALIDATION)}


@router.post("/ingest/worked-hours", status_code=202)
def ingest_hours(body: dict = Body(...), p: Principal = Depends(require("sensor", "commander", "flight_surgeon"))) -> dict:
    day = parse_day(body.get("date"))
    with transaction("api") as conn:
        conn.execute(
            "INSERT INTO operations.worked_hours (astronaut_id, work_date, planned_h, actual_h, source) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (astronaut_id, work_date) DO UPDATE SET "
            "planned_h = coalesce(EXCLUDED.planned_h, operations.worked_hours.planned_h), "
            "actual_h = coalesce(EXCLUDED.actual_h, operations.worked_hours.actual_h)",
            (str(body["astronaut_id"]), day, body.get("planned_h"), body.get("actual_h"), body.get("source", "manual")))
    return {"status": "recorded"}


# --- multimedia ---------------------------------------------------------------------------------


@router.post("/ingest/media", status_code=202)
async def ingest_media(request: Request, p: Principal = Depends(require("astronaut")),
                       x_media_kind: str = Header("audio"), x_question_id: int | None = Header(None)) -> dict:
    astronaut = own_astronaut(p)
    media_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    allowed = AUDIO_TYPES if x_media_kind == "audio" else VIDEO_TYPES if x_media_kind == "video" else set()
    if media_type not in allowed:
        raise HTTPException(status_code=415, detail="Tipo de contenido no admitido")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_MEDIA_BYTES:
            raise HTTPException(status_code=413, detail="El archivo supera 12 MiB")
    if not body:
        raise HTTPException(status_code=400, detail="Cuerpo vacío")
    job_id = str(uuid.uuid4())
    day = today()
    with transaction("api") as conn:
        if x_question_id is None and x_media_kind == "audio":
            m = mission(conn)
            x_question_id = interview_question(mission_day(conn, day), m["audio_interval_days"])[0]
        conn.execute(
            "INSERT INTO biometrics.media_results (job_id, astronaut_id, cycle_date, kind, question_id, status) "
            "VALUES (%s, %s, %s, %s, %s, 'queued')", (job_id, astronaut, day, x_media_kind, x_question_id))
    try:
        media_redis().xadd(MEDIA_STREAM, {
            "job_id": job_id, "astronaut_id": astronaut, "cycle_date": day.isoformat(), "kind": x_media_kind,
            "question_id": str(x_question_id or 0), "media_type": media_type, "payload": bytes(body),
        }, maxlen=MEDIA_MAXLEN, approximate=False)
    except redis.RedisError as error:
        with transaction("api") as conn:
            conn.execute("UPDATE biometrics.media_results SET status = 'failed', error_code = 'queue_unavailable' "
                         "WHERE job_id = %s", (job_id,))
        raise HTTPException(status_code=503, detail="Cola multimedia no disponible") from error
    finally:
        body.clear()  # el búfer de la API se vacía en cuanto el trabajo está en la cola
    return {"job_id": job_id, "status": "queued"}


@router.get("/ingest/media/{job_id}")
def media_status(job_id: uuid.UUID, p: Principal = Depends(require("astronaut"))) -> dict:
    astronaut = own_astronaut(p)
    with transaction("api") as conn:
        row = conn.execute("SELECT status, error_code, kind FROM biometrics.media_results WHERE job_id = %s "
                           "AND astronaut_id = %s", (str(job_id), astronaut)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    # El astronauta ve el estado, no las puntuaciones (son para el equipo médico)
    return {"job_id": str(job_id), "status": row[0], "error_code": row[1], "kind": row[2]}
