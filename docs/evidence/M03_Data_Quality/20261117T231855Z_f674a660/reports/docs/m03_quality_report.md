# NHS A&E M03 — Data Quality Validation

## Source and unit of analysis

- Source: `data/staging/ae_historical_raw_combined.parquet`
- Rows: 11,449 (11,392 provider, 57 aggregate).
- Observed reporting months: 57 (2022-01–2026-09).
- Expected grain for modelling: organisation code × reporting month, excluding national totals *only after M03*.
- NHS counts were checked but not changed; zero demand is not treated as missing.

## Validation outcomes

- Gate: **PASS_CORE_CHECKS_WITH_ADVISORIES**
- Error finding groups: 0
- National metric-month reconciliations: 1026 matched; 0 mismatched; 0 not comparable.
- Providers with gaps between first/last recorded months: 12.
- Providers with name variants: 18.
- Consecutive-month Type 1 changes flagged for human review: 0.

## Highest-volume source issues

No row-level errors or warnings detected by the implemented checks.

## Interpretation

A passed core gate does not establish clinical suitability or longitudinal provider comparability. Provider restructures, structural zero Type 1 activity, metadata changes and large demand shifts require context before modelling.

M04 should document any standardisation decisions and M05 should resolve historical provider-identity questions.

## Outputs

All checks are reproducible from the M02 staged file. Detailed grouped evidence is in `data/quality/m03_findings.csv`, with monthly profiles, reconciliation and continuity reports under `docs/`.
