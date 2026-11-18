# Historical NHS A&E data intake — M01 / M02

## Research purpose

Create a source-traceable monthly data foundation for subsequent provider-level Type 1 A&E attendance forecasting. The ingest stage is not a model, a recommendation system, or evidence of a validated clinical intervention.

## M01 — Source inventory

**Input:** Public monthly NHS England A&E CSVs from `data/raw/YYYY/`.

**Actions:** Discover all CSVs; extract month from the record's `Period` field and compare with its filename and folder; report source file size, SHA256, source columns, row count, and preliminary TOTAL-row identification; check that one file exists for each expected month.

**Output:** `docs/source_manifest.csv` and `docs/m01_coverage.json`.

**Acceptance:** 57 monthly periods in the January 2022–September 2026 window with no missing or duplicated months, no unresolved preliminary file-level issues, and traceable source paths. If an exception occurs, halt M02 pending investigation.

## M02 — Raw-value-preserving ingestion

**Input:** M01-passed monthly CSVs.

**Actions:** Load each CSV with all 22 original columns as strings; append `source_month`, `source_file`, `source_sha256` and `source_record_number`; concatenate chronologically; verify combined row count and source hashes.

**Output:** `data/staging/ae_historical_raw_combined.csv`, optional Parquet, and `data/staging/m02_ingestion_summary.json`.

**Acceptance:** All source records retained, including national TOTAL; no original source measure is coerced or imputed; combined row count equals the sum of the M01 row counts; original CSV files remain byte-for-byte unchanged.

## Scope deferred to subsequent milestones

- **M03:** validate duplicate organisation/month keys, numeric validity, completeness and reconciliation across all attendance/admission measures.
- **M04:** define standard column names and appropriate numeric data types, segregate national totals, investigate issues before deciding on treatments.
- **M05:** examine organisation changes, missing months, structural zero counts, service discontinuities and anomalous trends.

**Source references:** [GitHub](https://github.com/neoscar10/NHS-A-E-IDSS), [NHS England A&E activity publications](https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/).
