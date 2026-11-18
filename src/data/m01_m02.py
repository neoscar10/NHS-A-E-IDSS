"""M01 source inventory + M02 lossless-value ingestion for NHS monthly A&E CSVs.

Read-only with respect to data/raw. No imputation, total-row deletion,
feature engineering, or modelling is performed in these milestones.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_URL = "https://github.com/neoscar10/NHS-A-E-IDSS"
EXPECTED_COLUMNS = [
    "Period", "Org Code", "Parent Org", "Org name",
    "A&E attendances Type 1", "A&E attendances Type 2",
    "A&E attendances Other A&E Department",
    "A&E attendances Booked Appointments Type 1",
    "A&E attendances Booked Appointments Type 2",
    "A&E attendances Booked Appointments Other Department",
    "Attendances over 4hrs Type 1", "Attendances over 4hrs Type 2",
    "Attendances over 4hrs Other Department",
    "Attendances over 4hrs Booked Appointments Type 1",
    "Attendances over 4hrs Booked Appointments Type 2",
    "Attendances over 4hrs Booked Appointments Other Department",
    "Patients who have waited 4-12 hs from DTA to admission",
    "Patients who have waited 12+ hrs from DTA to admission",
    "Emergency admissions via A&E - Type 1",
    "Emergency admissions via A&E - Type 2",
    "Emergency admissions via A&E - Other A&E department",
    "Other emergency admissions",
]
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
ABBREV = {x[:3]: v for x, v in MONTHS.items()}


def is_total_record(row: dict[str, str]) -> bool:
    """Case/space-tolerant identification; does not remove the row."""
    return any(str(row.get(field, "")).strip().upper() == "TOTAL"
               for field in ("Org Code", "Org name"))


def period_month(value: str) -> str | None:
    """Parse 'MSitAE-SEPTEMBER-2026' as '2026-09'; not a forecast date."""
    match = re.fullmatch(r"\s*MSitAE-([A-Za-z]+)-(20\d{2})\s*", str(value), re.I)
    if not match:
        return None
    month = MONTHS.get(match.group(1).lower())
    return f"{match.group(2)}-{month:02d}" if month else None


def filename_month(path: Path) -> str | None:
    """Extract a month/year if explicitly encoded in the source filename."""
    pattern = r"(?i)(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[\s_-]+(20\d{2}|\d{2})(?!\d)"
    match = re.search(pattern, path.stem)
    if not match:
        return None
    name, year = match.groups()
    month = MONTHS.get(name.lower()) or ABBREV.get(name.lower()[:3])
    year_num = int(year) if len(year) == 4 else 2000 + int(year)
    return f"{year_num}-{month:02d}" if month else None


def sha256_file(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def inventory_file(path: Path, repo_root: Path) -> dict:
    """Inspect a CSV without changing it; retain warnings for later milestones."""
    source_path = path.relative_to(repo_root).as_posix()
    result = {
        "source_file": source_path,
        "source_url": f"{PROJECT_URL}/blob/main/{source_path}",
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "filename_month": filename_month(path),
        "folder_year": path.parent.name,
        "header_columns": "",
        "column_count": 0,
        "schema_matches_expected": False,
        "ignored_trailing_empty_columns": 0,
        "nonempty_trailing_cells": 0,
        "warnings": "",
        "data_rows": 0,
        "provider_rows": 0,
        "total_rows": 0,
        "empty_rows": 0,
        "row_width_errors": 0,
        "distinct_provider_periods": 0,
        "content_month": "",
        "status": "",
        "issues": "",
    }
    issues = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            header = next(reader)
            result["header_columns"] = " | ".join(header)
            result["column_count"] = len(header)
            # The NHS September 2024 release includes six extra trailing
            # columns (five blank headers and one labelled 'a'). Accept them
            # only when *every* data cell in those columns is empty.
            canonical_prefix = header[:len(EXPECTED_COLUMNS)] == EXPECTED_COLUMNS
            extra_count = max(0, len(header) - len(EXPECTED_COLUMNS))
            has_trailing_columns = canonical_prefix and extra_count > 0
            if header != EXPECTED_COLUMNS and not has_trailing_columns:
                issues.append("SCHEMA_MISMATCH")
            index = {name: i for i, name in enumerate(header)}
            found_periods = set()
            for values in reader:
                if not values or all(not v.strip() for v in values):
                    result["empty_rows"] += 1
                    continue
                result["data_rows"] += 1
                if len(values) != len(header):
                    result["row_width_errors"] += 1
                    continue
                if has_trailing_columns:
                    result["nonempty_trailing_cells"] += sum(
                        bool(value.strip()) for value in values[len(EXPECTED_COLUMNS):]
                    )
                row = dict(zip(header, values))
                if is_total_record(row):
                    result["total_rows"] += 1
                else:
                    result["provider_rows"] += 1
                    if "Period" in index:
                        found_periods.add(row["Period"].strip())
            if has_trailing_columns:
                if result["nonempty_trailing_cells"]:
                    issues.append("NONEMPTY_EXTRA_COLUMNS")
                    issues.append("SCHEMA_MISMATCH")
                else:
                    result["ignored_trailing_empty_columns"] = extra_count
                    result["warnings"] = f"TRAILING_EMPTY_SOURCE_COLUMNS:{extra_count}"
            result["schema_matches_expected"] = (
                header == EXPECTED_COLUMNS or
                (has_trailing_columns and result["nonempty_trailing_cells"] == 0
                 and result["row_width_errors"] == 0)
            )
            result["distinct_provider_periods"] = len(found_periods)
            parsed_periods = {period_month(p) for p in found_periods}
            if len(parsed_periods) == 1 and None not in parsed_periods:
                result["content_month"] = next(iter(parsed_periods))
            else:
                issues.append("UNPARSABLE_OR_MIXED_PERIOD")
            if result["content_month"] != result["filename_month"]:
                issues.append("FILENAME_CONTENT_PERIOD_MISMATCH")
            if result["content_month"] and not result["content_month"].startswith(f'{result["folder_year"]}-'):
                issues.append("FOLDER_YEAR_CONTENT_MISMATCH")
            if result["row_width_errors"]:
                issues.append("ROW_WIDTH_ERROR")
            if result["total_rows"] != 1:
                issues.append("TOTAL_ROW_COUNT_NOT_ONE")
            if result["empty_rows"]:
                issues.append("EMPTY_CSV_ROWS")
    except (OSError, UnicodeError, csv.Error, StopIteration) as exc:
        issues.append(f"READ_ERROR:{type(exc).__name__}")
    result["issues"] = ";".join(issues)
    result["status"] = "PASS_PRELIMINARY" if not issues else "REVIEW_REQUIRED"
    return result


def expected_months(start: str, end: str) -> list[str]:
    a, b = pd.Period(start, freq="M"), pd.Period(end, freq="M")
    if b < a:
        raise ValueError("End month must not precede start month")
    return [str(p) for p in pd.period_range(a, b, freq="M")]


def build_manifest(repo_root: Path, output_dir: Path, start: str, end: str) -> tuple[pd.DataFrame, dict]:
    """M01: source inventory and basic coverage checks. Writes only to output_dir."""
    repo_root = repo_root.resolve()
    source_dir = repo_root / "data" / "raw"
    if not source_dir.is_dir():
        raise FileNotFoundError(f"NHS source folder missing: {source_dir}")
    files = sorted(source_dir.glob("20[0-9][0-9]/*.csv"), key=lambda p: (filename_month(p) or "9999-99", p.name))
    if not files:
        raise FileNotFoundError(f"No monthly CSVs found in {source_dir}/YYYY/")
    entries = [inventory_file(path, repo_root) for path in files]
    manifest = pd.DataFrame(entries)
    months = manifest["content_month"].dropna().tolist()
    month_counts = Counter(months)
    wanted = set(expected_months(start, end))
    found = set(x for x in months if x)
    coverage = {
        "repository": PROJECT_URL,
        "start_month": start,
        "end_month": end,
        "expected_months": len(wanted),
        "source_files": len(manifest),
        "unique_content_months": len(found),
        "missing_months": sorted(wanted - found),
        "unexpected_months": sorted(found - wanted),
        "duplicate_months": sorted(k for k, n in month_counts.items() if n > 1 and k),
        "preliminary_review_files": int((manifest["status"] != "PASS_PRELIMINARY").sum()),
        "source_format_warning_files": int((manifest["warnings"] != "").sum()),
        "trailing_empty_source_columns_ignored": int(manifest["ignored_trailing_empty_columns"].sum()),
        "total_csv_data_rows": int(manifest["data_rows"].sum()),
        "total_provider_rows": int(manifest["provider_rows"].sum()),
        "total_aggregate_rows": int(manifest["total_rows"].sum()),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(output_dir / "source_manifest.csv", index=False)
    (output_dir / "m01_coverage.json").write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    return manifest, coverage


def ingest_historical(repo_root: Path, manifest: pd.DataFrame, staging_dir: Path) -> tuple[pd.DataFrame, dict]:
    """M02: combine source values without cleaning, excluding or converting measures."""
    source_frames = []
    for entry in manifest.to_dict(orient="records"):
        if entry["status"] != "PASS_PRELIMINARY":
            raise ValueError(f"M02 stopped: M01 review required for {entry['source_file']} ({entry['issues']})")
        path = repo_root / entry["source_file"]
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"Source changed after M01 inventory: {path}")
        # Discard only trailing source columns proven empty by the M01 scan.
        # The first 22 NHS measure/identity columns are kept as original strings.
        allowed_extra = int(entry.get("ignored_trailing_empty_columns", 0))
        columns_to_read = list(range(len(EXPECTED_COLUMNS))) if allowed_extra else None
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False,
                         na_filter=False, low_memory=False, on_bad_lines="error",
                         usecols=columns_to_read)
        if list(df.columns) != EXPECTED_COLUMNS:
            raise ValueError(f"Unexpected header on {entry['source_file']}")
        if len(df) != int(entry["data_rows"]):
            raise ValueError(f"Row count differs from M01 for {entry['source_file']}")
        # Metadata is additive: source column values and national TOTAL rows stay untouched.
        df["source_month"] = entry["content_month"]
        df["source_file"] = entry["source_file"]
        df["source_sha256"] = entry["sha256"]
        df["source_record_number"] = range(1, len(df) + 1)
        source_frames.append(df)
    combined = pd.concat(source_frames, ignore_index=True)
    if len(combined) != int(manifest["data_rows"].sum()):
        raise AssertionError("Combined row count does not match source inventory")
    staging_dir.mkdir(parents=True, exist_ok=True)
    csv_path = staging_dir / "ae_historical_raw_combined.csv"
    combined.to_csv(csv_path, index=False)
    parquet_path = staging_dir / "ae_historical_raw_combined.parquet"
    parquet_status = "exported"
    try:
        combined.to_parquet(parquet_path, index=False)
    except (ImportError, ModuleNotFoundError):
        parquet_status = "skipped: pyarrow or fastparquet unavailable"
    summary = {
        "source_files": int(len(manifest)),
        "combined_rows_including_totals": int(len(combined)),
        "provider_rows": int(manifest["provider_rows"].sum()),
        "national_total_rows_retained": int(manifest["total_rows"].sum()),
        "original_source_columns": len(EXPECTED_COLUMNS),
        "additive_provenance_columns": 4,
        "source_format_warning_files": int((manifest["warnings"] != "").sum()),
        "trailing_empty_source_columns_ignored": int(manifest["ignored_trailing_empty_columns"].sum()),
        "output_columns": len(combined.columns),
        "note": "M01/M02 only: no filtering, imputation, type conversion of source measures, or forecasting",
        "parquet_status": parquet_status,
        "combined_csv": str(csv_path),
    }
    (staging_dir / "m02_ingestion_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return combined, summary


def run_pipeline(repo_root: Path, output_root: Path | None = None,
                 start: str = "2022-01", end: str = "2026-09",
                 strict_coverage: bool = True) -> dict:
    """Run M01 then M02. Output folders are kept outside raw/, and never overwrite source files."""
    repo_root = Path(repo_root).resolve()
    output_root = Path(output_root).resolve() if output_root else repo_root
    raw_dir = (repo_root / "data" / "raw").resolve()
    if output_root == raw_dir or raw_dir in output_root.parents:
        raise ValueError("Output cannot be inside the raw source directory")
    manifest, coverage = build_manifest(repo_root, output_root / "docs", start, end)
    if strict_coverage and (coverage["missing_months"] or coverage["unexpected_months"] or coverage["duplicate_months"]):
        raise ValueError(f"M01 month coverage incomplete/duplicated; inspect {output_root / 'docs' / 'm01_coverage.json'}")
    combined, summary = ingest_historical(repo_root, manifest, output_root / "data" / "staging")
    return {"m01": coverage, "m02": summary, "combined": combined, "manifest": manifest}


def cli() -> None:
    parser = argparse.ArgumentParser(description="NHS A&E M01 inventory and M02 ingestion")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Path to the cloned NHS-A-E-IDSS repository")
    parser.add_argument("--output", type=Path, default=None, help="Destination root for outputs, default same repo")
    parser.add_argument("--start", default="2022-01")
    parser.add_argument("--end", default="2026-09")
    parser.add_argument("--allow-coverage-gaps", action="store_true")
    args = parser.parse_args()
    result = run_pipeline(args.repo, args.output, args.start, args.end, not args.allow_coverage_gaps)
    print(json.dumps({"m01": result["m01"], "m02": result["m02"]}, indent=2))


if __name__ == "__main__":
    cli()
