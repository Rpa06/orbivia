"""Historial de asignaciones."""

import pytest

from crew_planner.history import History, HistoryEntry
from crew_planner.model import ValidationError


def entry(day, astronaut="A1", task="T1", **kw):
    return HistoryEntry(day=day, astronaut=astronaut, task_id=task, category=kw.pop("category", task),
                        duration_min=kw.pop("duration_min", 60), **kw)


def test_window_and_order():
    history = History([entry(5), entry(1), entry(9, "A2"), entry(10)])
    assert [e.day for e in history.before(10)] == [1, 5, 9]
    assert [e.day for e in history.before(10, window_days=5)] == [5, 9]
    assert [e.day for e in history.for_astronaut("A1", 10)] == [1, 5]


def test_rejects_entries_on_or_after_plan_day():
    history = History([entry(3), entry(4)])
    history.check_before(5)
    with pytest.raises(ValidationError, match="posteriores"):
        history.check_before(4)


def test_extend_is_immutable():
    history = History([entry(1)])
    longer = history.extend([entry(2)])
    assert len(history) == 1 and len(longer) == 2


def test_validation():
    with pytest.raises(ValidationError, match="entero"):
        entry(1.5)
    with pytest.raises(ValidationError, match="intensity"):
        entry(1, intensity=2)


def test_save_and_load(tmp_path):
    history = History([entry(1), entry(2, "A2", demanding=True)])
    path = tmp_path / "h.json"
    history.save(path)
    assert History.load(path).entries == history.entries
