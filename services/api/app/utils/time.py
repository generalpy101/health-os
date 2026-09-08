from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def user_now(tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    return datetime.now(tz)


def user_today(tz_name: str) -> date:
    return user_now(tz_name).date()


def parse_date(value: str | date | None, tz_name: str = "UTC") -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return user_today(tz_name)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def date_range(days: int, tz_name: str = "UTC") -> tuple[date, date]:
    end = user_today(tz_name)
    return end - timedelta(days=days - 1), end
