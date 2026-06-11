from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import LatestPrediction, Match, MatchResult, Participant, Player
from .repository import PredictionRepository


class FakeRepository(PredictionRepository):
    def __init__(self) -> None:
        tz = ZoneInfo("Europe/Moscow")
        now = datetime.now(tz)
        self.participants = {
            "p1": Participant(
                participant_id="p1",
                display_name="Тестовый участник",
                telegram_id="100",
                invite_code="PIN100",
                status="active",
            ),
            "admin": Participant(
                participant_id="admin",
                display_name="Организатор",
                telegram_username="az_stat",
                telegram_id="101",
                invite_code="ADMIN",
                status="admin",
                role="admin",
            ),
            "p2": Participant(
                participant_id="p2",
                display_name="Новый участник",
                invite_code="PIN200",
                status="active",
            ),
        }
        self.matches = {
            "m1": Match(
                match_id="m1",
                group="A",
                tour="1",
                kickoff_msk=now + timedelta(hours=3),
                deadline_msk=now + timedelta(hours=3, minutes=-5),
                team1="Аргентина",
                team2="Франция",
                status="open",
            ),
            "m2": Match(
                match_id="m2",
                group="A",
                tour="1",
                kickoff_msk=now - timedelta(hours=1),
                deadline_msk=now - timedelta(hours=1, minutes=5),
                team1="Бразилия",
                team2="Испания",
                status="open",
            ),
        }
        self.players = [
            Player(team="Аргентина", player_name_ru="Месси", priority=90, top_rank_in_team=1),
            Player(team="Аргентина", player_name_ru="Альварес", priority=70, top_rank_in_team=2),
            Player(team="Франция", player_name_ru="Мбаппе", priority=95, top_rank_in_team=1),
            Player(team="Франция", player_name_ru="Гризманн", priority=65, top_rank_in_team=2),
            Player(team="Бразилия", player_name_ru="Винисиус", priority=80, top_rank_in_team=1),
            Player(team="Испания", player_name_ru="Ямаль", priority=75, top_rank_in_team=1),
        ]
        self.latest: list[LatestPrediction] = []
        self.results: list[MatchResult] = []
        self.scoring_rows: list[dict[str, str]] = []
        self.leaderboard_rows: list[dict[str, str]] = []
        self.raw_rows: list[dict[str, str]] = []
        self.locked_matches: list[str] = []
        self.notifications: list[dict[str, str]] = []

    def get_participant_by_telegram_id(self, telegram_id: str) -> Participant | None:
        return next((p for p in self.participants.values() if p.telegram_id == telegram_id), None)

    def bind_participant(self, invite_code: str, telegram_id: str, username: str, bound_at: str) -> Participant | None:
        for participant_id, participant in self.participants.items():
            if participant.invite_code.lower() != invite_code.lower():
                continue
            if participant.telegram_id and participant.telegram_id != telegram_id:
                return None
            updated = Participant(
                participant_id=participant.participant_id,
                display_name=participant.display_name,
                telegram_username=username,
                telegram_id=telegram_id,
                invite_code=participant.invite_code,
                status=participant.status,
                role=participant.role,
            )
            self.participants[participant_id] = updated
            return updated
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
            status="active",
        )
        self.participants[participant.participant_id] = participant
        return participant

    def get_open_matches(self, now_iso_msk: str) -> list[Match]:
        now = datetime.fromisoformat(now_iso_msk)
        return [
            match
            for match in self.matches.values()
            if match.status == "open" and now < match.deadline_msk
        ]

    def get_matches(self) -> list[Match]:
        return list(self.matches.values())

    def get_match(self, match_id: str) -> Match | None:
        return self.matches.get(match_id)

    def get_players_for_match(self, match: Match) -> list[Player]:
        return sorted(
            [p for p in self.players if p.team in {match.team1, match.team2} and p.is_active],
            key=lambda p: (p.team, -p.priority, p.top_rank_in_team, p.display_name),
        )

    def get_latest_for_participant(self, participant_id: str) -> list[LatestPrediction]:
        return [prediction for prediction in self.latest if prediction.participant_id == participant_id]

    def get_latest_for_match(self, match_id: str) -> list[LatestPrediction]:
        return [prediction for prediction in self.latest if prediction.match_id == match_id]

    def get_all_latest_predictions(self) -> list[LatestPrediction]:
        return list(self.latest)

    def get_participants(self) -> list[Participant]:
        return list(self.participants.values())

    def get_participants_with_predictions(self) -> list[Participant]:
        participant_ids = {prediction.participant_id for prediction in self.latest}
        return [
            participant
            for participant in self.participants.values()
            if participant.participant_id in participant_ids and participant.telegram_id
        ]

    def get_results(self) -> list[MatchResult]:
        return list(self.results)

    def replace_scoring_rows(self, rows: list[dict[str, str]]) -> None:
        self.scoring_rows = rows

    def replace_leaderboard_rows(self, rows: list[dict[str, str]]) -> None:
        self.leaderboard_rows = rows

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
        submission_id = f"s{len(self.raw_rows) + 1}"
        self.raw_rows.append(
            {
                "submission_id": submission_id,
                "participant_id": participant_id,
                "match_id": match_id,
                "telegram_id": telegram_id,
            }
        )
        self.latest = [
            prediction
            for prediction in self.latest
            if not (prediction.participant_id == participant_id and prediction.match_id == match_id)
        ]
        self.latest.append(
            LatestPrediction(
                participant_id=participant_id,
                match_id=match_id,
                scores=tuple(scores),
                author_team1=author_team1,
                author_team2=author_team2,
                display_name=self.participants.get(participant_id, Participant(participant_id, participant_id)).display_name,
                match_name=self._match_name(match_id),
                submitted_at_msk=timestamp_msk,
            )
        )
        return submission_id

    def mark_match_locked(self, match_id: str) -> None:
        self.locked_matches.append(match_id)
        self.latest = [
            LatestPrediction(
                participant_id=p.participant_id,
                match_id=p.match_id,
                scores=p.scores,
                author_team1=p.author_team1,
                author_team2=p.author_team2,
                display_name=p.display_name,
                match_name=p.match_name,
                submitted_at_msk=p.submitted_at_msk,
                is_locked=True if p.match_id == match_id else p.is_locked,
            )
            for p in self.latest
        ]

    def get_leaderboard_rows(self) -> list[dict[str, str]]:
        if self.leaderboard_rows:
            return self.leaderboard_rows
        return [{"rank": "1", "participant_id": "p1", "display_name": "Тестовый участник", "total_points": "12"}]

    def notification_was_sent(self, notification_key: str) -> bool:
        return any(row.get("notification_key") == notification_key for row in self.notifications)

    def record_notification(
        self,
        *,
        notification_key: str,
        notification_type: str,
        sent_at_msk: str,
        recipient_count: int,
        details: str,
    ) -> None:
        self.notifications.append(
            {
                "notification_key": notification_key,
                "notification_type": notification_type,
                "sent_at_msk": sent_at_msk,
                "recipient_count": str(recipient_count),
                "details": details,
            }
        )

    def _match_name(self, match_id: str) -> str:
        match = self.matches.get(match_id)
        if not match:
            return ""
        return f"{match.team1} - {match.team2}"
