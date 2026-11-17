import datetime
import re

from dateutil.relativedelta import relativedelta


def parse_duration(value, now=None):
    value = value.strip().lower()
    if value in {"permanent", "perm", "infinite", "none", "0"}:
        return None
    if value.isdigit():
        value += " days"
    units = {
        "y": "years", "yr": "years", "year": "years", "years": "years",
        "mo": "months", "month": "months", "months": "months",
        "w": "weeks", "week": "weeks", "weeks": "weeks",
        "d": "days", "day": "days", "days": "days",
        "h": "hours", "hr": "hours", "hour": "hours", "hours": "hours",
        "m": "minutes", "min": "minutes", "minute": "minutes", "minutes": "minutes",
        "s": "seconds", "sec": "seconds", "second": "seconds", "seconds": "seconds",
    }
    amounts = {}
    position = 0
    for match in re.finditer(r"(\d+)\s*([a-z]+)", value):
        if value[position:match.start()].strip(" ,") not in {"", "and"}:
            raise ValueError("Invalid duration.")
        unit = units.get(match.group(2))
        amount = int(match.group(1))
        if unit is None or amount <= 0 or amount > 100_000_000:
            raise ValueError("Use positive durations such as 6mo, 14d, 12h or 30m.")
        amounts[unit] = amounts.get(unit, 0) + amount
        position = match.end()
    if not amounts or value[position:].strip():
        raise ValueError("Use a duration such as 6 months, 14 days, 12h or 30m.")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        end = now + relativedelta(**amounts)
        seconds = int((end - now).total_seconds())
    except (ValueError, OverflowError) as exc:
        raise ValueError("The duration is too large.") from exc
    if not 0 < seconds <= 100 * 366 * 86400:
        raise ValueError("The duration must be positive and no longer than 100 years.")
    return seconds
