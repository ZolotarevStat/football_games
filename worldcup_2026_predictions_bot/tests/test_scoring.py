from __future__ import annotations

import unittest

from wc_predictions_bot.models import LatestPrediction, MatchResult, Participant
from wc_predictions_bot.scoring import calculate_scoring, format_leaderboard


class ScoringTest(unittest.TestCase):
    def test_calculate_score_and_author_points(self) -> None:
        result = calculate_scoring(
            predictions=[
                LatestPrediction(
                    participant_id="p1",
                    match_id="m1",
                    scores=("0-0", "1-1", "2-1", "1-0", "2-0", "1-2", "0-1"),
                    author_team1="Месси",
                    author_team2="Мбаппе",
                )
            ],
            results=[
                MatchResult(
                    match_id="m1",
                    actual_score="2-1",
                    goals=("Месси", "Месси", "Мбаппе"),
                    assists=("Мбаппе",),
                )
            ],
            participants=[Participant(participant_id="p1", display_name="Игрок 1")],
            now_iso="2026-06-07T12:00:00+03:00",
        )

        self.assertEqual(result.scoring_rows[0]["score_points"], "8")
        self.assertEqual(result.scoring_rows[0]["author_points"], "14")
        self.assertEqual(result.scoring_rows[0]["total_points"], "22")
        self.assertEqual(result.leaderboard_rows[0]["display_name"], "Игрок 1")
        self.assertIn("Игрок 1", format_leaderboard(result.leaderboard_rows))


if __name__ == "__main__":
    unittest.main()
