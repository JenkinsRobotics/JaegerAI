"""Pure-stdlib 5-field cron expression parser and next-fire calculator.

Supports standard POSIX/Vixie 5-field cron syntax (`minute hour dom month dow`):
- Wildcards (`*`), steps (`*/n`, `a-b/n`), ranges (`a-b`), lists (`a,b,c`)
- Named months (`JAN`-`DEC`) and weekdays (`SUN`-`SAT`, with both `0` and `7` = Sunday)
- Standard aliases (`@hourly`, `@daily`, `@midnight`, `@weekly`, `@monthly`)

Zero external dependencies; deterministic UTC or local-time next-fire calculation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

__all__ = [
    "CronExpressionError",
    "CronSchedule",
    "next_cron_time",
    "parse_cron",
    "validate_cron",
]

_ALIASES: dict[str, str] = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
}

_MONTH_NAMES: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DOW_NAMES: dict[str, int] = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

_MAX_CRON_LEN = 128
_FIELD_RE = re.compile(r"^[A-Za-z0-9*,/-]+$")


class CronExpressionError(ValueError):
    """Raised when a 5-field cron expression is syntactically or semantically invalid."""


@dataclass(frozen=True, slots=True)
class CronSchedule:
    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]  # 0=Sunday .. 6=Saturday
    dom_wildcard: bool
    dow_wildcard: bool

    def matches(self, dt: datetime) -> bool:
        if dt.minute not in self.minutes:
            return False
        if dt.hour not in self.hours:
            return False
        if dt.month not in self.months:
            return False
        # Python weekday(): Monday=0..Sunday=6 -> cron Sunday=0..Saturday=6
        cron_dow = (dt.weekday() + 1) % 7
        dom_ok = dt.day in self.days_of_month
        dow_ok = cron_dow in self.days_of_week
        if not self.dom_wildcard and not self.dow_wildcard:
            return dom_ok or dow_ok  # Standard Vixie cron semantics when both specified
        return dom_ok and dow_ok

    def next_after(self, after_ts: float, *, utc: bool = False) -> float:
        """Compute the next Unix timestamp strictly greater than ``after_ts``."""
        tz = timezone.utc if utc else datetime.now().astimezone().tzinfo
        base = datetime.fromtimestamp(float(after_ts), tz=tz)
        candidate = base.replace(second=0, microsecond=0) + timedelta(minutes=1)
        # Bound search to 4 years (+ leap year) so invalid dates like Feb 31 fail cleanly.
        limit = candidate + timedelta(days=366 * 4 + 2)
        while candidate <= limit:
            if candidate.month not in self.months:
                # Jump to the first day of the next month.
                if candidate.month == 12:
                    candidate = candidate.replace(year=candidate.year + 1, month=1, day=1, hour=0, minute=0)
                else:
                    candidate = candidate.replace(month=candidate.month + 1, day=1, hour=0, minute=0)
                continue
            cron_dow = (candidate.weekday() + 1) % 7
            dom_ok = candidate.day in self.days_of_month
            dow_ok = cron_dow in self.days_of_week
            day_ok = (dom_ok or dow_ok) if (not self.dom_wildcard and not self.dow_wildcard) else (dom_ok and dow_ok)
            if not day_ok:
                candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if candidate.hour not in self.hours:
                candidate = (candidate + timedelta(hours=1)).replace(minute=0)
                continue
            if candidate.minute not in self.minutes:
                candidate = candidate + timedelta(minutes=1)
                continue
            return candidate.timestamp()
        raise CronExpressionError(f"cron expression {self.expression!r} has no upcoming fire date within 4 years")


def _parse_atom(token: str, lo: int, hi: int, names: dict[str, int] | None, *, is_dow: bool) -> int:
    low = token.lower()
    if names and low in names:
        val = names[low]
    else:
        if not token.isdigit():
            raise CronExpressionError(f"invalid cron value {token!r}")
        val = int(token)
    if is_dow and val == 7:
        val = 0
    if val < lo or val > hi:
        raise CronExpressionError(f"cron value {val} out of range [{lo}, {hi}]")
    return val


def _parse_field(raw: str, lo: int, hi: int, names: dict[str, int] | None = None, *, is_dow: bool = False) -> tuple[frozenset[int], bool]:
    if not raw or not _FIELD_RE.match(raw):
        raise CronExpressionError(f"invalid cron field {raw!r}")
    is_wildcard = raw == "*"
    values: set[int] = set()
    for part in raw.split(","):
        if not part:
            raise CronExpressionError(f"empty item in cron field {raw!r}")
        if "/" in part:
            pieces = part.split("/")
            if len(pieces) != 2 or not pieces[1].isdigit():
                raise CronExpressionError(f"invalid step in cron field {part!r}")
            step = int(pieces[1])
            if step <= 0:
                raise CronExpressionError(f"cron step must be positive in {part!r}")
            range_part = pieces[0]
        else:
            step = 1
            range_part = part

        if range_part == "*":
            start, end = lo, hi
        elif "-" in range_part:
            bounds = range_part.split("-")
            if len(bounds) != 2:
                raise CronExpressionError(f"invalid range {range_part!r}")
            start = _parse_atom(bounds[0], lo, hi, names, is_dow=is_dow)
            # For dow ranges like MON-SUN (1-7), allow 7 as Sunday end bound before modulo.
            if is_dow and bounds[1].lower() in ("7", "sun"):
                end = 7
            else:
                end = _parse_atom(bounds[1], lo, hi, names, is_dow=is_dow)
            if start > end:
                raise CronExpressionError(f"inverted cron range {range_part!r}")
        else:
            val = _parse_atom(range_part, lo, hi, names, is_dow=is_dow)
            if "/" in part:
                start, end = val, hi
            else:
                values.add(val)
                continue

        for n in range(start, end + 1, step):
            values.add(n % 7 if is_dow else n)
    if not values:
        raise CronExpressionError(f"cron field {raw!r} matched no values")
    return frozenset(values), is_wildcard


def parse_cron(expression: str) -> CronSchedule:
    """Parse and validate a standard 5-field cron expression or @alias."""
    if not isinstance(expression, str):
        raise CronExpressionError("cron expression must be a string")
    cleaned = " ".join(expression.strip().split())
    if not cleaned or len(cleaned) > _MAX_CRON_LEN:
        raise CronExpressionError(f"cron expression must be 1-{_MAX_CRON_LEN} characters")
    expanded = _ALIASES.get(cleaned.lower(), cleaned)
    fields = expanded.split(" ")
    if len(fields) != 5:
        raise CronExpressionError(f"cron expression must have 5 fields (minute hour dom month dow), got {len(fields)}")
    minutes, _ = _parse_field(fields[0], 0, 59)
    hours, _ = _parse_field(fields[1], 0, 23)
    dom, dom_wild = _parse_field(fields[2], 1, 31)
    months, _ = _parse_field(fields[3], 1, 12, _MONTH_NAMES)
    dow, dow_wild = _parse_field(fields[4], 0, 6, _DOW_NAMES, is_dow=True)
    return CronSchedule(
        expression=cleaned,
        minutes=minutes,
        hours=hours,
        days_of_month=dom,
        months=months,
        days_of_week=dow,
        dom_wildcard=dom_wild,
        dow_wildcard=dow_wild,
    )


def validate_cron(expression: str) -> str:
    """Return normalized cron expression or raise CronExpressionError."""
    return parse_cron(expression).expression


def next_cron_time(expression: str, *, after: float, utc: bool = False) -> float:
    """Compute the next Unix timestamp matching ``expression`` strictly after ``after``."""
    return parse_cron(expression).next_after(after, utc=utc)
