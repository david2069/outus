# OUTUS v1: Open Utility Tariff & Usage Specification

Status: **draft 0.1** (2026-11-15). The JSON Schemas in `schemas/v1/` are the normative definition, and this text explains them. The key words MUST, SHOULD and MAY are used as in RFC 2119.

## 1. Scope
OUTUS describes:
- a customer's utility **plan** and its **tariffs**;
- the **usage** metered against them;
- **dynamic prices**;
- the resulting **bills**.

All of these use one model, exchanged as JSON documents.

**v1 specifies electricity.** `commodity` and `unit` are open fields, so others (for example Home Assistant integrations) MAY add profiles for gas, water or anything else. Gas and water aren't specified here.

## 2. Objects
```
Site ─┬─ Meter (commodity, unit, phases, PTO)
      │    └─ Plan (retailer, account, dates, billing cycle, tax)   one in force per meter
      │         ├─ plan-level Charges (supply, minimum bill, true-up)
      │         └─ Tariffs[] (applies_to: general / controlled_load / export / ev / rider)
      │              ├─ price_source (static or a price series)
      │              └─ Charges[]
      ├─ Usage: ledger intervals per meter and channel
      ├─ Price series: price intervals per source
      └─ Bills: one per plan per closed period, with line items
```

- **Plan.** A meter has at most one plan in force. Plans MUST NOT overlap. A plan whose `effective_end` has passed is history; a correction to it creates a new bill that supersedes the old one, and the plan itself is not edited.
- **Tariff.** One set of rates for one channel. A plan has one or more tariffs: for example general TOU, controlled load and feed-in.
- **Charge.** One line on a bill.

## 3. Charge classes
| class | Worked out | Bases |
|---|---|---|
| `interval` | each interval: the interval's quantity × the rate in force at the interval's **start** | `per_unit` (flat or TOU by window), `series`, `series_plus_adder`, `value_table` |
| `period` | at the close, from the period's ledger | `per_day`, `per_month`, `per_year`, `demand`, `excess_over_free_band`, `tier`, `minimum_bill`, `true_up`, `percent_of_bill` |

Rules:
- **Rate tables:** windows are matched first-match-wins, and an entry without a window covers the rest of the time.
- **Bands:** a TOU entry SHOULD name its `band`, one of FranklinWH's four: `super_off_peak`, `off_peak`, `mid_peak` or `on_peak`.
- **Baseline:** a `tier` charge with a `baseline` (kWh per day by months) uses baseline × days as its first tier.
- **Tiers:** a `tier` charge is cumulative over its `tier_per` (day or period). Producers MAY price intervals provisionally, and the close settles the tier.
- **Demand:** a `demand` charge builds `interval_min` averages from the ledger inside its `window`, then applies its `method`.
- **Direction and effect:** `direction` (import or export) and `effect` (cost or credit) give the sign. A bill line's `amount` is positive for a cost and negative for a credit.

## 4. Dynamic prices
- **Series:** a tariff with `price_source.kind = series` takes per-unit prices from a price series with the same `provider` and `region`.
- **Holding a price:** each price interval has a clock-aligned `start` (UTC) and a `duration_s`. Its price holds for the whole duration.
- **Revisions:** `kind` ranks the prices: forecast < estimate < confirmed < actual. A higher kind replaces a lower one for the same start and source. The ledger re-prices the interval and keeps a record of the change.
- **Missing prices:** a gap is priced from the last known price and marked `estimate`, then re-priced when the real price arrives.
- **All-in or adders:** `all_in: false` means `series_plus_adder` charges add the network and retail parts. `all_in: true` means the series already includes them.

## 5. Usage (the ledger)
- **Intervals:** producers SHOULD record clock-aligned **5-minute** intervals per meter and channel. Coarser settlement and demand intervals are built up from them.
- **Contents:** each interval records `quantity_in`, `quantity_out` (electricity export), `peak_rate` (kW), the `price` it was billed at and its `cost`. A bill can then be recalculated and checked from the ledger alone.
- **Source:** `metered`, `read` (a manual meter reading) or `estimated`.

## 6. Bills
- **Contents:** a bill covers one plan for one period, with `line_items` grouped by tariff and then plan-level charges, followed by tax and `net_total`.
- **Line items:** each line SHOULD carry `quantity`, `unit`, `rate`, a human-readable `formula` and its `inputs`.
- **Status:** `provisional` (the period hasn't ended yet), `final`, or `superseded`, which points to its replacement through the replacement's `supersedes`.
- **Progress:** a provisional bill MAY carry `progress` (days elapsed, days, projected total).
- **Source:** `calculated` (from the ledger) or `utility` (the utility's own figures, for example from HA Opower).

## 7. Documents
| `type` | Schema |
|---|---|
| `outus/plan` | `schemas/v1/plan.schema.json` |
| `outus/price-series` | `schemas/v1/price-series.schema.json` |
| `outus/usage` | `schemas/v1/usage.schema.json` |
| `outus/bill` | `schemas/v1/bill.schema.json` |

Every document has `type` and an integer `version`.

## 8. Extensions and versions
- **Unknown fields:** consumers MUST accept unknown fields and commodities, and MUST preserve them when they re-export a document.
- **Vendor fields:** vendor-specific fields SHOULD be prefixed `x-`.
- **Versions:** a change that breaks existing documents increases `version`. Additions don't.
- **Legacy import:** a `franklinwh-bridge/tariff-profile` v1 file imports as an `outus/plan` with one `general` tariff.

## 9. Presenting OUTUS (informative)
Applications that show OUTUS data SHOULD follow its structure, in this order:

1. **Setup**, in the model's order: site → meter → plan (retailer, account, dates) → tariffs → charges. Each missing step is shown with a way to complete it.
2. **Summary**: this period so far, with net cost, projection, day *n* of *N* and the source (calculated or utility). There is one figure per tariff, plus plan charges.
3. **Detail**: the open period's line items grouped by tariff, each with its formula. This view shows the live inputs: band now, rate now, demand peak so far, free band left, and tier position.
4. **History**: closed bills, newest first, each expanding to its line items. Also usage and price charts over the same periods, and export as `outus/bill` and `outus/usage`.
