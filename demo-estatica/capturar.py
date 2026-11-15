"""Graba las respuestas de la API local para la demo estática (sin backend).

Requisitos: el stack de docker levantado y la misión sembrada (`docker compose run --rm seed`).
Lee las contraseñas de volumenes/demo/credenciales.txt y no las escribe en ningún sitio.

    python3 demo-estatica/capturar.py [--base http://127.0.0.1:8080/api/v1]

Resultado: frontend/demo/data/<rol>.json con {"today": "AAAA-MM-DD", "session": {...},
"responses": {"GET /ruta": {"status": 200, "body": ...}}}. Solo lecturas: no modifica la base.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CREDS = ROOT / "volumenes" / "demo" / "credenciales.txt"
OUT = ROOT / "frontend" / "demo" / "data"
CREW = ("A1", "A2", "A3", "A4")
USERS = ("commander", "astro2", "astro3", "astro4", "surgeon", "earth.medical", "earth.mission")

# Lecturas que hace el frontend (frontend/**/*.js). Las de fecha se añaden en capture().
STATIC_PATHS = (
    "/meta/mission", "/auth/me", "/checkin/today", "/exercise", "/intentions", "/recommendations",
    "/cycle/insights", "/cycle/entries", "/cycle/share", "/cycle/shared", "/astronaut/dashboard", "/me/series",
    "/plans/today", "/crew/status", "/crew/radiation", "/crew/ids", "/mission/cohesion-graph",
)


def read_passwords() -> dict[str, str]:
    pw = {}
    for line in CREDS.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] in USERS:
            pw[parts[0]] = parts[-1]
    missing = set(USERS) - set(pw)
    if missing:
        raise SystemExit(f"Faltan credenciales en {CREDS}: {', '.join(sorted(missing))}")
    return pw


def call(base: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(base + path, method="POST" if body is not None else "GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


def capture(base: str, username: str, password: str) -> dict:
    status, sess = call(base, "/auth/login", body={"username": username, "password": password})
    if status != 200:
        raise SystemExit(f"No se pudo entrar como {username}: {status}")
    token = sess.pop("token", None)
    responses: dict[str, dict] = {}

    def get(path: str):
        st, body = call(base, path, token)
        responses[f"GET {path}"] = {"status": st, "body": body}
        return st, body

    for p in STATIC_PATHS:
        get(p)
    _, mission = get("/meta/mission")
    today = dt.date.fromisoformat(mission["today"]) if isinstance(mission, dict) and mission.get("today") else dt.date.today()
    for offset in range(0, 8):
        d = (today - dt.timedelta(days=offset)).isoformat()
        get(f"/plans/{d}")
        get(f"/plans/{d}/decisions")
    for a in CREW:
        get(f"/crew/{a}/series")
        get(f"/earth/history?astronaut_id={a}&days=30")
    # La sesión no lleva token: la demo no habla con ningún servidor.
    return {"today": today.isoformat(), "session": sess, "responses": responses}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8080/api/v1")
    args = ap.parse_args()
    pw = read_passwords()
    OUT.mkdir(parents=True, exist_ok=True)
    for user in USERS:
        data = capture(args.base, user, pw[user])
        role = data["session"].get("role", user)
        name = user if role == "astronaut" else role
        (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        ok = sum(1 for r in data["responses"].values() if r["status"] == 200)
        print(f"{name}: {ok}/{len(data['responses'])} respuestas 200 · hoy {data['today']}")


if __name__ == "__main__":
    main()
