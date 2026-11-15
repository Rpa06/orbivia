"""Estructura de la red sobre grafos simulados: grupos, puentes y cambios progresivos."""

import numpy as np
import pytest

from social_graph.graph import build_graph, compute_layout, export_graph
from social_graph.isolation import (
    REVIEW,
    STRUCTURAL,
    IsolationAnalyzer,
    IsolationConfig,
    network_structure,
)
from test_isolation import make_doc
from test_simulator import simulate

CREW = ["A", "B", "C", "D", "E", "F"]
CONFIG = IsolationConfig()


def matrix(edges: dict[tuple[int, int], float], n: int = 6, default: float = 0.0) -> np.ndarray:
    w = np.full((n, n), default)
    np.fill_diagonal(w, 0)
    for (i, j), value in edges.items():
        w[i, j] = w[j, i] = value
    return w


def two_groups(across: float = 0.0, bridge: float | None = None) -> np.ndarray:
    """{A, B, C} y {D, E, F} muy unidos por dentro; `bridge` es el peso C–D."""
    edges = {(i, j): 0.8 for i, j in [(0, 1), (0, 2), (1, 2), (3, 4), (3, 5), (4, 5)]}
    for i in range(3):
        for j in range(3, 6):
            edges[(i, j)] = across
    if bridge is not None:
        edges[(2, 3)] = bridge
    return matrix(edges)


def structure_of(weights, n=6, evaluable=None) -> dict:
    doc = make_doc(0, weights, evaluable=evaluable)
    doc["crew"] = CREW[:n]
    return IsolationAnalyzer().analyze([doc])[-1]["structure"]


def test_isolated_groups_form_two_communities():
    s = structure_of(two_groups())
    assert s["communities"] == [["A", "B", "C"], ["D", "E", "F"]]
    assert s["clear"] is True
    assert s["modularity"] == pytest.approx(0.5)
    assert s["between_communities"] == [{"a": 0, "b": 1, "mean_weight": 0.0}]
    assert s["bridges"] == [] and s["isolated"] == []
    assert all(v == 0 for v in s["betweenness"].values())


def test_bridge_between_groups_is_identified():
    s = structure_of(two_groups(bridge=0.3))
    assert s["communities"] == [["A", "B", "C"], ["D", "E", "F"]]
    assert s["clear"] is True
    assert s["bridges"] == ["C", "D"]
    # Todos los caminos entre grupos pasan por C y D
    assert s["betweenness"]["C"] == s["betweenness"]["D"] > 0
    assert s["betweenness"]["A"] == 0
    assert s["between_communities"][0]["mean_weight"] == pytest.approx(0.3 / 9)


def test_weak_links_between_groups_do_not_merge_them():
    s = structure_of(two_groups(across=0.12))
    assert s["communities"] == [["A", "B", "C"], ["D", "E", "F"]]
    assert s["clear"] is True
    assert s["between_communities"][0]["mean_weight"] == pytest.approx(0.12)
    assert set(s["bridges"]) == set(CREW)  # todos tienen algún lazo débil con el otro grupo


def test_homogeneous_graph_has_no_clear_groups():
    s = structure_of(matrix({}, default=0.5))
    assert s["clear"] is False
    assert s["modularity"] == pytest.approx(0.0, abs=1e-9)
    assert s["bridges"] == []
    # Grafo denso: todos los caminos son directos y la intermediación no informa
    assert all(v == 0 for v in s["betweenness"].values())


def test_links_below_threshold_are_not_edges():
    s = structure_of(matrix({}, default=0.05))
    assert s["communities"] == [] and s["modularity"] is None and s["clear"] is False
    assert s["isolated"] == CREW


def test_astronaut_with_few_relations():
    # F solo se relaciona, y poco, con E
    weights = matrix({(i, j): 0.6 for i in range(5) for j in range(i + 1, 5)})
    weights[4, 5] = weights[5, 4] = 0.15
    doc = make_doc(0, weights)
    doc["crew"] = CREW
    result = IsolationAnalyzer().analyze([doc])[-1]
    f = result["astronauts"]["F"]["indicators"]
    assert f["degree"]["value"] == pytest.approx(1 / 5)
    assert f["diversity"]["value"] == pytest.approx(1 / 5)  # todo su tiempo con una persona
    assert result["astronauts"]["A"]["indicators"]["degree"]["value"] == pytest.approx(4 / 5)
    assert STRUCTURAL not in result["astronauts"]["F"]["signals"]  # tiene una arista


def test_disconnected_astronaut_is_structural_isolation_only_if_a_network_exists():
    connected = matrix({(i, j): 0.6 for i in range(5) for j in range(i + 1, 5)})
    doc = make_doc(0, connected)
    doc["crew"] = CREW
    result = IsolationAnalyzer().analyze([doc])[-1]
    assert result["structure"]["isolated"] == ["F"]
    assert result["astronauts"]["F"]["status"] == REVIEW
    assert STRUCTURAL in result["astronauts"]["F"]["signals"]
    assert STRUCTURAL not in result["astronauts"]["A"]["signals"]

    # Si nadie tiene aristas no es algo individual
    nobody = make_doc(0, matrix({}, default=0.05))
    nobody["crew"] = CREW
    result = IsolationAnalyzer().analyze([nobody])[-1]
    assert all(STRUCTURAL not in a["signals"] for a in result["astronauts"].values())


def test_never_evaluable_astronaut_is_unknown_not_isolated():
    ev = ~np.eye(6, dtype=bool)
    ev[5, :] = ev[:, 5] = False
    doc = make_doc(0, matrix({}, default=0.5), evaluable=ev,
                   node_status=["ok"] * 5 + ["no_data"])
    doc["crew"] = CREW
    result = IsolationAnalyzer().analyze([doc])[-1]
    assert result["structure"]["unknown"] == ["F"]
    assert result["structure"]["isolated"] == []
    assert "F" not in result["structure"]["betweenness"]
    assert result["astronauts"]["F"]["signals"] == []


def test_structure_uses_the_smoothed_graph_so_changes_are_progressive():
    """Dos grupos que se mezclan a partir del día 10: la estructura cambia poco a poco."""
    docs = []
    for day in range(20):
        weights = two_groups() if day < 10 else matrix({}, default=0.6)
        doc = make_doc(day, weights)
        doc["crew"] = CREW
        docs.append(doc)
    result = IsolationAnalyzer().analyze(docs)
    clear = [r["structure"]["clear"] for r in result]
    between = [r["structure"]["between_communities"] for r in result]
    assert all(clear[:10])
    assert clear[10] is True  # un solo día mezclados no deshace los grupos
    assert not any(clear[16:])  # tras 7 días el grafo suavizado ya es homogéneo
    first_change = clear.index(False)
    assert 11 <= first_change <= 16
    mean_between = [b[0]["mean_weight"] for b in between[9:first_change]]
    assert mean_between == sorted(mean_between) and mean_between[0] == 0.0


def test_progressive_loss_of_links_ends_in_structural_isolation():
    docs = []
    for day in range(20):
        weights = matrix({}, default=0.6)
        fade = max(0.0, 0.6 - 0.06 * max(0, day - 4))  # F pierde peso con todos
        weights[5, :] = weights[:, 5] = fade
        np.fill_diagonal(weights, 0)
        doc = make_doc(day, weights, accompanied=[0.5] * 5 + [fade])
        doc["crew"] = CREW
        docs.append(doc)
    result = IsolationAnalyzer().analyze(docs)
    isolated = [STRUCTURAL in r["astronauts"]["F"]["signals"] for r in result]
    assert not any(isolated[:12])
    assert all(isolated[-2:])
    assert result[-1]["astronauts"]["F"]["status"] == REVIEW
    assert all(STRUCTURAL not in r["astronauts"]["A"]["signals"] for r in result)


def test_modularity_threshold_is_configurable():
    doc = make_doc(0, two_groups())
    doc["crew"] = CREW
    strict = IsolationAnalyzer(IsolationConfig(min_modularity=0.9)).analyze([doc])[-1]
    assert strict["structure"]["clear"] is False
    assert strict["structure"]["communities"]  # se calculan, pero no se dan por claras


def test_simulated_cliques_and_homogeneous_crews():
    cliques = simulate("cliques", 7, analyzer=IsolationAnalyzer())[-1]["isolation"]["structure"]
    assert cliques["clear"] is True
    assert cliques["communities"] == [["A1", "A2", "A3"], ["A4", "A5", "A6"]]
    assert cliques["between_communities"][0]["mean_weight"] < 0.1
    homogeneous = simulate("homogeneous", 7, analyzer=IsolationAnalyzer())[-1]["isolation"]["structure"]
    assert homogeneous["clear"] is False


def test_export_carries_communities_and_bridges():
    doc = simulate("cliques", 7, analyzer=IsolationAnalyzer())[-1]
    export = export_graph(doc, compute_layout(build_graph(doc)))
    assert [n["community"] for n in export["nodes"]] == [0, 0, 0, 1, 1, 1]
    assert export["crew"]["communities"] == [["A1", "A2", "A3"], ["A4", "A5", "A6"]]
    assert export["crew"]["modularity"] > 0.2
    assert all(isinstance(n["bridge"], bool) for n in export["nodes"])
