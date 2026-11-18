# NHS A&E IDSS | M05 longitudinal preparation

## Purpose
Prepare an auditable monthly provider calendar from the M04 standardised dataset. Distinguish absent records from reported zero activity and identify provisional Type 1 forecasting candidates using only observations through each reporting month.

## Installation and execution
Copy the package files into their corresponding directories in the NHS-A-E-IDSS repository. The existing M04 output, M04 code, evidence exporter and Python dependencies are required. From the repository root:

```powershell
python -m pytest -q tests/test_m05_longitudinal.py
```

Open `notebooks/04_m05_longitudinal_preparation.ipynb`, select the project Python kernel and run all cells. Save the executed notebook. Alternatively, run the pipeline in the terminal:

```powershell
python -m src.data.m05_longitudinal --repo .
```

The latest M04 run is selected by default. To reproduce a specific run, set `M04_RUN_ID` in the notebook or pass `--m04-run-id <run-id>` in the terminal. M04 output fingerprints and evidence status must match the recorded source. The default history window is 12 consecutive reporting months through the origin.

## Outputs
- `data/processed/m05/<run-id>/ae_provider_calendar.csv` and Parquet if PyArrow is installed.
- `data/processed/m05/<run-id>/m05_summary.json` with record totals, parameters and source/output fingerprints.
- `docs/evidence/M05_Longitudinal_Preparation/<run-id>/` with 300 DPI figures, continuity and eligibility tables, decisions, research report, test log and evidence manifest.

Only use completed outputs with matching run IDs, `PASS_LONGITUDINAL_PREPARATION` in the summary and `COMPLETE` in the evidence manifest. Original M04 outputs and raw data remain unchanged.

## Interpretation
Absent calendar rows have null numeric measures and are not submissions. The activity rule is a provisional proxy, not verified service eligibility. Name and parent variants require historical identity review. No imputation, outlier deletion, forecasting or model training is performed. Source publication timing must be addressed before time-aware model evaluation.
