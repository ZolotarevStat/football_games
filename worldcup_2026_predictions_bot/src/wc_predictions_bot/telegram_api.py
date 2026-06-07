from __future__ import annotations

import logging
from typing import Any

import requests

LOG = logging.getLogger(__name__)


class TelegramApi:
    def __init__(self, bot_token: str, *, trust_env_proxy: bool = False) -> None:
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else ""
        self.session = requests.Session()
        self.session.trust_env = trust_env_proxy

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> None:
        if not self.base_url:
            LOG.info("Telegram token is empty; message to %s: %s", chat_id, text)
            return
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        self._post("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        if not self.base_url:
            return
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self._post("answerCallbackQuery", payload)

    def delete_message(self, chat_id: str | int, message_id: str | int) -> None:
        if not self.base_url:
            return
        self._post("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    def _post(self, method: str, payload: dict[str, Any]) -> None:
        response = self.session.post(f"{self.base_url}/{method}", json=payload, timeout=(2, 3))
        if response.status_code >= 400:
            raise RuntimeError(f"Telegram {method} failed: {response.status_code} {response.text}")


class RecordingTelegramApi(TelegramApi):
    def __init__(self) -> None:
        super().__init__("")
        self.messages: list[tuple[str | int, str, dict[str, Any] | None]] = []
        self.callback_answers: list[tuple[str, str]] = []
        self.deleted_messages: list[tuple[str | int, str | int]] = []

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> None:
        self.messages.append((chat_id, text, reply_markup))

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        self.callback_answers.append((callback_query_id, text))

    def delete_message(self, chat_id: str | int, message_id: str | int) -> None:
        self.deleted_messages.append((chat_id, message_id))


class WebhookReplyTelegramApi(TelegramApi):
    def __init__(self, fallback: TelegramApi | None = None) -> None:
        super().__init__("")
        self.fallback = fallback
        self.responses: list[dict[str, Any]] = []

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"method": "sendMessage", "chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        self.responses.append(payload)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        payload: dict[str, Any] = {"method": "answerCallbackQuery", "callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self.responses.append(payload)

    def delete_message(self, chat_id: str | int, message_id: str | int) -> None:
        self.responses.append({"method": "deleteMessage", "chat_id": chat_id, "message_id": message_id})

    def first_webhook_response(self) -> dict[str, Any] | None:
        for response in self.responses:
            if response.get("method") == "sendMessage":
                return response
        return self.responses[0] if self.responses else None
