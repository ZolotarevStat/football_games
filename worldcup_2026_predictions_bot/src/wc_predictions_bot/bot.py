from __future__ import annotations

import html
import logging
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from .config import Config
from .models import LatestPrediction, Match, MatchResult, Participant, Player, PredictionDraft
from .presentation import format_prediction_for_my
from .repository import PredictionRepository
from .scoring import author_prediction_breakdown, calculate_scoring, format_leaderboard, is_counted_result, normalize_score, score_prediction, stage_key
from .state import DraftStore
from .telegram_api import TelegramApi
from .validators import (
    ValidationError,
    author_suggestions,
    ensure_authors_are_distinct,
    ensure_author_in_pool,
    ensure_author_not_used,
    ensure_open_deadline,
    parse_scores,
)

LOG = logging.getLogger(__name__)
AUTHOR_PREVIEW_LIMIT = 5
DEFAULT_MATCH_LIMIT = 5
MATCH_DAY_LIMIT = 3
PREDICTION_PREVIEW_LIMIT = 5
ADMIN_MATCH_PREVIEW_LIMIT = 5
BACK_BUTTON_TEXT = "↩️ Назад"
CLOSE_BUTTON_TEXT = "✖️ Закрыть"


class PredictionBot:
    def __init__(self, config: Config, repository: PredictionRepository, telegram: TelegramApi) -> None:
        self.config = config
        self.repository = repository
        self.telegram = telegram
        self.drafts = DraftStore(config.draft_ttl_seconds)

    def handle_update(self, update: dict[str, Any]) -> None:
        try:
            if "callback_query" in update:
                self._handle_callback(update["callback_query"], update.get("update_id", ""))
            elif "message" in update:
                self._handle_message(update["message"], update.get("update_id", ""))
        except Exception:
            LOG.exception("Update handling failed")
            message = update.get("message") or update.get("callback_query", {}).get("message") or {}
            chat_id = message.get("chat", {}).get("id")
            if chat_id:
                try:
                    self.telegram.send_message(chat_id, "Не смог обработать запрос. Попробуйте еще раз или напишите организатору.")
                except Exception:
                    LOG.exception("Failed to send fallback error message")

    def _handle_message(self, message: dict[str, Any], update_id: str) -> None:
        chat_id = message["chat"]["id"]
        user = message.get("from", {})
        telegram_id = str(user.get("id", ""))
        username = user.get("username", "")
        text = (message.get("text") or "").strip()
        is_private = self._is_private_message(message)

        if not text:
            if not is_private:
                return
            self.telegram.send_message(chat_id, "Я понимаю только текстовые команды.")
            return

        command, _, arg = text.partition(" ")
        command = self._normalize_command(command)

        if command == "/help":
            participant = self.repository.get_participant_by_telegram_id(telegram_id) if is_private else None
            self._send_help(chat_id, participant)
            return
        if command == "/rules" or text == "Правила":
            participant = self.repository.get_participant_by_telegram_id(telegram_id) if is_private else None
            self._send_rules(chat_id, participant)
            return
        if command == "/matches":
            participant = self.repository.get_participant_by_telegram_id(telegram_id) if is_private else None
            self._send_matches(chat_id, participant)
            return

        if not is_private and command not in self._group_commands():
            if command in {"/start", "/predict", "/submit", "/authors", "/scores", "/my", "/analytics", "/cancel"}:
                self._send_private_chat_notice(chat_id)
            return

        participant = self.repository.get_participant_by_telegram_id(telegram_id)
        if (
            not participant
            and is_private
            and self.config.open_registration_enabled
            and not (command == "/start" and arg.strip())
        ):
            if self._can_register_open_participant(user):
                participant = self._register_open_participant(user)
            else:
                self._send_access_request_notice(chat_id, user)
                return
        LOG.info(
            "Handling message command=%s chat_type=%s participant_found=%s",
            command,
            message.get("chat", {}).get("type", "private"),
            bool(participant),
        )

        if command == "/start":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            if participant:
                self._send_main_menu(chat_id, participant)
            elif arg.strip():
                self._bind(chat_id, arg.strip(), telegram_id, username)
            else:
                self.telegram.send_message(chat_id, "Введите ваш invite/PIN код одним сообщением.")
            return

        if not participant:
            if not is_private and command not in self._admin_commands():
                self._send_private_chat_notice(chat_id)
                return
            if not is_private:
                pass
            else:
                self._bind(chat_id, text, telegram_id, username)
                return

        if command == "/cancel":
            self.drafts.clear(telegram_id)
            self._send_dashboard(chat_id, participant, "Черновик сброшен.\n\nВыберите следующее действие:")
            return

        state = self.drafts.get(telegram_id)
        if state and state.step == "scores":
            self._handle_scores_text(chat_id, telegram_id, text, state.draft)
            return
        if state and state.step == "edit_scores":
            self._handle_edit_scores_text(chat_id, telegram_id, text, state.draft)
            return

        if command in {"/predict", "Сделать"} or text == "Сделать прогноз":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            self._send_open_matches(chat_id, participant)
        elif command == "/submit":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            self._handle_submit_command(chat_id, telegram_id, participant, arg.strip(), update_id)
        elif command == "/authors":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            if not arg.strip():
                self._send_prediction_edit_picker(chat_id, participant, "authors")
                return
            self._handle_authors_command(chat_id, telegram_id, participant, arg.strip(), update_id)
        elif command == "/scores":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            if not arg.strip():
                self._send_prediction_edit_picker(chat_id, participant, "scores")
                return
            self._handle_scores_command(chat_id, telegram_id, participant, arg.strip(), update_id)
        elif command == "/my" or text == "Мои прогнозы":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            self._send_my_predictions(chat_id, participant)
        elif command == "/analytics" or text == "Аналитика":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            self._send_user_analytics(chat_id, participant, "24h")
        elif command == "/publish":
            self._publish_locked(chat_id, participant, username, arg.strip(), is_private=is_private)
        elif command == "/leaderboard":
            self._publish_leaderboard(chat_id, participant, username, is_private=is_private)
        elif command == "/score":
            self._score_results(chat_id, participant, username, arg.strip())
        elif command == "/status":
            self._send_match_status(chat_id, participant, username, arg.strip())
        elif command == "/status_latest":
            self._send_latest_match_status(chat_id, participant, username)
        elif command == "/insights":
            self._send_match_insights(chat_id, participant, username, arg.strip())
        elif command == "/admin":
            self._send_admin_help(chat_id, participant, username)
        else:
            self._send_dashboard(
                chat_id,
                participant,
                "Команда не распознана. Используйте /matches, /predict, /my, /analytics, /scores, /authors или /help.\n\n"
                "Выберите действие:",
            )

    def _handle_callback(self, callback: dict[str, Any], update_id: str) -> None:
        callback_id = callback.get("id", "")
        message = callback.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        user = callback.get("from", {})
        telegram_id = str(user.get("id", ""))
        username = user.get("username", "")
        data = callback.get("data", "")
        LOG.info("Handling callback data_prefix=%s", data.split(":", 1)[0])

        try:
            self.telegram.answer_callback_query(callback_id)
        except Exception:
            LOG.warning("answerCallbackQuery failed; continuing callback handling")
        if data == "close":
            self._delete_message_safely(chat_id, message_id)
            return
        if data == "back":
            self._delete_message_safely(chat_id, message_id)
            self._handle_back_callback(chat_id, telegram_id, message)
            return
        participant = self.repository.get_participant_by_telegram_id(telegram_id)
        if not participant and self.config.open_registration_enabled and self._is_private_message(message):
            if self._can_register_open_participant(user):
                participant = self._register_open_participant(user)
            else:
                self._send_access_request_notice(chat_id, user)
                return
        if data.startswith("admin_menu:") or data.startswith("admin_action:") or data.startswith("admin_all:"):
            self._delete_message_safely(chat_id, message_id)
            self._handle_admin_callback(
                chat_id,
                participant,
                username,
                data,
                is_private=self._is_private_message(message),
            )
            return
        if not participant:
            self.telegram.send_message(chat_id, "Сначала привяжите аккаунт через /start.")
            return
        if not self._is_private_message(message):
            self._send_private_chat_notice(chat_id)
            return

        if data.startswith("dash:"):
            self._delete_message_safely(chat_id, message_id)
            self._handle_dashboard_action(chat_id, participant, data[5:])
        elif data.startswith("analytics:"):
            self._delete_message_safely(chat_id, message_id)
            self._send_user_analytics(chat_id, participant, data.split(":", 1)[1])
        elif data.startswith("m:"):
            self._delete_message_safely(chat_id, message_id)
            self._start_prediction_for_match(chat_id, telegram_id, participant, data[2:])
        elif data.startswith("a1:"):
            _, match_id, raw_index = data.split(":", 2)
            self._delete_message_safely(chat_id, message_id)
            self._select_author(chat_id, telegram_id, match_id, int(raw_index), first_team=True)
        elif data.startswith("a2:"):
            _, match_id, raw_index = data.split(":", 2)
            self._delete_message_safely(chat_id, message_id)
            self._select_author(chat_id, telegram_id, match_id, int(raw_index), first_team=False)
        elif data.startswith("full:"):
            _, prefix, match_id = data.split(":", 2)
            self._delete_message_safely(chat_id, message_id)
            self._send_full_author_buttons(chat_id, telegram_id, match_id, first_team=prefix == "a1")
        elif data.startswith("tour:"):
            self._delete_message_safely(chat_id, message_id)
            self._send_tour_matches(chat_id, data[5:])
        elif data == "my:all":
            self._delete_message_safely(chat_id, message_id)
            self._send_my_predictions(chat_id, participant, show_all=True)
        elif data.startswith("edit_all:"):
            self._delete_message_safely(chat_id, message_id)
            self._send_prediction_edit_picker(chat_id, participant, data.split(":", 1)[1], show_all=True)
        elif data.startswith("edit_saved_scores:"):
            self._delete_message_safely(chat_id, message_id)
            self._begin_saved_scores_edit(chat_id, telegram_id, participant, data.split(":", 1)[1])
        elif data.startswith("edit_saved_authors:"):
            self._delete_message_safely(chat_id, message_id)
            self._begin_saved_authors_edit(chat_id, telegram_id, participant, data.split(":", 1)[1])
        elif data.startswith("save:"):
            self._delete_message_safely(chat_id, message_id)
            self._confirm_save(chat_id, telegram_id, participant, update_id, data[5:])
        elif data.startswith("edit_scores:"):
            self._delete_message_safely(chat_id, message_id)
            self._edit_draft_scores(chat_id, telegram_id, data.split(":", 1)[1])
        elif data == "cancel":
            self._delete_message_safely(chat_id, message_id)
            self.drafts.clear(telegram_id)
            self._send_dashboard(chat_id, participant, "Черновик сброшен.\n\nВыберите следующее действие:")

    def _handle_back_callback(self, chat_id: int, telegram_id: str, message: dict[str, Any]) -> None:
        state = self.drafts.get(telegram_id)
        if state and state.step == "author2":
            state.draft.author_team1 = ""
            self.drafts.set(telegram_id, "author1", state.draft)
            self._send_author_buttons(chat_id, state.draft, first_team=True)
            return
        if state and state.step == "author1":
            match = self._require_match(state.draft.match_id)
            self.drafts.set(telegram_id, "scores", state.draft)
            self.telegram.send_message(
                chat_id,
                f"Введите новые 7 счетов для матча {match.team1} - {match.team2} через запятую.\n"
                f"Текущие счета: {', '.join(state.draft.scores)}\n"
                "Пример: 1-0,1-1,2-0,0-0,2-1,1-2,0-1",
            )
            return
        participant = self.repository.get_participant_by_telegram_id(telegram_id) if self._is_private_message(message) else None
        if participant:
            self._send_dashboard(chat_id, participant)

    def _bind(self, chat_id: int, invite_code: str, telegram_id: str, username: str) -> None:
        participant = self.repository.bind_participant(invite_code, telegram_id, username, self._now_iso())
        if not participant:
            self.telegram.send_message(chat_id, "Код не найден или участник неактивен. Проверьте код у организатора.")
            return
        self._send_main_menu(chat_id, participant)

    def _send_main_menu(self, chat_id: int, participant: Participant) -> None:
        self._send_dashboard(
            chat_id,
            participant,
            f"Готово, {participant.display_name}.\n"
            "Прогнозы отправляются только в личке этому боту.\n\n"
            "Выберите действие:",
        )

    def _send_dashboard(self, chat_id: int, participant: Participant, text: str | None = None) -> None:
        message = text or f"👤 {participant.display_name}\n\nВыберите действие:"
        self.telegram.send_message(chat_id, message, self._dashboard_keyboard())

    def _dashboard_keyboard(self) -> dict[str, list[list[dict[str, str]]]]:
        return {
            "inline_keyboard": [
                [{"text": "📝 Сделать прогноз", "callback_data": "dash:predict"}],
                [{"text": "🔒 Мои прогнозы", "callback_data": "dash:my"}],
                [{"text": "📊 Аналитика", "callback_data": "dash:analytics"}],
                [
                    {"text": "🗓 Матчи", "callback_data": "dash:matches"},
                    {"text": "📘 Правила", "callback_data": "dash:rules"},
                ],
                [{"text": CLOSE_BUTTON_TEXT, "callback_data": "close"}],
            ]
        }

    def _handle_dashboard_action(self, chat_id: int, participant: Participant, action: str) -> None:
        if action == "predict":
            self._send_open_matches(chat_id, participant)
        elif action == "my":
            self._send_my_predictions(chat_id, participant)
        elif action == "analytics":
            self._send_user_analytics(chat_id, participant, "24h")
        elif action == "matches":
            self._send_matches(chat_id, participant)
        elif action == "rules":
            self._send_rules(chat_id, participant)
        else:
            self._send_dashboard(chat_id, participant)

    def _register_open_participant(self, user: dict[str, Any]) -> Participant:
        telegram_id = str(user.get("id", ""))
        username = user.get("username", "")
        display_name = self._display_name(user)
        return self.repository.register_participant(
            telegram_id=telegram_id,
            username=username,
            display_name=display_name,
            created_at=self._now_iso(),
        )

    def _can_register_open_participant(self, user: dict[str, Any]) -> bool:
        if not self.config.allowed_usernames:
            return True
        username = user.get("username", "").strip().lstrip("@").lower()
        return bool(username and username in self.config.allowed_usernames)

    def _send_access_request_notice(self, chat_id: int, user: dict[str, Any]) -> None:
        username = user.get("username", "").strip()
        if username:
            self.telegram.send_message(
                chat_id,
                f"Доступ к тесту пока по списку участников. Попросите организатора добавить @{username}.",
            )
        else:
            self.telegram.send_message(
                chat_id,
                "Доступ к тесту пока по списку участников. Укажите Telegram username и попросите организатора добавить его.",
            )

    def _display_name(self, user: dict[str, Any]) -> str:
        full_name = " ".join(
            part.strip()
            for part in [user.get("first_name", ""), user.get("last_name", "")]
            if part and part.strip()
        )
        if full_name:
            return full_name
        username = user.get("username", "").strip()
        if username:
            return f"@{username}"
        return f"Участник {user.get('id', '')}"

    def _send_open_matches(self, chat_id: int, participant: Participant | None = None) -> None:
        all_open_matches = self.repository.get_open_matches(self._now_iso())
        matches = self._visible_open_matches(all_open_matches)
        if not matches:
            if participant:
                self._send_dashboard(chat_id, participant, "Открытых матчей сейчас нет.\n\nВыберите действие:")
            else:
                self.telegram.send_message(chat_id, "Открытых матчей сейчас нет.")
            return
        rows = [
            [{"text": self._match_button(match), "callback_data": f"m:{match.match_id}"}]
            for match in matches
        ]
        closest_tour_matches = self._closest_tour_matches(all_open_matches)
        visible_ids = {match.match_id for match in matches}
        if any(match.match_id not in visible_ids for match in closest_tour_matches):
            rows.append([{"text": "Все матчи ближайшего тура", "callback_data": f"tour:{closest_tour_matches[0].tour}"}])
        rows.append(self._back_row())
        lines = ["Выберите матч:", "", "Прогнозы отправляются в личке боту. Быстрое сохранение одной командой:"]
        lines.append("/submit MATCH_ID 1-0,1-1,2-0,0-0,2-1,1-2,0-1 | Автор1 | Автор2")
        lines.append("Открытые MATCH_ID:")
        for match in matches:
            lines.append(f"{match.match_id}: {match.team1} - {match.team2}")
        self.telegram.send_message(chat_id, "\n".join(lines), {"inline_keyboard": rows})

    def _send_matches(self, chat_id: int, participant: Participant | None = None) -> None:
        matches = self._visible_open_matches(self.repository.get_open_matches(self._now_iso()))
        if not matches:
            self.telegram.send_message(chat_id, "Открытых матчей на ближайший слот сейчас нет.")
            return
        submitted_match_ids = self._submitted_match_ids(participant) if participant else set()
        lines = [
            "🗓 Ближайшие открытые матчи:",
            "Используйте MATCH_ID в /submit, /scores или /authors.",
            "",
        ]
        for match in matches:
            marker = "✅ " if match.match_id in submitted_match_ids else ""
            lines.append(
                f"{marker}{match.match_id} — {match.team1} - {match.team2}\n"
                f"дедлайн {match.deadline_msk:%d.%m %H:%M} МСК"
            )
        self.telegram.send_message(chat_id, "\n".join(lines), self._dashboard_keyboard() if participant else None)

    def _visible_open_matches(self, matches: list[Match]) -> list[Match]:
        if not matches:
            return []
        sorted_matches = sorted(matches, key=lambda match: match.kickoff_msk)
        match_days: list[date] = []
        for match in sorted_matches:
            day = match.kickoff_msk.date()
            if day not in match_days:
                match_days.append(day)
            if len(match_days) >= MATCH_DAY_LIMIT:
                break
        selected_ids = {
            match.match_id
            for match in sorted_matches[:DEFAULT_MATCH_LIMIT]
        }
        selected_ids.update(
            match.match_id
            for match in sorted_matches
            if match.kickoff_msk.date() in set(match_days)
        )
        return [match for match in sorted_matches if match.match_id in selected_ids]

    def _closest_tour_matches(self, matches: list[Match]) -> list[Match]:
        if not matches:
            return []
        sorted_matches = sorted(matches, key=lambda match: match.kickoff_msk)
        closest_tour = sorted_matches[0].tour
        return [match for match in sorted_matches if match.tour == closest_tour]

    def _send_tour_matches(self, chat_id: int, tour: str) -> None:
        matches = [
            match
            for match in sorted(self.repository.get_open_matches(self._now_iso()), key=lambda item: item.kickoff_msk)
            if match.tour == tour
        ]
        if not matches:
            self.telegram.send_message(chat_id, "Открытых матчей ближайшего тура сейчас нет.")
            return
        rows = [
            [{"text": self._match_button(match), "callback_data": f"m:{match.match_id}"}]
            for match in matches
        ]
        rows.append(self._back_row())
        self.telegram.send_message(chat_id, f"Все матчи ближайшего тура ({tour}):", {"inline_keyboard": rows})

    def _start_prediction_for_match(self, chat_id: int, telegram_id: str, participant: Participant, match_id: str) -> None:
        match = self.repository.get_match(match_id)
        if not match:
            self.telegram.send_message(chat_id, "Матч не найден.")
            return
        try:
            ensure_open_deadline(match, self._now())
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return
        draft = PredictionDraft(participant_id=participant.participant_id, telegram_id=telegram_id, match_id=match_id)
        self.drafts.set(telegram_id, "scores", draft)
        used_names = self._used_author_names_for_match(participant.participant_id, match)
        lines = [
            f"Вы выбрали матч: {match.team1} - {match.team2}",
            f"Дедлайн: {match.deadline_msk:%d.%m %H:%M} МСК",
            "",
            "Введите 7 уникальных счетов в порядке вероятности через запятую.",
            "Пример: 1-0,1-1,2-0,0-0,2-1,1-2,0-1",
        ]
        if used_names:
            lines.extend(
                [
                    "",
                    "Уже задействованы в других актуальных прогнозах:",
                    ", ".join(sorted(used_names)),
                    "Эти игроки будут скрыты при выборе авторов.",
                ]
            )
        self.telegram.send_message(
            chat_id,
            "\n".join(lines),
        )

    def _handle_scores_text(self, chat_id: int, telegram_id: str, text: str, draft: PredictionDraft) -> None:
        try:
            draft.scores = parse_scores(text)
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return
        self.drafts.set(telegram_id, "author1", draft)
        self._send_author_buttons(chat_id, draft, first_team=True)

    def _handle_edit_scores_text(self, chat_id: int, telegram_id: str, text: str, draft: PredictionDraft) -> None:
        try:
            draft.scores = parse_scores(text)
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return
        self.drafts.set(telegram_id, "confirm", draft)
        self._send_confirmation(chat_id, draft)

    def _send_author_buttons(self, chat_id: int, draft: PredictionDraft, first_team: bool, full_list: bool = False) -> None:
        match = self._require_match(draft.match_id)
        team = match.team1 if first_team else match.team2
        team_players = self._available_author_players(draft, match, team)
        if not team_players:
            self.telegram.send_message(chat_id, f"В заявке команды {team} нет доступных игроков для выбора.")
            return
        prefix = "a1" if first_team else "a2"
        visible_players = team_players if full_list else team_players[:AUTHOR_PREVIEW_LIMIT]
        rows = [
            [{"text": player.display_name, "callback_data": f"{prefix}:{match.match_id}:{index}"}]
            for index, player in enumerate(visible_players)
        ]
        if not full_list and len(team_players) > AUTHOR_PREVIEW_LIMIT:
            rows.append([{"text": "Показать полный список", "callback_data": f"full:{prefix}:{match.match_id}"}])
        rows.append(self._back_row())
        label = "первой" if first_team else "второй"
        suffix = "" if full_list else f" — топ-{AUTHOR_PREVIEW_LIMIT} доступных"
        hidden_names = self._hidden_author_names_for_team(draft, match, team)
        lines = [f"Выберите автора Г+П для {label} команды ({team}){suffix}:"]
        if hidden_names:
            lines.extend(
                [
                    "",
                    "Скрыты, потому что уже выбраны в других актуальных прогнозах:",
                    ", ".join(hidden_names),
                ]
            )
        self.telegram.send_message(chat_id, "\n".join(lines), {"inline_keyboard": rows})

    def _send_full_author_buttons(self, chat_id: int, telegram_id: str, match_id: str, first_team: bool) -> None:
        state = self.drafts.get(telegram_id)
        if not state or state.draft.match_id != match_id:
            self.telegram.send_message(chat_id, "Черновик не найден. Начните заново через /predict.")
            return
        self._send_author_buttons(chat_id, state.draft, first_team=first_team, full_list=True)

    def _select_author(self, chat_id: int, telegram_id: str, match_id: str, raw_index: int, first_team: bool) -> None:
        state = self.drafts.get(telegram_id)
        if not state or state.draft.match_id != match_id:
            self.telegram.send_message(chat_id, "Черновик не найден. Начните заново через /predict.")
            return
        match = self._require_match(match_id)
        team = match.team1 if first_team else match.team2
        team_players = self._available_author_players(state.draft, match, team)
        if raw_index < 0 or raw_index >= len(team_players):
            self.telegram.send_message(chat_id, "Игрок не найден в пуле. Начните заново через /predict.")
            return
        selected = team_players[raw_index].display_name
        try:
            latest = self.repository.get_latest_for_participant(state.draft.participant_id)
            ensure_author_not_used(selected, latest, match_id)
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return

        if first_team:
            state.draft.author_team1 = selected
            self.drafts.set(telegram_id, "author2", state.draft)
            self._send_author_buttons(chat_id, state.draft, first_team=False)
        else:
            state.draft.author_team2 = selected
            self.drafts.set(telegram_id, "confirm", state.draft)
            self._send_confirmation(chat_id, state.draft)

    def _send_confirmation(self, chat_id: int, draft: PredictionDraft) -> None:
        match = self._require_match(draft.match_id)
        text = (
            f"Проверьте прогноз:\n"
            f"{match.team1} - {match.team2}, дедлайн {match.deadline_msk:%Y-%m-%d %H:%M} МСК\n"
            f"Счета: {', '.join(draft.scores)}\n"
            f"Автор {match.team1}: {draft.author_team1}\n"
            f"Автор {match.team2}: {draft.author_team2}"
        )
        keyboard = {"inline_keyboard": [[
            {"text": "Сохранить", "callback_data": f"save:{match.match_id}"},
        ], [
            {"text": "✏️ Изменить счета", "callback_data": f"edit_scores:{match.match_id}"},
        ], [
            {"text": "Отмена", "callback_data": "cancel"},
        ]]}
        self.telegram.send_message(chat_id, text, keyboard)

    def _edit_draft_scores(self, chat_id: int, telegram_id: str, match_id: str) -> None:
        state = self.drafts.get(telegram_id)
        if not state or state.draft.match_id != match_id:
            self.telegram.send_message(chat_id, "Черновик не найден. Начните заново через /predict.")
            return
        match = self._require_match(match_id)
        try:
            ensure_open_deadline(match, self._now())
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return
        self.drafts.set(telegram_id, "edit_scores", state.draft)
        self.telegram.send_message(
            chat_id,
            f"Введите новые 7 счетов для матча {match.team1} - {match.team2} через запятую.\n"
            "Авторы останутся прежними.\n"
            "Пример: 1-0,1-1,2-0,0-0,2-1,1-2,0-1",
        )

    def _confirm_save(
        self,
        chat_id: int,
        telegram_id: str,
        participant: Participant,
        update_id: str,
        callback_match_id: str,
    ) -> None:
        state = self.drafts.get(telegram_id)
        if not state or state.step != "confirm":
            self.telegram.send_message(chat_id, "Черновик не найден. Начните заново через /predict.")
            return
        draft = state.draft
        if draft.match_id != callback_match_id:
            self.telegram.send_message(chat_id, "Черновик не совпадает с кнопкой сохранения. Начните заново через /predict.")
            return
        match = self._require_match(draft.match_id)
        players = self.repository.get_players_for_match(match)
        try:
            ensure_open_deadline(match, self._now())
            ensure_author_in_pool(draft.author_team1, players, match.team1, "Автор команды 1")
            ensure_author_in_pool(draft.author_team2, players, match.team2, "Автор команды 2")
            ensure_authors_are_distinct(draft.author_team1, draft.author_team2)
            latest = self.repository.get_latest_for_participant(draft.participant_id)
            ensure_author_not_used(draft.author_team1, latest, draft.match_id)
            ensure_author_not_used(draft.author_team2, latest, draft.match_id)
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return

        submission_id = self.repository.save_prediction(
            timestamp_msk=self._now_iso(),
            telegram_id=telegram_id,
            participant_id=draft.participant_id,
            match_id=draft.match_id,
            scores=draft.scores,
            author_team1=draft.author_team1,
            author_team2=draft.author_team2,
            source_update_id=str(update_id),
        )
        self.drafts.clear(telegram_id)
        self._send_dashboard(chat_id, participant, f"Прогноз сохранен. ID: {submission_id[:8]}\n\nВыберите следующее действие:")

    def _handle_submit_command(
        self,
        chat_id: int,
        telegram_id: str,
        participant: Participant,
        arg: str,
        update_id: str,
    ) -> None:
        try:
            match_id, rest = arg.split(" ", 1)
            scores_text, author_team1, author_team2 = [part.strip() for part in rest.split("|", 2)]
        except ValueError:
            self.telegram.send_message(
                chat_id,
                "Формат: /submit MATCH_ID 1-0,1-1,2-0,0-0,2-1,1-2,0-1 | Автор1 | Автор2",
            )
            return

        match = self.repository.get_match(match_id.strip())
        if not match:
            self.telegram.send_message(chat_id, "Матч не найден. Используйте /predict, чтобы увидеть MATCH_ID.")
            return
        players = self.repository.get_players_for_match(match)
        try:
            scores = parse_scores(scores_text)
            ensure_open_deadline(match, self._now())
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return

        for author, team, label in [
            (author_team1, match.team1, "Автор команды 1"),
            (author_team2, match.team2, "Автор команды 2"),
        ]:
            try:
                ensure_author_in_pool(author, players, team, label)
            except ValidationError as error:
                self.telegram.send_message(chat_id, self._author_validation_message(str(error), author, players, team, "/submit"))
                return

        try:
            ensure_authors_are_distinct(author_team1, author_team2)
            latest = self.repository.get_latest_for_participant(participant.participant_id)
            ensure_author_not_used(author_team1, latest, match.match_id)
            ensure_author_not_used(author_team2, latest, match.match_id)
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return

        submission_id = self.repository.save_prediction(
            timestamp_msk=self._now_iso(),
            telegram_id=telegram_id,
            participant_id=participant.participant_id,
            match_id=match.match_id,
            scores=scores,
            author_team1=author_team1,
            author_team2=author_team2,
            source_update_id=str(update_id),
        )
        self.drafts.clear(telegram_id)
        self._send_dashboard(
            chat_id,
            participant,
            f"Прогноз сохранен. ID: {submission_id[:8]}\n"
            f"{match.team1} - {match.team2}: {', '.join(scores)}; {author_team1}, {author_team2}\n\n"
            "Выберите следующее действие:",
        )

    def _author_validation_message(
        self,
        base_message: str,
        author: str,
        players: list[Player],
        team: str,
        retry_command: str,
    ) -> str:
        suggestions = author_suggestions(author, players, team)
        if not suggestions:
            return base_message
        lines = [
            f"{base_message}",
            f'В заявке команды {team} не найдено точное имя: "{author}".',
            "Возможно, вы имели в виду:",
        ]
        lines.extend(f"- {suggestion}" for suggestion in suggestions)
        lines.append(f"Отправьте {retry_command} еще раз с точным именем из списка.")
        return "\n".join(lines)

    def _handle_authors_command(
        self,
        chat_id: int,
        telegram_id: str,
        participant: Participant,
        arg: str,
        update_id: str,
    ) -> None:
        try:
            match_id, author_team1, author_team2 = self._parse_authors_arg(arg)
        except ValueError:
            self.telegram.send_message(chat_id, "Формат: /authors MATCH_ID | Автор1 | Автор2")
            return

        match = self.repository.get_match(match_id)
        if not match:
            self.telegram.send_message(chat_id, "Матч не найден. Используйте /predict, чтобы увидеть MATCH_ID.")
            return

        latest = self.repository.get_latest_for_participant(participant.participant_id)
        prediction = next((item for item in latest if item.match_id == match.match_id), None)
        if not prediction:
            self.telegram.send_message(chat_id, "Для этого матча еще нет прогноза. Сначала сохраните его через /predict или /submit.")
            return

        players = self.repository.get_players_for_match(match)
        try:
            ensure_open_deadline(match, self._now())
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return

        for author, team, label in [
            (author_team1, match.team1, "Автор команды 1"),
            (author_team2, match.team2, "Автор команды 2"),
        ]:
            try:
                ensure_author_in_pool(author, players, team, label)
            except ValidationError as error:
                self.telegram.send_message(chat_id, self._author_validation_message(str(error), author, players, team, "/authors"))
                return

        try:
            ensure_authors_are_distinct(author_team1, author_team2)
            ensure_author_not_used(author_team1, latest, match.match_id)
            ensure_author_not_used(author_team2, latest, match.match_id)
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return

        submission_id = self.repository.save_prediction(
            timestamp_msk=self._now_iso(),
            telegram_id=telegram_id,
            participant_id=participant.participant_id,
            match_id=match.match_id,
            scores=list(prediction.scores),
            author_team1=author_team1,
            author_team2=author_team2,
            source_update_id=str(update_id),
        )
        self.drafts.clear(telegram_id)
        self._send_dashboard(
            chat_id,
            participant,
            f"Авторы обновлены. ID: {submission_id[:8]}\n"
            f"{match.team1} - {match.team2}: {', '.join(prediction.scores)}; {author_team1}, {author_team2}\n\n"
            "Выберите следующее действие:",
        )

    def _handle_scores_command(
        self,
        chat_id: int,
        telegram_id: str,
        participant: Participant,
        arg: str,
        update_id: str,
    ) -> None:
        match_id, _, scores_text = arg.partition(" ")
        if not match_id or not scores_text.strip():
            self.telegram.send_message(chat_id, "Формат: /scores MATCH_ID 1-0,1-1,2-0,0-0,2-1,1-2,0-1")
            return

        match = self.repository.get_match(match_id.strip())
        if not match:
            self.telegram.send_message(chat_id, "Матч не найден. Используйте /matches, чтобы увидеть MATCH_ID.")
            return

        latest = self.repository.get_latest_for_participant(participant.participant_id)
        prediction = next((item for item in latest if item.match_id == match.match_id), None)
        if not prediction:
            self.telegram.send_message(chat_id, "Для этого матча еще нет прогноза. Сначала сохраните его через /predict или /submit.")
            return

        try:
            scores = parse_scores(scores_text)
            ensure_open_deadline(match, self._now())
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return

        submission_id = self.repository.save_prediction(
            timestamp_msk=self._now_iso(),
            telegram_id=telegram_id,
            participant_id=participant.participant_id,
            match_id=match.match_id,
            scores=scores,
            author_team1=prediction.author_team1,
            author_team2=prediction.author_team2,
            source_update_id=str(update_id),
        )
        self.drafts.clear(telegram_id)
        self._send_dashboard(
            chat_id,
            participant,
            f"Счета обновлены. ID: {submission_id[:8]}\n"
            f"{match.team1} - {match.team2}: {', '.join(scores)}; {prediction.author_team1}, {prediction.author_team2}\n\n"
            "Выберите следующее действие:",
        )

    def _parse_authors_arg(self, arg: str) -> tuple[str, str, str]:
        parts = [part.strip() for part in arg.split("|")]
        if len(parts) == 3 and all(parts):
            return parts[0], parts[1], parts[2]
        if len(parts) == 2 and all(parts):
            match_id, _, author_team1 = parts[0].partition(" ")
            if match_id and author_team1:
                return match_id.strip(), author_team1.strip(), parts[1]
        raise ValueError("Invalid /authors format")

    def _send_my_predictions(self, chat_id: int, participant: Participant, show_all: bool = False) -> None:
        LOG.info("Loading latest predictions for /my")
        all_latest = self.repository.get_latest_for_participant(participant.participant_id)
        active_latest = self._active_latest_predictions(participant)
        LOG.info("Loaded active latest predictions for /my count=%s", len(active_latest))
        if not active_latest:
            if all_latest:
                self._send_dashboard(
                    chat_id,
                    participant,
                    "Актуальных открытых прогнозов нет. Закрытые и завершенные матчи скрыты из /my.\n\n"
                    "Выберите следующее действие:",
                )
            else:
                self._send_dashboard(chat_id, participant, "Пока нет сохраненных прогнозов.\n\nВыберите действие:")
            return
        visible_latest = active_latest if show_all else active_latest[:PREDICTION_PREVIEW_LIMIT]
        lines = ["🔒 Ваши актуальные прогнозы. Другие участники их не видят:"]
        for prediction in visible_latest:
            lines.append("")
            lines.append(format_prediction_for_my(prediction, self.repository.get_match(prediction.match_id)))
        keyboard = self._prediction_edit_keyboard(visible_latest, show_all_button=not show_all and len(active_latest) > len(visible_latest))
        self.telegram.send_message(chat_id, "\n".join(lines), keyboard)

    def _send_user_analytics(self, chat_id: int, participant: Participant, mode: str = "24h") -> None:
        entries = self._user_analytics_entries(participant, mode)
        title = self._user_analytics_title(mode)
        keyboard = self._user_analytics_keyboard()
        if not entries:
            self.telegram.send_message(
                chat_id,
                f"{title}\n\nПока нет ваших прогнозов на завершенные матчи в этом периоде.",
                keyboard,
            )
            return

        lines = [title]
        for prediction, match, result in entries:
            stage = stage_key(match)
            score_points, _ = score_prediction(prediction, result, stage)
            author_score = author_prediction_breakdown(prediction, result, stage)
            total_points = score_points + author_score.total_points
            lines.extend(
                [
                    "",
                    f"⚽ <b>{esc(match.team1)} - {esc(match.team2)}</b> ({esc(match.match_id)})",
                    (
                        f"Факт: {esc(normalize_score(result.actual_score))} | "
                        f"Очки: {total_points} = счет {score_points} + Г+П {author_score.total_points}"
                    ),
                    f"Счета: {self._analytics_scores(prediction, result)}",
                    f"Игроки: {self._analytics_author_line(prediction.author_team1, result)}, "
                    f"{self._analytics_author_line(prediction.author_team2, result)}",
                ]
            )
        self.telegram.send_message(chat_id, "\n".join(lines), keyboard, parse_mode="HTML")

    def _user_analytics_entries(
        self,
        participant: Participant,
        mode: str,
    ) -> list[tuple[LatestPrediction, Match, MatchResult]]:
        now = self._now()
        predictions = self.repository.get_latest_for_participant(participant.participant_id)
        match_by_id = {match.match_id: match for match in self.repository.get_matches()}
        result_by_id = {
            result.match_id: result
            for result in self.repository.get_results()
            if is_counted_result(result)
        }
        latest_tour = self._latest_counted_tour(match_by_id, result_by_id, now)
        entries: list[tuple[LatestPrediction, Match, MatchResult]] = []
        for prediction in predictions:
            match = match_by_id.get(prediction.match_id)
            result = result_by_id.get(prediction.match_id)
            if not match or not result or match.kickoff_msk > now:
                continue
            if mode == "24h" and not (now - timedelta(hours=24) <= match.kickoff_msk <= now):
                continue
            if mode == "tour" and match.tour != latest_tour:
                continue
            entries.append((prediction, match, result))
        return sorted(entries, key=lambda item: item[1].kickoff_msk)

    def _latest_counted_tour(
        self,
        match_by_id: dict[str, Match],
        result_by_id: dict[str, MatchResult],
        now: datetime,
    ) -> str:
        matches = [
            match
            for match_id, match in match_by_id.items()
            if match_id in result_by_id and match.kickoff_msk <= now
        ]
        if not matches:
            return ""
        return max(matches, key=lambda match: match.kickoff_msk).tour

    def _user_analytics_title(self, mode: str) -> str:
        if mode == "tour":
            return "📊 Ваши сыгранные прогнозы за последний тур"
        if mode == "all":
            return "📊 Все ваши сыгранные прогнозы"
        return "📊 Ваши сыгранные прогнозы за последние 24 часа"

    def _user_analytics_keyboard(self) -> dict[str, list[list[dict[str, str]]]]:
        rows = [
            [{"text": "Последние 24 часа", "callback_data": "analytics:24h"}],
            [{"text": "Весь последний тур", "callback_data": "analytics:tour"}],
            [{"text": "Все прошедшие матчи", "callback_data": "analytics:all"}],
        ]
        rows.extend(self._dashboard_keyboard()["inline_keyboard"])
        return {"inline_keyboard": rows}

    def _analytics_scores(self, prediction: LatestPrediction, result: MatchResult) -> str:
        actual_score = normalize_score(result.actual_score)
        parts = []
        for score in prediction.scores:
            normalized = normalize_score(score)
            escaped_score = esc(normalized)
            parts.append(f"<b>{escaped_score}</b>" if normalized == actual_score else escaped_score)
        return ", ".join(parts)

    def _analytics_author_line(self, author: str, result: MatchResult) -> str:
        goals = max(0, Counter(result.goals)[author] - Counter(result.own_goals)[author])
        assists = Counter(result.assists)[author]
        return f"{esc(author)} ({goals}+{assists})"

    def _send_prediction_edit_picker(self, chat_id: int, participant: Participant, action: str, show_all: bool = False) -> None:
        active_latest = self._active_latest_predictions(participant)
        if not active_latest:
            self._send_dashboard(
                chat_id,
                participant,
                "Актуальных открытых прогнозов для редактирования нет.\n\nВыберите следующее действие:",
            )
            return
        title = "Выберите прогноз, где заменить счета:" if action == "scores" else "Выберите прогноз, где заменить авторов Г+П:"
        rows = []
        visible_latest = active_latest if show_all else active_latest[:PREDICTION_PREVIEW_LIMIT]
        for prediction in visible_latest:
            match = self.repository.get_match(prediction.match_id)
            if not match:
                continue
            rows.append([{"text": self._short_match_label(match), "callback_data": f"edit_saved_{action}:{match.match_id}"}])
        if len(active_latest) > len(visible_latest):
            rows.append([{"text": "Показать все актуальные прогнозы", "callback_data": f"edit_all:{action}"}])
        rows.append(self._back_row())
        self.telegram.send_message(chat_id, title, {"inline_keyboard": rows})

    def _prediction_edit_keyboard(self, predictions: list[Any], show_all_button: bool = False) -> dict[str, list[list[dict[str, str]]]]:
        rows: list[list[dict[str, str]]] = []
        for prediction in predictions:
            match = self.repository.get_match(prediction.match_id)
            if not match:
                continue
            label = self._short_match_label(match)
            rows.append([{"text": f"✏️ Счета: {label}", "callback_data": f"edit_saved_scores:{match.match_id}"}])
            rows.append([{"text": f"🧩 Авторы: {label}", "callback_data": f"edit_saved_authors:{match.match_id}"}])
        if show_all_button:
            rows.append([{"text": "Показать все актуальные прогнозы", "callback_data": "my:all"}])
        rows.extend(self._dashboard_keyboard()["inline_keyboard"])
        return {"inline_keyboard": rows}

    def _active_latest_predictions(self, participant: Participant) -> list[Any]:
        open_ids = {match.match_id for match in self.repository.get_open_matches(self._now_iso())}
        match_by_id = {match.match_id: match for match in self.repository.get_matches()}
        latest = [
            prediction
            for prediction in self.repository.get_latest_for_participant(participant.participant_id)
            if prediction.match_id in open_ids and prediction.match_id in match_by_id
        ]
        return sorted(latest, key=lambda prediction: match_by_id[prediction.match_id].kickoff_msk)

    def _find_active_prediction(self, participant: Participant, match_id: str) -> tuple[Any | None, Match | None]:
        for prediction in self._active_latest_predictions(participant):
            if prediction.match_id == match_id:
                return prediction, self.repository.get_match(match_id)
        return None, self.repository.get_match(match_id)

    def _begin_saved_scores_edit(self, chat_id: int, telegram_id: str, participant: Participant, match_id: str) -> None:
        prediction, match = self._find_active_prediction(participant, match_id)
        if not prediction or not match:
            self.telegram.send_message(chat_id, "Актуальный прогноз для этого матча не найден или дедлайн уже прошел.")
            return
        draft = PredictionDraft(
            participant_id=participant.participant_id,
            telegram_id=telegram_id,
            match_id=match.match_id,
            scores=list(prediction.scores),
            author_team1=prediction.author_team1,
            author_team2=prediction.author_team2,
        )
        self.drafts.set(telegram_id, "confirm", draft)
        self._edit_draft_scores(chat_id, telegram_id, match.match_id)

    def _begin_saved_authors_edit(self, chat_id: int, telegram_id: str, participant: Participant, match_id: str) -> None:
        prediction, match = self._find_active_prediction(participant, match_id)
        if not prediction or not match:
            self.telegram.send_message(chat_id, "Актуальный прогноз для этого матча не найден или дедлайн уже прошел.")
            return
        draft = PredictionDraft(
            participant_id=participant.participant_id,
            telegram_id=telegram_id,
            match_id=match.match_id,
            scores=list(prediction.scores),
        )
        self.drafts.set(telegram_id, "author1", draft)
        self._send_author_buttons(chat_id, draft, first_team=True)

    def _publish_locked(
        self,
        chat_id: int,
        participant: Participant,
        username: str,
        match_id: str,
        *,
        is_private: bool,
    ) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        if not match_id:
            self._send_admin_match_picker(chat_id, participant, username, "publish", is_private=is_private)
            return
        match = self.repository.get_match(match_id)
        if not match:
            self.telegram.send_message(chat_id, "Матч не найден.")
            return
        if self._now() < match.deadline_msk:
            self.telegram.send_message(chat_id, "Дедлайн еще не прошел. Публикация заблокирована.")
            return
        predictions = self.repository.get_latest_for_match(match_id)
        if not predictions:
            self.telegram.send_message(chat_id, "По матчу нет прогнозов.")
            return
        participants = {participant.participant_id: participant for participant in self.repository.get_participants()}
        lines = [
            f"🔒 Прогнозы закрыты: {match.team1} - {match.team2}",
            f"Дедлайн: {match.deadline_msk:%d.%m %H:%M} МСК",
        ]
        for prediction in sorted(predictions, key=lambda item: participants.get(item.participant_id, Participant(item.participant_id, item.participant_id)).display_name):
            participant_name = participants.get(
                prediction.participant_id,
                Participant(prediction.participant_id, prediction.display_name or prediction.participant_id),
            ).display_name
            lines.append(
                f"\n👤 {participant_name}\n"
                f"Счета: {', '.join(prediction.scores)}\n"
                f"{prediction.author_team1}, {prediction.author_team2}"
            )
        target_chat_id = self._broadcast_target_chat_id(chat_id, is_private=is_private)
        try:
            self.telegram.send_message(target_chat_id, "\n".join(lines))
        except RuntimeError as error:
            self.telegram.send_message(chat_id, self._broadcast_send_error(str(error), is_private=is_private))
            return
        self.repository.mark_match_locked(match_id)
        self.telegram.send_message(chat_id, "Прогнозы опубликованы и помечены locked.")

    def _publish_leaderboard(self, chat_id: int, participant: Participant, username: str, *, is_private: bool) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        rows = self.repository.get_leaderboard_rows()
        if not rows:
            self.telegram.send_message(chat_id, "Лист leaderboard пуст или еще не готов.")
            return
        target_chat_id = self._broadcast_target_chat_id(chat_id, is_private=is_private)
        try:
            self.telegram.send_message(
                target_chat_id,
                format_leaderboard(rows, title="🏆 Таблица после игрового дня", html=True),
                parse_mode="HTML",
            )
        except RuntimeError as error:
            self.telegram.send_message(chat_id, self._broadcast_send_error(str(error), is_private=is_private))

    def _broadcast_target_chat_id(self, chat_id: int | str, *, is_private: bool) -> str | int:
        if not is_private:
            return chat_id
        return self.config.tournament_chat_id or str(chat_id)

    def _broadcast_send_error(self, error_text: str, *, is_private: bool) -> str:
        if is_private:
            return (
                "Не смог отправить сообщение в турнирный чат. "
                "Проверьте TOURNAMENT_CHAT_ID или запустите команду прямо в турнирной группе. "
                f"Ошибка Telegram: {error_text}"
            )
        return f"Не смог отправить сообщение в этот чат. Ошибка Telegram: {error_text}"

    def _score_results(self, chat_id: int, participant: Participant, username: str, arg: str) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        if not arg:
            self._send_admin_match_picker(chat_id, participant, username, "score", is_private=True)
            return
        match_id = "" if arg.strip().lower() == "all" else arg.strip()
        all_result = calculate_scoring(
            predictions=self.repository.get_all_latest_predictions(),
            results=self.repository.get_results(),
            participants=self.repository.get_participants(),
            matches=self.repository.get_matches(),
            now_iso=self._now_iso(),
        )
        if not all_result.match_ids:
            self.telegram.send_message(chat_id, "Нет результатов для пересчета. Заполните лист results.")
            return
        if not all_result.scoring_rows:
            self.telegram.send_message(chat_id, "Результаты есть, но подходящих прогнозов не найдено.")
            return
        display_result = all_result
        if match_id:
            display_result = calculate_scoring(
                predictions=self.repository.get_all_latest_predictions(),
                results=self.repository.get_results(),
                participants=self.repository.get_participants(),
                matches=self.repository.get_matches(),
                now_iso=self._now_iso(),
                match_id=match_id,
            )
            if not display_result.match_ids:
                self.telegram.send_message(chat_id, "По этому MATCH_ID нет заполненного результата.")
                return
            if not display_result.scoring_rows:
                self.telegram.send_message(chat_id, "Результат есть, но подходящих прогнозов по этому матчу не найдено.")
                return

        self.repository.replace_scoring_rows(all_result.scoring_rows)
        self.repository.replace_leaderboard_rows(all_result.leaderboard_rows)
        for sheet_name, rows in all_result.analytics_rows.items():
            self.repository.replace_analytics_rows(sheet_name, rows)
        scope = "всем матчам" if not match_id else match_id
        result_summary = "\n".join(self._match_result_summary_lines(match_id)) if match_id else ""
        self.telegram.send_message(
            chat_id,
            f"✅ Пересчет по {scope} готов.\n"
            f"Матчей с результатами в таблицах: {len(all_result.match_ids)}\n"
            f"Строк scoring: {len(all_result.scoring_rows)}\n"
            f"Аналитика: {len(all_result.analytics_rows)} листов"
            f"{result_summary}\n\n"
            f"{format_leaderboard(display_result.leaderboard_rows, title='🏆 Очки по матчу' if match_id else '🏆 Таблица', html=True)}",
            parse_mode="HTML",
        )

    def _match_result_summary_lines(self, match_id: str) -> list[str]:
        match = self.repository.get_match(match_id)
        result = next((item for item in self.repository.get_results() if item.match_id == match_id), None)
        if not match or not result:
            return []
        lines = [
            "",
            "⚽ Результат матча",
            f"{match.team1} - {match.team2}: {result.actual_score}",
        ]
        if result.goals:
            lines.append(f"Голы: {', '.join(result.goals)}")
        if result.assists:
            lines.append(f"Ассисты: {', '.join(result.assists)}")
        if result.own_goals:
            lines.append(f"Автоголы: {', '.join(result.own_goals)}")
        return lines

    def _send_match_status(self, chat_id: int, participant: Participant, username: str, match_id: str) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        if not match_id:
            self._send_admin_match_picker(chat_id, participant, username, "status", is_private=True)
            return
        match = self.repository.get_match(match_id)
        if not match:
            self.telegram.send_message(chat_id, "Матч не найден.")
            return

        participants = self._forecast_participants()
        submitted_predictions = self.repository.get_latest_for_match(match.match_id)
        submitted_ids = {prediction.participant_id for prediction in submitted_predictions}
        submitted = [participant for participant in participants if participant.participant_id in submitted_ids]
        missing = [participant for participant in participants if participant.participant_id not in submitted_ids]

        lines = [
            f"📋 Статус прогнозов: {match.match_id}",
            f"{match.team1} - {match.team2}",
            f"Дедлайн: {match.deadline_msk:%d.%m %H:%M} МСК",
            f"Сдали: {len(submitted)}/{len(participants)}",
        ]
        if missing:
            lines.append("")
            lines.append("Не сдали:")
            lines.extend(f"- {participant.display_name}" for participant in missing[:40])
            if len(missing) > 40:
                lines.append(f"...и еще {len(missing) - 40}")
        else:
            lines.append("")
            lines.append("Все активные участники сдали прогноз.")
        self.telegram.send_message(chat_id, "\n".join(lines))

    def _send_latest_match_status(self, chat_id: int, participant: Participant, username: str) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        open_matches = sorted(self.repository.get_open_matches(self._now_iso()), key=lambda match: match.kickoff_msk)
        if not open_matches:
            self.telegram.send_message(chat_id, "Открытых ближайших матчей сейчас нет.")
            return
        self._send_match_status(chat_id, participant, username, open_matches[0].match_id)

    def _send_match_insights(self, chat_id: int, participant: Participant, username: str, match_id: str) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        if not match_id:
            self._send_admin_match_picker(chat_id, participant, username, "insights", is_private=True)
            return
        match = self.repository.get_match(match_id)
        if not match:
            self.telegram.send_message(chat_id, "Матч не найден.")
            return
        predictions = self.repository.get_latest_for_match(match.match_id)
        if not predictions:
            self.telegram.send_message(chat_id, "По матчу нет прогнозов.")
            return

        total = len(predictions)
        first_scores = Counter(prediction.scores[0] for prediction in predictions if prediction.scores)
        team1_authors = Counter(prediction.author_team1 for prediction in predictions if prediction.author_team1)
        team2_authors = Counter(prediction.author_team2 for prediction in predictions if prediction.author_team2)
        outcomes = Counter(self._first_score_outcome(prediction.scores[0], match) for prediction in predictions if prediction.scores)

        top_score, top_score_count = self._top_counter_item(first_scores)
        top_team1_author, top_team1_count = self._top_counter_item(team1_authors)
        top_team2_author, top_team2_count = self._top_counter_item(team2_authors)

        lines = [
            f"📊 Агрегаты прогнозов: {match.match_id}",
            f"{match.team1} - {match.team2}",
            f"Участников с прогнозом: {total}",
            "",
            f"Самый популярный 1-й счет: {top_score} ({self._share(top_score_count, total)}, {top_score_count}/{total})",
            (
                f"Самый популярный автор Г+П у {match.team1}: "
                f"{top_team1_author} ({self._share(top_team1_count, total)}, {top_team1_count}/{total})"
            ),
            (
                f"Самый популярный автор Г+П у {match.team2}: "
                f"{top_team2_author} ({self._share(top_team2_count, total)}, {top_team2_count}/{total})"
            ),
            (
                "Доли исходов по 1-м счетам: "
                f"{match.team1} {self._share(outcomes.get('team1', 0), total)} / "
                f"ничья {self._share(outcomes.get('draw', 0), total)} / "
                f"{match.team2} {self._share(outcomes.get('team2', 0), total)}"
            ),
            "",
            "Выбранные игроки",
            f"{match.team1}:",
        ]
        lines.extend(self._format_counter_lines(team1_authors))
        lines.append(f"{match.team2}:")
        lines.extend(self._format_counter_lines(team2_authors))
        self.telegram.send_message(chat_id, "\n".join(lines))

    def _handle_admin_callback(
        self,
        chat_id: int,
        participant: Participant | None,
        username: str,
        data: str,
        *,
        is_private: bool,
    ) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        if data.startswith("admin_menu:"):
            action = data.split(":", 1)[1]
            if action == "leaderboard":
                self._publish_leaderboard(chat_id, participant, username, is_private=is_private)
                return
            self._send_admin_match_picker(chat_id, participant, username, action, is_private=is_private)
            return
        if data.startswith("admin_all:"):
            action = data.split(":", 1)[1]
            self._send_admin_match_picker(chat_id, participant, username, action, is_private=is_private, show_all=True)
            return
        if data.startswith("admin_action:"):
            _, action, match_id = data.split(":", 2)
            if action == "status":
                self._send_match_status(chat_id, participant, username, match_id)
            elif action == "publish":
                self._publish_locked(chat_id, participant, username, match_id, is_private=is_private)
            elif action == "insights":
                self._send_match_insights(chat_id, participant, username, match_id)
            elif action == "score":
                self._score_results(chat_id, participant, username, match_id)
            elif action == "postmatch":
                self._send_postmatch_summary(chat_id, participant, username, match_id, is_private=is_private)

    def _send_postmatch_summary(
        self,
        chat_id: int,
        participant: Participant,
        username: str,
        match_id: str,
        *,
        is_private: bool,
    ) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        target_chat_id = self._broadcast_target_chat_id(chat_id, is_private=is_private)
        self.telegram.send_message(target_chat_id, f"🚀 Итоги матча {match_id}")
        self._publish_locked(target_chat_id, participant, username, match_id, is_private=False)
        self._send_match_insights(target_chat_id, participant, username, match_id)
        self._score_results(target_chat_id, participant, username, match_id)
        self._publish_leaderboard(target_chat_id, participant, username, is_private=False)

    def _send_admin_match_picker(
        self,
        chat_id: int,
        participant: Participant | None,
        username: str,
        action: str,
        *,
        is_private: bool,
        show_all: bool = False,
    ) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        matches = self._admin_matches_for_action(action)
        if action in {"score", "postmatch"}:
            result_match_ids = {result.match_id for result in self.repository.get_results()}
            if result_match_ids:
                matches = [match for match in matches if match.match_id in result_match_ids]
        if not matches and action != "score":
            self.telegram.send_message(chat_id, self._empty_admin_picker_text(action))
            return

        visible_matches = matches if show_all else matches[:ADMIN_MATCH_PREVIEW_LIMIT]
        rows: list[list[dict[str, str]]] = []
        if action == "score":
            rows.append([{"text": "🧮 Пересчитать все заполненные результаты", "callback_data": "admin_action:score:all"}])
        for match in visible_matches:
            rows.append([{"text": self._admin_match_button(action, match), "callback_data": f"admin_action:{action}:{match.match_id}"}])
        if len(matches) > len(visible_matches):
            rows.append([{"text": "Показать все матчи", "callback_data": f"admin_all:{action}"}])
        rows.append(self._back_row())
        self.telegram.send_message(chat_id, self._admin_picker_title(action), {"inline_keyboard": rows})

    def _admin_matches_for_action(self, action: str) -> list[Match]:
        now = self._now()
        if action == "status":
            return sorted(self.repository.get_open_matches(self._now_iso()), key=lambda match: match.kickoff_msk)
        if action == "publish":
            return [
                match
                for match in sorted(self.repository.get_matches(), key=lambda item: item.deadline_msk, reverse=True)
                if now >= match.deadline_msk and self.repository.get_latest_for_match(match.match_id)
            ]
        if action == "insights":
            predicted_match_ids = {prediction.match_id for prediction in self.repository.get_all_latest_predictions()}
            return [
                match
                for match in sorted(self.repository.get_matches(), key=lambda item: abs((item.kickoff_msk - now).total_seconds()))
                if match.match_id in predicted_match_ids
            ]
        if action in {"score", "postmatch"}:
            result_match_ids = {result.match_id for result in self.repository.get_results()}
            return [
                match
                for match in sorted(self.repository.get_matches(), key=lambda item: item.kickoff_msk, reverse=True)
                if match.match_id in result_match_ids
            ]
        return []

    def _admin_picker_title(self, action: str) -> str:
        titles = {
            "status": "📋 Выберите матч для проверки статуса:",
            "publish": "🔒 Выберите матч для публикации прогнозов:",
            "insights": "📊 Выберите матч для агрегатов прогнозов:",
            "score": "🧮 Выберите матч для пересчета очков:",
            "postmatch": "🚀 Выберите матч для полного post-match отчета:",
        }
        return titles.get(action, "Выберите матч:")

    def _empty_admin_picker_text(self, action: str) -> str:
        messages = {
            "status": "Открытых матчей для проверки сейчас нет.",
            "publish": "Нет матчей после дедлайна с сохраненными прогнозами.",
            "insights": "Нет матчей с сохраненными прогнозами.",
            "postmatch": "Нет матчей с результатами для post-match отчета.",
        }
        return messages.get(action, "Нет подходящих матчей.")

    def _admin_match_button(self, action: str, match: Match) -> str:
        if action == "publish":
            return f"{match.team1}-{match.team2} дедлайн {match.deadline_msk:%d.%m %H:%M}"
        if action == "score":
            return f"{match.team1}-{match.team2}"
        if action == "postmatch":
            return f"{match.team1}-{match.team2}"
        return self._match_button(match)

    def _first_score_outcome(self, score: str, match: Match) -> str:
        left, _, right = score.replace(":", "-").partition("-")
        try:
            team1_score = int(left)
            team2_score = int(right)
        except ValueError:
            return "unknown"
        if team1_score > team2_score:
            return "team1"
        if team2_score > team1_score:
            return "team2"
        return "draw"

    def _top_counter_item(self, counter: Counter[str]) -> tuple[str, int]:
        if not counter:
            return "нет данных", 0
        return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0]

    def _share(self, count: int, total: int) -> str:
        if total <= 0:
            return "0%"
        return f"{count * 100 / total:.0f}%"

    def _format_counter_lines(self, counter: Counter[str]) -> list[str]:
        if not counter:
            return ["- нет данных"]
        return [f"- {name} — {count}" for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]

    def _forecast_participants(self) -> list[Participant]:
        return [
            participant
            for participant in self.repository.get_participants()
            if participant.status.strip().lower() == "active"
        ]

    def _send_help(self, chat_id: int, participant: Participant | None = None) -> None:
        self.telegram.send_message(
            chat_id,
            "🎮 /matches - ближайшие матчи и MATCH_ID\n"
            "📝 /predict - сделать или изменить прогноз\n"
            "🔒 /my - мои прогнозы\n"
            "📊 /analytics - разбор сыгранных прогнозов\n"
            "⚡ /submit MATCH_ID ... - быстрое сохранение\n"
            "✏️ /scores - выбрать прогноз кнопкой и заменить счета\n"
            "🧩 /authors - выбрать прогноз кнопкой и заменить авторов\n"
            "📘 /rules - подробные правила\n"
            "↩️ /cancel - сбросить черновик",
            self._dashboard_keyboard() if participant else None,
        )

    def _send_rules(self, chat_id: int, participant: Participant | None = None) -> None:
        self.telegram.send_message(
            chat_id,
            "📘 Правила прогноза\n"
            "🔒 Отправляйте прогнозы только в личку боту.\n"
            "✅ Нужно 7 уникальных счетов в порядке вероятности.\n"
            "⚽ Выберите по одному автору Г+П из активной заявки каждой команды.\n"
            "♻️ Игрока нельзя использовать повторно в актуальных прогнозах.\n"
            "✏️ Повторный /submit по тому же MATCH_ID перезаписывает прогноз.\n"
            "🔢 /scores меняет только счета и оставляет авторов без изменений.\n"
            "🧩 /authors меняет только авторов и оставляет счета без изменений.\n"
            "🧭 Без MATCH_ID бот покажет прогнозы кнопками.\n"
            "⏰ После дедлайна новые прогнозы и правки блокируются сервером.\n"
            "🏆 С 1/8 финала очки за счета и Г+П постепенно растут.\n"
            "📌 Источник голов и ассистов для подсчета: sports.ru.\n"
            "⚖️ При равенстве очков tie-breakers: финал, матч за 3 место, 1/2, 1/4, 1/8, 1/16, группа.\n\n"
            "Пример:\n"
            "/submit MATCH_ID 1-0,1-1,2-0,0-0,2-1,1-2,0-1 | Автор1 | Автор2",
            self._dashboard_keyboard() if participant else None,
        )

    def _send_admin_help(self, chat_id: int, participant: Participant, username: str) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        self.telegram.send_message(
            chat_id,
            "🛠 Админские команды\n"
            "📋 /status MATCH_ID — кто сдал прогноз по матчу\n"
            "📋 /status — выбрать матч кнопкой\n"
            "📋 /status_latest — кто сдал прогноз по ближайшему открытому матчу\n"
            "📊 /insights MATCH_ID — агрегаты прогнозов по матчу\n"
            "📊 /insights — выбрать матч кнопкой\n"
            "🔒 /publish MATCH_ID — опубликовать прогнозы после дедлайна\n"
            "🔒 /publish — выбрать закрытый матч кнопкой\n"
            "🧮 /score MATCH_ID — пересчитать очки по матчу\n"
            "🧮 /score all — пересчитать очки по всем заполненным результатам\n"
            "🧮 /score — выбрать матч кнопкой\n"
            "🚀 Кнопка «Итоги матча» — одним нажатием: publish, insights, score, leaderboard\n"
            "🏆 /leaderboard — отправить таблицу лидеров в турнирный чат\n\n"
            "Результаты матчей для MVP заносим вручную в Google Sheets.",
            self._admin_keyboard(),
        )

    def _available_author_players(self, draft: PredictionDraft, match: Match, team: str) -> list[Player]:
        players = self.repository.get_players_for_match(match)
        latest = self.repository.get_latest_for_participant(draft.participant_id)
        used_names = self._used_author_names(latest, current_match_id=draft.match_id)
        return [
            player
            for player in players
            if player.team == team and player.is_active and player.display_name not in used_names
        ]

    def _used_author_names(self, latest: list[Any], current_match_id: str) -> set[str]:
        used: set[str] = set()
        for prediction in latest:
            if prediction.match_id == current_match_id:
                continue
            used.add(prediction.author_team1)
            used.add(prediction.author_team2)
        used.discard("")
        return used

    def _submitted_match_ids(self, participant: Participant) -> set[str]:
        return {prediction.match_id for prediction in self.repository.get_latest_for_participant(participant.participant_id)}

    def _used_author_names_for_match(self, participant_id: str, match: Match) -> list[str]:
        used_names = self._used_author_names(
            self.repository.get_latest_for_participant(participant_id),
            current_match_id=match.match_id,
        )
        if not used_names:
            return []
        match_player_names = {
            player.display_name
            for player in self.repository.get_players_for_match(match)
            if player.team in {match.team1, match.team2}
        }
        return sorted(used_names & match_player_names)

    def _hidden_author_names_for_team(self, draft: PredictionDraft, match: Match, team: str) -> list[str]:
        used_names = self._used_author_names(
            self.repository.get_latest_for_participant(draft.participant_id),
            current_match_id=draft.match_id,
        )
        if not used_names:
            return []
        players = self.repository.get_players_for_match(match)
        return sorted(
            {
                player.display_name
                for player in players
                if player.team == team and player.display_name in used_names
            }
        )

    def _require_match(self, match_id: str) -> Match:
        match = self.repository.get_match(match_id)
        if not match:
            raise RuntimeError(f"Match not found: {match_id}")
        return match

    def _match_button(self, match: Match) -> str:
        return f"{match.tour} {match.team1}-{match.team2} до {match.deadline_msk:%d.%m %H:%M}"

    def _short_match_label(self, match: Match) -> str:
        return f"{match.team1}-{match.team2} до {match.deadline_msk:%d.%m %H:%M}"

    def _admin_keyboard(self) -> dict[str, list[list[dict[str, str]]]]:
        return {
            "inline_keyboard": [
                [{"text": "🚀 Итоги матча", "callback_data": "admin_menu:postmatch"}],
                [{"text": "📋 Статус по матчу", "callback_data": "admin_menu:status"}],
                [{"text": "📊 Агрегаты прогнозов", "callback_data": "admin_menu:insights"}],
                [{"text": "🔒 Опубликовать прогнозы", "callback_data": "admin_menu:publish"}],
                [{"text": "🧮 Пересчитать очки", "callback_data": "admin_menu:score"}],
                [{"text": "🏆 Отправить таблицу лидеров", "callback_data": "admin_menu:leaderboard"}],
                [{"text": CLOSE_BUTTON_TEXT, "callback_data": "close"}],
            ]
        }

    def _back_row(self) -> list[dict[str, str]]:
        return [{"text": BACK_BUTTON_TEXT, "callback_data": "back"}]

    def maybe_send_daily_match_notifications(self, now: datetime | None = None) -> int:
        current = now or self._now()
        if current.hour != 12:
            return 0
        notification_key = f"daily_matches:{current.date().isoformat()}"
        if self.repository.notification_was_sent(notification_key):
            return 0

        window_end = current + timedelta(hours=24)
        matches = [
            match
            for match in sorted(self.repository.get_open_matches(current.isoformat(timespec="seconds")), key=lambda item: item.kickoff_msk)
            if current <= match.kickoff_msk <= window_end
        ]
        if not matches:
            self.repository.record_notification(
                notification_key=notification_key,
                notification_type="daily_matches",
                sent_at_msk=current.isoformat(timespec="seconds"),
                recipient_count=0,
                details="no open matches in next 24h",
            )
            return 0

        participants = self.repository.get_participants_with_predictions()
        message = self._daily_match_notification_text(matches)
        sent_count = 0
        for participant in participants:
            try:
                self.telegram.send_message(participant.telegram_id, message)
                sent_count += 1
            except Exception:
                LOG.exception("Failed to send daily notification to participant_id=%s", participant.participant_id)

        self.repository.record_notification(
            notification_key=notification_key,
            notification_type="daily_matches",
            sent_at_msk=current.isoformat(timespec="seconds"),
            recipient_count=sent_count,
            details=", ".join(match.match_id for match in matches),
        )
        return sent_count

    def _daily_match_notification_text(self, matches: list[Match]) -> str:
        lines = [
            "🔔 Матчи ближайших 24 часов",
            "Дедлайн: за 5 минут до начала матча.",
            "",
        ]
        for match in matches:
            lines.append(f"{match.match_id} — {match.team1} - {match.team2}")
            lines.append(f"⏰ {match.deadline_msk:%d.%m %H:%M} МСК")
        lines.append("")
        lines.append("Сделать или изменить прогноз: /predict")
        return "\n".join(lines)

    def _is_admin(self, participant: Participant | None, username: str) -> bool:
        username_admin = username.strip().lstrip("@").lower() in self.config.admin_usernames
        if not participant:
            return username_admin
        role_admin = participant.role.lower() == "admin" or participant.status.lower() == "admin"
        stored_username_admin = participant.telegram_username.strip().lstrip("@").lower() in self.config.admin_usernames
        return role_admin or username_admin or stored_username_admin

    def _is_private_message(self, message: dict[str, Any]) -> bool:
        return message.get("chat", {}).get("type", "private") == "private"

    def _normalize_command(self, command: str) -> str:
        if command.startswith("/") and "@" in command:
            return command.split("@", 1)[0]
        return command

    def _group_commands(self) -> set[str]:
        return {
            "/start",
            "/matches",
            "/predict",
            "/submit",
            "/authors",
            "/scores",
            "/my",
            "/analytics",
            "/help",
            "/rules",
            "/publish",
            "/leaderboard",
            "/score",
            "/status",
            "/status_latest",
            "/insights",
            "/admin",
        }

    def _admin_commands(self) -> set[str]:
        return {
            "/publish",
            "/leaderboard",
            "/score",
            "/status",
            "/status_latest",
            "/insights",
            "/admin",
        }

    def _send_private_chat_notice(self, chat_id: int) -> None:
        self.telegram.send_message(
            chat_id,
            "Прогнозы принимаются только в личке боту, чтобы участники не видели ставки друг друга. "
            "Откройте @tii_wc_predictions_2026_bot и отправьте /predict, /submit, /scores, /authors или /analytics там.",
        )

    def _delete_message_safely(self, chat_id: int | str | None, message_id: int | str | None) -> None:
        if not chat_id or not message_id:
            return
        try:
            self.telegram.delete_message(chat_id, message_id)
        except Exception:
            LOG.warning("Could not delete message chat_id=%s message_id=%s", chat_id, message_id)

    def _now(self) -> datetime:
        return datetime.now(self.config.app_tz)

    def _now_iso(self) -> str:
        return self._now().isoformat(timespec="seconds")


def esc(value: str) -> str:
    return html.escape(value, quote=False)
