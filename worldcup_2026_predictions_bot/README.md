# World Cup 2026 Prediction Bot

A Python and Telegram application for running a prediction tournament across the complete 48-team, 104-match World Cup. The bot collects match and player predictions, validates every submission, enforces deadlines, calculates scores, and publishes leaderboards and aggregate insights.

Google Sheets provides a transparent operational data layer for fixtures, participants, predictions, results, scoring, and analytical outputs.

## Architecture

```text
Telegram users
      |
      v
Always-on polling worker
      |
      +--> validation and scoring services
      |
      v
Google Sheets
```

The active runtime is a polling worker deployed on an always-on VM. Early webhook and Cloud Functions experiments are archived under [`legacy/cloud_functions/`](./legacy/cloud_functions/) and are not part of the production path.

## Product Capabilities

- Guided Telegram flow for match-score and player-contribution predictions
- Invite/PIN registration and optional username allowlists
- Server-side validation of formats, rosters, deadlines, and repeated player selections
- Private predictions before the deadline and controlled publication afterwards
- Stage-aware scoring from the group phase through the final
- Overall and metric-specific leaderboards
- Aggregate views of player picks and first-score beliefs
- Daily reminders for upcoming matches
- Administrative commands for submission status, scoring, and publication

## Prediction Flow

1. Register with `/start`.
2. Review open fixtures with `/matches`.
3. Start a prediction with `/predict`.
4. Submit seven unique score options.
5. Select one goal-or-assist author from each team's active roster.
6. Confirm the prediction before the deadline.
7. Review the latest saved prediction with `/my`.

Predictions can be edited until the match deadline. The bot keeps only short-lived draft state in memory; durable records are written to Google Sheets.

## Validation and Scoring

The application checks that:

- the participant is registered;
- the match exists and remains open;
- exactly seven unique scores use the expected format;
- selected players belong to the correct active rosters;
- the two selected players are distinct;
- a participant does not reuse the same player across latest predictions;
- cancelled, technical, and void results are excluded from scoring;
- own goals do not receive player-contribution points.

Points increase in the knockout rounds. Tied leaderboard positions are resolved by performance in later stages, starting with the final and moving backwards through the tournament.

## Analytics Outputs

Scoring updates both participant rankings and aggregate analytical views:

- overall leaderboard;
- score, goal, and assist leaderboards;
- match-level player-pick distributions;
- first-score belief summaries;
- stage-level tie-break information.

## Google Sheets Schema

The service expects these sheets:

```text
participants
matches
players
predictions_raw
predictions_latest
results
scoring
leaderboard
leaderboard_by_total
leaderboard_by_score
leaderboard_by_goals
leaderboard_by_assists
match_author_picks
match_first_score_belief
scoring_rules
```

Create or update the required headers:

```bash
python -m wc_predictions_bot.setup_sheets \
  --spreadsheet-id "$GOOGLE_SPREADSHEET_ID" \
  --service-account-file service-account.json
```

## Local Setup

Requires Python 3.11 or later.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .

export TELEGRAM_BOT_TOKEN=...
export GOOGLE_SPREADSHEET_ID=...
export GOOGLE_SERVICE_ACCOUNT_FILE=...
export TOURNAMENT_CHAT_ID=...

python -m wc_predictions_bot.polling
```

The deployment runtime also accepts a base64-encoded service-account value through `GOOGLE_SERVICE_ACCOUNT_JSON_B64`.

Optional access settings:

```text
ADMIN_USERNAMES=organizer_username
OPEN_REGISTRATION_ENABLED=false
ALLOWED_USERNAMES=
APP_TZ=Europe/Moscow
CACHE_TTL_SECONDS=60
DRAFT_TTL_SECONDS=1800
```

See [`DEPLOY.md`](./DEPLOY.md) for the VM and `systemd` deployment workflow, and [`ORGANIZER_GUIDE.md`](./ORGANIZER_GUIDE.md) for result entry and tournament operations.

## Tests

Run the test suite without Telegram or Google credentials:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

The tests use `FakeRepository` to cover the application flow without external services. A complete manual scenario is documented in [`SMOKE_TEST_SCENARIO.md`](./SMOKE_TEST_SCENARIO.md).

## Privacy and Secrets

Participant-level data, Telegram exports, Google Sheets content, local outputs, and credentials are excluded from version control. Never commit `.env`, bot tokens, or service-account files.
