from __future__ import annotations

import os
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    spreadsheet_id: str
    service_account_json_b64: str
    service_account_file: str
    tournament_chat_id: str
    admin_usernames: frozenset[str]
    app_tz: ZoneInfo
    cache_ttl_seconds: int
    draft_ttl_seconds: int
    telegram_trust_env_proxy: bool
    open_registration_enabled: bool

    @classmethod
    def from_env(cls) -> "Config":
        admins = {
            username.strip().lstrip("@").lower()
            for username in re.split(r"[,;]", os.getenv("ADMIN_USERNAMES", "az_stat,SanMorocco"))
            if username.strip()
        }
        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            spreadsheet_id=os.getenv("GOOGLE_SPREADSHEET_ID", ""),
            service_account_json_b64=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64", ""),
            service_account_file=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", ""),
            tournament_chat_id=os.getenv("TOURNAMENT_CHAT_ID", ""),
            admin_usernames=frozenset(admins),
            app_tz=ZoneInfo(os.getenv("APP_TZ", "Europe/Moscow")),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "60")),
            draft_ttl_seconds=int(os.getenv("DRAFT_TTL_SECONDS", "1800")),
            telegram_trust_env_proxy=os.getenv("TELEGRAM_TRUST_ENV_PROXY", "").lower() in {"1", "true", "yes"},
            open_registration_enabled=os.getenv("OPEN_REGISTRATION_ENABLED", "").lower() in {"1", "true", "yes"},
        )
