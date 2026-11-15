"""Grafo diario, layout comparable entre días y exportación para Tierra."""

import json

import numpy as np
import pytest

from conftest import H, apart, run_day, standard_schedule, together
from social_graph.config import load_settings
from social_graph.graph import (
    DISCLAIMER,
    GraphExporter,
    build_graph,
    compute_layout,
    export_graph,
    render_png,
)
from social_graph.isolation import IsolationAnalyzer
from social_graph.params import Params
from social_graph.schedule import FixedSchedule
from social_graph.service import SocialGraphService
from social_graph.simulator import PositionSimulator, SimulationSource, build_scenario
from social_graph.store import MemoryStore

CREW = ["A", "B", "C", "D"]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def positions(t):
    """A y B juntos 2 h; C siempre solo; D sin sensor."""
    p = together(apart(CREW), ["A", "B"]) if 17 * H <= t < 19 * H else apart(CREW)
    p["D"] = None
    return p


@pytest.fixture(scope="module")
def doc() -> dict:
    return run_day(CREW, standard_schedule(CREW), positions).to_dict()


def distances(layout: dict) -> np.ndarray:
    points = np.array(list(layout.values()))
    d = np.linalg.norm(points[:, None] - points[None, :], axis=-1)
    return d[np.triu_indices(len(points), 1)]


def test_graph_contains_every_node_even_isolated(doc):
    graph = build_graph(doc)
    assert list(graph.nodes) == CREW
    assert list(graph.edges) == [("A", "B")]
    assert graph["A"]["B"]["weight"] == pytest.approx(doc["weights"][0][1])
    assert graph.degree("C") == 0 and graph.degree("D") == 0
    assert graph.nodes["D"]["data_status"] == "no_data"


def test_layout_is_deterministic_and_readable(doc):
    graph = build_graph(doc)
    first = compute_layout(graph, seed=42)
    assert first == compute_layout(graph, seed=42)
    assert set(first) == set(CREW)
    assert distances(first).min() >= 0.5 - 1e-3
    assert max(np.hypot(x, y) for x, y in first.values()) <= 1.0 + 1e-3


def test_layout_starts_from_previous_day(doc):
    graph = build_graph(doc)
    day1 = compute_layout(graph, seed=42)
    day2 = compute_layout(graph, previous=day1, seed=42)
    moved = np.mean([np.hypot(day2[n][0] - day1[n][0], day2[n][1] - day1[n][1]) for n in CREW])
    assert moved < 0.15
    # Se parte siempre de posiciones fijas (círculo o día anterior): el resultado
    # no depende del azar
    assert compute_layout(graph, seed=7) == day1


def test_circular_layout_is_fixed(doc):
    graph = build_graph(doc)
    layout = compute_layout(graph, mode="circular")
    assert layout["A"] == [1.0, 0.0]
    assert layout == compute_layout(graph, previous={"A": [0.3, 0.3]}, mode="circular", seed=9)
    with pytest.raises(ValueError):
        compute_layout(graph, mode="espiral")


def test_export_has_nodes_edges_positions_and_metrics(doc):
    layout = compute_layout(build_graph(doc))
    export = export_graph(doc, layout)
    json.dumps(export, allow_nan=False)
    assert export["disclaimer"] == DISCLAIMER and "no es una métrica" in DISCLAIMER
    assert [n["id"] for n in export["nodes"]] == CREW
    node_a = export["nodes"][0]
    assert (node_a["x"], node_a["y"]) == tuple(layout["A"])
    assert node_a["strength"] == pytest.approx(doc["strength"][0])
    assert node_a["strength_norm"] == pytest.approx(doc["strength_norm"][0])
    assert node_a["leisure_h"] == pytest.approx(8.0)
    # A–B, A–C y B–C son evaluables; las parejas con D no tienen datos
    assert {(e["source"], e["target"]) for e in export["edges"]} == {("A", "B"), ("A", "C"), ("B", "C")}
    ab = next(e for e in export["edges"] if e["target"] == "B")
    assert ab["status"] == "interaction" and ab["interaction_min"] == pytest.approx(120.0)
    assert next(e for e in export["edges"] if e["source"] == "B")["status"] == "zero"
    assert {(m["source"], m["target"], m["status"]) for m in export["masked_pairs"]} == {
        ("A", "D", "no_data"), ("B", "D", "no_data"), ("C", "D", "no_data"),
    }
    assert export["nodes"][3]["data_status"] == "no_data"


def test_schedule_mismatch_is_separate_from_weights():
    crew = ["A", "B"]
    aligned = FixedSchedule({a: {"sleep": [(22 * H, 6 * H)], "work": [(8 * H, 16 * H)]} for a in crew})
    shifted = FixedSchedule({
        "A": {"sleep": [(22 * H, 6 * H)], "work": [(8 * H, 16 * H)]},   # ocio 06–08 y 16–22
        "B": {"sleep": [(2 * H, 10 * H)], "work": [(10 * H, 18 * H)]},  # ocio 18–02
    })
    always_together = lambda t: together(apart(crew), crew)
    exports = []
    for schedule in (aligned, shifted):
        d = run_day(crew, schedule, always_together).to_dict()
        exports.append(export_graph(d, compute_layout(build_graph(d))))
    same, different = exports
    assert same["crew"]["schedule_mismatch"] == pytest.approx(0.0)
    assert different["crew"]["schedule_mismatch"] == pytest.approx(0.5)
    assert different["nodes"][0]["schedule_mismatch"] == pytest.approx(0.5)
    # Pasan juntos todo el ocio que comparten: el peso no baja por el desajuste
    assert same["edges"][0]["weight"] == pytest.approx(1.0)
    assert different["edges"][0]["weight"] == pytest.approx(1.0)


def test_png_is_rendered(doc, tmp_path):
    export = export_graph(doc, compute_layout(build_graph(doc)))
    path = tmp_path / "grafo.png"
    render_png(export, path)
    data = path.read_bytes()
    assert data.startswith(PNG_SIGNATURE) and len(data) > 10_000


def test_exporter_writes_daily_and_latest_files(doc, tmp_path):
    exporter = GraphExporter(tmp_path / "salida")
    export = exporter.export(doc)
    names = sorted(p.name for p in (tmp_path / "salida").iterdir())
    assert names == ["day_0000.json", "day_0000.png", "latest.json", "latest.png"]
    assert json.loads((tmp_path / "salida" / "latest.json").read_text(encoding="utf-8")) == export


def test_exporter_without_output_dir_writes_nothing(doc, tmp_path):
    export = GraphExporter(None).export(doc)
    assert export["day"] == 0
    assert list(tmp_path.iterdir()) == []


def test_service_stores_graph_with_isolation_status_and_stable_positions(tmp_path):
    crew = ["A1", "A2", "A3", "A4", "A5", "A6"]
    scenario = build_scenario("low_integration", crew, 1)
    source = SimulationSource(PositionSimulator(scenario, 1), 60.0, 0, n_days=9, idle=False)
    store = MemoryStore()
    SocialGraphService(
        crew, scenario.schedule, Params(max_gap_s=120.0), source, store,
        analyzer=IsolationAnalyzer(), exporter=GraphExporter(tmp_path, render=False),
    ).run()
    days = store.load_days()
    assert len(days) == 9 and all("graph" in d for d in days)
    last = days[-1]["graph"]
    target = next(n for n in last["nodes"] if n["id"] == "A6")
    assert target["status"] in ("follow_up", "review")
    assert "low_vs_crew" in target["signals"]
    assert (tmp_path / "day_0008.json").exists() and not (tmp_path / "latest.png").exists()
    moves = []
    for before, after in zip(days, days[1:]):
        a = np.array([[n["x"], n["y"]] for n in before["graph"]["nodes"]])
        b = np.array([[n["x"], n["y"]] for n in after["graph"]["nodes"]])
        moves.append(np.linalg.norm(a - b, axis=1).mean())
    assert np.mean(moves) < 0.3


def test_layout_configuration():
    settings = load_settings({"SG_LAYOUT": "circular", "SG_LAYOUT_SEED": "7", "SG_OUTPUT_DIR": "/data"})
    assert (settings.layout, settings.layout_seed, settings.output_dir) == ("circular", 7, "/data")
    assert load_settings({}).output_dir is None
    with pytest.raises(ValueError):
        load_settings({"SG_LAYOUT": "espiral"})
