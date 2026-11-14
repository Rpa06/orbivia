"""Servicio sync-tierra: envía a Tierra los vectores diarios cuando hay enlace.

- Ventana de comunicación: SYNC_WINDOW = "always", "never" o "M1-M2" (minutos de
  cada hora en que hay enlace, p. ej. "0-20").
- Funciona sin conexión: lo pendiente queda en `biometrics.sync_log` y se reanuda
  cuando vuelve el enlace. Reintentos con espera creciente.
- Sin duplicados: cada registro lleva su huella SHA-256; un registro ya enviado
  con la misma huella no se reenvía, y el receptor ignora duplicados.
- Solo envía lo que permite `whitelist.py`.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import psycopg

from .whitelist import build_record, digest

logger = logging.getLogger("sync-tierra")
BATCH = 50


def in_window(now: datetime, spec: str) -> bool:
    spec = (spec or "always").strip().lower()
    if spec == "always":
        return True
    if spec == "never":
        return False
    start, end = (int(x) for x in spec.split("-"))
    return start <= now.minute < end


def connect() -> psycopg.Connection:
    return psycopg.connect(host=os.environ.get("POSTGRES_HOST", "db"),
                           port=int(os.environ.get("POSTGRES_PORT", "5432")),
                           dbname=os.environ.get("POSTGRES_DB", "orbivia"),
                           user=os.environ.get("ORBIVIA_DB_SYNC_USER", "orbivia_sync"),
                           password=os.environ["ORBIVIA_DB_SYNC_PASSWORD"], connect_timeout=5)


def pending_records(conn) -> list[tuple[dict, str]]:
    rows = conn.execute(
        "SELECT v.astronaut_id, v.cycle_date, v.schema_version, v.vector, v.missing_mask, v.simulated_mask "
        "FROM biometrics.daily_vector v LEFT JOIN biometrics.sync_log s ON s.astronaut_id = v.astronaut_id "
        "AND s.cycle_date = v.cycle_date AND s.schema_version = v.schema_version "
        "WHERE s.status IS DISTINCT FROM 'sent' OR s.payload_sha256 IS NULL "
        "OR s.last_attempt < v.created_at ORDER BY v.cycle_date, v.astronaut_id LIMIT %s", (BATCH,)).fetchall()
    out = []
    for astronaut, day, version, vector, missing, simulated in rows:
        interviews = [
            {"question_id": q, "acoustic": ac, "nlp": nlp}
            for q, ac, nlp in conn.execute(
                "SELECT question_id, acoustic, nlp FROM biometrics.media_results WHERE astronaut_id = %s "
                "AND cycle_date = %s AND kind = 'audio' AND status = 'completed'", (astronaut, day)).fetchall()
        ]
        record = build_record(astronaut, day.isoformat(), version, bytes(vector), missing, simulated, interviews)
        sha = digest(record)
        already = conn.execute(
            "SELECT 1 FROM biometrics.sync_log WHERE astronaut_id = %s AND cycle_date = %s AND schema_version = %s "
            "AND status = 'sent' AND payload_sha256 = %s", (astronaut, day, version, sha)).fetchone()
        if not already:
            out.append((record, sha))
    return out


def send(endpoint: str, token: str, records: list[dict]) -> dict:
    body = json.dumps({"records": records}).encode()
    request = urllib.request.Request(endpoint, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read() or b"{}")


def mark(conn, items: list[tuple[dict, str]], status: str, error: str | None = None) -> None:
    for record, sha in items:
        conn.execute(
            "INSERT INTO biometrics.sync_log (astronaut_id, cycle_date, schema_version, payload_sha256, status, attempts, "
            "last_attempt, acked_at, last_error) VALUES (%s, %s, %s, %s, %s, 1, now(), %s, %s) "
            "ON CONFLICT (astronaut_id, cycle_date, schema_version) DO UPDATE SET payload_sha256 = EXCLUDED.payload_sha256, "
            "status = EXCLUDED.status, attempts = biometrics.sync_log.attempts + 1, last_attempt = now(), "
            "acked_at = EXCLUDED.acked_at, last_error = EXCLUDED.last_error",
            (record["astronaut_id"], record["cycle_date"], record["schema_version"], sha, status,
             datetime.now(timezone.utc) if status == "sent" else None, error))


def run_once(endpoint: str, token: str, window: str) -> dict:
    if not in_window(datetime.now(timezone.utc), window):
        return {"status": "no_link"}
    with connect() as conn:
        items = pending_records(conn)
        if not items:
            return {"status": "up_to_date"}
        try:
            ack = send(endpoint, token, [r for r, _ in items])
        except (urllib.error.URLError, OSError, ValueError) as error:
            mark(conn, items, "failed", type(error).__name__)
            return {"status": "failed", "pending": len(items), "error": type(error).__name__}
        mark(conn, items, "sent")
        return {"status": "sent", "count": len(items), "ack": ack}


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    endpoint = os.environ.get("EARTH_ENDPOINT_URL", "http://earth-receiver:8090/ingest")
    token = os.environ.get("EARTH_SYNC_TOKEN", "")
    window = os.environ.get("SYNC_WINDOW", "always")
    interval = float(os.environ.get("SYNC_INTERVAL_S", "60"))
    heartbeat = os.environ.get("SYNC_HEARTBEAT_FILE", "/tmp/sync_tierra.heartbeat")
    delay = interval
    while True:
        try:
            result = run_once(endpoint, token, window)
            if result["status"] in ("sent", "failed"):
                logger.info("Sincronización: %s", {k: v for k, v in result.items() if k != "ack"})
            delay = interval if result["status"] != "failed" else min(delay * 2, 900)
            with open(heartbeat, "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except psycopg.Error:
            logger.exception("Base de datos no disponible")
            delay = min(delay * 2, 300)
        except Exception:
            logger.exception("Error en la sincronización")
            delay = min(delay * 2, 300)
        time.sleep(delay)


if __name__ == "__main__":
    main()
