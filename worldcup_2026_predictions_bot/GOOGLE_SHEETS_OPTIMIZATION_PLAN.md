# Google Sheets API optimization plan

## Current symptom

The bot can hit Google Sheets quota during bursts of manual edits, `/my`, `/score`, `/publish`, and post-match admin flows.
Observed failure class: write quota `429` for Google Sheets API. User-facing bot errors must preserve the intended prediction change so the user can forward it to the organizer.

## What was already reduced

- Removed filter refresh after every append/update of prediction rows.
- Added retries for transient Google Sheets errors and quota responses.
- Cached `participants` and `predictions_latest` reads within the repository TTL; successful writes clear the affected sheet cache.
- `/score MATCH_ID` writes cumulative scoring/leaderboard sheets once while displaying only the selected match in Telegram.

## Likely API hot spots

- `get_participant_by_telegram_id` on every update.
- `get_latest_for_participant` in `/my`, edit validation, author uniqueness checks, and save paths.
- `save_prediction`: currently reads `predictions_latest`, appends `predictions_raw`, then updates/appends `predictions_latest`.
- `mark_match_locked`: updates one row per prediction, which can spike writes after `/publish`.
- Scoring/admin flows clear and rewrite multiple sheets; this is acceptable for post-match admin use but should not run repeatedly.

## P1 optimizations

1. Add row indexes for `participants` and `predictions_latest`.
   - Cache maps such as `telegram_id -> row`, `(participant_id, match_id) -> row`.
   - Rebuild them after sheet writes and on TTL expiry.
   - Keep append-only raw history unchanged.

2. Use `batchUpdate` for multi-row updates.
   - `mark_match_locked` should update all affected rows in one request.
   - Post-match analytics formatting should be grouped where possible.

3. Split read ranges by command.
   - `/my` and edit commands need only `predictions_latest`, `matches`, and sometimes `players`.
   - Public `/matches` does not need participants or predictions unless marking submitted matches for a bound participant.

4. Avoid repeated reads inside one command.
   - Load `latest`, `match`, `players` once in the bot flow and pass them down.
   - Avoid helper methods that re-read the same sheet during one command.

## P2 optimizations

1. Introduce a lightweight local state cache on the VM.
   - Keep Sheets as source of truth.
   - Cache read-heavy sheets in process memory with explicit invalidation after writes.
   - Optional: persist row-index metadata locally for restart warmup, but avoid making VM disk a second source of truth.

2. Move latest-state operations away from Google Sheets if quota stays painful.
   - SQLite on VM for hot path + periodic Sheets export is faster and cheaper, but increases operational complexity.
   - For MVP, keep Sheets unless quota failures continue after P1.

## Operational guidance

- Do not spam `/score all` or the post-match one-button flow repeatedly within the same minute.
- If a user receives a quota message, they should forward it to the organizer; it contains the intended scores/authors.
- If quota spikes during match deadline windows, wait 60-90 seconds and retry after the quota window resets.
