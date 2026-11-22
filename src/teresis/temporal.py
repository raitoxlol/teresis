"""Deterministic temporal expression parser for memory queries (stdlib only, no LLM)."""

from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass

DAY = 86400.0

_NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "couple": 2, "few": 3, "several": 4,
}

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_NUM_PAT = r"(?:\d+|a\s+couple\s+(?:of\s+)?|a\s+few\s+|" + "|".join(_NUM_WORDS) + r")"
_UNIT_PAT = r"(days?|weeks?|months?|years?)"
_MONTH_PAT = r"(?:" + "|".join(_MONTHS) + r")"

_RE_AGO = re.compile(rf"\b({_NUM_PAT})\s+{_UNIT_PAT}\s+ago\b", re.I)
_RE_IN_LAST = re.compile(rf"\b(?:in|over|during)\s+the\s+(?:last|past)\s+(?:({_NUM_PAT})\s+)?{_UNIT_PAT}\b", re.I)
_RE_LAST_UNIT = re.compile(r"\blast\s+(week|month|year|weekend)\b", re.I)
_RE_YESTERDAY = re.compile(r"\b(yesterday|today)\b", re.I)
_RE_ISO = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_RE_MONTH_DAY = re.compile(rf"\b(?:on\s+)?({_MONTH_PAT})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(20\d{{2}}))?\b", re.I)
_RE_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_PAT})(?:,?\s*(20\d{{2}}))?\b", re.I)
_RE_IN_MONTH = re.compile(rf"\b(?:in|during|last|this)\s+({_MONTH_PAT})(?:\s+(20\d{{2}}))?\b", re.I)
_RE_MONTH_YEAR = re.compile(rf"\b({_MONTH_PAT})\s+(20\d{{2}})\b", re.I)
_RE_IN_YEAR = re.compile(r"\b(?:in|during)\s+(20\d{2})\b", re.I)


@dataclass(frozen=True)
class TimeWindow:
    start: float
    end: float
    soft_margin: float  # seconds outside [start, end] where proximity decays to 0.5

    def proximity(self, ts: float) -> float:
        """1.0 inside [start, end], smoothly decaying outside."""
        if ts <= 0:
            return 0.0
        if self.start <= ts <= self.end:
            return 1.0
        dist = self.start - ts if ts < self.start else ts - self.end
        return 1.0 / (1.0 + (dist / max(self.soft_margin, DAY)) ** 2)


def _parse_num(raw: str) -> int:
    s = raw.strip().lower()
    if s.isdigit():
        return int(s)
    if "couple" in s:
        return 2
    if "few" in s:
        return 3
    return _NUM_WORDS.get(s, 1)


def _utc(y: int, m: int, d: int, end_of_day: bool = False) -> float:
    t = dt.datetime(y, m, d, 23 if end_of_day else 0, 59 if end_of_day else 0, 59 if end_of_day else 0,
                    tzinfo=dt.timezone.utc)
    return t.timestamp()


def _month_window(year: int, month: int) -> TimeWindow:
    last_day = calendar.monthrange(year, month)[1]
    return TimeWindow(_utc(year, month, 1), _utc(year, month, last_day, end_of_day=True), soft_margin=10 * DAY)


def _resolve_month_year(now_dt: dt.datetime, month: int, explicit_year: str | None) -> int:
    if explicit_year:
        return int(explicit_year)
    return now_dt.year if month <= now_dt.month else now_dt.year - 1


def parse_time_window(query: str, now: float) -> TimeWindow | None:
    """Extract a target [start, end] unix timestamp window from a query relative to ``now``."""
    if not query or now <= 0:
        return None
    now_dt = dt.datetime.fromtimestamp(now, tz=dt.timezone.utc)

    # 1. Exact ISO date: 2023-05-08
    if m := _RE_ISO.search(query):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            try:
                return TimeWindow(_utc(y, mo, d) - DAY, _utc(y, mo, d, True) + DAY, soft_margin=5 * DAY)
            except ValueError:
                pass

    # 2. Month + day: "May 8", "on June 27, 2023", "8 May 2023"
    if m := _RE_MONTH_DAY.search(query):
        mo = _MONTHS[m.group(1).lower()]
        d = int(m.group(2))
        y = _resolve_month_year(now_dt, mo, m.group(3))
        try:
            return TimeWindow(_utc(y, mo, d) - 2 * DAY, _utc(y, mo, d, True) + 2 * DAY, soft_margin=7 * DAY)
        except ValueError:
            pass
    if m := _RE_DAY_MONTH.search(query):
        d = int(m.group(1))
        mo = _MONTHS[m.group(2).lower()]
        y = _resolve_month_year(now_dt, mo, m.group(3))
        try:
            return TimeWindow(_utc(y, mo, d) - 2 * DAY, _utc(y, mo, d, True) + 2 * DAY, soft_margin=7 * DAY)
        except ValueError:
            pass

    # 3. Relative "N days/weeks/months/years ago" (skip "how many days ago" questions!)
    low = query.lower()
    if "how many" not in low:
        if m := _RE_AGO.search(query):
            n = _parse_num(m.group(1))
            unit = m.group(2).lower().rstrip("s")
            if unit == "day":
                center = now - n * DAY
                half = max(1.5, 0.35 * n) * DAY
                return TimeWindow(center - half, center + half, soft_margin=max(3.0, 0.5 * n) * DAY)
            if unit == "week":
                center = now - n * 7 * DAY
                half = max(4.0, 2.5 * n) * DAY
                return TimeWindow(center - half, center + half, soft_margin=max(7.0, 4.0 * n) * DAY)
            if unit == "month":
                center = now - n * 30.4 * DAY
                half = max(15.0, 8.0 * n) * DAY
                return TimeWindow(center - half, center + half, soft_margin=max(20.0, 10.0 * n) * DAY)
            if unit == "year":
                center = now - n * 365.25 * DAY
                half = 60 * DAY
                return TimeWindow(center - half, center + half, soft_margin=90 * DAY)

    # 4. "yesterday" / "today"
    if m := _RE_YESTERDAY.search(query):
        w = m.group(1).lower()
        offset = 1 if w == "yesterday" else 0
        center = now - offset * DAY
        return TimeWindow(center - 1.5 * DAY, center + 1.5 * DAY, soft_margin=3 * DAY)

    # 4b. "in the last month" / "over the past 2 weeks" -> rolling [now - duration, now]
    if m := _RE_IN_LAST.search(query):
        n = _parse_num(m.group(1)) if m.group(1) else 1
        unit = m.group(2).lower().rstrip("s")
        span = {"day": DAY, "week": 7 * DAY, "month": 31 * DAY, "year": 366 * DAY}[unit] * n
        return TimeWindow(now - span, now, soft_margin=max(3 * DAY, 0.25 * span))

    # 5. "last week" / "last month" / "last year" / "last weekend"
    if m := _RE_LAST_UNIT.search(query):
        unit = m.group(1).lower()
        if unit in ("week", "weekend"):
            return TimeWindow(now - 11 * DAY, now - 2 * DAY, soft_margin=7 * DAY)
        if unit == "month":
            prev_m = now_dt.month - 1 or 12
            prev_y = now_dt.year if now_dt.month > 1 else now_dt.year - 1
            return _month_window(prev_y, prev_m)
        if unit == "year":
            return TimeWindow(_utc(now_dt.year - 1, 1, 1), _utc(now_dt.year - 1, 12, 31, True), soft_margin=60 * DAY)

    # 6. Explicit month ("in January", "February 2023")
    if m := _RE_IN_MONTH.search(query):
        mo = _MONTHS[m.group(1).lower()]
        y = _resolve_month_year(now_dt, mo, m.group(2))
        return _month_window(y, mo)
    if m := _RE_MONTH_YEAR.search(query):
        mo = _MONTHS[m.group(1).lower()]
        y = int(m.group(2))
        return _month_window(y, mo)

    # 7. Explicit year ("in 2022")
    if m := _RE_IN_YEAR.search(query):
        y = int(m.group(1))
        return TimeWindow(_utc(y, 1, 1), _utc(y, 12, 31, True), soft_margin=60 * DAY)

    return None
