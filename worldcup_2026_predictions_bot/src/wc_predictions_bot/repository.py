from __future__ import annotations

from abc import ABC, abstractmethod

from .models import LatestPrediction, Match, MatchResult, Participant, Player


class PredictionRepository(ABC):
    @abstractmethod
    def get_participant_by_telegram_id(self, telegram_id: str) -> Participant | None:
        raise NotImplementedError

    @abstractmethod
    def bind_participant(self, invite_code: str, telegram_id: str, username: str, bound_at: str) -> Participant | None:
        raise NotImplementedError

    @abstractmethod
    def register_participant(
        self,
        *,
        telegram_id: str,
        username: str,
        display_name: str,
        created_at: str,
    ) -> Participant:
        raise NotImplementedError

    @abstractmethod
    def get_open_matches(self, now_iso_msk: str) -> list[Match]:
        raise NotImplementedError

    @abstractmethod
    def get_matches(self) -> list[Match]:
        raise NotImplementedError

    @abstractmethod
    def get_match(self, match_id: str) -> Match | None:
        raise NotImplementedError

    @abstractmethod
    def get_players_for_match(self, match: Match) -> list[Player]:
        raise NotImplementedError

    @abstractmethod
    def get_latest_for_participant(self, participant_id: str) -> list[LatestPrediction]:
        raise NotImplementedError

    @abstractmethod
    def get_latest_for_match(self, match_id: str) -> list[LatestPrediction]:
        raise NotImplementedError

    @abstractmethod
    def get_all_latest_predictions(self) -> list[LatestPrediction]:
        raise NotImplementedError

    @abstractmethod
    def get_participants(self) -> list[Participant]:
        raise NotImplementedError

    @abstractmethod
    def get_participants_with_predictions(self) -> list[Participant]:
        raise NotImplementedError

    @abstractmethod
    def get_results(self) -> list[MatchResult]:
        raise NotImplementedError

    @abstractmethod
    def replace_scoring_rows(self, rows: list[dict[str, str]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def replace_leaderboard_rows(self, rows: list[dict[str, str]]) -> None:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def mark_match_locked(self, match_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_leaderboard_rows(self) -> list[dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def notification_was_sent(self, notification_key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def record_notification(
        self,
        *,
        notification_key: str,
        notification_type: str,
        sent_at_msk: str,
        recipient_count: int,
        details: str,
    ) -> None:
        raise NotImplementedError
