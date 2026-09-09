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


# ---------- user-defined day boundary ("my day starts at") ----------

def day_window(day: date, tz_name: str, start_min: int | None) -> tuple[datetime, datetime] | None:
    """[start, end) datetimes (user tz) for a logical day. None when midnight."""
    if not start_min:
        return None
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz) + timedelta(minutes=start_min)
    return start, start + timedelta(days=1)


def logical_day_for(ts: datetime, tz_name: str, start_min: int | None) -> date:
    """Which logical day a timestamp belongs to under the boundary."""
    local = ts.astimezone(ZoneInfo(tz_name))
    if not start_min:
        return local.date()
    boundary = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=start_min)
    return local.date() if local >= boundary else (local - timedelta(days=1)).date()


def logical_today(tz_name: str, start_min: int | None) -> date:
    return logical_day_for(user_now(tz_name), tz_name, start_min)
