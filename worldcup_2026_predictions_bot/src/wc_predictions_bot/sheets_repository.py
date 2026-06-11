from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from .models import LatestPrediction, Match, MatchResult, Participant, Player
from .repository import PredictionRepository
from .sheet_schema import SHEET_HEADERS


class SheetsRepository(PredictionRepository):
    def __init__(
        self,
        *,
        spreadsheet_id: str,
        service_account_json_b64: str = "",
        service_account_file: str = "",
        cache_ttl_seconds: int = 60,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.service_account_json_b64 = service_account_json_b64
        self.service_account_file = service_account_file
        self.cache_ttl_seconds = cache_ttl_seconds
        self._service: Any | None = None
        self._cache: dict[str, tuple[float, list[dict[str, str]]]] = {}

    @property
    def service(self) -> Any:
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def _build_service(self) -> Any:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        if self.service_account_json_b64:
            raw = base64.b64decode(self.service_account_json_b64).decode("utf-8")
            info = json.loads(raw)
            credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        elif self.service_account_file:
            credentials = service_account.Credentials.from_service_account_file(self.service_account_file, scopes=scopes)
        else:
            raise RuntimeError("Google service account credentials are not configured.")
        return build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def _values(self) -> Any:
        return self.service.spreadsheets().values()

    def _read_sheet(self, sheet_name: str, use_cache: bool = True) -> list[dict[str, str]]:
        now = time.monotonic()
        cached = self._cache.get(sheet_name)
        if use_cache and cached and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]

        result = self._values().get(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A:Z").execute()
        values = result.get("values", [])
        if not values:
            rows: list[dict[str, str]] = []
        else:
            headers = [str(value).strip() for value in values[0]]
            rows = [
                {headers[index]: str(value).strip() for index, value in enumerate(row) if index < len(headers)}
                for row in values[1:]
                if any(str(value).strip() for value in row)
            ]
        self._cache[sheet_name] = (now, rows)
        return rows

    def _clear_cache(self, *sheet_names: str) -> None:
        for sheet_name in sheet_names:
            self._cache.pop(sheet_name, None)

    def _append_dict(self, sheet_name: str, row: dict[str, str]) -> None:
        headers = SHEET_HEADERS[sheet_name]
        values = [[row.get(header, "") for header in headers]]
        self._values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{sheet_name}!A:Z",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
        self._clear_cache(sheet_name)

    def _update_row(self, sheet_name: str, one_based_row: int, row: dict[str, str]) -> None:
        headers = SHEET_HEADERS[sheet_name]
        values = [[row.get(header, "") for header in headers]]
        end_col = chr(ord("A") + len(headers) - 1)
        self._values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{sheet_name}!A{one_based_row}:{end_col}{one_based_row}",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
        self._clear_cache(sheet_name)

    def _replace_dict_rows(self, sheet_name: str, rows: list[dict[str, str]]) -> None:
        headers = SHEET_HEADERS[sheet_name]
        values = [headers, *[[row.get(header, "") for header in headers] for row in rows]]
        end_col = chr(ord("A") + len(headers) - 1)
        self._values().clear(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A:Z").execute()
        self._values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{sheet_name}!A1:{end_col}{len(values)}",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
        self._clear_cache(sheet_name)

    def get_participant_by_telegram_id(self, telegram_id: str) -> Participant | None:
        for row in self._read_sheet("participants", use_cache=False):
            if row.get("telegram_id") == telegram_id:
                return _participant(row)
        return None

    def get_participants(self) -> list[Participant]:
        return [_participant(row) for row in self._read_sheet("participants", use_cache=False)]

    def bind_participant(self, invite_code: str, telegram_id: str, username: str, bound_at: str) -> Participant | None:
        rows = self._read_sheet("participants", use_cache=False)
        headers = SHEET_HEADERS["participants"]
        for index, row in enumerate(rows, start=2):
            if row.get("invite_code", "").strip().lower() != invite_code.strip().lower():
                continue
            if row.get("status", "active").lower() not in {"active", "admin", ""}:
                return None
            if row.get("telegram_id") and row.get("telegram_id") != telegram_id:
                return None
            row = {header: row.get(header, "") for header in headers}
            row["telegram_id"] = telegram_id
            row["telegram_username"] = username
            row["bound_at"] = bound_at
            self._update_row("participants", index, row)
            return _participant(row)
        return None

    def register_participant(
        self,
        *,
        telegram_id: str,
        username: str,
        display_name: str,
        created_at: str,
    ) -> Participant:
        existing = self.get_participant_by_telegram_id(telegram_id)
        if existing:
            return existing
        participant = Participant(
            participant_id=f"tg_{telegram_id}",
            display_name=display_name,
            telegram_username=username,
            telegram_id=telegram_id,
            invite_code="",
            status="active",
            role="",
        )
        self._append_dict(
            "participants",
            {
                "participant_id": participant.participant_id,
                "display_name": participant.display_name,
                "telegram_username": participant.telegram_username,
                "telegram_id": participant.telegram_id,
                "invite_code": "",
                "status": "active",
                "created_at": created_at,
                "bound_at": created_at,
                "role": "",
            },
        )
        return participant

    def get_open_matches(self, now_iso_msk: str) -> list[Match]:
        now_msk = datetime.fromisoformat(now_iso_msk)
        matches = self.get_matches()
        return [
            match
            for match in matches
            if match.status.lower() in {"open", "scheduled", ""}
            and now_msk < match.deadline_msk
        ]

    def get_matches(self) -> list[Match]:
        return [_match(row) for row in self._read_sheet("matches")]

    def get_match(self, match_id: str) -> Match | None:
        for row in self._read_sheet("matches"):
            if row.get("match_id") == match_id:
                return _match(row)
        return None

    def get_players_for_match(self, match: Match) -> list[Player]:
        players = [_player(row) for row in self._read_sheet("players")]
        teams = {match.team1, match.team2}
        return sorted(
            [
                player
                for player in players
                if player.team in teams and player.is_active
            ],
            key=lambda player: (player.team, -player.priority, player.top_rank_in_team, player.display_name),
        )

    def get_latest_for_participant(self, participant_id: str) -> list[LatestPrediction]:
        return [
            _latest(row)
            for row in self._read_sheet("predictions_latest", use_cache=False)
            if row.get("participant_id") == participant_id and row.get("validation_status", "valid") == "valid"
        ]

    def get_latest_for_match(self, match_id: str) -> list[LatestPrediction]:
        return [
            _latest(row)
            for row in self._read_sheet("predictions_latest", use_cache=False)
            if row.get("match_id") == match_id and row.get("validation_status", "valid") == "valid"
        ]

    def get_all_latest_predictions(self) -> list[LatestPrediction]:
        return [
            _latest(row)
            for row in self._read_sheet("predictions_latest", use_cache=False)
            if row.get("validation_status", "valid") == "valid"
        ]

    def get_participants_with_predictions(self) -> list[Participant]:
        predicted_participant_ids = {
            prediction.participant_id
            for prediction in self.get_all_latest_predictions()
            if prediction.participant_id
        }
        return [
            participant
            for participant in self.get_participants()
            if participant.participant_id in predicted_participant_ids
            and participant.telegram_id
            and participant.status.strip().lower() in {"active", "admin", ""}
        ]

    def get_results(self) -> list[MatchResult]:
        return [
            _result(row)
            for row in self._read_sheet("results", use_cache=False)
            if row.get("match_id") and row.get("actual_score")
        ]

    def replace_scoring_rows(self, rows: list[dict[str, str]]) -> None:
        self._replace_dict_rows("scoring", rows)

    def replace_leaderboard_rows(self, rows: list[dict[str, str]]) -> None:
        self._replace_dict_rows("leaderboard", rows)

    def replace_analytics_rows(self, sheet_name: str, rows: list[dict[str, str]]) -> None:
        if sheet_name not in SHEET_HEADERS:
            raise ValueError(f"Unknown analytics sheet: {sheet_name}")
        self._replace_dict_rows(sheet_name, rows)

    def save_prediction(
        self,
        *,
        timestamp_msk: str,
        telegram_id: str,
        participant_id: str,
        match_id: str,
        scores: list[str],
        author_team1: str,
        author_team2: str,
        source_update_id: str,
    ) -> str:
        latest_rows = self._read_sheet("predictions_latest", use_cache=False)
        existing_row_index = None
        for index, row in enumerate(latest_rows, start=2):
            if row.get("participant_id") == participant_id and row.get("match_id") == match_id:
                existing_row_index = index
                break

        participant = self._participant_by_id(participant_id)
        match = self.get_match(match_id)
        display_name = participant.display_name if participant else participant_id
        match_name = f"{match.team1} - {match.team2}" if match else match_id
        submission_id = uuid.uuid4().hex
        raw_row = {
            "submission_id": submission_id,
            "timestamp_msk": timestamp_msk,
            "telegram_id": telegram_id,
            "participant_id": participant_id,
            "match_id": match_id,
            **{f"score_{index}": score for index, score in enumerate(scores, start=1)},
            "author_team1": author_team1,
            "author_team2": author_team2,
            "validation_status": "valid",
            "source_update_id": source_update_id,
            "is_replacement": "TRUE" if existing_row_index else "FALSE",
        }
        self._append_dict("predictions_raw", raw_row)

        latest_row = {
            "display_name": display_name,
            "match_name": match_name,
            "match_id": match_id,
            "submitted_at_msk": timestamp_msk,
            **{f"score_{index}": score for index, score in enumerate(scores, start=1)},
            "author_team1": author_team1,
            "author_team2": author_team2,
            "is_locked": "FALSE",
            "validation_status": "valid",
            "replaces_submission_id": submission_id,
            "participant_id": participant_id,
        }
        if existing_row_index:
            self._update_row("predictions_latest", existing_row_index, latest_row)
        else:
            self._append_dict("predictions_latest", latest_row)
        return submission_id

    def mark_match_locked(self, match_id: str) -> None:
        rows = self._read_sheet("predictions_latest", use_cache=False)
        for index, row in enumerate(rows, start=2):
            if row.get("match_id") != match_id:
                continue
            updated = {header: row.get(header, "") for header in SHEET_HEADERS["predictions_latest"]}
            updated["is_locked"] = "TRUE"
            self._update_row("predictions_latest", index, updated)

    def get_leaderboard_rows(self) -> list[dict[str, str]]:
        return self._read_sheet("leaderboard", use_cache=False)

    def notification_was_sent(self, notification_key: str) -> bool:
        return any(
            row.get("notification_key") == notification_key
            for row in self._read_sheet("notifications_log", use_cache=False)
        )

    def record_notification(
        self,
        *,
        notification_key: str,
        notification_type: str,
        sent_at_msk: str,
        recipient_count: int,
        details: str,
    ) -> None:
        self._append_dict(
            "notifications_log",
            {
                "notification_key": notification_key,
                "notification_type": notification_type,
                "sent_at_msk": sent_at_msk,
                "recipient_count": str(recipient_count),
                "details": details,
            },
        )

    def _participant_by_id(self, participant_id: str) -> Participant | None:
        for participant in self.get_participants():
            if participant.participant_id == participant_id:
                return participant
        return None


def _parse_dt(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo("Europe/Moscow"))
    return parsed


def _participant(row: dict[str, str]) -> Participant:
    return Participant(
        participant_id=row.get("participant_id", ""),
        display_name=row.get("display_name", ""),
        telegram_username=row.get("telegram_username", ""),
        telegram_id=row.get("telegram_id", ""),
        invite_code=row.get("invite_code", ""),
        status=row.get("status", "active"),
        role=row.get("role", ""),
    )


def _match(row: dict[str, str]) -> Match:
    return Match(
        match_id=row.get("match_id", ""),
        group=row.get("group", ""),
        tour=row.get("tour", ""),
        kickoff_msk=_parse_dt(row.get("kickoff_msk", "")),
        deadline_msk=_parse_dt(row.get("deadline_msk", "")),
        team1=row.get("team1", ""),
        team2=row.get("team2", ""),
        status=row.get("status", "open"),
    )


def _player(row: dict[str, str]) -> Player:
    rank_raw = row.get("top_rank_in_team", "999") or "999"
    priority_raw = row.get("priority", "0") or "0"
    return Player(
        team=row.get("team", ""),
        position=row.get("position", ""),
        player_name_ru=row.get("player_name_ru", ""),
        player_name_en=row.get("player_name_en", ""),
        priority=_float(priority_raw),
        top_rank_in_team=int(float(rank_raw)),
        is_active=row.get("is_active", "TRUE").strip().upper() not in {"FALSE", "0", "NO"},
    )


def _float(value: str) -> float:
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return 0.0


def _latest(row: dict[str, str]) -> LatestPrediction:
    scores = tuple(row.get(f"score_{index}", "") for index in range(1, 8))
    return LatestPrediction(
        participant_id=row.get("participant_id", ""),
        match_id=row.get("match_id", ""),
        submitted_at_msk=row.get("submitted_at_msk", ""),
        scores=scores,
        author_team1=row.get("author_team1", ""),
        author_team2=row.get("author_team2", ""),
        display_name=row.get("display_name", ""),
        match_name=row.get("match_name", ""),
        is_locked=row.get("is_locked", "").strip().upper() in {"TRUE", "1", "YES"},
    )


def _split_names(value: str) -> tuple[str, ...]:
    normalized = value.replace(";", ",").replace("\n", ",")
    return tuple(part.strip() for part in normalized.split(",") if part.strip())


def _result(row: dict[str, str]) -> MatchResult:
    return MatchResult(
        match_id=row.get("match_id", ""),
        actual_score=row.get("actual_score", "").replace(":", "-"),
        status=row.get("status", "final"),
        goals=_split_names(row.get("goals", "")),
        assists=_split_names(row.get("assists", "")),
        own_goals=_split_names(row.get("own_goals", "")),
        updated_at=row.get("updated_at", ""),
    )
