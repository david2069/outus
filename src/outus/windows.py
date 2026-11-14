"""Time windows: does a local time fall inside an OUTUS window?

A window is ``{months, day_types, start, end, holiday_region, clock}`` (OUTUS) or the
older tariff-profile ``{months, days, start, end}`` (``days`` = weekday numbers, Monday 0).
Omitted parts mean always. An end at or before the start wraps past midnight, and
``24:00`` ends the day.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

#: A callable telling whether a local date is a public holiday in a region.
HolidayCheck = Callable[[dt.date, str | None], bool]


def hhmm(raw: Any) -> int | None:
    """``"HH:MM"`` → minutes since midnight, or None."""
    if not isinstance(raw, str) or ":" not in raw:
        return None
    try:
        h, m = (int(x) for x in raw.split(":", 1))
    except ValueError:
        return None
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m):
        return None
    return h * 60 + m


def day_type(local: dt.datetime, region: str | None = None,
             is_holiday: HolidayCheck | None = None) -> str:
    """``holiday``, ``weekend`` or ``weekday`` for a local time."""
    if is_holiday is not None and is_holiday(local.date(), region):
        return "holiday"
    return "weekend" if local.weekday() >= 5 else "weekday"


def in_window(win: Any, local: dt.datetime, is_holiday: HolidayCheck | None = None) -> bool:
    """Is ``local`` (the site's local time) inside ``win``? No window means always."""
    if win is None:
        return True
    if not isinstance(win, dict):
        return False
    months = win.get("months") or []
    if months and local.month not in months:
        return False
    days = win.get("days") or []
    if days and local.weekday() not in days:
        return False
    types = win.get("day_types") or []
    # A public holiday is its own day type: a window listing only weekdays excludes it.
    # Without a holiday check, no day is a holiday.
    if types and day_type(local, win.get("holiday_region"), is_holiday) not in types:
        return False
    start, end = hhmm(win.get("start")), hhmm(win.get("end"))
    if start is None or end is None:
        return True
    if win.get("clock") == "standard" and local.dst():
        local = local - local.dst()
    minute = local.hour * 60 + local.minute
    if end <= start:
        return minute >= start or minute < end
    return start <= minute < end
