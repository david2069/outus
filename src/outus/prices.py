"""Dynamic prices (OUTUS price series): the price at an interval's start holds for its
duration, and a later kind replaces an earlier one for the same start."""
from __future__ import annotations

import bisect
import datetime as dt
from typing import Any

RANK = {"forecast": 0, "estimate": 1, "confirmed": 2, "actual": 3}


def _epoch(v: Any) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    return int(dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())


class PriceBook:
    """One source's price intervals, keyed by start (UTC epoch seconds)."""

    def __init__(self, provider: str = "", region: str = "") -> None:
        self.provider, self.region = provider, region
        self._by_start: dict[int, dict] = {}
        self._starts: list[int] = []

    def add(self, intervals: list[dict]) -> list[int]:
        """Merge intervals; returns the starts whose price changed (to re-price)."""
        changed = []
        for iv in intervals:
            start = _epoch(iv["start"])
            old = self._by_start.get(start)
            if old is not None and RANK.get(iv.get("kind"), 0) < RANK.get(old.get("kind"), 0):
                continue
            new = dict(iv, start=start)
            if old is None:
                bisect.insort(self._starts, start)
            if old is None or (old.get("import"), old.get("export"), old.get("kind")) != (
                    new.get("import"), new.get("export"), new.get("kind")):
                changed.append(start)
            self._by_start[start] = new
        return changed

    def at(self, ts: float) -> dict | None:
        """The price in force at ``ts``. Past the last interval, the last known price is
        carried forward and marked ``estimate``; None before the first."""
        i = bisect.bisect_right(self._starts, int(ts)) - 1
        if i < 0:
            return None
        iv = self._by_start[self._starts[i]]
        if ts < iv["start"] + int(iv.get("duration_s") or 300):
            return iv
        return dict(iv, kind="estimate", carried=True)

    @classmethod
    def from_document(cls, doc: dict) -> PriceBook:
        src = doc.get("source") or {}
        book = cls(src.get("provider", ""), src.get("region", ""))
        book.add(doc.get("intervals") or [])
        return book
