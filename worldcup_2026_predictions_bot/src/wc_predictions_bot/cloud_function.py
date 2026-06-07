from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import requests

from .app_factory import build_bot_from_env
from .bot import PredictionBot
from .telegram_api import WebhookReplyTelegramApi

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
LOG = logging.getLogger(__name__)
BOT = build_bot_from_env()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        if isinstance(event, str):
            event = json.loads(event or "{}")
        admin_action = _query_params(event).get("admin_action") or _raw_query(event).get("admin_action")
        if admin_action == "set_webhook":
            return _set_webhook(event)
        if admin_action == "get_webhook_info":
            return _get_webhook_info()
        if "message" in event or "callback_query" in event:
            update = event
        else:
            body = event.get("body") or "{}"
            if event.get("isBase64Encoded"):
                body = base64.b64decode(body).decode("utf-8")
            update = json.loads(body)
        reply_telegram = WebhookReplyTelegramApi(BOT.telegram)
        request_bot = PredictionBot(BOT.config, BOT.repository, reply_telegram)
        request_bot.handle_update(update)
        webhook_response = reply_telegram.first_webhook_response()
        if webhook_response:
            return {
                "statusCode": 200,
                "headers": {"content-type": "application/json"},
                "body": json.dumps(webhook_response, ensure_ascii=False),
            }
        return {"statusCode": 200, "body": json.dumps({"ok": True})}
    except Exception:
        LOG.exception("Cloud function failed")
        return {"statusCode": 200, "body": json.dumps({"ok": False})}


def _query_params(event: dict[str, Any]) -> dict[str, str]:
    params = event.get("queryStringParameters") or {}
    if isinstance(params, dict):
        return {str(key): str(value) for key, value in params.items()}
    return {}


def _raw_query(event: dict[str, Any]) -> dict[str, str]:
    raw = event.get("queryString") or ""
    if not isinstance(raw, str) or not raw:
        return {}
    result: dict[str, str] = {}
    for part in raw.split("&"):
        if "=" not in part:
            result[part] = ""
            continue
        key, value = part.split("=", 1)
        result[key] = value
    return result


def _set_webhook(event: dict[str, Any]) -> dict[str, Any]:
    params = _query_params(event) or _raw_query(event)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    secret = os.getenv("ADMIN_SETUP_SECRET", "")
    if secret and params.get("secret") != secret:
        return {"statusCode": 403, "body": json.dumps({"ok": False, "error": "forbidden"})}
    webhook_url = params.get("url") or os.getenv("WEBHOOK_URL", "")
    try:
        if not token:
            return {"statusCode": 200, "body": json.dumps({"ok": False, "error": "token_missing"})}
        if not webhook_url:
            return {"statusCode": 200, "body": json.dumps({"ok": False, "error": "webhook_url_missing"})}
        drop_pending = params.get("drop_pending_updates", "").lower() in {"1", "true", "yes"}
        response = requests.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={
                "url": webhook_url,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": drop_pending,
                "max_connections": 1,
            },
            timeout=20,
        )
        data = response.json()
        return {
            "statusCode": response.status_code,
            "body": json.dumps(
                {
                    "ok": data.get("ok"),
                    "description": data.get("description", ""),
                    "result": data.get("result"),
                },
                ensure_ascii=False,
            ),
        }
    except Exception as exc:
        LOG.exception("Set webhook failed")
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "ok": False,
                    "error_type": exc.__class__.__name__,
                    "token_present": bool(token),
                    "webhook_url_present": bool(webhook_url),
                    "query_params_seen": bool(params),
                }
            ),
        }


def _get_webhook_info() -> dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    try:
        if not token:
            return {"statusCode": 200, "body": json.dumps({"ok": False, "error": "token_missing"})}
        response = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=20)
        data = response.json()
        result = data.get("result") or {}
        safe_result = {
            "url_present": bool(result.get("url")),
            "has_custom_certificate": result.get("has_custom_certificate"),
            "pending_update_count": result.get("pending_update_count"),
            "last_error_date": result.get("last_error_date"),
            "last_error_message": result.get("last_error_message"),
            "max_connections": result.get("max_connections"),
        }
        return {
            "statusCode": response.status_code,
            "body": json.dumps(
                {
                    "ok": data.get("ok"),
                    "result": safe_result,
                },
                ensure_ascii=False,
            ),
        }
    except Exception as exc:
        LOG.exception("Get webhook info failed")
        return {
            "statusCode": 200,
            "body": json.dumps({"ok": False, "error_type": exc.__class__.__name__, "token_present": bool(token)}),
        }
