from __future__ import annotations

from .app_factory import build_bot_from_env
from .env_loader import load_dotenv
from .sheet_schema import SHEET_HEADERS
from .sheets_repository import SheetsRepository


def main() -> None:
    load_dotenv(".env")
    bot = build_bot_from_env()
    repository = bot.repository
    if not isinstance(repository, SheetsRepository):
        raise RuntimeError("This migration requires SheetsRepository.")

    participants = {participant.participant_id: participant for participant in repository.get_participants()}
    matches = {match.match_id: match for match in repository.get_matches()}
    rows = repository._read_sheet("predictions_latest", use_cache=False)
    migrated: list[dict[str, str]] = []
    for row in rows:
        participant_id = row.get("participant_id", "")
        match_id = row.get("match_id", "")
        participant = participants.get(participant_id)
        match = matches.get(match_id)
        migrated.append(
            {
                "display_name": row.get("display_name") or (participant.display_name if participant else participant_id),
                "match_name": row.get("match_name") or (f"{match.team1} - {match.team2}" if match else match_id),
                "match_id": match_id,
                "submitted_at_msk": row.get("submitted_at_msk", ""),
                **{f"score_{index}": row.get(f"score_{index}", "") for index in range(1, 8)},
                "author_team1": row.get("author_team1", ""),
                "author_team2": row.get("author_team2", ""),
                "is_locked": row.get("is_locked", "FALSE"),
                "validation_status": row.get("validation_status", "valid"),
                "replaces_submission_id": row.get("replaces_submission_id", ""),
                "participant_id": participant_id,
            }
        )
    repository._replace_dict_rows("predictions_latest", migrated)
    print(f"Migrated predictions_latest rows: {len(migrated)}; columns: {len(SHEET_HEADERS['predictions_latest'])}.")


if __name__ == "__main__":
    main()
