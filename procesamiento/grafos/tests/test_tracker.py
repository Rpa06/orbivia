"""Detector con histéresis y acumulador: duraciones por timestamps, huecos y días."""

import random

import pytest

from conftest import H, apart, feed, standard_schedule, together
from social_graph.params import Params
from social_graph.schedule import FixedSchedule
from social_graph.tracker import InteractionTracker
from social_graph.validation import PositionSample

AB = ("A", "B")
AC = ("A", "C")
BC = ("B", "C")


def make(crew, params=None, schedule=None):
    return InteractionTracker(crew, schedule or standard_schedule(crew), params or Params())


def contact_between(crew, group, start, end):
    """Posiciones: `group` junto en [start, end), todos separados fuera."""
    base = apart(crew)
    return lambda t: together(base, group) if start <= t < end else base


@pytest.mark.parametrize("period", [5.0, 10.0, 30.0, 60.0])
def test_duration_depends_on_timestamps_not_sample_count(crew, period):
    tracker = make(crew)
    feed(tracker, 16.5 * H, 18.5 * H, period, contact_between(crew, AB, 17 * H, 18 * H))
    totals = tracker.totals(0)
    assert totals.interaction[AB] == pytest.approx(3600.0)
    assert totals.overlap_observed[AB] == pytest.approx(2 * H - period)


def test_irregular_sampling_gives_same_duration(crew):
    rng = random.Random(1)
    positions = contact_between(crew, AB, 17 * H, 18 * H)
    tracker = make(crew)
    t = 16.5 * H
    while t < 18.5 * H:
        tracker.add_sample(PositionSample(t, positions(t)))
        t += rng.uniform(2.0, 40.0)
    # El error está acotado por el paso de muestreo en cada borde
    assert tracker.totals(0).interaction[AB] == pytest.approx(3600.0, abs=80.0)


def test_simultaneous_interactions_count_for_every_pair(crew):
    tracker = make(crew)
    feed(tracker, 16.5 * H, 18.5 * H, 10.0, contact_between(crew, crew, 17 * H, 18 * H))
    totals = tracker.totals(0)
    for pair in (AB, AC, BC):
        assert totals.interaction[pair] == pytest.approx(3600.0)
    # El tiempo acompañado no cuenta dos veces: 1 h menos la permanencia mínima
    assert totals.accompanied["A"] == pytest.approx(3600.0 - 60.0)
    assert totals.accompanied["A"] <= totals.leisure_observed["A"]


def test_interaction_only_counts_in_joint_leisure(crew):
    # Juntos de 15:00 a 17:00, pero el trabajo acaba a las 16:00
    tracker = make(crew)
    feed(tracker, 14.5 * H, 17.5 * H, 10.0, contact_between(crew, AB, 15 * H, 17 * H))
    assert tracker.totals(0).interaction[AB] == pytest.approx(3600.0)


def test_no_interaction_when_only_one_is_in_leisure():
    crew = ["A", "B"]
    schedule = FixedSchedule(
        {
            "A": {"sleep": [(22 * H, 6 * H)], "work": [(8 * H, 16 * H)]},
            "B": {"sleep": [(22 * H, 6 * H)], "work": [(6 * H, 22 * H)]},
        }
    )
    tracker = make(crew, schedule=schedule)
    feed(tracker, 16.5 * H, 18.5 * H, 10.0, contact_between(crew, AB, 17 * H, 18 * H))
    assert tracker.totals(0).interaction.get(AB, 0.0) == 0.0
    assert tracker.totals(0).overlap_observed.get(AB, 0.0) == 0.0


def test_hysteresis_keeps_contact_between_thresholds():
    crew = ["A", "B"]
    tracker = make(crew)
    # Entra a 1.9 m y oscila entre 1.9 y 2.4 m: por debajo del umbral de salida (2.5)
    def positions(t):
        if not 17 * H <= t < 18 * H:
            return apart(crew)
        gap = 1.9 if int(t // 10) % 2 == 0 else 2.4
        return together(apart(crew), AB, gap=gap)

    feed(tracker, 16.5 * H, 18.5 * H, 10.0, positions)
    assert tracker.totals(0).interaction[AB] == pytest.approx(3600.0)


def test_no_entry_between_thresholds():
    crew = ["A", "B"]
    tracker = make(crew)
    positions = lambda t: together(apart(crew), AB, gap=2.3)
    feed(tracker, 17 * H, 18 * H, 10.0, positions)
    assert tracker.totals(0).interaction.get(AB, 0.0) == 0.0


def test_minimum_dwell_discards_brief_contacts_and_credits_from_start(crew):
    brief = make(crew)
    feed(brief, 16.9 * H, 17.1 * H, 10.0, contact_between(crew, AB, 17 * H, 17 * H + 30))
    assert brief.totals(0).interaction.get(AB, 0.0) == 0.0

    long = make(crew)
    feed(long, 16.9 * H, 17.2 * H, 10.0, contact_between(crew, AB, 17 * H, 17 * H + 300))
    assert long.totals(0).interaction[AB] == pytest.approx(300.0)


def test_short_dropout_is_bridged(crew):
    base = contact_between(crew, AB, 17 * H, 18 * H)

    def positions(t):
        p = dict(base(t))
        if 17.5 * H <= t < 17.5 * H + 30:  # 3 muestras perdidas: hueco de 40 s <= 60 s
            p["A"] = None
        return p

    tracker = make(crew)
    feed(tracker, 16.5 * H, 18.5 * H, 10.0, positions)
    assert tracker.totals(0).interaction[AB] == pytest.approx(3600.0)


def test_long_gap_adds_no_interaction_and_no_observed_time(crew):
    period = 10.0
    base = contact_between(crew, AB, 17 * H, 18 * H)
    gap_start, gap_end = 17 * H + 1200, 17 * H + 2400

    def positions(t):
        p = dict(base(t))
        if gap_start <= t < gap_end:
            p["A"] = None
        return p

    tracker = make(crew)
    feed(tracker, 16.5 * H, 18.5 * H, period, positions)
    totals = tracker.totals(0)
    # Última muestra válida antes del hueco: gap_start − period
    assert totals.interaction[AB] == pytest.approx((1200 - period) + 1200)
    assert totals.overlap_observed[AB] == pytest.approx(2 * H - period - (1200 + period))
    # La pareja B–C no se ve afectada por el fallo del sensor de A
    assert totals.overlap_observed[BC] == pytest.approx(2 * H - period)


def test_sampling_slower_than_max_gap_observes_nothing(crew):
    tracker = make(crew)
    feed(tracker, 16.5 * H, 18.5 * H, 120.0, contact_between(crew, AB, 17 * H, 18 * H))
    assert tracker.totals(0).interaction.get(AB, 0.0) == 0.0
    assert tracker.totals(0).overlap_observed.get(AB, 0.0) == 0.0


def test_old_and_duplicate_samples_are_discarded(crew):
    positions = contact_between(crew, AB, 17 * H, 18 * H)
    tracker = make(crew)
    feed(tracker, 16.5 * H, 18.5 * H, 10.0, positions)
    before = tracker.totals(0).interaction[AB]
    # Relectura de mensajes ya procesados (p. ej. tras un reinicio)
    for t in (17 * H, 17.5 * H, 18.5 * H - 10.0):
        assert tracker.add_sample(PositionSample(t, positions(t))) is False
    assert tracker.totals(0).interaction[AB] == before
    assert tracker.n_discarded == 3


NIGHT_OWLS = {"sleep": [(2 * H, 10 * H)], "work": [(10 * H, 18 * H)]}  # ocio 18:00–02:00


def test_contact_across_midnight_stays_in_one_mission_day():
    crew = ["A", "B"]
    schedule = FixedSchedule({a: NIGHT_OWLS for a in crew})
    tracker = make(crew, schedule=schedule)  # corte a las 04:00
    feed(tracker, 23 * H, 25 * H, 10.0, contact_between(crew, AB, 23.5 * H, 24.5 * H))
    assert tracker.open_days() == [0]
    assert tracker.totals(0).interaction[AB] == pytest.approx(3600.0)


def test_contact_across_day_cutoff_is_split_and_conserved():
    crew = ["A", "B"]
    schedule = FixedSchedule({a: NIGHT_OWLS for a in crew})
    tracker = make(crew, params=Params(day_cutoff_s=0.0), schedule=schedule)
    feed(tracker, 23 * H, 25 * H, 10.0, contact_between(crew, AB, 23.5 * H, 24.5 * H))
    assert tracker.totals(0).interaction[AB] == pytest.approx(1800.0)
    assert tracker.totals(1).interaction[AB] == pytest.approx(1800.0)


def test_closed_day_receives_no_more_time(crew):
    tracker = make(crew, params=Params(day_cutoff_s=0.0), schedule=FixedSchedule({a: NIGHT_OWLS for a in crew}))
    feed(tracker, 23 * H, 24 * H + 10, 10.0, contact_between(crew, AB, 23.5 * H, 24.5 * H))
    closed = tracker.pop_day(0)
    assert closed.interaction[AB] == pytest.approx(1800.0)
    feed(tracker, 24 * H + 10, 25 * H, 10.0, contact_between(crew, AB, 23.5 * H, 24.5 * H))
    assert tracker.open_days() == [1]
    assert tracker.totals(1).interaction[AB] == pytest.approx(1800.0)


def test_duplicate_crew_ids_rejected():
    with pytest.raises(ValueError):
        make(["A", "A"])
