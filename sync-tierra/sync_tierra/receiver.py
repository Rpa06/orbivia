"""Receptor simulado en Tierra para la demo (no es un sistema de NASA).

Acepta lotes de sync-tierra, comprueba la lista blanca, descarta duplicados por
huella y guarda los registros en un fichero JSON Lines de su propio volumen.
GET /records devuelve lo recibido; GET /health comprueba que está vivo.
"""

from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .whitelist import ForbiddenField, digest, validate

DATA = Path(os.environ.get("EARTH_DATA_DIR", "/data")) / "received.jsonl"


def _seen() -> set[str]:
    if not DATA.exists():
        return set()
    return {json.loads(line)["sha256"] for line in DATA.read_text(encoding="utf-8").splitlines() if line}


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):  # sin registro de contenido
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, {"status": "ok"})
        elif self.path == "/records":
            lines = DATA.read_text(encoding="utf-8").splitlines() if DATA.exists() else []
            self._reply(200, {"count": len(lines), "records": [json.loads(l) for l in lines[-200:]]})
        else:
            self._reply(404, {"detail": "no encontrado"})

    def do_POST(self) -> None:
        token = os.environ.get("EARTH_SYNC_TOKEN", "")
        supplied = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        if not token or not hmac.compare_digest(token, supplied):
            self._reply(401, {"detail": "token no válido"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if self.path != "/ingest" or length <= 0 or length > 5_000_000:
            self._reply(400, {"detail": "petición no válida"})
            return
        records = json.loads(self.rfile.read(length)).get("records", [])
        seen, stored, duplicates = _seen(), 0, 0
        DATA.parent.mkdir(parents=True, exist_ok=True)
        with DATA.open("a", encoding="utf-8") as out:
            for record in records:
                try:
                    validate(record)
                except ForbiddenField as error:
                    self._reply(422, {"detail": str(error)})
                    return
                sha = digest(record)
                if sha in seen:
                    duplicates += 1
                    continue
                out.write(json.dumps({"sha256": sha, "record": record}) + "\n")
                seen.add(sha)
                stored += 1
        self._reply(200, {"stored": stored, "duplicates": duplicates})


def main() -> None:
    port = int(os.environ.get("EARTH_PORT", "8090"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
