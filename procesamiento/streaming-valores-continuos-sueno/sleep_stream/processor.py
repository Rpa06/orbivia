"""Procesamiento incremental sobre Redis.

Claves (prefijo `orbivia:sleep` por defecto; los identificadores no admiten ':'):

    {p}:ingest                      Stream  registros y señales de inicio y fin
    {p}:dead                        Stream  mensajes rechazados, con su motivo
    {p}:summaries                   Stream  aviso de cada resumen disponible
    {p}:session:{astro}:{sesión}    Hash    estado y acumuladores de la sesión
    {p}:agg:{astro}:{sesión}:L{k}   Hash    agregados del nivel k (campo = inicio de ventana)
    {p}:seen:{astro}:{sesión}       Bitmap  registros ya aplicados (duplicados)
    {p}:anomalies:{astro}:{sesión}  List    episodios de anomalía cerrados
    {p}:summary:{astro}:{sesión}    String  resumen final en JSON
    {p}:index:{astro}               ZSet    sesiones aún sin completar
    {p}:finalizing                  Set     sesiones con fin recibido y sin resumen
    {p}:stats                       Hash    contadores de mensajes rechazados

Garantías. Cada lote de una sesión se confirma en una transacción (WATCH sobre
la clave de la sesión + MULTI/EXEC) que escribe a la vez el estado, las
ventanas, el mapa de duplicados y el XACK de los mensajes. Un mensaje queda
aplicado y confirmado, o ni lo uno ni lo otro: si el consumidor cae a medias,
el mensaje sigue pendiente y otro consumidor lo reclama. Los registros
originales se borran del stream solo cuando ya están confirmados.
"""

import json
import logging
import time
from collections.abc import Iterable, Mapping
from typing import Any

import redis

from .config import Settings, check_id
from .engine import ACTIVE, COMPLETED, FINALIZING, SEALED, Engine, Session, Window
from .records import END, START, Message, Rejected, parse_message
from .stats import Agg
from .store import SummaryStore
from .summary import build_summary

logger = logging.getLogger(__name__)

Entry = tuple[str, Mapping[Any, Any]]
MAX_DELIVERIES = 5
PENDING_SCAN = 200


class SessionConflict(Exception):
    """Ya existe una sesión con ese identificador y otro inicio."""


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _next_id(stream_id: str) -> str:
    ms, seq = stream_id.split("-")
    return f"{ms}-{int(seq) + 1}"


class Keys:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.ingest = f"{prefix}:ingest"
        self.dead = f"{prefix}:dead"
        self.summaries = f"{prefix}:summaries"
        self.finalizing = f"{prefix}:finalizing"
        self.stats = f"{prefix}:stats"

    def session(self, astronaut: str, session: str) -> str:
        return f"{self.prefix}:session:{astronaut}:{session}"

    def agg(self, astronaut: str, session: str, level: int) -> str:
        return f"{self.prefix}:agg:{astronaut}:{session}:L{level}"

    def seen(self, astronaut: str, session: str) -> str:
        return f"{self.prefix}:seen:{astronaut}:{session}"

    def anomalies(self, astronaut: str, session: str) -> str:
        return f"{self.prefix}:anomalies:{astronaut}:{session}"

    def summary(self, astronaut: str, session: str) -> str:
        return f"{self.prefix}:summary:{astronaut}:{session}"

    def index(self, astronaut: str) -> str:
        return f"{self.prefix}:index:{astronaut}"


class RedisWindows:
    """Ventanas de una sesión dentro de una transacción: lee al vuelo y escribe al confirmar."""

    def __init__(self, pipe: Any, keys: list[str]) -> None:
        self._pipe = pipe
        self._keys = keys
        self._cache: dict[tuple[int, int], Window | None] = {}
        self._dirty: set[tuple[int, int]] = set()
        self._deleted: set[tuple[int, int]] = set()

    def get(self, level: int, start: int) -> Window | None:
        key = (level, start)
        if key not in self._cache:
            raw = self._pipe.hget(self._keys[level], start)
            self._cache[key] = None if raw is None else {
                name: Agg.load(item) for name, item in json.loads(raw).items()}
        return self._cache[key]

    def put(self, level: int, start: int, window: Window) -> None:
        key = (level, start)
        self._cache[key] = window
        self._dirty.add(key)
        self._deleted.discard(key)

    def delete(self, level: int, start: int) -> None:
        key = (level, start)
        self._cache[key] = None
        self._deleted.add(key)
        self._dirty.discard(key)

    def starts(self, level: int) -> list[int]:
        found = {int(field) for field in self._pipe.hkeys(self._keys[level])}
        found |= {start for lvl, start in self._dirty if lvl == level}
        found -= {start for lvl, start in self._deleted if lvl == level}
        return sorted(found)

    def flush(self, pipe: Any) -> None:
        for level, start in sorted(self._dirty):
            window = self._cache[(level, start)]
            payload = json.dumps({name: agg.dump() for name, agg in window.items()}, allow_nan=False)
            pipe.hset(self._keys[level], start, payload)
        for level, start in sorted(self._deleted):
            pipe.hdel(self._keys[level], start)


def _load_session(raw: Mapping[bytes, bytes]) -> Session:
    fields = {_text(key): _text(value) for key, value in raw.items()}
    session = Session(
        astronaut_id=fields["astronaut_id"],
        session_id=fields["sleep_session_id"],
        start_ts=float(fields["start_ts"]),
        status=fields["status"],
        end_ts=float(fields["end_ts"]) if fields.get("end_ts") else None,
        end_id=fields.get("end_id") or None,
    )
    session.load_state(json.loads(fields["state"]))
    return session


def _dump_session(session: Session) -> dict[str, str]:
    return {
        "astronaut_id": session.astronaut_id,
        "sleep_session_id": session.session_id,
        "status": session.status,
        "start_ts": repr(session.start_ts),
        "end_ts": "" if session.end_ts is None else repr(session.end_ts),
        "end_id": session.end_id or "",
        "updated_at": repr(time.time()),
        "state": json.dumps(session.dump_state(), allow_nan=False),
    }


class SleepProcessor:
    def __init__(self, client: redis.Redis, store: SummaryStore, cfg: Settings | None = None) -> None:
        self.r = client
        self.store = store
        self.cfg = cfg or Settings()
        self.engine = Engine(self.cfg)
        self.keys = Keys(self.cfg.prefix)
        self._group_ready = False

    def _level_keys(self, astronaut: str, session: str) -> list[str]:
        return [self.keys.agg(astronaut, session, level) for level in range(len(self.cfg.levels_s))]

    def ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            self.r.xgroup_create(self.keys.ingest, self.cfg.group, id="0", mkstream=True)
        except redis.ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
        self._group_ready = True

    # --- entrada: lo que usan la API y los sensores ---------------------------------

    def start_session(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Abre una sesión de forma síncrona. Repetir la llamada con el mismo inicio
        no cambia nada; con otro inicio lanza `SessionConflict`."""
        message = parse_message({**data, "type": START})
        self._apply_group(message.astronaut_id, message.session_id, [(None, message, "")], strict=True)
        return self.status(message.astronaut_id, message.session_id)

    def submit(self, data: Mapping[str, Any]) -> str:
        """Valida la forma del mensaje y lo encola. Lanza `Rejected` si está mal formado."""
        parse_message(data)
        return _text(self.r.xadd(self.keys.ingest, {"data": json.dumps(data, allow_nan=False)}))

    def submit_many(self, records: Iterable[Mapping[str, Any]]) -> list[str]:
        records = list(records)
        for item in records:
            parse_message(item)
        pipe = self.r.pipeline(transaction=False)
        for item in records:
            pipe.xadd(self.keys.ingest, {"data": json.dumps(item, allow_nan=False)})
        return [_text(entry_id) for entry_id in pipe.execute()]

    def end_session(self, astronaut_id: str, session_id: str, end_timestamp: float | None = None) -> str:
        """Encola la señal de fin. Va por el stream para quedar ordenada tras los registros."""
        data: dict[str, Any] = {"type": END, "astronaut_id": astronaut_id, "sleep_session_id": session_id}
        if end_timestamp is not None:
            data["end_timestamp"] = end_timestamp
        return self.submit(data)

    # --- consumo ---------------------------------------------------------------------

    def read(self, consumer: str, block_ms: int | None = None) -> list[Entry]:
        self.ensure_group()
        batches = self.r.xreadgroup(self.cfg.group, consumer, {self.keys.ingest: ">"},
                                    count=self.cfg.batch_count, block=block_ms)
        return [(_text(i), fields) for _, entries in batches or [] for i, fields in entries]

    def read_own_pending(self, consumer: str) -> list[Entry]:
        """Mensajes que este mismo consumidor leyó y no llegó a confirmar (tras un reinicio)."""
        self.ensure_group()
        batches = self.r.xreadgroup(self.cfg.group, consumer, {self.keys.ingest: "0"},
                                    count=self.cfg.batch_count)
        return [(_text(i), fields) for _, entries in batches or [] for i, fields in entries if fields]

    def recover(self, consumer: str, min_idle_ms: int | None = None) -> int:
        """Reclama mensajes que otro consumidor dejó sin confirmar. Uno que ya se ha
        entregado demasiadas veces va a la cola de rechazados en vez de reintentarse."""
        self.ensure_group()
        idle = self.cfg.claim_idle_ms if min_idle_ms is None else min_idle_ms
        pending = self.r.xpending_range(self.keys.ingest, self.cfg.group, min="-", max="+",
                                        count=self.cfg.batch_count, idle=idle)
        if not pending:
            return 0
        poison = [_text(p["message_id"]) for p in pending if p["times_delivered"] >= MAX_DELIVERIES]
        retry = [_text(p["message_id"]) for p in pending if p["times_delivered"] < MAX_DELIVERIES]
        if poison:
            dead = []
            for entry_id in poison:
                found = self.r.xrange(self.keys.ingest, entry_id, entry_id)
                raw = found[0][1].get(b"data", b"") if found else b""
                dead.append((entry_id, _text(raw), "processing_error"))
            self._dead_letter(dead)
        if not retry:
            return len(poison)
        claimed = self.r.xclaim(self.keys.ingest, self.cfg.group, consumer, min_idle_time=idle,
                                message_ids=retry)
        entries = [(_text(item[0]), item[1]) for item in claimed if item and item[1]]
        return self.process(entries) + len(poison)

    def process(self, entries: Iterable[Entry]) -> int:
        """Aplica un lote de mensajes del stream. Devuelve cuántos ha tratado."""
        groups: dict[tuple[str, str], list[tuple[str | None, Message, str]]] = {}
        dead: list[tuple[str, str, str]] = []
        count = 0
        for entry_id, fields in entries:
            count += 1
            raw = fields.get(b"data", fields.get("data"))
            text = "" if raw is None else _text(raw)
            try:
                message = parse_message(json.loads(text))
            except Rejected as error:
                dead.append((entry_id, text, error.code))
            except (ValueError, TypeError):
                dead.append((entry_id, text, "bad_json"))
            else:
                groups.setdefault((message.astronaut_id, message.session_id), []).append(
                    (entry_id, message, text))
        if dead:
            self._dead_letter(dead)
        for (astronaut, session), items in groups.items():
            try:
                self._apply_group(astronaut, session, items)
            except redis.RedisError:
                raise  # sin Redis no se puede seguir; lo no confirmado queda pendiente
            except Exception:
                # El fallo de una sesión no detiene a las demás. Sus mensajes quedan
                # pendientes y `recover` los reintenta o los manda a rechazados.
                logger.exception("Error procesando la sesión %s/%s", astronaut, session)
        return count

    def _dead_letter(self, items: list[tuple[str | None, str, str]], pipe: Any = None) -> None:
        own = pipe is None
        if own:
            pipe = self.r.pipeline(transaction=True)
        for entry_id, text, code in items:
            pipe.xadd(self.keys.dead, {"data": text, "reason": code, "source_id": entry_id or ""},
                      maxlen=self.cfg.dead_maxlen, approximate=True)
            pipe.hincrby(self.keys.stats, f"dead:{code}", 1)
            if own and entry_id:
                pipe.xack(self.keys.ingest, self.cfg.group, entry_id)
        if own:
            pipe.execute()

    def _seen_reader(self, pipe: Any, key: str, session: Session | None,
                     items: list[tuple[str | None, Message, str]]):
        """Lee de una vez el tramo del mapa de duplicados que cubre el lote."""
        if session is None:
            return lambda position: False
        resolution = self.cfg.dedup_resolution_s
        positions = [int((m.timestamp - session.start_ts) / resolution) for _, m, _ in items
                     if m.type not in (START, END) and m.timestamp >= session.start_ts]
        if not positions:
            return lambda position: False
        low = min(positions) // 8
        chunk = pipe.getrange(key, low, max(positions) // 8)

        def seen(position: int) -> bool:
            index = position // 8 - low
            return index < len(chunk) and bool(chunk[index] >> (7 - position % 8) & 1)

        return seen

    def _apply_group(self, astronaut: str, session_id: str,
                     items: list[tuple[str | None, Message, str]], strict: bool = False) -> None:
        skey = self.keys.session(astronaut, session_id)
        seen_key = self.keys.seen(astronaut, session_id)
        for _ in range(self.cfg.max_tx_retries):
            with self.r.pipeline() as pipe:
                try:
                    pipe.watch(skey)
                    raw = pipe.hgetall(skey)
                    session = _load_session(raw) if raw else None
                    windows = RedisWindows(pipe, self._level_keys(astronaut, session_id))
                    seen = self._seen_reader(pipe, seen_key, session, items)
                    closed: list[dict[str, Any]] = []
                    dead: list[tuple[str | None, str, str]] = []
                    positions: dict[int, None] = {}  # conjunto ordenado
                    created = became_finalizing = touched = False

                    for entry_id, message, text in items:
                        if message.type == START:
                            if session is None:
                                session = self.engine.new_session(message)
                                created = True
                            elif session.start_ts != message.timestamp:
                                if strict:
                                    raise SessionConflict(f"{astronaut}/{session_id} ya existe con otro inicio")
                                dead.append((entry_id, text, "session_conflict"))
                            continue
                        if session is None:
                            dead.append((entry_id, text, "unknown_session"))
                            continue
                        if message.type == END:
                            if session.status == ACTIVE:
                                last = session.watermark if session.watermark is not None else session.start_ts
                                end = message.timestamp if message.timestamp is not None else last
                                if end < session.start_ts:
                                    session.reject("end_before_start")
                                    dead.append((entry_id, text, "end_before_start"))
                                    continue
                                # Nunca antes del último dato ya aceptado
                                session.end_ts = max(end, last)
                                session.end_id = entry_id
                                session.status = FINALIZING
                                became_finalizing = True
                            continue
                        session.counters["received"] += 1
                        try:
                            position = self.engine.check(session, message.timestamp)
                        except Rejected as error:
                            session.reject(error.code)
                            dead.append((entry_id, text, error.code))
                            continue
                        if position in positions or seen(position):
                            session.counters["duplicates"] += 1
                            continue
                        positions[position] = None
                        self.engine.apply(session, windows, message, closed)
                        touched = True

                    if touched:
                        self.engine.advance(session, windows, closed)

                    ids = [entry_id for entry_id, _, _ in items if entry_id]
                    pipe.multi()
                    if session is not None:
                        pipe.hset(skey, mapping=_dump_session(session))
                        windows.flush(pipe)
                        for position in positions:
                            pipe.setbit(seen_key, position, 1)
                        if closed:
                            pipe.rpush(self.keys.anomalies(astronaut, session_id),
                                       *[json.dumps(episode, allow_nan=False) for episode in closed])
                        if created:
                            pipe.zadd(self.keys.index(astronaut), {session_id: session.start_ts})
                        if became_finalizing:
                            pipe.sadd(self.keys.finalizing, f"{astronaut}:{session_id}")
                    if dead:
                        self._dead_letter(dead, pipe)
                    if ids:
                        pipe.xack(self.keys.ingest, self.cfg.group, *ids)
                    pipe.execute()
                    return
                except redis.WatchError:
                    continue
        raise RuntimeError(f"Demasiados reintentos en la transacción de {astronaut}/{session_id}")

    # --- finalización -------------------------------------------------------------------

    def finalize_ready(self) -> list[tuple[str, str]]:
        """Genera el resumen de las sesiones con fin recibido cuyos mensajes ya están
        todos aplicados. Devuelve las que han quedado completadas."""
        done = []
        for token in sorted(_text(t) for t in self.r.smembers(self.keys.finalizing)):
            astronaut, session = token.split(":")
            try:
                if self.try_finalize(astronaut, session) is not None:
                    done.append((astronaut, session))
            except redis.RedisError:
                raise
            except Exception:
                logger.exception("No se pudo finalizar %s/%s; se reintentará", astronaut, session)
        return done

    def try_finalize(self, astronaut: str, session_id: str) -> dict[str, Any] | None:
        skey = self.keys.session(astronaut, session_id)
        status, end_id = (None if v is None else _text(v) for v in self.r.hmget(skey, "status", "end_id"))
        if status == FINALIZING:
            if self._has_pending_before(end_id, astronaut, session_id):
                return None
            self._seal(astronaut, session_id)
            status = _text(self.r.hget(skey, "status"))
        if status == SEALED:
            return self._complete(astronaut, session_id)
        if status == COMPLETED:
            return self.get_summary(astronaut, session_id)
        return None

    def _has_pending_before(self, end_id: str | None, astronaut: str, session_id: str) -> bool:
        """¿Queda sin confirmar algún mensaje de esta sesión anterior a su señal de fin?"""
        if not end_id:
            return False
        pending = self.r.xpending_range(self.keys.ingest, self.cfg.group, min="-", max=f"({end_id}",
                                        count=PENDING_SCAN)
        if len(pending) >= PENDING_SCAN:
            return True  # demasiados para mirarlos uno a uno: se espera
        for item in pending:
            entry_id = _text(item["message_id"])
            found = self.r.xrange(self.keys.ingest, entry_id, entry_id)
            if not found:
                continue
            try:
                data = json.loads(found[0][1].get(b"data", b"null"))
            except ValueError:
                continue
            if (isinstance(data, dict) and data.get("astronaut_id") == astronaut
                    and data.get("sleep_session_id") == session_id):
                return True
        return False

    def _seal(self, astronaut: str, session_id: str) -> None:
        """Cierra las ventanas y deja escrito el resumen. Desde aquí la sesión no admite datos."""
        skey = self.keys.session(astronaut, session_id)
        akey = self.keys.anomalies(astronaut, session_id)
        for _ in range(self.cfg.max_tx_retries):
            with self.r.pipeline() as pipe:
                try:
                    pipe.watch(skey)
                    session = _load_session(pipe.hgetall(skey))
                    if session.status != FINALIZING:
                        return
                    windows = RedisWindows(pipe, self._level_keys(astronaut, session_id))
                    closed: list[dict[str, Any]] = []
                    timeline = self.engine.seal(session, windows, closed)
                    anomalies = [json.loads(item) for item in pipe.lrange(akey, 0, -1)] + closed
                    summary = build_summary(session, timeline, anomalies, self.cfg)
                    pipe.multi()
                    pipe.hset(skey, mapping=_dump_session(session))
                    windows.flush(pipe)
                    if closed:
                        pipe.rpush(akey, *[json.dumps(episode, allow_nan=False) for episode in closed])
                    pipe.set(self.keys.summary(astronaut, session_id), json.dumps(summary, allow_nan=False))
                    pipe.execute()
                    return
                except redis.WatchError:
                    continue
        raise RuntimeError(f"Demasiados reintentos al cerrar {astronaut}/{session_id}")

    def _complete(self, astronaut: str, session_id: str) -> dict[str, Any]:
        """Persiste el resumen de forma duradera y solo entonces marca la sesión como
        completada, avisa y pone caducidad al estado temporal. Repetible sin efectos."""
        skey = self.keys.session(astronaut, session_id)
        summary_key = self.keys.summary(astronaut, session_id)
        summary = json.loads(self.r.get(summary_key))
        saved = self.store.save_summary(summary)
        for _ in range(self.cfg.max_tx_retries):
            with self.r.pipeline() as pipe:
                try:
                    pipe.watch(skey)
                    if _text(pipe.hget(skey, "status")) == COMPLETED:
                        return saved
                    pipe.multi()
                    pipe.hset(skey, "status", COMPLETED)
                    pipe.set(summary_key, json.dumps(saved, allow_nan=False), ex=self.cfg.summary_ttl_s)
                    temporary = [skey, self.keys.seen(astronaut, session_id),
                                 self.keys.anomalies(astronaut, session_id),
                                 *self._level_keys(astronaut, session_id)]
                    for key in temporary:
                        pipe.expire(key, self.cfg.completed_ttl_s)
                    meta = saved["session_metadata"]
                    pipe.xadd(self.keys.summaries, {
                        "astronaut_id": astronaut,
                        "sleep_session_id": session_id,
                        "start_timestamp": repr(meta["start_timestamp"]),
                        "end_timestamp": repr(meta["end_timestamp"]),
                    }, maxlen=1000, approximate=True)
                    pipe.srem(self.keys.finalizing, f"{astronaut}:{session_id}")
                    pipe.zrem(self.keys.index(astronaut), session_id)
                    pipe.execute()
                    return saved
                except redis.WatchError:
                    continue
        raise RuntimeError(f"Demasiados reintentos al completar {astronaut}/{session_id}")

    # --- mantenimiento --------------------------------------------------------------------

    def trim(self) -> int:
        """Borra del stream los registros ya confirmados por el grupo."""
        self.ensure_group()
        pending = self.r.xpending(self.keys.ingest, self.cfg.group)
        if pending["pending"]:
            threshold = _text(pending["min"])
        else:
            group = next(g for g in self.r.xinfo_groups(self.keys.ingest)
                         if _text(g["name"]) == self.cfg.group)
            last = _text(group["last-delivered-id"])
            if last == "0-0":
                return 0
            threshold = _next_id(last)
        return self.r.xtrim(self.keys.ingest, minid=threshold, approximate=False)

    def drain(self, consumer: str, max_rounds: int = 100000) -> None:
        """Procesa todo lo que haya en el stream y finaliza lo que esté listo. Para
        simulaciones y tests; el servicio usa el bucle de `worker`."""
        self.process(self.read_own_pending(consumer))
        for _ in range(max_rounds):
            entries = self.read(consumer)
            if not entries:
                break
            self.process(entries)
        self.finalize_ready()
        self.trim()

    # --- consulta ---------------------------------------------------------------------------

    def status(self, astronaut_id: str, session_id: str) -> dict[str, Any] | None:
        check_id(astronaut_id, "astronaut_id")
        check_id(session_id, "sleep_session_id")
        raw = self.r.hgetall(self.keys.session(astronaut_id, session_id))
        if not raw:
            summary = self.store.get_summary(astronaut_id, session_id)
            if summary is None:
                return None
            meta = summary["session_metadata"]
            return {"astronaut_id": astronaut_id, "sleep_session_id": session_id, "status": COMPLETED,
                    "start_timestamp": meta["start_timestamp"], "end_timestamp": meta["end_timestamp"],
                    "summary_available": True, "temporary_state": "expired"}
        session = _load_session(raw)
        pipe = self.r.pipeline(transaction=False)
        for key in self._level_keys(astronaut_id, session_id):
            pipe.hlen(key)
        lengths = pipe.execute()
        return {
            "astronaut_id": astronaut_id,
            "sleep_session_id": session_id,
            "status": session.status,
            "start_timestamp": session.start_ts,
            "end_timestamp": session.end_ts,
            "last_data_timestamp": session.watermark,
            "counters": session.counters,
            "rejections": session.rejections,
            "stored_aggregates": {str(size): n for size, n in zip(self.cfg.levels_s, lengths)},
            "anomalies": {**session.anomalies, "open": len(session.episodes)},
            "summary_available": session.status == COMPLETED,
        }

    def get_summary(self, astronaut_id: str, session_id: str) -> dict[str, Any] | None:
        """El resumen solo existe para el exterior cuando ya está guardado de forma duradera."""
        check_id(astronaut_id, "astronaut_id")
        check_id(session_id, "sleep_session_id")
        status = self.r.hget(self.keys.session(astronaut_id, session_id), "status")
        if status is not None and _text(status) != COMPLETED:
            return None
        cached = self.r.get(self.keys.summary(astronaut_id, session_id)) if status is not None else None
        if cached is not None:
            return json.loads(cached)
        return self.store.get_summary(astronaut_id, session_id)

    def list_sessions(self, astronaut_id: str) -> list[dict[str, Any]]:
        """Historial: sesiones completadas (almacén duradero) y las que siguen abiertas."""
        check_id(astronaut_id, "astronaut_id")
        sessions = self.store.list_sessions(astronaut_id)
        known = {item["sleep_session_id"] for item in sessions}
        for member, start in self.r.zrange(self.keys.index(astronaut_id), 0, -1, withscores=True):
            session_id = _text(member)
            if session_id in known:
                continue
            status = self.r.hget(self.keys.session(astronaut_id, session_id), "status")
            sessions.append({"astronaut_id": astronaut_id, "sleep_session_id": session_id,
                             "status": _text(status) if status else "unknown",
                             "start_timestamp": start, "end_timestamp": None})
        return sorted(sessions, key=lambda item: item["start_timestamp"])
