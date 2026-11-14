from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from checkin import (  # noqa: E402
    CheckIn,
    compare_weekly_team_means,
    load_checkins,
    save_checkin,
)


class CheckInTests(unittest.TestCase):
    def make_checkin(
        self,
        participant: str,
        team_rating: int,
        estimate: int | None,
        day: int = 9,
    ) -> CheckIn:
        return CheckIn(
            participant_id=participant,
            date=date(2026, 11, day),
            sleep_quality=3,
            rested=4,
            workload=3,
            mood=4,
            team_cohesion=team_rating,
            estimated_team_mean=estimate,
        )

    def test_rejects_ratings_outside_scale(self) -> None:
        with self.assertRaisesRegex(ValueError, "entre 1 y 5"):
            self.make_checkin("crew-a", 6, None)

    def test_weekly_comparison_uses_other_participants_only(self) -> None:
        records = [
            self.make_checkin("crew-a", 4, 4),
            self.make_checkin("crew-b", 2, 4),
            self.make_checkin("crew-c", 2, 4),
            self.make_checkin("crew-d", 3, 4),
        ]

        results = compare_weekly_team_means(records, date(2026, 11, 12))

        crew_a = next(result for result in results if result.participant_id == "crew-a")
        self.assertAlmostEqual(crew_a.actual_peer_mean, 7 / 3)
        self.assertAlmostEqual(crew_a.difference, 5 / 3)
        self.assertEqual(crew_a.peers_count, 3)

    def test_does_not_compare_when_no_peer_submitted(self) -> None:
        results = compare_weekly_team_means(
            [self.make_checkin("crew-a", 4, 4)], date(2026, 11, 12)
        )
        self.assertEqual(results, [])

    def test_persists_checkin_and_rejects_second_weekly_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Path(directory) / "responses.jsonl"
            save_checkin(storage, self.make_checkin("crew-a", 4, 4))

            self.assertEqual(load_checkins(storage), [self.make_checkin("crew-a", 4, 4)])
            with self.assertRaisesRegex(ValueError, "respuesta semanal"):
                save_checkin(storage, self.make_checkin("crew-a", 3, 3, day=10))


if __name__ == "__main__":
    unittest.main()
