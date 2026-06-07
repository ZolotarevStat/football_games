from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import requests

from .env_loader import load_dotenv


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def call_telegram(token: str, method: str, *, trust_env: bool) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = trust_env
    response = session.get(f"https://api.telegram.org/bot{token}/{method}", timeout=20)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--trust-env-proxy", action="store_true")
    args = parser.parse_args()

    load_dotenv(args.env_file)
    env = load_env(Path(args.env_file))
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token or token.startswith("PASTE_"):
        print("telegram_token_configured=False")
        return

    try:
        me = call_telegram(token, "getMe", trust_env=args.trust_env_proxy)
        print("get_me_ok=" + str(me.get("ok")))
        result = me.get("result") or {}
        print("bot_username=" + str(result.get("username", "")))
        print("bot_id_present=" + str(bool(result.get("id"))))

        updates = call_telegram(token, "getUpdates", trust_env=args.trust_env_proxy)
        print("get_updates_ok=" + str(updates.get("ok")))
        seen: set[str] = set()
        for update in updates.get("result", []):
            message = update.get("message") or update.get("channel_post") or {}
            chat = message.get("chat") or {}
            chat_id = str(chat.get("id", ""))
            if not chat_id or chat_id in seen:
                continue
            seen.add(chat_id)
            print(
                "chat="
                + chat_id
                + " type="
                + str(chat.get("type", ""))
                + " title="
                + str(chat.get("title", ""))
            )
    except Exception as exc:
        print("telegram_check_failed=" + exc.__class__.__name__)


if __name__ == "__main__":
    main()
