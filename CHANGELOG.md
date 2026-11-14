# Changelog

## [Unreleased]

### Added
- OUTUS v1 draft 0.1 for electricity: the plan, price-series, usage and bill schemas; the spec text, including how to present OUTUS data (setup → summary → detail → history); illustrative AU and US examples; and schema tests.
- `outus` 0.1.0, the Python reference implementation: ledger, prices, billing (interval and period charges, explainable line items, provisional bills with projection), billing periods, plan checks, setup steps, and v1 tariff-profile import.
- Schema additions: `baseline` as kWh/day by months, window `days`, and bill `progress`.
