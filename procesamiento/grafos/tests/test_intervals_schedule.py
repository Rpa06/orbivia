import pytest

from conftest import H, STANDARD
from social_graph.intervals import clip, complement, intersect, normalize, total, union
from social_graph.schedule import (
    FixedSchedule,
    day_index,
    day_window,
    leisure,
    leisure_time,
    split_by_day,
)

CUTOFF = 4 * H


def test_normalize_merges_overlaps_and_drops_empty():
    assert normalize([(5, 7), (0, 2), (1, 3), (3, 4), (9, 9), (8, 6)]) == [(0, 4), (5, 7)]


def test_total_does_not_double_count_overlaps():
    assert total([(0, 10), (5, 15)]) == 15


def test_intersect_and_complement():
    assert intersect([(0, 5), (8, 12)], [(3, 9), (11, 20)]) == [(3, 5), (8, 9), (11, 12)]
    assert complement([(2, 4), (6, 20)], (0, 10)) == [(0, 2), (4, 6)]
    assert clip([(0, 10)], 3, 5) == [(3, 5)]
    assert union([(0, 1)], [(1, 2)]) == [(0, 2)]


def test_day_index_and_window_respect_cutoff():
    assert day_index(3.9 * H, CUTOFF) == -1
    assert day_index(4 * H, CUTOFF) == 0
    assert day_window(0, CUTOFF) == (4 * H, 28 * H)


def test_split_by_day_preserves_duration():
    pieces = list(split_by_day(27 * H, 29 * H, CUTOFF))
    assert pieces == [(0, 27 * H, 28 * H), (1, 28 * H, 29 * H)]


def test_sleep_crossing_midnight_is_not_double_counted():
    schedule = FixedSchedule({"A": STANDARD})
    for day in (0, 1, 5):
        window = day_window(day, CUTOFF)
        assert total(schedule.sleep("A", window)) == pytest.approx(8 * H)
        assert leisure_time(schedule, "A", window) == pytest.approx(8 * H)


def test_leisure_is_set_complement_when_sleep_and_work_overlap():
    # Sueño 22–06 y trabajo 05–13 se solapan 1 h. La resta daría 24−8−8 = 8 h;
    # el ocio real son 9 h.
    schedule = FixedSchedule({"A": {"sleep": [(22 * H, 6 * H)], "work": [(5 * H, 13 * H)]}})
    assert leisure_time(schedule, "A", day_window(0, CUTOFF)) == pytest.approx(9 * H)


def test_leisure_intervals_with_midnight_cutoff():
    schedule = FixedSchedule({"A": STANDARD})
    window = day_window(0, 0.0)
    assert leisure(schedule, "A", window) == [(6 * H, 8 * H), (16 * H, 22 * H)]


def test_jitter_is_deterministic_and_bounded():
    a = FixedSchedule({"A": STANDARD}, jitter_s=1800, seed=7)
    b = FixedSchedule({"A": STANDARD}, jitter_s=1800, seed=7)
    c = FixedSchedule({"A": STANDARD}, jitter_s=1800, seed=8)
    window = day_window(3, CUTOFF)
    assert a.work("A", window) == b.work("A", window)
    assert a.work("A", window) != c.work("A", window)
    start, end = a.work("A", window)[0]
    assert end - start == pytest.approx(8 * H)
    assert abs(start - (3 * 24 * H + 8 * H)) <= 1800


def test_unknown_block_kind_is_rejected():
    with pytest.raises(ValueError):
        FixedSchedule({"A": {"ocio": [(0, H)]}})
