from datetime import date, timedelta

import pytest

from conductual import (
    INTERVIEW_QUESTIONS, compare_double_question, interview_due, interview_question,
    needs_implementation_intention, score_pvt, validate_checkin,
)

D = date(2026, 11, 10)


def test_checkin_five_questions_one_to_five():
    ok = validate_checkin("AST-01", D, {"sleep": 4, "fatigue": 2, "workload": 3, "mood": 4, "cohesion": 5})
    assert ok["fatigue"] == 2
    with pytest.raises(ValueError):
        validate_checkin("AST-01", D, {"sleep": 6, "fatigue": 2, "workload": 3, "mood": 4, "cohesion": 5})
    with pytest.raises(ValueError):
        validate_checkin("AST-01", D, {"sleep": 4, "fatigue": True, "workload": 3, "mood": 4, "cohesion": 5})
    with pytest.raises(ValueError, match="Faltan"):
        validate_checkin("AST-01", D, {"sleep": 4})


def test_pvt_scoring():
    score = score_pvt([250, 300, 520, 80, 610], duration_s=180)
    assert score.trials == 4 and score.lapses == 2 and score.false_starts == 1
    assert score.mean_rt_ms == pytest.approx((250 + 300 + 520 + 610) / 4)
    with pytest.raises(ValueError):
        score_pvt([], 180)


def test_interview_every_three_days_rotates_eight_questions():
    assert [d for d in range(1, 10) if interview_due(d, 3)] == [1, 4, 7]
    seen = [interview_question(d, 3)[0] for d in range(1, 3 * 8 + 1, 3)]
    assert seen == list(range(1, 9))
    assert interview_question(25, 3)[0] == 1  # vuelve a empezar
    assert len(INTERVIEW_QUESTIONS) == 8


def test_two_consecutive_exercise_skips():
    assert needs_implementation_intention([(D, False), (D + timedelta(days=1), False)])
    assert not needs_implementation_intention([(D, False), (D + timedelta(days=1), True)])
    assert not needs_implementation_intention([(D, False), (D + timedelta(days=2), False)])


def test_double_question_compares_with_the_rest_of_the_crew():
    results = compare_double_question([("A", 4, 3), ("B", 2, 4), ("C", 3, 4)], D)
    by = {r.astronaut_id: r for r in results}
    assert by["A"].actual_peer_mean == pytest.approx(2.5) and by["A"].difference == pytest.approx(0.5)
    assert by["B"].peers_count == 2
