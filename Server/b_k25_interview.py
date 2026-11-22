"""Read spoken fact-card answers as numbers or short text, without guessing."""

import re
from typing import Final

from b_k25_numbers import NATIVE, whole_number
from b_k25_prompts import FactField

NUMBER: Final = rf"\d+(?:\.\d+)?|{NATIVE}|[일이삼사오육칠팔구십백]+"
HOURS: Final = re.compile(
    rf"(?P<h>{NUMBER})\s*시간(?:\s*(?P<half>반)|\s*(?P<m>{NUMBER})\s*분)?",
)
MINUTES: Final = re.compile(rf"(?<![가-힣\d])(?P<m>{NUMBER})\s*분")
PEOPLE: Final = re.compile(rf"(?P<n>{NUMBER})\s*(?:명|분|인|사람)")
BARE_PEOPLE: Final = re.compile(r"\d{1,3}")
UNSURE: Final = re.compile(r"^(?:음+|어+|글쎄요?|잘?\s*모르겠어요|모르겠습니다|몰라요|모름)[\s.…!?]*$")
MAX_MINUTES: Final = 1440
MAX_PEOPLE: Final = 1000


def parse_minutes(answer: str) -> int | None:
    """Read a class length in minutes, such as 두 시간 반, 2시간 30분, or 구십 분."""
    hours = HOURS.search(answer)
    if hours is not None:
        minutes = round(float(hours["h"]) * 60) if "." in hours["h"] else whole_number(hours["h"]) * 60
        if hours["half"]:
            minutes += 30
        elif hours["m"]:
            minutes += whole_number(hours["m"])
    else:
        only = MINUTES.search(answer)
        if only is None:
            return None
        minutes = whole_number(only["m"])
    return minutes if 0 < minutes <= MAX_MINUTES else None


def parse_people(answer: str) -> int | None:
    """Read one class capacity; several different numbers are not one answer."""
    counted = {whole_number(match["n"]) for match in PEOPLE.finditer(answer)}
    if not counted and BARE_PEOPLE.fullmatch(answer.strip()) is not None:
        counted = {int(answer.strip())}
    if len(counted) != 1:
        return None
    people = counted.pop()
    return people if 0 < people <= MAX_PEOPLE else None


def number_value(field: FactField, answer: str) -> str | None:
    """Read the number columns; None when the answer is not one clear number."""
    match field:
        case "durationMinutes":
            value = parse_minutes(answer)
        case "capacity":
            value = parse_people(answer)
        case _:
            return None
    return None if value is None else str(value)


def is_unsure(answer: str) -> bool:
    """Tell whether the owner only said that they do not know."""
    return not answer.strip() or bool(UNSURE.match(answer.strip()))
