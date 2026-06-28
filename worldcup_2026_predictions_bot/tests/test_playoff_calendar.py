from __future__ import annotations

import unittest

from wc_predictions_bot.models import MatchResult
from wc_predictions_bot.playoff_calendar import build_playoff_calendar


class PlayoffCalendarTest(unittest.TestCase):
    def test_round32_fixtures_use_flashscore_schedule_and_internal_team_names(self) -> None:
        update = build_playoff_calendar([])
        match = next(item for item in update.matches if item.match_id == "SAfCan")

        self.assertEqual(match.team1, "ЮАР")
        self.assertEqual(match.team2, "Канада")
        self.assertEqual(match.tour, "1/16")
        self.assertEqual(match.status, "open")
        self.assertEqual(match.kickoff_msk.isoformat(timespec="minutes"), "2026-06-28T22:00+03:00")
        self.assertEqual(match.deadline_msk.isoformat(timespec="minutes"), "2026-06-28T21:55+03:00")
        self.assertEqual(sum(1 for item in update.matches if item.tour == "1/16"), 16)

    def test_future_round_resolves_winners_from_results(self) -> None:
        update = build_playoff_calendar(
            [
                MatchResult(match_id="SAfCan", actual_score="2-1"),
                MatchResult(match_id="NedMor", actual_score="0-1"),
            ]
        )

        match = next(item for item in update.matches if item.match_id == "M90")

        self.assertEqual(match.tour, "1/8")
        self.assertEqual(match.team1, "ЮАР")
        self.assertEqual(match.team2, "Марокко")
        self.assertEqual(match.status, "open")
        self.assertGreaterEqual(update.resolved_future_match_count, 1)

    def test_draw_result_leaves_future_pair_planned_and_warns(self) -> None:
        update = build_playoff_calendar([MatchResult(match_id="SAfCan", actual_score="1-1")])
        match = next(item for item in update.matches if item.match_id == "M90")

        self.assertEqual(match.team1, "Победитель M73")
        self.assertEqual(match.status, "planned")
        self.assertTrue(any("ничья" in warning for warning in update.warnings))

    def test_draw_result_can_resolve_winner_from_status_marker(self) -> None:
        update = build_playoff_calendar([MatchResult(match_id="SAfCan", actual_score="1-1", status="final,winner_team2")])
        match = next(item for item in update.matches if item.match_id == "M90")

        self.assertEqual(match.team1, "Канада")
        self.assertEqual(match.status, "planned")
        self.assertFalse(update.warnings)


if __name__ == "__main__":
    unittest.main()
