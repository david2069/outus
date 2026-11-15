# OUTUS: Open Utility Tariff & Usage Specification

One open JSON model for a utility **plan** and its **tariffs**, the **usage** metered against them, **dynamic prices**, and the **bills** that result, with every bill line explained.

Tariffs are entered once and exchanged as files. Any integration can read, write and extend them.

- **v1 specifies electricity.** `commodity` and `unit` are open, so others (Home Assistant integrations, for example) can add gas, water and more as extensions.
- **Status:** draft 0.1. The [spec](docs/spec.md) and the [JSON Schemas](schemas/v1/) define it.
- **Implemented by:** [hems](https://github.com/david2069/hems) (Python), used by the FranklinWH Direct Connect and Modbus bridges.

| Document | What it holds |
|---|---|
| `outus/plan` | a customer's plan: retailer, dates, billing cycle, tax, plan charges, and one or more tariffs (general, controlled load, export, EV, riders) |
| `outus/price-series` | dynamic prices: each interval's price at its start, held for its duration |
| `outus/usage` | the ledger: metered quantity per channel in 5-minute intervals, with the price and cost each was billed at |
| `outus/bill` | one plan for one closed period, with line items showing their formula and inputs |

Charges are either **interval** charges (worked out each interval: energy, feed-in, bonus) or **period** charges (worked out at the close: supply, demand, export above a free band, tiers, minimum bill, true-up).

## Examples
`examples/electricity/` has an AU TOU plan (general, controlled load and feed-in tariffs), a US TOU plan with net billing, a price series, usage and a bill. **The rates are illustrative, not anyone's current tariff.**

## Implementations
| Implementation | Language | Notes |
|---|---|---|
| [hems](https://github.com/david2069/hems) | Python | ledger, prices, explainable bills, plan checks; used by the FranklinWH Direct Connect and Modbus bridges |

Others are welcome; an implementation should validate what it writes against `schemas/v1/`.

## Checking the schemas
```
pip install pytest "jsonschema>=4.18" referencing rfc3339-validator
pytest
```

## Releases
The spec is versioned on its own: a `spec-v*` tag publishes a GitHub release with the
schemas and examples attached.

## Licence
MIT
