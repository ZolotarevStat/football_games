from __future__ import annotations

import unittest
from datetime import timedelta
from dataclasses import replace

from wc_predictions_bot.bot import PredictionBot
from wc_predictions_bot.config import Config
from wc_predictions_bot.fake_repository import FakeRepository
from wc_predictions_bot.models import LatestPrediction, Match, MatchResult, Player
from wc_predictions_bot.telegram_api import RecordingTelegramApi


def make_config(open_registration_enabled: bool = False) -> Config:
    return replace(Config.from_env(), open_registration_enabled=open_registration_enabled)


def message_update(text: str, telegram_id: int = 100, username: str = "user", chat_type: str = "private") -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": telegram_id, "type": chat_type},
            "from": {"id": telegram_id, "username": username, "first_name": "Test", "last_name": "User"},
            "text": text,
        },
    }


def callback_update(data: str, telegram_id: int = 100, username: str = "user", update_id: int = 2) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "from": {"id": telegram_id, "username": username},
            "message": {"message_id": update_id, "chat": {"id": telegram_id, "type": "private"}},
            "data": data,
        },
    }


class BotFlowTest(unittest.TestCase):
    def test_happy_path_saves_raw_and_latest(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict"))
        bot.handle_update(callback_update("m:m1"))
        bot.handle_update(message_update("1-0,1-1,2-0,0-0,2-1,1-2,0-1"))
        bot.handle_update(callback_update("a1:m1:0"))
        bot.handle_update(callback_update("a2:m1:0"))
        bot.handle_update(callback_update("save:m1"))

        self.assertEqual(len(repo.raw_rows), 1)
        self.assertEqual(len(repo.latest), 1)
        self.assertEqual(repo.latest[0].author_team1, "Месси")
        self.assertEqual(repo.latest[0].author_team2, "Мбаппе")
        self.assertIn((100, 2), tg.deleted_messages)

    def test_unbound_user_cannot_predict(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict", telegram_id=999))

        self.assertFalse(repo.raw_rows)
        self.assertIn("Код не найден", tg.messages[-1][1])

    def test_open_registration_start_without_pin_creates_participant(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(open_registration_enabled=True), repo, tg)

        bot.handle_update(message_update("/start", telegram_id=999, username="new_user"))

        participant = repo.get_participant_by_telegram_id("999")
        self.assertIsNotNone(participant)
        self.assertEqual(participant.display_name, "Test User")
        self.assertIn("Готово", tg.messages[-1][1])

    def test_open_registration_predict_without_pin_shows_matches(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(open_registration_enabled=True), repo, tg)

        bot.handle_update(message_update("/predict", telegram_id=999, username="new_user"))

        self.assertIsNotNone(repo.get_participant_by_telegram_id("999"))
        self.assertIn("Выберите матч", tg.messages[0][1])

    def test_invite_code_cannot_rebind_existing_participant_to_other_user(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/start PIN100", telegram_id=999))

        self.assertIn("Код не найден", tg.messages[-1][1])

    def test_deadline_blocks_match_callback(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(callback_update("m:m2"))

        self.assertIn("Дедлайн", tg.messages[-1][1])

    def test_used_author_is_hidden_from_buttons(self) -> None:
        repo = FakeRepository()
        repo.latest.append(
            LatestPrediction(
                participant_id="p1",
                match_id="other",
                scores=tuple(["1-0"] * 7),
                author_team1="Месси",
                author_team2="Гризманн",
            )
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(callback_update("m:m1"))
        bot.handle_update(message_update("1-0,1-1,2-0,0-0,2-1,1-2,0-1"))

        keyboard = tg.messages[-1][2]["inline_keyboard"]
        button_names = [button["text"] for row in keyboard for button in row]
        self.assertNotIn("Месси", button_names)
        self.assertIn("Альварес", button_names)
        self.assertEqual(len(repo.raw_rows), 0)

    def test_author_buttons_show_top_5_preview_and_full_list_button(self) -> None:
        repo = FakeRepository()
        for rank in range(3, 13):
            repo.players.append(
                Player(
                    team="Аргентина",
                    player_name_ru=f"Игрок {rank}",
                    priority=100 - rank,
                    top_rank_in_team=rank,
                )
            )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(callback_update("m:m1"))
        bot.handle_update(message_update("1-0,1-1,2-0,0-0,2-1,1-2,0-1"))

        keyboard = tg.messages[-1][2]["inline_keyboard"]
        button_names = [button["text"] for row in keyboard for button in row]
        self.assertNotIn("Игрок 12", button_names)
        self.assertEqual(button_names[-1], "Показать полный список")
        self.assertEqual(len(button_names), 6)

        bot.handle_update(callback_update("full:a1:m1", update_id=3))

        keyboard = tg.messages[-1][2]["inline_keyboard"]
        button_names = [button["text"] for row in keyboard for button in row]
        self.assertIn("Игрок 12", button_names)
        self.assertEqual(len(button_names), 12)
        self.assertIn((100, 3), tg.deleted_messages)

    def test_admin_publish_locks_and_posts_to_tournament_chat(self) -> None:
        repo = FakeRepository()
        repo.latest.append(
            LatestPrediction(
                participant_id="p1",
                match_id="m2",
                scores=tuple(["1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"]),
                author_team1="Винисиус",
                author_team2="Ямаль",
            )
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/publish m2", telegram_id=101, username="az_stat"))

        self.assertIn("m2", repo.locked_matches)
        self.assertIn("Закрытые прогнозы", tg.messages[-2][1])

    def test_submit_command_saves_without_callbacks(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(
            message_update(
                "/submit m1 1-0,1-1,2-0,0-0,2-1,1-2,0-1 | Месси | Мбаппе"
            )
        )

        self.assertEqual(len(repo.raw_rows), 1)
        self.assertEqual(repo.latest[0].match_id, "m1")
        self.assertIn("Прогноз сохранен", tg.messages[-1][1])

    def test_submit_command_suggests_roster_player_for_manual_typo(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(
            message_update(
                "/submit m1 1-0,1-1,2-0,0-0,2-1,1-2,0-1 | Месс | Мбаппе"
            )
        )

        self.assertEqual(len(repo.raw_rows), 0)
        self.assertIn("Возможно, вы имели в виду", tg.messages[-1][1])
        self.assertIn("- Месси", tg.messages[-1][1])

    def test_authors_command_updates_only_authors(self) -> None:
        repo = FakeRepository()
        repo.latest.append(
            LatestPrediction(
                participant_id="p1",
                match_id="m1",
                scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                author_team1="Месси",
                author_team2="Мбаппе",
            )
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/authors m1 | Альварес | Гризманн"))

        self.assertEqual(len(repo.raw_rows), 1)
        self.assertEqual(repo.latest[0].scores, ("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"))
        self.assertEqual(repo.latest[0].author_team1, "Альварес")
        self.assertEqual(repo.latest[0].author_team2, "Гризманн")
        self.assertIn("Авторы обновлены", tg.messages[-1][1])

    def test_authors_command_requires_existing_prediction(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/authors m1 | Альварес | Гризманн"))

        self.assertEqual(len(repo.raw_rows), 0)
        self.assertIn("еще нет прогноза", tg.messages[-1][1])

    def test_authors_command_suggests_roster_player_for_typo(self) -> None:
        repo = FakeRepository()
        repo.latest.append(
            LatestPrediction(
                participant_id="p1",
                match_id="m1",
                scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                author_team1="Месси",
                author_team2="Мбаппе",
            )
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/authors m1 | Альвар | Гризманн"))

        self.assertEqual(len(repo.raw_rows), 0)
        self.assertIn("Возможно, вы имели в виду", tg.messages[-1][1])
        self.assertIn("- Альварес", tg.messages[-1][1])
        self.assertIn("/authors", tg.messages[-1][1])

    def test_submit_command_is_private_only(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(
            message_update(
                "/submit m1 1-0,1-1,2-0,0-0,2-1,1-2,0-1 | Месси | Мбаппе",
                chat_type="supergroup",
            )
        )

        self.assertEqual(len(repo.raw_rows), 0)
        self.assertIn("только в личке", tg.messages[-1][1])

    def test_my_predictions_use_flags_and_hide_match_id_when_match_exists(self) -> None:
        repo = FakeRepository()
        repo.latest.append(
            LatestPrediction(
                participant_id="p1",
                match_id="m1",
                scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                author_team1="Месси",
                author_team2="Мбаппе",
            )
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/my"))

        text = tg.messages[-1][1]
        self.assertIn("🇦🇷 Аргентина - Франция 🇫🇷", text)
        self.assertIn("1️⃣ 1-0", text)
        self.assertNotIn("m1:", text)

    def test_admin_score_recalculates_leaderboard(self) -> None:
        repo = FakeRepository()
        repo.latest.append(
            LatestPrediction(
                participant_id="p1",
                match_id="m2",
                scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                author_team1="Винисиус",
                author_team2="Ямаль",
            )
        )
        repo.results.append(
            MatchResult(
                match_id="m2",
                actual_score="1-0",
                goals=("Винисиус",),
                assists=("Ямаль",),
            )
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/score all", telegram_id=101, username="az_stat"))

        self.assertEqual(repo.scoring_rows[0]["total_points"], "18")
        self.assertEqual(repo.leaderboard_rows[0]["display_name"], "Тестовый участник")
        self.assertIn("🏆 Таблица", tg.messages[-1][1])
        self.assertIn("Тестовый участник", tg.messages[-1][1])

    def test_group_plain_text_is_ignored(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("Ура!", chat_type="supergroup"))

        self.assertEqual(tg.messages, [])

    def test_group_command_with_bot_mention_is_normalized(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/my@tii_wc_predictions_2026_bot", chat_type="supergroup"))

        self.assertIn("только в личке", tg.messages[-1][1])

    def test_predict_shows_only_next_three_days(self) -> None:
        repo = FakeRepository()
        base_match = repo.matches["m1"]
        repo.matches["m3"] = Match(
            match_id="m3",
            group="B",
            tour="2",
            kickoff_msk=base_match.kickoff_msk + timedelta(days=5),
            deadline_msk=base_match.deadline_msk + timedelta(days=5),
            team1="Аргентина",
            team2="Франция",
            status="open",
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict"))

        keyboard = tg.messages[0][2]["inline_keyboard"]
        callback_ids = [button["callback_data"] for row in keyboard for button in row]
        self.assertIn("m:m1", callback_ids)
        self.assertNotIn("m:m3", callback_ids)

    def test_predict_falls_back_to_first_three_match_days_before_tournament_start(self) -> None:
        repo = FakeRepository()
        base_match = repo.matches["m1"]
        repo.matches["m1"] = Match(
            match_id="m1",
            group=base_match.group,
            tour=base_match.tour,
            kickoff_msk=base_match.kickoff_msk + timedelta(days=5),
            deadline_msk=base_match.deadline_msk + timedelta(days=5),
            team1=base_match.team1,
            team2=base_match.team2,
            status="open",
        )
        repo.matches["m3"] = Match(
            match_id="m3",
            group="B",
            tour="2",
            kickoff_msk=base_match.kickoff_msk + timedelta(days=9),
            deadline_msk=base_match.deadline_msk + timedelta(days=9),
            team1="Аргентина",
            team2="Франция",
            status="open",
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict"))

        keyboard = tg.messages[0][2]["inline_keyboard"]
        callback_ids = [button["callback_data"] for row in keyboard for button in row]
        self.assertIn("m:m1", callback_ids)
        self.assertNotIn("m:m3", callback_ids)


if __name__ == "__main__":
    unittest.main()
