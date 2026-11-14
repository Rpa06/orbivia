"""Registro privado del ciclo menstrual (README §2.G).

- Solo la astronauta lo lee y lo escribe. Se puede borrar entero.
- Puede compartirlo con el médico de a bordo durante un tiempo limitado.
- Se guarda cifrado (pgp_sym_encrypt) en `private_cycle`, con un rol de base de
  datos propio (`orbivia_cycle`). El motor de disponibilidad y el planificador
  usan otro rol sin permisos sobre este esquema.
- No se agrega, no entra en la nota ni en el reparto y no se envía a Tierra.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException

from .auth import CREW_ROLES, Principal, own_astronaut, require
from .common import clean, parse_day
from .db import transaction

router = APIRouter(prefix="/api/v1/cycle", tags=["private_cycle"])

PHASES = ("menstrual", "follicular", "ovulatory", "luteal", "unknown")
SYMPTOMS = ("pain", "sleep", "mood", "fatigue", "headache", "other")
FLOW = ("none", "spotting", "light", "medium", "heavy")
MAX_SHARE_H = 72


def _key() -> str:
    key = os.environ.get("CYCLE_ENCRYPTION_KEY", "")
    if len(key) < 32:
        raise HTTPException(status_code=503, detail="CYCLE_ENCRYPTION_KEY no configurada (mínimo 32 caracteres)")
    return key


def _validate(body: dict) -> dict:
    phase = body.get("phase", "unknown")
    flow = body.get("flow", "none")
    symptoms = body.get("symptoms") or []
    if phase not in PHASES or flow not in FLOW or not all(s in SYMPTOMS for s in symptoms):
        raise HTTPException(status_code=422, detail="Fase, sangrado o síntomas no válidos")
    note = str(body.get("note", ""))[:300]
    return {"phase": phase, "flow": flow, "symptoms": sorted(set(symptoms)),
            "unexpected_bleeding": bool(body.get("unexpected_bleeding", False)), "note": note}


def _entries(conn, astronaut: str) -> list[dict]:
    rows = conn.execute("SELECT id, entry_date, pgp_sym_decrypt(payload, %s) FROM private_cycle.entries "
                        "WHERE astronaut_id = %s ORDER BY entry_date", (_key(), astronaut)).fetchall()
    return [{"id": i, "date": d.isoformat(), **json.loads(text)} for i, d, text in rows]


@router.get("/entries")
def list_entries(p: Principal = Depends(require(*CREW_ROLES))) -> list[dict]:
    with transaction("cycle") as conn:
        return _entries(conn, own_astronaut(p))


@router.post("/entries", status_code=201)
def add_entry(body: dict = Body(...), p: Principal = Depends(require(*CREW_ROLES))) -> dict:
    astronaut = own_astronaut(p)
    day = parse_day(body.get("date"))
    payload = _validate(body)
    with transaction("cycle") as conn:
        row = conn.execute("INSERT INTO private_cycle.entries (astronaut_id, entry_date, payload) "
                           "VALUES (%s, %s, pgp_sym_encrypt(%s, %s)) RETURNING id",
                           (astronaut, day, json.dumps(payload), _key())).fetchone()
    return {"id": row[0]}


@router.delete("/entries")
def delete_all(p: Principal = Depends(require(*CREW_ROLES))) -> dict:
    astronaut = own_astronaut(p)
    with transaction("cycle") as conn:
        n = conn.execute("DELETE FROM private_cycle.entries WHERE astronaut_id = %s", (astronaut,)).rowcount
        conn.execute("DELETE FROM private_cycle.shares WHERE astronaut_id = %s", (astronaut,))
    return {"deleted": n}


@router.get("/insights")
def insights(p: Principal = Depends(require(*CREW_ROLES))) -> dict:
    """Aviso individualizado a partir de su propio registro: síntomas frecuentes por fase."""
    with transaction("cycle") as conn:
        entries = _entries(conn, own_astronaut(p))
    by_phase: dict[str, Counter] = defaultdict(Counter)
    counts = Counter()
    for e in entries:
        counts[e["phase"]] += 1
        by_phase[e["phase"]].update(e["symptoms"])
    patterns = {phase: [s for s, c in symptoms.most_common() if c >= max(2, counts[phase] // 2)]
                for phase, symptoms in by_phase.items()}
    latest = entries[-1] if entries else None
    notice = None
    if latest and patterns.get(latest["phase"]):
        notice = (f"En la fase {latest['phase']} sueles registrar: {', '.join(patterns[latest['phase']])}. "
                  "Tenlo en cuenta al elegir entre los planes propuestos. Este aviso solo lo ves tú.")
    return {"entries": len(entries), "patterns": patterns, "notice": notice,
            "unexpected_bleeding_days": sum(1 for e in entries if e["unexpected_bleeding"])}


@router.post("/share", status_code=201)
def share(body: dict = Body(...), p: Principal = Depends(require(*CREW_ROLES))) -> dict:
    hours = int(body.get("hours", 24))
    if not 1 <= hours <= MAX_SHARE_H:
        raise HTTPException(status_code=422, detail=f"Entre 1 y {MAX_SHARE_H} horas")
    expires = datetime.now(timezone.utc) + timedelta(hours=hours)
    with transaction("cycle") as conn:
        conn.execute("INSERT INTO private_cycle.shares (astronaut_id, expires_at) VALUES (%s, %s) "
                     "ON CONFLICT (astronaut_id) DO UPDATE SET expires_at = EXCLUDED.expires_at, granted_at = now()",
                     (own_astronaut(p), expires))
    return {"shared_with": "flight_surgeon", "expires_at": expires.isoformat()}


@router.delete("/share")
def revoke(p: Principal = Depends(require(*CREW_ROLES))) -> dict:
    with transaction("cycle") as conn:
        conn.execute("DELETE FROM private_cycle.shares WHERE astronaut_id = %s", (own_astronaut(p),))
    return {"status": "revoked"}


@router.get("/share")
def share_status(p: Principal = Depends(require(*CREW_ROLES))) -> dict:
    with transaction("cycle") as conn:
        row = conn.execute("SELECT expires_at FROM private_cycle.shares WHERE astronaut_id = %s AND expires_at > now()",
                           (own_astronaut(p),)).fetchone()
    return clean({"active": row is not None, "expires_at": row[0].isoformat() if row else None})


@router.get("/shared")
def shared_with_me(p: Principal = Depends(require("flight_surgeon"))) -> dict:
    """Solo los registros que alguna astronauta comparte ahora mismo con el médico."""
    with transaction("cycle") as conn:
        active = [r[0] for r in conn.execute(
            "SELECT astronaut_id FROM private_cycle.shares WHERE expires_at > now() ORDER BY astronaut_id")]
        return {"shared": {a: _entries(conn, a) for a in active}}
