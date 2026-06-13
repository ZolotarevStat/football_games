from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dataclasses import replace

from wc_predictions_bot.bot import PredictionBot
from wc_predictions_bot.config import Config
from wc_predictions_bot.fake_repository import FakeRepository
from wc_predictions_bot.models import LatestPrediction, Match, MatchResult, Player
from wc_predictions_bot.sheets_repository import GoogleSheetsQuotaExceededError
from wc_predictions_bot.telegram_api import RecordingTelegramApi


def make_config(
    open_registration_enabled: bool = False,
    allowed_usernames: frozenset[str] = frozenset(),
    tournament_chat_id: str = "",
    admin_usernames: frozenset[str] = frozenset(),
) -> Config:
    return replace(
        Config.from_env(),
        open_registration_enabled=open_registration_enabled,
        allowed_usernames=allowed_usernames,
        tournament_chat_id=tournament_chat_id,
        admin_usernames=admin_usernames,
    )


def message_update(
    text: str,
    telegram_id: int = 100,
    username: str = "user",
    chat_type: str = "private",
    chat_id: int | None = None,
) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": telegram_id if chat_id is None else chat_id, "type": chat_type},
            "from": {"id": telegram_id, "username": username, "first_name": "Test", "last_name": "User"},
            "text": text,
        },
    }


def callback_update(
    data: str,
    telegram_id: int = 100,
    username: str = "user",
    update_id: int = 2,
    chat_type: str = "private",
    chat_id: int | None = None,
) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "from": {"id": telegram_id, "username": username},
            "message": {"message_id": update_id, "chat": {"id": telegram_id if chat_id is None else chat_id, "type": chat_type}},
            "data": data,
        },
    }


class FailingTelegramApi(RecordingTelegramApi):
    def __init__(self, failing_chat_id: str | int) -> None:
        super().__init__()
        self.failing_chat_id = str(failing_chat_id)

    def send_message(self, chat_id, text, reply_markup=None, parse_mode=None) -> None:
        if str(chat_id) == self.failing_chat_id:
            raise RuntimeError('Telegram sendMessage failed: 400 {"description":"Bad Request: chat not found"}')
        super().send_message(chat_id, text, reply_markup, parse_mode)


class QuotaFailingSaveRepository(FakeRepository):
    def save_prediction(self, **kwargs):
        raise GoogleSheetsQuotaExceededError("Quota exceeded for quota metric 'Write requests'")


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
        button_names = [button["text"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("📝 Сделать прогноз", button_names)
        self.assertIn("🔒 Мои прогнозы", button_names)

    def test_open_registration_predict_without_pin_shows_matches(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(open_registration_enabled=True), repo, tg)

        bot.handle_update(message_update("/predict", telegram_id=999, username="new_user"))

        self.assertIsNotNone(repo.get_participant_by_telegram_id("999"))
        self.assertIn("Выберите матч", tg.messages[0][1])

    def test_open_registration_allows_username_from_allowlist(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(
            make_config(open_registration_enabled=True, allowed_usernames=frozenset({"new_user"})),
            repo,
            tg,
        )

        bot.handle_update(message_update("/predict", telegram_id=999, username="new_user"))

        self.assertIsNotNone(repo.get_participant_by_telegram_id("999"))
        self.assertIn("Выберите матч", tg.messages[0][1])

    def test_open_registration_rejects_username_outside_allowlist(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(
            make_config(open_registration_enabled=True, allowed_usernames=frozenset({"allowed_user"})),
            repo,
            tg,
        )

        bot.handle_update(message_update("/predict", telegram_id=999, username="new_user"))

        self.assertIsNone(repo.get_participant_by_telegram_id("999"))
        self.assertIn("добавить @new_user", tg.messages[-1][1])

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

    def test_matches_command_shows_compact_open_match_ids_without_binding(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/matches", telegram_id=999, chat_type="supergroup"))

        self.assertIn("Ближайшие открытые матчи", tg.messages[-1][1])
        self.assertIn("m1", tg.messages[-1][1])
        self.assertNotIn("m2", tg.messages[-1][1])

    def test_matches_command_marks_matches_with_saved_prediction_in_private_chat(self) -> None:
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

        bot.handle_update(message_update("/matches"))

        self.assertIn("✅ m1 — Аргентина - Франция", tg.messages[-1][1])
        button_names = [button["text"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("📝 Сделать прогноз", button_names)

    def test_predict_message_is_single_deletable_block(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict"))
        bot.handle_update(callback_update("back", update_id=2))

        self.assertEqual(len(tg.messages), 2)
        self.assertIn("Выберите матч", tg.messages[0][1])
        self.assertIn("Открытые MATCH_ID", tg.messages[0][1])
        self.assertIn("Выберите действие", tg.messages[-1][1])
        self.assertIn((100, 2), tg.deleted_messages)

    def test_dashboard_close_deletes_without_recreating_dashboard(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/start"))
        bot.handle_update(callback_update("close", update_id=2))

        self.assertEqual(len(tg.messages), 1)
        self.assertIn((100, 2), tg.deleted_messages)

    def test_rules_command_is_available_without_binding(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/rules", telegram_id=999, chat_type="supergroup"))

        self.assertIn("Правила прогноза", tg.messages[-1][1])

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
        repo.latest.append(
            LatestPrediction(
                participant_id="p1",
                match_id="other2",
                scores=tuple(["1-0"] * 7),
                author_team1="Винисиус",
                author_team2="Ямаль",
            )
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(callback_update("m:m1"))
        self.assertIn("Вы выбрали матч: Аргентина - Франция", tg.messages[-1][1])
        self.assertIn("Уже задействованы", tg.messages[-1][1])
        self.assertIn("Месси", tg.messages[-1][1])
        self.assertIn("Гризманн", tg.messages[-1][1])
        self.assertNotIn("Винисиус", tg.messages[-1][1])
        self.assertNotIn("Ямаль", tg.messages[-1][1])
        bot.handle_update(message_update("1-0,1-1,2-0,0-0,2-1,1-2,0-1"))

        keyboard = tg.messages[-1][2]["inline_keyboard"]
        button_names = [button["text"] for row in keyboard for button in row]
        self.assertNotIn("Месси", button_names)
        self.assertIn("Альварес", button_names)
        self.assertIn("Скрыты, потому что уже выбраны", tg.messages[-1][1])
        self.assertIn("Месси", tg.messages[-1][1])
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
        self.assertIn("Показать полный список", button_names)
        self.assertEqual(button_names[-1], "↩️ Назад")
        self.assertEqual(len(button_names), 7)

        bot.handle_update(callback_update("full:a1:m1", update_id=3))

        keyboard = tg.messages[-1][2]["inline_keyboard"]
        button_names = [button["text"] for row in keyboard for button in row]
        self.assertIn("Игрок 12", button_names)
        self.assertEqual(button_names[-1], "↩️ Назад")
        self.assertEqual(len(button_names), 13)
        self.assertIn((100, 3), tg.deleted_messages)

    def test_back_callback_deletes_active_message(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(callback_update("back", update_id=9))

        self.assertIn((100, 9), tg.deleted_messages)
        self.assertIn("Выберите действие", tg.messages[-1][1])

    def test_back_from_second_author_returns_to_first_author_without_losing_scores(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict"))
        bot.handle_update(callback_update("m:m1", update_id=2))
        bot.handle_update(message_update("1-0,1-1,2-0,0-0,2-1,1-2,0-1"))
        bot.handle_update(callback_update("a1:m1:0", update_id=3))
        bot.handle_update(callback_update("back", update_id=4))

        self.assertIn((100, 4), tg.deleted_messages)
        self.assertIn("Выберите автора Г+П для первой команды", tg.messages[-1][1])
        button_names = [button["text"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("Месси", button_names)
        self.assertIn("Альварес", button_names)

        bot.handle_update(callback_update("a1:m1:1", update_id=5))
        bot.handle_update(callback_update("a2:m1:0", update_id=6))
        bot.handle_update(callback_update("save:m1", update_id=7))

        self.assertEqual(repo.latest[0].scores, ("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"))
        self.assertEqual(repo.latest[0].author_team1, "Альварес")
        self.assertEqual(repo.latest[0].author_team2, "Мбаппе")

    def test_back_from_first_author_returns_to_score_input_for_same_match(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict"))
        bot.handle_update(callback_update("m:m1", update_id=2))
        bot.handle_update(message_update("1-0,1-1,2-0,0-0,2-1,1-2,0-1"))
        bot.handle_update(callback_update("back", update_id=3))

        self.assertIn((100, 3), tg.deleted_messages)
        self.assertIn("Введите новые 7 счетов для матча Аргентина - Франция", tg.messages[-1][1])
        self.assertIn("Текущие счета: 1-0, 1-1, 2-0, 0-0, 2-1, 1-2, 0-1", tg.messages[-1][1])

        bot.handle_update(message_update("2-0,1-0,1-1,0-0,2-1,1-2,0-1"))
        bot.handle_update(callback_update("a1:m1:0", update_id=4))
        bot.handle_update(callback_update("a2:m1:0", update_id=5))
        bot.handle_update(callback_update("save:m1", update_id=6))

        self.assertEqual(repo.latest[0].scores, ("2-0", "1-0", "1-1", "0-0", "2-1", "1-2", "0-1"))

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

        bot.handle_update(message_update("/publish m2", telegram_id=101, username="organizer_username"))

        self.assertIn("m2", repo.locked_matches)
        self.assertIn("Прогнозы закрыты", tg.messages[-2][1])
        self.assertIn("Тестовый участник", tg.messages[-2][1])
        self.assertNotIn("p1:", tg.messages[-2][1])

    def test_admin_publish_in_group_uses_current_chat_over_configured_chat(self) -> None:
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
        tg = FailingTelegramApi(failing_chat_id="-999")
        bot = PredictionBot(make_config(tournament_chat_id="-999"), repo, tg)

        bot.handle_update(
            message_update(
                "/publish m2",
                telegram_id=101,
                username="organizer_username",
                chat_type="supergroup",
                chat_id=-1001,
            )
        )

        self.assertIn("m2", repo.locked_matches)
        self.assertEqual(tg.messages[-2][0], -1001)
        self.assertIn("Прогнозы закрыты", tg.messages[-2][1])

    def test_admin_publish_private_reports_bad_configured_chat_without_locking(self) -> None:
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
        tg = FailingTelegramApi(failing_chat_id="-999")
        bot = PredictionBot(make_config(tournament_chat_id="-999"), repo, tg)

        bot.handle_update(message_update("/publish m2", telegram_id=101, username="organizer_username"))

        self.assertNotIn("m2", repo.locked_matches)
        self.assertIn("Проверьте TOURNAMENT_CHAT_ID", tg.messages[-1][1])

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
        button_names = [button["text"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("🔒 Мои прогнозы", button_names)

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

    def test_scores_command_updates_only_scores(self) -> None:
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

        bot.handle_update(message_update("/scores m1 2-0,1-0,1-1,0-0,2-1,1-2,0-1"))

        self.assertEqual(len(repo.raw_rows), 1)
        self.assertEqual(repo.latest[0].scores, ("2-0", "1-0", "1-1", "0-0", "2-1", "1-2", "0-1"))
        self.assertEqual(repo.latest[0].author_team1, "Месси")
        self.assertEqual(repo.latest[0].author_team2, "Мбаппе")
        self.assertIn("Счета обновлены", tg.messages[-1][1])

    def test_scores_command_requires_existing_prediction(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/scores m1 2-0,1-0,1-1,0-0,2-1,1-2,0-1"))

        self.assertEqual(len(repo.raw_rows), 0)
        self.assertIn("еще нет прогноза", tg.messages[-1][1])

    def test_confirmation_can_edit_scores_without_reselecting_authors(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict"))
        bot.handle_update(callback_update("m:m1"))
        bot.handle_update(message_update("1-0,1-1,2-0,0-0,2-1,1-2,0-1"))
        bot.handle_update(callback_update("a1:m1:0"))
        bot.handle_update(callback_update("a2:m1:0"))
        bot.handle_update(callback_update("edit_scores:m1"))
        bot.handle_update(message_update("2-0,1-0,1-1,0-0,2-1,1-2,0-1"))
        bot.handle_update(callback_update("save:m1"))

        self.assertEqual(repo.latest[0].scores, ("2-0", "1-0", "1-1", "0-0", "2-1", "1-2", "0-1"))
        self.assertEqual(repo.latest[0].author_team1, "Месси")
        self.assertEqual(repo.latest[0].author_team2, "Мбаппе")

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
        button_names = [button["text"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("📝 Сделать прогноз", button_names)
        self.assertTrue(any(name.startswith("✏️ Счета: Аргентина-Франция") for name in button_names))
        self.assertTrue(any(name.startswith("🧩 Авторы: Аргентина-Франция") for name in button_names))

    def test_my_predictions_hides_closed_matches_and_keeps_only_active_edit_buttons(self) -> None:
        repo = FakeRepository()
        repo.latest.extend(
            [
                LatestPrediction(
                    participant_id="p1",
                    match_id="m1",
                    scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                    author_team1="Месси",
                    author_team2="Мбаппе",
                ),
                LatestPrediction(
                    participant_id="p1",
                    match_id="m2",
                    scores=("2-0", "1-0", "1-1", "0-0", "2-1", "1-2", "0-1"),
                    author_team1="Винисиус",
                    author_team2="Ямаль",
                ),
            ]
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/my"))

        text = tg.messages[-1][1]
        self.assertIn("Аргентина - Франция", text)
        self.assertNotIn("Бразилия", text)
        button_names = [button["text"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertTrue(any(name.startswith("✏️ Счета: Аргентина-Франция") for name in button_names))
        self.assertFalse(any(name.startswith("✏️ Счета: Бразилия-Испания") for name in button_names))

    def test_my_predictions_limits_to_five_active_predictions_and_can_show_all(self) -> None:
        repo = FakeRepository()
        base_match = repo.matches["m1"]
        repo.latest.append(
            LatestPrediction(
                participant_id="p1",
                match_id="m1",
                scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                author_team1="Месси",
                author_team2="Мбаппе",
            )
        )
        for index in range(3, 9):
            repo.matches[f"m{index}"] = Match(
                match_id=f"m{index}",
                group="B",
                tour=str(index),
                kickoff_msk=base_match.kickoff_msk + timedelta(days=index),
                deadline_msk=base_match.deadline_msk + timedelta(days=index),
                team1="Аргентина",
                team2="Франция",
                status="open",
            )
            repo.latest.append(
                LatestPrediction(
                    participant_id="p1",
                    match_id=f"m{index}",
                    scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                    author_team1="Месси",
                    author_team2="Мбаппе",
                )
            )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/my"))

        button_data = [button["callback_data"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("my:all", button_data)
        self.assertIn("edit_saved_scores:m1", button_data)
        self.assertIn("edit_saved_scores:m6", button_data)
        self.assertNotIn("edit_saved_scores:m7", button_data)

        bot.handle_update(callback_update("my:all", update_id=3))

        button_data = [button["callback_data"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("edit_saved_scores:m8", button_data)

    def test_scores_without_match_id_opens_active_prediction_picker_and_edits_selected_match(self) -> None:
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

        bot.handle_update(message_update("/scores"))
        self.assertIn("Выберите прогноз, где заменить счета", tg.messages[-1][1])
        button_data = [button["callback_data"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("edit_saved_scores:m1", button_data)

        bot.handle_update(callback_update("edit_saved_scores:m1", update_id=3))

        self.assertIn("Введите новые 7 счетов", tg.messages[-1][1])
        bot.handle_update(message_update("2-0,1-0,1-1,0-0,2-1,1-2,0-1"))
        bot.handle_update(callback_update("save:m1", update_id=4))

        self.assertEqual(repo.latest[0].scores, ("2-0", "1-0", "1-1", "0-0", "2-1", "1-2", "0-1"))

    def test_authors_without_match_id_opens_active_prediction_picker_and_reselects_authors(self) -> None:
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

        bot.handle_update(message_update("/authors"))
        self.assertIn("Выберите прогноз, где заменить авторов", tg.messages[-1][1])
        button_data = [button["callback_data"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("edit_saved_authors:m1", button_data)

        bot.handle_update(callback_update("edit_saved_authors:m1", update_id=3))

        self.assertIn("Выберите автора Г+П для первой команды", tg.messages[-1][1])
        bot.handle_update(callback_update("a1:m1:1", update_id=4))
        bot.handle_update(callback_update("a2:m1:1", update_id=5))
        bot.handle_update(callback_update("save:m1", update_id=6))

        self.assertEqual(repo.latest[0].scores, ("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"))
        self.assertEqual(repo.latest[0].author_team1, "Альварес")
        self.assertEqual(repo.latest[0].author_team2, "Гризманн")

    def test_scores_quota_failure_returns_forwardable_requested_change(self) -> None:
        repo = QuotaFailingSaveRepository()
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

        bot.handle_update(message_update("/scores m1 2-0,1-0,1-1,0-0,2-1,1-2,0-1"))

        text = tg.messages[-1][1]
        self.assertIn("Вы хотели изменить счета в матче m1", text)
        self.assertIn("Счета: 2-0, 1-0, 1-1, 0-0, 2-1, 1-2, 0-1", text)
        self.assertIn("Автор Аргентина: Месси", text)
        self.assertIn("переполнения квоты запросов к Google Sheets", text)
        self.assertIn("Перешлите это сообщение организатору", text)

    def test_authors_quota_failure_returns_forwardable_requested_change(self) -> None:
        repo = QuotaFailingSaveRepository()
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

        text = tg.messages[-1][1]
        self.assertIn("Вы хотели изменить авторов в матче m1", text)
        self.assertIn("Счета: 1-0, 1-1, 2-0, 0-0, 2-1, 1-2, 0-1", text)
        self.assertIn("Автор Аргентина: Альварес", text)
        self.assertIn("Автор Франция: Гризманн", text)

    def test_interactive_save_quota_failure_preserves_requested_prediction(self) -> None:
        repo = QuotaFailingSaveRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict"))
        bot.handle_update(callback_update("m:m1"))
        bot.handle_update(message_update("1-0,1-1,2-0,0-0,2-1,1-2,0-1"))
        bot.handle_update(callback_update("a1:m1:0"))
        bot.handle_update(callback_update("a2:m1:0"))
        bot.handle_update(callback_update("save:m1"))

        text = tg.messages[-1][1]
        self.assertIn("Вы хотели сохранить или изменить прогноз в матче m1", text)
        self.assertIn("Автор Аргентина: Месси", text)
        self.assertIn("Автор Франция: Мбаппе", text)

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

        bot.handle_update(message_update("/score all", telegram_id=101, username="organizer_username"))

        self.assertEqual(repo.scoring_rows[0]["total_points"], "18")
        self.assertEqual(repo.analytics_rows["leaderboard_by_total"][0]["display_name"], "Тестовый участник")
        self.assertEqual(repo.leaderboard_rows[0]["display_name"], "Тестовый участник")
        self.assertIn("🏆 Таблица", tg.messages[-1][1])
        self.assertIn("Тестовый участник", tg.messages[-1][1])
        self.assertIn("<pre>", tg.messages[-1][1])
        self.assertIn("| 18 | 12 | 4  | 2  ", tg.messages[-1][1])

    def test_admin_score_for_single_match_keeps_cumulative_sheets(self) -> None:
        repo = FakeRepository()
        repo.latest.extend(
            [
                LatestPrediction(
                    participant_id="p1",
                    match_id="m1",
                    scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                    author_team1="Месси",
                    author_team2="Мбаппе",
                ),
                LatestPrediction(
                    participant_id="p1",
                    match_id="m2",
                    scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                    author_team1="Винисиус",
                    author_team2="Ямаль",
                ),
            ]
        )
        repo.results.extend(
            [
                MatchResult(match_id="m1", actual_score="1-0", goals=("Месси",)),
                MatchResult(match_id="m2", actual_score="1-0", goals=("Винисиус",), assists=("Ямаль",)),
            ]
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/score m2", telegram_id=101, username="organizer_username"))

        self.assertEqual(len(repo.scoring_rows), 2)
        self.assertEqual(repo.leaderboard_rows[0]["total_points"], "34")
        self.assertIn("Пересчет по m2", tg.messages[-1][1])
        self.assertIn("Матчей с результатами в таблицах: 2", tg.messages[-1][1])
        self.assertIn("Бразилия - Испания: 1-0", tg.messages[-1][1])
        self.assertIn("🏆 Очки по матчу", tg.messages[-1][1])
        self.assertIn("| 18 | 12 | 4  | 2  ", tg.messages[-1][1])

    def test_user_analytics_shows_recent_finished_prediction_breakdown(self) -> None:
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

        bot.handle_update(message_update("/analytics"))

        message = tg.messages[-1][1]
        self.assertIn("последние 24 часа", message)
        self.assertIn("<b>1-0</b>", message)
        self.assertIn("Очки: 18 = счет 12 + Г+П 6", message)
        self.assertIn("Винисиус (1+0)", message)
        self.assertIn("Ямаль (0+1)", message)
        button_data = [button["callback_data"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("analytics:tour", button_data)
        self.assertIn("analytics:all", button_data)

    def test_user_analytics_all_includes_finished_prediction_outside_24h(self) -> None:
        repo = FakeRepository()
        old_kickoff = datetime.now(ZoneInfo("Europe/Moscow")) - timedelta(days=3)
        repo.matches["old"] = Match(
            match_id="old",
            group="A",
            tour="0",
            kickoff_msk=old_kickoff,
            deadline_msk=old_kickoff - timedelta(minutes=5),
            team1="Бразилия",
            team2="Испания",
            status="open",
        )
        repo.latest.append(
            LatestPrediction(
                participant_id="p1",
                match_id="old",
                scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                author_team1="Винисиус",
                author_team2="Ямаль",
            )
        )
        repo.results.append(MatchResult(match_id="old", actual_score="1-0", goals=("Винисиус",)))
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/analytics"))
        self.assertNotIn("Бразилия - Испания", tg.messages[-1][1])

        bot.handle_update(callback_update("analytics:all", update_id=3))
        self.assertIn("Все ваши сыгранные прогнозы", tg.messages[-1][1])
        self.assertIn("Бразилия - Испания", tg.messages[-1][1])

    def test_user_analytics_is_private_only(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/analytics", chat_type="group", chat_id=-100))

        self.assertIn("только в личке", tg.messages[-1][1])

    def test_admin_status_shows_missing_participants_without_predictions(self) -> None:
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

        bot.handle_update(message_update("/status m1", telegram_id=101, username="organizer_username"))

        text = tg.messages[-1][1]
        self.assertIn("Статус прогнозов", text)
        self.assertIn("Сдали: 1/2", text)
        self.assertIn("Новый участник", text)

    def test_admin_status_without_match_id_opens_match_picker(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/status", telegram_id=101, username="organizer_username"))

        self.assertIn("Выберите матч для проверки статуса", tg.messages[-1][1])
        button_data = [button["callback_data"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("admin_action:status:m1", button_data)
        self.assertNotIn("admin_action:status:m2", button_data)

        bot.handle_update(callback_update("admin_action:status:m1", telegram_id=101, username="organizer_username", update_id=3))

        self.assertIn("Статус прогнозов: m1", tg.messages[-1][1])

    def test_admin_status_latest_uses_nearest_open_match(self) -> None:
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

        bot.handle_update(message_update("/status_latest", telegram_id=101, username="organizer_username"))

        text = tg.messages[-1][1]
        self.assertIn("Статус прогнозов: m1", text)
        self.assertIn("Сдали: 1/2", text)

    def test_status_latest_is_admin_only(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/status_latest", telegram_id=100, username="user"))

        self.assertIn("только организаторам", tg.messages[-1][1])

    def test_admin_insights_shows_match_prediction_aggregates(self) -> None:
        repo = FakeRepository()
        repo.latest.extend(
            [
                LatestPrediction(
                    participant_id="p1",
                    match_id="m1",
                    scores=("1-0", "1-1", "2-0", "0-0", "2-1", "1-2", "0-1"),
                    author_team1="Месси",
                    author_team2="Мбаппе",
                ),
                LatestPrediction(
                    participant_id="p2",
                    match_id="m1",
                    scores=("1-0", "2-1", "0-0", "1-1", "2-0", "1-2", "0-1"),
                    author_team1="Месси",
                    author_team2="Гризманн",
                ),
                LatestPrediction(
                    participant_id="admin",
                    match_id="m1",
                    scores=("1-1", "1-0", "2-0", "0-0", "2-1", "1-2", "0-1"),
                    author_team1="Альварес",
                    author_team2="Мбаппе",
                ),
            ]
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/insights m1", telegram_id=101, username="organizer_username"))

        text = tg.messages[-1][1]
        self.assertIn("Агрегаты прогнозов: m1", text)
        self.assertIn("Участников с прогнозом: 3", text)
        self.assertIn("Самый популярный 1-й счет: 1-0 (67%, 2/3)", text)
        self.assertIn("Самый популярный автор Г+П у Аргентина: Месси (67%, 2/3)", text)
        self.assertIn("Самый популярный автор Г+П у Франция: Мбаппе (67%, 2/3)", text)
        self.assertIn("Доли исходов по 1-м счетам: Аргентина 67% / ничья 33% / Франция 0%", text)
        self.assertIn("- Месси — 2", text)
        self.assertIn("- Альварес — 1", text)
        self.assertIn("- Мбаппе — 2", text)
        self.assertIn("- Гризманн — 1", text)

    def test_admin_insights_without_match_id_opens_prediction_match_picker(self) -> None:
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

        bot.handle_update(message_update("/insights", telegram_id=101, username="organizer_username"))

        self.assertIn("Выберите матч для агрегатов", tg.messages[-1][1])
        button_data = [button["callback_data"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("admin_action:insights:m1", button_data)

        bot.handle_update(callback_update("admin_action:insights:m1", telegram_id=101, username="organizer_username", update_id=3))

        self.assertIn("Агрегаты прогнозов: m1", tg.messages[-1][1])

    def test_admin_insights_is_admin_only(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/insights m1", telegram_id=100, username="user"))

        self.assertIn("только организаторам", tg.messages[-1][1])

    def test_admin_insights_allows_configured_username_without_bound_participant(self) -> None:
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
        bot = PredictionBot(make_config(admin_usernames=frozenset({"group_admin"})), repo, tg)

        bot.handle_update(message_update("/insights m1", telegram_id=999, username="group_admin", chat_type="supergroup"))

        self.assertIn("Агрегаты прогнозов: m1", tg.messages[-1][1])

    def test_admin_command_shows_admin_reference_only_to_admins(self) -> None:
        repo = FakeRepository()
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/admin", telegram_id=100, username="user"))
        self.assertIn("только организаторам", tg.messages[-1][1])

        bot.handle_update(message_update("/admin", telegram_id=101, username="organizer_username"))
        self.assertIn("Админские команды", tg.messages[-1][1])
        self.assertIn("/status MATCH_ID", tg.messages[-1][1])
        self.assertIn("/status_latest", tg.messages[-1][1])
        self.assertIn("/insights MATCH_ID", tg.messages[-1][1])
        button_data = [button["callback_data"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("admin_menu:status", button_data)
        self.assertIn("admin_menu:postmatch", button_data)
        self.assertIn("admin_menu:publish", button_data)
        self.assertIn("admin_menu:score", button_data)

    def test_admin_postmatch_button_sends_publish_insights_score_and_leaderboard(self) -> None:
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
        repo.results.append(MatchResult(match_id="m2", actual_score="1-0", goals=("Винисиус",), assists=("Ямаль",)))
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(
            callback_update(
                "admin_action:postmatch:m2",
                telegram_id=101,
                username="organizer_username",
                update_id=3,
                chat_type="supergroup",
                chat_id=-1001,
            )
        )

        texts = "\n".join(message[1] for message in tg.messages)
        self.assertIn("Итоги матча m2", texts)
        self.assertIn("Прогнозы закрыты", texts)
        self.assertIn("Агрегаты прогнозов: m2", texts)
        self.assertIn("Пересчет по m2", texts)
        self.assertIn("Таблица после игрового дня", texts)
        self.assertIn("m2", repo.locked_matches)

    def test_admin_publish_without_match_id_can_publish_from_group_picker(self) -> None:
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

        bot.handle_update(
            message_update(
                "/publish",
                telegram_id=101,
                username="organizer_username",
                chat_type="supergroup",
                chat_id=-1001,
            )
        )

        self.assertIn("Выберите матч для публикации", tg.messages[-1][1])
        button_data = [button["callback_data"] for row in tg.messages[-1][2]["inline_keyboard"] for button in row]
        self.assertIn("admin_action:publish:m2", button_data)

        bot.handle_update(
            callback_update(
                "admin_action:publish:m2",
                telegram_id=101,
                username="organizer_username",
                update_id=3,
                chat_type="supergroup",
                chat_id=-1001,
            )
        )

        self.assertIn("m2", repo.locked_matches)
        self.assertEqual(tg.messages[-2][0], -1001)
        self.assertIn("Прогнозы закрыты", tg.messages[-2][1])

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

    def test_predict_shows_at_least_five_nearest_matches(self) -> None:
        repo = FakeRepository()
        base_match = repo.matches["m1"]
        for index in range(3, 8):
            repo.matches[f"m{index}"] = Match(
                match_id=f"m{index}",
                group="B",
                tour=str(index),
                kickoff_msk=base_match.kickoff_msk + timedelta(days=index),
                deadline_msk=base_match.deadline_msk + timedelta(days=index),
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
        self.assertIn("m:m5", callback_ids)
        self.assertNotIn("m:m7", callback_ids)

    def test_predict_includes_all_matches_from_three_nearest_match_days(self) -> None:
        repo = FakeRepository()
        base_match = repo.matches["m1"]
        for index in range(3, 9):
            day_offset = 1 if index <= 5 else 2
            repo.matches[f"m{index}"] = Match(
                match_id=f"m{index}",
                group="B",
                tour="1",
                kickoff_msk=base_match.kickoff_msk + timedelta(days=day_offset, minutes=index),
                deadline_msk=base_match.deadline_msk + timedelta(days=day_offset, minutes=index),
                team1="Аргентина",
                team2="Франция",
                status="open",
            )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict"))

        keyboard = tg.messages[0][2]["inline_keyboard"]
        callback_ids = [button["callback_data"] for row in keyboard for button in row]
        self.assertIn("m:m8", callback_ids)

    def test_predict_can_show_all_matches_from_closest_tour(self) -> None:
        repo = FakeRepository()
        base_match = repo.matches["m1"]
        for index in range(3, 9):
            repo.matches[f"m{index}"] = Match(
                match_id=f"m{index}",
                group="B",
                tour="1",
                kickoff_msk=base_match.kickoff_msk + timedelta(days=index),
                deadline_msk=base_match.deadline_msk + timedelta(days=index),
                team1="Аргентина",
                team2="Франция",
                status="open",
            )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        bot.handle_update(message_update("/predict"))

        keyboard = tg.messages[0][2]["inline_keyboard"]
        callback_ids = [button["callback_data"] for row in keyboard for button in row]
        self.assertIn("tour:1", callback_ids)

        bot.handle_update(callback_update("tour:1", update_id=3))

        keyboard = tg.messages[-1][2]["inline_keyboard"]
        callback_ids = [button["callback_data"] for row in keyboard for button in row]
        self.assertIn("m:m8", callback_ids)

    def test_daily_notifications_send_once_to_participants_with_predictions(self) -> None:
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
        notification_now = datetime.now(ZoneInfo("Europe/Moscow")).replace(hour=12, minute=0, second=0, microsecond=0)
        repo.matches["m1"] = Match(
            match_id="m1",
            group="A",
            tour="1",
            kickoff_msk=notification_now + timedelta(hours=3),
            deadline_msk=notification_now + timedelta(hours=2, minutes=55),
            team1="Аргентина",
            team2="Франция",
            status="open",
        )
        tg = RecordingTelegramApi()
        bot = PredictionBot(make_config(), repo, tg)

        sent_count = bot.maybe_send_daily_match_notifications(notification_now)
        second_sent_count = bot.maybe_send_daily_match_notifications(notification_now)

        self.assertEqual(sent_count, 1)
        self.assertEqual(second_sent_count, 0)
        self.assertEqual(tg.messages[-1][0], "100")
        self.assertIn("Матчи ближайших 24 часов", tg.messages[-1][1])
        self.assertEqual(len(repo.notifications), 1)


if __name__ == "__main__":
    unittest.main()
