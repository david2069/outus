"""Import a ``franklinwh-bridge/tariff-profile`` v1 file as an OUTUS plan.

A v1 profile is one tariff: seasons of TOU blocks naming a time period with buy/sell
rates, a tariff-wide default rate (a number or a tier ladder), optional demand, export
bonus and export charge windows, and fixed charges. It becomes a plan with a ``general``
tariff (buy) and, when anything is paid or charged for export, an ``export`` tariff. The
original profile is kept under ``x-tariff-profile-v1`` so nothing is lost.
"""
from __future__ import annotations

import copy
from typing import Any

PROFILE_TYPE = "franklinwh-bridge/tariff-profile"
_FIXED = {"daily": ("per_day", 1.0), "weekly": ("per_day", 1 / 7.0),
          "monthly": ("per_month", 1.0), "quarterly": ("per_month", 1 / 3.0),
          "annual": ("per_year", 1.0)}


def _days(days: list | None, out: dict) -> None:
    """v1 weekday numbers (Monday 0) → OUTUS day types where exact, else kept as ``days``."""
    d = set(days or [])
    if not d or d == set(range(7)):
        return
    if d == {0, 1, 2, 3, 4}:
        out["day_types"] = ["weekday"]
    elif d == {5, 6}:
        out["day_types"] = ["weekend"]
    else:
        out["days"] = sorted(d)


def _window(w: dict | None) -> dict | None:
    if not isinstance(w, dict) or not w:
        return None
    out = {k: w[k] for k in ("months", "start", "end") if w.get(k)}
    _days(w.get("days"), out)
    return out or None


def _tou(seasons: list, side: str) -> list[dict]:
    rates = []
    for s in seasons or []:
        periods = s.get("time_periods") or s.get("waves") or {}
        for b in s.get("blocks") or []:
            band = b.get("time_period") or b.get("wave")
            rate = (periods.get(band) or {}).get(side)
            if not isinstance(rate, (int, float)):
                continue
            win = {"start": b.get("start"), "end": b.get("end")}
            if s.get("months"):
                win["months"] = list(s["months"])
            _days(b.get("days"), win)
            rates.append({"window": win, "band": band, "rate": float(rate)})
    return rates


def _flat_or_tiers(value: Any) -> tuple[float | None, list[dict] | None]:
    if isinstance(value, (int, float)):
        return float(value), None
    if isinstance(value, list) and value:
        tiers = [{"up_to": t.get("up_to_kwh"), "rate": float(t["rate"])}
                 for t in value if isinstance(t, dict) and isinstance(t.get("rate"), (int, float))]
        return None, tiers or None
    return None, None


def from_tariff_profile(doc: dict) -> dict:
    """A v1 tariff-profile document (or its inner ``profile``) → an OUTUS plan."""
    p = doc.get("profile", doc) if doc.get("type") == PROFILE_TYPE else doc
    pr = p.get("pricing") or {}
    seasons = pr.get("seasons") or []
    default = pr.get("default_rate") or {}
    general: list[dict] = []
    export: list[dict] = []

    buy_flat, buy_tiers = _flat_or_tiers(default.get("buy"))
    tou_buy = _tou(seasons, "buy")
    if tou_buy or buy_flat is not None:
        rates = tou_buy + ([{"rate": buy_flat}] if buy_flat is not None else [])
        general.append({"id": "energy", "label": "Energy", "class": "interval", "basis": "per_unit",
                        "unit": "kWh", "rates": rates})
    if buy_tiers:
        general.append({"id": "energy_tiers", "label": "Energy (tiered)", "class": "period",
                        "basis": "tier", "unit": "kWh", "tiers": buy_tiers})

    if pr.get("demand_rate") and _window(p.get("demand_window")):
        per = "per_month" if pr.get("demand_charge_basis") == "per_kw_month" else "per_day"
        general.append({"id": "demand", "label": "Peak demand", "class": "period", "basis": "demand",
                        "rate": float(pr["demand_rate"]), "unit": "kW",
                        "window": _window(p.get("demand_window")),
                        "demand": {"method": "monthly_max",
                                   "interval_min": int(pr.get("demand_interval_min") or 30),
                                   "unit": "kW", "frequency": per}})

    sell_flat, _ = _flat_or_tiers(default.get("sell"))
    tou_sell = _tou(seasons, "sell")
    if tou_sell or sell_flat is not None:
        rates = tou_sell + ([{"rate": sell_flat}] if sell_flat is not None else [])
        export.append({"id": "feed_in", "label": "Feed-in credit", "class": "interval",
                       "basis": "per_unit", "direction": "export", "effect": "credit", "unit": "kWh",
                       "rates": rates})
    if pr.get("export_bonus_rate") and _window(p.get("bonus_window")):
        export.append({"id": "bonus", "label": "Export bonus", "class": "interval", "basis": "per_unit",
                       "direction": "export", "effect": "credit", "unit": "kWh",
                       "window": _window(p.get("bonus_window")), "rate": float(pr["export_bonus_rate"])})
    ec = pr.get("export_charge") or {}
    if ec.get("rate"):
        export.append({"id": "export_charge", "label": "Export charge", "class": "period",
                       "basis": "excess_over_free_band", "direction": "export", "unit": "kWh",
                       "rate": float(ec["rate"]), "window": _window(ec.get("window")),
                       "free_band": {"quantity": float(ec.get("free_kwh_per_day") or 0.0), "per": "day"}})

    charges = []
    for i, f in enumerate(pr.get("fixed_charges") or []):
        if not isinstance(f, dict) or not isinstance(f.get("rate"), (int, float)):
            continue
        basis, k = _FIXED.get(f.get("frequency") or "daily", ("per_day", 1.0))
        charges.append({"id": f"fixed_{i + 1}", "label": f.get("description") or f.get("type") or "Fixed charge",
                        "class": "period", "basis": basis,
                        "rate": round(float(f["rate"]) * k * (1 + float(f.get("tax_rate") or 0.0)), 6),
                        "unit": basis.removeprefix("per_")})

    tariffs = []
    if general:
        tariffs.append({"id": "general", "name": "General", "applies_to": "general",
                        "price_source": {"kind": "static"}, "charges": general})
    if export:
        tariffs.append({"id": "export", "name": "Export", "applies_to": "export", "charges": export})
    plan: dict[str, Any] = {
        "type": "outus/plan", "version": 1,
        "name": p.get("name") or "Imported plan",
        "retailer": {k: v for k, v in (("name", p.get("retailer")), ("network", p.get("network")),
                                       ("country", p.get("country"))) if v},
        "currency": {"AU": "AUD", "US": "USD", "NZ": "NZD", "GB": "GBP"}.get(p.get("country") or "", "AUD"),
        "billing": {"cycle": "monthly", "cycle_day": max(1, min(28, int(pr.get("billing_cycle_day") or 1)))},
        "tax": {"rate": 0.10 if p.get("country") == "AU" else 0.0, "rates_include_tax": True},
        "export_compensation": "feed_in",
        "charges": charges,
        "tariffs": tariffs,
        "x-tariff-profile-v1": copy.deepcopy(p),
    }
    for k in ("timezone", "effective_start", "effective_end"):
        if p.get(k):
            plan[k] = p[k]
    return plan
