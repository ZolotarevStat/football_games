from __future__ import annotations

import argparse

from .config import Config
from .env_loader import load_dotenv
from .playoff_calendar import build_playoff_calendar
from .sheets_repository import SheetsRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    load_dotenv(args.env_file)
    config = Config.from_env()
    if not config.spreadsheet_id:
        raise RuntimeError("GOOGLE_SPREADSHEET_ID is empty.")

    repository = SheetsRepository(
        spreadsheet_id=config.spreadsheet_id,
        service_account_json_b64=config.service_account_json_b64,
        service_account_file=config.service_account_file,
        cache_ttl_seconds=config.cache_ttl_seconds,
    )
    update = build_playoff_calendar(repository.get_results() if args.apply else [])
    if args.apply:
        repository.upsert_matches(update.matches)

    action = "updated" if args.apply else "dry-run"
    print(
        f"playoff_calendar {action}: matches={len(update.matches)} "
        f"open={update.open_match_count} planned={update.planned_match_count} "
        f"resolved_future={update.resolved_future_match_count}"
    )
    for match in update.matches:
        print(
            f"{match.match_id}\t{match.tour}\t{match.kickoff_msk.isoformat(timespec='minutes')}\t"
            f"{match.team1} - {match.team2}\t{match.status}"
        )
    if update.warnings:
        print("warnings:")
        for warning in update.warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
