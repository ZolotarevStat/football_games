# Deploy Notes

Preferred MVP target: Yandex Cloud Compute VM with a `systemd` polling worker.

Why polling now:

- no local `setWebhook` call is required;
- no public HTTPS endpoint is required;
- Telegram updates are read by the hosted worker itself;
- the laptop is not part of production runtime.

## YC VM Worker

Start command:

```bash
python -m wc_predictions_bot.polling
```

Environment variables:

```text
TELEGRAM_BOT_TOKEN
GOOGLE_SPREADSHEET_ID
GOOGLE_SERVICE_ACCOUNT_JSON_B64
TOURNAMENT_CHAT_ID
ADMIN_USERNAMES=az_stat,SanMorocco
APP_TZ=Europe/Moscow
CACHE_TTL_SECONDS=60
DRAFT_TTL_SECONDS=1800
```

`GOOGLE_SERVICE_ACCOUNT_JSON_B64` is base64 of `service-account.json`.

Readiness check without printing secrets:

```bash
.venv/bin/python -m wc_predictions_bot.print_deploy_env
```

Do not deploy `.env` or `service-account.json` files. Put secrets into hosting environment variables.

Typical VM layout:

```text
/opt/wc-predictions-bot
  .env
  .venv/
  src/
  tests/
```

Typical smoke sequence:

```bash
cd /opt/wc-predictions-bot
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
sudo systemctl restart wc-predictions-bot
systemctl is-active wc-predictions-bot
```

## Test After Worker Starts

1. In private chat with the bot:

```text
/start TESTUSER
```

2. Then:

```text
/predict
```

3. Submit:

```text
1-0,1-1,2-0,0-0,2-1,1-2,0-1
```

4. Pick `Месси` and `Мбаппе`.
5. Confirm save.
6. Check `predictions_raw` and `predictions_latest` in Google Sheets.

## Webhook Function Alternative

Yandex Cloud Function behind API Gateway or direct HTTPS trigger.

## Function

Use Python 3.11+ runtime.

Entrypoint:

```text
main.handler
```

Environment variables:

```text
TELEGRAM_BOT_TOKEN
GOOGLE_SPREADSHEET_ID
GOOGLE_SERVICE_ACCOUNT_JSON_B64
TOURNAMENT_CHAT_ID
ADMIN_USERNAMES=az_stat,SanMorocco
APP_TZ=Europe/Moscow
CACHE_TTL_SECONDS=60
DRAFT_TTL_SECONDS=1800
```

Package contents should include:

```text
main.py
requirements.txt
src/wc_predictions_bot/**
```

## Setup Order

1. Create Telegram bot token via BotFather.
2. Create Google service account and share the Google Sheet with its email as Editor.
3. Encode service account JSON:

```bash
base64 -i service-account.json
```

4. Deploy function with env vars above.
5. Run the sheet schema setup against the target spreadsheet.
6. Set Telegram webhook to deployed HTTPS URL.
7. Send `/start <invite_code>` from one test Telegram account.
8. Run one full prediction on a future test match.
9. Run `/publish <match_id>` on an already-deadline-passed test match.

## Stop Rules

- Cloud packaging >45 minutes: switch to Railway/Render Python service.
- Google auth >45 minutes: use Apps Script write endpoint fallback.
- Webhook setup >30 minutes: use polling on always-on service for MVP.
