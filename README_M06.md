# NHS A&E IDSS | M06 final dataset verification

## Purpose
Verify the prepared provider-month calendar against the pinned M04 and M05 outputs. Publish versioned, reproducible analytical datasets, a data contract and research evidence. No forecasting features or models are created at this stage.

## Run
Copy the package files into the corresponding locations in the repository. Keep the existing M01 to M05 code, processed data and evidence exporter. Use the existing Python environment.

```powershell
python -m pytest -q tests/test_m06_finalise.py
```

Open `notebooks/05_m06_final_dataset.ipynb`, select the project kernel, run all cells and save the notebook. Alternatively run from the repository root:

```powershell
python -m src.data.m06_finalise --repo .
```

By default the pipeline selects the most recent M05 run directory and requires that run to be complete. To reproduce a particular version, set `M05_RUN_ID` in the notebook or pass `--m05-run-id <run-id>` in the command. A failed or incomplete latest run is not silently replaced by an older run.

## Outputs
The pipeline writes to `data/processed/m06/<run-id>/`:

| File | Purpose |
|---|---|
| `ae_provider_calendar_final.csv` | Calendar-aware input for M07; one row per provider code and month after first observation. |
| `ae_provider_observed_final.csv` | Published provider records only; suitable for descriptive analysis, not positional lagging. |
| `ae_national_final.csv` | Separate national benchmark, one total per reporting month. |
| `m06_summary.json` | Run identifiers, verification counts and output fingerprints. |
| `m06_data_contract.json` | Schema, keys, target, missingness and modelling constraints. |

Equivalent Parquet files are exported and round-trip checked when PyArrow is installed. CSV preserves null counts as empty fields; use explicit types when loading. The evidence snapshot in `docs/evidence/M06_Final_Dataset/<run-id>/` includes 300 DPI figures, the dictionary, reconciliation results, monthly profile, decisions, report, test log and fingerprint manifest.

Use only releases with `PASS_FINAL_DATASET_VERIFICATION` in the summary and `COMPLETE` in the evidence manifest. Record the exact run ID for downstream work. Keep previous versions for reproducibility.

## Scope and limitations
The release preserves observed counts, provenance and reported zeros, with missing calendar counts remaining null. Candidate status is a provisional reporting-history proxy, not an independently verified Type 1 service designation. The historical files may contain revisions that were not available at earlier dates. Temporal feature engineering, publication availability, chronological evaluation and model training are separate stages.
