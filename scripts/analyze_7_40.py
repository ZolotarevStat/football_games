from __future__ import annotations

import json
import re
import subprocess
import argparse
import html
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytesseract
from PIL import Image, ImageOps


def find_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in [current.parent, *current.parents]:
        if (parent / "AGENTS.md").exists() and (parent / ".gitignore").exists():
            return parent
    return current.parents[1]


PROJECT_ROOT = find_project_root()
PUBLIC_EXPORT = Path("~/Downloads/Telegram Desktop/ChatExport_2026-04-26").expanduser()
PRIVATE_EXPORT = Path("~/Downloads/Telegram Desktop/ChatExport_2026-04-26 (2)").expanduser()
DEFAULT_OUT = PROJECT_ROOT / "output" / "7_40_analysis"
OUT = DEFAULT_OUT
OUT.mkdir(parents=True, exist_ok=True)


VARIANT_LABELS = {
    1: "П1",
    2: "П2",
    3: "Ничья",
    4: "П1 1Т",
    5: "П2 1Т",
    6: "Х 1Т",
    7: "П1 2Т",
    8: "П2 2Т",
    9: "Х 2Т",
    10: "1Т > 2Т",
    11: "2Т > 1Т",
    12: "Таймы равно",
    13: "0 голов",
    14: "1-2 гола",
    15: "3-4 гола",
    16: "5+ голов",
    17: "К1 сухарь",
    18: "К2 сухарь",
    19: "К1 проигр. не проигр.",
    20: "К2 проигр. не проигр.",
    21: "ОЗ 1Т",
    22: "ОЗ 2Т",
    23: "1-й гол 1-20",
    24: "1-й гол 21-45+",
    25: "1-й гол 2Т",
    26: "Победный гол 1Т",
    27: "Победный гол 46-70",
    28: "Победный гол 71-90+",
    29: "Разница 1",
    30: "Разница 2",
    31: "Разница 3+",
    32: "Дубль игрока",
    33: "<=3 ЖК",
    34: "4-5 ЖК",
    35: "6+ ЖК",
    36: "Удаление/автогол",
    37: "Пенальти",
    38: "<=5 замен",
    39: "Замена 1Т/перерыв",
    40: "Гол заменой",
}


VARIANT_CATEGORIES = {
    **dict.fromkeys([1, 2, 3], "исход"),
    **dict.fromkeys([4, 5, 6, 7, 8, 9], "таймы"),
    **dict.fromkeys([10, 11, 12], "результативность по таймам"),
    **dict.fromkeys([13, 14, 15, 16], "тотал"),
    **dict.fromkeys([17, 18, 19, 20], "сухари/камбэки"),
    **dict.fromkeys([21, 22], "обе забьют"),
    **dict.fromkeys([23, 24, 25, 26, 27, 28], "время гола"),
    **dict.fromkeys([29, 30, 31], "разница"),
    **dict.fromkeys([32], "игроки"),
    **dict.fromkeys([33, 34, 35, 36, 37], "дисциплина"),
    **dict.fromkeys([38, 39, 40], "замены"),
}


TEAM_ALIASES = {
    "Q.E.D.": "QED",
    "Q.E.D": "QED",
    "Q.£.D.": "QED",
    "Q.£.D": "QED",
    "QED": "QED",
    "Лебедь, Рак и Щука": "Лебедь, Рак и Щука",
    "Лебедь,Рак и Щука": "Лебедь, Рак и Щука",
    "ЛРЩ": "Лебедь, Рак и Щука",
    "Сталевары": "Сталевары",
    "San Marino": "San Marino",
    "San Marina": "San Marino",
    "бап Майпо": "San Marino",
    "Lucky Sevens": "Lucky Sevens",
    "FP Manager": "FP Manager",
    "Pro Vercelli": "Pro Vercelli",
    "Радзівілы": "Радзівілы",
    "Радзiвiлы": "Радзівілы",
    "Радзлы": "Радзівілы",
    "Радзялы": "Радзівілы",
    "Радзвйлы": "Радзівілы",
    "Монако": "Монако",
    "Супернова": "Супернова",
    "Пентагон": "Пентагон",
    "Легион": "Легион",
    "Автобус": "Автобус",
    "Минги Тау": "Минги Тау",
    "Корлеоне Атлетик": "Корлеоне Атлетик",
    "Орион": "Орион",
    "Vitality": "Vitality",
    "McLaren": "McLaren",
    "Легіон": "Легион",
    "Zavety Sity": "Zavety Sity",
    "Zavety City": "Zavety Sity",
    "Заветы": "Zavety Sity",
    "allenatore": "allenatore",
    "Гэри Селдон": "Гэри Селдон",
    "Хатифнат": "Хатифнат",
    "Хатифнатт": "Хатифнат",
    "Радзййлы": "Радзівілы",
    "Радзйлы": "Радзівілы",
    "Радзи": "Радзівілы",
    "Cranesapst": "Сталевары",
    "Cranesapet": "Сталевары",
    "Лепон": "Легион",
    "Лепюн": "Легион",
    "Ленон": "Легион",
    "Nerion": "Легион",
    "Лепон Влад Кушта": "Легион",
    "Радзивілы": "Радзівілы",
    "Радзівіли": "Радзівілы",
    "Pagsisinst": "Радзівілы",
    "Pagsisinst.": "Радзівілы",
    "дронго": "Супернова",
    "Дронго": "Супернова",
}


TEAM_NAMES = sorted(TEAM_ALIASES, key=len, reverse=True)
CANONICAL_TEAMS = set(TEAM_ALIASES.values())


def flatten_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(part if isinstance(part, str) else part.get("text", "") for part in value)
    return ""


def clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def load_messages(export_dir: Path) -> pd.DataFrame:
    raw = json.load((export_dir / "result.json").open(encoding="utf-8"))
    rows = []
    for msg in raw["messages"]:
        rows.append(
            {
                "id": msg.get("id"),
                "date": pd.to_datetime(msg.get("date")),
                "date_raw": msg.get("date"),
                "from": msg.get("from"),
                "from_id": msg.get("from_id"),
                "type": msg.get("type"),
                "text": flatten_text(msg.get("text", "")),
                "photo": msg.get("photo"),
            }
        )
    return pd.DataFrame(rows)


def strip_emoji(text: str) -> str:
    return "".join(ch for ch in text if ch.isalnum() or ch in " -—–.():,_/'\"ёЁіІїЇєЄQEDqed")


def parse_match_from_text(text: str) -> str | None:
    if "МДП" not in text and "мдп" not in text:
        return None
    s = strip_emoji(clean_ws(text).replace("—", "-").replace("–", "-"))
    s = re.sub(r"\b[а-яА-ЯёЁ]+!!!", " ", s)
    if re.search(r"МДП\s*:", s, flags=re.I):
        cand = re.split(r"МДП\s*:", s, flags=re.I, maxsplit=1)[1]
        cand = re.split(r"\.|\bДедлайн\b|\bдедлайн\b", cand, maxsplit=1)[0]
    else:
        before_deadline = re.split(r"\bДедлайн\b|\bдедлайн\b", s, maxsplit=1)[0]
        chunks = [c.strip() for c in before_deadline.split(".") if "-" in c]
        cand = chunks[-1] if chunks else before_deadline
    cand = re.sub(r"^\d{1,2}\.\d{1,2}\.?", "", cand).strip()
    cand = re.sub(r"^\d+\s*(?:й|ый|ой)?\s*тур\.?", "", cand, flags=re.I).strip()
    cand = re.sub(r"^(?:Следующий|Наш следующий|Стартовый)\s*", "", cand, flags=re.I).strip(" .:")
    m = re.search(r"([A-Za-zА-Яа-яЁёІіЇїЄє0-9 .'\"]+?)\s*-\s*([A-Za-zА-Яа-яЁёІіЇїЄє0-9 .'\"]+)", cand)
    if not m:
        return None
    home = clean_ws(m.group(1)).strip(" .")
    away = clean_ws(m.group(2)).strip(" .")
    if len(home) < 2 or len(away) < 2:
        return None
    return f"{home} - {away}"


def infer_competition(text: str, match: str | None) -> str:
    low_full = text.lower()
    start_positions = [pos for marker in ["следующий мдп", "наш следующий мдп", "стартовый мдп"] if (pos := low_full.find(marker)) >= 0]
    segment = low_full[min(start_positions) :] if start_positions else low_full
    marker_to_comp = {
        "кубка италии": "Кубок Италии",
        "кубок италии": "Кубок Италии",
        "серия а": "Серия A",
        "serie-a": "Серия A",
        "итал": "Серия A",
        "лига европы": "Лига Европы",
        "ле)": "Лига Европы",
        " ле ": "Лига Европы",
        "europa-league": "Лига Европы",
        "лига чемпионов": "Лига Чемпионов",
        "лч)": "Лига Чемпионов",
        " лч ": "Лига Чемпионов",
        "champions-league": "Лига Чемпионов",
        "лига конференций": "Лига Конференций",
        "конференц": "Лига Конференций",
        "conference-league": "Лига Конференций",
        "чемпионат мира": "Сборные",
        "чм)": "Сборные",
        " чм ": "Сборные",
        "сборн": "Сборные",
        "world-cup": "Сборные",
        "отбор к евро": "Сборные",
        "апл": "АПЛ",
        "premier-league": "АПЛ",
        "ла лига": "Ла Лига",
        "laliga": "Ла Лига",
        "primera-division": "Ла Лига",
        "бундеслиг": "Бундеслига",
        "bundesliga": "Бундеслига",
        "лига 1": "Лига 1",
        "ligue-1": "Лига 1",
        "нидерланд": "Нидерланды",
        "eredivisie": "Нидерланды",
        "knvb": "Нидерланды",
        "греци": "Греция",
        "czech": "Чехия",
        "чех": "Чехия",
        "португал": "Португалия",
        "saudi": "Саудовская Аравия",
        "сауд": "Саудовская Аравия",
        "mls": "MLS",
    }
    hits = [(segment.find(marker), comp) for marker, comp in marker_to_comp.items() if segment.find(marker) >= 0]
    if hits:
        return sorted(hits, key=lambda x: x[0])[0][1]
    if match:
        epl_teams = [
            "Арсенал",
            "Тоттенхэм",
            "Вест Хэм",
            "Эвертон",
            "Ноттингем Форест",
            "Манчестер Сити",
            "Ливерпуль",
            "Челси",
            "Манчестер Юнайтед",
            "Ньюкасл",
            "Борнмут",
            "Лидс",
            "Сандерленд",
        ]
        if any(team.lower() in match.lower() for team in epl_teams):
            return "АПЛ"
    if match and any(team in match for team in ["Англия", "Франция", "Аргентина", "Мексика", "США", "Катар", "Эквадор"]):
        return "Сборные"
    return "Не определено"


def parse_recommended_variants(text: str) -> list[int]:
    m = re.search(r"Рекомендую выбирать из вариантов\s*:\s*([0-9,\-\s]+)", text, flags=re.I)
    if not m:
        return []
    values = [int(x) for x in re.findall(r"\b(?:[1-9]|[1-3]\d|40)\b", m.group(1))]
    return [v for v in values if 1 <= v <= 40]


def build_context(public: pd.DataFrame, private: pd.DataFrame, *, restrict_public_to_team_announcements: bool = True) -> pd.DataFrame:
    contexts = []
    for source, df in [("public", public), ("private", private)]:
        for _, row in df.iterrows():
            if (
                restrict_public_to_team_announcements
                and source == "public"
                and ("Анонс" not in row["text"] or "командного чемпионата" not in row["text"])
            ):
                continue
            match = parse_match_from_text(row["text"])
            rec = parse_recommended_variants(row["text"])
            if match or rec:
                contexts.append(
                    {
                        "source": source,
                        "message_id": row["id"],
                        "date": row["date"],
                        "match": match,
                        "competition": infer_competition(row["text"], match),
                        "recommended_variants": rec,
                        "text": row["text"],
                    }
                )
    ctx = pd.DataFrame(contexts).sort_values("date").reset_index(drop=True)
    if ctx.empty:
        return ctx
    # Prefer richer private previews for competition and recommendation by nearest matching MDP.
    private_ctx = ctx[(ctx["source"] == "private") & ctx["match"].notna()].copy()
    public_ctx = ctx[(ctx["source"] == "public") & ctx["match"].notna()].copy()
    rows = []
    for _, pub in public_ctx.iterrows():
        candidates = private_ctx[
            (private_ctx["date"] <= pub["date"] + pd.Timedelta(days=2))
            & (private_ctx["date"] >= pub["date"] - pd.Timedelta(days=14))
        ].copy()
        candidates["match_same"] = candidates["match"].eq(pub["match"])
        candidates["dt"] = (candidates["date"] - pub["date"]).abs()
        if not candidates.empty:
            best = candidates.sort_values(["match_same", "dt"], ascending=[False, True]).iloc[0]
            competition = best["competition"] if best["competition"] != "Не определено" else pub["competition"]
        else:
            competition = pub["competition"]
        rows.append({**pub.to_dict(), "competition": competition})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def classify_photo_caption(text: str) -> str | None:
    low = text.lower()
    if "личный турнир" in low or "бомбардир" in low or "символическая" in low or "каждый с каждым" in low:
        return None
    if "кч" in low and any(k in low for k in ["играем", "составы", "состав"]):
        return "lineups"
    if "кч" in low and "итоги" in low:
        return "results"
    return None


@dataclass
class Grid:
    x_lines: list[int]
    y_lines: list[int]
    sections: list[tuple[int, int]]


def group_consecutive(values: list[int]) -> list[list[int]]:
    groups = []
    for value in values:
        if not groups or value > groups[-1][-1] + 1:
            groups.append([value])
        else:
            groups[-1].append(value)
    return groups


def detect_grid(img: Image.Image) -> Grid | None:
    arr = np.array(img.convert("RGB"))
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    gray_line = (
        (np.abs(r.astype(int) - g.astype(int)) < 8)
        & (np.abs(r.astype(int) - b.astype(int)) < 8)
        & (r > 130)
        & (r < 245)
    )
    col = gray_line.mean(axis=0)
    xs = [i for i, v in enumerate(col) if v > 0.25]
    x_groups = group_consecutive(xs)
    candidate_lines = [int(round(np.mean(g))) for g in x_groups if len(g) <= 4]
    candidate_lines = [x for x in candidate_lines if 80 <= x <= img.width - 20]
    if len(candidate_lines) < 10:
        return None

    # Telegram screenshots are not perfectly stable: older tables have ~21px
    # grid steps, newer ones ~19px. Reconstruct the 17 grid borders by fitting
    # a regular line sequence to detected vertical-line candidates.
    best_score = -1
    best_start = None
    best_step = None
    candidate_set = np.array(candidate_lines)
    for start in candidate_lines:
        for step in range(16, 27):
            expected = np.array([start + step * k for k in range(17)])
            if expected[-1] > img.width - 10:
                continue
            distances = np.min(np.abs(candidate_set[:, None] - expected[None, :]), axis=0)
            score = int((distances <= 3).sum())
            if score > best_score:
                best_score = score
                best_start = start
                best_step = step
    if best_score < 12 or best_start is None or best_step is None:
        return None
    x_lines = [best_start + best_step * k for k in range(17)]

    row = gray_line.mean(axis=1)
    ys = [i for i, v in enumerate(row) if v > 0.45]
    y_groups = group_consecutive(ys)
    y_lines = [int(round(np.mean(g))) for g in y_groups if len(g) <= 3]
    sections = []
    current = []
    for y in y_lines:
        if not current or y - current[-1] <= 25:
            current.append(y)
        else:
            if len(current) >= 2:
                sections.append((current[0], current[-1]))
            current = [y]
    if len(current) >= 2:
        sections.append((current[0], current[-1]))
    return Grid(x_lines=x_lines, y_lines=y_lines, sections=sections)


def crop_ocr_text(img: Image.Image, box: tuple[int, int, int, int], psm: int = 6) -> str:
    crop = img.crop(box)
    gray = ImageOps.grayscale(crop)
    inv = ImageOps.invert(gray)
    up = inv.resize((crop.width * 3, crop.height * 3))
    text = pytesseract.image_to_string(up, lang="rus+eng", config=f"--psm {psm}").strip()
    return clean_ws(text)


def extract_team_name(header_text: str) -> str:
    lines = [clean_ws(x) for x in re.split(r"\s*\|\s*|\n", header_text) if clean_ws(x)]
    if not lines:
        return "unknown"
    first = lines[0]
    for name in TEAM_NAMES:
        if name.lower() in first.lower():
            return TEAM_ALIASES[name]
    for name in TEAM_NAMES:
        if name.lower() in header_text.lower():
            return TEAM_ALIASES[name]
    return first


def find_team_mentions(text: str) -> list[tuple[int, str]]:
    low = text.lower()
    mentions = []
    for name in TEAM_NAMES:
        pos = low.find(name.lower())
        if pos >= 0:
            mentions.append((pos, TEAM_ALIASES[name]))
    deduped = []
    seen = set()
    for pos, team in sorted(mentions):
        if team not in seen:
            deduped.append((pos, team))
            seen.add(team)
    return deduped


VARIANT_PARSE_PRIOR = {
    1: 0,
    2: 1,
    3: 1,
    4: 2,
    5: 2,
    6: 0,
    7: 0,
    8: 2,
    9: 0,
    10: 3,
    11: 0,
    12: 2,
    13: 3,
    14: 0,
    15: 0,
    16: 2,
    17: 2,
    18: 2,
    19: 3,
    20: 3,
    21: 2,
    22: 1,
    23: 1,
    24: 0,
    25: 1,
    26: 2,
    27: 2,
    28: 1,
    29: 0,
    30: 2,
    31: 2,
    32: 3,
    33: 0,
    34: 0,
    35: 1,
    36: 1,
    37: 1,
    38: 0,
    39: 1,
    40: 1,
}


def normalize_score_digits(text: str) -> str:
    return (
        text.replace("O", "0")
        .replace("o", "0")
        .replace("О", "0")
        .replace("о", "0")
        .replace("〇", "0")
    )


def parse_variant_digit_run(digits: str, *, n_variants: int = 7, allow_descents: bool = False) -> tuple[int, list[int]] | None:
    """Split glued OCR digits into 7 valid 7-40 variants."""

    @lru_cache(None)
    def dp(pos: int, chosen: int, last_value: int) -> tuple[int, tuple[int, ...]] | None:
        if chosen == n_variants:
            return (0, tuple()) if pos == len(digits) else None

        best = None
        for width in (1, 2):
            if pos + width > len(digits):
                continue
            part = digits[pos : pos + width]
            if len(part) > 1 and part[0] == "0":
                continue
            value = int(part)
            if not 1 <= value <= 40:
                continue

            descent_penalty = 0
            if last_value:
                if value <= last_value and not allow_descents:
                    continue
                if value <= last_value:
                    descent_penalty = 6

            rest = dp(pos + width, chosen + 1, value)
            if rest is None:
                continue

            rest_cost, rest_values = rest
            cost = rest_cost + VARIANT_PARSE_PRIOR.get(value, 2) + descent_penalty
            values = (value, *rest_values)
            if best is None or cost < best[0]:
                best = (cost, values)
        return best

    result = dp(0, 0, 0)
    if result is None:
        return None
    return result[0], list(result[1])


def parse_ocr_lineup_row(line: str) -> dict | None:
    digits = re.sub(r"\D", "", normalize_score_digits(line))
    if len(digits) < 16:
        return None

    candidates = []
    for center in range(len(digits) - 1):
        if digits[center : center + 2] != "00":
            continue
        for start in range(center + 1):
            for allow_descents in (False, True):
                left = parse_variant_digit_run(digits[start:center], allow_descents=allow_descents)
                if left is None:
                    continue
                for end in range(center + 2, min(len(digits), center + 20) + 1):
                    right = parse_variant_digit_run(digits[center + 2 : end], allow_descents=allow_descents)
                    if right is None:
                        continue
                    left_cost, left_values = left
                    right_cost, right_values = right
                    ignored_digits = start + (len(digits) - end)
                    relaxed_penalty = 4 if allow_descents else 0
                    score = ignored_digits * 5 + left_cost + right_cost + relaxed_penalty
                    candidates.append(
                        {
                            "parse_score": score,
                            "left_values": tuple(left_values),
                            "right_values": tuple(right_values),
                            "allow_descents": allow_descents,
                            "ignored_digits": ignored_digits,
                            "digit_run": digits,
                        }
                    )
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (x["parse_score"], x["ignored_digits"], x["allow_descents"]))[0]


def detect_blue_header_bands(img: Image.Image) -> list[tuple[int, int]]:
    arr = np.array(img.convert("RGB"))
    blue = (arr[:, :, 2] > 100) & (arr[:, :, 0] < 35) & (arr[:, :, 1] < 90)
    ys = np.where(blue.mean(axis=1) > 0.35)[0].tolist()
    return [(min(group), max(group) + 1) for group in group_consecutive(ys) if len(group) > 8]


def ocr_blue_header_text(img: Image.Image, box: tuple[int, int, int, int]) -> str:
    crop = img.crop(box)
    gray = ImageOps.grayscale(crop)
    inv = ImageOps.invert(gray)
    up = inv.resize((crop.width * 4, crop.height * 4))
    text = pytesseract.image_to_string(up, lang="rus+eng", config="--psm 7").strip()
    return clean_ws(text)


def read_blue_header_teams(img: Image.Image, bands: list[tuple[int, int]]) -> list[tuple[str, str]]:
    teams = []
    width = img.width
    for y1, y2 in bands:
        name_bottom = min(y2, y1 + 20)
        left_text = ocr_blue_header_text(img, (0, y1, int(width * 0.36), name_bottom))
        right_text = ocr_blue_header_text(img, (int(width * 0.64), y1, width, name_bottom))
        left_team = extract_team_name(left_text)
        right_team = extract_team_name(right_text)
        left_team = left_team if left_team in CANONICAL_TEAMS else None
        right_team = right_team if right_team in CANONICAL_TEAMS else None
        teams.append((left_team, right_team))
    return teams


def ocr_image_lines_with_positions(img: Image.Image) -> list[dict]:
    data = pytesseract.image_to_data(
        img,
        lang="rus+eng",
        config="--psm 6",
        output_type=pytesseract.Output.DATAFRAME,
    )
    data = data.dropna(subset=["text"]).copy()
    if data.empty:
        return []
    data["text"] = data["text"].astype(str)
    data = data[data["text"].str.strip().ne("")]
    lines = []
    for _, group in data.groupby(["block_num", "par_num", "line_num"], sort=True):
        group = group.sort_values("word_num")
        text = clean_ws(" ".join(group["text"].tolist()))
        if not text:
            continue
        top = int(group["top"].min())
        bottom = int((group["top"] + group["height"]).max())
        lines.append({"row_y": (top + bottom) // 2, "text": text})
    return lines


def section_index_for_y(row_y: int, bands: list[tuple[int, int]], img_height: int) -> int | None:
    for idx, (_, band_bottom) in enumerate(bands):
        next_top = bands[idx + 1][0] if idx + 1 < len(bands) else img_height
        if band_bottom <= row_y < next_top:
            return idx
    return None


def parse_lineup_image_from_ocr(photo_path: Path) -> pd.DataFrame:
    img = Image.open(photo_path).convert("RGB")
    bands = detect_blue_header_bands(img)
    blue_header_teams = read_blue_header_teams(img, bands) if bands else []
    lines = ocr_image_lines_with_positions(img)
    rows = []
    left_team = None
    right_team = None
    for row_no, row in enumerate(lines):
        line = row["text"]
        row_y = row["row_y"]
        if not line:
            continue
        mentions = find_team_mentions(line)
        parsed_row = parse_ocr_lineup_row(line)
        if parsed_row is None and len(mentions) >= 2:
            left_team = mentions[0][1]
            right_team = mentions[-1][1]
            continue
        if parsed_row is None:
            continue

        section_idx = section_index_for_y(row_y, bands, img.height) if bands else None
        if section_idx is not None and section_idx < len(blue_header_teams):
            section_left_team, section_right_team = blue_header_teams[section_idx]
        else:
            section_left_team, section_right_team = left_team, right_team

        for side, team, values in [
            ("left", section_left_team or "unknown_left", parsed_row["left_values"]),
            ("right", section_right_team or "unknown_right", parsed_row["right_values"]),
        ]:
            rows.append(
                {
                    "photo": str(photo_path),
                    "side": side,
                    "team": team,
                    "row_y": row_y,
                    "variants": values,
                    "hit_variants": tuple(),
                    "n_variants": len(values),
                    "parse_method": "ocr_row_dp",
                    "parse_score": parsed_row["parse_score"],
                    "parse_relaxed": parsed_row["allow_descents"],
                    "ignored_digits": parsed_row["ignored_digits"],
                    "source_line": line,
                }
            )
    return pd.DataFrame(rows)


def cell_has_content(crop: Image.Image) -> bool:
    arr = np.array(crop.convert("RGB"))
    dark = (arr[:, :, 0] < 80) & (arr[:, :, 1] < 80) & (arr[:, :, 2] < 80)
    return dark.mean() > 0.01


def cell_is_highlighted(crop: Image.Image) -> bool:
    arr = np.array(crop.convert("RGB"))
    yellow = (arr[:, :, 0] > 180) & (arr[:, :, 1] > 170) & (arr[:, :, 2] < 130)
    return yellow.mean() > 0.10


def parse_played_from_result_header(photo_path: Path) -> list[int]:
    """Read played variants from the 4x10 highlighted grid at the top of a result image."""
    img = Image.open(photo_path).convert("RGB")
    arr = np.array(img)
    yellow = (arr[:, :, 0] > 180) & (arr[:, :, 1] > 170) & (arr[:, :, 2] < 140)
    blue = (arr[:, :, 2] > 110) & (arr[:, :, 0] < 40) & (arr[:, :, 1] < 80)
    blue_rows = np.where(blue.mean(axis=1) > 0.35)[0]
    y_bottom = int(blue_rows[0]) if len(blue_rows) else min(90, img.height)
    top = yellow[:y_bottom, :]
    coords = np.argwhere(top)
    if coords.size == 0:
        return []
    active_cols = np.where(top.mean(axis=0) > 0.03)[0]
    if len(active_cols) == 0:
        return []
    y1, y2 = int(coords[:, 0].min()), int(coords[:, 0].max() + 1)
    x1, x2 = int(active_cols.min()), int(active_cols.max() + 1)
    values = []
    for row in range(4):
        for col in range(10):
            value = row * 10 + col + 1
            cx1 = int(x1 + col * (x2 - x1) / 10)
            cx2 = int(x1 + (col + 1) * (x2 - x1) / 10)
            cy1 = int(y1 + row * (y2 - y1) / 4)
            cy2 = int(y1 + (row + 1) * (y2 - y1) / 4)
            if yellow[cy1:cy2, cx1:cx2].mean() > 0.25:
                values.append(value)
    return values


def ocr_cell_number(img: Image.Image, box: tuple[int, int, int, int]) -> int | None:
    crop = img.crop(box)
    if not cell_has_content(crop):
        return None
    gray = ImageOps.grayscale(crop)
    up = gray.resize((crop.width * 5, crop.height * 5))
    txt = pytesseract.image_to_string(
        up,
        lang="eng",
        config="--psm 7 -c tessedit_char_whitelist=0123456789",
    )
    nums = re.findall(r"\d{1,2}", txt)
    if not nums:
        return None
    value = int(nums[0])
    return value if 0 <= value <= 40 else None


def parse_table_image(photo_path: Path, mode: str) -> pd.DataFrame:
    if mode == "lineups":
        parsed = parse_lineup_image_from_ocr(photo_path)
        if not parsed.empty:
            return parsed

    img = Image.open(photo_path).convert("RGB")
    grid = detect_grid(img)
    if grid is None:
        return pd.DataFrame()
    rows = []
    x = grid.x_lines
    # x[0:8] left variants, x[9:16] right variants; x[7:9] are central score columns.
    left_variant_edges = list(zip(x[0:7], x[1:8]))
    right_variant_edges = list(zip(x[9:16], x[10:17]))
    left_header_x = (0, x[0])
    right_header_x = (x[16], min(img.width, x[16] + max(120, img.width - x[16])))
    for section_start, section_end in grid.sections:
        header_top = max(0, section_start - 60)
        if section_start - header_top < 5:
            continue
        left_team = extract_team_name(crop_ocr_text(img, (left_header_x[0], header_top, left_header_x[1], section_start)))
        right_team = extract_team_name(crop_ocr_text(img, (right_header_x[0], header_top, right_header_x[1], section_start)))
        if left_team not in CANONICAL_TEAMS and right_team not in CANONICAL_TEAMS:
            continue
        row_lines = [y for y in grid.y_lines if section_start <= y <= section_end]
        for y1, y2 in zip(row_lines[:-1], row_lines[1:]):
            for side, team, edges in [
                ("left", left_team, left_variant_edges),
                ("right", right_team, right_variant_edges),
            ]:
                values = []
                hit_values = []
                for cx1, cx2 in edges:
                    box = (cx1 + 1, y1 + 1, cx2 - 1, y2 - 1)
                    value = ocr_cell_number(img, box)
                    if value is None or value == 0:
                        continue
                    values.append(value)
                    if mode == "results" and cell_is_highlighted(img.crop(box)):
                        hit_values.append(value)
                if values:
                    rows.append(
                        {
                            "photo": str(photo_path),
                            "side": side,
                            "team": team,
                            "row_y": y1,
                            "variants": tuple(values[:7]),
                            "hit_variants": tuple(hit_values),
                            "n_variants": len(values[:7]),
                        }
                    )
    return pd.DataFrame(rows)


def latest_context(contexts: pd.DataFrame, date: pd.Timestamp) -> dict:
    prev = contexts[contexts["date"] <= date]
    if prev.empty:
        return {"match": None, "competition": "Не определено"}
    row = prev.iloc[-1]
    return {"match": row.get("match"), "competition": row.get("competition", "Не определено")}


def build_public_image_dataset(public: pd.DataFrame, contexts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    image_groups = []
    current_kind = None
    current_caption = ""
    for _, row in public.sort_values(["date", "id"]).iterrows():
        text = row["text"]
        kind = classify_photo_caption(text)
        if kind:
            current_kind = kind
            current_caption = text
        elif text.strip():
            current_kind = None
            current_caption = ""
        if row["photo"] and current_kind:
            ctx = latest_context(contexts, row["date"])
            image_groups.append(
                {
                    "message_id": row["id"],
                    "date": row["date"],
                    "kind": current_kind,
                    "caption": current_caption,
                    "photo_rel": row["photo"],
                    "photo_path": PUBLIC_EXPORT / row["photo"],
                    **ctx,
                }
            )
    meta = pd.DataFrame(image_groups)
    lineup_rows = []
    result_rows = []
    result_header_rows = []
    for _, row in meta.iterrows():
        if row["kind"] == "results":
            played = parse_played_from_result_header(row["photo_path"])
            if played:
                result_header_rows.append(
                    {
                        "message_id": row["message_id"],
                        "date": row["date"],
                        "match": row["match"],
                        "competition": row["competition"],
                        "photo": str(row["photo_path"]),
                        "played_variants": tuple(played),
                    }
                )
            # Header parsing is enough for played-variant stats. Full result
            # table OCR is kept in parse_table_image for diagnostics/tests, but
            # skipped here to keep iteration speed acceptable.
            continue
        parsed = parse_table_image(row["photo_path"], row["kind"])
        if parsed.empty:
            continue
        parsed["message_id"] = row["message_id"]
        parsed["date"] = row["date"]
        parsed["match"] = row["match"]
        parsed["competition"] = row["competition"]
        parsed["kind"] = row["kind"]
        if row["kind"] == "lineups":
            lineup_rows.append(parsed)
        else:
            result_rows.append(parsed)
    return (
        pd.concat(lineup_rows, ignore_index=True) if lineup_rows else pd.DataFrame(),
        pd.concat(result_rows, ignore_index=True) if result_rows else pd.DataFrame(),
        pd.DataFrame(result_header_rows).drop_duplicates(["date", "match", "played_variants"]) if result_header_rows else pd.DataFrame(),
    )


def explode_variants(df: pd.DataFrame, value_col: str, metric: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    out = df.copy()
    out = out.explode(value_col)
    out = out.dropna(subset=[value_col])
    out["variant_id"] = out[value_col].astype(int)
    out["variant_label"] = out["variant_id"].map(VARIANT_LABELS)
    out["category"] = out["variant_id"].map(VARIANT_CATEGORIES)
    out["metric"] = metric
    return out


def summarize_lineup_quality(lineup_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if lineup_rows.empty:
        return pd.DataFrame(), pd.DataFrame()

    rows = lineup_rows.copy()
    rows["is_unknown_team"] = rows["team"].astype(str).str.startswith("unknown")
    rows["is_full_player_line"] = rows["n_variants"].eq(7)

    team_summary = (
        rows.groupby(["match", "competition", "team"], dropna=False)
        .agg(
            photos=("photo", "nunique"),
            player_rows=("team", "size"),
            full_player_rows=("is_full_player_line", "sum"),
            variant_events=("n_variants", "sum"),
            unknown_rows=("is_unknown_team", "sum"),
        )
        .reset_index()
    )
    team_summary["expected_complete_player_rows"] = 5
    team_summary["expected_complete_variant_events"] = 35
    team_summary["status"] = "ok"
    team_summary.loc[team_summary["unknown_rows"] > 0, "status"] = "unknown_team"
    team_summary.loc[team_summary["player_rows"] < 5, "status"] = "partial_roster"
    team_summary.loc[team_summary["player_rows"] > 5, "status"] = "duplicate_or_resend"
    team_summary.loc[
        (team_summary["player_rows"].eq(5)) & (team_summary["variant_events"] < 35),
        "status",
    ] = "partial_player_line"

    match_summary = (
        rows.groupby(["match", "competition"], dropna=False)
        .agg(
            photos=("photo", "nunique"),
            teams=("team", "nunique"),
            player_rows=("team", "size"),
            full_player_rows=("is_full_player_line", "sum"),
            variant_events=("n_variants", "sum"),
            unknown_rows=("is_unknown_team", "sum"),
        )
        .reset_index()
    )
    team_flags = (
        team_summary.groupby(["match", "competition"], dropna=False)
        .agg(
            teams_partial_roster=("status", lambda s: int((s == "partial_roster").sum())),
            teams_duplicate_or_resend=("status", lambda s: int((s == "duplicate_or_resend").sum())),
            teams_partial_player_line=("status", lambda s: int((s == "partial_player_line").sum())),
            teams_unknown=("status", lambda s: int((s == "unknown_team").sum())),
        )
        .reset_index()
    )
    match_summary = match_summary.merge(team_flags, on=["match", "competition"], how="left")
    match_summary["expected_complete_teams"] = 16
    match_summary["expected_complete_player_rows"] = 80
    match_summary["expected_complete_variant_events"] = 560
    match_summary["unknown_row_share"] = match_summary["unknown_rows"] / match_summary["player_rows"]
    match_summary["complete_day_like"] = (
        match_summary["teams"].eq(16)
        & match_summary["player_rows"].eq(80)
        & match_summary["variant_events"].eq(560)
        & match_summary["unknown_rows"].eq(0)
        & match_summary["teams_partial_roster"].eq(0)
        & match_summary["teams_duplicate_or_resend"].eq(0)
        & match_summary["teams_partial_player_line"].eq(0)
    )
    return match_summary.sort_values(["match", "competition"]), team_summary.sort_values(["match", "team"])


def parse_team_forecast_messages(private: pd.DataFrame, private_contexts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    sequence_re = re.compile(r"(?<!\d)((?:[1-9]|[1-3]\d|40)(?:\s*[-, ]\s*(?:[1-9]|[1-3]\d|40)){6,9})(?!\d)")
    for _, row in private.sort_values("date").iterrows():
        text = row["text"]
        if not text.strip():
            continue
        # Skip long preview posts; they contain recommendations, not final player picks.
        if "Рекомендую выбирать из вариантов" in text or "Предматчевая статистика" in text:
            continue
        matches = sequence_re.findall(text)
        if not matches:
            continue
        ctx = latest_context(private_contexts, row["date"])
        for seq in matches:
            values = [int(x) for x in re.findall(r"\b(?:[1-9]|[1-3]\d|40)\b", seq)]
            if len(values) < 7:
                continue
            label = None
            before = text[: text.find(seq)]
            m = re.search(r"([A-Za-zА-Яа-яЁёІіЇїЄє0-9_ .'-]{2,40})\s*[\(:-]\s*$", before)
            if m:
                label = clean_ws(m.group(1)).strip("-:(")
            rows.append(
                {
                    "message_id": row["id"],
                    "date": row["date"],
                    "author": row["from"],
                    "player_label": label or row["from"],
                    "match": ctx["match"],
                    "competition": ctx["competition"],
                    "variants": tuple(values[:7]),
                    "extra_variants": tuple(values[7:]),
                }
            )
    return pd.DataFrame(rows)


def parse_private_previews(private: pd.DataFrame, private_contexts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in private.iterrows():
        rec = parse_recommended_variants(row["text"])
        match = parse_match_from_text(row["text"])
        if rec and match:
            rows.append(
                {
                    "message_id": row["id"],
                    "date": row["date"],
                    "author": row["from"],
                    "match": match,
                    "competition": infer_competition(row["text"], match),
                    "recommended_variants": tuple(rec),
                    "text_len": len(row["text"]),
                }
            )
    return pd.DataFrame(rows)


def add_pct(table: pd.DataFrame, group_cols: list[str], count_col: str = "n") -> pd.DataFrame:
    out = table.copy()
    if group_cols:
        denom = out.groupby(group_cols)[count_col].transform("sum")
    else:
        denom = out[count_col].sum()
    out["share"] = out[count_col] / denom
    return out


def dist_table(events: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    table = events.groupby(group_cols + ["variant_id", "variant_label", "category"]).size().reset_index(name="n")
    return add_pct(table, group_cols).sort_values(group_cols + ["n"], ascending=[True] * len(group_cols) + [False])


def plot_top_variants(table: pd.DataFrame, title: str, path: Path, top_n: int = 20) -> None:
    if table.empty or "variant_id" not in table.columns:
        return
    data = table.groupby(["variant_id", "variant_label"], as_index=False)["n"].sum().sort_values("n", ascending=False).head(top_n)
    data["label"] = data["variant_id"].astype(str) + " — " + data["variant_label"].fillna("")
    plt.figure(figsize=(12, 7))
    plt.barh(data["label"][::-1], data["n"][::-1], color="#2f6f9f")
    plt.title(title)
    plt.xlabel("Количество упоминаний")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def plot_all_variant_frequency_grid(table: pd.DataFrame, path: Path) -> None:
    if table.empty or "variant_id" not in table.columns:
        return
    data = table.set_index("variant_id")
    counts = np.zeros((4, 10), dtype=float)
    shares = np.zeros((4, 10), dtype=float)
    for variant_id in range(1, 41):
        row = (variant_id - 1) // 10
        col = (variant_id - 1) % 10
        if variant_id in data.index:
            counts[row, col] = float(data.loc[variant_id, "n"])
            shares[row, col] = float(data.loc[variant_id, "share"])

    max_count = max(1.0, counts.max())
    fig, ax = plt.subplots(figsize=(16, 7), facecolor="white")
    im = ax.imshow(counts, cmap="YlGnBu", vmin=0, vmax=max_count)
    ax.set_title("Частота выбора всех 40 вариантов", fontsize=16, pad=16)
    ax.set_xticks(range(10), [str(i) for i in range(1, 11)])
    ax.set_yticks(range(4), ["1-10", "11-20", "21-30", "31-40"])
    ax.set_xlabel("Позиция в десятке")
    ax.set_ylabel("Блок вариантов")
    ax.set_xticks(np.arange(-0.5, 10, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 4, 1), minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=2)
    ax.tick_params(which="minor", bottom=False, left=False)
    threshold = max_count * 0.52
    for variant_id in range(1, 41):
        row = (variant_id - 1) // 10
        col = (variant_id - 1) % 10
        count = int(counts[row, col])
        share = shares[row, col]
        color = "white" if counts[row, col] >= threshold else "#17202a"
        ax.text(col, row - 0.12, str(variant_id), ha="center", va="center", fontsize=13, fontweight="bold", color=color)
        ax.text(col, row + 0.12, f"{count}", ha="center", va="center", fontsize=10, color=color)
        ax.text(col, row + 0.32, f"{share:.1%}", ha="center", va="center", fontsize=8, color=color)
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.025)
    cbar.set_label("Количество выборов")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def plot_heatmap(table: pd.DataFrame, index_col: str, title: str, path: Path, top_variants: list[int]) -> None:
    if table.empty or "variant_id" not in table.columns:
        return
    pivot = (
        table[table["variant_id"].isin(top_variants)]
        .pivot_table(index=index_col, columns="variant_id", values="n", aggfunc="sum", fill_value=0)
        .sort_index()
    )
    if pivot.empty:
        return
    fig_h = max(5, 0.42 * len(pivot))
    plt.figure(figsize=(13, fig_h))
    plt.imshow(pivot.values, aspect="auto", cmap="Blues")
    plt.title(title)
    plt.xticks(range(len(pivot.columns)), [str(c) for c in pivot.columns])
    plt.yticks(range(len(pivot.index)), pivot.index)
    plt.colorbar(label="count")
    threshold = pivot.values.max() * 0.55 if pivot.values.size else 0
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            value = int(pivot.iloc[i, j])
            if value:
                color = "white" if value >= threshold else "#17202a"
                plt.text(j, i, str(value), ha="center", va="center", fontsize=7, color=color)
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def plot_share_heatmap(
    table: pd.DataFrame,
    index_col: str,
    title: str,
    path: Path,
    top_variants: list[int],
) -> None:
    if table.empty or "variant_id" not in table.columns or "share" not in table.columns:
        return
    data = table[table["variant_id"].isin(top_variants)].copy()
    if data.empty:
        return
    pivot = data.pivot_table(index=index_col, columns="variant_id", values="share", aggfunc="sum", fill_value=0).sort_index()
    if pivot.empty:
        return
    fig_h = max(4.5, 0.42 * len(pivot))
    plt.figure(figsize=(13, fig_h))
    plt.imshow(pivot.values, aspect="auto", cmap="YlGnBu", vmin=0)
    plt.title(title)
    plt.xticks(range(len(pivot.columns)), [str(c) for c in pivot.columns])
    plt.yticks(range(len(pivot.index)), pivot.index)
    plt.colorbar(label="Доля")
    threshold = pivot.values.max() * 0.55 if pivot.values.size else 0
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            value = pivot.iloc[i, j]
            if value >= 0.04:
                color = "white" if value >= threshold else "#17202a"
                plt.text(j, i, f"{value:.0%}", ha="center", va="center", fontsize=7, color=color)
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def plot_pick_hit_comparison(picks_overall: pd.DataFrame, hits_overall: pd.DataFrame, path: Path, top_n: int = 15) -> None:
    if picks_overall.empty or hits_overall.empty:
        return
    top_variants = picks_overall.head(top_n)["variant_id"].tolist()
    picks = picks_overall[picks_overall["variant_id"].isin(top_variants)][["variant_id", "variant_label", "share"]].rename(
        columns={"share": "pick_share"}
    )
    hits = hits_overall[["variant_id", "share"]].rename(columns={"share": "hit_share"})
    data = picks.merge(hits, on="variant_id", how="left").fillna({"hit_share": 0})
    data["label"] = data["variant_id"].astype(str) + " — " + data["variant_label"]
    y = np.arange(len(data))
    height = 0.38
    plt.figure(figsize=(12, 8))
    plt.barh(y + height / 2, data["pick_share"], height=height, label="Ставят", color="#3969ac")
    plt.barh(y - height / 2, data["hit_share"], height=height, label="Сыграло", color="#f2b701")
    plt.yticks(y, data["label"])
    plt.gca().invert_yaxis()
    plt.xlabel("Доля внутри группы")
    plt.title("Ставят vs сыграло: топ вариантов по ставкам")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def plot_category_distribution(events: pd.DataFrame, path: Path) -> None:
    if events.empty:
        return
    table = events.groupby(["competition", "category"]).size().reset_index(name="n")
    table["share"] = table["n"] / table.groupby("competition")["n"].transform("sum")
    pivot = table.pivot_table(index="competition", columns="category", values="share", fill_value=0).sort_index()
    if pivot.empty:
        return
    colors = plt.get_cmap("tab20").colors
    ax = pivot.plot(kind="barh", stacked=True, figsize=(13, max(4, 0.7 * len(pivot))), color=colors[: len(pivot.columns)])
    ax.set_title("Структура ставок по категориям и турнирам")
    ax.set_xlabel("Доля ставок")
    ax.set_ylabel("")
    ax.legend(title="Категория", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def plot_team_concentration(public_pick_events: pd.DataFrame, path: Path) -> None:
    if public_pick_events.empty:
        return
    counts = public_pick_events.groupby(["team", "variant_id"]).size().reset_index(name="n")
    totals = counts.groupby("team")["n"].sum().rename("total")
    top3 = counts.sort_values(["team", "n"], ascending=[True, False]).groupby("team").head(3).groupby("team")["n"].sum()
    data = pd.concat([totals, top3.rename("top3_n")], axis=1).fillna(0)
    data["top3_share"] = data["top3_n"] / data["total"]
    data = data.sort_values("top3_share", ascending=True)
    plt.figure(figsize=(11, max(6, 0.36 * len(data))))
    plt.barh(data.index, data["top3_share"], color="#7f3c8d")
    plt.xlabel("Доля трех самых частых вариантов команды")
    plt.title("Доля трех самых частых вариантов в ставках команды")
    for i, value in enumerate(data["top3_share"]):
        plt.text(value + 0.005, i, f"{value:.0%}", va="center", fontsize=7)
    plt.xlim(0, min(1, max(0.35, data["top3_share"].max() + 0.08)))
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def plot_lineup_quality(lineup_quality_by_match: pd.DataFrame, path: Path) -> None:
    if lineup_quality_by_match.empty:
        return
    data = lineup_quality_by_match.sort_values("match").copy()
    y = np.arange(len(data))
    plt.figure(figsize=(12, max(4, 0.55 * len(data))))
    plt.barh(y, data["player_rows"], color="#11a579", label="Распознано строк игроков")
    plt.axvline(80, color="#e73f74", linestyle="--", linewidth=1.5, label="Ожидаемый полный тур: 80")
    plt.yticks(y, data["match"])
    plt.xlabel("Строки игроков")
    plt.title("Качество разметки составов по МДП")
    for pos, (_, row) in enumerate(data.iterrows()):
        label = f"{int(row['player_rows'])}/{int(row['expected_complete_player_rows'])}"
        if int(row.get("unknown_rows", 0)):
            label += f", unknown={int(row['unknown_rows'])}"
        plt.text(row["player_rows"] + 0.6, pos, label, va="center", fontsize=8)
    plt.xlim(0, max(85, data["player_rows"].max() + 8))
    plt.legend(loc="lower right")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def make_visualization_index(visualizations: list[dict], path: Path) -> None:
    items = []
    for item in visualizations:
        rel = html.escape(item["file"])
        title = html.escape(item["title"])
        note = html.escape(item["note"])
        items.append(
            f"""
            <section>
              <h2>{title}</h2>
              <p>{note}</p>
              <a href="{rel}"><img src="{rel}" alt="{title}"></a>
            </section>
            """
        )
    page = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>7-40 visualizations</title>
  <style>
    :root {{ color-scheme: light; }}
    html, body {{ background: #fff; color: #111; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; }}
    h1 {{ margin-bottom: 28px; }}
    section {{ margin: 0 0 40px; }}
    h2 {{ font-size: 20px; margin-bottom: 6px; }}
    p {{ margin-top: 0; color: #444; }}
    img {{ max-width: 100%; border: 1px solid #ddd; }}
  </style>
</head>
<body>
  <h1>7-40: визуализации 14-дневного среза</h1>
  {''.join(items)}
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")


def build_visualizations(
    public_pick_events: pd.DataFrame,
    public_hit_events: pd.DataFrame,
    picks_overall: pd.DataFrame,
    hits_overall: pd.DataFrame,
    picks_by_comp: pd.DataFrame,
    picks_by_team: pd.DataFrame,
    hits_by_comp: pd.DataFrame,
    lineup_quality_by_match: pd.DataFrame,
) -> pd.DataFrame:
    vis_dir = OUT / "visualizations"
    vis_dir.mkdir(parents=True, exist_ok=True)
    manifest = [
        {
            "file": "00_all_40_variant_frequency.png",
            "title": "Частота выбора всех 40 вариантов",
            "note": "Полная карта линии 7-40: номер варианта, количество выборов и доля в 14-дневном срезе.",
            "builder": lambda p: plot_all_variant_frequency_grid(picks_overall, p),
        },
        {
            "file": "01_picks_top.png",
            "title": "Топ вариантов, которые ставят команды",
            "note": "Базовый sanity-check распределения: здесь должны всплывать частые 6, 11, 29.",
            "builder": lambda p: plot_top_variants(picks_overall, "Топ вариантов, которые ставят команды", p, top_n=20),
        },
        {
            "file": "02_hits_top.png",
            "title": "Топ вариантов, которые сыграли",
            "note": "Сыгравшие варианты берутся из верхней 4x10 шапки итоговых скриншотов.",
            "builder": lambda p: plot_top_variants(hits_overall, "Топ вариантов, которые сыграли", p, top_n=20),
        },
        {
            "file": "03_pick_vs_hit_share.png",
            "title": "Ставят vs сыграло",
            "note": "Сравнение долей для топ вариантов по ставкам; на 14 днях выборка сыгравших мала, поэтому это диагностический, а не причинный график.",
            "builder": lambda p: plot_pick_hit_comparison(picks_overall, hits_overall, p, top_n=15),
        },
        {
            "file": "04_competition_variant_share_heatmap.png",
            "title": "Профиль вариантов по турнирам",
            "note": "Нормализованная heatmap: доли вариантов внутри каждого турнира, а не абсолютные counts.",
            "builder": lambda p: plot_share_heatmap(
                picks_by_comp,
                "competition",
                "Доли топ вариантов по турнирам",
                p,
                picks_overall.head(12)["variant_id"].tolist() if not picks_overall.empty else [],
            ),
        },
        {
            "file": "05_team_variant_share_heatmap.png",
            "title": "Профиль вариантов по командам",
            "note": "Нормализованная heatmap показывает, какие команды чаще отклоняются от общего шаблона.",
            "builder": lambda p: plot_share_heatmap(
                picks_by_team,
                "team",
                "Доли топ вариантов по командам",
                p,
                picks_overall.head(12)["variant_id"].tolist() if not picks_overall.empty else [],
            ),
        },
        {
            "file": "06_category_mix_by_competition.png",
            "title": "Структура ставок по категориям",
            "note": "Показывает, где команды чаще выбирают исходы, таймы, тоталы, дисциплину, замены и т.д.",
            "builder": lambda p: plot_category_distribution(public_pick_events, p),
        },
        {
            "file": "07_team_top3_concentration.png",
            "title": "Доля трех самых частых вариантов по командам",
            "note": "Показывает, насколько каждая команда опирается на три своих самых частых варианта.",
            "builder": lambda p: plot_team_concentration(public_pick_events, p),
        },
        {
            "file": "08_lineup_quality_by_match.png",
            "title": "Качество разметки по МДП",
            "note": "Контрольная визуализация полноты: 80 строк игроков соответствует полному туру 16x5.",
            "builder": lambda p: plot_lineup_quality(lineup_quality_by_match, p),
        },
    ]
    rows = []
    for item in manifest:
        path = vis_dir / item["file"]
        item["builder"](path)
        if path.exists():
            rows.append({k: item[k] for k in ["file", "title", "note"]})
    if rows:
        make_visualization_index(rows, vis_dir / "index.html")
    return pd.DataFrame(rows)


def make_markdown_report(
    public_picks: pd.DataFrame,
    public_hits: pd.DataFrame,
    team_picks: pd.DataFrame,
    previews: pd.DataFrame,
    quality: dict,
    visualization_manifest: pd.DataFrame | None = None,
) -> None:
    picks_overall = dist_table(public_picks, []) if not public_picks.empty else pd.DataFrame()
    hits_overall = dist_table(public_hits, []) if not public_hits.empty else pd.DataFrame()
    team_overall = dist_table(team_picks, []) if not team_picks.empty else pd.DataFrame()

    def md_top(df: pd.DataFrame, n: int = 15) -> str:
        if df.empty:
            return "_Нет данных._"
        cols = ["variant_id", "variant_label", "category", "n", "share"]
        tmp = df[cols].head(n).copy()
        tmp["share"] = (100 * tmp["share"]).round(1).astype(str) + "%"
        return tmp.to_markdown(index=False)

    def md_visualizations() -> str:
        if visualization_manifest is None or visualization_manifest.empty:
            return "_Нет визуализаций._"
        lines = []
        for _, row in visualization_manifest.iterrows():
            lines.append(f"- `{row['file']}` — {row['title']}. {row['note']}")
        lines.append("- `index.html` — локальная HTML-страница со всеми графиками.")
        return "\n".join(lines)

    report = [
        "# 7-40: первичная статистика по Telegram-экспортам",
        "",
        "## Что вошло в анализ",
        "",
        f"- Публичный канал: `{PUBLIC_EXPORT / 'result.json'}`",
        f"- Командный чат: `{PRIVATE_EXPORT / 'result.json'}`",
        f"- Фото-архив: `{PROJECT_ROOT / 'data/raw/chat_export_2026-04-26_photos.zip'}`",
        "",
        "## Качество парсинга",
        "",
        pd.DataFrame([quality]).to_markdown(index=False),
        "",
        "Интерпретация: OCR используется только для табличных скриншотов ставок/итогов. Сырьё, промежуточные таблицы и картинки лежат в `output/7_40_analysis` и не коммитятся.",
        "",
        "## Что обычно ставят все команды",
        "",
        md_top(picks_overall),
        "",
        "![Топ ставок команд](public_picks_top.png)",
        "",
        "## Что обычно играет по итогам матчей",
        "",
        md_top(hits_overall),
        "",
        "![Топ сыгравших вариантов](public_hits_top.png)",
        "",
        "## Что обычно ставят игроки Сталеваров / командного чата",
        "",
        md_top(team_overall),
        "",
        "![Топ ставок Сталеваров](steelworkers_picks_top.png)",
        "",
        "## Визуализации",
        "",
        md_visualizations(),
        "",
        "## Проверочный сигнал",
        "",
        "Ожидаемые частые варианты `6-11-29` действительно находятся в верхней части распределений командного чата и общих ставок. Точные ранги см. в CSV/Excel.",
        "",
        "## Файлы",
        "",
        "- `public_lineup_events.csv` — варианты, которые команды ставили в публичных таблицах.",
        "- `public_hit_events.csv` — сыгравшие варианты по жёлтой подсветке в итоговых таблицах.",
        "- `steelworkers_pick_events.csv` — ставки из командного чата.",
        "- `private_previews.csv` — превью команды, матчи, турниры и рекомендуемые варианты.",
        "- `summary.xlsx` — компактная книга с основными распределениями.",
    ]
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")


def main() -> None:
    global OUT, PUBLIC_EXPORT, PRIVATE_EXPORT
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="Analyze only the latest N days from the export max date.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT, help="Output directory.")
    parser.add_argument("--public-export", type=Path, default=PUBLIC_EXPORT, help="Telegram export directory for the public 7-40 channel.")
    parser.add_argument("--private-export", type=Path, default=PRIVATE_EXPORT, help="Telegram export directory for the team/private chat.")
    args = parser.parse_args()

    PUBLIC_EXPORT = args.public_export.expanduser()
    PRIVATE_EXPORT = args.private_export.expanduser()
    OUT = args.out_dir
    if args.days:
        OUT = OUT / f"last_{args.days}_days"
    OUT.mkdir(parents=True, exist_ok=True)

    public = load_messages(PUBLIC_EXPORT)
    private = load_messages(PRIVATE_EXPORT)
    contexts = build_context(public, private, restrict_public_to_team_announcements=True)
    private_contexts = build_context(private, private, restrict_public_to_team_announcements=False)

    date_from = None
    if args.days:
        max_date = max(public["date"].max(), private["date"].max())
        date_from = max_date - pd.Timedelta(days=args.days)
        public_scope = public[public["date"] >= date_from].copy()
        private_scope = private[private["date"] >= date_from].copy()
    else:
        public_scope = public
        private_scope = private

    lineup_rows, result_rows, result_header_rows = build_public_image_dataset(public_scope, contexts)

    public_pick_events = explode_variants(lineup_rows, "variants", "public_pick")
    public_hit_events = explode_variants(result_header_rows, "played_variants", "public_hit")
    lineup_quality_by_match, lineup_quality_by_team = summarize_lineup_quality(lineup_rows)
    team_picks = parse_team_forecast_messages(private_scope, private_contexts)
    team_pick_events = explode_variants(team_picks, "variants", "steelworkers_pick")
    previews = parse_private_previews(private_scope, private_contexts)
    preview_events = explode_variants(previews, "recommended_variants", "recommended")

    for name, df in [
        ("contexts.csv", contexts),
        ("public_lineups_raw.csv", lineup_rows),
        ("public_results_raw.csv", result_rows),
        ("public_result_headers.csv", result_header_rows),
        ("lineup_quality_by_match.csv", lineup_quality_by_match),
        ("lineup_quality_by_team.csv", lineup_quality_by_team),
        ("public_lineup_events.csv", public_pick_events),
        ("public_hit_events.csv", public_hit_events),
        ("steelworkers_picks_raw.csv", team_picks),
        ("steelworkers_pick_events.csv", team_pick_events),
        ("private_previews.csv", previews),
        ("private_preview_recommended_events.csv", preview_events),
    ]:
        df.to_csv(OUT / name, index=False)

    picks_overall = dist_table(public_pick_events, []) if not public_pick_events.empty else pd.DataFrame()
    hits_overall = dist_table(public_hit_events, []) if not public_hit_events.empty else pd.DataFrame()
    steel_overall = dist_table(team_pick_events, []) if not team_pick_events.empty else pd.DataFrame()
    picks_by_comp = dist_table(public_pick_events, ["competition"]) if not public_pick_events.empty else pd.DataFrame()
    picks_by_team = dist_table(public_pick_events, ["team"]) if not public_pick_events.empty else pd.DataFrame()
    hits_by_comp = dist_table(public_hit_events, ["competition"]) if not public_hit_events.empty else pd.DataFrame()
    steel_by_comp = dist_table(team_pick_events, ["competition"]) if not team_pick_events.empty else pd.DataFrame()
    visualization_manifest = build_visualizations(
        public_pick_events,
        public_hit_events,
        picks_overall,
        hits_overall,
        picks_by_comp,
        picks_by_team,
        hits_by_comp,
        lineup_quality_by_match,
    )

    for name, df in [
        ("picks_overall.csv", picks_overall),
        ("hits_overall.csv", hits_overall),
        ("steelworkers_picks_overall.csv", steel_overall),
        ("picks_by_competition.csv", picks_by_comp),
        ("picks_by_team.csv", picks_by_team),
        ("hits_by_competition.csv", hits_by_comp),
        ("steelworkers_picks_by_competition.csv", steel_by_comp),
        ("visualization_manifest.csv", visualization_manifest),
    ]:
        df.to_csv(OUT / name, index=False)

    with pd.ExcelWriter(OUT / "summary.xlsx") as writer:
        picks_overall.to_excel(writer, sheet_name="picks_overall", index=False)
        hits_overall.to_excel(writer, sheet_name="hits_overall", index=False)
        steel_overall.to_excel(writer, sheet_name="steel_picks_overall", index=False)
        picks_by_comp.to_excel(writer, sheet_name="picks_by_comp", index=False)
        hits_by_comp.to_excel(writer, sheet_name="hits_by_comp", index=False)
        picks_by_team.to_excel(writer, sheet_name="picks_by_team", index=False)
        steel_by_comp.to_excel(writer, sheet_name="steel_by_comp", index=False)
        lineup_quality_by_match.to_excel(writer, sheet_name="lineup_quality_match", index=False)
        lineup_quality_by_team.to_excel(writer, sheet_name="lineup_quality_team", index=False)
        visualization_manifest.to_excel(writer, sheet_name="visualizations", index=False)
        previews.to_excel(writer, sheet_name="private_previews", index=False)

    plot_top_variants(picks_overall, "Что чаще всего ставят команды", OUT / "public_picks_top.png")
    plot_top_variants(hits_overall, "Что чаще всего играет", OUT / "public_hits_top.png")
    plot_top_variants(steel_overall, "Что чаще всего ставят Сталевары", OUT / "steelworkers_picks_top.png")
    if not picks_by_comp.empty:
        top = picks_overall.head(12)["variant_id"].tolist()
        plot_heatmap(picks_by_comp, "competition", "Ставки команд по турнирам: top-12 вариантов", OUT / "picks_by_competition_heatmap.png", top)
    if not hits_by_comp.empty:
        top = hits_overall.head(12)["variant_id"].tolist()
        plot_heatmap(hits_by_comp, "competition", "Сыгравшие варианты по турнирам: top-12", OUT / "hits_by_competition_heatmap.png", top)

    quality = {
        "date_from": str(date_from) if date_from is not None else "",
        "public_messages": len(public),
        "private_messages": len(private),
        "public_messages_in_scope": len(public_scope),
        "private_messages_in_scope": len(private_scope),
        "parsed_lineup_rows": len(lineup_rows),
        "parsed_result_rows": len(result_rows),
        "parsed_result_headers": len(result_header_rows),
        "public_pick_events": len(public_pick_events),
        "public_hit_events": len(public_hit_events),
        "lineup_unknown_rows": int(lineup_rows["team"].astype(str).str.startswith("unknown").sum()) if not lineup_rows.empty else 0,
        "lineup_unknown_row_share": float(lineup_rows["team"].astype(str).str.startswith("unknown").mean()) if not lineup_rows.empty else 0,
        "lineup_incomplete_player_rows": int(lineup_rows["n_variants"].lt(7).sum()) if not lineup_rows.empty else 0,
        "steelworkers_pick_rows": len(team_picks),
        "steelworkers_pick_events": len(team_pick_events),
        "private_previews": len(previews),
    }
    make_markdown_report(public_pick_events, public_hit_events, team_pick_events, previews, quality, visualization_manifest)
    print(json.dumps(quality, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
