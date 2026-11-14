"""Adaptador del grafo social, con matrices a mano y contra el servicio real."""

import pytest

from conftest import social_doc
from crew_planner.config import Social
from crew_planner.model import ValidationError
from crew_planner.social import from_daily_result, integration_need, latest_before

CREW = ["A1", "A2", "A3"]
W = [[None, 0.6, None], [0.6, None, 0.2], [None, 0.2, None]]


def test_reads_weights_and_status():
    snap = from_daily_result(social_doc(4, CREW, W, {"A3": "review"}))
    assert snap.weight("A1", "A2") == 0.6
    assert snap.weight("A2", "A1") == 0.6
    assert snap.weight("A1", "A3") is None  # sin datos: nunca 0
    assert snap.weight("A1", "A1") is None
    assert snap.weight("A1", "X9") is None
    assert snap.known_weights() == [0.6, 0.2]
    assert snap.status["A3"] == "review"


def test_rejects_asymmetric_or_out_of_range():
    bad = [[None, 0.6, None], [0.5, None, 0.2], [None, 0.2, None]]
    with pytest.raises(ValidationError, match="simétrica"):
        from_daily_result(social_doc(4, CREW, bad))
    bad = [[None, 1.6, None], [1.6, None, 0.2], [None, 0.2, None]]
    with pytest.raises(ValidationError, match=r"\[0, 1\]"):
        from_daily_result(social_doc(4, CREW, bad))
    half = [[None, 0.6, None], [None, None, 0.2], [None, 0.2, None]]
    with pytest.raises(ValidationError, match="simétrica"):
        from_daily_result(social_doc(4, CREW, half))


def test_rejects_documents_without_isolation():
    with pytest.raises(ValidationError, match="aislamiento"):
        from_daily_result({"day": 1, "crew": CREW})


def test_usable_only_if_recent_and_previous():
    snap = from_daily_result(social_doc(4, CREW, W))
    config = Social(max_age_days=2)
    assert snap.usable_for(5, config) and snap.usable_for(6, config)
    assert not snap.usable_for(7, config)
    assert not snap.usable_for(4, config)  # el mismo día aún no está cerrado


def test_latest_before():
    docs = [social_doc(d, CREW, W) for d in (1, 3, 6)]
    assert latest_before(docs, 5).day == 3
    assert latest_before(docs, 1) is None


def test_integration_need_from_status():
    snap = from_daily_result(social_doc(4, CREW, W, {"A2": "follow_up", "A3": "review"}))
    need = integration_need(snap, CREW + ["A4"], Social())
    assert need == {"A1": 0.0, "A2": 0.5, "A3": 1.0, "A4": 0.0}


def test_integration_need_ignores_crew_wide_drop_and_missing_graph():
    snap = from_daily_result(social_doc(4, CREW, W, {"A3": "review"}, drop=True))
    assert set(integration_need(snap, CREW, Social()).values()) == {0.0}
    assert set(integration_need(None, CREW, Social()).values()) == {0.0}


def test_warming_up_and_no_data_give_no_need():
    snap = from_daily_result(social_doc(4, CREW, W, {"A1": "warming_up", "A2": "no_data"}))
    assert set(integration_need(snap, CREW, Social()).values()) == {0.0}


# --- contrato con el módulo real --------------------------------------------------


def test_contract_with_social_graph_service():
    """El adaptador entiende lo que guarda de verdad el servicio social-graph."""
    social_graph = pytest.importorskip("social_graph.service")
    from social_graph.isolation import IsolationAnalyzer
    from social_graph.params import Params
    from social_graph.schedule import FixedSchedule
    from social_graph.sources import ListSource
    from social_graph.store import MemoryStore

    h, day, cutoff = 3600.0, 86400.0, 4 * 3600.0
    crew = ["A", "B", "C"]
    standard = {"sleep": [(22 * h, 6 * h)], "work": [(8 * h, 16 * h)]}

    def positions(t):
        # A y B juntos de 17:00 a 19:00; C siempre lejos
        hour = (t % day) / h
        near = 17 <= hour < 19
        return {"A": [0, 0, 0], "B": [1 if near else 50, 0, 0], "C": [100, 0, 0]}

    messages, t = [], cutoff
    while t < cutoff + 3 * day + 600:
        messages.append((f"m{t:.0f}", {"t": t, "positions": positions(t)}))
        t += 30.0
    store = MemoryStore()
    social_graph.SocialGraphService(
        crew, FixedSchedule({a: standard for a in crew}), Params(), ListSource(messages), store,
        analyzer=IsolationAnalyzer(),
    ).run()

    docs = store.load_days()
    assert [d["day"] for d in docs] == [0, 1, 2]
    snap = latest_before(docs, 3)
    assert snap.day == 2 and snap.crew == tuple(crew)
    assert snap.weight("A", "B") > 0.5
    assert snap.weight("A", "C") == 0.0  # evaluable y sin interacción: cero legítimo
    assert snap.weight("A", "B") == snap.weight("B", "A")
    assert set(snap.status.values()) <= {"warming_up", "normal", "follow_up", "review"}
