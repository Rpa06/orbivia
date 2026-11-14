"""Motor de una sesión de sueño: ventanas, colapso progresivo y anomalías.

No conoce Redis. Trabaja sobre el estado de la sesión (`Session`) y un almacén
de ventanas (`WindowStore`); el backend carga ambos, llama al motor y confirma
el resultado en una sola transacción.

Ventanas. El nivel 0 tiene las ventanas más finas (1 min por defecto). Cada
nivel k < último se conserva `retain_s[k]` segundos por detrás del último dato;
lo más antiguo se funde en el nivel k+1 y se borra. `floors[k]` es el instante
por debajo del cual el nivel k ya no existe. Un registro atrasado va al nivel
más fino que todavía cubre su instante, de modo que nunca se pierde.

Además se mantiene un acumulador global por métrica (`total`), actualizado con
cada registro: las métricas finales no requieren recorrer nada al terminar.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import ID_PATTERN, Settings
from .records import INVALID, MISSING, Message, Rejected, classify
from .stats import Agg, Ewma, Trend

ACTIVE, FINALIZING, SEALED, COMPLETED = "active", "finalizing", "sealed", "completed"

Window = dict[str, Agg]


class WindowStore(Protocol):
    def get(self, level: int, start: int) -> Window | None: ...

    def put(self, level: int, start: int, window: Window) -> None: ...

    def delete(self, level: int, start: int) -> None: ...

    def starts(self, level: int) -> list[int]: ...


class MemoryWindows:
    """Almacén de ventanas en memoria, para tests del motor."""

    def __init__(self) -> None:
        self.levels: dict[int, dict[int, Window]] = {}

    def get(self, level: int, start: int) -> Window | None:
        return self.levels.get(level, {}).get(start)

    def put(self, level: int, start: int, window: Window) -> None:
        self.levels.setdefault(level, {})[start] = window

    def delete(self, level: int, start: int) -> None:
        self.levels.get(level, {}).pop(start, None)

    def starts(self, level: int) -> list[int]:
        return sorted(self.levels.get(level, {}))


def _counters() -> dict[str, int]:
    return {"received": 0, "accepted": 0, "duplicates": 0, "rejected": 0,
            "out_of_order": 0, "late_coarse": 0}


def _activity() -> dict[str, Any]:
    return {"next": None, "scored": 0, "active": 0, "unknown": 0, "bouts": 0, "prev": None}


@dataclass
class Session:
    astronaut_id: str
    session_id: str
    start_ts: float
    status: str = ACTIVE
    end_ts: float | None = None
    end_id: str | None = None
    expected: list[str] = field(default_factory=list)
    sample_period_s: float | None = None
    baselines: dict[str, dict[str, dict[str, float]]] = field(
        default_factory=lambda: {"metrics": {}, "vector": {}})
    watermark: float | None = None
    counters: dict[str, int] = field(default_factory=_counters)
    rejections: dict[str, int] = field(default_factory=dict)
    invalid_reasons: dict[str, int] = field(default_factory=dict)
    total: dict[str, Agg] = field(default_factory=dict)
    trend: dict[str, Trend] = field(default_factory=dict)
    ewma: dict[str, Ewma] = field(default_factory=dict)
    floors: list[int | None] = field(default_factory=list)
    activity: dict[str, Any] = field(default_factory=_activity)
    episodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    anomalies: dict[str, int] = field(default_factory=lambda: {"stored": 0, "dropped": 0, "samples": 0})

    def dump_state(self) -> dict[str, Any]:
        return {
            "expected": self.expected,
            "sample_period_s": self.sample_period_s,
            "baselines": self.baselines,
            "watermark": self.watermark,
            "counters": self.counters,
            "rejections": self.rejections,
            "invalid_reasons": self.invalid_reasons,
            "total": {name: agg.dump() for name, agg in self.total.items()},
            "trend": {name: t.dump() for name, t in self.trend.items()},
            "ewma": {name: e.dump() for name, e in self.ewma.items()},
            "floors": self.floors,
            "activity": self.activity,
            "episodes": self.episodes,
            "anomalies": self.anomalies,
        }

    def load_state(self, raw: dict[str, Any]) -> None:
        for key in ("expected", "sample_period_s", "baselines", "watermark", "counters",
                    "rejections", "invalid_reasons", "floors", "activity", "episodes", "anomalies"):
            setattr(self, key, raw[key])
        self.total = {name: Agg.load(item) for name, item in raw["total"].items()}
        self.trend = {name: Trend(item) for name, item in raw["trend"].items()}
        self.ewma = {name: Ewma(item) for name, item in raw["ewma"].items()}

    def reject(self, code: str) -> None:
        self.counters["rejected"] += 1
        self.rejections[code] = self.rejections.get(code, 0) + 1


def _align(ts: float, size: int) -> int:
    return int(ts // size) * size


class Engine:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.specs = cfg.specs
        self.levels = cfg.levels_s
        self.top = len(cfg.levels_s) - 1

    def new_session(self, message: Message) -> Session:
        options = message.options
        return Session(
            astronaut_id=message.astronaut_id,
            session_id=message.session_id,
            start_ts=message.timestamp,
            expected=options.get("expected_metrics") or sorted(self.specs),
            sample_period_s=options.get("sample_period_s"),
            baselines=options.get("baselines") or {"metrics": {}, "vector": {}},
            floors=[None] * self.top,
        )

    # --- admisión ----------------------------------------------------------------

    def check(self, session: Session, ts: float) -> int:
        """Comprueba que el registro pertenece a la sesión. Devuelve su posición
        en el mapa de bits de duplicados."""
        if session.status in (SEALED, COMPLETED):
            raise Rejected("session_closed", "la sesión ya tiene resumen")
        if ts < session.start_ts:
            raise Rejected("before_start", "timestamp anterior al inicio de la sesión")
        if ts >= session.start_ts + self.cfg.max_session_s:
            raise Rejected("beyond_max_session", "timestamp más allá de la duración máxima")
        if session.status == FINALIZING and ts > session.end_ts:
            raise Rejected("after_end", "timestamp posterior al fin de la sesión")
        return int((ts - session.start_ts) / self.cfg.dedup_resolution_s)

    # --- un registro ---------------------------------------------------------------

    def _route(self, session: Session, ts: float) -> tuple[int, int]:
        for level in range(self.top):
            floor = session.floors[level]
            if floor is None or ts >= floor:
                return level, _align(ts, self.levels[level])
        return self.top, _align(ts, self.levels[self.top])

    def apply(self, session: Session, windows: WindowStore, message: Message,
              out: list[dict[str, Any]]) -> None:
        """Incorpora un registro ya admitido y no duplicado. Los episodios de
        anomalía que se cierran se añaden a `out`."""
        ts = message.timestamp
        session.counters["accepted"] += 1
        if session.watermark is not None and ts < session.watermark:
            session.counters["out_of_order"] += 1
        level, start = self._route(session, ts)
        if level > 0:
            session.counters["late_coarse"] += 1
        window = windows.get(level, start) or {}

        names = list(session.expected)
        for name in message.metrics:
            if name in session.expected:
                continue
            if isinstance(name, str) and ID_PATTERN.fullmatch(name):
                names.append(name)  # métrica nueva: se agrega sin rango ni histograma
            else:
                session.invalid_reasons["bad_metric_name"] = (
                    session.invalid_reasons.get("bad_metric_name", 0) + 1)
        for name in names:
            spec = self.specs.get(name)
            state, value = classify(name in message.metrics, message.metrics.get(name), spec,
                                    message.units.get(name))
            in_window = window.setdefault(name, Agg())
            in_total = session.total.setdefault(name, Agg())
            if state == MISSING:
                in_window.missing += 1
                in_total.missing += 1
                continue
            if state == INVALID:
                in_window.invalid += 1
                in_total.invalid += 1
                session.invalid_reasons[value] = session.invalid_reasons.get(value, 0) + 1
                continue
            # La referencia y el contexto son los anteriores a incorporar el valor
            self._detect(session, name, value, ts, level, start, in_window, out)
            in_window.add(value, ts, spec)
            in_total.add(value, ts, spec)
            session.trend.setdefault(name, Trend()).add(ts - session.start_ts, value)
            session.ewma.setdefault(name, Ewma()).update(
                value, ts, self.cfg.ewma_halflife_s, self.cfg.warmup_n)

        windows.put(level, start, window)
        if session.watermark is None or ts > session.watermark:
            session.watermark = ts

    # --- anomalías -------------------------------------------------------------------

    def _detect(self, session: Session, name: str, value: float, ts: float, level: int,
                start: int, window_agg: Agg, out: list[dict[str, Any]]) -> None:
        spec = self.specs.get(name)
        found: list[tuple[str, float, dict[str, float]]] = []
        ewma = session.ewma.get(name)
        if ewma is not None and spec is not None:
            z = ewma.zscore(value, spec.min_std, self.cfg.warmup_n)
            if z is not None and abs(z) > self.cfg.z_threshold:
                found.append(("ewma_zscore", z, {"mean": ewma.mean, "std": ewma.std(spec.min_std)}))
        baseline = session.baselines["metrics"].get(name)
        if baseline is not None:
            z = (value - baseline["mean"]) / baseline["sd"]
            if abs(z) > self.cfg.baseline_z_threshold:
                found.append(("baseline_zscore", z, {"mean": baseline["mean"], "std": baseline["sd"]}))

        for method, z, reference in found:
            session.anomalies["samples"] += 1
            key = f"{name}|{method}"
            episode = session.episodes.get(key)
            if episode is not None and (
                episode["start_ts"] - self.cfg.episode_gap_s <= ts
                <= episode["end_ts"] + self.cfg.episode_gap_s
            ):
                episode["count"] += 1
                episode["start_ts"] = min(episode["start_ts"], ts)
                episode["end_ts"] = max(episode["end_ts"], ts)
                # El pico es el valor más alejado de la referencia inicial del episodio.
                # No se compara z: la referencia se adapta mientras dura la anomalía.
                center = episode["reference"]["mean"]
                if abs(value - center) > abs(episode["peak_value"] - center):
                    episode.update(peak_value=value, peak_ts=ts, peak_z=z)
                continue
            if episode is not None:
                self._emit(session, episode, out)
            session.episodes[key] = {
                "kind": "statistical_anomaly",
                "metric": name,
                "unit": spec.unit if spec else None,
                "method": method,
                "threshold": (self.cfg.z_threshold if method == "ewma_zscore"
                              else self.cfg.baseline_z_threshold),
                "start_ts": ts,
                "end_ts": ts,
                "count": 1,
                "peak_value": value,
                "peak_ts": ts,
                "peak_z": z,
                "reference": reference,
                "window": {
                    "start": start,
                    "size_s": self.levels[level],
                    "n": window_agg.n,
                    "mean": window_agg.mean if window_agg.n else None,
                    "std": window_agg.std,
                    "min": window_agg.min,
                    "max": window_agg.max,
                },
            }

    def _emit(self, session: Session, episode: dict[str, Any], out: list[dict[str, Any]]) -> None:
        if session.anomalies["stored"] < self.cfg.max_anomalies:
            session.anomalies["stored"] += 1
            out.append(episode)
        else:
            session.anomalies["dropped"] += 1

    def _flush_episodes(self, session: Session, out: list[dict[str, Any]], older_than: float | None) -> None:
        for key in sorted(session.episodes):
            if older_than is None or session.episodes[key]["end_ts"] < older_than:
                self._emit(session, session.episodes.pop(key), out)

    # --- avance tras un lote ---------------------------------------------------------

    def advance(self, session: Session, windows: WindowStore, out: list[dict[str, Any]]) -> None:
        """Puntúa los minutos ya cerrados, cierra episodios y colapsa lo antiguo."""
        if session.watermark is None:
            return
        self._score_epochs(session, windows, session.watermark - self.cfg.lateness_s, closed_only=True)
        self._flush_episodes(session, out, session.watermark - self.cfg.episode_gap_s)
        for level in range(self.top):
            target = _align(session.watermark - self.cfg.retain_s[level], self.levels[level + 1])
            self._collapse(session, windows, level, target)

    def _collapse(self, session: Session, windows: WindowStore, level: int, target: int) -> None:
        """Funde en el nivel siguiente las ventanas del nivel `level` anteriores a `target`."""
        parent_size = self.levels[level + 1]
        floor = session.floors[level]
        if floor is None:
            floor = _align(session.start_ts, parent_size)
        if target <= floor:
            return
        for start in range(floor, target, self.levels[level]):
            child = windows.get(level, start)
            if child is None:
                continue
            parent_start = _align(start, parent_size)
            parent = windows.get(level + 1, parent_start) or {}
            for name, agg in child.items():
                parent.setdefault(name, Agg()).merge(agg)
            windows.put(level + 1, parent_start, parent)
            windows.delete(level, start)
        session.floors[level] = target

    def _score_epochs(self, session: Session, windows: WindowStore, until: float, closed_only: bool) -> None:
        """Clasifica cada minuto como activo, quieto o sin dato de movimiento."""
        size = self.levels[0]
        activity = session.activity
        if activity["next"] is None:
            activity["next"] = _align(session.start_ts, size)
        while (activity["next"] + size <= until) if closed_only else (activity["next"] < until):
            window = windows.get(0, activity["next"])
            agg = window.get(self.cfg.activity_metric) if window else None
            if agg is None or agg.n == 0:
                activity["unknown"] += 1
                activity["prev"] = None
            else:
                activity["scored"] += 1
                is_active = agg.mean > self.cfg.activity_threshold
                if is_active:
                    activity["active"] += 1
                    if activity["prev"] != 1:
                        activity["bouts"] += 1
                activity["prev"] = 1 if is_active else 0
            activity["next"] += size

    # --- cierre ------------------------------------------------------------------------

    def seal(self, session: Session, windows: WindowStore, out: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Cierra la sesión: puntúa lo que queda, funde todo en el último nivel y
        devuelve la línea temporal final. El trabajo está acotado por el número de
        ventanas vivas, no por el de registros."""
        self._score_epochs(session, windows, session.end_ts, closed_only=False)
        self._flush_episodes(session, out, None)
        for level in range(self.top):
            parent_size = self.levels[level + 1]
            for start in windows.starts(level):
                child = windows.get(level, start)
                parent_start = _align(start, parent_size)
                parent = windows.get(level + 1, parent_start) or {}
                for name, agg in child.items():
                    parent.setdefault(name, Agg()).merge(agg)
                windows.put(level + 1, parent_start, parent)
                windows.delete(level, start)
            session.floors[level] = _align(session.end_ts, parent_size) + parent_size
        session.status = SEALED
        return [
            {"start": start, "size_s": self.levels[self.top], "window": windows.get(self.top, start)}
            for start in windows.starts(self.top)
        ]
