"""Detector de interacción con histéresis y acumulador diario.

Reglas (docs/social_graph_design.md, apartado 4e):

- Entre dos muestras válidas consecutivas de una pareja separadas como mucho
  `max_gap_s`, el intervalo cuenta como observado. Si al inicio del intervalo
  estaban en contacto, suma interacción. Todo se recorta al ocio simultáneo.
- Si la separación es mayor, es un hueco: no suma nada y el contacto se reinicia.
- Las duraciones salen de los timestamps, nunca del número de muestras.
- No se guardan matrices ni grafos intermedios, solo totales por día.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations

from .intervals import Interval, clip, intersect, total, union
from .params import Params
from .schedule import Schedule, day_index, day_window, leisure, split_by_day
from .validation import PositionSample, pair_distances, pair_key

Pair = tuple[str, str]
_SEP = "|"


def _pair_to_str(pair: Pair) -> str:
    return _SEP.join(pair)


def _pair_from_str(text: str) -> Pair:
    a, b = text.split(_SEP)
    return (a, b)


@dataclass
class DayTotals:
    """Totales en bruto de un día de misión, en segundos."""

    interaction: dict[Pair, float] = field(default_factory=lambda: defaultdict(float))
    overlap_observed: dict[Pair, float] = field(default_factory=lambda: defaultdict(float))
    leisure_observed: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    accompanied: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    n_samples: int = 0

    def to_state(self) -> dict:
        return {
            "interaction": {_pair_to_str(k): v for k, v in self.interaction.items()},
            "overlap_observed": {_pair_to_str(k): v for k, v in self.overlap_observed.items()},
            "leisure_observed": dict(self.leisure_observed),
            "accompanied": dict(self.accompanied),
            "n_samples": self.n_samples,
        }

    @classmethod
    def from_state(cls, state: dict) -> "DayTotals":
        totals = cls(n_samples=state["n_samples"])
        totals.interaction.update({_pair_from_str(k): v for k, v in state["interaction"].items()})
        totals.overlap_observed.update(
            {_pair_from_str(k): v for k, v in state["overlap_observed"].items()}
        )
        totals.leisure_observed.update(state["leisure_observed"])
        totals.accompanied.update(state["accompanied"])
        return totals


@dataclass
class PairState:
    last_t: float | None = None
    in_contact: bool = False
    # Tiempo de contacto en ocio simultáneo del episodio actual
    dwell_s: float = 0.0
    # Contacto aún no confirmado (por debajo de la permanencia mínima), por día
    pending: dict[int, float] = field(default_factory=dict)

    def end_episode(self) -> None:
        self.in_contact = False
        self.dwell_s = 0.0
        self.pending = {}


class InteractionTracker:
    """Procesa instantáneas de posición y acumula totales por día de misión."""

    def __init__(self, crew: Sequence[str], schedule: Schedule, params: Params) -> None:
        if len(set(crew)) != len(crew):
            raise ValueError("Identificadores de astronauta repetidos")
        if any(_SEP in a for a in crew):
            raise ValueError(f"Los identificadores no pueden contener '{_SEP}'")
        self.crew = list(crew)
        self.schedule = schedule
        self.params = params
        self.last_sample_t: float | None = None
        self.n_discarded = 0
        self._pairs: dict[Pair, PairState] = {
            pair_key(a, b): PairState() for a, b in combinations(self.crew, 2)
        }
        self._last_seen: dict[str, float] = {}
        self._days: dict[int, DayTotals] = {}
        self._closed_through: int | None = None
        self._leisure_cache: dict[tuple[str, int], list[Interval]] = {}

    # --- días -----------------------------------------------------------------

    @property
    def current_day(self) -> int | None:
        if self.last_sample_t is None:
            return None
        return day_index(self.last_sample_t, self.params.day_cutoff_s)

    @property
    def closed_through(self) -> int | None:
        """Último día cerrado, o None si aún no se ha cerrado ninguno."""
        return self._closed_through

    def open_days(self) -> list[int]:
        return sorted(self._days)

    def totals(self, day: int) -> DayTotals:
        return self._days.get(day, DayTotals())

    def pop_day(self, day: int) -> DayTotals:
        """Cierra un día: devuelve sus totales y deja de acumular en él."""
        if self._closed_through is None or day > self._closed_through:
            self._closed_through = day
        for key in [k for k in self._leisure_cache if k[1] <= day]:
            del self._leisure_cache[key]
        return self._days.pop(day, DayTotals())

    def _is_closed(self, day: int) -> bool:
        return self._closed_through is not None and day <= self._closed_through

    def _day(self, day: int) -> DayTotals:
        return self._days.setdefault(day, DayTotals())

    def _leisure(self, astronaut: str, day: int) -> list[Interval]:
        key = (astronaut, day)
        if key not in self._leisure_cache:
            window = day_window(day, self.params.day_cutoff_s)
            self._leisure_cache[key] = leisure(self.schedule, astronaut, window)
        return self._leisure_cache[key]

    # --- muestras -------------------------------------------------------------

    def add_sample(self, sample: PositionSample) -> bool:
        """Procesa una instantánea. Devuelve False si se descarta por antigua.

        Descartar lo ya visto hace que releer mensajes tras un reinicio no
        cuente dos veces.
        """
        t = sample.t
        if self.last_sample_t is not None and t <= self.last_sample_t:
            self.n_discarded += 1
            return False

        cutoff = self.params.day_cutoff_s
        if not self._is_closed(day_index(t, cutoff)):
            self._day(day_index(t, cutoff)).n_samples += 1

        valid = [a for a in self.crew if sample.positions.get(a) is not None]
        for astronaut in valid:
            self._advance_astronaut(astronaut, t)
        for pair, distance in pair_distances(sample).items():
            self._advance_pair(pair, t, distance)
        for astronaut in valid:
            self._last_seen[astronaut] = t
        self.last_sample_t = t
        return True

    def _advance_astronaut(self, astronaut: str, t: float) -> None:
        """Ocio observado y tiempo acompañado del astronauta desde su última muestra."""
        last = self._last_seen.get(astronaut)
        if last is None or t - last > self.params.max_gap_s:
            return
        # Compañeros en contacto confirmado, con estado vigente en `last`
        partners = [
            other
            for other in self.crew
            if other != astronaut and self._is_confirmed(pair_key(astronaut, other), last)
        ]
        for day, start, end in split_by_day(last, t, self.params.day_cutoff_s):
            if self._is_closed(day):
                continue
            own = clip(self._leisure(astronaut, day), start, end)
            totals = self._day(day)
            totals.leisure_observed[astronaut] += total(own)
            if partners:
                together = union(*(intersect(own, self._leisure(p, day)) for p in partners))
                totals.accompanied[astronaut] += total(together)

    def _is_confirmed(self, pair: Pair, at: float) -> bool:
        state = self._pairs[pair]
        return (
            state.in_contact
            and state.last_t == at
            and state.dwell_s >= self.params.min_dwell_s
        )

    def _advance_pair(self, pair: Pair, t: float, distance: float) -> None:
        state = self._pairs[pair]
        params = self.params
        if state.last_t is not None:
            if t - state.last_t <= params.max_gap_s:
                self._credit_interval(pair, state, state.last_t, t)
            else:
                # Hueco de datos: no se inventa interacción y hay que volver a entrar
                state.end_episode()

        if state.in_contact:
            if distance > params.d_out_m:
                state.end_episode()
        elif distance <= params.d_in_m:
            state.in_contact = True
        state.last_t = t

    def _credit_interval(self, pair: Pair, state: PairState, start: float, end: float) -> None:
        a, b = pair
        for day, piece_start, piece_end in split_by_day(start, end, self.params.day_cutoff_s):
            joint = intersect(
                clip(self._leisure(a, day), piece_start, piece_end), self._leisure(b, day)
            )
            duration = total(joint)
            if duration <= 0:
                continue
            if not self._is_closed(day):
                self._day(day).overlap_observed[pair] += duration
            if state.in_contact:
                self._credit_contact(pair, state, day, duration)

    def _credit_contact(self, pair: Pair, state: PairState, day: int, duration: float) -> None:
        state.dwell_s += duration
        state.pending[day] = state.pending.get(day, 0.0) + duration
        if state.dwell_s < self.params.min_dwell_s:
            return
        # Permanencia mínima alcanzada: se confirma también lo pendiente
        for pending_day, seconds in state.pending.items():
            if not self._is_closed(pending_day):
                self._day(pending_day).interaction[pair] += seconds
        state.pending = {}

    # --- estado para checkpoint -----------------------------------------------

    def to_state(self) -> dict:
        """Estado completo en tipos compatibles con JSON."""
        return {
            "last_sample_t": self.last_sample_t,
            "n_discarded": self.n_discarded,
            "closed_through": self._closed_through,
            "last_seen": dict(self._last_seen),
            "pairs": {
                _pair_to_str(pair): {
                    "last_t": st.last_t,
                    "in_contact": st.in_contact,
                    "dwell_s": st.dwell_s,
                    "pending": {str(day): s for day, s in st.pending.items()},
                }
                for pair, st in self._pairs.items()
            },
            "days": {str(day): totals.to_state() for day, totals in self._days.items()},
        }

    @classmethod
    def from_state(
        cls, crew: Sequence[str], schedule: Schedule, params: Params, state: dict
    ) -> "InteractionTracker":
        tracker = cls(crew, schedule, params)
        tracker.last_sample_t = state["last_sample_t"]
        tracker.n_discarded = state["n_discarded"]
        tracker._closed_through = state["closed_through"]
        tracker._last_seen = {a: t for a, t in state["last_seen"].items() if a in tracker.crew}
        for text, st in state["pairs"].items():
            pair = _pair_from_str(text)
            if pair in tracker._pairs:
                tracker._pairs[pair] = PairState(
                    last_t=st["last_t"],
                    in_contact=st["in_contact"],
                    dwell_s=st["dwell_s"],
                    pending={int(day): s for day, s in st["pending"].items()},
                )
        tracker._days = {int(day): DayTotals.from_state(t) for day, t in state["days"].items()}
        return tracker
