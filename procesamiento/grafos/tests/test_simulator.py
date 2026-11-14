"""Simulador: determinismo, reanudación y propiedades de cada escenario."""

import warnings

import numpy as np
import pytest

from social_graph.params import Params
from social_graph.service import SocialGraphService
from social_graph.simulator import (
    SCENARIOS,
    PositionSimulator,
    SimulationSource,
    build_scenario,
)
from social_graph.store import MemoryStore
from social_graph.validation import parse_sample

CREW = ["A1", "A2", "A3", "A4", "A5", "A6"]
H = 3600.0
PERIOD = 60.0
PARAMS = Params(max_gap_s=120.0)


def simulate(name: str, days: int, seed: int = 1, analyzer=None) -> list[dict]:
    scenario = build_scenario(name, CREW, seed)
    source = SimulationSource(PositionSimulator(scenario, seed), PERIOD, 0, n_days=days, idle=False)
    store = MemoryStore()
    SocialGraphService(CREW, scenario.schedule, PARAMS, source, store, analyzer=analyzer).run()
    return store.load_days()


def mean_matrix(days: list[dict], key: str) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # la diagonal no está definida
        return np.nanmean([np.array(d[key], dtype=float) for d in days], axis=0)


@pytest.fixture(scope="module")
def short_runs() -> dict[str, list[dict]]:
    return {name: simulate(name, days=4) for name in SCENARIOS if name != "sensor_loss"}


def test_same_seed_gives_same_samples_in_any_order():
    a = PositionSimulator(build_scenario("homogeneous", CREW, 5), 5)
    b = PositionSimulator(build_scenario("homogeneous", CREW, 5), 5)
    times = [18 * H + k * 10 for k in range(200)]
    forward = [a.sample(t) for t in times]
    backward = [b.sample(t) for t in reversed(times)][::-1]
    assert forward == backward


def test_different_seed_gives_different_samples():
    a = PositionSimulator(build_scenario("homogeneous", CREW, 5), 5)
    b = PositionSimulator(build_scenario("homogeneous", CREW, 6), 6)
    assert a.sample(18 * H) != b.sample(18 * H)


def test_samples_are_valid_messages():
    simulator = PositionSimulator(build_scenario("sensor_loss", CREW, 1), 1)
    for k in range(300):
        sample, issues = parse_sample(simulator.sample(12 * 24 * H + 17 * H + k * 60), CREW)
        assert sample is not None and issues == []


def test_nobody_is_close_while_sleeping_or_working():
    simulator = PositionSimulator(build_scenario("simultaneous", CREW, 1), 1)
    for t in (2 * H, 3 * H, 10 * H, 14 * H):  # sueño y trabajo
        positions = simulator.positions(t)
        points = np.array([positions[a] for a in CREW])
        distances = np.linalg.norm(points[:, None] - points[None, :], axis=-1)
        assert distances[~np.eye(len(CREW), dtype=bool)].min() > 5.0


def test_source_resumes_exactly_after_cursor():
    simulator = PositionSimulator(build_scenario("homogeneous", CREW, 1), 1)
    full = list(SimulationSource(simulator, 10.0, 0, n_days=1, idle=False).stream(None))
    assert len(full) == 8641
    assert full[0][1]["t"] == 4 * H
    cursor = {"id": full[4999][0], "t": full[4999][1]["t"]}
    resumed = list(SimulationSource(simulator, 10.0, 0, n_days=1, idle=False).stream(cursor))
    assert resumed == full[5000:]


def test_source_paces_with_speedup_and_idles_when_finished():
    simulator = PositionSimulator(build_scenario("homogeneous", CREW, 1), 1)
    sleeps = []
    source = SimulationSource(simulator, 10.0, speedup=3600.0, n_days=0, sleep=sleeps.append)
    stream = source.stream(None)
    assert next(stream) is not None
    assert next(stream) is None  # simulación terminada: pausa
    assert sleeps[0] == pytest.approx(10.0 / 3600.0)


def test_service_restart_in_simulation_matches_uninterrupted_run():
    reference = simulate("cliques", days=3)
    scenario = build_scenario("cliques", CREW, 1)
    store = MemoryStore()

    def service():
        source = SimulationSource(PositionSimulator(scenario, 1), PERIOD, 0, n_days=3, idle=False)
        return SocialGraphService(CREW, scenario.schedule, PARAMS, source, store)

    count = iter(range(10**6))
    service().run(should_stop=lambda: next(count) >= 2000)  # se detiene a mitad del día 1
    assert len(store.load_days()) == 1
    service().run()
    assert store.load_days() == reference


def test_unknown_scenario():
    with pytest.raises(ValueError):
        build_scenario("fiesta", CREW)


def test_every_scenario_produces_valid_matrices(short_runs):
    for name, days in short_runs.items():
        assert len(days) == 4, name
        for doc in days:
            w = np.array(doc["weights"])
            assert np.array_equal(w, w.T), name
            assert np.all(np.diag(w) == 0), name
            assert np.all((w >= 0) & (w <= 1)), name
            assert doc["quality"]["bound_violations"] == 0, name
            c = np.array(doc["accompanied"], dtype=float)
            assert np.all((c[~np.isnan(c)] >= 0) & (c[~np.isnan(c)] <= 1)), name


def test_homogeneous_crew_has_similar_strengths(short_runs):
    strength = np.mean([d["strength_norm"] for d in short_runs["homogeneous"]], axis=0)
    assert strength.min() > 0.25
    assert strength.max() / strength.min() < 1.6


def test_low_integration_astronaut_has_lowest_strength(short_runs):
    strength = np.mean([d["strength_norm"] for d in short_runs["low_integration"]], axis=0)
    assert np.argmin(strength) == 5
    assert strength[5] < 0.5 * np.median(strength[:5])


def test_cliques_interact_within_groups(short_runs):
    w = mean_matrix(short_runs["cliques"], "weights")
    within = np.mean([w[0, 1], w[0, 2], w[1, 2], w[3, 4], w[3, 5], w[4, 5]])
    across = w[:3, 3:].mean()
    assert within > 0.5
    assert across < 0.1


def test_simultaneous_interactions_count_for_all_pairs(short_runs):
    doc = short_runs["simultaneous"][0]
    interaction = np.array(doc["interaction_s"])
    # Con todos juntos, la suma de tiempos por pareja supera el ocio de una persona
    assert interaction[0].sum() > doc["leisure_s"][0]
    assert np.all(interaction[np.triu_indices(6, 1)] > 2 * H)
    assert max(doc["accompanied"]) <= 1.0


def test_unequal_leisure_stays_bounded(short_runs):
    doc = short_runs["unequal_leisure"][1]
    leisure = np.array(doc["leisure_s"])
    assert leisure[0] > 2 * leisure[-1]
    for key in ("r_overlap", "r_leisure"):
        r = np.array(doc[key], dtype=float)
        assert np.nanmax(r) <= 1.0 and np.nanmin(r) >= 0.0
    # Por ocio individual, quien tiene menos ocio parece menos relacionado; por solape no
    assert np.array(doc["alignment"], dtype=float)[0, 5] < 0.7


def test_shifted_schedules_lower_alignment_not_affinity(short_runs):
    days = short_runs["shifted_schedules"]
    alignment = mean_matrix(days, "alignment")
    r_overlap = mean_matrix(days, "r_overlap")
    assert alignment[0, 1] > 0.9
    assert alignment[:3, 3:].mean() < 0.5
    # La conducta es la misma: R por solape es parecido dentro y entre turnos
    within = np.mean([r_overlap[0, 1], r_overlap[0, 2], r_overlap[1, 2]])
    across = r_overlap[:3, 3:].mean()
    assert across == pytest.approx(within, rel=0.5)
    assert all(status == "ok" for status in days[0]["node_status"])
