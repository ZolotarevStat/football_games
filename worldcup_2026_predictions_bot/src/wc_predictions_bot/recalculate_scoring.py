from __future__ import annotations

import argparse

from .app_factory import build_bot_from_env
from .env_loader import load_dotenv
from .scoring import calculate_scoring, format_leaderboard


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--match-id", default="all")
    args = parser.parse_args()

    load_dotenv(args.env_file)
    bot = build_bot_from_env()
    match_id = "" if args.match_id.lower() == "all" else args.match_id
    all_result = calculate_scoring(
        predictions=bot.repository.get_all_latest_predictions(),
        results=bot.repository.get_results(),
        participants=bot.repository.get_participants(),
        matches=bot.repository.get_matches(),
        now_iso=bot._now_iso(),
    )
    if not all_result.match_ids:
        raise RuntimeError("No matching rows in results.")
    display_result = all_result
    if match_id:
        display_result = calculate_scoring(
            predictions=bot.repository.get_all_latest_predictions(),
            results=bot.repository.get_results(),
            participants=bot.repository.get_participants(),
            matches=bot.repository.get_matches(),
            now_iso=bot._now_iso(),
            match_id=match_id,
        )
        if not display_result.match_ids:
            raise RuntimeError(f"No matching rows in results for match_id={match_id}.")
    bot.repository.replace_scoring_rows(all_result.scoring_rows)
    bot.repository.replace_leaderboard_rows(all_result.leaderboard_rows)
    for sheet_name, rows in all_result.analytics_rows.items():
        bot.repository.replace_analytics_rows(sheet_name, rows)
    print(f"Updated scoring rows: {len(all_result.scoring_rows)}")
    print(f"Updated leaderboard rows: {len(all_result.leaderboard_rows)}")
    print(f"Updated analytics sheets: {len(all_result.analytics_rows)}")
    print(format_leaderboard(display_result.leaderboard_rows))


if __name__ == "__main__":
    main()
