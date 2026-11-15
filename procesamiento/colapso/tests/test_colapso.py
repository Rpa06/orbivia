import math
import random
import statistics
from datetime import date, timedelta

import pytest

from colapso.builder import build_vector
from colapso.stats import (
    Baseline, Welford, baseline_from, choose_baseline, forward_fill, rolling_slope, window_stats, zscore,
)
from colapso.vector import (
    FIELDS, N_FIELDS, VECTOR_BYTES, CollapsedVector, VectorError, deterioration, from_named,
    missing_mask, pack, schema_document, unpack,
)

D0 = date(2026, 11, 1)


# --- vector ----------------------------------------------------------------------------


def test_vector_is_exactly_80_bytes_of_float32():
    v = CollapsedVector("AST-01", "2026-11-14", tuple(float(i) / 10 for i in range(20)))
    data = v.to_bytes()
    assert len(data) == VECTOR_BYTES == 80 and N_FIELDS == 20
    assert unpack(data) == v.values


def test_vector_rejects_wrong_length_and_bad_values():
    with pytest.raises(VectorError):
        CollapsedVector("AST-01", "2026-11-14", (0.0,) * 19)
    with pytest.raises(VectorError):
        unpack(b"\x00" * 79)
    with pytest.raises(VectorError):
        CollapsedVector("AST-01", "2026-11-14", (math.inf,) + (0.0,) * 19)


def test_missing_values_are_nan_and_masked():
    v = from_named("AST-01", "2026-11-14", {"pvt_rt_z": 1.5})
    assert v.missing_mask == (2**20 - 1) & ~(1 << 1)
    assert v.as_dict()["pvt_rt_z"] == pytest.approx(1.5)
    assert v.as_dict()["sleep_duration_z"] is None
    assert len(v.to_bytes()) == 80
    assert v.embedding()[0] == 0.0


def test_metadata_is_outside_the_vector():
    doc = schema_document()
    assert doc["bytes"] == 80 and len(doc["fields"]) == 20
    assert {"astronaut_id", "cycle_date", "schema_version"} <= set(doc["external_metadata"])
    assert "astronaut_id" not in {f["name"] for f in doc["fields"]}


def test_schema_covers_required_signals():
    names = [f.name for f in FIELDS]
    assert sum(n.startswith("checkin_") for n in names) == 5
    assert sum(n.startswith("nlp_") for n in names) == 4
    assert sum(n.startswith("acoustic_") for n in names) == 2
    for required in ("sleep_duration_z", "pvt_rt_z", "self_perception_gap",
                     "social_centrality_z", "circadian_desync_z"):
        assert required in names


def test_deterioration_direction():
    higher_better = FIELDS[0]
    lower_better = FIELDS[1]
    two_sided = next(f for f in FIELDS if f.direction == 0)
    assert deterioration(higher_better, -2.0) == 2.0
    assert deterioration(lower_better, 2.0) == 2.0
    assert deterioration(two_sided, -1.5) == 1.5


# --- Welford -----------------------------------------------------------------------------


def test_welford_matches_two_pass_statistics():
    rng = random.Random(7)
    data = [rng.gauss(50, 7) for _ in range(500)]
    acc = Welford()
    for x in data:
        acc = acc.add(x)
    assert acc.n == 500
    assert acc.mean == pytest.approx(statistics.fmean(data), rel=1e-12)
    assert acc.sd == pytest.approx(statistics.stdev(data), rel=1e-10)


def test_welford_merge_equals_sequential():
    data = [float(x) for x in range(1, 41)]
    a, b, full = Welford(), Welford(), Welford()
    for x in data[:15]:
        a = a.add(x)
    for x in data[15:]:
        b = b.add(x)
    for x in data:
        full = full.add(x)
    merged = a.merge(b)
    assert merged.n == full.n and merged.mean == pytest.approx(full.mean)
    assert merged.variance == pytest.approx(full.variance)


def test_welford_does_not_count_the_same_cycle_twice():
    acc = Welford().add(10.0, on=D0).add(12.0, on=D0 + timedelta(days=1))
    again = acc.add(99.0, on=D0 + timedelta(days=1))  # re-ejecución del mismo ciclo
    older = acc.add(99.0, on=D0)
    assert again == acc and older == acc and acc.n == 2


def test_each_astronaut_keeps_its_own_baseline():
    a = baseline_from([40, 42, 44, 41, 43])
    b = baseline_from([30, 31, 29, 30, 32])
    assert zscore(42, a) == pytest.approx(0.0, abs=0.01)
    assert zscore(42, b) > 5
    assert a.p05 <= a.p50 <= a.p95


def test_adaptation_baseline_only_after_adaptation_days():
    terr, adapt = Baseline(10, 1), Baseline(8, 1, kind="adaptation")
    assert choose_baseline(terr, adapt, mission_day=5, adaptation_days=10) is terr
    assert choose_baseline(terr, adapt, mission_day=11, adaptation_days=10) is adapt
    assert choose_baseline(terr, adapt, mission_day=11, adaptation_days=0) is terr  # misión muy corta


# --- series ----------------------------------------------------------------------------


def test_rolling_slope_and_windows():
    series = {D0 + timedelta(days=k): 0.5 * k for k in range(30)}
    slope, n = rolling_slope([(k, 0.5 * k) for k in range(14)])
    assert slope == pytest.approx(0.5) and n == 14
    for days in (7, 14, 30):
        stats = window_stats(series, D0 + timedelta(days=29), days)
        assert stats["n"] == days and stats["slope"] == pytest.approx(0.5)


def test_forward_fill_respects_seven_days():
    obs = {D0: 3.0}
    assert forward_fill(obs, D0 + timedelta(days=7), 7).value == 3.0
    late = forward_fill(obs, D0 + timedelta(days=8), 7)
    assert math.isnan(late.value) and late.protocol_warning
    assert forward_fill(obs, D0 - timedelta(days=1), 7).measured_on is None  # nunca el futuro


def test_daily_variables_are_not_carried():
    obs = {D0: 7.5}
    assert forward_fill(obs, D0, 0).value == 7.5
    assert math.isnan(forward_fill(obs, D0 + timedelta(days=1), 0).value)


# --- builder ---------------------------------------------------------------------------


def _baselines():
    return {
        "sleep_duration_h": (Baseline(7.0, 0.5), None),
        "pvt_mean_rt_ms": (Baseline(250, 20), None),
        "checkin.fatigue": (Baseline(2.0, 0.5), None),
    }


def test_builder_daily_cycles_do_not_mix():
    raw = {
        "sleep_duration_h": {D0: 6.0, D0 + timedelta(days=1): 7.0},
        "pvt_mean_rt_ms": {D0: 290},
        "checkin.fatigue": {D0: 2.0},
    }
    day1 = build_vector("AST-01", D0, 20, 10, raw, _baselines()).vector.as_dict()
    day2 = build_vector("AST-01", D0 + timedelta(days=1), 21, 10, raw, _baselines()).vector.as_dict()
    assert day1["sleep_duration_z"] == pytest.approx(-2.0)
    assert day2["sleep_duration_z"] == pytest.approx(0.0)
    assert day2["pvt_rt_z"] is None  # el PVT de ayer no vale hoy


def test_self_perception_gap():
    raw = {"pvt_mean_rt_ms": {D0: 310}, "checkin.fatigue": {D0: 2.0}}  # rinde 3σ peor, declara normal
    result = build_vector("AST-01", D0, 20, 10, raw, _baselines())
    assert result.vector.as_dict()["self_perception_gap"] == pytest.approx(3.0)


def test_media_scores_carry_for_the_interview_interval():
    media = {"nlp_low_mood_z": {D0: 1.2}}
    on_day_3 = build_vector("AST-01", D0 + timedelta(days=3), 20, 10, {}, {}, media, media_carry_days=3)
    on_day_4 = build_vector("AST-01", D0 + timedelta(days=4), 20, 10, {}, {}, media, media_carry_days=3)
    assert on_day_3.vector.as_dict()["nlp_low_mood_z"] == pytest.approx(1.2)
    assert on_day_4.vector.as_dict()["nlp_low_mood_z"] is None


def test_simulated_mask_marks_simulated_sources():
    raw = {"sleep_duration_h": {D0: 7.0}}
    result = build_vector("AST-01", D0, 20, 10, raw, _baselines(), simulated_sources={"sleep_duration_h"})
    assert result.vector.simulated_mask == 1
    assert missing_mask(result.vector.values) & 1 == 0
    assert len(pack(result.vector.values)) == 80
