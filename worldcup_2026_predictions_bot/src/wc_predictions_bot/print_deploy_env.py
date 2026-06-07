from __future__ import annotations

import base64
from pathlib import Path

from .env_loader import load_dotenv


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


def main() -> None:
    env_path = Path(".env")
    load_dotenv(str(env_path))
    values = read_env(env_path)
    service_account_file = Path(values.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service-account.json")).expanduser()
    service_account_b64 = ""
    if service_account_file.exists():
        service_account_b64 = base64.b64encode(service_account_file.read_bytes()).decode("ascii")

    deploy_values = {
        "TELEGRAM_BOT_TOKEN": values.get("TELEGRAM_BOT_TOKEN", ""),
        "GOOGLE_SPREADSHEET_ID": values.get("GOOGLE_SPREADSHEET_ID", ""),
        "GOOGLE_SERVICE_ACCOUNT_JSON_B64": service_account_b64,
        "TOURNAMENT_CHAT_ID": values.get("TOURNAMENT_CHAT_ID", ""),
        "ADMIN_USERNAMES": values.get("ADMIN_USERNAMES", "az_stat,SanMorocco"),
        "APP_TZ": values.get("APP_TZ", "Europe/Moscow"),
        "CACHE_TTL_SECONDS": values.get("CACHE_TTL_SECONDS", "60"),
        "DRAFT_TTL_SECONDS": values.get("DRAFT_TTL_SECONDS", "1800"),
    }
    for key, value in deploy_values.items():
        print(f"{key}={mask(value)}")
    print("")
    print("For hosting UI, copy values from .env plus GOOGLE_SERVICE_ACCOUNT_JSON_B64 generated from service-account.json.")
    print("Do not paste the masked values above; they are only a readiness check.")


if __name__ == "__main__":
    main()
