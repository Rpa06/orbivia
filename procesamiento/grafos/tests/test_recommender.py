"""CollaborationRecommender sobre grafos simulados."""

import json

import numpy as np
import pytest

from social_graph.config import load_settings
from social_graph.isolation import IsolationAnalyzer
from social_graph.recommender import (
    ACTIVITIES,
    BRIDGE,
    CROSS_COMMUNITY,
    LOW_INTEGRATION,
    WEAK_PAIR,
    CollaborationRecommender,
    RecommenderConfig,
)
from test_isolation import make_doc
from test_simulator import simulate
from test_structure import CREW, matrix, two_groups

H = 3600.0
EVENING = [(16 * H, 22 * H)]  # 6 h de ocio
ALL_EVENING = {a: EVENING for a in CREW}


def assess(weights, days=1, evaluable=None, node_status=None, accompanied=None) -> dict:
    docs = []
    for day in range(days):
        doc = make_doc(day, weights, evaluable=evaluable, node_status=node_status, accompanied=accompanied)
        doc["crew"] = CREW
        docs.append(doc)
    return IsolationAnalyzer().analyze(docs)[-1]


def recommend(assessment, leisure=ALL_EVENING, history=(), config=None, target_day=None):
    target = assessment["day"] + 1 if target_day is None else target_day
    return CollaborationRecommender(config).recommend(assessment, leisure, target, history)


def test_well_connected_crew_gets_no_proposals():
    result = recommend(assess(matrix({}, default=0.6)))
    assert result["proposals"] == [] and result["schedule_issues"] == []


def test_isolated_groups_get_cross_group_proposals():
    result = recommend(assess(two_groups()))
    proposals = result["proposals"]
    assert len(proposals) == 2
    groups = [{"A", "B", "C"}, {"D", "E", "F"}]
    for proposal in proposals:
        members = set(proposal["participants"])
        assert members & groups[0] and members & groups[1]
        assert CROSS_COMMUNITY in proposal["reasons"] and WEAK_PAIR in proposal["reasons"]
        assert proposal["status"] == "proposed" and proposal["voluntary"] is True
    # Nadie recibe dos propuestas el mismo día
    assert not set(proposals[0]["participants"]) & set(proposals[1]["participants"])


def test_bridge_joins_a_trio_between_groups():
    result = recommend(assess(two_groups(bridge=0.3)), config=RecommenderConfig(group_sizes=(3,)))
    first = result["proposals"][0]
    assert BRIDGE in first["reasons"]
    assert set(first["participants"]) & {"C", "D"}
    assert "ya se relaciona con ambos grupos" in first["justification"]


def test_disconnected_astronaut_is_paired_with_someone_well_connected():
    weights = matrix({(i, j): 0.6 for i in range(5) for j in range(i + 1, 5)})
    result = recommend(assess(weights))
    first = result["proposals"][0]
    assert "F" in first["participants"]
    assert LOW_INTEGRATION in first["reasons"]
    assert len(set(first["participants"]) - {"F"}) >= 1


def test_trio_is_never_made_only_of_low_integration_people():
    # D, E y F están desconectados de todos
    weights = matrix({(0, 1): 0.6, (0, 2): 0.6, (1, 2): 0.6})
    result = recommend(assess(weights), config=RecommenderConfig(group_sizes=(3,), max_per_day=6))
    assert result["proposals"]
    for proposal in result["proposals"]:
        assert set(proposal["participants"]) & {"A", "B", "C"}


def test_justification_uses_numbers_and_crew_text_reveals_nothing():
    weights = matrix({(i, j): 0.6 for i in range(5) for j in range(i + 1, 5)})
    proposal = recommend(assess(weights))["proposals"][0]
    assert "peso de interacción 0.00" in proposal["justification"]
    assert "mediana de la tripulación" in proposal["justification"]
    assert "Propuestas en los últimos 7 días" in proposal["justification"]
    assert proposal["metrics"]["pair_weights"][0]["weight"] == 0.0
    text = proposal["crew_text"]
    assert text.startswith("Propuesta voluntaria: ")
    assert proposal["window"] in text and proposal["activity"] in text
    for word in ("peso", "integración", "aislamiento", "mediana", "indicador", "0."):
        assert word not in text
    json.dumps(proposal, allow_nan=False)


def test_window_is_inside_common_leisure():
    leisure = dict(ALL_EVENING)
    leisure["A"] = [(6 * H, 8 * H), (20 * H, 22 * H)]
    leisure["D"] = [(19 * H, 21 * H)]
    config = RecommenderConfig(max_leisure_fraction=1.0, max_per_day=9)
    result = recommend(assess(two_groups()), leisure=leisure, config=config)
    proposal = next(p for p in result["proposals"] if {"A", "D"} <= set(p["participants"]))
    assert proposal["start_s"] == 20 * H and proposal["end_s"] == 20 * H + 2700
    assert proposal["window"] == "20:00–20:45"


def test_pairs_without_common_leisure_are_a_schedule_issue_not_a_proposal():
    leisure = {a: [(6 * H, 12 * H)] for a in "ABC"} | {a: [(16 * H, 22 * H)] for a in "DEF"}
    result = recommend(assess(two_groups()), leisure=leisure)
    assert result["proposals"] == []
    assert len(result["schedule_issues"]) == 9
    assert {"pair": ["A", "D"], "reason": "no_common_leisure"} in result["schedule_issues"]


def test_short_leisure_is_not_taken_up_by_activities():
    leisure = dict(ALL_EVENING)
    leisure["F"] = [(20 * H, 21 * H)]  # 1 h: 45 min sería más de un tercio
    weights = matrix({(i, j): 0.6 for i in range(5) for j in range(i + 1, 5)})
    result = recommend(assess(weights), leisure=leisure)
    assert all("F" not in p["participants"] for p in result["proposals"])


def test_pairs_without_data_are_not_opportunities():
    ev = ~np.eye(6, dtype=bool)
    ev[5, :] = ev[:, 5] = False
    assessment = assess(matrix({}, default=0.6), evaluable=ev, node_status=["ok"] * 5 + ["no_data"])
    result = recommend(assessment)
    assert result["proposals"] == []


def test_load_is_spread_over_people_and_capped_per_week():
    assessment = assess(two_groups())
    history: list[dict] = []
    for day in range(1, 8):
        result = recommend(assessment, history=history, target_day=day)
        history += result["proposals"]
    counts = {a: sum(a in p["participants"] for p in history) for a in CREW}
    assert max(counts.values()) <= 2  # tope semanal por persona
    assert min(counts.values()) >= 1  # no recaen siempre en los mismos
    # Con el tope alcanzado deja de proponer, y vuelve cuando pasa la semana
    assert recommend(assessment, history=history, target_day=7)["proposals"] == []
    assert recommend(assessment, history=history, target_day=20)["proposals"]


def test_result_is_deterministic_and_activity_rotates():
    assessment = assess(two_groups())
    first = recommend(assessment)
    assert first == recommend(assessment)
    names = [name for name, sizes in ACTIVITIES if 2 in sizes]
    history: list[dict] = []
    seen = []
    for day in range(1, 30, 8):  # separados más de una semana
        result = recommend(assessment, history=history, target_day=day,
                           config=RecommenderConfig(group_sizes=(2,), max_per_day=1))
        history += result["proposals"]
        seen.append(result["proposals"][0]["activity"])
    assert seen == names[:4]


def test_limits_are_configurable():
    assessment = assess(two_groups())
    assert len(recommend(assessment, config=RecommenderConfig(max_per_day=1))["proposals"]) == 1
    pairs_only = recommend(assessment, config=RecommenderConfig(group_sizes=(2,), max_per_day=3))
    assert [len(p["participants"]) for p in pairs_only["proposals"]] == [2, 2, 2]
    settings = load_settings({"SG_REC_MAX_PER_DAY": "1", "SG_REC_GROUP_SIZES": "2",
                              "SG_REC_MIN_WINDOW_S": "1800"})
    assert settings.recommender == RecommenderConfig(max_per_day=1, group_sizes=(2,), min_window_s=1800)
    with pytest.raises(ValueError):
        load_settings({"SG_REC_GROUP_SIZES": "5"})


def test_service_stores_recommendations_for_the_next_day():
    days = simulate("cliques", 8, analyzer=IsolationAnalyzer(),
                    recommender=CollaborationRecommender())
    last = days[-1]["recommendations"]
    assert last["day"] == days[-1]["day"] + 1
    assert last["proposals"]
    for proposal in last["proposals"]:
        members = set(proposal["participants"])
        assert members & {"A1", "A2", "A3"} and members & {"A4", "A5", "A6"}
    # El historial se respeta entre días: nadie supera el tope semanal
    counts: dict[str, int] = {}
    for d in days:
        for p in d["recommendations"]["proposals"]:
            for a in p["participants"]:
                counts[a] = counts.get(a, 0) + 1
    assert max(counts.values()) <= 3  # 8 días: tope de 2 por ventana de 7
