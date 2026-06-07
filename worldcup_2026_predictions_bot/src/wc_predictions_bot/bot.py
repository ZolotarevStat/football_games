from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from typing import Any

from .config import Config
from .models import Match, Participant, Player, PredictionDraft
from .presentation import format_prediction_for_my
from .repository import PredictionRepository
from .scoring import calculate_scoring, format_leaderboard
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

        if not is_private and command not in self._group_commands():
            if command in {"/start", "/predict", "/submit", "/authors", "/my", "/cancel"}:
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
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            self._bind(chat_id, text, telegram_id, username)
            return

        if command == "/cancel":
            self.drafts.clear(telegram_id)
            self.telegram.send_message(chat_id, "Черновик сброшен.")
            return

        state = self.drafts.get(telegram_id)
        if state and state.step == "scores":
            self._handle_scores_text(chat_id, telegram_id, text, state.draft)
            return

        if command in {"/predict", "Сделать"} or text == "Сделать прогноз":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            self._send_open_matches(chat_id)
        elif command == "/submit":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            self._handle_submit_command(chat_id, telegram_id, participant, arg.strip(), update_id)
        elif command == "/authors":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            self._handle_authors_command(chat_id, telegram_id, participant, arg.strip(), update_id)
        elif command == "/my" or text == "Мои прогнозы":
            if not is_private:
                self._send_private_chat_notice(chat_id)
                return
            self._send_my_predictions(chat_id, participant)
        elif command == "/help" or text == "Правила":
            self._send_help(chat_id)
        elif command == "/publish":
            self._publish_locked(chat_id, participant, username, arg.strip())
        elif command == "/leaderboard":
            self._publish_leaderboard(chat_id, participant, username)
        elif command == "/score":
            self._score_results(chat_id, participant, username, arg.strip())
        else:
            self.telegram.send_message(chat_id, "Команда не распознана. Используйте /predict, /my, /authors, /leaderboard или /help.")

    def _handle_callback(self, callback: dict[str, Any], update_id: str) -> None:
        callback_id = callback.get("id", "")
        message = callback.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        user = callback.get("from", {})
        telegram_id = str(user.get("id", ""))
        data = callback.get("data", "")
        LOG.info("Handling callback data_prefix=%s", data.split(":", 1)[0])

        try:
            self.telegram.answer_callback_query(callback_id)
        except Exception:
            LOG.warning("answerCallbackQuery failed; continuing callback handling")
        participant = self.repository.get_participant_by_telegram_id(telegram_id)
        if not participant and self.config.open_registration_enabled and self._is_private_message(message):
            participant = self._register_open_participant(user)
        if not participant:
            self.telegram.send_message(chat_id, "Сначала привяжите аккаунт через /start.")
            return
        if not self._is_private_message(message):
            self._send_private_chat_notice(chat_id)
            return

        if data.startswith("m:"):
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
        elif data.startswith("save:"):
            self._delete_message_safely(chat_id, message_id)
            self._confirm_save(chat_id, telegram_id, update_id, data[5:])
        elif data == "cancel":
            self._delete_message_safely(chat_id, message_id)
            self.drafts.clear(telegram_id)
            self.telegram.send_message(chat_id, "Черновик сброшен.")

    def _bind(self, chat_id: int, invite_code: str, telegram_id: str, username: str) -> None:
        participant = self.repository.bind_participant(invite_code, telegram_id, username, self._now_iso())
        if not participant:
            self.telegram.send_message(chat_id, "Код не найден или участник неактивен. Проверьте код у организатора.")
            return
        self._send_main_menu(chat_id, participant)

    def _send_main_menu(self, chat_id: int, participant: Participant) -> None:
        self.telegram.send_message(
            chat_id,
            f"Готово, {participant.display_name}.\n"
            "Прогнозы отправляются только в личке этому боту.\n"
            "Команды: /predict - сделать прогноз, /my - мои прогнозы, /help - правила.",
        )

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

    def _send_open_matches(self, chat_id: int) -> None:
        matches = self._visible_open_matches(self.repository.get_open_matches(self._now_iso()))
        if not matches:
            self.telegram.send_message(chat_id, "Открытых матчей сейчас нет.")
            return
        rows = [
            [{"text": self._match_button(match), "callback_data": f"m:{match.match_id}"}]
            for match in matches
        ]
        self.telegram.send_message(chat_id, "Выберите матч:", {"inline_keyboard": rows})
        lines = ["Прогнозы отправляются в личке боту. Быстрое сохранение одной командой:"]
        lines.append("/submit MATCH_ID 1-0,1-1,2-0,0-0,2-1,1-2,0-1 | Автор1 | Автор2")
        lines.append("Открытые MATCH_ID:")
        for match in matches:
            lines.append(f"{match.match_id}: {match.team1} - {match.team2}")
        self.telegram.send_message(chat_id, "\n".join(lines))

    def _visible_open_matches(self, matches: list[Match]) -> list[Match]:
        if not matches:
            return []
        sorted_matches = sorted(matches, key=lambda match: match.kickoff_msk)
        now = self._now()
        current_window_end = now + timedelta(days=3)
        current_window_matches = [
            match for match in sorted_matches if now <= match.kickoff_msk < current_window_end
        ]
        if current_window_matches:
            return current_window_matches

        first_kickoff = sorted_matches[0].kickoff_msk
        fallback_window_end = first_kickoff + timedelta(days=3)
        return [match for match in sorted_matches if match.kickoff_msk < fallback_window_end]

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
        self.telegram.send_message(
            chat_id,
            "Введите 7 уникальных счетов в порядке вероятности через запятую.\n"
            "Пример: 1-0,1-1,2-0,0-0,2-1,1-2,0-1",
        )

    def _handle_scores_text(self, chat_id: int, telegram_id: str, text: str, draft: PredictionDraft) -> None:
        try:
            draft.scores = parse_scores(text)
        except ValidationError as error:
            self.telegram.send_message(chat_id, str(error))
            return
        self.drafts.set(telegram_id, "author1", draft)
        self._send_author_buttons(chat_id, draft, first_team=True)

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
        label = "первой" if first_team else "второй"
        suffix = "" if full_list else f" — топ-{AUTHOR_PREVIEW_LIMIT} доступных"
        self.telegram.send_message(chat_id, f"Выберите автора Г+П для {label} команды ({team}){suffix}:", {"inline_keyboard": rows})

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
            {"text": "Отмена", "callback_data": "cancel"},
        ]]}
        self.telegram.send_message(chat_id, text, keyboard)

    def _confirm_save(self, chat_id: int, telegram_id: str, update_id: str, callback_match_id: str) -> None:
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
        self.telegram.send_message(chat_id, f"Прогноз сохранен. ID: {submission_id[:8]}")

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
        self.telegram.send_message(
            chat_id,
            f"Прогноз сохранен. ID: {submission_id[:8]}\n"
            f"{match.team1} - {match.team2}: {', '.join(scores)}; {author_team1}, {author_team2}",
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
        self.telegram.send_message(
            chat_id,
            f"Авторы обновлены. ID: {submission_id[:8]}\n"
            f"{match.team1} - {match.team2}: {', '.join(prediction.scores)}; {author_team1}, {author_team2}",
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

    def _send_my_predictions(self, chat_id: int, participant: Participant) -> None:
        LOG.info("Loading latest predictions for /my")
        latest = self.repository.get_latest_for_participant(participant.participant_id)
        LOG.info("Loaded latest predictions for /my count=%s", len(latest))
        if not latest:
            self.telegram.send_message(chat_id, "Пока нет сохраненных прогнозов.")
            return
        lines = ["🔒 Ваши актуальные прогнозы. Другие участники их не видят:"]
        for prediction in latest:
            lines.append("")
            lines.append(format_prediction_for_my(prediction, self.repository.get_match(prediction.match_id)))
        self.telegram.send_message(chat_id, "\n".join(lines))

    def _publish_locked(self, chat_id: int, participant: Participant, username: str, match_id: str) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        if not match_id:
            self.telegram.send_message(chat_id, "Формат: /publish MATCH_ID")
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
        lines = [f"Закрытые прогнозы: {match.team1} - {match.team2}"]
        for prediction in predictions:
            lines.append(
                f"{prediction.participant_id}: {', '.join(prediction.scores)}; "
                f"{prediction.author_team1}, {prediction.author_team2}"
            )
        target_chat_id = self.config.tournament_chat_id or str(chat_id)
        self.telegram.send_message(target_chat_id, "\n".join(lines))
        self.repository.mark_match_locked(match_id)
        self.telegram.send_message(chat_id, "Прогнозы опубликованы и помечены locked.")

    def _publish_leaderboard(self, chat_id: int, participant: Participant, username: str) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        rows = self.repository.get_leaderboard_rows()
        if not rows:
            self.telegram.send_message(chat_id, "Лист leaderboard пуст или еще не готов.")
            return
        target_chat_id = self.config.tournament_chat_id or str(chat_id)
        self.telegram.send_message(target_chat_id, format_leaderboard(rows, title="🏆 Таблица после игрового дня"))

    def _score_results(self, chat_id: int, participant: Participant, username: str, arg: str) -> None:
        if not self._is_admin(participant, username):
            self.telegram.send_message(chat_id, "Команда доступна только организаторам.")
            return
        if not arg:
            self.telegram.send_message(chat_id, "Формат: /score MATCH_ID или /score all")
            return
        match_id = "" if arg.strip().lower() == "all" else arg.strip()
        result = calculate_scoring(
            predictions=self.repository.get_all_latest_predictions(),
            results=self.repository.get_results(),
            participants=self.repository.get_participants(),
            now_iso=self._now_iso(),
            match_id=match_id,
        )
        if not result.match_ids:
            self.telegram.send_message(chat_id, "Нет результатов для пересчета. Заполните лист results.")
            return
        if not result.scoring_rows:
            self.telegram.send_message(chat_id, "Результаты есть, но подходящих прогнозов не найдено.")
            return
        self.repository.replace_scoring_rows(result.scoring_rows)
        self.repository.replace_leaderboard_rows(result.leaderboard_rows)
        scope = "всем матчам" if not match_id else match_id
        self.telegram.send_message(
            chat_id,
            f"✅ Пересчет по {scope} готов.\n"
            f"Матчей с результатами: {len(result.match_ids)}\n"
            f"Строк scoring: {len(result.scoring_rows)}\n\n"
            f"{format_leaderboard(result.leaderboard_rows)}",
        )

    def _send_help(self, chat_id: int) -> None:
        self.telegram.send_message(
            chat_id,
            "🎮 Команды: /predict - сделать или изменить прогноз, /my - мои прогнозы, /cancel - сбросить черновик.\n"
            "🔒 Куда отправлять: только в личку этому боту, не в общий чат.\n"
            "⚡ Быстрое сохранение: /submit MATCH_ID 1-0,1-1,2-0,0-0,2-1,1-2,0-1 | Автор1 | Автор2\n"
            "🧩 Быстрая замена авторов: /authors MATCH_ID | Автор1 | Автор2\n"
            "✅ В прогнозе нужно 7 уникальных счетов и по одному автору Г+П из активной заявки каждой команды.\n"
            "✏️ Редактирование: повторный /submit по тому же MATCH_ID перезаписывает прогноз.\n"
            "✏️ Только авторы: /authors меняет авторов и оставляет счета без изменений.\n"
            "⏰ Дедлайн: за 5 минут до начала матча; после дедлайна новые прогнозы и правки блокируются сервером.\n"
            "♻️ Игрока нельзя использовать повторно в актуальных прогнозах.\n"
            "🏆 Организатор: /score MATCH_ID, /score all, /leaderboard.",
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

    def _require_match(self, match_id: str) -> Match:
        match = self.repository.get_match(match_id)
        if not match:
            raise RuntimeError(f"Match not found: {match_id}")
        return match

    def _match_button(self, match: Match) -> str:
        return f"{match.tour} {match.team1}-{match.team2} до {match.deadline_msk:%m.%d %H:%M}"

    def _is_admin(self, participant: Participant, username: str) -> bool:
        role_admin = participant.role.lower() == "admin" or participant.status.lower() == "admin"
        username_admin = username.strip().lstrip("@").lower() in self.config.admin_usernames
        stored_username_admin = participant.telegram_username.strip().lstrip("@").lower() in self.config.admin_usernames
        return role_admin or username_admin or stored_username_admin

    def _is_private_message(self, message: dict[str, Any]) -> bool:
        return message.get("chat", {}).get("type", "private") == "private"

    def _normalize_command(self, command: str) -> str:
        if command.startswith("/") and "@" in command:
            return command.split("@", 1)[0]
        return command

    def _group_commands(self) -> set[str]:
        return {"/start", "/predict", "/submit", "/authors", "/my", "/help", "/publish", "/leaderboard", "/score"}

    def _send_private_chat_notice(self, chat_id: int) -> None:
        self.telegram.send_message(
            chat_id,
            "Прогнозы принимаются только в личке боту, чтобы участники не видели ставки друг друга. "
            "Откройте @tii_wc_predictions_2026_bot и отправьте /predict или /submit там.",
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
