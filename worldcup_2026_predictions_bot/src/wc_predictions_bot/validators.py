from __future__ import annotations

from difflib import SequenceMatcher
import re
from datetime import datetime

from .models import LatestPrediction, Match, Player

SCORE_PATTERN = re.compile(r"^(0|[1-9]\d*)-(0|[1-9]\d*)$")


class ValidationError(ValueError):
    pass


def parse_scores(text: str) -> list[str]:
    scores = [part.strip().replace(":", "-") for part in text.split(",") if part.strip()]
    validate_scores(scores)
    return scores


def validate_scores(scores: list[str]) -> None:
    if len(scores) != 7:
        raise ValidationError("Нужно ровно 7 вариантов счета через запятую.")
    normalized = [score.strip().replace(":", "-") for score in scores]
    invalid = [score for score in normalized if not SCORE_PATTERN.match(score)]
    if invalid:
        raise ValidationError(f"Некорректный формат счета: {', '.join(invalid)}. Пример: 1-0")
    if len(set(normalized)) != 7:
        raise ValidationError("Счета внутри прогноза не должны повторяться.")


def ensure_open_deadline(match: Match, now_msk: datetime) -> None:
    if match.status.lower() not in {"open", "scheduled", ""}:
        raise ValidationError("Матч закрыт для прогнозов.")
    if now_msk >= match.deadline_msk:
        raise ValidationError("Дедлайн матча уже прошел, прогноз сохранить нельзя.")


def candidate_names(players: list[Player], team: str) -> set[str]:
    return {player.display_name for player in players if player.team == team and player.is_active}


def normalize_player_name(value: str) -> str:
    value = value.lower().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def author_suggestions(author: str, players: list[Player], team: str, limit: int = 3) -> list[str]:
    query = normalize_player_name(author)
    if not query:
        return []

    scored: list[tuple[float, str]] = []
    for player in players:
        if player.team != team or not player.is_active:
            continue
        names = [player.display_name, player.player_name_en]
        normalized_names = [normalize_player_name(name) for name in names if name]
        if not normalized_names:
            continue
        score = max(_name_match_score(query, normalized_name) for normalized_name in normalized_names)
        if score >= 0.55:
            scored.append((score, player.display_name))

    scored.sort(key=lambda item: (-item[0], item[1]))
    suggestions: list[str] = []
    for _, display_name in scored:
        if display_name not in suggestions:
            suggestions.append(display_name)
        if len(suggestions) >= limit:
            break
    return suggestions


def _name_match_score(query: str, candidate: str) -> float:
    if query == candidate:
        return 1.0
    if query in candidate or candidate in query:
        return 0.95
    query_tokens = set(query.split())
    candidate_tokens = set(candidate.split())
    if query_tokens and query_tokens <= candidate_tokens:
        return 0.9
    if query_tokens and candidate_tokens:
        overlap = len(query_tokens & candidate_tokens) / len(query_tokens)
        if overlap >= 0.8:
            return 0.85
    return SequenceMatcher(None, query, candidate).ratio()


def ensure_author_in_pool(author: str, players: list[Player], team: str, label: str) -> None:
    if author not in candidate_names(players, team):
        raise ValidationError(f"{label} должен быть из активной заявки команды {team}.")


def ensure_authors_are_distinct(author_team1: str, author_team2: str) -> None:
    if normalize_player_name(author_team1) == normalize_player_name(author_team2):
        raise ValidationError("Авторы Г+П не должны повторяться внутри прогноза.")


def ensure_author_not_used(
    author: str,
    latest_predictions: list[LatestPrediction],
    current_match_id: str,
) -> None:
    used_matches = [
        prediction.match_id
        for prediction in latest_predictions
        if prediction.match_id != current_match_id
        and (prediction.author_team1 == author or prediction.author_team2 == author)
    ]
    if used_matches:
        raise ValidationError(f"{author} уже выбран в другом актуальном прогнозе.")
