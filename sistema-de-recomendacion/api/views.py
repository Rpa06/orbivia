"""Vistas por rol. Cada endpoint decide en el backend qué datos salen.

| Rol            | Qué recibe                                                                  |
|----------------|-----------------------------------------------------------------------------|
| astronaut      | solo lo suyo: disponibilidad, acciones, tareas, ejercicio                    |
| flight_surgeon | estado, avisos, check-in, acústica y NLP de toda la tripulación              |
| commander      | nota de disponibilidad y motivo general; nunca check-in, NLP, voz ni ciclo   |
| earth_medical  | historial de vectores y métricas acústicas y NLP; nunca audio, vídeo ni texto|
| earth_mission  | avisos agregados; grafo de cohesión solo ante incidencia activa              |
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from colapso.vector import FIELDS, NLP_FIELDS, ACOUSTIC_FIELDS, CHECKIN_FIELDS, schema_document, unpack

from .auth import Principal, current_principal, own_astronaut, require
from .common import clean, mission, mission_day, parse_day, today
from .db import transaction

router = APIRouter(prefix="/api/v1", tags=["views"])

REASON_LABELS = {"none": "sin incidencias", "fatigue": "fatiga", "isolation": "aislamiento",
                 "workload": "carga", "medical_followup": "seguimiento médico"}
AREA_LABELS = {"medical": "Médico", "fatigue_sleep": "Fatiga y sueño", "psychological": "Psicológico",
               "social_team": "Social y equipo"}
PSYCH_FIELDS = set(NLP_FIELDS) | set(ACOUSTIC_FIELDS) | set(CHECKIN_FIELDS)


def _named(blob: bytes, hide: set[int] = frozenset()) -> dict:
    values = unpack(bytes(blob))
    return clean({f.name: (None if f.index in hide else round(values[f.index], 3)) for f in FIELDS
                  if f.index not in hide})


@router.get("/meta/vector-schema")
def vector_schema(p: Principal = Depends(current_principal)) -> dict:
    return schema_document()


@router.get("/meta/mission")
def mission_info(p: Principal = Depends(current_principal)) -> dict:
    with transaction("api") as conn:
        m = mission(conn)
        day = today()
        return clean({**m, "today": day, "mission_day": mission_day(conn, day),
                      "data_notice": "Todos los datos de esta demo son simulados" if m["simulated"] else None})


@router.get("/astronaut/dashboard")
def astronaut_dashboard(p: Principal = Depends(require("astronaut"))) -> dict:
    astronaut = own_astronaut(p)
    day = parse_day(None)
    with transaction("api") as conn:
        avail = conn.execute("SELECT cycle_date, score, reason_category FROM biometrics.availability "
                             "WHERE astronaut_id = %s ORDER BY cycle_date DESC LIMIT 14", (astronaut,)).fetchall()
        actions = conn.execute("SELECT action_code, first_date, last_notified FROM biometrics.actions "
                               "WHERE astronaut_id = %s AND active ORDER BY last_notified DESC", (astronaut,)).fetchall()
        checkin = conn.execute("SELECT 1 FROM biometrics.checkins WHERE astronaut_id = %s AND cycle_date = %s",
                               (astronaut, day)).fetchone()
        vec = conn.execute("SELECT vector, simulated_mask FROM biometrics.daily_vector WHERE astronaut_id = %s "
                           "ORDER BY cycle_date DESC LIMIT 1", (astronaut,)).fetchone()
    from motor.actions import CATALOG
    return clean({
        "astronaut_id": astronaut,
        "availability": [{"date": d, "score": s, "reason": REASON_LABELS.get(r, r)} for d, s, r in avail],
        "recommendations": [{"code": c, **CATALOG.get(c, {}), "since": f, "last_notified": l} for c, f, l in actions],
        "checkin_done_today": checkin is not None,
        # Sus propios datos objetivos; las puntuaciones de texto y voz las interpreta el equipo médico
        "latest_vector": _named(vec[0], set(NLP_FIELDS) | set(ACOUSTIC_FIELDS)) if vec else None,
        "simulated": bool(vec and vec[1]),
    })


@router.get("/crew/status")
def crew_status(date: str | None = None,
                p: Principal = Depends(require("flight_surgeon", "commander", "earth_mission"))) -> dict:
    day = parse_day(date)
    with transaction("api") as conn:
        avail = conn.execute("SELECT astronaut_id, score, reason_category, areas FROM biometrics.availability "
                             "WHERE cycle_date = %s ORDER BY astronaut_id", (day,)).fetchall()
        alerts = conn.execute("SELECT astronaut_id, criterion, area, variables, detail, reference FROM biometrics.alerts "
                              "WHERE cycle_date = %s ORDER BY astronaut_id, criterion", (day,)).fetchall()
        if p.role == "earth_mission":
            return _aggregate(day, alerts, avail)
        if p.role == "commander":
            return clean({"date": day, "crew": [
                {"astronaut_id": a, "availability": s, "reason": REASON_LABELS.get(r, r)} for a, s, r, _ in avail]})
        # flight_surgeon: detalle completo
        vectors = {a: _named(v) for a, v in conn.execute(
            "SELECT astronaut_id, vector FROM biometrics.daily_vector WHERE cycle_date = %s", (day,)).fetchall()}
        checkins = {r[0]: dict(zip(("sleep", "fatigue", "workload", "mood", "cohesion", "known_reason"), r[1:]))
                    for r in conn.execute("SELECT astronaut_id, sleep, fatigue, workload, mood, cohesion, known_reason "
                                          "FROM biometrics.checkins WHERE cycle_date = %s", (day,)).fetchall()}
        media = {}
        for a, q, acoustic, nlp, d in conn.execute(
                "SELECT astronaut_id, question_id, acoustic, nlp, cycle_date FROM biometrics.media_results "
                "WHERE status = 'completed' AND kind = 'audio' AND cycle_date BETWEEN %s AND %s "
                "ORDER BY cycle_date", (day - timedelta(days=6), day)).fetchall():
            media[a] = {"date": d, "question_id": q, "acoustic": acoustic, "nlp": nlp}
        actions = {}
        for a, code, last in conn.execute("SELECT astronaut_id, action_code, last_notified FROM biometrics.actions "
                                          "WHERE active").fetchall():
            actions.setdefault(a, []).append({"code": code, "last_notified": last})
        audits = {a: au for a, au in conn.execute("SELECT astronaut_id, audit FROM biometrics.availability "
                                                  "WHERE cycle_date = %s", (day,)).fetchall()}
    crew = []
    for a, s, r, areas in avail:
        crew.append({
            "astronaut_id": a, "availability": s, "reason": REASON_LABELS.get(r, r),
            "areas": {AREA_LABELS[k]: v for k, v in (areas or {}).items()},
            "alerts": [{"criterion": c, "area": AREA_LABELS[ar], "variables": v, "detail": de, "reference": ref}
                       for aa, c, ar, v, de, ref in alerts if aa == a],
            "vector": vectors.get(a), "checkin": checkins.get(a), "latest_interview": media.get(a),
            "actions": actions.get(a, []),
            "availability_audit": (audits.get(a) or {}).get("contributions"),
        })
    return clean({"date": day, "crew": crew,
                  "nlp_notice": "Las puntuaciones de texto son la confianza del clasificador, no escalas clínicas."})


def _incident_active(alerts) -> bool:
    return any(area == "social_team" for _, _, area, *_ in alerts)


def _aggregate(day, alerts, avail) -> dict:
    """Vista agregada para misión: recuentos, sin identificar a nadie."""
    by_area = Counter(AREA_LABELS[area] for _, _, area, *_ in alerts)
    by_criterion = Counter(c for _, c, *_ in alerts)
    scores = [s for _, s, _, _ in avail]
    return clean({
        "date": day,
        "alerts_by_area": dict(by_area), "alerts_by_criterion": dict(by_criterion),
        "astronauts_with_alerts": len({a for a, *_ in alerts}),
        "crew_size": len(avail),
        "mean_availability": round(sum(scores) / len(scores), 1) if scores else None,
        "cohesion_incident_active": _incident_active(alerts),
    })


@router.get("/mission/cohesion-graph")
def cohesion_graph(date: str | None = None, p: Principal = Depends(require("earth_mission"))) -> dict:
    """Grafo de cohesión, solo si hay una incidencia social activa. Nodos sin identificar."""
    day = parse_day(date)
    with transaction("api") as conn:
        alerts = conn.execute("SELECT astronaut_id, criterion, area FROM biometrics.alerts WHERE cycle_date = %s",
                              (day,)).fetchall()
        if not _incident_active(alerts):
            raise HTTPException(status_code=403, detail="El grafo de cohesión solo se muestra ante una incidencia activa")
        mday = mission_day(conn, day)
        row = conn.execute("SELECT result FROM biometrics.social_graph_daily_result WHERE day <= %s "
                           "ORDER BY day DESC LIMIT 1", (mday - 1,)).fetchone()
        if row:
            crew = row[0].get("crew") or []
            weights = ((row[0].get("isolation") or {}).get("structure") or {}).get("smoothed_weights")
        else:
            crew, weights = [], None
        if not weights:
            # Sin servicio de grafo activo: proximidad simulada del seed
            rows = conn.execute("SELECT astronaut_id, value FROM biometrics.measurements WHERE cycle_date = %s "
                                "AND variable = 'social_centrality' ORDER BY astronaut_id", (day,)).fetchall()
            crew = [a for a, _ in rows]
            weights = [[None if i == j else round(min(rows[i][1], rows[j][1]), 3) for j in range(len(rows))]
                       for i in range(len(rows))]
    salt = day.isoformat()
    labels = {a: "N" + hashlib.sha256((salt + a).encode()).hexdigest()[:4] for a in crew}
    nodes = sorted(labels.values())
    edges = []
    for i, a in enumerate(crew):
        for j, b in enumerate(crew):
            if i < j and weights[i][j] is not None:
                edges.append({"a": labels[a], "b": labels[b], "weight": weights[i][j]})
    return {"date": day.isoformat(), "nodes": nodes, "edges": edges,
            "notice": "Nodos seudonimizados por día. Uso exclusivo de vigilancia; nunca para repartir tareas."}


@router.get("/earth/history")
def earth_history(astronaut_id: str = Query(...), days: int = Query(30, ge=1, le=365),
                  p: Principal = Depends(require("earth_medical", "flight_surgeon"))) -> dict:
    day = today()
    with transaction("api") as conn:
        vectors = conn.execute(
            "SELECT cycle_date, schema_version, vector, missing_mask, simulated_mask FROM biometrics.daily_vector "
            "WHERE astronaut_id = %s AND cycle_date > %s ORDER BY cycle_date", (astronaut_id, day - timedelta(days=days))
        ).fetchall()
        media = conn.execute(
            "SELECT cycle_date, question_id, acoustic, nlp FROM biometrics.media_results WHERE astronaut_id = %s "
            "AND status = 'completed' AND cycle_date > %s ORDER BY cycle_date",
            (astronaut_id, day - timedelta(days=days))).fetchall()
        alerts = conn.execute("SELECT cycle_date, criterion, area, variables FROM biometrics.alerts "
                              "WHERE astronaut_id = %s AND cycle_date > %s ORDER BY cycle_date",
                              (astronaut_id, day - timedelta(days=days))).fetchall()
    return clean({
        "astronaut_id": astronaut_id,
        "vectors": [{"date": d, "schema_version": sv, "values": _named(v), "missing_mask": mm, "simulated_mask": sm}
                    for d, sv, v, mm, sm in vectors],
        "interviews": [{"date": d, "question_id": q, "acoustic": ac, "nlp": nlp} for d, q, ac, nlp in media],
        "alerts": [{"date": d, "criterion": c, "area": AREA_LABELS[a], "variables": v} for d, c, a, v in alerts],
        "excluded": "Audio, vídeo, transcripciones y registro del ciclo nunca se almacenan ni se envían.",
    })


@router.get("/recommendations")
def recommendations(p: Principal = Depends(require("astronaut", "flight_surgeon"))) -> dict:
    from motor.actions import CATALOG
    with transaction("api") as conn:
        if p.role == "astronaut":
            rows = conn.execute("SELECT astronaut_id, action_code, first_date, last_notified FROM biometrics.actions "
                                "WHERE active AND astronaut_id = %s", (own_astronaut(p),)).fetchall()
        else:
            rows = conn.execute("SELECT astronaut_id, action_code, first_date, last_notified FROM biometrics.actions "
                                "WHERE active ORDER BY astronaut_id").fetchall()
    return clean({"actions": [{"astronaut_id": a, "code": c, **CATALOG.get(c, {}), "since": f, "last_notified": l}
                              for a, c, f, l in rows]})


@router.get("/crew/ids")
def crew_ids(p: Principal = Depends(require("flight_surgeon", "earth_medical", "commander"))) -> list[str]:
    with transaction("api") as conn:
        return [r[0] for r in conn.execute("SELECT pseudonym FROM vault_identity.astronauts ORDER BY pseudonym")]
