from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from wc_predictions_bot.models import LatestPrediction, Match, MatchResult, Participant
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
        self.assertEqual(result.scoring_rows[0]["goal_points"], "12")
        self.assertEqual(result.scoring_rows[0]["assist_points"], "2")
        self.assertEqual(result.scoring_rows[0]["author_points"], "14")
        self.assertEqual(result.scoring_rows[0]["total_points"], "22")
        self.assertEqual(result.leaderboard_rows[0]["goal_points"], "12")
        self.assertEqual(result.leaderboard_rows[0]["assist_points"], "2")
        self.assertEqual(result.leaderboard_rows[0]["display_name"], "Игрок 1")
        self.assertIn("Игрок 1", format_leaderboard(result.leaderboard_rows))

    def test_own_goal_does_not_score_author_points(self) -> None:
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
                    actual_score="1-0",
                    goals=("Месси",),
                    own_goals=("Месси",),
                )
            ],
            participants=[Participant(participant_id="p1", display_name="Игрок 1")],
            now_iso="2026-06-07T12:00:00+03:00",
        )

        self.assertEqual(result.scoring_rows[0]["author_points"], "0")

    def test_technical_and_cancelled_results_are_not_counted(self) -> None:
        result = calculate_scoring(
            predictions=[
                LatestPrediction(
                    participant_id="p1",
                    match_id="m1",
                    scores=("0-0", "1-1", "2-1", "1-0", "2-0", "1-2", "0-1"),
                    author_team1="Месси",
                    author_team2="Мбаппе",
                ),
                LatestPrediction(
                    participant_id="p1",
                    match_id="m2",
                    scores=("0-0", "1-1", "2-1", "1-0", "2-0", "1-2", "0-1"),
                    author_team1="Месси",
                    author_team2="Мбаппе",
                ),
            ],
            results=[
                MatchResult(match_id="m1", actual_score="3-0", status="technical"),
                MatchResult(match_id="m2", actual_score="0-0", status="cancelled"),
            ],
            participants=[Participant(participant_id="p1", display_name="Игрок 1")],
            now_iso="2026-06-07T12:00:00+03:00",
        )

        self.assertEqual(result.scoring_rows, [])
        self.assertEqual(result.leaderboard_rows, [])
        self.assertEqual(result.match_ids, ())

    def test_playoff_stage_points_increase_from_round16(self) -> None:
        result = calculate_scoring(
            predictions=[
                LatestPrediction(
                    participant_id="p1",
                    match_id="m1",
                    scores=("2-1", "1-1", "1-0", "0-0", "2-0", "1-2", "0-1"),
                    author_team1="Месси",
                    author_team2="Мбаппе",
                )
            ],
            results=[
                MatchResult(
                    match_id="m1",
                    actual_score="2-1",
                    goals=("Месси",),
                    assists=("Мбаппе",),
                )
            ],
            participants=[Participant(participant_id="p1", display_name="Игрок 1")],
            matches=[
                Match(
                    match_id="m1",
                    group="",
                    tour="1/8",
                    kickoff_msk=datetime(2026, 7, 1, 20, 0, tzinfo=ZoneInfo("Europe/Moscow")),
                    deadline_msk=datetime(2026, 7, 1, 19, 55, tzinfo=ZoneInfo("Europe/Moscow")),
                    team1="Аргентина",
                    team2="Франция",
                )
            ],
            now_iso="2026-07-01T23:00:00+03:00",
        )

        self.assertEqual(result.scoring_rows[0]["stage"], "round16")
        self.assertEqual(result.scoring_rows[0]["score_points"], "19")
        self.assertEqual(result.scoring_rows[0]["goal_points"], "6")
        self.assertEqual(result.scoring_rows[0]["assist_points"], "3")
        self.assertEqual(result.scoring_rows[0]["author_points"], "9")

    def test_builds_leaderboard_and_match_analytics_rows(self) -> None:
        result = calculate_scoring(
            predictions=[
                LatestPrediction(
                    participant_id="p1",
                    match_id="m1",
                    scores=("2-1", "1-1", "1-0", "0-0", "2-0", "1-2", "0-1"),
                    author_team1="Игрок A",
                    author_team2="Игрок B",
                ),
                LatestPrediction(
                    participant_id="p2",
                    match_id="m1",
                    scores=("1-1", "2-1", "1-0", "0-0", "2-0", "1-2", "0-1"),
                    author_team1="Игрок A",
                    author_team2="Игрок C",
                ),
            ],
            results=[
                MatchResult(
                    match_id="m1",
                    actual_score="2-1",
                    goals=("Игрок A",),
                    assists=("Игрок B",),
                )
            ],
            participants=[
                Participant(participant_id="p1", display_name="Игрок 1"),
                Participant(participant_id="p2", display_name="Игрок 2"),
            ],
            matches=[
                Match(
                    match_id="m1",
                    group="A",
                    tour="1",
                    kickoff_msk=datetime(2026, 6, 12, 20, 0, tzinfo=ZoneInfo("Europe/Moscow")),
                    deadline_msk=datetime(2026, 6, 12, 19, 55, tzinfo=ZoneInfo("Europe/Moscow")),
                    team1="Команда A",
                    team2="Команда B",
                )
            ],
            now_iso="2026-06-12T23:00:00+03:00",
        )

        self.assertIn("leaderboard_by_score", result.analytics_rows)
        self.assertIn("match_author_picks", result.analytics_rows)
        self.assertIn("match_first_score_belief", result.analytics_rows)
        author_rows = result.analytics_rows["match_author_picks"]
        self.assertEqual(author_rows[0]["player_name"], "Игрок A")
        self.assertEqual(author_rows[0]["pick_count"], "2")
        belief_rows = result.analytics_rows["match_first_score_belief"]
        self.assertEqual(belief_rows[0]["match_name"], "Команда A - Команда B")

    def test_leaderboard_tie_breaks_by_later_stage_points(self) -> None:
        result = calculate_scoring(
            predictions=[
                LatestPrediction("p1", "final", ("0-0", "1-0", "2-0", "2-1", "1-2", "0-1", "3-0"), "", ""),
                LatestPrediction("p1", "group", ("0-0", "1-1", "2-0", "2-1", "1-2", "0-1", "3-0"), "", ""),
                LatestPrediction("p2", "final", ("0-0", "1-1", "2-0", "1-0", "2-1", "1-2", "0-1"), "", ""),
                LatestPrediction("p2", "group", ("0-0", "1-1", "2-0", "2-1", "1-2", "1-0", "0-1"), "", ""),
            ],
            results=[
                MatchResult(match_id="final", actual_score="1-0"),
                MatchResult(match_id="group", actual_score="1-0"),
            ],
            participants=[
                Participant(participant_id="p1", display_name="Игрок 1"),
                Participant(participant_id="p2", display_name="Игрок 2"),
            ],
            matches=[
                Match(
                    match_id="final",
                    group="",
                    tour="Финал",
                    kickoff_msk=datetime(2026, 7, 19, 20, 0, tzinfo=ZoneInfo("Europe/Moscow")),
                    deadline_msk=datetime(2026, 7, 19, 19, 55, tzinfo=ZoneInfo("Europe/Moscow")),
                    team1="A",
                    team2="B",
                ),
                Match(
                    match_id="group",
                    group="",
                    tour="Группа",
                    kickoff_msk=datetime(2026, 6, 15, 20, 0, tzinfo=ZoneInfo("Europe/Moscow")),
                    deadline_msk=datetime(2026, 6, 15, 19, 55, tzinfo=ZoneInfo("Europe/Moscow")),
                    team1="C",
                    team2="D",
                ),
            ],
            now_iso="2026-07-20T12:00:00+03:00",
        )

        self.assertEqual(result.leaderboard_rows[0]["display_name"], "Игрок 1")
        self.assertEqual(result.leaderboard_rows[0]["total_points"], result.leaderboard_rows[1]["total_points"])
        self.assertGreater(
            int(result.leaderboard_rows[0]["final_points"]),
            int(result.leaderboard_rows[1]["final_points"]),
        )


if __name__ == "__main__":
    unittest.main()
