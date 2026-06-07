# Telegram Bot MVP

Минимальная архитектура для webhook:

```text
Telegram webhook -> Python backend / cloud function -> Google Sheets
```

Текущий внешний MVP runtime:

```text
Always-on polling worker -> Telegram Bot API -> Google Sheets
```

Durable-данные живут только в Google Sheets. В памяти хранится только короткий черновик ввода между шагами: выбор матча -> 7 счетов -> автор команды 1 -> автор команды 2 -> подтверждение.

## Нужные доступы

Единый набор для финального e2e:

- `TELEGRAM_BOT_TOKEN`
- `GOOGLE_SPREADSHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON_B64` или `GOOGLE_SERVICE_ACCOUNT_FILE`
- доступ service account к Google Sheet как Editor
- `TOURNAMENT_CHAT_ID`
- деплой-доступ: Yandex Cloud VM для polling-worker

## Sheets Schema

Сервис ожидает листы:

- `participants`
- `matches`
- `players`
- `predictions_raw`
- `predictions_latest`
- `results`
- `scoring`
- `leaderboard`
- `scoring_rules`

Создать/обновить заголовки:

```bash
python -m wc_predictions_bot.setup_sheets \
  --spreadsheet-id "$GOOGLE_SPREADSHEET_ID" \
  --service-account-file service-account.json
```

## Local Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
export TELEGRAM_BOT_TOKEN=...
export GOOGLE_SPREADSHEET_ID=...
export GOOGLE_SERVICE_ACCOUNT_FILE=...
export TOURNAMENT_CHAT_ID=...
python -m wc_predictions_bot.server
```

Healthcheck: `GET /health`. Webhook endpoint: `POST /webhook`.

Quick local polling smoke, without deployment:

```bash
.venv/bin/python -m wc_predictions_bot.polling
```

External worker command on YC VM:

```bash
python -m wc_predictions_bot.polling
```

Cloud Function entrypoint: `main.handler`. Deployment checklist: see `DEPLOY.md`.

Set Telegram webhook after deployment:

```bash
python -m wc_predictions_bot.set_webhook \
  --token "$TELEGRAM_BOT_TOKEN" \
  --url "https://<deployed-host>/webhook"
```

## User Flow

- `/start` -> bind by invite/PIN.
- `/predict` -> choose open match.
- Enter 7 unique scores, comma-separated: `1-0,1-1,2-0,0-0,2-1,1-2,0-1`.
- Choose one G+A author from team 1 active roster, sorted by G+A priority.
- Choose one G+A author from team 2 active roster, sorted by G+A priority.
- Confirm save.
- `/my` shows latest predictions.
- `/help` shows rules.
- `/authors MATCH_ID | Автор1 | Автор2` updates only G+A authors for an existing prediction before deadline.

## Access Modes

- Invite/PIN mode: participants bind through `/start PIN`.
- Test allowlist mode: set `OPEN_REGISTRATION_ENABLED=true` and `ALLOWED_USERNAMES=user1,user2`.
- If `ALLOWED_USERNAMES` is set, only listed Telegram usernames can auto-register without PIN.
- Users outside the list get a message asking them to contact the organizer.

Admin:

- `/publish MATCH_ID` publishes closed predictions to `TOURNAMENT_CHAT_ID` after deadline and marks latest rows locked.
- `/leaderboard` publishes `leaderboard` sheet if it is filled.

## Validation

Hard server-side checks:

- bound participant only;
- match exists and deadline is not passed;
- exactly 7 scores;
- unique score options;
- score format `N-N` or `N:N`;
- author is in the active roster for the correct team;
- direct `/submit` and `/authors` player typos are rejected with roster-based suggestions;
- G+A authors inside one prediction must be distinct;
- selected author was not already used by the same participant in other latest predictions.
- results with status `cancelled`, `technical`, or `void` are ignored in scoring;
- own goals do not give author points.

## Smoke Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

Current local smoke uses `FakeRepository`, so it does not need Telegram or Google secrets.
