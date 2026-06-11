# Telegram Bot MVP

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
- `leaderboard_by_total`
- `leaderboard_by_score`
- `leaderboard_by_goals`
- `leaderboard_by_assists`
- `match_author_picks`
- `match_first_score_belief`
- `scoring_rules`

Инструкция для организатора по заполнению результатов: `ORGANIZER_GUIDE.md`.
Smoke-сценарий одного тестового матча: `SMOKE_TEST_SCENARIO.md`.

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
.venv/bin/python -m wc_predictions_bot.polling
```

External worker command on YC VM:

```bash
python -m wc_predictions_bot.polling
```

Cloud Functions/webhook experiment files are archived under `legacy/cloud_functions/` and are not the active runtime path.

## User Flow

- `/start` -> bind by invite/PIN.
- `/matches` shows compact open match IDs.
- `/predict` -> choose open match. The default list is the union of 5 nearest matches and all matches from the 3 nearest match days; a button can open all matches from the nearest tour.
- Enter 7 unique scores, comma-separated: `1-0,1-1,2-0,0-0,2-1,1-2,0-1`.
- Choose one G+A author from team 1 active roster, sorted by G+A priority.
- Choose one G+A author from team 2 active roster, sorted by G+A priority.
- Confirm save.
- `/my` shows latest predictions.
- `/help` shows rules.
- `/rules` shows detailed rules.
- `/scores MATCH_ID 1-0,1-1,2-0,0-0,2-1,1-2,0-1` updates only score variants for an existing prediction before deadline.
- `/authors MATCH_ID | Автор1 | Автор2` updates only G+A authors for an existing prediction before deadline.

## Access Modes

- Invite/PIN mode: participants bind through `/start PIN`.
- Test allowlist mode: set `OPEN_REGISTRATION_ENABLED=true` and `ALLOWED_USERNAMES=user1,user2`.
- If `ALLOWED_USERNAMES` is set, only listed Telegram usernames can auto-register without PIN.
- Users outside the list get a message asking them to contact the organizer.

Admin:

- `/publish MATCH_ID` publishes closed predictions to `TOURNAMENT_CHAT_ID` after deadline and marks latest rows locked.
- `/status MATCH_ID` shows submitted/missing participants for a match.
- `/insights MATCH_ID` shows aggregate picks for a match: most popular first score, outcome shares, top G+A authors by team, and all selected players grouped by team.
- `/score MATCH_ID` recalculates scoring for one match; `/score all` recalculates all filled results.
- `/score` updates `scoring`, `leaderboard`, metric leaderboards, author-pick analytics, and first-score belief analytics.
- `/leaderboard` publishes `leaderboard` sheet if it is filled.
- Daily notifications are sent at 12:00 MSK to users who have already submitted at least one prediction when there are open matches in the next 24 hours.

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
- scoring increases from 1/8 onward and leaderboard ties are sorted by later-stage points: final, third place, semifinal, quarterfinal, round16, round32, group.

## Smoke Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

Current local smoke uses `FakeRepository`, so it does not need Telegram or Google secrets.
