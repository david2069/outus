"""Bills from an OUTUS plan and the ledger.

Interval charges are priced per ledger interval at the rate in force at its start;
period charges are worked out from the period's ledger. ``bill`` returns an OUTUS bill
whose line items carry their inputs and formula. For an open period it is
``provisional``: period charges are prorated to the elapsed days, and ``progress`` holds
the projection to the period's end.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any
from zoneinfo import ZoneInfo

from . import periods
from .prices import PriceBook
from .windows import HolidayCheck, day_type, in_window

#: Which ledger channel each tariff reads.
CHANNEL = {"general": "general", "export": "general", "controlled_load": "controlled_load",
           "ev": "ev", "rider": "general"}
INTERVAL_BASES = {"per_unit", "series", "series_plus_adder", "value_table"}
SUPPORTED_DEMAND = {"monthly_max", "top_n_avg", "daily_excess"}


def plan_in_force(plans: list[dict], day: dt.date) -> dict | None:
    """The plan whose dates cover ``day`` (blank end = still in force)."""
    for p in plans:
        start = p.get("effective_start")
        end = p.get("effective_end")
        if start and day < dt.date.fromisoformat(start):
            continue
        if end and day > dt.date.fromisoformat(end):
            continue
        return p
    return None


def _direction(tariff: dict, charge: dict) -> str:
    return charge.get("direction") or ("export" if tariff.get("applies_to") == "export" else "import")


def _sign(charge: dict) -> float:
    return -1.0 if charge.get("effect") == "credit" else 1.0


def rate_at(charge: dict, local: dt.datetime, is_holiday: HolidayCheck | None = None
            ) -> tuple[float | None, str | None]:
    """A static charge's (rate, band) at ``local``: its rate table's first matching
    entry, else its flat ``rate``."""
    for entry in charge.get("rates") or []:
        if in_window(entry.get("window"), local, is_holiday):
            return entry.get("rate"), entry.get("band")
    if "rates" in charge and charge.get("rate") is None:
        return None, None
    return charge.get("rate"), None


def _value_table(charge: dict, local: dt.datetime) -> float | None:
    month = (charge.get("value_table") or {}).get(str(local.month)) or {}
    row = month.get("weekend" if local.weekday() >= 5 else "weekday")
    return row[local.hour] if row and len(row) == 24 else None


def _interval_rate(tariff: dict, charge: dict, local: dt.datetime, ts: float,
                   prices: PriceBook | None, is_holiday: HolidayCheck | None
                   ) -> tuple[float | None, str | None, str]:
    """(rate, band, price kind) for one interval charge."""
    basis = charge["basis"]
    if basis == "value_table":
        return _value_table(charge, local), None, "static"
    if basis in ("series", "series_plus_adder"):
        p = prices.at(ts) if prices is not None else None
        if p is None:
            return None, None, "missing"
        side = p.get("export") if _direction(tariff, charge) == "export" else p.get("import")
        if side is None:
            return None, None, "missing"
        adder = 0.0
        band = p.get("band")
        if basis == "series_plus_adder":
            a, band2 = rate_at(charge, local, is_holiday)
            adder, band = (a or 0.0), (band2 or band)
        return side + adder, band, p.get("kind", "actual")
    rate, band = rate_at(charge, local, is_holiday)
    return rate, band, "static"


def _local(ts: float, tz: ZoneInfo) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, tz)


def _money(v: float) -> float:
    return round(v + 0.0, 2)


def _fmt(v: float, dp: int = 2) -> str:
    return f"{v:,.{dp}f}"


def _tariffs(plan: dict) -> list[dict]:
    return [t for t in plan.get("tariffs") or [] if isinstance(t, dict)]


def _qty(iv: dict, direction: str) -> float:
    return float(iv.get("quantity_out" if direction == "export" else "quantity_in") or 0.0)


def _interval_lines(plan: dict, ledger: dict[str, list[dict]], tz: ZoneInfo,
                    prices: PriceBook | None, is_holiday: HolidayCheck | None) -> list[dict]:
    lines = []
    for t in _tariffs(plan):
        chan = ledger.get(CHANNEL.get(t.get("applies_to"), "general")) or []
        for c in t.get("charges") or []:
            if c.get("class") != "interval" or c.get("basis") not in INTERVAL_BASES:
                continue
            d = _direction(t, c)
            qty = amount = unpriced = 0.0
            bands: dict[str, float] = defaultdict(float)
            rates_seen, n, kinds = set(), 0, set()
            for iv in chan:
                q = _qty(iv, d)
                if q <= 0:
                    continue
                local = _local(iv["start"], tz)
                if not in_window(c.get("window"), local, is_holiday):
                    continue
                rate, band, kind = _interval_rate(t, c, local, iv["start"], prices, is_holiday)
                if rate is None:
                    unpriced += q
                    continue
                qty += q
                amount += q * rate
                n += 1
                rates_seen.add(round(rate, 6))
                kinds.add(kind)
                if band:
                    bands[band] += q
            if qty <= 0 and unpriced <= 0:
                continue
            unit = c.get("unit") or "kWh"
            one_rate = next(iter(rates_seen)) if len(rates_seen) == 1 else None
            if one_rate is not None:
                formula = f"{_fmt(qty, 3)} {unit} × ${one_rate}"
            else:
                what = "prices" if c["basis"] != "per_unit" else "TOU rates"
                formula = f"{_fmt(qty, 3)} {unit} × {what} ({n:,} intervals)"
            inputs: dict[str, Any] = {f"{b}_{unit}": round(v, 3) for b, v in bands.items()}
            if unpriced:
                inputs["unpriced_" + unit] = round(unpriced, 3)
            if kinds - {"static"}:
                inputs["price_kinds"] = sorted(kinds)
            lines.append({"tariff_id": t.get("id"), "charge_id": c.get("id"),
                          "label": c.get("label") or c.get("id"), "quantity": round(qty, 3),
                          "unit": unit, **({"rate": one_rate} if one_rate is not None else {}),
                          "amount": _money(_sign(c) * amount), "formula": formula,
                          "inputs": inputs, "class": "interval"})
    return lines


def _demand(t: dict, c: dict, chan: list[dict], tz: ZoneInfo,
            is_holiday: HolidayCheck | None) -> tuple[float, dict]:
    spec = c.get("demand") or {}
    step = int(spec.get("interval_min") or 30) * 60
    buckets: dict[int, float] = defaultdict(float)
    for iv in chan:
        start = int(iv["start"]) // step * step
        if in_window(c.get("window"), _local(start, tz), is_holiday):
            buckets[start] += float(iv.get("quantity_in") or 0.0)
    kw = {s: q * 3600.0 / step for s, q in buckets.items()}
    if spec.get("unit") == "kVA" and spec.get("power_factor"):
        kw = {s: v / float(spec["power_factor"]) for s, v in kw.items()}
    method = spec.get("method") or "monthly_max"
    inputs: dict[str, Any] = {"method": method}
    if not kw:
        return 0.0, inputs
    if method == "top_n_avg":
        n = int(spec.get("n") or 1)
        ranked = sorted(kw.items(), key=lambda x: -x[1])
        if spec.get("distinct_days"):
            seen, picked = set(), []
            for s, v in ranked:
                day = _local(s, tz).date()
                if day not in seen:
                    seen.add(day)
                    picked.append((s, v))
            ranked = picked
        top = ranked[:n]
        value = sum(v for _, v in top) / len(top)
        inputs["peaks"] = [{"at": _local(s, tz).isoformat(), "kw": round(v, 3)} for s, v in top]
    elif method == "daily_excess":
        by_day: dict[dt.date, float] = defaultdict(float)
        for s, v in kw.items():
            d = _local(s, tz).date()
            by_day[d] = max(by_day[d], v)
        thr = float(spec.get("threshold") or 0.0)
        value = sum(max(0.0, v - thr) for v in by_day.values())
        inputs["threshold"] = thr
    else:
        s, value = max(kw.items(), key=lambda x: x[1])
        inputs["peak_at"] = _local(s, tz).isoformat()
    value = max(value, float(spec.get("min") or 0.0))
    inputs["peak"] = round(value, 3)
    return value, inputs


def _period_lines(plan: dict, ledger: dict[str, list[dict]], tz: ZoneInfo, start: dt.datetime,
                  end: dt.datetime, used_days: float, period_days: float,
                  is_holiday: HolidayCheck | None) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """Period charges, except those that need the subtotal (minimum bill, percent)."""
    lines, deferred = [], []
    cycle = (plan.get("billing") or {}).get("cycle", "monthly")
    months = periods.MONTHS_PER_CYCLE.get(cycle, 1)
    frac = used_days / period_days if period_days else 0.0
    owners = [(None, c) for c in plan.get("charges") or []] + [
        (t, c) for t in _tariffs(plan) for c in t.get("charges") or []]
    for t, c in owners:
        if c.get("class") != "period":
            continue
        basis, rate = c.get("basis"), float(c.get("rate") or 0.0)
        tid = t.get("id") if t else None
        base = {"tariff_id": tid, "charge_id": c.get("id"), "label": c.get("label") or c.get("id"),
                "class": "period"}
        chan = ledger.get(CHANNEL.get((t or {}).get("applies_to"), "general")) or []
        if basis == "per_day":
            lines.append({**base, "quantity": round(used_days, 3), "unit": "day", "rate": rate,
                          "amount": _money(_sign(c) * rate * used_days),
                          "formula": f"{_fmt(used_days, 0 if used_days == int(used_days) else 2)} days × ${rate}"})
        elif basis == "per_month":
            q = months * frac
            lines.append({**base, "quantity": round(q, 4), "unit": "month", "rate": rate,
                          "amount": _money(_sign(c) * rate * q), "formula": f"{_fmt(q, 2)} months × ${rate}"})
        elif basis == "per_year":
            q = used_days / 365.0
            lines.append({**base, "quantity": round(q, 4), "unit": "year", "rate": rate,
                          "amount": _money(_sign(c) * rate * q), "formula": f"{used_days:g}/365 years × ${rate}"})
        elif basis == "demand":
            spec = c.get("demand") or {}
            method = spec.get("method") or "monthly_max"
            if method not in SUPPORTED_DEMAND:
                lines.append({**base, "amount": 0.0, "formula": f"{method}: not supported yet",
                              "inputs": {"unsupported": method}})
                continue
            peak, inputs = _demand(t or {}, c, chan, tz, is_holiday)
            per = spec.get("frequency", "per_month")
            mult, how = (used_days, f" × {used_days:g} days") if per == "per_day" else (
                months * frac, f" × {_fmt(months * frac, 2)} months" if months * frac != 1 else "")
            unit = spec.get("unit", "kW")
            at = inputs.get("peak_at")
            when = f" ({_local_short(at)})" if at else ""
            lines.append({**base, "quantity": round(peak, 3), "unit": unit, "rate": rate,
                          "amount": _money(_sign(c) * peak * rate * mult),
                          "formula": f"peak {_fmt(peak, 2)} {unit}{when} × ${rate}{how}", "inputs": inputs})
        elif basis == "excess_over_free_band":
            fb = c.get("free_band") or {}
            free = float(fb.get("quantity") or 0.0)
            d = _direction(t or {}, c)
            by_day: dict[dt.date, float] = defaultdict(float)
            for iv in chan:
                local = _local(iv["start"], tz)
                if in_window(c.get("window"), local, is_holiday):
                    by_day[local.date()] += _qty(iv, d)
            total = sum(by_day.values())
            if fb.get("per") == "day":
                excess = sum(max(0.0, v - free) for v in by_day.values())
                today = max(by_day) if by_day else None
                left = max(0.0, free - by_day[today]) if today else free
                desc = f"{_fmt(free, 0)} kWh/day free"
            else:
                allow = free if fb.get("per") == "period" else free * used_days / 365.0
                excess, left = max(0.0, total - allow), max(0.0, allow - total)
                desc = f"{_fmt(allow, 1)} kWh free"
            lines.append({**base, "quantity": round(excess, 3), "unit": c.get("unit") or "kWh",
                          "rate": rate, "amount": _money(_sign(c) * excess * rate),
                          "formula": f"{_fmt(excess, 3)} kWh above {desc} × ${rate}",
                          "inputs": {"in_window": round(total, 3), "free_left": round(left, 3)}})
        elif basis == "tier":
            used = sum(_qty(iv, _direction(t or {}, c)) for iv in chan)
            lines.append({**base, **_tier(c, used, start, used_days)})
        elif basis in ("minimum_bill", "percent_of_bill"):
            deferred.append((base, c))
        # true_up is an annual settlement: informational, not a line in a period bill.
    return lines, deferred


def _local_short(iso: str) -> str:
    d = dt.datetime.fromisoformat(iso)
    return f"{d.day} {d:%b %H:%M}"


def _tier(c: dict, used: float, start: dt.datetime, used_days: float) -> dict:
    """Tiered quantity over the period. With a ``baseline`` the first tier's allowance is
    the baseline kWh/day for the period's season × days."""
    tiers = [x for x in c.get("tiers") or [] if isinstance(x, dict)]
    allowance = None
    for b in c.get("baseline") or []:
        if not b.get("months") or start.month in b["months"]:
            allowance = float(b["kwh_per_day"]) * used_days
            break
    amount, left, prev, parts = 0.0, used, 0.0, []
    for i, tier in enumerate(tiers):
        cap = allowance if (i == 0 and allowance is not None) else tier.get("up_to")
        span = left if cap is None else max(0.0, min(left, float(cap) - prev))
        if span > 0:
            amount += span * float(tier["rate"])
            parts.append(f"{_fmt(span, 1)} × ${tier['rate']}")
        left -= span
        if cap is not None:
            prev = float(cap)
    inputs = {"used": round(used, 3)}
    if allowance is not None:
        inputs["baseline_allowance"] = round(allowance, 3)
    return {"quantity": round(used, 3), "unit": c.get("unit") or "kWh",
            "amount": _money(_sign(c) * amount), "formula": " + ".join(parts) or "0",
            "inputs": inputs}


def bill(plan: dict, ledger: dict[str, list[dict]], start: dt.datetime, end: dt.datetime,
         now: dt.datetime | None = None, prices: PriceBook | None = None,
         is_holiday: HolidayCheck | None = None) -> dict:
    """An OUTUS bill for ``plan`` over [start, end) from the ledger intervals
    (``{channel: [interval]}``, ``start`` in epoch seconds). ``now`` before ``end`` makes
    it provisional, with period charges to date and a projection."""
    tz = ZoneInfo(plan.get("timezone") or "UTC")
    start, end = start.astimezone(tz), end.astimezone(tz)
    s_ts, e_ts = start.timestamp(), end.timestamp()
    led = {ch: [iv for iv in ivs if s_ts <= iv["start"] < e_ts] for ch, ivs in ledger.items()}
    period_days = periods.days(start, end)
    final = now is None or now >= end
    used_days = period_days if final else max(0.0, round((now - start).total_seconds() / 86400.0, 3))
    lines = _interval_lines(plan, led, tz, prices, is_holiday)
    plines, deferred = _period_lines(plan, led, tz, start, end, used_days, period_days, is_holiday)
    lines += plines
    subtotal = sum(x["amount"] for x in lines)
    for base, c in deferred:
        if c.get("basis") == "minimum_bill":
            floor = float(c.get("amount") or 0.0) * (used_days / period_days if period_days else 0)
            top_up = max(0.0, floor - subtotal)
            if top_up:
                lines.append({**base, "amount": _money(top_up),
                              "formula": f"minimum ${_fmt(floor)} − charges ${_fmt(subtotal)}"})
        else:
            r = float(c.get("rate") or 0.0)
            lines.append({**base, "rate": r, "amount": _money(_sign(c) * r * subtotal),
                          "formula": f"{r:.2%} × ${_fmt(subtotal)}"})
    net = _money(sum(x["amount"] for x in lines))
    tax_cfg = plan.get("tax") or {}
    rate = float(tax_cfg.get("rate") or 0.0)
    if tax_cfg.get("rates_include_tax", True):
        tax = _money(net * rate / (1 + rate)) if rate else 0.0
    else:
        tax = _money(net * rate)
        net = _money(net + tax)
    for x in lines:
        x.pop("class", None)
    out = {
        "type": "outus/bill", "version": 1,
        "plan_id": plan.get("id"), "plan_name": plan.get("name"),
        "retailer": (plan.get("retailer") or {}).get("name"),
        "currency": plan.get("currency"),
        "period_start": start.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "period_end": end.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "calculated", "status": "final" if final else "provisional",
        "line_items": lines, "tax": tax, "net_total": net,
    }
    if plan.get("meter"):
        out["meter"] = plan["meter"]
    if plan.get("account_number"):
        out["account_number"] = plan["account_number"]
    if not final:
        out["progress"] = _progress(lines, used_days, period_days, rate, tax_cfg)
    return {k: v for k, v in out.items() if v is not None}


def _progress(lines: list[dict], used_days: float, period_days: float, tax_rate: float,
              tax_cfg: dict) -> dict:
    """Day n of N and a straight-line projection of every line to the period's end."""
    scale = period_days / used_days if used_days else 0.0
    projected = sum(x["amount"] for x in lines) * scale
    if not tax_cfg.get("rates_include_tax", True):
        projected *= 1 + tax_rate
    return {"days_elapsed": used_days, "days": period_days, "projected_total": _money(projected)}


def now_rates(plan: dict, at: dt.datetime, prices: PriceBook | None = None,
              is_holiday: HolidayCheck | None = None) -> list[dict]:
    """Each interval charge's rate and band now: the live inputs of Bill detail."""
    tz = ZoneInfo(plan.get("timezone") or "UTC")
    local = at.astimezone(tz)
    out = []
    for t in _tariffs(plan):
        for c in t.get("charges") or []:
            if c.get("class") != "interval" or not in_window(c.get("window"), local, is_holiday):
                continue
            rate, band, kind = _interval_rate(t, c, local, local.timestamp(), prices, is_holiday)
            out.append({"tariff_id": t.get("id"), "charge_id": c.get("id"),
                        "label": c.get("label") or c.get("id"), "rate": rate, "band": band,
                        "kind": kind, "day_type": day_type(local, None, is_holiday)})
    return out
