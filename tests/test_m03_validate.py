"""Regression tests for M03 validation. No real NHS data is modified."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data.m01_m02 import EXPECTED_COLUMNS
from src.data.m03_validate import validate_dataset, load_staged, MEASURES


def row(month: str, code: str, type1: str, ordinal: int, total: bool = False) -> dict:
    y, m = month.split("-")
    dt = pd.Timestamp(year=int(y), month=int(m), day=1)
    prefix = "Total" if total else f"MSitAE-{dt.strftime('%B').upper()}-{y}"
    raw = {c: "0" for c in MEASURES}
    raw.update({"Period": prefix, "Org Code": "Total " if total else code,
                "Parent Org": "Total" if total else "NHS ENGLAND LONDON",
                "Org name": "Total" if total else f"TEST HOSPITAL {code}"})
    raw[MEASURES[0]] = type1
    raw.update({"source_month": month,
                "source_file": f"data/raw/{y}/{dt.strftime('%B')}-{y}-test.csv",
                "source_sha256": "a" * 64,
                "source_record_number": str(ordinal)})
    return raw


def make_repo(tmp_path: Path, rows: list[dict]) -> Path:
    staging = tmp_path / "data" / "staging"
    staging.mkdir(parents=True)
    df = pd.DataFrame(rows, columns=EXPECTED_COLUMNS + ["source_month", "source_file", "source_sha256", "source_record_number"])
    df.to_csv(staging / "ae_historical_raw_combined.csv", index=False)
    (staging / "m02_ingestion_summary.json").write_text(json.dumps({
        "combined_rows_including_totals": len(rows),
        "national_total_rows_retained": sum(r["Org Code"].strip().upper() == "TOTAL" for r in rows),
    }), encoding="utf-8")
    return tmp_path


def find_checks(result):
    return set(result["findings"]["check"])


def test_valid_month_and_zero_type1_retained(tmp_path):
    rows = [row("2026-09", "R1", "0", 1), row("2026-09", "R2", "5", 2),
            row("2026-09", "TOTAL", "5", 3, True)]
    result = validate_dataset(make_repo(tmp_path, rows))
    assert result["summary"]["quality_gate"] == "PASS_CORE_CHECKS_WITH_ADVISORIES"
    assert result["summary"]["checks"]["reconciliations_matched"] == 18
    assert result["monthly"].iloc[0]["type1_zero_provider_rows"] == 1
    assert len(result["findings"]) == 0
    assert (tmp_path / "docs/m03_quality_report.md").exists()
    assert (tmp_path / "data/quality/m03_findings.csv").exists()


def test_duplicates_provider_month_are_blocking(tmp_path):
    rows = [row("2026-09", "r1 ", "2", 1), row("2026-09", "R1", "3", 2),
            row("2026-09", "TOTAL", "5", 3, True)]
    result = validate_dataset(make_repo(tmp_path, rows))
    assert "DUPLICATE_PROVIDER_MONTH_KEY" in find_checks(result)
    assert result["summary"]["quality_gate"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("invalid,check", [
    ("", "MISSING_COUNT"), ("-5", "NEGATIVE_COUNT"), ("1.5", "NON_INTEGER_COUNT"),
    ("not available", "NON_INTEGER_COUNT")
])
def test_bad_measure_count_flagged_and_no_false_reconciliation(tmp_path, invalid, check):
    rows = [row("2026-09", "R1", invalid, 1), row("2026-09", "TOTAL", "10", 2, True)]
    result = validate_dataset(make_repo(tmp_path, rows))
    assert check in find_checks(result)
    assert "NOT_COMPARABLE" in result["reconciliation"]["status"].tolist()
    assert "NATIONAL_TOTAL_MISMATCH" not in find_checks(result)


def test_total_mismatch_flagged(tmp_path):
    rows = [row("2026-09", "R1", "7", 1), row("2026-09", "TOTAL", "9", 2, True)]
    result = validate_dataset(make_repo(tmp_path, rows))
    assert "NATIONAL_TOTAL_MISMATCH" in find_checks(result)
    assert (result["reconciliation"]["status"] == "MISMATCH").sum() == 1


def test_total_missing_is_flagged(tmp_path):
    rows = [row("2026-09", "R1", "7", 1)]
    result = validate_dataset(make_repo(tmp_path, rows))
    assert "INVALID_TOTAL_ROW_COUNT" in find_checks(result)
    assert (result["reconciliation"]["status"] == "NOT_COMPARABLE").all()


def test_mismatching_period_flagged(tmp_path):
    rows = [row("2026-09", "R1", "7", 1), row("2026-09", "TOTAL", "7", 2, True)]
    rows[0]["Period"] = "MSitAE-AUGUST-2026"
    result = validate_dataset(make_repo(tmp_path, rows))
    assert "PERIOD_SOURCE_MONTH_MISMATCH" in find_checks(result)


def test_missing_code_flagged(tmp_path):
    rows = [row("2026-09", "", "7", 1), row("2026-09", "TOTAL", "7", 2, True)]
    result = validate_dataset(make_repo(tmp_path, rows))
    assert "MISSING_ORG_CODE" in find_checks(result)


def test_duplicate_source_row_identifier_flagged(tmp_path):
    rows = [row("2026-09", "R1", "7", 1), row("2026-09", "TOTAL", "7", 1, True)]
    result = validate_dataset(make_repo(tmp_path, rows))
    assert "DUPLICATE_SOURCE_ORDINAL" in find_checks(result)


def test_continuity_gap_and_name_change_are_advisory(tmp_path):
    a = row("2026-07", "R1", "100", 1)
    b = row("2026-09", "R1", "300", 1)
    b["Org name"] = "RENAMED HOSPITAL"
    rows = [a, row("2026-07", "TOTAL", "100", 2, True),
            b, row("2026-09", "TOTAL", "300", 2, True)]
    result = validate_dataset(make_repo(tmp_path, rows))
    provider = result["continuity"].set_index("org_code").loc["R1"]
    assert int(provider["missing_within_span"]) == 1
    assert int(provider["distinct_provider_names"]) == 2
    assert result["summary"]["checks"]["providers_with_internal_month_gaps"] == 1


def test_large_change_candidate_without_auto_fix(tmp_path):
    rows = [row("2026-08", "R1", "1000", 1), row("2026-08", "TOTAL", "1000", 2, True),
            row("2026-09", "R1", "4000", 1), row("2026-09", "TOTAL", "4000", 2, True)]
    root = make_repo(tmp_path, rows)
    before = (root / "data/staging/ae_historical_raw_combined.csv").read_bytes()
    result = validate_dataset(root)
    after = (root / "data/staging/ae_historical_raw_combined.csv").read_bytes()
    assert before == after
    assert len(result["change_candidates"]) == 1
    assert result["summary"]["quality_gate"] == "PASS_CORE_CHECKS_WITH_ADVISORIES"


def test_wrong_schema_rejected(tmp_path):
    root = make_repo(tmp_path, [row("2026-09", "R1", "1", 1)])
    f = root / "data/staging/ae_historical_raw_combined.csv"
    content = pd.read_csv(f, dtype=str)
    content.drop(columns=["source_month"]).to_csv(f, index=False)
    with pytest.raises(ValueError, match="schema"):
        load_staged(root)


def test_reject_outputs_under_raw_dir(tmp_path):
    root = make_repo(tmp_path, [row("2026-09", "R1", "1", 1)])
    with pytest.raises(ValueError, match="data/raw"):
        validate_dataset(root, output_root=root / "data/raw/outputs")


def test_read_staged_relative_input(tmp_path):
    root = make_repo(tmp_path, [row("2026-09", "R1", "1", 1)])
    data, path = load_staged(root, Path("data/staging/ae_historical_raw_combined.csv"))
    assert len(data) == 1
    assert str(path).endswith("ae_historical_raw_combined.csv")


def test_manifest_provenance_verified(tmp_path):
    rows = [row("2026-09", "R1", "1", 1), row("2026-09", "TOTAL", "1", 2, True)]
    root = make_repo(tmp_path, rows)
    (root / "docs").mkdir(exist_ok=True)
    pd.DataFrame([{"source_file": rows[0]["source_file"], "sha256": "b" * 64,
                   "content_month": "2026-09", "data_rows": "2"}]).to_csv(root / "docs/source_manifest.csv", index=False)
    result = validate_dataset(root)
    assert result["summary"]["checks"]["m01_manifest_check"] == "MISMATCH"
    assert "M01_M02_PROVENANCE_MISMATCH" in find_checks(result)


def test_manifest_coverage_absent_month_is_blocking(tmp_path):
    rows = [row("2026-09", "R1", "1", 1), row("2026-09", "TOTAL", "1", 2, True)]
    root = make_repo(tmp_path, rows)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/m01_coverage.json").write_text(json.dumps({
        "start_month": "2026-08", "end_month": "2026-09"
    }))
    result = validate_dataset(root)
    assert result["summary"]["checks"]["m01_month_coverage_check"] == "MISMATCH"
    assert "M01_M02_MONTH_COVERAGE_MISMATCH" in find_checks(result)
    assert result["summary"]["quality_gate"] == "REVIEW_REQUIRED"


def test_m02_count_summary_mismatch(tmp_path):
    rows = [row("2026-09", "R1", "1", 1), row("2026-09", "TOTAL", "1", 2, True)]
    root = make_repo(tmp_path, rows)
    (root / "data/staging/m02_ingestion_summary.json").write_text(json.dumps({
        "combined_rows_including_totals": 999,
        "national_total_rows_retained": 1,
    }))
    result = validate_dataset(root)
    assert "M02_SUMMARY_MISMATCH" in find_checks(result)
    assert result["summary"]["quality_gate"] == "REVIEW_REQUIRED"
