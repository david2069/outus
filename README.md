# OUTUS: Open Utility Tariff & Usage Specification

One open JSON model for a utility **plan** and its **tariffs**, the **usage** metered against them, **dynamic prices**, and the **bills** that result, with every bill line explained.

Tariffs are entered once and exchanged as files. Any integration can read, write and extend them.

- **v1 specifies electricity.** `commodity` and `unit` are open, so others (Home Assistant integrations, for example) can add gas, water and more as extensions.
- **Status:** draft 0.1. The [spec](docs/spec.md) and the [JSON Schemas](schemas/v1/) define it.
- **Used by:** the FranklinWH Direct Connect and Modbus bridges (through `franklinwh-hems`).

| Document | What it holds |
|---|---|
| `outus/plan` | a customer's plan: retailer, dates, billing cycle, tax, plan charges, and one or more tariffs (general, controlled load, export, EV, riders) |
| `outus/price-series` | dynamic prices: each interval's price at its start, held for its duration |
| `outus/usage` | the ledger: metered quantity per channel in 5-minute intervals, with the price and cost each was billed at |
| `outus/bill` | one plan for one closed period, with line items showing their formula and inputs |

Charges are either **interval** charges (worked out each interval: energy, feed-in, bonus) or **period** charges (worked out at the close: supply, demand, export above a free band, tiers, minimum bill, true-up).

## Examples
`examples/electricity/` has an AU TOU plan (general, controlled load and feed-in tariffs), a US TOU plan with net billing, a price series, usage and a bill. **The rates are illustrative, not anyone's current tariff.**

## Reference implementation (`outus`, Python ≥ 3.11, no dependencies)
| Module | Job |
|---|---|
| `outus.ledger` | grid readings from the devices behind a meter → 5-minute usage intervals |
| `outus.prices` | a price series: price at an interval's start, later kinds replace earlier ones |
| `outus.billing` | an OUTUS bill from a plan and the ledger, with formulas; provisional bills project to the period's end; `now_rates` for the live band and rate |
| `outus.periods` | billing period bounds (monthly, bimonthly, quarterly) |
| `outus.plans` | checks a schema can't express (overlapping plans, wrong charge class, unpriced gaps) |
| `outus.setup` | setup steps in order: site → meter → plan → tariffs |
| `outus.profile_v1` | imports a `franklinwh-bridge/tariff-profile` v1 file as a plan |

```
pip install -e ".[test]"
pytest
```

## Licence
MIT
