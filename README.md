# NHS A&E Intelligent Decision Support System

Provider-level, next-month Type 1 A&E attendance forecasting for operational capacity planning. This MSc ICA2 project uses monthly aggregate NHS England data; it does not predict individual patient outcomes or automate clinical decisions.

## Current analytical dataset

The verified January 2022 to September 2026 collection contains 57 source files, 11,449 source records (including 57 national totals), 11,392 observed provider-months and 223 distinct provider codes. The aligned calendar contains 12,263 rows, of which 871 are absent observations. The recorded M06 run reconciled all 1,026 month-measure comparisons.

| Stage | Notebook |
| --- | --- |
| M01-M02: Inventory and ingestion | [01_m01_m02_inventory_ingestion](notebooks/01_m01_m02_inventory_ingestion.ipynb) |
| M03: Data quality | [02_m03_data_quality_validation](notebooks/02_m03_data_quality_validation.ipynb) |
| M04: Standardisation | [03_m04_preprocessing](notebooks/03_m04_preprocessing.ipynb) |
| M05: Longitudinal preparation | [04_m05_longitudinal_preparation](notebooks/04_m05_longitudinal_preparation.ipynb) |
| M06: Final dataset | [05_m06_final_dataset](notebooks/05_m06_final_dataset.ipynb) |

## Setup and execution

Use a dedicated Python environment (Python 3.11 or later, subject to dependency compatibility). From the cloned repository root:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

Open the five notebooks in order in VS Code or JupyterLab, select the same Python environment, and run all cells. M01-M02 rebuilds staging data from the included source files. M03 audits the staged dataset; M04-M06 produce versioned datasets and evidence. Review the generated summaries and evidence manifests before proceeding. For a terminal-only run:

```bash
python -m src.data.m01_m02 --repo . --start 2022-01 --end 2026-09
python -m src.data.m03_validate --repo . --fail-on-errors
python -m src.data.m04_preprocess --repo .
python -m src.data.m05_longitudinal --repo .
python -m src.data.m06_finalise --repo .
```

The notebooks additionally provide research interpretation and visual evidence. The terminal-only sequence does not reproduce every notebook visual or M01-M03 evidence snapshot.

## Repository layout

| Directory | Purpose |
| --- | --- |
| `data/raw/` | Original monthly source CSVs |
| `data/staging/`, `data/quality/`, `data/processed/` | Generated local outputs |
| `src/`, `tests/` | Pipeline implementation and regression tests |
| `notebooks/` | Executable research analyses |
| `docs/evidence/` | Versioned figures, reports, manifests and test logs |
| `app/`, `models/` | Reserved for later stages |

Read the [methodology](docs/METHODOLOGY.md) and [data dictionary](docs/DATA_DICTIONARY.md). Historical evidence snapshots retain their original paths and fingerprints; they describe their original run, not a later revision of the notebooks.

## Source and scope

Source: [NHS England A&E Attendances and Emergency Admissions](https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/). The raw files were assembled in the [group repository](https://github.com/neoscar10/NHS-A-E-IDSS). Verify the applicable source reuse terms and attribution before external distribution.

Data preparation is complete for the recorded run. Forecasting features, chronological evaluation, model performance and operational validation remain separate future work.
