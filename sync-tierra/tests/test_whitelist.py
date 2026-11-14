from datetime import datetime

import pytest

from sync_tierra.service import in_window
from sync_tierra.whitelist import ForbiddenField, build_record, digest, validate

VEC = bytes(80)


def test_record_contains_only_whitelisted_fields():
    r = build_record("A1", "2026-11-14", 1, VEC, 0, 0, [{"question_id": 2, "acoustic": {"f0_mean": 30.1},
                                                          "nlp": {"low_mood": 0.2}}])
    assert set(r) <= {"astronaut_id", "cycle_date", "schema_version", "vector_b64", "missing_mask",
                      "simulated_mask", "interviews"}
    assert digest(r) == digest(dict(r))


@pytest.mark.parametrize("interview", [
    {"question_id": 1, "acoustic": {"f0_mean": 1.0, "transcript": "hola"}},
    {"question_id": 1, "nlp": {"low_mood": 0.1, "text": "x"}},
    {"question_id": 1, "acoustic": {"f0_mean": "texto"}},
])
def test_forbidden_content_is_rejected(interview):
    with pytest.raises(ForbiddenField):
        build_record("A1", "2026-11-14", 1, VEC, 0, 0, [interview])


def test_forbidden_top_level_fields():
    r = build_record("A1", "2026-11-14", 1, VEC, 0, 0, [])
    for key in ("audio", "video", "transcript", "cycle_entries"):
        bad = {**r, key: "x"}
        with pytest.raises(ForbiddenField):
            validate(bad)


def test_vector_must_be_80_bytes():
    with pytest.raises(ForbiddenField):
        build_record("A1", "2026-11-14", 1, bytes(79), 0, 0, [])


def test_communication_window():
    t = datetime(2026, 11, 14, 10, 15)
    assert in_window(t, "always") and not in_window(t, "never")
    assert in_window(t, "0-20") and not in_window(t, "30-50")
