"""Korean presentation of values computed from rows, always in Asia/Seoul."""

from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from contracts import CardDue

SEOUL: Final = ZoneInfo("Asia/Seoul")
WEEKDAYS: Final = "월화수목금토일"
TWO_LETTER_NAME: Final = 2


def local(moment: datetime) -> datetime:
    """Convert an aware timestamp to workshop time."""
    return moment.astimezone(SEOUL)


def day_start(day: date) -> datetime:
    """Return local midnight, the inclusive start of a workshop day."""
    return datetime.combine(day, time.min, SEOUL)


def next_day_start(day: date) -> datetime:
    """Return the exclusive end of a workshop day."""
    return day_start(day + timedelta(days=1))


def month_start(day: date) -> date:
    """Return the first day of the containing month."""
    return day.replace(day=1)


def next_month(first: date) -> date:
    """Return the first day of the following month."""
    return (first.replace(day=28) + timedelta(days=4)).replace(day=1)


def previous_month(first: date) -> date:
    """Return the first day of the preceding month."""
    return (first - timedelta(days=1)).replace(day=1)


def clock(moment: datetime) -> str:
    """Format a 24-hour local time."""
    return local(moment).strftime("%H:%M")


def month_day(day: date) -> str:
    """Format a date without its weekday."""
    return f"{day.month}월 {day.day}일"


def weekday(day: date) -> str:
    """Return the one-letter Korean weekday."""
    return WEEKDAYS[day.weekday()]


def month_day_weekday(day: date) -> str:
    """Format a date with its weekday."""
    return f"{month_day(day)} {weekday(day)}"


def relative_day(day: date, today: date) -> str:
    """Name nearby days the way the owner says them."""
    names = {-1: "어제", 0: "오늘", 1: "내일"}
    return names.get((day - today).days, month_day(day))


def relative_moment(moment: datetime, today: date) -> str:
    """Format a nearby deadline."""
    return f"{relative_day(local(moment).date(), today)} {clock(moment)}"


def count(value: int) -> str:
    """Format a number of items."""
    return f"{value:,}건"


def people(value: int) -> str:
    """Format a number of people."""
    return f"{value:,}명"


def won(value: int) -> str:
    """Format Korean won."""
    return f"{value:,}원"


def masked(name: str) -> str:
    """Hide the middle of a customer name on shared screens."""
    if len(name) <= 1:
        return name
    if len(name) == TWO_LETTER_NAME:
        return f"{name[0]}*"
    return f"{name[0]}{'*' * (len(name) - 2)}{name[-1]}"


def due(
    moment: datetime, *, prefix: str | None = None, suffix: str = "", missed: str | None = None,
) -> CardDue:
    """Send a deadline as a Seoul-time moment; the client phrases it against its own clock."""
    at = local(moment).isoformat(timespec="seconds")
    return CardDue(at=at, prefix=prefix, suffix=suffix, missed=missed)
