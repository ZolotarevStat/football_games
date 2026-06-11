from __future__ import annotations

import argparse
import logging
import time
from typing import Any

import requests

from .app_factory import build_bot_from_env
from .env_loader import load_dotenv

LOG = logging.getLogger(__name__)


def telegram_get(token: str, method: str, params: dict[str, Any], *, trust_env_proxy: bool) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = trust_env_proxy
    response = session.get(
        f"https://api.telegram.org/bot{token}/{method}",
        params=params,
        timeout=35,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} returned ok=false")
    return data


def telegram_post(token: str, method: str, payload: dict[str, Any], *, trust_env_proxy: bool) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = trust_env_proxy
    response = session.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=payload,
        timeout=(5, 20),
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} returned ok=false: {data.get('description', '')}")
    return data


def safe_exception_message(exc: Exception, token: str) -> str:
    message = str(exc)
    if token:
        message = message.replace(token, "<redacted-token>")
    return message


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--trust-env-proxy", action="store_true")
    parser.add_argument("--drop-pending-updates", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    load_dotenv(args.env_file)
    if args.trust_env_proxy:
        import os

        os.environ["TELEGRAM_TRUST_ENV_PROXY"] = "true"
    bot = build_bot_from_env()
    token = bot.config.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")

    offset = 0
    try:
        telegram_post(
            token,
            "deleteWebhook",
            {"drop_pending_updates": args.drop_pending_updates},
            trust_env_proxy=args.trust_env_proxy,
        )
        LOG.info("Webhook disabled. Polling can receive updates.")
    except Exception as exc:
        LOG.warning("Could not disable webhook before polling: %s", safe_exception_message(exc, token))

    LOG.info("Polling started. trust_env_proxy=%s Press Ctrl+C to stop.", args.trust_env_proxy)
    while True:
        try:
            bot.maybe_send_daily_match_notifications()
            data = telegram_get(
                token,
                "getUpdates",
                {"offset": offset, "timeout": 25, "allowed_updates": '["message","callback_query"]'},
                trust_env_proxy=args.trust_env_proxy,
            )
            for update in data.get("result", []):
                offset = max(offset, int(update["update_id"]) + 1)
                LOG.info(
                    "Handling update_id=%s message=%s callback=%s",
                    update.get("update_id"),
                    "message" in update,
                    "callback_query" in update,
                )
                bot.handle_update(update)
        except KeyboardInterrupt:
            LOG.info("Polling stopped.")
            return
        except Exception as exc:
            LOG.warning("Polling iteration failed: %s: %s", exc.__class__.__name__, safe_exception_message(exc, token))
            time.sleep(5)


if __name__ == "__main__":
    main()
