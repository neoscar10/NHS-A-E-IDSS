# NHS A&E IDSS | Research evidence exporter v1.0

## Install

Copy the files in this package into the matching folders in your existing NHS-A-E-IDSS clone. Keep the existing validators, notebooks, requirements and data. These are additive files; no dependency changes are required if M01 to M03 already run.

From the project root in the active VS Code terminal:

```powershell
python -m pytest -q tests/test_evidence_exporter.py
```

The new suite contains 10 tests. To run all three suites:

```powershell
python -m pytest -q tests/test_m01_m02.py tests/test_m03_validate.py tests/test_evidence_exporter.py
```

Open `notebooks/01_m01_m02_evidence_collection.ipynb`, select the project kernel and choose Run All. Then open `notebooks/02_m03_data_quality_validation_v1_2.ipynb` and choose Run All. Save the executed notebooks with Ctrl+S. Keep the previous notebooks if desired. No additional data pipeline run is needed for M01/M02; these notebooks require your existing successful outputs. M03 reruns the unchanged validator using your staged dataset and writes its fresh reports in its evidence folder only.

## Output structure

```text
docs/evidence/
  M01_Data_Inventory/<UTC-run-id>/
    figures/01_source_coverage.png
    reports/source_manifest.csv
    reports/m01_coverage.json
    reports/inventory_interpretation.md
    test_results/pytest_01.txt
    evidence_manifest.json
  M02_Data_Ingestion/<UTC-run-id>/
    figures/01_ingested_record_groups.png
    reports/m02_ingestion_summary.json
    reports/ingestion_interpretation.md
    test_results/pytest_01.txt
    evidence_manifest.json
  M03_Data_Quality/<UTC-run-id>/
    figures/ (four or five PNGs; reporting-gap chart is conditional)
    reports/docs/ (summary, quality report, monthly, reconciliation, continuity and change candidates)
    reports/data/quality/m03_findings.csv
    reports/m03_preprocessing_decisions.csv
    test_results/pytest_01.txt
    evidence_manifest.json
```

Every run is separate and uses a UTC timestamp plus a random suffix. `COMPLETE` means evidence collection completed, not that a model is validated. `COMPLETE_REVIEW_REQUIRED` records a quality issue, test failure or changed input detected during collection. `IN_PROGRESS` is an interrupted/unsealed run. The manifest records file hashes, current package versions and the Git HEAD if available. HEAD is not a guarantee that the working tree is committed. Input hashes describe files at evidence-collection time; retrospective M01/M02 snapshots do not independently establish past execution provenance. Large staged datasets are hashed, not duplicated. Keep the original source files and code version to reproduce the results.

Tests run at collection time on synthetic fixtures. Set `RUN_TESTS=False` in either notebook only if intentionally skipping them. Test logs will then be absent. The executed notebook itself remains in `notebooks/`; save it in VS Code. Notebook outputs are not automatically archived while the notebook is running.

## Optional terminal-only collection

```powershell
python src/utils/evidence_exporter.py --repo . --milestone M01 M02 M03 --run-tests
```

This archives existing reports, fingerprints inputs and runs tests. It does not generate figures or the M03 decision register, and does not rerun the validators. Use the notebooks for complete evidence collection.

## Reuse in future milestones

`EvidenceRun(repo_root, 'M04', 'Preprocessing evidence')` starts a new run. Record inputs using `record_input`, copy an existing report with `copy_report`, export a Matplotlib figure using `save_figure`, export a DataFrame with `write_table`, and record tests using `run_tests`. Call `finish` only after all intended artifacts are generated. M04 to M10 folders are supported but no future-stage implementation is included.

Before committing, review generated reports and test logs for content appropriate to the public repository. Keep a backup of the evidence if needed. This package does not upload to GitHub or Google Drive.

## Validation

The exporter suite (10 tests) and existing M01/M02 and M03 suites (8 and 19 tests) passed together. Both notebooks executed on a synthetic 57-month integration fixture using CSV fallback (PyArrow was unavailable in the build environment). All seven expected test-fixture charts were visually checked. Real NHS evidence must be generated locally from the actual completed outputs. The package contains no synthetic results or NHS-derived results.
