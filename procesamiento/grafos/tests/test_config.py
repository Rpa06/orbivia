import json

import pytest

from social_graph.config import (
    DEFAULT_CREW,
    load_settings,
    params_version,
    parse_time_of_day,
)
from social_graph.params import Params
from social_graph.schedule import day_window, leisure_time

H = 3600.0


def test_defaults_match_design():
    settings = load_settings({})
    assert settings.params == Params()
    assert settings.crew == DEFAULT_CREW
    assert settings.source == "simulation"
    assert settings.checkpoint_every_s == 30.0
    schedule = settings.build_schedule()
    window = day_window(0, settings.params.day_cutoff_s)
    assert leisure_time(schedule, "A1", window) == pytest.approx(8 * H)


def test_environment_overrides():
    env = {
        "SG_D_IN_M": "1.5",
        "SG_D_OUT_M": "2",
        "SG_MIN_DWELL_S": "30",
        "SG_MAX_GAP_S": "90",
        "SG_DAY_CUTOFF": "03:30",
        "SG_NORMALIZATION": "leisure",
        "SG_WEIGHT_FN": "linear",
        "SG_KAPPA": "0.2",
        "SG_MIN_OVERLAP_S": "900",
        "SG_MIN_COVERAGE": "0.7",
        "SG_CREW": "X, Y ,Z",
        "SG_SOURCE": "redis",
        "SG_STREAM": "otro:stream",
        "SG_CHECKPOINT_EVERY_S": "5",
        "SG_SCHEDULE_JITTER_S": "600",
    }
    settings = load_settings(env)
    assert settings.params == Params(
        d_in_m=1.5, d_out_m=2.0, min_dwell_s=30, max_gap_s=90, day_cutoff_s=3.5 * H,
        normalization="leisure", weight_fn="linear", kappa=0.2, min_overlap_s=900, min_coverage=0.7,
    )
    assert settings.crew == ("X", "Y", "Z")
    assert (settings.source, settings.stream, settings.checkpoint_every_s) == ("redis", "otro:stream", 5.0)
    assert settings.schedule_jitter_s == 600


def test_schedule_from_json_with_default_for_the_rest(tmp_path):
    custom = {"A1": {"sleep": [["00:00", "08:00"]], "work": [["09:00", "13:00"]]}}
    for env in (
        {"SG_CREW": "A1,A2", "SG_SCHEDULE_JSON": json.dumps(custom)},
        {"SG_CREW": "A1,A2", "SG_SCHEDULE_FILE": str(_write(tmp_path / "h.json", custom))},
    ):
        settings = load_settings(env)
        schedule = settings.build_schedule()
        window = day_window(0, settings.params.day_cutoff_s)
        assert leisure_time(schedule, "A1", window) == pytest.approx(12 * H)
        assert leisure_time(schedule, "A2", window) == pytest.approx(8 * H)


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "env",
    [
        {"SG_KAPPA": "abc"},
        {"SG_DAY_CUTOFF": "25:00"},
        {"SG_DAY_CUTOFF": "4"},
        {"SG_SOURCE": "kafka"},
        {"SG_CREW": "solo"},
        {"SG_D_IN_M": "3", "SG_D_OUT_M": "2"},
        {"SG_SCHEDULE_JSON": json.dumps({"A1": {"siesta": [["13:00", "14:00"]]}})},
    ],
)
def test_invalid_configuration_is_rejected(env):
    with pytest.raises(ValueError):
        load_settings(env)


def test_time_of_day():
    assert parse_time_of_day("04:00") == 4 * H
    assert parse_time_of_day("23:59") == 23 * H + 59 * 60


def test_params_version_is_stable_and_sensitive():
    assert params_version(Params()) == params_version(Params())
    assert params_version(Params()) != params_version(Params(kappa=0.31))
    assert len(params_version(Params())) == 12
