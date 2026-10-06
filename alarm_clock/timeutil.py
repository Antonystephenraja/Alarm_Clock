"""Pure time helpers: timezone handling, input parsing, formatting, next-occurrence math.

Nothing in this module touches the disk, the console or the sound card, so every
function can be tested by passing in a fixed "now".
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from functools import lru_cache
from typing import Dict, List, Optional

try:
    import zoneinfo
except ImportError:  # pragma: no cover - Python < 3.9
    zoneinfo = None

LOCAL = "local"
UTC = "UTC"
MAX_DURATION = timedelta(hours=24)

_OFFSET_RE = re.compile(r"^(?:UTC|GMT)?([+-])(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE)
_TIME_RE = re.compile(
    r"^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?$", re.IGNORECASE
)
_DURATION_RE = re.compile(r"(?:\d+[hms])+")
_DURATION_PART_RE = re.compile(r"(\d+)([hms])")
_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}


# --------------------------------------------------------------------------- timezones

def _parse_offset(text: str) -> Optional[timedelta]:
    """Parse 'UTC+05:30', '+5:30', '-8', 'GMT-0800'. Returns None if it is not an offset."""
    match = _OFFSET_RE.match(text.strip())
    if not match:
        return None
    sign = -1 if match.group(1) == "-" else 1
    hours, minutes = int(match.group(2)), int(match.group(3) or 0)
    if hours > 14 or minutes > 59:
        raise ValueError(f"Invalid UTC offset '{text}'. Use e.g. UTC+05:30 or -8 (max +/-14:00).")
    return sign * timedelta(hours=hours, minutes=minutes)


def _offset_name(offset: timedelta) -> str:
    minutes = int(offset.total_seconds() // 60)
    if minutes == 0:
        return UTC
    sign = "+" if minutes > 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{mins:02d}"


@lru_cache(maxsize=None)
def _zone_lookup() -> Dict[str, str]:
    """Lower-case name -> canonical IANA name (empty when no tz database is installed)."""
    if zoneinfo is None:
        return {}
    return {name.lower(): name for name in zoneinfo.available_timezones()}


def tz_names() -> List[str]:
    """All installed IANA zone names, sorted. Empty if no tz database is available."""
    return sorted(_zone_lookup().values())


def normalize_tz(name: str) -> str:
    """Validate a timezone and return its canonical spelling.

    Accepts 'local', 'UTC', fixed offsets ('UTC+05:30', '-8') and IANA names
    ('Asia/Kolkata', case-insensitive) when a tz database is installed.
    """
    text = name.strip()
    if text.lower() in (LOCAL, "system"):
        return LOCAL
    if text.upper() in (UTC, "GMT", "Z"):
        return UTC
    offset = _parse_offset(text)
    if offset is not None:
        return _offset_name(offset)
    found = _zone_lookup().get(text.lower())
    if found is None:
        if not _zone_lookup():
            raise ValueError(
                f"Unknown timezone '{name}'. Named zones need the tz database "
                "(Windows: pip install tzdata). 'local', 'UTC' and offsets such as "
                "UTC+05:30 always work."
            )
        raise ValueError(
            f"Unknown timezone '{name}'. Search with the 'timezones' command, "
            "or use an offset such as UTC+05:30."
        )
    return found


@lru_cache(maxsize=None)
def get_zone(tz: str) -> Optional[tzinfo]:
    """tzinfo for a timezone name, or None for the system-local zone."""
    canonical = normalize_tz(tz)
    if canonical == LOCAL:
        return None
    if canonical == UTC:
        return timezone.utc
    offset = _parse_offset(canonical)
    if offset is not None:
        return timezone(offset)
    return zoneinfo.ZoneInfo(canonical)


# ------------------------------------------------------------------------- clock math

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def from_iso(text: str) -> datetime:
    return datetime.fromisoformat(text)


def in_zone(moment: datetime, tz: str) -> datetime:
    """Express an aware datetime in the given timezone."""
    zone = get_zone(tz)
    return moment.astimezone() if zone is None else moment.astimezone(zone)


def localize(day: date, at: time, tz: str) -> datetime:
    """The instant (UTC) at which the wall clock in `tz` reads `at` on `day`."""
    naive = datetime.combine(day, at)
    zone = get_zone(tz)
    aware = naive.astimezone() if zone is None else naive.replace(tzinfo=zone)
    return aware.astimezone(timezone.utc)


def next_occurrence(at: time, tz: str, after: datetime) -> datetime:
    """First instant strictly after `after` when the wall clock in `tz` reads `at` (UTC result)."""
    today = in_zone(after, tz).date()
    candidate = localize(today, at, tz)
    if candidate <= after:
        candidate = localize(today + timedelta(days=1), at, tz)
    return candidate


# ---------------------------------------------------------------------------- parsing

def parse_time_of_day(text: str) -> time:
    """'07:30', '19:30:15', '7:30pm', '7 am' -> time. Raises ValueError with a hint."""
    error = ValueError(
        f"Invalid time '{text}'. Use HH:MM (24h, e.g. 07:30) or h:MM am/pm (e.g. 7:30pm)."
    )
    match = _TIME_RE.match(text.strip())
    if not match:
        raise error
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    second = int(match.group(3) or 0)
    meridiem = match.group(4)
    if meridiem is None and match.group(2) is None:
        raise error  # a bare "7" is ambiguous
    if meridiem:
        if not 1 <= hour <= 12:
            raise error
        hour = hour % 12 + (12 if meridiem.lower().startswith("p") else 0)
    if hour > 23 or minute > 59 or second > 59:
        raise error
    return time(hour, minute, second)


def parse_duration(text: str) -> timedelta:
    """'90s', '25m', '2h', '1h30m' -> timedelta (1 second to 24 hours)."""
    compact = "".join(text.lower().split())
    if not _DURATION_RE.fullmatch(compact):
        raise ValueError(f"Invalid duration '{text}'. Use units, e.g. 90s, 25m, 2h or 1h30m.")
    seconds = sum(int(n) * _UNIT_SECONDS[unit] for n, unit in _DURATION_PART_RE.findall(compact))
    if seconds <= 0:
        raise ValueError("Duration must be greater than zero.")
    delta = timedelta(seconds=seconds)
    if delta > MAX_DURATION:
        raise ValueError("Duration cannot exceed 24h; use a clock time for later alarms.")
    return delta


# -------------------------------------------------------------------------- formatting

def format_clock(moment, fmt: str, seconds: bool = True) -> str:
    """Format the time part of a time/datetime as 12h ('7:05:09 PM') or 24h ('19:05:09')."""
    hour, minute, second = moment.hour, moment.minute, moment.second
    if fmt == "12":
        text = f"{hour % 12 or 12}:{minute:02d}"
        if seconds:
            text += f":{second:02d}"
        return f"{text} {'AM' if hour < 12 else 'PM'}"
    text = f"{hour:02d}:{minute:02d}"
    return text + f":{second:02d}" if seconds else text


def format_alarm_time(at: time, fmt: str) -> str:
    """Alarm times show seconds only when they are not zero."""
    return format_clock(at, fmt, seconds=bool(at.second))


def format_date(moment) -> str:
    return f"{moment:%A}, {moment.day:02d} {moment:%B %Y}"


def format_stamp(moment: datetime, fmt: str) -> str:
    """Short date + time, e.g. 'Wed 07 Oct 07:30'."""
    return f"{moment:%a} {moment.day:02d} {moment:%b} " + format_clock(
        moment, fmt, seconds=bool(moment.second)
    )


def format_offset(moment: datetime) -> str:
    return _offset_name(moment.utcoffset() or timedelta(0))


def humanize_delta(delta: timedelta) -> str:
    """'1d 2h 05m', '2h 05m', '5m 03s', '12s'."""
    total = max(0, int(delta.total_seconds()))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h {minutes:02d}m"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def format_countdown(delta: timedelta) -> str:
    """'00:24:13', or '1d 02:03:04' for longer spans."""
    total = max(0, int(delta.total_seconds()))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    clock = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{days}d {clock}" if days else clock
