"""Synthetic fixture tests for source inventory and ingestion (no real NHS claims)."""
import csv
import hashlib
from pathlib import Path

import pytest

from src.data.data_ingestion import (
    EXPECTED_COLUMNS, build_manifest, filename_month, ingest_historical,
    is_total_record, period_month, run_pipeline,
)


def _row(month: str, code: str, name: str, count: str) -> list[str]:
    values = [month, code, "NHS ENGLAND TEST", name] + ["0"] * 18
    values[4] = count
    return values


def _pin_sources(repo):
    import json
    from src.data.source_integrity import REGISTER, git_blob_sha
    path = repo / REGISTER
    path.parent.mkdir(parents=True, exist_ok=True)
    files = [{'path': p.relative_to(repo).as_posix(), 'git_blob_sha1': git_blob_sha(p.read_bytes())}
             for p in sorted((repo / 'data/raw').rglob('*.csv'))]
    path.write_text(json.dumps({'source_version': 'synthetic-fixture', 'files': files}), encoding='utf-8')


def _fixture(repo: Path, months=("JANUARY", "FEBRUARY")):
    for number, month in enumerate(months, start=1):
        path = repo / "data" / "raw" / "2022" / f"{month.title()}-2022-synthetic.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(EXPECTED_COLUMNS)
            period = f"MSitAE-{month}-2022"
            writer.writerow(_row(period, f"R0{number}", "Fictional Provider", str(100 * number)))
            writer.writerow(_row(" Total ", " Total ", "Total", str(100 * number)))
    _pin_sources(repo)
    return repo


def test_period_parsing():
    assert period_month("MSitAE-SEPTEMBER-2026") == "2026-09"
    assert period_month("TOTAL") is None
    assert filename_month(Path("Monthly-AE-Nov-25-CSV-revised.csv")) == "2025-11"


def test_total_variants():
    assert is_total_record({"Org Code": " Total ", "Org name": "anything"})
    assert is_total_record({"Org Code": "ABC", "Org name": "TOTAL"})
    assert not is_total_record({"Org Code": "ABC", "Org name": "General Hospital"})


def test_inventory_and_ingestion(tmp_path):
    repo = _fixture(tmp_path / "source")
    original_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (repo / "data" / "raw").rglob("*.csv")}
    output = tmp_path / "outputs"
    result = run_pipeline(repo, output, "2022-01", "2022-02")
    assert result["m01"]["source_files"] == 2
    assert result["m01"]["missing_months"] == []
    assert result["m01"]["total_provider_rows"] == 2
    assert result["m02"]["combined_rows_including_totals"] == 4
    df = result["combined"]
    assert list(df.columns[:22]) == EXPECTED_COLUMNS
    assert len(df.columns) == 26
    assert df["A&E attendances Type 1"].tolist() == ["100", "100", "200", "200"]
    assert df["source_month"].tolist() == ["2022-01", "2022-01", "2022-02", "2022-02"]
    assert df["source_record_number"].tolist() == [1, 2, 1, 2]
    assert (output / "docs" / "source_manifest.csv").exists()
    assert (output / "data" / "staging" / "ae_historical_raw_combined.csv").exists()
    assert all(original_hashes[p.name] == hashlib.sha256(p.read_bytes()).hexdigest()
               for p in (repo / "data" / "raw").rglob("*.csv"))


def test_missing_month_blocks_strict_ingestion(tmp_path):
    repo = _fixture(tmp_path / "source", months=("JANUARY",))
    with pytest.raises(ValueError, match="month coverage"):
        run_pipeline(repo, tmp_path / "output", "2022-01", "2022-02")
    assert (tmp_path / "output" / "docs" / "source_manifest.csv").exists()


def test_schema_error_detected_without_corrupting_sources(tmp_path):
    repo = _fixture(tmp_path / "source", months=("JANUARY",))
    path = next((repo / "data" / "raw").rglob("*.csv"))
    data = path.read_text(encoding="utf-8").replace("A&E attendances Type 1", "incorrect column", 1)
    path.write_text(data, encoding="utf-8")
    manifest, coverage = build_manifest(repo, tmp_path / "output" / "docs", "2022-01", "2022-01")
    assert manifest.iloc[0]["status"] == "REVIEW_REQUIRED"
    with pytest.raises(ValueError, match="review required"):
        ingest_historical(repo, manifest, tmp_path / "output" / "data" / "staging")


def test_changed_file_after_inventory_blocks_ingestion(tmp_path):
    repo = _fixture(tmp_path / "source", months=("JANUARY",))
    manifest, _ = build_manifest(repo, tmp_path / "output" / "docs", "2022-01", "2022-01")
    path = next((repo / "data" / "raw").rglob("*.csv"))
    with path.open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="changed after M01"):
        ingest_historical(repo, manifest, tmp_path / "output" / "data" / "staging")


def test_trailing_empty_source_columns_handled_safely(tmp_path):
    repo = _fixture(tmp_path / "source", months=("JANUARY",))
    path = next((repo / "data" / "raw").rglob("*.csv"))
    # Mirrors the September 2024 problem: six extra fields, last header 'a'.
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    rows[0] += ["", "", "", "", "", "a"]
    for row in rows[1:]:
        row.extend([""] * 6)
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    original_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    _pin_sources(repo)

    result = run_pipeline(repo, tmp_path / "out", "2022-01", "2022-01")
    entry = result["manifest"].iloc[0]
    assert entry["status"] == "PASS_PRELIMINARY"
    assert entry["column_count"] == 28
    assert entry["ignored_trailing_empty_columns"] == 6
    assert entry["warnings"] == "TRAILING_EMPTY_SOURCE_COLUMNS:6"
    assert result["m01"]["source_format_warning_files"] == 1
    assert result["m02"]["combined_rows_including_totals"] == 2
    assert list(result["combined"].columns[:22]) == EXPECTED_COLUMNS
    assert len(result["combined"].columns) == 26
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_sha256


def test_nonempty_trailing_columns_block_ingestion(tmp_path):
    repo = _fixture(tmp_path / "source", months=("JANUARY",))
    path = next((repo / "data" / "raw").rglob("*.csv"))
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    rows[0].extend(["", "a"])
    rows[1].extend(["", "not empty"])
    rows[2].extend(["", ""])
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    manifest, _ = build_manifest(repo, tmp_path / "out" / "docs", "2022-01", "2022-01")
    entry = manifest.iloc[0]
    assert entry["status"] == "REVIEW_REQUIRED"
    assert "NONEMPTY_EXTRA_COLUMNS" in entry["issues"]
    assert entry["nonempty_trailing_cells"] == 1
    with pytest.raises(ValueError, match="review required"):
        ingest_historical(repo, manifest, tmp_path / "out" / "data" / "staging")
