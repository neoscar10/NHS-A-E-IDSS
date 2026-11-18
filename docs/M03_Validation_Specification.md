# NHS England A&E — M03 Data Quality Validation Specification

## Purpose

Assess whether the M02 provider-month table preserves count integrity, reporting-month identity and historical data provenance before preparation of a forecasting dataset. The raw NHS extracts and their combined staging copy remain unchanged.

**Historical window:** January 2022–September 2026, 57 source files as recorded by the M01 inventory.

**Recorded source grain:** one provider organisation record per reporting month, plus a separate national TOTAL record per month. Providers may not offer Type 1 services; zero Type 1 attendances is not automatically missing.

## Validation contract

| ID / area | Check | Handling | Analytical importance |
| --- | --- | --- | --- |
| Input contract | Exactly 22 source columns and four M02 provenance columns | Stop if schema differs | Prevents silently evaluating the wrong export |
| M01/M02 provenance | Compare staged file counts, content months and stored SHA-256 values to M01 manifest, if available | ERROR on contradiction | Detects accidental dataset or source-version mixing |
| Reporting months | `source_month` uses YYYY-MM; the `Period` field agrees for provider rows | ERROR | Protects chronological evaluation |
| Identity | Provider `Org Code` and `Org name` present | ERROR | Required for provider-month keys |
| Geographic grouping | `Parent Org` present | WARNING | Useful for group summaries; not automatically a model feature |
| Uniqueness | `(source_month, normalised Org Code)` unique for provider rows | ERROR | Duplicate provider observations would inflate demand |
| Provenance record | `(source_file, source_record_number)` unique | ERROR | Prevents duplicated extracted records |
| Source provenance | `source_file` has expected year path and 64-character SHA-256 | ERROR | Preserves reproducibility |
| Count integrity | All 18 numeric source fields contain non-negative whole-number strings | ERROR; blank ≠ zero | Prevents invalid arithmetic |
| National row count | Exactly one case/whitespace-insensitive national TOTAL row per month | ERROR | Protects reconciliation |
| National reconciliation | Provider sums agree with national TOTAL for each month × measure | ERROR on difference; NOT_COMPARABLE if invalid | Detects unaccounted row loss and potential published/source discrepancies |
| Provider time continuity | Internal reporting-month gaps and multiple names per organisation code | Advisory, not deletion | May represent organisational changes, not bad data |
| Type 1 structural zeros | Monthly share of provider records with Type 1 zero | Descriptive only | Some providers provide other A&E services |
| Demand-change screening | For consecutive months, absolute Type 1 change ≥2,000 **and** relative change ≥100% | Review candidate only | Prioritises unusual shifts; not a clinical or statistical anomaly test |

The numerical screening thresholds above are **exploratory triage rules**, not standards specified by NHS England. They must not drive automatic replacement of recorded counts.

## Comparability and methodology

1. Source integrity and forecasting suitability are distinct: no observed schema or arithmetic error does **not** prove a stable provider identity or a predictive signal.
2. Compare historical provider codes, closures, mergers and Type 1 service scope in M05 before choosing the forecasting population.
3. Do not use contemporaneous four-hour waiting measures as predictors for *future* attendance unless their availability at the forecast origin can be established.
4. Retain the national TOTAL row as a source control; later exclude it from the provider-level modelling table to prevent double-counting.
5. No imputation, interpolation, winsorisation, group replacement or target leakage belongs to M03.

## Decisions for M04/M05 after reviewing actual results

- Identify any failed core validation checks by source month and column.
- Decide whether to standardise identifiers, reporting dates and provider names, preserving original columns for traceability.
- Investigate source records that do not reconcile with published national totals before adopting any transformation.
- Resolve provider continuity questions with documented evidence rather than dropping non-consecutive histories by default.
- Define model eligibility (e.g. Type 1 providers with sufficient history), training horizon, forecast origin and time-aware splits in the next milestones.
