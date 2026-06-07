from __future__ import annotations

from .models import LatestPrediction, Match

TEAM_FLAGS = {
    "Австралия": "🇦🇺",
    "Австрия": "🇦🇹",
    "Алжир": "🇩🇿",
    "Англия": "🇬🇧",
    "Аргентина": "🇦🇷",
    "Бельгия": "🇧🇪",
    "Босния и Герцеговина": "🇧🇦",
    "Бразилия": "🇧🇷",
    "Гаити": "🇭🇹",
    "Гана": "🇬🇭",
    "Германия": "🇩🇪",
    "ДР Конго": "🇨🇩",
    "Египет": "🇪🇬",
    "Иордания": "🇯🇴",
    "Ирак": "🇮🇶",
    "Иран": "🇮🇷",
    "Испания": "🇪🇸",
    "Кабо-Верде": "🇨🇻",
    "Канада": "🇨🇦",
    "Катар": "🇶🇦",
    "Колумбия": "🇨🇴",
    "Кот-д'Ивуар": "🇨🇮",
    "Кюрасао": "🇨🇼",
    "Марокко": "🇲🇦",
    "Мексика": "🇲🇽",
    "Нидерланды": "🇳🇱",
    "Новая Зеландия": "🇳🇿",
    "Норвегия": "🇳🇴",
    "Панама": "🇵🇦",
    "Парагвай": "🇵🇾",
    "Португалия": "🇵🇹",
    "США": "🇺🇸",
    "Саудовская Аравия": "🇸🇦",
    "Сенегал": "🇸🇳",
    "Тунис": "🇹🇳",
    "Турция": "🇹🇷",
    "Узбекистан": "🇺🇿",
    "Уругвай": "🇺🇾",
    "Франция": "🇫🇷",
    "Хорватия": "🇭🇷",
    "Чехия": "🇨🇿",
    "Швейцария": "🇨🇭",
    "Швеция": "🇸🇪",
    "Шотландия": "🏴",
    "Эквадор": "🇪🇨",
    "ЮАР": "🇿🇦",
    "Южная Корея": "🇰🇷",
    "Япония": "🇯🇵",
}

RANK_MARKERS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣")


def flag(team: str) -> str:
    return TEAM_FLAGS.get(team, "🏳️")


def match_title(match: Match) -> str:
    return f"{flag(match.team1)} {match.team1} - {match.team2} {flag(match.team2)}"


def compact_scores(scores: tuple[str, ...] | list[str]) -> str:
    return "  ".join(f"{RANK_MARKERS[index]} {score}" for index, score in enumerate(scores[:7]))


def format_prediction_for_my(prediction: LatestPrediction, match: Match | None) -> str:
    if match:
        header = match_title(match)
        deadline = f"до {match.deadline_msk:%d.%m %H:%M} МСК"
    else:
        header = prediction.match_id
        deadline = ""
    lines = [
        f"⚽ {header}",
        f"📊 {compact_scores(prediction.scores)}",
        f"🧩 Авторы: {prediction.author_team1}, {prediction.author_team2}",
    ]
    if deadline:
        lines.append(f"⏰ {deadline}")
    return "\n".join(lines)
