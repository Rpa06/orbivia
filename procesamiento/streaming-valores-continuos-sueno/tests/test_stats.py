"""Acumuladores: exactitud frente al cálculo directo y fusión correcta."""

import math
import random
import statistics

import pytest

from sleep_stream.config import MetricSpec
from sleep_stream.stats import Agg, Ewma, Trend

SPEC = MetricSpec("heart_rate", "bpm", 20.0, 250.0, 30.0, 130.0, 100, 1.0)


def fill(values, spec=SPEC, t0=0.0):
    agg = Agg()
    for k, value in enumerate(values):
        agg.add(value, t0 + k, spec)
    return agg


def sample(n, seed=1):
    rng = random.Random(seed)
    return [round(rng.gauss(60.0, 5.0), 1) for _ in range(n)]


def test_welford_matches_direct_computation():
    values = sample(5000)
    agg = fill(values)
    assert agg.n == 5000
    assert agg.mean == pytest.approx(statistics.fmean(values), rel=1e-12)
    assert agg.variance == pytest.approx(statistics.variance(values), rel=1e-10)
    assert (agg.min, agg.max) == (min(values), max(values))
    assert (agg.first, agg.last) == (values[0], values[-1])


def test_variance_is_stable_with_large_offset():
    # La suma de cuadrados sin centrar perdería precisión aquí
    values = [1e9 + x for x in (0.1, 0.2, 0.3, 0.4, 0.5)] * 200
    assert fill(values, spec=None).variance == pytest.approx(statistics.variance(values), rel=1e-6)


def test_merge_equals_seeing_everything_together():
    values = sample(3000, seed=2)
    whole = fill(values)
    rng = random.Random(3)
    cuts = sorted(rng.sample(range(1, 3000), 9))
    merged = Agg()
    for begin, end in zip([0, *cuts], [*cuts, 3000]):
        merged.merge(fill(values[begin:end], t0=begin))
    assert merged.n == whole.n
    assert merged.mean == pytest.approx(whole.mean, rel=1e-12)
    assert merged.variance == pytest.approx(whole.variance, rel=1e-10)
    assert (merged.min, merged.max, merged.first, merged.last) == (whole.min, whole.max, whole.first, whole.last)
    assert merged.hist == whole.hist


def test_merged_mean_is_not_the_mean_of_means():
    small, big = fill([100.0]), fill([50.0] * 99, t0=10)
    merged = Agg()
    merged.merge(small)
    merged.merge(big)
    assert merged.mean == pytest.approx(50.5)
    assert merged.mean != pytest.approx((small.mean + big.mean) / 2)


def test_merge_order_does_not_matter():
    parts = [fill(sample(50, seed=s), t0=100 * s) for s in range(6)]
    forward, backward = Agg(), Agg()
    for part in parts:
        forward.merge(part)
    for part in reversed(parts):
        backward.merge(part)
    assert backward.mean == pytest.approx(forward.mean, rel=1e-12)
    assert backward.m2 == pytest.approx(forward.m2, rel=1e-10)
    assert (backward.first, backward.last) == (forward.first, forward.last)


def test_first_and_last_follow_time_not_arrival():
    agg = Agg()
    for ts, value in ((30, 3.0), (10, 1.0), (20, 2.0)):
        agg.add(value, ts)
    assert (agg.first, agg.last) == (1.0, 3.0)


def test_missing_and_invalid_are_not_observations():
    agg = fill([60.0, 62.0])
    agg.missing += 3
    agg.invalid += 1
    other = Agg()
    other.missing += 2
    agg.merge(other)
    stats = agg.stats(SPEC)
    assert stats["valid_count"] == 2 and stats["missing_count"] == 5 and stats["invalid_count"] == 1
    assert stats["mean"] == pytest.approx(61.0)


def test_empty_aggregate_reports_none_not_zero():
    stats = Agg().stats(SPEC)
    assert stats["mean"] is None and stats["std"] is None and stats["median"] is None


def test_quantiles_within_one_bin_of_exact():
    values = sample(20000, seed=5)
    agg = fill(values)
    ordered = sorted(values)
    for q in (0.05, 0.5, 0.95):
        exact = ordered[int(q * len(ordered))]
        assert abs(agg.quantile(q, SPEC) - exact) <= SPEC.bin_width


def test_roundtrip_through_json_is_exact():
    import json

    agg = fill(sample(777, seed=8))
    copy = Agg.load(json.loads(json.dumps(agg.dump())))
    assert copy.dump() == agg.dump()


def test_trend_matches_least_squares_in_any_order():
    rng = random.Random(4)
    points = [(t, 70.0 + 0.002 * t + rng.gauss(0, 1)) for t in range(0, 28800, 30)]
    mean_t = statistics.fmean(t for t, _ in points)
    mean_x = statistics.fmean(x for _, x in points)
    exact = sum((t - mean_t) * (x - mean_x) for t, x in points) / sum((t - mean_t) ** 2 for t, _ in points)
    rng.shuffle(points)
    trend = Trend()
    for t, x in points:
        trend.add(t, x)
    assert trend.slope == pytest.approx(exact, rel=1e-9)
    assert Trend(trend.dump()).slope == trend.slope


def test_trend_needs_time_span():
    trend = Trend()
    trend.add(5.0, 1.0)
    assert trend.slope is None


def run_ewma(values, period=1.0):
    """Devuelve la referencia y las z de cada valor, como hace el motor."""
    ewma, scores = Ewma(), []
    for k, value in enumerate(values):
        scores.append(ewma.zscore(value, 1.0, 30, 600.0))
        ewma.update(value, k * period, 1.0, 600.0, 30, 600.0, 4.0)
    return ewma, scores


def test_ewma_does_not_score_during_warmup():
    _, scores = run_ewma([60.0] * 700)
    assert all(z is None for z in scores[:601])
    assert all(z is not None for z in scores[601:])


def test_ewma_flags_a_spike_but_follows_slow_drift():
    values = [60.0 - 0.002 * t + math.sin(t / 7.0) for t in range(3600)]  # deriva lenta con oscilación
    ewma, scores = run_ewma(values)
    assert not any(z is not None and abs(z) > 4 for z in scores)
    assert abs(ewma.zscore(110.0, 1.0, 30, 600.0)) > 4


def test_ewma_spike_does_not_mask_the_next_one():
    rng = random.Random(6)
    values = [60.0 + rng.gauss(0, 1) for _ in range(3000)]
    for k in (1500, 1501, 1502, 1700):
        values[k] = 110.0
    _, scores = run_ewma(values)
    assert all(abs(scores[k]) > 4 for k in (1500, 1501, 1502, 1700))
    # Tras el primer pico la referencia no se ha desplazado ni ensanchado apenas
    assert not any(abs(z) > 4 for z in scores[1503:1700])


def test_ewma_ignores_late_values():
    ewma, _ = run_ewma([60.0] * 100)
    before = ewma.dump()
    ewma.update(200.0, 50, 1.0, 600.0, 30, 600.0, 4.0)
    assert ewma.dump() == before
