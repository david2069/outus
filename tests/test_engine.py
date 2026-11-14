"""The reference implementation: windows, periods, ledger, prices, bills, v1 import, checks."""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from outus import billing, ledger, periods, plans, profile_v1, setup
from outus.prices import PriceBook
from outus.windows import in_window

ROOT = Path(__file__).resolve().parents[1]
SYD = ZoneInfo("Australia/Sydney")
AU = json.loads((ROOT / "examples/electricity/au-tou-plan.json").read_text())
US = json.loads((ROOT / "examples/electricity/us-tou-net-billing-plan.json").read_text())


def loc(*a):
    return dt.datetime(*a, tzinfo=SYD)


def ivs(local_start, n, kwh_in=0.0, kwh_out=0.0, step_min=5):
    """n ledger intervals from a local start, each with the given kWh."""
    out = []
    for i in range(n):
        t = local_start + dt.timedelta(minutes=step_min * i)
        out.append({"start": int(t.timestamp()), "duration_s": 300, "quantity_in": kwh_in,
                    "quantity_out": kwh_out, "peak_rate": kwh_in * 12})
    return out


# windows / periods
def test_window_wraps_midnight_and_day_types():
    w = {"start": "22:00", "end": "07:00"}
    assert in_window(w, loc(2026, 11, 16, 23, 0)) and in_window(w, loc(2026, 11, 16, 6, 59))
    assert not in_window(w, loc(2026, 11, 16, 7, 0))
    wk = {"day_types": ["weekday"]}
    assert in_window(wk, loc(2026, 11, 16, 12)) and not in_window(wk, loc(2026, 11, 15, 12))
    hol = lambda d, r: d == dt.date(2026, 12, 25)                     # noqa: E731
    assert not in_window(wk, loc(2026, 12, 25, 12), hol)               # a holiday is its own day type


def test_periods_monthly_and_quarterly():
    s, e = periods.bounds(loc(2026, 11, 15, 9), "monthly", 12)
    assert (s.day, s.month, e.day, e.month) == (12, 11, 12, 12)
    s, e = periods.bounds(loc(2026, 11, 3, 9), "monthly", 12)
    assert (s.month, e.month) == (10, 11)
    s, e = periods.bounds(loc(2026, 11, 15), "quarterly", 1, anchor_month=1)
    assert (s.month, e.month, e.year) == (10, 1, 2027)


# ledger
def test_ledger_sums_devices_and_closes_five_minute_intervals():
    st = ledger.new_state("m1")
    t0 = loc(2026, 11, 16, 12, 0).timestamp()
    closed = []
    for i in range(0, 601, 10):                                         # 10 min of readings
        closed += ledger.add_reading(st, "a", t0 + i, 1000.0)
        closed += ledger.add_reading(st, "b", t0 + i + 1, 2000.0)
    assert [c["start"] for c in closed] == [int(t0), int(t0) + 300]
    assert closed[0]["quantity_in"] == pytest.approx(0.25, abs=0.002)   # 3 kW × 5 min
    assert closed[0]["peak_rate"] == pytest.approx(3.0, abs=0.03)


def test_ledger_leaves_out_a_silent_device_and_records_export():
    st = ledger.new_state("m1")
    t0 = loc(2026, 11, 16, 12, 0).timestamp()
    ledger.add_reading(st, "b", t0, 5000.0)                             # b reports once
    closed = []
    for i in range(0, 1201, 10):
        closed += ledger.add_reading(st, "a", t0 + i, -1200.0)
    last = closed[-1]
    assert last["quantity_in"] == 0 and last["quantity_out"] == pytest.approx(0.1, abs=0.002)


# prices
def test_price_book_ranks_kinds_and_carries_forward():
    book = PriceBook()
    t = int(loc(2026, 11, 16, 12).timestamp())
    book.add([{"start": t, "duration_s": 300, "import": 0.30, "kind": "forecast"}])
    assert book.add([{"start": t, "duration_s": 300, "import": 0.10, "kind": "confirmed"}]) == [t]
    assert book.add([{"start": t, "duration_s": 300, "import": 0.99, "kind": "estimate"}]) == []
    assert book.at(t + 10)["import"] == 0.10
    assert book.at(t + 900)["kind"] == "estimate"                       # carried forward
    assert book.at(t - 1) is None


# bills
def _au_month():
    s, e = loc(2026, 11, 1), loc(2026, 12, 1)
    gen = ivs(loc(2026, 11, 16, 17, 30), 6, kwh_in=0.35)                # Monday on-peak, 4.2 kW for 30 min
    gen += ivs(loc(2026, 11, 17, 11, 0), 24, kwh_out=0.25)              # 6 kWh exported 11:00–13:00
    gen += ivs(loc(2026, 11, 18, 10, 0), 60, kwh_out=0.25)              # 15 kWh 10:00–15:00: 5 above the free 10
    cl = ivs(loc(2026, 11, 17, 23, 0), 12, kwh_in=0.2)                  # 2.4 kWh controlled load
    return s, e, {"general": gen, "controlled_load": cl}


def _line(b, cid):
    return next(x for x in b["line_items"] if x["charge_id"] == cid)


def test_au_bill_line_items_and_formulas():
    s, e, led = _au_month()
    b = billing.bill(AU, led, s, e)
    assert b["status"] == "final"
    assert _line(b, "energy")["amount"] == pytest.approx(round(2.1 * 0.52, 2))
    assert _line(b, "energy")["inputs"] == {"on_peak_kWh": 2.1}
    d = _line(b, "demand")
    assert d["quantity"] == pytest.approx(4.2) and d["amount"] == pytest.approx(round(4.2 * 0.45 * 30, 2))
    assert "16 Nov 17:30" in d["formula"]
    assert _line(b, "cl_energy")["amount"] == pytest.approx(round(2.4 * 0.18, 2))
    assert _line(b, "fit")["amount"] == pytest.approx(-round(21 * 0.05, 2))
    x = _line(b, "export_charge")
    assert x["quantity"] == pytest.approx(5.0) and x["amount"] == pytest.approx(round(5 * 0.012, 2))
    assert _line(b, "supply")["formula"] == "30 days × $1.1"
    assert b["net_total"] == pytest.approx(round(sum(i["amount"] for i in b["line_items"]), 2))
    assert b["tax"] == pytest.approx(round(b["net_total"] / 11, 2))


def test_open_period_is_provisional_and_projects():
    s, e, led = _au_month()
    b = billing.bill(AU, led, s, e, now=loc(2026, 11, 16, 12, 0))
    assert b["status"] == "provisional"
    assert _line(b, "supply")["quantity"] == pytest.approx(15.5, abs=0.01)
    p = b["progress"]
    assert p["days"] == 30 and p["projected_total"] > b["net_total"]


def test_minimum_bill_tops_up():
    s, e = dt.datetime(2026, 1, 12, tzinfo=ZoneInfo("America/Los_Angeles")), dt.datetime(2026, 2, 12, tzinfo=ZoneInfo("America/Los_Angeles"))
    plan = json.loads(json.dumps(US))
    plan["charges"] = [c for c in plan["charges"] if c["id"] == "minimum"]
    plan["tariffs"] = plan["tariffs"][:1]
    b = billing.bill(plan, {"general": []}, s, e)
    assert _line(b, "minimum")["amount"] == pytest.approx(10.0)


def test_us_baseline_credit_and_export_value_table():
    la = ZoneInfo("America/Los_Angeles")
    s, e = dt.datetime(2026, 9, 12, tzinfo=la), dt.datetime(2026, 10, 12, tzinfo=la)
    gen = []
    for i in range(12):                                                  # 1 kWh export at 18:00–19:00, a weekday
        t = dt.datetime(2026, 9, 16, 18, 0, tzinfo=la) + dt.timedelta(minutes=5 * i)
        gen.append({"start": int(t.timestamp()), "duration_s": 300, "quantity_in": 0.0,
                    "quantity_out": 1 / 12})
    for i in range(12 * 24 * 30):                                        # 0.5 kW all month
        t = s + dt.timedelta(minutes=5 * i)
        gen.append({"start": int(t.timestamp()), "duration_s": 300, "quantity_in": 0.5 / 12,
                    "quantity_out": 0.0})
    b = billing.bill(US, {"general": gen}, s, e)
    acc = _line(b, "acc")
    assert acc["amount"] == pytest.approx(-2.10) and acc["rate"] == 2.1
    base = _line(b, "baseline_credit")
    assert base["inputs"]["baseline_allowance"] == pytest.approx(12.4 * 30)
    assert base["amount"] == pytest.approx(-round(360 * 0.10, 2))       # 360 kWh used < allowance


def test_series_pricing_uses_the_price_at_the_interval_start():
    plan = {"type": "outus/plan", "version": 1, "name": "Dyn", "currency": "AUD",
            "timezone": "Australia/Sydney", "billing": {"cycle": "monthly"},
            "tariffs": [{"id": "g", "applies_to": "general",
                         "price_source": {"kind": "series", "provider": "aemo", "settlement_interval_min": 5},
                         "charges": [{"id": "e", "class": "interval", "basis": "series_plus_adder",
                                      "rates": [{"rate": 0.10}]}]}]}
    t = loc(2026, 10, 15, 12, 0)
    book = PriceBook("aemo")
    book.add([{"start": int(t.timestamp()), "duration_s": 300, "import": 0.05, "kind": "actual"},
              {"start": int(t.timestamp()) + 300, "duration_s": 300, "import": 0.50, "kind": "forecast"}])
    b = billing.bill(plan, {"general": ivs(t, 2, kwh_in=1.0)}, loc(2026, 10, 1), loc(2026, 11, 1), prices=book)
    line = _line(b, "e")
    assert line["amount"] == pytest.approx(0.15 + 0.60)
    assert line["inputs"]["price_kinds"] == ["actual", "forecast"]
    assert plans.check(plan) == []


def test_bill_validates_against_the_schema():
    from test_schemas import validate
    s, e, led = _au_month()
    assert validate(billing.bill(AU, led, s, e)) == []
    assert validate(billing.bill(AU, led, s, e, now=loc(2026, 11, 16))) == []


def test_now_rates_names_the_band():
    r = billing.now_rates(AU, loc(2026, 11, 16, 17, 0))
    energy = next(x for x in r if x["charge_id"] == "energy")
    assert (energy["band"], energy["rate"]) == ("on_peak", 0.52)


# v1 import
AGL = {
    "type": "franklinwh-bridge/tariff-profile", "version": 1,
    "profile": {
        "name": "AGL Energy Ausgrid NSW", "retailer": "AGL", "network": "Ausgrid", "plan_type": "tou",
        "country": "AU", "timezone": "Australia/Sydney",
        "demand_window": {"months": [1, 2], "days": [], "start": "16:00", "end": "21:00"},
        "bonus_window": {"months": [], "days": [], "start": "17:00", "end": "21:00"},
        "pricing": {
            "billing_cycle_day": 1, "demand_rate": 0.3949, "demand_interval_min": 30,
            "demand_charge_basis": "per_kw_day", "export_bonus_rate": 0.28,
            "export_charge": {"window": {"months": [], "days": [], "start": "10:00", "end": "15:00"},
                              "rate": 0.013552, "free_kwh_per_day": 6.83},
            "fixed_charges": [{"type": "supply", "description": "Daily supply charge", "frequency": "daily",
                               "rate": 1.58631, "tax_rate": 0}],
            "seasons": [{"id": "peak", "name": "Peak season", "months": [11, 12, 1, 2, 3, 6, 7, 8],
                         "blocks": [{"start": "00:00", "end": "15:00", "time_period": "off_peak"},
                                    {"start": "15:00", "end": "17:00", "time_period": "on_peak"},
                                    {"start": "17:00", "end": "21:00", "time_period": "mid_peak", "days": [0, 1, 2, 3, 4]},
                                    {"start": "21:00", "end": "24:00", "time_period": "off_peak"}],
                         "time_periods": {"off_peak": {"buy": 0.21626, "sell": 0.03},
                                          "mid_peak": {"buy": 0.54175, "sell": 0.28},
                                          "on_peak": {"buy": 0.54175, "sell": 0.03}}}],
        },
    },
}


def test_v1_profile_imports_as_a_plan_and_prices_the_same():
    from test_schemas import validate
    plan = profile_v1.from_tariff_profile(AGL)
    assert validate(plan) == []
    assert [t["applies_to"] for t in plan["tariffs"]] == ["general", "export"]
    energy = plan["tariffs"][0]["charges"][0]
    assert billing.rate_at(energy, loc(2026, 1, 16, 16, 0)) == (0.54175, "on_peak")
    assert energy["rates"][2]["window"]["day_types"] == ["weekday"]
    assert plan["x-tariff-profile-v1"]["name"] == "AGL Energy Ausgrid NSW"
    assert plan["charges"][0]["basis"] == "per_day" and plan["charges"][0]["rate"] == 1.58631
    ids = {c["id"] for t in plan["tariffs"] for c in t["charges"]}
    assert {"energy", "demand", "feed_in", "bonus", "export_charge"} <= ids


# checks / setup
def test_checks_catch_overlaps_and_wrong_classes():
    a = {"name": "A", "effective_start": "2026-01-01", "effective_end": "2026-06-30"}
    b = {"name": "B", "effective_start": "2026-06-01"}
    assert plans.overlaps([a, b]) == ["A and B overlap from 2026-06-01"]
    bad = {"tariffs": [{"id": "g", "charges": [{"id": "x", "class": "interval", "basis": "per_day"},
                                               {"id": "y", "class": "interval", "basis": "per_unit",
                                                "rates": [{"window": {"start": "16:00", "end": "21:00"}, "rate": 1}]}]}]}
    issues = plans.check(bad)
    assert any("per_day is a period basis" in i for i in issues)
    assert any("no catch-all rate" in i for i in issues)
    assert plans.check(AU) == [] and plans.check(US) == []


def test_setup_steps_in_order():
    today = dt.date(2026, 11, 15)
    s = setup.steps([{"id": "s1"}], [{"id": "m1", "name": "Meter 1"}], [], "m1", today)
    assert [x["key"] for x in s] == ["site", "meter", "plan", "tariffs"]
    assert [x["done"] for x in s] == [True, True, False, False]
    assert s[2]["blocked"] is False and s[3]["blocked"] is True
    s = setup.steps([{"id": "s1"}], [{"id": "m1"}], [AU], "m1", today)
    assert setup.complete(s) and s[2]["detail"] == AU["name"]
