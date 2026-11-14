"""Servicio vivo: cierre de día, checkpoint y reinicio sin doble conteo."""

import json
import logging

import pytest

from conftest import H, apart, standard_schedule, together
from social_graph.config import params_version
from social_graph.daily import NO_DATA
from social_graph.params import Params
from social_graph.service import SocialGraphService
from social_graph.sources import ListSource, RedisStreamSource
from social_graph.store import MemoryStore
from social_graph.tracker import InteractionTracker
from social_graph.validation import PositionSample

CREW = ["A", "B", "C"]
DAY = 24 * H
CUTOFF = 4 * H
PERIOD = 30.0


def positions_at(t: float) -> dict:
    """A y B juntos de 17:00 a 18:00 cada día; el día 1 se une C."""
    hour = (t % DAY) / H
    day = int((t - CUTOFF) // DAY)
    if 17 <= hour < 18:
        return together(apart(CREW), CREW if day == 1 else ["A", "B"])
    return apart(CREW)


def messages(start: float, end: float, period: float = PERIOD) -> list:
    out, k = [], 0
    while start + k * period < end:
        t = start + k * period
        out.append((f"m{t:.0f}", {"t": t, "positions": {a: list(p) for a, p in positions_at(t).items()}}))
        k += 1
    return out


# Dos días completos y el principio del tercero, que provoca el cierre del segundo
ALL = messages(CUTOFF, CUTOFF + 2 * DAY + 600)


def make_service(source, store, **kwargs) -> SocialGraphService:
    return SocialGraphService(CREW, standard_schedule(CREW), Params(), source, store, **kwargs)


def run_all(store=None) -> MemoryStore:
    store = store or MemoryStore()
    make_service(ListSource(ALL), store).run()
    return store


@pytest.fixture(scope="module")
def reference() -> list[dict]:
    return run_all().load_days()


def test_days_are_closed_and_stored(reference):
    assert [d["day"] for d in reference] == [0, 1]
    day0, day1 = reference
    assert day0["crew"] == CREW
    assert day0["params_version"] == params_version(Params())
    assert day0["interaction_s"][0][1] == pytest.approx(3600.0)
    assert day0["status"][0][2] == "zero"
    assert day1["interaction_s"][0][2] == pytest.approx(3600.0)
    assert day0["quality"]["n_samples"] == DAY / PERIOD
    assert day0["quality"]["bound_violations"] == 0
    assert day0["params"]["kappa"] == 0.3


def test_stored_documents_are_strict_json(reference):
    text = json.dumps(reference, allow_nan=False)
    assert "NaN" not in text
    # La diagonal de R no está definida: se guarda como null, no como 0
    assert reference[0]["r_overlap"][0][0] is None


def test_open_day_is_not_stored_but_checkpointed():
    store = run_all()
    state = store.load_checkpoint()
    assert list(state["tracker"]["days"]) == ["2"]
    assert state["tracker"]["closed_through"] == 1
    assert state["cursor"]["id"] == ALL[-1][0]


@pytest.mark.parametrize("checkpoint_at,crash_at", [(100, 100), (1570, 1620), (2900, 3500), (5700, 5800)])
def test_restart_resumes_without_loss_or_double_count(reference, checkpoint_at, crash_at):
    """El servicio muere en `crash_at`; su último checkpoint es de `checkpoint_at`."""
    store = MemoryStore()
    first = make_service(ListSource(ALL), store)
    for message in ALL[:checkpoint_at]:
        first.process(*message)
    first.checkpoint()
    snapshot = store.load_checkpoint()
    for message in ALL[checkpoint_at:crash_at]:
        first.process(*message)  # trabajo posterior al checkpoint
    if first.tracker.closed_through == snapshot["tracker"]["closed_through"]:
        # Sin cierre de día por medio, lo posterior al checkpoint se pierde con el proceso
        store.save_checkpoint(snapshot)

    make_service(ListSource(ALL), store).run()
    assert store.load_days() == reference


def test_redelivered_messages_are_not_counted_twice(reference):
    class ReplayEverything(ListSource):
        def stream(self, cursor):
            return super().stream(None)  # ignora el cursor: reenvía todo

    store = MemoryStore()
    first = make_service(ListSource(ALL), store)
    for message in ALL[:3500]:
        first.process(*message)
    first.checkpoint()

    make_service(ReplayEverything(ALL), store).run()
    days = store.load_days()
    assert [d["day"] for d in days] == [0, 1]
    for got, expected in zip(days, reference):
        assert got["interaction_s"] == expected["interaction_s"]
        assert got["overlap_observed_s"] == expected["overlap_observed_s"]
        assert got["weights"] == expected["weights"]
    assert days[1]["quality"]["discarded_samples"] > 0


def test_tracker_state_roundtrip_mid_contact():
    schedule, params = standard_schedule(CREW), Params()
    samples = [PositionSample(m["t"], {a: tuple(p) for a, p in m["positions"].items()}) for _, m in ALL[:2000]]
    cut = 1570  # dentro del contacto de las 17:00
    straight = InteractionTracker(CREW, schedule, params)
    for s in samples:
        straight.add_sample(s)

    first = InteractionTracker(CREW, schedule, params)
    for s in samples[:cut]:
        first.add_sample(s)
    restored = InteractionTracker.from_state(
        CREW, schedule, params, json.loads(json.dumps(first.to_state()))
    )
    for s in samples[cut:]:
        restored.add_sample(s)
    assert restored.to_state() == straight.to_state()


def test_checkpoint_of_other_crew_is_ignored():
    store = run_all()
    other = SocialGraphService(["X", "Y"], standard_schedule(["X", "Y"]), Params(), ListSource([]), store)
    assert other.restore() is False
    assert other.tracker.last_sample_t is None


def test_invalid_messages_are_counted_not_fatal():
    bad = [("b1", None), ("b2", {"t": "x"}), ("b3", {"t": CUTOFF + 45, "positions": {"A": [0, 0], "Z": [0, 0, 0]}})]
    stream = ALL[:2] + bad + ALL[2:]
    store = MemoryStore()
    make_service(ListSource(stream), store).run()
    quality = store.load_days()[0]["quality"]
    assert quality["invalid_messages"] == 2
    assert quality["position_issues"] == 2


def test_days_without_any_data_are_stored_as_no_data():
    stream = messages(CUTOFF, CUTOFF + DAY) + messages(CUTOFF + 3 * DAY, CUTOFF + 3 * DAY + 600)
    store = MemoryStore()
    make_service(ListSource(stream), store).run()
    days = store.load_days()
    assert [d["day"] for d in days] == [0, 1, 2]
    assert days[0]["node_status"] == ["ok"] * 3
    for empty in days[1:]:
        assert empty["node_status"] == [NO_DATA] * 3
        assert empty["quality"]["n_samples"] == 0


def test_day_hook_receives_each_closed_day():
    seen = []
    make_service(ListSource(ALL), MemoryStore(), on_day_closed=[lambda doc: seen.append(doc["day"])]).run()
    assert seen == [0, 1]


def test_periodic_checkpoint_uses_clock():
    ticks = iter(range(10_000))
    store = MemoryStore()
    saves = []
    original = store.save_checkpoint
    store.save_checkpoint = lambda state: (saves.append(1), original(state))[1]
    make_service(ListSource(ALL[:50]), store, checkpoint_every_s=10, clock=lambda: next(ticks)).run()
    assert 4 <= len(saves) <= 7  # ~50 ticks / 10 s, más el checkpoint final


def test_warns_when_sampling_is_slower_than_max_gap(caplog):
    slow = messages(CUTOFF, CUTOFF + 2 * H, period=120.0)
    with caplog.at_level(logging.WARNING):
        make_service(ListSource(slow), MemoryStore()).run()
    assert any("hueco máximo" in record.message for record in caplog.records)


class FakeRedis:
    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def xread(self, streams, count=None, block=None):
        (name, last_id), = streams.items()
        self.calls.append(last_id)
        ids = [entry_id for entry_id, _ in self.entries]
        start = ids.index(last_id.encode()) + 1 if last_id != "0-0" else 0
        batch = self.entries[start:start + 2]
        return [(name.encode(), batch)] if batch else []


def test_redis_source_decodes_resumes_and_ticks():
    entries = [
        (b"1-0", {b"data": json.dumps({"t": 1.0, "positions": {}}).encode()}),
        (b"2-0", {b"data": b"{no es json"}),
        (b"3-0", {b"otro": b"x"}),
    ]
    client = FakeRedis(entries)
    stream = RedisStreamSource(client, "orbivia:positions").stream({"id": "1-0", "t": 1.0})
    assert next(stream) == ("2-0", None)
    assert next(stream) == ("3-0", None)
    assert next(stream) is None  # sin mensajes nuevos: pausa
    assert client.calls[0] == "1-0"

    fresh = RedisStreamSource(FakeRedis(entries), "orbivia:positions").stream(None)
    assert next(fresh) == ("1-0", {"t": 1.0, "positions": {}})
