# Research methodology

## Objective and grain

The analytical objective is next-month Type 1 A&E attendance forecasting at NHS provider-code level, supporting operational planning. The source consists of monthly aggregate returns, not individual patient records or individual hospital-site counts.

## Preparation and verification

| Stage | Method and acceptance criterion |
| --- | --- |
| M01 | Inventory files and match the reporting period to filename and year; record SHA-256, schema and row counts. Require all expected months and one national total per file. |
| M02 | Concatenate the 22 source fields as strings and append four provenance fields. Retain all source observations and national totals. Check row counts and source hashes. |
| M03 | Check keys, dates, missing required fields, count validity, provenance and national reconciliation. Report provider continuity and naming variations separately. |
| M04 | Standardise names, trim identifier whitespace, uppercase codes, derive month-start dates and convert the 18 measures to integers. Separate national totals and verify conservation. |
| M05 | Construct an explicit monthly calendar from each provider's first observation to the end of the collection. Preserve null counts for absent records. Derive time-aware candidate status. |
| M06 | Reconstruct the calendar from the pinned M04 and M05 inputs; verify observed records, numerical reconciliation, output fingerprints and serialisation. Export calendar, observed-provider and national tables. |

## Recorded findings

The source inventory covers January 2022 to September 2026. September 2024 contains six additional trailing columns whose data cells are empty; the ingestion excludes only these empty fields and retains the raw file. Non-empty extra fields fail validation.

The recorded run retained 11,392 provider records and 57 separate national totals. All 18 measures reconcile across 57 months. Of the 12,263 calendar rows, 871 have no observation (30 internal gaps and 841 after the last recorded observation). The 4,426 reported zero Type 1 observations remain unchanged. There are 18 provider codes with recorded name variants.

## Candidate population

An origin is provisionally eligible when a provider has a reported observation, 12 consecutive observed months ending at that origin, and at least one positive Type 1 observation within the window. The rule supports seasonal forecasting and is not an NHS service designation. The recorded September 2026 cohort contains 120 candidates among 191 reporting providers. A candidate origin is not necessarily an evaluable forecast pair.

## Limitations and modelling implications

- A missing calendar observation is not zero activity or evidence of service closure.
- Provider code continuity and name changes do not establish historical service equivalence. Review reorganisations before modelling.
- The M03 demand-change screen requires at least 2,000 absolute and 100% relative change from a positive preceding month. It is an exploratory heuristic, misses zero-to-positive transitions and changes across gaps, and is not a comprehensive outlier test.
- Candidate eligibility must use information available at the forecast origin. Historical descriptive classifications must not define earlier cohorts using future information.
- Publication delays and revisions may affect historical information availability. Align forecasts, features and targets to publication-aware origins and use chronological validation. Do not use target-month measures, provenance fields or national totals as provider predictors.
- No imputation, outlier removal, feature scaling or model performance assessment has been performed.

## Evidence and reproduction

Use the versioned `docs/evidence/` snapshots for detailed tables, figures, decisions and test logs. M04-M06 output directories share run IDs with their evidence manifests. Only use completed runs with matching fingerprints and successful summaries. Regression tests use synthetic fixtures; the NHS evidence records execution against the actual source data. Recorded summaries are traceable to their original run and revision.

Source: [NHS England A&E activity publications](https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/).
