from __future__ import annotations

from .bot import PredictionBot
from .config import Config
from .sheets_repository import SheetsRepository
from .telegram_api import TelegramApi


def build_bot_from_env() -> PredictionBot:
    config = Config.from_env()
    repository = SheetsRepository(
        spreadsheet_id=config.spreadsheet_id,
        service_account_json_b64=config.service_account_json_b64,
        service_account_file=config.service_account_file,
        cache_ttl_seconds=config.cache_ttl_seconds,
    )
    telegram = TelegramApi(config.telegram_bot_token, trust_env_proxy=config.telegram_trust_env_proxy)
    return PredictionBot(config, repository, telegram)
