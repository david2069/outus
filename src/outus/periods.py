"""Billing periods: where the period containing a moment starts and ends."""
from __future__ import annotations

import calendar
import datetime as dt

MONTHS_PER_CYCLE = {"monthly": 1, "bimonthly": 2, "quarterly": 3}


def _on_day(year: int, month: int, day: int, like: dt.datetime) -> dt.datetime:
    return like.replace(year=year, month=month, day=min(day, calendar.monthrange(year, month)[1]),
                        hour=0, minute=0, second=0, microsecond=0)


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    i = year * 12 + (month - 1) + n
    return i // 12, i % 12 + 1


def bounds(local: dt.datetime, cycle: str = "monthly", cycle_day: int = 1,
           anchor_month: int = 1) -> tuple[dt.datetime, dt.datetime]:
    """(start, end) of the billing period containing ``local`` (site local time).

    Periods start on ``cycle_day`` (clamped to the month's length). Bimonthly and
    quarterly periods are counted from ``anchor_month``.
    """
    step = MONTHS_PER_CYCLE.get(cycle, 1)
    day = max(1, min(28, int(cycle_day or 1)))
    # The latest cycle-day on or before `local`, in a month on the cycle's grid.
    y, m = local.year, local.month
    for _ in range(step + 1):
        if (m - anchor_month) % step == 0:
            start = _on_day(y, m, day, local)
            if start <= local:
                break
        y, m = _add_months(y, m, -1)
    else:                                                       # pragma: no cover
        raise ValueError("no period start found")
    ey, em = _add_months(start.year, start.month, step)
    return start, _on_day(ey, em, day, local)


def days(start: dt.datetime, end: dt.datetime) -> float:
    """Length in days (a DST change makes it fractional; bills count whole days)."""
    return round((end - start).total_seconds() / 86400.0)
