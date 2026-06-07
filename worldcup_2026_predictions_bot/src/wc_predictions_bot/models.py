from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Participant:
    participant_id: str
    display_name: str
    telegram_username: str = ""
    telegram_id: str = ""
    invite_code: str = ""
    status: str = "active"
    role: str = ""


@dataclass(frozen=True)
class Match:
    match_id: str
    group: str
    tour: str
    kickoff_msk: datetime
    deadline_msk: datetime
    team1: str
    team2: str
    status: str = "open"


@dataclass(frozen=True)
class Player:
    team: str
    player_name_ru: str
    player_name_en: str = ""
    position: str = ""
    priority: float = 0.0
    top_rank_in_team: int = 999
    is_active: bool = True

    @property
    def display_name(self) -> str:
        return self.player_name_ru or self.player_name_en


@dataclass(frozen=True)
class LatestPrediction:
    participant_id: str
    match_id: str
    scores: tuple[str, ...]
    author_team1: str
    author_team2: str
    submitted_at_msk: str = ""
    is_locked: bool = False


@dataclass(frozen=True)
class MatchResult:
    match_id: str
    actual_score: str
    status: str = "final"
    goals: tuple[str, ...] = ()
    assists: tuple[str, ...] = ()
    own_goals: tuple[str, ...] = ()
    updated_at: str = ""


@dataclass
class PredictionDraft:
    participant_id: str
    telegram_id: str
    match_id: str
    scores: list[str] = field(default_factory=list)
    author_team1: str = ""
    author_team2: str = ""
