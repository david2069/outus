# Changelog

## [Unreleased]

### Added
- Releases: a `spec-v*` tag publishes the schemas and examples as a GitHub release.

### Changed
- The Python engine moved to its own repo, [hems](https://github.com/david2069/hems), so the spec is published independently.

### Added (draft 0.1)
- OUTUS v1 draft 0.1 for electricity: the plan, price-series, usage and bill schemas; the spec text, including how to present OUTUS data (setup → summary → detail → history); illustrative AU and US examples; and schema tests.
- Schema additions: `baseline` as kWh/day by months, window `days`, and bill `progress`.
