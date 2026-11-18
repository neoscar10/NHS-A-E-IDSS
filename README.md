# NHS A&E Intelligent Decision Support System

Provider-level, next-month Type 1 A&E attendance forecasting for operational capacity planning. This MSc ICA2 project uses monthly aggregate NHS England data; it does not predict individual patient outcomes or automate clinical decisions.

## Current analytical dataset

The verified January 2022 to September 2026 collection contains 57 source files, 11,449 source records (including 57 national totals), 11,392 observed provider-months and 223 distinct provider codes. The aligned calendar contains 12,263 rows, of which 871 are absent observations. The recorded M06 run reconciled all 1,026 month-measure comparisons.

| Stage | Notebook |
| --- | --- |
| M01-M02: Inventory and ingestion | [01_data_ingestion](notebooks/01_data_ingestion.ipynb) |
| M03: Data quality | [02_data_quality](notebooks/02_data_quality.ipynb) |
| M04: Standardisation | [03_data_preprocessing](notebooks/03_data_preprocessing.ipynb) |
| M05: Longitudinal preparation | [04_longitudinal_preparation](notebooks/04_longitudinal_preparation.ipynb) |
| M06: Final dataset | [05_final_dataset](notebooks/05_final_dataset.ipynb) |

## Setup and execution

Use a dedicated Python environment (Python 3.11 or later, subject to dependency compatibility). From the cloned repository root:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

Open a notebook in VS Code or JupyterLab using the project environment. Set the execution mode in its first code cell.

| Mode | Use | Output location |
| --- | --- | --- |
| `explore` (default) | Review saved results and figures without recomputing the pipeline | Existing evidence, read-only |
| `rebuild` | Recalculate and test the five notebooks in order | `.work/rebuild/`, excluded from Git |
| `snapshot` | Preserve a deliberate, versioned research execution | `data/processed/` and `docs/evidence/` |

Explore reads completed evidence and verifies displayed artifact fingerprints (allowing Git text line-ending conversion). It does not write datasets or evidence; saving the notebook itself can update its cached cell outputs. The archived results are not a fresh execution. Set `VIEW_REBUILD = True` to explore completed rebuild results. To inspect a particular archived run, use `EXPLORE_RUN_IDS` with the milestone and run ID.

For a fresh rebuild, set `MODE = "rebuild"` in notebooks 01 through 05 and run each once, in sequence. A rebuild has its own source and code copies, local datasets and evidence. It never appends to the archived evidence. To replace an existing or interrupted rebuild, stop its kernels and set `RESET_REBUILD = True` in notebook 01 only. This deletes the previous local rebuild workspace; leave the setting false for ordinary use. Do not run rebuild stages concurrently.

For a research snapshot, set `MODE = "snapshot"` in the five notebooks and run them in order. This regenerates staging files and creates new versioned processed datasets and evidence. Save execution settings before Run All. Review the completed manifests before retaining or committing the new research evidence.

## Repository layout

| Directory | Purpose |
| --- | --- |
| `data/raw/` | Original monthly source CSVs |
| `data/staging/`, `data/quality/`, `data/processed/` | Generated local outputs |
| `src/`, `tests/` | Pipeline implementation and regression tests |
| `notebooks/` | Executable research analyses |
| `.work/rebuild/` | Isolated, replaceable local rebuild (not tracked) |
| `docs/evidence/` | Versioned figures, reports, manifests and test logs |
| `app/`, `models/` | Reserved for later stages |

Read the [methodology](docs/METHODOLOGY.md) and [data dictionary](docs/DATA_DICTIONARY.md). Historical evidence snapshots retain their original paths and fingerprints; they describe their original run, not a later revision of the notebooks.

## Source and scope

Source: [NHS England A&E Attendances and Emergency Admissions](https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/). The raw files were assembled in the [group repository](https://github.com/neoscar10/NHS-A-E-IDSS). Verify the applicable source reuse terms and attribution before external distribution.

Data preparation is complete for the recorded run. Forecasting features, chronological evaluation, model performance and operational validation remain separate future work.
