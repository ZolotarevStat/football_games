from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .import_compact_xlsx import match_id
from .models import Match, MatchResult
from .scoring import is_counted_result, normalize_score

TZ = ZoneInfo("Europe/Moscow")
DEADLINE_BEFORE_KICKOFF = timedelta(minutes=5)


@dataclass(frozen=True)
class Round32Fixture:
    number: int
    kickoff_msk: datetime
    team1: str
    team2: str


@dataclass(frozen=True)
class BracketFixture:
    number: int
    tour: str
    kickoff_msk: datetime
    source1: str
    source2: str


@dataclass(frozen=True)
class PlayoffCalendarUpdate:
    matches: list[Match]
    open_match_count: int
    planned_match_count: int
    resolved_future_match_count: int
    warnings: tuple[str, ...] = ()


def _msk(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(TZ)


def _msk_from_utc_offset(date_value: str, hour: int, utc_offset_hours: int) -> datetime:
    local_tz = timezone(timedelta(hours=utc_offset_hours))
    return datetime.fromisoformat(f"{date_value}T{hour:02d}:00:00").replace(tzinfo=local_tz).astimezone(TZ)


ROUND32_FIXTURES: tuple[Round32Fixture, ...] = (
    Round32Fixture(73, _msk("2026-06-28T22:00:00+03:00"), "ЮАР", "Канада"),
    Round32Fixture(74, _msk("2026-06-29T23:30:00+03:00"), "Германия", "Парагвай"),
    Round32Fixture(75, _msk("2026-06-30T04:00:00+03:00"), "Нидерланды", "Марокко"),
    Round32Fixture(76, _msk("2026-06-29T20:00:00+03:00"), "Бразилия", "Япония"),
    Round32Fixture(77, _msk("2026-07-01T00:00:00+03:00"), "Франция", "Швеция"),
    Round32Fixture(78, _msk("2026-06-30T20:00:00+03:00"), "Кот-д'Ивуар", "Норвегия"),
    Round32Fixture(79, _msk("2026-07-01T04:00:00+03:00"), "Мексика", "Эквадор"),
    Round32Fixture(80, _msk("2026-07-01T19:00:00+03:00"), "Англия", "ДР Конго"),
    Round32Fixture(81, _msk("2026-07-02T03:00:00+03:00"), "США", "Босния и Герцеговина"),
    Round32Fixture(82, _msk("2026-07-01T23:00:00+03:00"), "Бельгия", "Сенегал"),
    Round32Fixture(83, _msk("2026-07-03T02:00:00+03:00"), "Португалия", "Хорватия"),
    Round32Fixture(84, _msk("2026-07-02T22:00:00+03:00"), "Испания", "Австрия"),
    Round32Fixture(85, _msk("2026-07-03T06:00:00+03:00"), "Швейцария", "Алжир"),
    Round32Fixture(86, _msk("2026-07-04T01:00:00+03:00"), "Аргентина", "Кабо-Верде"),
    Round32Fixture(87, _msk("2026-07-04T04:30:00+03:00"), "Колумбия", "Гана"),
    Round32Fixture(88, _msk("2026-07-03T21:00:00+03:00"), "Австралия", "Египет"),
)


BRACKET_FIXTURES: tuple[BracketFixture, ...] = (
    BracketFixture(89, "1/8", _msk_from_utc_offset("2026-07-04", 17, -4), "W74", "W77"),
    BracketFixture(90, "1/8", _msk_from_utc_offset("2026-07-04", 12, -5), "W73", "W75"),
    BracketFixture(91, "1/8", _msk_from_utc_offset("2026-07-05", 16, -4), "W76", "W78"),
    BracketFixture(92, "1/8", _msk_from_utc_offset("2026-07-05", 18, -6), "W79", "W80"),
    BracketFixture(93, "1/8", _msk_from_utc_offset("2026-07-06", 14, -5), "W83", "W84"),
    BracketFixture(94, "1/8", _msk_from_utc_offset("2026-07-06", 17, -7), "W81", "W82"),
    BracketFixture(95, "1/8", _msk_from_utc_offset("2026-07-07", 12, -4), "W86", "W88"),
    BracketFixture(96, "1/8", _msk_from_utc_offset("2026-07-07", 13, -7), "W85", "W87"),
    BracketFixture(97, "1/4", _msk_from_utc_offset("2026-07-09", 16, -4), "W89", "W90"),
    BracketFixture(98, "1/4", _msk_from_utc_offset("2026-07-10", 12, -7), "W93", "W94"),
    BracketFixture(99, "1/4", _msk_from_utc_offset("2026-07-11", 17, -4), "W91", "W92"),
    BracketFixture(100, "1/4", _msk_from_utc_offset("2026-07-11", 20, -5), "W95", "W96"),
    BracketFixture(101, "1/2", _msk_from_utc_offset("2026-07-14", 14, -5), "W97", "W98"),
    BracketFixture(102, "1/2", _msk_from_utc_offset("2026-07-15", 15, -4), "W99", "W100"),
    BracketFixture(103, "Матч за 3 место", _msk_from_utc_offset("2026-07-18", 17, -4), "L101", "L102"),
    BracketFixture(104, "Финал", _msk_from_utc_offset("2026-07-19", 15, -4), "W101", "W102"),
)


def build_playoff_calendar(results: list[MatchResult]) -> PlayoffCalendarUpdate:
    result_by_match = {result.match_id: result for result in results if result.match_id}
    winner_by_number: dict[int, str] = {}
    loser_by_number: dict[int, str] = {}
    match_by_number: dict[int, Match] = {}
    warnings: list[str] = []
    matches: list[Match] = []

    for fixture in ROUND32_FIXTURES:
        item = Match(
            match_id=match_id(fixture.team1, fixture.team2),
            group="Плей-офф",
            tour="1/16",
            kickoff_msk=fixture.kickoff_msk,
            deadline_msk=fixture.kickoff_msk - DEADLINE_BEFORE_KICKOFF,
            team1=fixture.team1,
            team2=fixture.team2,
            status="open",
        )
        matches.append(item)
        match_by_number[fixture.number] = item
        _store_winner_and_loser(fixture.number, item, result_by_match.get(item.match_id), winner_by_number, loser_by_number, warnings)

    for fixture in BRACKET_FIXTURES:
        team1 = _resolve_source(fixture.source1, winner_by_number, loser_by_number)
        team2 = _resolve_source(fixture.source2, winner_by_number, loser_by_number)
        status = "open" if _is_resolved_team(team1) and _is_resolved_team(team2) else "planned"
        item = Match(
            match_id=f"M{fixture.number}",
            group="Плей-офф",
            tour=fixture.tour,
            kickoff_msk=fixture.kickoff_msk,
            deadline_msk=fixture.kickoff_msk - DEADLINE_BEFORE_KICKOFF,
            team1=team1,
            team2=team2,
            status=status,
        )
        matches.append(item)
        match_by_number[fixture.number] = item
        if status == "open":
            _store_winner_and_loser(
                fixture.number,
                item,
                result_by_match.get(item.match_id),
                winner_by_number,
                loser_by_number,
                warnings,
            )

    return PlayoffCalendarUpdate(
        matches=sorted(matches, key=lambda item: item.kickoff_msk),
        open_match_count=sum(1 for item in matches if item.status == "open"),
        planned_match_count=sum(1 for item in matches if item.status == "planned"),
        resolved_future_match_count=sum(1 for item in matches if _is_future_match_id(item.match_id) and item.status == "open"),
        warnings=tuple(warnings),
    )


def _store_winner_and_loser(
    number: int,
    match: Match,
    result: MatchResult | None,
    winner_by_number: dict[int, str],
    loser_by_number: dict[int, str],
    warnings: list[str],
) -> None:
    winner, loser, warning = _winner_and_loser(match, result)
    if warning:
        warnings.append(f"M{number}: {warning}")
    if winner and loser:
        winner_by_number[number] = winner
        loser_by_number[number] = loser


def _winner_and_loser(match: Match, result: MatchResult | None) -> tuple[str | None, str | None, str | None]:
    if not result or not is_counted_result(result):
        return None, None, None
    status_tokens = _status_tokens(result.status)
    if status_tokens & {"winner_team1", "team1_wins", "w1"}:
        return match.team1, match.team2, None
    if status_tokens & {"winner_team2", "team2_wins", "w2"}:
        return match.team2, match.team1, None
    normalized = normalize_score(result.actual_score)
    left_raw, _, right_raw = normalized.partition("-")
    try:
        left = int(left_raw)
        right = int(right_raw)
    except ValueError:
        return None, None, f"не смог определить победителя по счету {result.actual_score!r}"
    if left > right:
        return match.team1, match.team2, None
    if right > left:
        return match.team2, match.team1, None
    return None, None, f"ничья {normalized}; добавьте победителя вручную перед актуализацией следующего раунда"


def _resolve_source(source: str, winner_by_number: dict[int, str], loser_by_number: dict[int, str]) -> str:
    source_type = source[:1]
    number = int(source[1:])
    if source_type == "W":
        return winner_by_number.get(number, f"Победитель M{number}")
    if source_type == "L":
        return loser_by_number.get(number, f"Проигравший M{number}")
    raise ValueError(f"Unsupported bracket source: {source}")


def _is_resolved_team(value: str) -> bool:
    return not value.startswith(("Победитель ", "Проигравший "))


def _is_future_match_id(value: str) -> bool:
    return value.startswith("M") and value[1:].isdigit()


def _status_tokens(value: str) -> set[str]:
    return {part.strip().lower() for part in value.replace(";", ",").replace("|", ",").split(",") if part.strip()}
