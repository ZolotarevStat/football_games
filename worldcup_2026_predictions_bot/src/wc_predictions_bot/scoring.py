from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from html import escape

from .models import LatestPrediction, Match, MatchResult, Participant

SCORE_POINTS_BY_RANK = (12, 10, 8, 7, 6, 5, 4)
GOAL_POINTS = 4
ASSIST_POINTS = 2
COUNTED_RESULT_STATUSES = {"", "final", "played", "finished"}
STAGE_SCORE_POINTS_BY_RANK = {
    "group": (12, 10, 8, 7, 6, 5, 4),
    "round32": (15, 12, 10, 8, 7, 6, 5),
    "round16": (19, 15, 12, 10, 8, 7, 6),
    "quarterfinal": (21, 17, 14, 12, 10, 9, 8),
    "third_place": (21, 17, 14, 12, 10, 9, 8),
    "semifinal": (23, 19, 16, 14, 12, 11, 10),
    "final": (25, 21, 18, 16, 14, 13, 12),
}
STAGE_GOAL_POINTS = {
    "group": 4,
    "round32": 4,
    "round16": 6,
    "quarterfinal": 8,
    "third_place": 8,
    "semifinal": 10,
    "final": 12,
}
STAGE_ASSIST_POINTS = {
    "group": 2,
    "round32": 2,
    "round16": 3,
    "quarterfinal": 4,
    "third_place": 4,
    "semifinal": 5,
    "final": 6,
}
TIEBREAKER_FIELDS = (
    "final_points",
    "third_place_points",
    "semifinal_points",
    "quarterfinal_points",
    "round16_points",
    "round32_points",
    "group_points",
)


@dataclass(frozen=True)
class ScoringResult:
    scoring_rows: list[dict[str, str]]
    leaderboard_rows: list[dict[str, str]]
    analytics_rows: dict[str, list[dict[str, str]]]
    match_ids: tuple[str, ...]


@dataclass(frozen=True)
class AuthorScore:
    total_points: int
    goal_points: int
    assist_points: int
    note: str


def calculate_scoring(
    *,
    predictions: list[LatestPrediction],
    results: list[MatchResult],
    participants: list[Participant],
    now_iso: str,
    match_id: str = "",
    matches: list[Match] | None = None,
) -> ScoringResult:
    result_by_match = {
        result.match_id: result
        for result in results
        if is_counted_result(result) and (not match_id or result.match_id == match_id)
    }
    participant_by_id = {participant.participant_id: participant for participant in participants}
    match_by_id = {match.match_id: match for match in matches or []}
    scoring_rows: list[dict[str, str]] = []
    leaderboard: dict[str, dict[str, int]] = defaultdict(lambda: {
        "matches_scored": 0,
        "score_points": 0,
        "goal_points": 0,
        "assist_points": 0,
        "author_points": 0,
        "total_points": 0,
        **{field: 0 for field in TIEBREAKER_FIELDS},
    })

    for prediction in predictions:
        result = result_by_match.get(prediction.match_id)
        if not result:
            continue
        match = match_by_id.get(prediction.match_id)
        stage = stage_key(match)
        score_points, score_note = score_prediction(prediction, result, stage)
        author_score = author_prediction_breakdown(prediction, result, stage)
        author_points = author_score.total_points
        total_points = score_points + author_points
        participant = participant_by_id.get(prediction.participant_id)
        match_name = f"{match.team1} - {match.team2}" if match else prediction.match_name
        scoring_rows.append(
            {
                "participant_id": prediction.participant_id,
                "display_name": participant.display_name if participant else prediction.display_name or prediction.participant_id,
                "match_id": prediction.match_id,
                "match_name": match_name or prediction.match_id,
                "stage": stage,
                "score_points": str(score_points),
                "goal_points": str(author_score.goal_points),
                "assist_points": str(author_score.assist_points),
                "author_points": str(author_points),
                "penalties": "0",
                "total_points": str(total_points),
                "explanation": "; ".join(part for part in [score_note, author_score.note] if part),
            }
        )
        totals = leaderboard[prediction.participant_id]
        totals["matches_scored"] += 1
        totals["score_points"] += score_points
        totals["goal_points"] += author_score.goal_points
        totals["assist_points"] += author_score.assist_points
        totals["author_points"] += author_points
        totals["total_points"] += total_points
        totals[f"{stage}_points"] += total_points

    leaderboard_rows = build_leaderboard_rows(leaderboard, participant_by_id, now_iso)
    analytics_rows = build_analytics_rows(
        predictions=predictions,
        result_by_match=result_by_match,
        match_by_id=match_by_id,
        participant_by_id=participant_by_id,
        leaderboard_rows=leaderboard_rows,
        now_iso=now_iso,
    )
    return ScoringResult(
        scoring_rows=scoring_rows,
        leaderboard_rows=leaderboard_rows,
        analytics_rows=analytics_rows,
        match_ids=tuple(sorted(result_by_match)),
    )


def score_prediction(prediction: LatestPrediction, result: MatchResult, stage: str = "group") -> tuple[int, str]:
    actual_score = normalize_score(result.actual_score)
    score_points_by_rank = STAGE_SCORE_POINTS_BY_RANK.get(stage, SCORE_POINTS_BY_RANK)
    for index, score in enumerate(prediction.scores):
        if normalize_score(score) == actual_score:
            points = score_points_by_rank[index]
            return points, f"точный счет #{index + 1}: +{points}"
    return 0, "точного счета нет"


def is_counted_result(result: MatchResult) -> bool:
    return bool(result.actual_score and result.status.strip().lower() in COUNTED_RESULT_STATUSES)


def author_prediction(prediction: LatestPrediction, result: MatchResult, stage: str = "group") -> tuple[int, str]:
    author_score = author_prediction_breakdown(prediction, result, stage)
    return author_score.total_points, author_score.note


def author_prediction_breakdown(prediction: LatestPrediction, result: MatchResult, stage: str = "group") -> AuthorScore:
    goals = Counter(result.goals)
    assists = Counter(result.assists)
    own_goals = Counter(result.own_goals)
    goal_point_value = STAGE_GOAL_POINTS.get(stage, GOAL_POINTS)
    assist_point_value = STAGE_ASSIST_POINTS.get(stage, ASSIST_POINTS)
    total_goal_points = 0
    total_assist_points = 0
    notes: list[str] = []

    for author in [prediction.author_team1, prediction.author_team2]:
        author_goals = max(0, goals[author] - own_goals[author])
        author_assists = assists[author]
        author_goal_points = author_goals * goal_point_value
        author_assist_points = author_assists * assist_point_value
        author_points = author_goal_points + author_assist_points
        total_goal_points += author_goal_points
        total_assist_points += author_assist_points
        if author_points:
            parts = []
            if author_goals:
                parts.append(f"{author_goals} гол")
            if author_assists:
                parts.append(f"{author_assists} ассист")
            notes.append(f"{author}: {', '.join(parts)} (+{author_points})")

    if not notes:
        return AuthorScore(0, 0, 0, "авторы без Г+П")
    return AuthorScore(total_goal_points + total_assist_points, total_goal_points, total_assist_points, "; ".join(notes))


def build_leaderboard_rows(
    totals_by_participant: dict[str, dict[str, int]],
    participant_by_id: dict[str, Participant],
    now_iso: str,
) -> list[dict[str, str]]:
    sorted_items = sorted(
        totals_by_participant.items(),
        key=lambda item: (
            -item[1]["total_points"],
            *[-item[1][field] for field in TIEBREAKER_FIELDS],
            -item[1]["score_points"],
            item[0],
        ),
    )
    rows: list[dict[str, str]] = []
    previous_points: int | None = None
    rank = 0
    for index, (participant_id, totals) in enumerate(sorted_items, start=1):
        if totals["total_points"] != previous_points:
            rank = index
            previous_points = totals["total_points"]
        participant = participant_by_id.get(participant_id)
        display_name = participant.display_name if participant else participant_id
        playoff_points = sum(
            totals[field]
            for field in (
                "final_points",
                "third_place_points",
                "semifinal_points",
                "quarterfinal_points",
                "round16_points",
                "round32_points",
            )
        )
        rows.append(
            {
                "rank": str(rank),
                "participant_id": participant_id,
                "display_name": display_name,
                "matches_scored": str(totals["matches_scored"]),
                "score_points": str(totals["score_points"]),
                "goal_points": str(totals["goal_points"]),
                "assist_points": str(totals["assist_points"]),
                "author_points": str(totals["author_points"]),
                "tour_points": str(totals["total_points"]),
                "total_points": str(totals["total_points"]),
                **{field: str(totals[field]) for field in TIEBREAKER_FIELDS},
                "updated_at": now_iso,
                "№": str(rank),
                "Имя": display_name,
                "№ матчей": str(totals["matches_scored"]),
                "Счёт": str(totals["score_points"]),
                "Голы": str(totals["goal_points"]),
                "Ассисты": str(totals["assist_points"]),
                "Итого": str(totals["total_points"]),
                "Группа": str(totals["group_points"]),
                "Плей-офф": str(playoff_points),
            }
        )
    return rows


def format_leaderboard(rows: list[dict[str, str]], *, title: str = "🏆 Таблица", html: bool = False) -> str:
    if not rows:
        return "Таблица пока пустая."
    table_lines = _leaderboard_table_lines(rows[:40])
    if len(rows) > 40:
        table_lines.append(f"...и еще {len(rows) - 40}")
    if html:
        escaped_table = "\n".join(escape(line) for line in table_lines)
        return f"{escape(title)}\n<pre>{escaped_table}</pre>"
    return "\n".join([title, *table_lines])


def _leaderboard_table_lines(rows: list[dict[str, str]]) -> list[str]:
    name_width = min(
        24,
        max(
            10,
            len("Участник"),
            *(len(row.get("display_name") or row.get("Имя") or row.get("participant_id") or "") for row in rows),
        ),
    )
    lines = [
        (
            f"{'#':<2} | {'Участник':<{name_width}} | "
            f"{'Итог':>4} | {'Счет':>4} | {'Голы':>4} | {'Пасы':>4}"
        )
    ]
    for row in rows[:40]:
        rank = row.get("rank", "") or row.get("№", "")
        medal = {"1": "🥇", "2": "🥈", "3": "🥉"}.get(rank, f"{rank}.")
        score_points = row.get("score_points", "") or row.get("Счёт", "0")
        goal_points = row.get("goal_points", "") or row.get("Голы", "")
        assist_points = row.get("assist_points", "") or row.get("Ассисты", "")
        if not goal_points and not assist_points:
            goal_points = row.get("author_points", "0")
            assist_points = "0"
        total_points = row.get("total_points", "") or row.get("Итого", "0")
        display_name = row.get("display_name") or row.get("Имя") or row.get("participant_id") or ""
        if len(display_name) > name_width:
            display_name = f"{display_name[: name_width - 1]}…"
        lines.append(
            f"{medal:<2} | {display_name:<{name_width}} | "
            f"{total_points:>4} | {score_points:>4} | {goal_points:>4} | {assist_points:>4}"
        )
    return lines


def build_analytics_rows(
    *,
    predictions: list[LatestPrediction],
    result_by_match: dict[str, MatchResult],
    match_by_id: dict[str, Match],
    participant_by_id: dict[str, Participant],
    leaderboard_rows: list[dict[str, str]],
    now_iso: str,
) -> dict[str, list[dict[str, str]]]:
    counted_predictions = [
        prediction
        for prediction in predictions
        if prediction.match_id in result_by_match
    ]
    return {
        "leaderboard_by_total": build_metric_leaderboard_rows(leaderboard_rows, "total_points", now_iso),
        "leaderboard_by_score": build_metric_leaderboard_rows(leaderboard_rows, "score_points", now_iso),
        "leaderboard_by_goals": build_metric_leaderboard_rows(leaderboard_rows, "goal_points", now_iso),
        "leaderboard_by_assists": build_metric_leaderboard_rows(leaderboard_rows, "assist_points", now_iso),
        "match_author_picks": build_match_author_pick_rows(counted_predictions, match_by_id, participant_by_id, now_iso),
        "match_first_score_belief": build_first_score_belief_rows(counted_predictions, match_by_id, participant_by_id, now_iso),
    }


def build_metric_leaderboard_rows(
    leaderboard_rows: list[dict[str, str]],
    metric: str,
    now_iso: str,
) -> list[dict[str, str]]:
    rows = sorted(
        leaderboard_rows,
        key=lambda row: (-int(row.get(metric, "0") or 0), -int(row.get("total_points", "0") or 0), row.get("display_name", "")),
    )
    output: list[dict[str, str]] = []
    previous_value: int | None = None
    rank = 0
    for index, row in enumerate(rows, start=1):
        metric_value = int(row.get(metric, "0") or 0)
        if metric_value != previous_value:
            rank = index
            previous_value = metric_value
        output.append(
            {
                "rank": str(rank),
                "participant_id": row.get("participant_id", ""),
                "display_name": row.get("display_name", ""),
                "metric": metric,
                "metric_points": str(metric_value),
                "total_points": row.get("total_points", "0"),
                "score_points": row.get("score_points", "0"),
                "goal_points": row.get("goal_points", "0"),
                "assist_points": row.get("assist_points", "0"),
                "updated_at": now_iso,
            }
        )
    return output


def build_match_author_pick_rows(
    predictions: list[LatestPrediction],
    match_by_id: dict[str, Match],
    participant_by_id: dict[str, Participant],
    now_iso: str,
) -> list[dict[str, str]]:
    picks: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for prediction in predictions:
        match = match_by_id.get(prediction.match_id)
        team1 = match.team1 if match else "team1"
        team2 = match.team2 if match else "team2"
        participant_name = participant_display_name(prediction, participant_by_id)
        if prediction.author_team1:
            picks[(prediction.match_id, team1, prediction.author_team1)].add(participant_name)
        if prediction.author_team2:
            picks[(prediction.match_id, team2, prediction.author_team2)].add(participant_name)

    rows: list[dict[str, str]] = []
    for (match_id, team, player_name), participants in sorted(
        picks.items(),
        key=lambda item: (item[0][0], -len(item[1]), item[0][1], item[0][2]),
    ):
        match = match_by_id.get(match_id)
        rows.append(
            {
                "match_id": match_id,
                "match_name": match_name(match, match_id),
                "team": team,
                "player_name": player_name,
                "pick_count": str(len(participants)),
                "participants": ", ".join(sorted(participants)),
                "updated_at": now_iso,
            }
        )
    return rows


def build_first_score_belief_rows(
    predictions: list[LatestPrediction],
    match_by_id: dict[str, Match],
    participant_by_id: dict[str, Participant],
    now_iso: str,
) -> list[dict[str, str]]:
    picks: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for prediction in predictions:
        if not prediction.scores:
            continue
        first_score = normalize_score(prediction.scores[0])
        match = match_by_id.get(prediction.match_id)
        picks[(prediction.match_id, outcome_label(first_score, match), first_score)].add(
            participant_display_name(prediction, participant_by_id)
        )

    rows: list[dict[str, str]] = []
    for (match_id, outcome, first_score), participants in sorted(
        picks.items(),
        key=lambda item: (item[0][0], -len(item[1]), item[0][1], item[0][2]),
    ):
        match = match_by_id.get(match_id)
        rows.append(
            {
                "match_id": match_id,
                "match_name": match_name(match, match_id),
                "outcome": outcome,
                "first_score": first_score,
                "pick_count": str(len(participants)),
                "participants": ", ".join(sorted(participants)),
                "updated_at": now_iso,
            }
        )
    return rows


def participant_display_name(
    prediction: LatestPrediction,
    participant_by_id: dict[str, Participant],
) -> str:
    participant = participant_by_id.get(prediction.participant_id)
    return participant.display_name if participant else prediction.display_name or prediction.participant_id


def match_name(match: Match | None, fallback_match_id: str) -> str:
    if not match:
        return fallback_match_id
    return f"{match.team1} - {match.team2}"


def outcome_label(score: str, match: Match | None) -> str:
    try:
        left, right = [int(part) for part in score.split("-", 1)]
    except ValueError:
        return "unknown"
    if left == right:
        return "draw"
    if not match:
        return "team1_win" if left > right else "team2_win"
    return f"{match.team1} win" if left > right else f"{match.team2} win"


def normalize_score(score: str) -> str:
    return score.strip().replace(":", "-")


def stage_key(match: Match | None) -> str:
    if not match:
        return "group"
    value = f"{match.tour} {match.group}".strip().lower()
    value = value.replace("финал", "final")
    if "3" in value and ("мест" in value or "place" in value):
        return "third_place"
    if "final" in value and "semi" not in value and "полу" not in value and "1/2" not in value:
        return "final"
    if "1/2" in value or "semi" in value or "полу" in value:
        return "semifinal"
    if "1/4" in value or "quarter" in value or "четвер" in value:
        return "quarterfinal"
    if "1/8" in value or "round16" in value or "1-8" in value:
        return "round16"
    if "1/16" in value or "round32" in value or "1-16" in value:
        return "round32"
    return "group"


def now_iso_seconds() -> str:
    return datetime.now().isoformat(timespec="seconds")
