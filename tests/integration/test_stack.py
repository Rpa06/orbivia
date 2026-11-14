"""Tests de integración contra el despliegue en marcha (docker compose up + seed).

    docker compose up -d --build && docker compose run --rm seed
    python -m pytest tests/integration

Necesita: la API en ORBIVIA_API_URL (por defecto http://127.0.0.1:8000), PostgreSQL en
127.0.0.1:${POSTGRES_PORT}, el fichero .env local y volumenes/demo/credenciales.txt.
Se omiten si el despliegue no está disponible.
"""

from __future__ import annotations

import io
import math
import os
import subprocess
import time
import wave
from pathlib import Path

import httpx
import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
API = os.environ.get("ORBIVIA_API_URL", "http://127.0.0.1:8000")


def _env() -> dict[str, str]:
    out = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


ENV = _env()


def _credentials() -> dict[str, str]:
    path = ROOT / "volumenes" / "demo" / "credenciales.txt"
    if not path.exists():
        return {}
    creds = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and not line.startswith("#"):
            creds[parts[0]] = parts[2]
    return creds


CREDS = _credentials()

try:
    httpx.get(f"{API}/health/ready", timeout=3).raise_for_status()
    AVAILABLE = bool(CREDS)
except Exception:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="Despliegue o credenciales de demo no disponibles")

_tokens: dict[str, str] = {}


def token(user: str) -> str:
    if user not in _tokens:
        r = httpx.post(f"{API}/api/v1/auth/login", json={"username": user, "password": CREDS[user]}, timeout=10)
        r.raise_for_status()
        _tokens[user] = r.json()["token"]
    return _tokens[user]


def get(user: str, path: str, **kw) -> httpx.Response:
    return httpx.get(f"{API}/api/v1{path}", headers={"Authorization": f"Bearer {token(user)}"}, timeout=60, **kw)


def post(user: str, path: str, **kw) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token(user)}", **kw.pop("headers", {})}
    return httpx.post(f"{API}/api/v1{path}", headers=headers, timeout=300, **kw)


def db(role: str) -> psycopg.Connection:
    users = {"admin": (ENV.get("POSTGRES_USER", "orbivia"), ENV.get("POSTGRES_PASSWORD")),
             "api": ("orbivia_api", ENV.get("ORBIVIA_DB_API_PASSWORD")),
             "engine": ("orbivia_engine", ENV.get("ORBIVIA_DB_ENGINE_PASSWORD")),
             "cycle": ("orbivia_cycle", ENV.get("ORBIVIA_DB_CYCLE_PASSWORD")),
             "sync": ("orbivia_sync", ENV.get("ORBIVIA_DB_SYNC_PASSWORD"))}
    user, password = users[role]
    return psycopg.connect(host="127.0.0.1", port=int(ENV.get("POSTGRES_PORT", "5432")),
                           dbname=ENV.get("POSTGRES_DB", "orbivia"), user=user, password=password, autocommit=True)


def compose(*args: str) -> str:
    env = dict(os.environ)
    env["PATH"] = f"{Path.home()}/.docker/bin:/Applications/Docker.app/Contents/Resources/bin:" + env.get("PATH", "")
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=120).stdout


# --- infraestructura ---------------------------------------------------------------------


def test_health_ready_and_proxy():
    assert httpx.get(f"{API}/health/ready", timeout=5).json() == {"status": "ready"}
    front = httpx.get("http://127.0.0.1:" + ENV.get("FRONTEND_PORT", "8080") + "/api/health/ready", timeout=5)
    assert front.status_code == 200  # Nginx -> http://api:8000


def test_all_services_healthy():
    out = compose("ps", "--format", "{{.Service}} {{.Health}}")
    services = dict(line.split(" ", 1) for line in out.strip().splitlines() if " " in line)
    for name in ("db", "broker", "media-broker", "api", "worker-stream", "worker-ml", "sync-tierra",
                 "earth-receiver", "frontend"):
        assert services.get(name) == "healthy", (name, services.get(name))


# --- datos -------------------------------------------------------------------------------------


def test_vectors_are_80_bytes_and_each_astronaut_has_own_baseline():
    with db("admin") as conn:
        assert conn.execute("SELECT count(*) FROM biometrics.daily_vector WHERE octet_length(vector) <> 80").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM biometrics.daily_vector").fetchone()[0] >= 4 * 14
        means = conn.execute("SELECT count(DISTINCT mean) FROM biometrics.baselines WHERE kind = 'terrestrial' "
                             "AND variable = 'grip_strength_kg'").fetchone()[0]
        assert means == 4


def test_terrestrial_baseline_is_frozen():
    with db("engine") as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE biometrics.baselines SET mean = 0 WHERE kind = 'terrestrial'")
    with db("admin") as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("UPDATE biometrics.baselines SET mean = 0 WHERE kind = 'terrestrial'")


def test_no_column_can_hold_media_or_transcripts():
    with db("admin") as conn:
        cols = [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema IN "
            "('biometrics','operations','vault_identity','private_cycle')").fetchall()]
    assert not [c for c in cols if any(w in c for w in ("transcript", "audio_blob", "video_blob", "wav"))]


# --- privacidad y RBAC ----------------------------------------------------------------------


def test_commander_never_receives_psychological_data():
    r = get("commander", "/crew/status")
    assert r.status_code == 200
    for a in r.json()["crew"]:
        assert set(a) == {"astronaut_id", "availability", "reason"}
    assert get("commander", "/earth/history", params={"astronaut_id": "A1"}).status_code == 403
    assert get("commander", "/recommendations").status_code == 403


def test_earth_mission_gets_only_aggregates():
    r = get("earth.mission", "/crew/status").json()
    assert "crew" not in r and "alerts_by_area" in r
    assert "A1" not in str(r)
    assert get("earth.mission", "/earth/history", params={"astronaut_id": "A1"}).status_code == 403
    assert get("earth.mission", "/cycle/shared").status_code == 403


def test_earth_medical_history_without_media_or_cycle():
    r = get("earth.medical", "/earth/history", params={"astronaut_id": "A2"})
    assert r.status_code == 200
    text = r.text.lower()
    assert "transcript" not in text and "phase" not in text
    assert get("earth.medical", "/cycle/shared").status_code == 403
    assert get("earth.medical", "/crew/status").status_code == 403


def test_astronaut_only_sees_own_data():
    assert get("astro1", "/crew/status").status_code == 403
    assert get("astro1", "/earth/history", params={"astronaut_id": "A2"}).status_code == 403
    d = get("astro1", "/astronaut/dashboard").json()
    assert d["astronaut_id"] == "A1"
    assert all(k not in (d["latest_vector"] or {}) for k in ("nlp_low_mood_z", "acoustic_pause_z"))


def test_cycle_private_and_shared_only_with_permission():
    assert get("astro4", "/cycle/entries").status_code == 200
    assert len(get("astro4", "/cycle/entries").json()) > 0
    assert get("astro1", "/cycle/entries").json() == []        # A1 solo ve lo suyo
    assert get("surgeon", "/cycle/entries").status_code == 403
    post("astro4", "/cycle/share", json={"hours": 1})
    assert "A4" in get("surgeon", "/cycle/shared").json()["shared"]
    httpx.delete(f"{API}/api/v1/cycle/share", headers={"Authorization": f"Bearer {token('astro4')}"}, timeout=10)
    assert "A4" not in get("surgeon", "/cycle/shared").json()["shared"]


def test_engine_and_sync_roles_cannot_read_private_cycle():
    for role in ("engine", "sync", "api"):
        with db(role) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT * FROM private_cycle.entries LIMIT 1")
    with db("cycle") as conn:
        conn.execute("SELECT count(*) FROM private_cycle.entries")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM biometrics.daily_vector LIMIT 1")


def test_cycle_payload_is_encrypted_at_rest():
    with db("admin") as conn:
        raw = conn.execute("SELECT payload FROM private_cycle.entries LIMIT 1").fetchone()[0]
    assert b"phase" not in bytes(raw) and b"menstrual" not in bytes(raw)


def test_unauthenticated_and_wrong_role_are_rejected():
    assert httpx.get(f"{API}/api/v1/crew/status", timeout=5).status_code == 401
    assert post("astro1", "/ops/trigger-daily-collapse", json={}).status_code == 403


# --- flujos ------------------------------------------------------------------------------------


def test_checkin_then_pvt_without_showing_results_first():
    user = "astro2"
    today = get(user, "/checkin/today").json()
    if not today["checkin_done"]:
        assert post(user, "/pvt", json={"reaction_times_ms": [300], "duration_s": 180}).status_code == 409
        r = post(user, "/checkin", json={"answers": {"sleep": 3, "fatigue": 3, "workload": 4, "mood": 3, "cohesion": 4}})
        assert r.status_code == 201
        assert set(r.json()) == {"status", "next", "pvt_duration_s"}  # ningún resultado
    if not get(user, "/checkin/today").json()["pvt_done"]:
        r = post(user, "/pvt", json={"reaction_times_ms": [280, 320, 610, 300] * 20, "duration_s": 180})
        assert r.status_code == 201 and r.json()["lapses"] == 20


def test_trigger_collapse_and_three_plans():
    r = post("surgeon", "/ops/trigger-daily-collapse", json={"plans": True, "force": True})
    assert r.status_code == 200
    body = r.json()
    assert len(body["collapse"]["astronauts"]) == 4
    plans = get("astro1", "/plans/today").json()
    assert plans["status"] == "ok" and len(plans["options"]) == 3
    assert plans["social_graph_used"] is False
    for o in plans["options"]:
        assert o["advantages"] and o["disadvantages"]
        assert "justification" not in str(o)
    commander = post("commander", "/ops/trigger-daily-collapse", json={"plans": False}).json()
    assert isinstance(commander["collapse"]["astronauts"], int)  # sin detalle por astronauta


def test_plans_respect_constraints_and_research_is_not_reassigned():
    with db("admin") as conn:
        rows = conn.execute("SELECT option_id, payload FROM operations.plans WHERE plan_date = current_date").fetchall()
        science = {r[0] for r in conn.execute("SELECT task_id FROM operations.task_catalog WHERE category = 'science'")}
        limits = conn.execute("SELECT weekly_limits FROM operations.plan_runs WHERE plan_date = current_date").fetchone()[0]
    caps = {l["astronaut"]: l["max_today_h"] for l in limits}
    owners: dict[str, set] = {}
    for _, payload in rows:
        for a, w in payload["global"]["workload"].items():
            assert w["hours"] <= min(8.0, caps[a]) + 1e-6
        for e in payload["individual"]:
            if e["task"].split(":")[0] in science:
                owners.setdefault(e["task"], set()).add(e["astronaut"])
    assert all(len(v) == 1 for v in owners.values())


def test_decisions_are_recorded_and_private_reason_is_masked():
    with db("admin") as conn:
        conn.execute("DELETE FROM operations.plan_decisions WHERE plan_date = current_date")
    r = post("astro3", "/plans/today/decision", json={"decision": "rejected_all", "private_reason": True,
                                                      "reason": "texto que no debe guardarse"})
    assert r.status_code == 201
    r = post("commander", "/plans/today/decision", json={"decision": "selected", "option_id": "B"})
    assert r.status_code == 201
    with db("admin") as conn:
        rows = conn.execute("SELECT decision, option_id, reason_category, reason_text FROM operations.plan_decisions "
                            "WHERE plan_date = current_date ORDER BY id").fetchall()
    assert rows[0] == ("rejected_all", None, "personal", "motivo personal")
    assert rows[1][:2] == ("selected", "B")


# --- multimedia ---------------------------------------------------------------------------------


def _tone_wav(seconds: float = 3.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        frames = bytearray()
        for i in range(int(16000 * seconds)):
            amp = 0.0 if (i // 4000) % 3 == 2 else 0.3  # tramos con y sin voz
            v = int(32767 * amp * math.sin(2 * math.pi * (180 + 20 * math.sin(i / 3000)) * i / 16000))
            frames += v.to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def test_media_is_processed_in_memory_and_purged():
    since = compose("exec", "-T", "worker-ml", "date", "+%s").strip()
    r = post("astro1", "/ingest/media", content=_tone_wav(), headers={"Content-Type": "audio/wav", "X-Media-Kind": "audio"})
    assert r.status_code == 202
    job = r.json()["job_id"]
    for _ in range(60):
        status = get("astro1", f"/ingest/media/{job}").json()
        if status["status"] != "queued":
            break
        time.sleep(1)
    assert status["status"] == "completed", status
    assert set(status) == {"job_id", "status", "error_code", "kind"}  # el astronauta no ve puntuaciones
    with db("admin") as conn:
        acoustic, nlp = conn.execute("SELECT acoustic, nlp FROM biometrics.media_results WHERE job_id = %s",
                                     (job,)).fetchone()
    assert "f0_mean" in acoustic and nlp is None  # NLP desactivado por defecto
    assert compose("exec", "-T", "media-broker", "redis-cli", "XLEN", "orbivia:media").strip() == "0"
    # Ningún fichero nuevo en el contenedor desde que se envió el audio (ni en /tmp ni en otro sitio)
    leftovers = compose("exec", "-T", "worker-ml", "sh", "-c",
                        f"find / -xdev -type f -newermt @{since} -not -path '/proc/*' -not -path '/sys/*' 2>/dev/null | head")
    assert leftovers.strip() == "", leftovers


def test_invalid_media_leaves_nothing_behind():
    r = post("astro1", "/ingest/media", content=b"esto no es audio" * 50,
             headers={"Content-Type": "audio/wav", "X-Media-Kind": "audio"})
    job = r.json()["job_id"]
    for _ in range(30):
        status = get("astro1", f"/ingest/media/{job}").json()
        if status["status"] != "queued":
            break
        time.sleep(1)
    assert status["status"] == "failed"
    assert compose("exec", "-T", "media-broker", "redis-cli", "XLEN", "orbivia:media").strip() == "0"


# --- sincronización con Tierra ---------------------------------------------------------------


def test_sync_sends_only_whitelisted_data_without_duplicates():
    deadline = time.time() + 150
    while time.time() < deadline:
        with db("admin") as conn:
            sent = conn.execute("SELECT count(*) FROM biometrics.sync_log WHERE status = 'sent'").fetchone()[0]
            total = conn.execute("SELECT count(*) FROM biometrics.daily_vector").fetchone()[0]
        if sent >= total - 4:
            break
        time.sleep(10)
    assert sent > 0
    received = (ROOT / "volumenes" / "tierra" / "received.jsonl").read_text()
    lowered = received.lower()
    for word in ("transcript", "menstr", "phase", "payload", "\"audio\"", "\"video\""):
        assert word not in lowered
    import json
    shas = [json.loads(l)["sha256"] for l in received.splitlines()]
    assert len(shas) == len(set(shas))
