# NHS A&E IDSS | M04 preprocessing

## Purpose
Standardise the M02 combined dataset without imputing absent observations or removing providers. Preserve the 18 numeric measures, retain every source record and separate national totals from provider rows. M05 will investigate longitudinal comparability and forecasting eligibility.

## Installation in VS Code
Copy the contents of this package into the corresponding directories of the existing NHS-A-E-IDSS clone. It adds files and does not replace M01/M02, M03, the evidence exporter, or existing notebooks. Prerequisites: the completed M01/M02 source manifest, coverage report and staged data, M03 validator, evidence exporter and their dependencies. No additional libraries are required if the previous notebooks ran successfully.

From the project root in the existing Python environment:

```powershell
python -m pytest -q tests/test_m04_preprocess.py
```

Alternatively open `notebooks/03_m04_preprocessing.ipynb`, select the same kernel used for M03, and choose Run All. This executes the pipeline and captures a fresh M04 test log. Save the executed notebook with Ctrl+S. Terminal-only alternative (choose one workflow to avoid duplicate snapshots):

```powershell
python -m src.data.m04_preprocess --repo .
```

## Where the files appear

- `data/processed/m04/<run-id>/ae_provider_monthly.csv` and optional Parquet: all provider-month records, no national totals.
- `data/processed/m04/<run-id>/ae_national_monthly.csv` and optional Parquet: the separately retained published national aggregates.
- `data/processed/m04/<run-id>/m04_summary.json`: counts, quality outcomes, output paths and fingerprints.
- `docs/evidence/M04_Preprocessing/<run-id>/`: three 300 DPI figures, fresh M03 reports, M04 research report, data dictionary, change counts, measure conservation, decision register, test results and evidence manifest.

Both locations use the same timestamped run ID. A new run does not overwrite an earlier one. Use outputs in later stages only if the matching evidence manifest reads COMPLETE and the summary reads PASS_STANDARDISATION. An interrupted or failed run can leave partial files; do not use them. The notebook displays the current output paths. The original `data/raw/` and `data/staging/` remain unmodified.

## Expected results for the previously observed NHS collection
If the current staged source is unchanged: 57 reporting months, 11,449 total source records, 11,392 provider records and 57 retained national aggregates. Expect 18 of 18 measures conserved, zero provider records removed, and the same count of reported zero Type 1 values before and after. The exact M04 results require execution against the local collection.

## Verification and limitations
16 new regression tests passed, as did the combined 53-test suite in the development environment. The notebook was executed on a fictional 57-month CSV fixture and the three charts were reviewed. PyArrow was not installed in that environment, so the Parquet branch and actual NHS data have not been independently tested here. CSV exports are always produced on a successful run. If PyArrow is installed, Parquet is also written. CSV readers must use explicit data types. M04 checks do not prove that provider codes represent historically equivalent services; M05 must examine open advisories. No imputation, new lag features, provider selection or model evaluation occurs at M04.
