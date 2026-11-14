"""Motor de sesión sin Redis: ventanas, colapso, anomalías, actigrafía y resumen."""

import random

import pytest

from sleep_stream.config import Settings
from sleep_stream.simulate import night_records

from conftest import T0, LocalRun, record, truth

# Colapso inmediato: cada nivel se funde en cuanto su ventana madre queda atrás
EAGER = Settings(retain_s=(180, 180, 180), lateness_s=60)


def minute_records(minutes, start=T0, **extra):
    """Un registro por minuto, con valores distintos para poder comprobar medias."""
    return [record(start + 60 * k, heart_rate=50.0 + k % 20, movement=0.02, **extra) for k in range(minutes)]


# --- ventanas y colapso -----------------------------------------------------------


def test_sixty_minute_records_collapse_like_the_design_example():
    run = LocalRun()
    run.feed(minute_records(60))
    # Sin colapsar todavía más que lo que supera la retención de 15 min del nivel 0
    assert sum(run.window_counts()) < 60
    summary = run.seal(T0 + 3600)
    # 60 registros de 1 min -> 2 agregados de 30 min
    assert run.window_counts() == [0, 0, 0, 2]
    assert [entry["metrics"]["heart_rate"]["n"] for entry in summary["timeline"]] == [30, 30]
    assert summary["session_metadata"]["aggregates_consistent"] is True


def test_storage_stays_bounded_during_a_long_night():
    run = LocalRun()
    peak = 0
    records = minute_records(8 * 60)
    for begin in range(0, len(records), 10):
        run.feed(records[begin:begin + 10])
        peak = max(peak, sum(run.window_counts()))
    # 15 de 1 min + 12 de 5 min + 8 de 15 min + 16 de 30 min, más las ventanas en curso
    assert peak <= 60
    assert run.window_counts()[0] <= 20


def test_each_level_holds_only_its_retention():
    run = LocalRun().feed(minute_records(8 * 60))
    cfg = run.cfg
    watermark = run.session.watermark
    for level in range(3):
        starts = run.windows.starts(level)
        assert starts, f"el nivel {level} debería tener ventanas recientes"
        assert min(starts) >= watermark - cfg.retain_s[level] - cfg.levels_s[level + 1]


def test_collapse_preserves_exact_global_statistics():
    records, _ = night_records("ASTRO_001", "SLEEP_001", T0, 4 * 3600, period_s=5, seed=7)
    run = LocalRun().feed(records, advance_every=50)
    summary = run.seal(T0 + 4 * 3600)
    for metric in ("heart_rate", "spo2", "skin_temperature"):
        exact, got = truth(records, metric), summary["metrics"][metric]
        assert got["valid_count"] == exact["n"]
        assert got["mean"] == pytest.approx(exact["mean"], rel=1e-10)
        assert got["std"] == pytest.approx(exact["std"], rel=1e-8)
        assert (got["min"], got["max"]) == (exact["min"], exact["max"])
    assert summary["session_metadata"]["aggregates_consistent"] is True


def test_timeline_windows_add_up_to_the_totals():
    records, _ = night_records("ASTRO_001", "SLEEP_001", T0, 3 * 3600, period_s=10, seed=3)
    summary = LocalRun().feed(records, advance_every=20).seal(T0 + 3 * 3600)
    for metric, stats in summary["metrics"].items():
        assert sum(e["metrics"][metric]["n"] for e in summary["timeline"]) == stats["valid_count"]
        assert sum(e["metrics"][metric]["missing"] for e in summary["timeline"]) == stats["missing_count"]


# --- desorden, duplicados y rechazos ------------------------------------------------


def test_out_of_order_records_give_the_same_result():
    records, _ = night_records("ASTRO_001", "SLEEP_001", T0, 2 * 3600, period_s=5, seed=1)
    ordered = LocalRun().feed(records, advance_every=30).seal(T0 + 7200)
    shuffled = list(records)
    rng = random.Random(9)
    for begin in range(0, len(shuffled), 12):  # desorden local, como en una red real
        chunk = shuffled[begin:begin + 12]
        rng.shuffle(chunk)
        shuffled[begin:begin + 12] = chunk
    run = LocalRun().feed(shuffled, advance_every=30)
    result = run.seal(T0 + 7200)
    assert run.session.counters["out_of_order"] > 0
    for metric in ordered["metrics"]:
        a, b = ordered["metrics"][metric], result["metrics"][metric]
        assert b["valid_count"] == a["valid_count"]
        assert b["mean"] == pytest.approx(a["mean"], rel=1e-10)
        assert (b["min"], b["max"], b["first"], b["last"]) == (a["min"], a["max"], a["first"], a["last"])


def test_very_late_record_lands_in_a_coarser_window_and_is_not_lost():
    run = LocalRun().feed(minute_records(4 * 60))
    late = record(T0 + 90, heart_rate=99.0, movement=0.02)  # su minuto se colapsó hace horas
    run.feed([late])
    assert run.session.counters["late_coarse"] == 1
    summary = run.seal(T0 + 4 * 3600)
    assert summary["metrics"]["heart_rate"]["valid_count"] == 241
    assert summary["metrics"]["heart_rate"]["max"] == 99.0
    assert summary["timeline"][0]["metrics"]["heart_rate"]["max"] == 99.0
    assert summary["session_metadata"]["aggregates_consistent"] is True


def test_duplicates_are_counted_once():
    records = minute_records(30)
    run = LocalRun().feed(records + records[5:15])
    assert run.session.counters["duplicates"] == 10
    assert run.session.total["heart_rate"].n == 30


def test_records_outside_the_session_are_rejected_not_aggregated():
    run = LocalRun().feed([
        record(T0 - 1, heart_rate=58),
        record(T0 + 90000, heart_rate=58),
        {"astronaut_id": "ASTRO_001", "sleep_session_id": "SLEEP_001", "timestamp": T0 + 5},
    ])
    assert run.session.rejections == {"before_start": 1, "beyond_max_session": 1, "bad_metrics": 1}
    assert run.session.counters["accepted"] == 0


# --- ausentes e inválidos -------------------------------------------------------------


def test_missing_and_invalid_values_never_enter_the_statistics():
    run = LocalRun(expected_metrics=["heart_rate", "spo2"]).feed([
        record(T0 + 1, heart_rate=60, spo2=98),
        record(T0 + 2, heart_rate=None, spo2=97),
        record(T0 + 3, spo2=96),                  # heart_rate ausente
        record(T0 + 4, heart_rate=999, spo2=95),  # fuera del rango del sensor
        record(T0 + 5, heart_rate="60", spo2=94),
        record(T0 + 6, heart_rate=62, spo2=93),
    ])
    summary = run.seal(T0 + 60)
    hr = summary["metrics"]["heart_rate"]
    assert (hr["valid_count"], hr["missing_count"], hr["invalid_count"]) == (2, 2, 2)
    assert hr["mean"] == pytest.approx(61.0)
    assert summary["metrics"]["spo2"]["valid_count"] == 6
    assert summary["session_metadata"]["invalid_reasons"] == {"out_of_range": 1, "bad_type": 1}


def test_metric_never_received_is_none_not_zero():
    run = LocalRun().feed([record(T0 + k, heart_rate=60) for k in range(10)])
    summary = run.seal(T0 + 60)
    assert summary["sleep_summary_vector"]["mean_spo2"] is None
    assert summary["normalized_vector"]["mean_spo2"]["status"] == "missing"
    assert summary["metrics"]["spo2"]["mean"] is None
    assert summary["metrics"]["spo2"]["missing_count"] == 10


def test_new_metric_is_aggregated_without_changing_anything():
    run = LocalRun().feed([record(T0 + k, heart_rate=60, eeg_delta_power=0.4 + k) for k in range(5)])
    summary = run.seal(T0 + 60)
    assert summary["metrics"]["eeg_delta_power"]["mean"] == pytest.approx(2.4)
    assert summary["metrics"]["eeg_delta_power"]["median"] is None  # sin rango no hay histograma


def test_completeness_counts_records_that_never_arrived():
    records = [record(T0 + k, heart_rate=60, movement=0.02) for k in range(0, 600, 2)]  # llega la mitad
    declared = LocalRun(expected_metrics=["heart_rate"], sample_period_s=1).feed(records).seal(T0 + 600)
    assert declared["sleep_summary_vector"]["measurement_completeness"] == pytest.approx(0.5)
    assert declared["session_metadata"]["missing_observations"] == 300
    undeclared = LocalRun(expected_metrics=["heart_rate"]).feed(records).seal(T0 + 600)
    assert undeclared["sleep_summary_vector"]["measurement_completeness"] == pytest.approx(1.0)
    assert undeclared["session_metadata"]["missing_observations"] is None


# --- anomalías ----------------------------------------------------------------------


def steady(seconds, start=T0, hr=60.0):
    rng = random.Random(11)
    return [record(start + k, heart_rate=round(hr + rng.gauss(0, 1), 1), movement=0.02) for k in range(seconds)]


def test_spike_survives_although_the_window_mean_is_normal():
    records = steady(3600)
    records[1830]["metrics"]["heart_rate"] = 120.0
    summary = LocalRun().feed(records, advance_every=60).seal(T0 + 3600)
    anomalies = [a for a in summary["anomalies"] if a["metric"] == "heart_rate"]
    assert len(anomalies) == 1
    anomaly = anomalies[0]
    assert anomaly["peak_value"] == 120.0 and anomaly["peak_ts"] == T0 + 1830
    assert anomaly["method"] == "ewma_zscore" and anomaly["kind"] == "statistical_anomaly"
    assert anomaly["reference"]["mean"] == pytest.approx(60.0, abs=1.5)
    # Contexto: la ventana de 1 min tal como estaba justo antes del pico
    assert anomaly["window"]["size_s"] == 60 and anomaly["window"]["n"] == 30
    assert anomaly["window"]["mean"] == pytest.approx(60.0, abs=1.0)
    # La media de su ventana de 30 min no delata nada: por eso se guarda el evento
    half_hour = summary["timeline"][1]["metrics"]["heart_rate"]
    assert half_hour["mean"] == pytest.approx(60.0, abs=0.2)
    assert half_hour["max"] == 120.0


def test_consecutive_anomalous_samples_form_one_episode():
    records = steady(3600)
    for k in range(1800, 1815):
        records[k]["metrics"]["heart_rate"] = 115.0 + (k - 1800)
    summary = LocalRun().feed(records, advance_every=60).seal(T0 + 3600)
    episodes = [a for a in summary["anomalies"] if a["metric"] == "heart_rate"]
    assert len(episodes) == 1
    assert episodes[0]["count"] >= 5
    assert (episodes[0]["start_ts"], episodes[0]["peak_value"]) == (T0 + 1800, 129.0)
    assert summary["session_metadata"]["anomalous_samples"] >= episodes[0]["count"]


def test_slow_overnight_drift_is_not_an_anomaly():
    rng = random.Random(2)
    records = [record(T0 + k, heart_rate=round(66.0 - 0.001 * k + rng.gauss(0, 1), 1), movement=0.02)
               for k in range(0, 4 * 3600, 2)]
    summary = LocalRun().feed(records, advance_every=60).seal(T0 + 4 * 3600)
    assert [a for a in summary["anomalies"] if a["metric"] == "heart_rate"] == []


def test_individual_baseline_adds_a_second_method():
    run = LocalRun(baselines={"metrics": {"heart_rate": {"mean": 60.0, "sd": 2.0}}})
    records = steady(600)
    records[300]["metrics"]["heart_rate"] = 75.0
    summary = run.feed(records, advance_every=60).seal(T0 + 600)
    methods = {a["method"] for a in summary["anomalies"] if a["peak_ts"] == T0 + 300}
    assert methods == {"ewma_zscore", "baseline_zscore"}


def test_anomaly_list_is_capped_and_the_overflow_is_counted():
    cfg = Settings(max_anomalies=3, episode_gap_s=5)
    records = steady(3600)
    for k in range(600, 3600, 300):  # 10 picos bien separados
        records[k]["metrics"]["heart_rate"] = 130.0
    summary = LocalRun(cfg).feed(records, advance_every=60).seal(T0 + 3600)
    assert len(summary["anomalies"]) == 3
    assert summary["session_metadata"]["anomalies_dropped"] == 7


# --- actigrafía y vector --------------------------------------------------------------


def test_activity_epochs_efficiency_and_fragmentation():
    records = []
    for minute in range(120):
        active = minute in (30, 31, 32, 80)  # dos rachas: una de 3 min y una de 1
        records += [record(T0 + 60 * minute + s, heart_rate=60, movement=0.9 if active else 0.02)
                    for s in range(0, 60, 10)]
    summary = LocalRun().feed(records, advance_every=30).seal(T0 + 7200)
    sleep = summary["sleep"]
    assert (sleep["scored_epochs"], sleep["active_epochs"], sleep["activity_bouts"]) == (120, 4, 2)
    vector = summary["sleep_summary_vector"]
    assert vector["time_in_bed_h"] == pytest.approx(2.0)
    assert vector["estimated_sleep_h"] == pytest.approx(116 / 60)
    assert vector["sleep_efficiency"] == pytest.approx(116 / 120)
    assert vector["sleep_fragmentation"] == pytest.approx(1.0)  # 2 rachas en 2 h


def test_minutes_without_movement_data_are_unknown_not_asleep():
    records = [record(T0 + 60 * m, heart_rate=60, movement=0.02) for m in range(30)]
    records += [record(T0 + 60 * m, heart_rate=60) for m in range(30, 60)]  # sin movimiento
    summary = LocalRun().feed(records).seal(T0 + 3600)
    sleep = summary["sleep"]
    assert (sleep["scored_epochs"], sleep["unknown_epochs"]) == (30, 30)
    assert summary["sleep_summary_vector"]["estimated_sleep_h"] == pytest.approx(0.5)
    assert sleep["activity_coverage"] == pytest.approx(0.5)


def test_vector_has_every_dimension_in_order():
    records, _ = night_records("ASTRO_001", "SLEEP_001", T0, 3600, period_s=5, seed=1)
    summary = LocalRun().feed(records, advance_every=30).seal(T0 + 3600)
    names = [item["name"] for item in summary["vector_spec"]]
    assert list(summary["sleep_summary_vector"]) == names
    assert all(summary["sleep_summary_vector"][name] is not None for name in names)


def test_hrv_trend_is_reported_per_hour():
    records = [record(T0 + k, heart_rate_variability=60.0 + 5.0 * k / 3600, movement=0.02)
               for k in range(0, 7200, 10)]
    summary = LocalRun().feed(records, advance_every=30).seal(T0 + 7200)
    assert summary["sleep_summary_vector"]["hrv_trend"] == pytest.approx(5.0, rel=1e-6)


def test_normalization_only_where_a_transformation_is_defined():
    run = LocalRun(baselines={"vector": {"mean_heart_rate": {"mean": 55.0, "sd": 5.0}}})
    summary = run.feed([record(T0 + k, heart_rate=60, movement=0.02) for k in range(120)]).seal(T0 + 120)
    normalized = summary["normalized_vector"]
    assert normalized["mean_heart_rate"] == {"value": pytest.approx(1.0), "status": "known", "method": "baseline_z"}
    assert normalized["sleep_efficiency"]["method"] == "identity"
    assert normalized["movement_level"] == {"value": None, "status": "no_baseline", "method": "baseline_z"}


def test_state_survives_serialization_mid_session():
    import json

    from sleep_stream.engine import Session

    records, _ = night_records("ASTRO_001", "SLEEP_001", T0, 3600, period_s=5, seed=4)
    whole = LocalRun().feed(records, advance_every=30).seal(T0 + 3600)

    run = LocalRun().feed(records[:400], advance_every=30)
    saved = json.loads(json.dumps(run.session.dump_state()))
    restored = Session("ASTRO_001", "SLEEP_001", float(T0))
    restored.load_state(saved)
    run.session = restored
    resumed = run.feed(records[400:], advance_every=30).seal(T0 + 3600)
    assert resumed == whole
