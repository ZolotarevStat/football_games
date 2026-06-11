from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")


def load_env(path: Path) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


def call_telegram(method: str, payload: dict[str, object]) -> dict[str, object]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env")
    webhook_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_WEBHOOK_URL
    if not webhook_url:
        raise RuntimeError("WEBHOOK_URL is missing. Pass it as argv[1] or set WEBHOOK_URL in .env.")
    result = call_telegram(
        "setWebhook",
        {
            "url": webhook_url,
            "drop_pending_updates": "true",
            "allowed_updates": json.dumps(["message", "callback_query"]),
            "max_connections": "1",
        },
    )
    safe_result = {
        "ok": result.get("ok"),
        "description": result.get("description"),
        "result": result.get("result"),
        "webhook_url": webhook_url,
    }
    print(json.dumps(safe_result, ensure_ascii=False))
    info = call_telegram("getWebhookInfo", {})
    info_result = info.get("result") or {}
    safe_info = {
        "ok": info.get("ok"),
        "url_present": bool(info_result.get("url")),
        "pending_update_count": info_result.get("pending_update_count"),
        "last_error_date": info_result.get("last_error_date"),
        "last_error_message": info_result.get("last_error_message"),
        "max_connections": info_result.get("max_connections"),
        "allowed_updates": info_result.get("allowed_updates"),
    }
    print(json.dumps(safe_info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
