"""Tres planes del día, elección o rechazo, y ejecución manual del colapso."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Body, Depends, HTTPException

from motor import planning, pipeline

from .auth import Principal, require
from .common import clean, parse_day
from .db import redis_client, transaction

logger = logging.getLogger("orbivia.api.plans")
router = APIRouter(prefix="/api/v1", tags=["plans"])

REASON_CATEGORIES = ("none", "operational", "safety", "workload", "personal")


@router.get("/plans/{date}")
def get_plans(date: str, p: Principal = Depends(require("astronaut", "commander", "flight_surgeon"))) -> dict:
    day = parse_day(date)
    with transaction("api") as conn:
        run = conn.execute("SELECT status, notes, weekly_limits FROM operations.plan_runs WHERE plan_date = %s",
                           (day,)).fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail="Aún no hay planes para ese día")
        plans = conn.execute("SELECT option_id, payload FROM operations.plans WHERE plan_date = %s ORDER BY option_id",
                             (day,)).fetchall()
        decision = conn.execute("SELECT decision, option_id, reason_category, reason_text, decided_by_role, decided_at "
                                "FROM operations.plan_decisions WHERE plan_date = %s ORDER BY id DESC LIMIT 1",
                                (day,)).fetchone()
    views = [planning.crew_view(payload) for _, payload in plans]
    if p.role == "astronaut":
        # Cada astronauta ve el reparto (necesario para elegir) y sus propias horas
        for v in views:
            v["workload"] = {a: w for a, w in v["workload"].items() if a == p.astronaut_id}
    out = {"date": day, "status": run[0], "notes": run[1], "options": views,
           "weekly_limits": run[2] if p.role != "astronaut" else
           [l for l in run[2] if l["astronaut"] == p.astronaut_id],
           "social_graph_used": False,
           "decision": None}
    if decision:
        out["decision"] = {"decision": decision[0], "option_id": decision[1], "reason_category": decision[2],
                           "reason": decision[3], "by_role": decision[4], "at": decision[5]}
    return clean(out)


@router.post("/plans/{date}/decision", status_code=201)
def decide(date: str, body: dict = Body(...), p: Principal = Depends(require("commander"))) -> dict:
    """Solo el comandante elige un plan o rechaza los tres, tras consultar a la tripulación.
    Con motivo privado solo consta 'motivo personal'."""
    day = parse_day(date)
    decision = body.get("decision")
    if decision not in ("selected", "rejected_all"):
        raise HTTPException(status_code=422, detail="decision debe ser 'selected' o 'rejected_all'")
    option = body.get("option_id") if decision == "selected" else None
    category = body.get("reason_category", "none")
    if body.get("private_reason"):
        category, reason = "personal", "motivo personal"
    else:
        reason = (str(body.get("reason", "")).strip() or None)
        if category == "personal":
            reason = "motivo personal"
    if category not in REASON_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"reason_category debe ser una de {REASON_CATEGORIES}")
    if decision == "rejected_all" and not reason and category == "none":
        raise HTTPException(status_code=422, detail="Indica el motivo del rechazo (o márcalo como personal)")
    if reason and len(reason) > 300:
        raise HTTPException(status_code=422, detail="Motivo demasiado largo")
    with transaction("api") as conn:
        plans = {o: payload for o, payload in conn.execute(
            "SELECT option_id, payload FROM operations.plans WHERE plan_date = %s", (day,)).fetchall()}
        if not plans:
            raise HTTPException(status_code=404, detail="No hay planes para ese día")
        if option is not None and option not in plans:
            raise HTTPException(status_code=422, detail="Opción desconocida")
        conn.execute(
            "INSERT INTO operations.plan_decisions (plan_date, decision, option_id, reason_category, reason_text, "
            "decided_by_role, decided_by_user) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (day, decision, option, category, reason, p.role, p.user_id))
        if option is not None:
            for a, w in plans[option]["global"]["workload"].items():
                conn.execute(
                    "INSERT INTO operations.worked_hours (astronaut_id, work_date, planned_h, source) VALUES "
                    "(%s, %s, %s, 'plan') ON CONFLICT (astronaut_id, work_date) DO UPDATE SET planned_h = EXCLUDED.planned_h",
                    (a, day, w["hours"]))
    return {"status": "recorded", "decision": decision, "option_id": option, "reason_category": category}


@router.get("/plans/{date}/decisions")
def decisions(date: str, p: Principal = Depends(require("commander", "flight_surgeon", "earth_mission"))) -> dict:
    day = parse_day(date)
    with transaction("api") as conn:
        rows = conn.execute("SELECT decision, option_id, reason_category, reason_text, decided_by_role, decided_at "
                            "FROM operations.plan_decisions WHERE plan_date = %s ORDER BY id", (day,)).fetchall()
    return clean({"date": day, "decisions": [
        {"decision": d, "option_id": o, "reason_category": c,
         "reason": t if p.role != "earth_mission" else None, "by_role": r, "at": at}
        for d, o, c, t, r, at in rows]})


@router.post("/ops/trigger-daily-collapse")
def trigger_daily_collapse(body: dict | None = Body(None),
                           p: Principal = Depends(require("flight_surgeon", "commander"))) -> dict:
    """Colapso diario y planes bajo demanda. Usa el rol de BD del motor (sin acceso al ciclo)."""
    body = body or {}
    day = parse_day(body.get("date"))
    try:
        cache = redis_client()
        cache.ping()
    except Exception:
        cache = None
    with transaction("engine") as conn:
        summary = pipeline.run_daily_collapse(conn, day, cache)
    result = {"collapse": summary}
    if body.get("plans", True):
        with transaction("engine") as conn:
            result["plans"] = pipeline.generate_plans(conn, day, force=bool(body.get("force", False)))
    if p.role == "commander":
        # El comandante no ve detalle por astronauta del colapso
        result["collapse"] = {"cycle_date": summary["cycle_date"], "mission_day": summary["mission_day"],
                              "astronauts": len(summary["astronauts"])}
    return clean(result)
