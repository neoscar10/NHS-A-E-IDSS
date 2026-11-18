# NHS A&E IDSS — M03 Data Quality Validation

## Goal

Run a **read-only** data-quality audit on the combined provider-month NHS England monthly A&E source data created by M01/M02. M03 **does not clean, drop, impute, standardise or model** any original source measurements.

**Input:** `data/staging/ae_historical_raw_combined.parquet`, or the matching `.csv` if Parquet is unavailable. Your completed M02 run reported 57 months, 11,449 rows, 11,392 provider records and 57 national total rows. M03 independently checks these against the staged source/manifest; it does not presume the data has passed deeper validation.

## Copy into the cloned VS Code repository

Open the cloned `NHS-A-E-IDSS` repository in VS Code. Use its integrated terminal at the repository root.

| Package file | Destination inside your cloned project |
| --- | --- |
| `src/data/m03_validate.py` | `src/data/m03_validate.py` |
| `tests/test_m03_validate.py` | `tests/test_m03_validate.py` |
| `notebooks/02_m03_data_quality_validation.ipynb` | `notebooks/02_m03_data_quality_validation.ipynb` |
| `docs/M03_Validation_Specification.md` | `docs/M03_Validation_Specification.md` |
| `requirements-m03.txt` | `requirements-m03.txt` (repository root) |
| `README_M03.md` | `README_M03.md` (repository root) |

**Keep** your existing `src/data/m01_m02.py` (v1.1), `data/raw/` CSVs, the M02 staged files and existing project README. Do **not** replace any of those with copies from this package. This package intentionally does not include a second `m01_m02.py`.

## Run from the VS Code terminal (PowerShell)

```powershell
conda activate nhs-ae-idss
python -m pip install -r requirements-m03.txt
python -m pytest -q tests/test_m03_validate.py
python src/data/m03_validate.py --repo .
```

For CI or a strict validation gate, add `--fail-on-errors` to return exit code `2` if any ERROR finding is detected. Without that switch, the report is written **even if** checks identify problems.

If you cannot run `conda` in PowerShell, use **Anaconda Prompt**, activate the same environment there and run the commands; or initialise PowerShell once with `conda init powershell` and reopen VS Code.

## Explore the results in VS Code

1. Open `notebooks/02_m03_data_quality_validation.ipynb`.
2. Choose **Select Kernel** and the `nhs-ae-idss` Conda interpreter (install the VS Code Python and Jupyter extensions if necessary).
3. Click **Run All**.
4. Inspect the issues table, both monthly figures, national reconciliation and provider continuity before treating the dataset as model-ready.

### Generated outputs

| File | Meaning |
| --- | --- |
| `docs/m03_quality_summary.json` | Counts, checks and overall quality gate |
| `docs/m03_quality_report.md` | Short reader-facing evidence report |
| `data/quality/m03_findings.csv` | Grouped ERROR/WARNING evidence and source records |
| `docs/m03_monthly_profile.csv` | Monthly volume, provider count and zero-Type-1 profile |
| `docs/m03_monthly_reconciliation.csv` | Every month × each of 18 reported measures (normally 57 × 18 = 1,026 checks) |
| `docs/m03_provider_continuity.csv` | Organisation-level time coverage, name variants and structural Type 1 zeros |
| `docs/m03_type1_change_candidates.csv` | Large consecutive-month Type 1 differences to investigate, not automatic errors |

### How to interpret the gate

- `REVIEW_REQUIRED`: one or more **ERROR** checks failed. Inspect the findings before cleaning or modelling.
- `PASS_CORE_CHECKS_WITH_ADVISORIES`: implemented core checks found no errors; longitudinal questions and clinical/operational interpretation remain to be addressed.
- Reconciliation statuses are `MATCH`, `MISMATCH` and `NOT_COMPARABLE` (the last includes missing totals or invalid numeric values).
- Genuine zero Type 1 counts are **never treated as missing**, and the national TOTAL rows are **retained** in the staged source. Exclusion for provider modelling belongs to a later modelling-ready transformation.

## Prevent generated large files being committed accidentally

Check your `.gitignore` and add the following patterns if they are not already covered:

```gitignore
data/staging/
data/quality/
```

Keep `docs/m03_quality_report.md` if you want to version the research findings; decide whether to commit the generated CSV/JSON reports after reviewing their size and contents. Generated outputs can always be reproduced from M01/M02.

## Implementation status

The M03 regression suite and notebook were tested against **synthetic** fixtures (including a 57-month synthetic M01/M02 integration output). The notebook is shipped with no saved synthetic result cells. The validator has **not** been run on your local 11,449 NHS records here; its real M03 findings must be produced by the commands above.
