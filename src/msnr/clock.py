from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
PKT = ZoneInfo("Asia/Karachi")
NY = ZoneInfo("America/New_York")


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    return value.astimezone(UTC)


def iso(value: datetime) -> str:
    return aware(value).isoformat()


def period(now: datetime, kind: str) -> tuple[datetime, datetime]:
    """Last completed [start, end) report period, at 02:00 PKT.

    Daily periods end at today's 02:00 if reached, otherwise yesterday's.
    Weekly periods end Saturday 02:00; a Saturday daily report is also distinct.
    """
    local = aware(now).astimezone(PKT)
    end = local.replace(hour=2, minute=0, second=0, microsecond=0)
    if end > local:
        end -= timedelta(days=1)
    if kind == "weekly":
        end -= timedelta(days=(end.weekday() - 5) % 7)
        start = end - timedelta(days=7)
    elif kind == "daily":
        start = end - timedelta(days=1)
    else:
        raise ValueError("Unknown reporting period")
    return start.astimezone(UTC), end.astimezone(UTC)


def quarter(now: datetime) -> int:
    wall = aware(now).astimezone(NY)
    return (wall.hour * 60 + wall.minute) % 360 // 90 + 1


def session(now: datetime) -> str:
    wall = aware(now).astimezone(NY)
    m = wall.hour * 60 + wall.minute
    if m >= 19 * 60:
        return "asia"
    if 2 * 60 <= m < 5 * 60:
        return "london"
    if 8 * 60 <= m < 11 * 60:
        return "new_york_am"
    if 13 * 60 <= m < 16 * 60:
        return "new_york_pm"
    return "off_session"
