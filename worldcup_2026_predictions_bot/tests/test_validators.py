from __future__ import annotations

import unittest

from wc_predictions_bot.models import LatestPrediction, Player
from wc_predictions_bot.validators import (
    ValidationError,
    author_suggestions,
    ensure_authors_are_distinct,
    ensure_author_in_pool,
    ensure_author_not_used,
    parse_scores,
)


class ValidatorTest(unittest.TestCase):
    def test_parse_scores_accepts_seven_unique_scores(self) -> None:
        self.assertEqual(
            parse_scores("1-0, 1:1, 2-0,0-0,2-1,1-2,0-1"),
            ["1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"],
        )

    def test_parse_scores_rejects_duplicates(self) -> None:
        with self.assertRaises(ValidationError):
            parse_scores("1-0,1-0,2-0,0-0,2-1,1-2,0-1")

    def test_parse_scores_rejects_bad_format(self) -> None:
        with self.assertRaises(ValidationError):
            parse_scores("1-0,win,2-0,0-0,2-1,1-2,0-1")

    def test_author_pool_validation(self) -> None:
        players = [Player(team="A", player_name_ru="Игрок 1", top_rank_in_team=1)]
        ensure_author_in_pool("Игрок 1", players, "A", "Автор")
        with self.assertRaises(ValidationError):
            ensure_author_in_pool("Игрок 2", players, "A", "Автор")

    def test_authors_must_be_distinct(self) -> None:
        ensure_authors_are_distinct("Игрок 1", "Игрок 2")
        with self.assertRaises(ValidationError):
            ensure_authors_are_distinct("Игрок 1", " игрок  1 ")

    def test_author_suggestions_match_roster_player(self) -> None:
        players = [
            Player(team="Мексика", player_name_ru="Рауль Хименес", player_name_en="Raul Jimenez", top_rank_in_team=1),
            Player(team="Мексика", player_name_ru="Сантьяго Хименес", player_name_en="Santiago Gimenez", top_rank_in_team=2),
            Player(team="ЮАР", player_name_ru="Икраам Рейнерс", top_rank_in_team=1),
        ]

        self.assertEqual(author_suggestions("Хименес", players, "Мексика")[:2], ["Рауль Хименес", "Сантьяго Хименес"])
        self.assertEqual(author_suggestions("Raul Jimenez", players, "Мексика")[:1], ["Рауль Хименес"])

    def test_duplicate_author_excludes_same_match_edit(self) -> None:
        latest = [
            LatestPrediction("p1", "m1", tuple(["1-0"] * 7), "Месси", "Мбаппе"),
            LatestPrediction("p1", "m2", tuple(["1-0"] * 7), "Альварес", "Гризманн"),
        ]
        ensure_author_not_used("Месси", latest, "m1")
        with self.assertRaises(ValidationError):
            ensure_author_not_used("Месси", latest, "m3")


if __name__ == "__main__":
    unittest.main()
