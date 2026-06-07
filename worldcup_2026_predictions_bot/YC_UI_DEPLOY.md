# Yandex Cloud UI Deploy

Target architecture:

```text
Telegram webhook -> Yandex Cloud Function -> Google Sheets
```

## 1. Upload Package

Use this archive:

```text
yc_function.zip
```

Entrypoint:

```text
main.handler
```

Runtime:

```text
Python 3.12
```

If Python 3.12 is unavailable in the UI, use Python 3.11.

## 2. Function Env Vars

Set these variables in the Yandex Cloud Function version:

```text
TELEGRAM_BOT_TOKEN
GOOGLE_SPREADSHEET_ID
GOOGLE_SERVICE_ACCOUNT_JSON_B64
TOURNAMENT_CHAT_ID
ADMIN_USERNAMES=az_stat,SanMorocco
OPEN_REGISTRATION_ENABLED=false
ALLOWED_USERNAMES=
APP_TZ=Europe/Moscow
CACHE_TTL_SECONDS=60
DRAFT_TTL_SECONDS=1800
```

`TOURNAMENT_CHAT_ID` can be empty for the first private-chat smoke test.

To copy service account JSON as base64:

```bash
cd /Users/aozolotarev/Documents/personal/outputs/worldcup_2026_predictions/telegram_bot_mvp
base64 -i service-account.json | pbcopy
```

## 3. Create Function Through UI

1. Open Yandex Cloud Console.
2. Select your cloud and folder.
3. Go to Cloud Functions.
4. Click Create function.
5. Name: `wc-predictions-bot`.
6. Create version.
7. Runtime: Python 3.12 or Python 3.11.
8. Method: ZIP archive.
9. Upload `yc_function.zip`.
10. Entrypoint: `main.handler`.
11. Add env vars above.
12. Timeout: 30 seconds.
13. Memory: 256 MB or 512 MB.
14. Make function public / allow unauthenticated HTTPS invocation.

## 4. Smoke Test Function

On the Testing tab, payload:

```json
{
  "body": "{\"message\":{\"chat\":{\"id\":123},\"from\":{\"id\":123,\"username\":\"test\"},\"text\":\"/help\"},\"update_id\":1}"
}
```

Expected output:

```json
{"statusCode": 200, "body": "{\"ok\": true}"}
```

The function may still fail to send a Telegram message if Telegram API is unavailable from Yandex Cloud, but it should import and run.

## 5. Set Telegram Webhook

After creating the function, copy its HTTPS invoke URL.

Webhook URL:

```text
https://functions.yandexcloud.net/<function-id>
```

Set webhook from any environment that can reach Telegram Bot API:

```bash
curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://functions.yandexcloud.net/<function-id>"}'
```

If local Telegram API access is blocked, create a temporary helper function in Yandex Cloud or use Cloud Shell / another network.

## 6. Telegram E2E

Private chat:

```text
/start TESTUSER
/predict
```

Use test prediction:

```text
1-0,1-1,2-0,0-0,2-1,1-2,0-1
```

Pick `Месси`, then `Мбаппе`, confirm save.

Check Google Sheets:

- `predictions_raw`
- `predictions_latest`
