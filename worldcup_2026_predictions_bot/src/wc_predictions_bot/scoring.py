from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

from .models import LatestPrediction, MatchResult, Participant

SCORE_POINTS_BY_RANK = (12, 10, 8, 7, 6, 5, 4)
GOAL_POINTS = 4
ASSIST_POINTS = 2


@dataclass(frozen=True)
class ScoringResult:
    scoring_rows: list[dict[str, str]]
    leaderboard_rows: list[dict[str, str]]
    match_ids: tuple[str, ...]


def calculate_scoring(
    *,
    predictions: list[LatestPrediction],
    results: list[MatchResult],
    participants: list[Participant],
    now_iso: str,
    match_id: str = "",
) -> ScoringResult:
    result_by_match = {
        result.match_id: result
        for result in results
        if result.actual_score and (not match_id or result.match_id == match_id)
    }
    participant_by_id = {participant.participant_id: participant for participant in participants}
    scoring_rows: list[dict[str, str]] = []
    leaderboard: dict[str, dict[str, int]] = defaultdict(lambda: {
        "matches_scored": 0,
        "score_points": 0,
        "author_points": 0,
        "total_points": 0,
    })

    for prediction in predictions:
        result = result_by_match.get(prediction.match_id)
        if not result:
            continue
        score_points, score_note = score_prediction(prediction, result)
        author_points, author_note = author_prediction(prediction, result)
        total_points = score_points + author_points
        scoring_rows.append(
            {
                "participant_id": prediction.participant_id,
                "match_id": prediction.match_id,
                "score_points": str(score_points),
                "author_points": str(author_points),
                "penalties": "0",
                "total_points": str(total_points),
                "explanation": "; ".join(part for part in [score_note, author_note] if part),
            }
        )
        totals = leaderboard[prediction.participant_id]
        totals["matches_scored"] += 1
        totals["score_points"] += score_points
        totals["author_points"] += author_points
        totals["total_points"] += total_points

    leaderboard_rows = build_leaderboard_rows(leaderboard, participant_by_id, now_iso)
    return ScoringResult(
        scoring_rows=scoring_rows,
        leaderboard_rows=leaderboard_rows,
        match_ids=tuple(sorted(result_by_match)),
    )


def score_prediction(prediction: LatestPrediction, result: MatchResult) -> tuple[int, str]:
    actual_score = normalize_score(result.actual_score)
    for index, score in enumerate(prediction.scores):
        if normalize_score(score) == actual_score:
            points = SCORE_POINTS_BY_RANK[index]
            return points, f"точный счет #{index + 1}: +{points}"
    return 0, "точного счета нет"


def author_prediction(prediction: LatestPrediction, result: MatchResult) -> tuple[int, str]:
    goals = Counter(result.goals)
    assists = Counter(result.assists)
    own_goals = Counter(result.own_goals)
    points = 0
    notes: list[str] = []

    for author in [prediction.author_team1, prediction.author_team2]:
        author_goals = max(0, goals[author] - own_goals[author])
        author_assists = assists[author]
        author_points = author_goals * GOAL_POINTS + author_assists * ASSIST_POINTS
        points += author_points
        if author_points:
            parts = []
            if author_goals:
                parts.append(f"{author_goals} гол")
            if author_assists:
                parts.append(f"{author_assists} ассист")
            notes.append(f"{author}: {', '.join(parts)} (+{author_points})")

    if not notes:
        return 0, "авторы без Г+П"
    return points, "; ".join(notes)


def build_leaderboard_rows(
    totals_by_participant: dict[str, dict[str, int]],
    participant_by_id: dict[str, Participant],
    now_iso: str,
) -> list[dict[str, str]]:
    sorted_items = sorted(
        totals_by_participant.items(),
        key=lambda item: (-item[1]["total_points"], -item[1]["score_points"], item[0]),
    )
    rows: list[dict[str, str]] = []
    previous_points: int | None = None
    rank = 0
    for index, (participant_id, totals) in enumerate(sorted_items, start=1):
        if totals["total_points"] != previous_points:
            rank = index
            previous_points = totals["total_points"]
        participant = participant_by_id.get(participant_id)
        rows.append(
            {
                "rank": str(rank),
                "participant_id": participant_id,
                "display_name": participant.display_name if participant else participant_id,
                "matches_scored": str(totals["matches_scored"]),
                "score_points": str(totals["score_points"]),
                "author_points": str(totals["author_points"]),
                "tour_points": str(totals["total_points"]),
                "total_points": str(totals["total_points"]),
                "updated_at": now_iso,
            }
        )
    return rows


def format_leaderboard(rows: list[dict[str, str]], *, title: str = "🏆 Таблица") -> str:
    if not rows:
        return "Таблица пока пустая."
    lines = [title, "Место | Участник | Очки | Счета | Игроки"]
    for row in rows[:40]:
        rank = row.get("rank", "")
        medal = {"1": "🥇", "2": "🥈", "3": "🥉"}.get(rank, f"{rank}.")
        lines.append(
            f"{medal} {row.get('display_name') or row.get('participant_id')} — "
            f"{row.get('total_points', '0')} "
            f"(счета {row.get('score_points', '0')}, игроки {row.get('author_points', '0')})"
        )
    return "\n".join(lines)


def normalize_score(score: str) -> str:
    return score.strip().replace(":", "-")


def now_iso_seconds() -> str:
    return datetime.now().isoformat(timespec="seconds")
