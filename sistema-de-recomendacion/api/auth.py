"""Autenticación y control de acceso por rol (RBAC) en el backend.

- Contraseñas con scrypt (biblioteca estándar), nunca en claro.
- Token firmado con HMAC-SHA256 y caducidad; secreto en AUTH_SECRET.
- `require(*roles)` es la única puerta: la interfaz puede ocultar cosas, pero
  quien decide qué datos salen es esta comprobación.

Roles de aplicación: astronaut, flight_surgeon, commander, earth_medical, earth_mission.
Además, los sensores autenticados con INGEST_SENSOR_TOKEN actúan con rol `sensor`
solo en los endpoints de ingesta.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from .db import transaction

ROLES = ("astronaut", "flight_surgeon", "commander", "earth_medical", "earth_mission")
TOKEN_TTL_S = 8 * 3600

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    expected = hash_password(password, base64.b64decode(salt_b64)).split("$")[2]
    return hmac.compare_digest(expected, digest_b64)


def _secret() -> bytes:
    secret = os.environ.get("AUTH_SECRET", "")
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="AUTH_SECRET no configurado (mínimo 32 caracteres)")
    return secret.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(user_id: int, role: str, astronaut_id: str | None, username: str) -> str:
    payload = {"uid": user_id, "role": role, "ast": astronaut_id, "usr": username,
               "exp": int(time.time()) + TOKEN_TTL_S}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


@dataclass(frozen=True)
class Principal:
    user_id: int | None
    role: str
    astronaut_id: str | None
    username: str


def decode_token(token: str) -> Principal:
    try:
        body, sig = token.split(".")
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Token no válido") from error
    expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Token no válido")
    payload = json.loads(_unb64(body))
    if payload.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="Sesión caducada")
    if payload.get("role") not in ROLES:
        raise HTTPException(status_code=401, detail="Rol no válido")
    return Principal(payload["uid"], payload["role"], payload.get("ast"), payload.get("usr", ""))


def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Falta el token de acceso")
    sensor = os.environ.get("INGEST_SENSOR_TOKEN", "")
    if sensor and len(sensor) >= 32 and hmac.compare_digest(token, sensor):
        return Principal(None, "sensor", None, "sensor")
    return decode_token(token)


def require(*roles: str):
    allowed = set(roles)

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status_code=403, detail="Tu rol no tiene acceso a estos datos")
        return principal

    return dependency


def own_astronaut(principal: Principal) -> str:
    if principal.role != "astronaut" or not principal.astronaut_id:
        raise HTTPException(status_code=403, detail="Solo el propio astronauta")
    return principal.astronaut_id


@router.post("/login")
def login(body: dict = Body(...)) -> dict:
    username = str(body.get("username", "")).strip().lower()
    password = str(body.get("password", ""))
    with transaction("api") as conn:
        row = conn.execute(
            "SELECT id, password_hash, role, astronaut_id FROM vault_identity.users "
            "WHERE username = %s AND active", (username,)).fetchone()
    if row is None or not verify_password(password, row[1]):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    return {"token": issue_token(row[0], row[2], row[3], username), "role": row[2],
            "astronaut_id": row[3], "username": username, "expires_in": TOKEN_TTL_S}


@router.get("/me")
def me(principal: Principal = Depends(current_principal)) -> dict:
    return {"role": principal.role, "astronaut_id": principal.astronaut_id, "username": principal.username}
