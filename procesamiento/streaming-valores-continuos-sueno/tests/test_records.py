"""Validación de mensajes y clasificación de cada métrica."""

import pytest

from sleep_stream.config import ConfigError, Settings, load_settings
from sleep_stream.records import END, INVALID, MISSING, OK, START, Rejected, classify, parse_message

from conftest import T0, record

HR = Settings().specs["heart_rate"]


def rejected(data):
    with pytest.raises(Rejected) as info:
        parse_message(data)
    return info.value.code


def test_valid_record():
    message = parse_message(record(T0 + 60, heart_rate=58, spo2=98))
    assert (message.astronaut_id, message.session_id, message.timestamp) == ("ASTRO_001", "SLEEP_001", T0 + 60)
    assert message.metrics == {"heart_rate": 58, "spo2": 98}


@pytest.mark.parametrize("data, code", [
    ([1, 2], "bad_structure"),
    ({"timestamp": T0, "metrics": {"heart_rate": 58}}, "bad_astronaut_id"),
    ({"astronaut_id": "ASTRO_001", "timestamp": T0, "metrics": {"heart_rate": 58}}, "bad_sleep_session_id"),
    # ':' separaría mal las claves de Redis
    ({**record(T0, heart_rate=58), "astronaut_id": "ASTRO:001"}, "bad_astronaut_id"),
    ({**record(T0, heart_rate=58), "astronaut_id": 7}, "bad_astronaut_id"),
    ({**record(T0, heart_rate=58), "type": "pause"}, "bad_type"),
    ({**record(T0), "metrics": {}}, "bad_metrics"),
    ({**record(T0), "metrics": [58]}, "bad_metrics"),
    (record("ayer", heart_rate=58), "bad_timestamp"),
    (record(True, heart_rate=58), "bad_timestamp"),
    (record(float("nan"), heart_rate=58), "bad_timestamp"),
    (record(-5, heart_rate=58), "bad_timestamp"),
    (record(T0 * 1000, heart_rate=58), "timestamp_unit"),
])
def test_malformed_messages_are_rejected_with_a_code(data, code):
    assert rejected(data) == code


def test_start_and_end_messages():
    start = parse_message({"type": "start", "astronaut_id": "A1", "sleep_session_id": "S1",
                           "start_timestamp": T0, "sample_period_s": 1,
                           "expected_metrics": ["spo2", "heart_rate"],
                           "baselines": {"metrics": {"heart_rate": {"mean": 58, "sd": 4}}}})
    assert start.type == START and start.timestamp == T0
    assert start.options["expected_metrics"] == ["heart_rate", "spo2"]
    assert start.options["baselines"]["metrics"]["heart_rate"] == {"mean": 58.0, "sd": 4.0}
    end = parse_message({"type": "end", "astronaut_id": "A1", "sleep_session_id": "S1"})
    assert end.type == END and end.timestamp is None


def test_start_rejects_bad_baseline():
    code = rejected({"type": "start", "astronaut_id": "A1", "sleep_session_id": "S1", "start_timestamp": T0,
                     "baselines": {"metrics": {"heart_rate": {"mean": 58, "sd": 0}}}})
    assert code == "bad_baselines"


@pytest.mark.parametrize("present, value, unit, expected", [
    (True, 58, None, (OK, 58.0)),
    (True, 58.5, "bpm", (OK, 58.5)),
    (False, None, None, (MISSING, None)),
    (True, None, None, (MISSING, None)),
    (True, "58", None, (INVALID, "bad_type")),
    (True, True, None, (INVALID, "bad_type")),
    (True, float("inf"), None, (INVALID, "not_finite")),
    (True, 0, None, (INVALID, "out_of_range")),
    (True, 400, None, (INVALID, "out_of_range")),
    (True, 58, "Hz", (INVALID, "unit_mismatch")),
])
def test_classify_metric(present, value, unit, expected):
    assert classify(present, value, HR, unit) == expected


def test_unknown_metric_is_accepted_without_range():
    assert classify(True, 12345.0, None) == (OK, 12345.0)


def test_settings_from_environment():
    cfg = load_settings({"SLEEP_LEVELS_S": "30,60,600", "SLEEP_RETAIN_S": "300,1200",
                         "SLEEP_Z_THRESHOLD": "5", "SLEEP_PREFIX": "x:sleep"})
    assert cfg.levels_s == (30, 60, 600) and cfg.retain_s == (300, 1200)
    assert cfg.z_threshold == 5.0 and cfg.prefix == "x:sleep"
    assert cfg.version != Settings().version
    assert load_settings({"SLEEP_PREFIX": "x:sleep"}).version == Settings().version


@pytest.mark.parametrize("kwargs", [
    {"levels_s": (60, 100, 900, 1800)},           # 100 no es múltiplo de 60
    {"retain_s": (900, 3600)},                     # falta un nivel
    {"retain_s": (60, 3600, 7200)},                # no cubre el margen de llegada tardía
    {"retain_s": (900, 600, 7200)},                # un nivel grueso no puede vivir menos que uno fino
])
def test_inconsistent_settings_are_refused(kwargs):
    with pytest.raises(ConfigError):
        Settings(**kwargs)
