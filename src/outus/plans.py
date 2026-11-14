"""Checks on OUTUS plans that a JSON Schema can't express."""
from __future__ import annotations

import datetime as dt

from .billing import INTERVAL_BASES
from .windows import hhmm

BANDS = ("super_off_peak", "off_peak", "mid_peak", "on_peak")
PERIOD_BASES = {"per_day", "per_month", "per_year", "demand", "excess_over_free_band", "tier",
                "minimum_bill", "true_up", "percent_of_bill"}


def _date(v):
    return dt.date.fromisoformat(v) if v else None


def overlaps(plans: list[dict]) -> list[str]:
    """Plans on one meter must not overlap (blank end = open-ended)."""
    issues = []
    spans = sorted(((_date(p.get("effective_start")) or dt.date.min,
                     _date(p.get("effective_end")) or dt.date.max, p.get("name") or p.get("id"))
                    for p in plans), key=lambda x: x[0])
    for (s1, e1, n1), (s2, _e2, n2) in zip(spans, spans[1:]):
        if s2 <= e1:
            issues.append(f"{n1} and {n2} overlap from {s2.isoformat()}")
    return issues


def check(plan: dict) -> list[str]:
    """Problems that would price wrongly. Empty = fine."""
    issues = []
    if not plan.get("tariffs"):
        issues.append("the plan has no tariffs")
    s, e = _date(plan.get("effective_start")), _date(plan.get("effective_end"))
    if s and e and e < s:
        issues.append("effective_end is before effective_start")
    for t in plan.get("tariffs") or []:
        tn = t.get("name") or t.get("id")
        for c in t.get("charges") or []:
            cn = f"{tn} › {c.get('label') or c.get('id')}"
            cls, basis = c.get("class"), c.get("basis")
            if cls == "interval" and basis not in INTERVAL_BASES:
                issues.append(f"{cn}: {basis} is a period basis, not interval")
            if cls == "period" and basis not in PERIOD_BASES:
                issues.append(f"{cn}: {basis} is an interval basis, not period")
            if basis in ("series", "series_plus_adder") and (t.get("price_source") or {}).get("kind") != "series":
                issues.append(f"{cn}: priced from a series, but the tariff has no series price source")
            for r in c.get("rates") or []:
                if r.get("band") and r["band"] not in BANDS:
                    issues.append(f"{cn}: unknown band {r['band']}")
                w = r.get("window") or {}
                for k in ("start", "end"):
                    if w.get(k) is not None and hhmm(w[k]) is None:
                        issues.append(f"{cn}: bad time {w[k]}")
            if basis == "per_unit" and c.get("rates") and not any(not r.get("window") for r in c["rates"]):
                issues.append(f"{cn}: no catch-all rate; times outside its windows go unpriced")
    return issues
