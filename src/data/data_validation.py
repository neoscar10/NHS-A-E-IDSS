"""M03: read-only quality validation of M01/M02 NHS England monthly A&E data.

Input: data/staging/ae_historical_raw_combined.parquet (or .csv)
Outputs: docs/m03_*.csv/json/md and data/quality/m03_findings.csv.

Does not modify data/raw, the staged source, or any source measurements.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

if __package__:
    from .data_ingestion import EXPECTED_COLUMNS, expected_months, period_month
else:
    from data_ingestion import EXPECTED_COLUMNS, expected_months, period_month

PROVENANCE = ["source_month", "source_file", "source_sha256", "source_record_number"]
IDENTITY = EXPECTED_COLUMNS[:4]
MEASURES = EXPECTED_COLUMNS[4:]
OUTPUTS = {
    "summary": "docs/m03_quality_summary.json",
    "report": "docs/m03_quality_report.md",
    "findings": "data/quality/m03_findings.csv",
    "monthly": "docs/m03_monthly_profile.csv",
    "reconciliation": "docs/m03_monthly_reconciliation.csv",
    "continuity": "docs/m03_provider_continuity.csv",
    "changes": "docs/m03_type1_change_candidates.csv",
}


def load_staged(repo_root: Path, input_path: Path | None = None) -> tuple[pd.DataFrame, Path]:
    """Load original strings, maintaining empty strings distinct from numeric zero."""
    if input_path is None:
        parquet = repo_root / "data/staging/ae_historical_raw_combined.parquet"
        csv_path = repo_root / "data/staging/ae_historical_raw_combined.csv"
        path = csv_path if csv_path.exists() else parquet
    else:
        path = Path(input_path)
        path = path.resolve() if path.is_absolute() else (repo_root / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Staged M02 data not found: {path}. Run M01/M02 first.")
    if path.suffix.lower() == ".parquet":
        data = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        data = pd.read_csv(path, dtype=str, encoding="utf-8-sig", na_filter=False,
                           keep_default_na=False, low_memory=False)
    else:
        raise ValueError("M03 input must be .csv or .parquet")
    expected = EXPECTED_COLUMNS + PROVENANCE
    if list(data.columns) != expected:
        missing = sorted(set(expected) - set(data.columns))
        additional = sorted(set(data.columns) - set(expected))
        raise ValueError(f"M02 schema differs from expected 26 fields. Missing={missing}; extra={additional}")
    # Source values retain textual representation; this working copy can be examined safely.
    data = data.astype("string").fillna("")
    return data, path


def is_total_series(data: pd.DataFrame) -> pd.Series:
    code = data["Org Code"].str.strip().str.upper()
    name = data["Org name"].str.strip().str.upper()
    return code.eq("TOTAL") | name.eq("TOTAL")


def _json_write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, default=str, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_dataset(repo_root: Path, input_path: Path | None = None,
                     output_root: Path | None = None, *, verify_source: bool = True) -> dict:
    """Profile and report all issues without fixing or filtering any source records.

    Returns a dict containing summary, monthly, reconciliation, continuity,
    change_candidates, findings (all pandas DataFrames except summary).
    """
    repo_root = Path(repo_root).resolve()
    output_root = Path(output_root).resolve() if output_root else repo_root
    raw_dir = (repo_root / "data/raw").resolve()
    if output_root == raw_dir or raw_dir in output_root.parents:
        raise ValueError("Outputs must not be placed under data/raw")
    data, source = load_staged(repo_root, input_path)
    identity = {'source_to_staging_check': 'NOT_PERFORMED'}
    if verify_source:
        if __package__:
            from .source_integrity import verify_source_to_staging
        else:
            from source_integrity import verify_source_to_staging
        alternate = repo_root / ('data/staging/ae_historical_raw_combined.parquet' if source.suffix.lower() == '.csv' else 'data/staging/ae_historical_raw_combined.csv')
        identity = verify_source_to_staging(repo_root, data, other_path=alternate)
    source_label = source.relative_to(repo_root).as_posix() if source.is_relative_to(repo_root) else source.name
    total = is_total_series(data)
    provider = ~total
    code = data["Org Code"].str.strip().str.upper()
    name = data["Org name"].str.strip()
    parent = data["Parent Org"].str.strip()
    month = data["source_month"].str.strip()
    numeric: dict[str, pd.Series] = {}
    valid_numeric: dict[str, pd.Series] = {}
    finding_rows: list[dict] = []

    def record(check: str, severity: str, mask: pd.Series, field: str,
               message: str, evidence_limit: int = 3) -> None:
        """Compact grouped findings, with representative record IDs for traceability."""
        selected = data.loc[mask.fillna(False), ["source_month", "Org Code", "source_file", "source_record_number"]]
        if selected.empty:
            return
        for observed_month, subset in selected.groupby("source_month", sort=True):
            sample = [f"{r['Org Code'].strip()}@{r['source_file']}#{r['source_record_number']}"
                      for _, r in subset.head(evidence_limit).iterrows()]
            finding_rows.append({"check": check, "severity": severity,
                                 "source_month": str(observed_month), "field": field,
                                 "affected_rows": int(len(subset)),
                                 "sample_records": " | ".join(sample), "meaning": message})

    # A. Provenance, dates and identity.
    month_valid = month.str.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])").fillna(False)
    record("INVALID_SOURCE_MONTH", "ERROR", ~month_valid, "source_month", "Month must be YYYY-MM")
    record("MISSING_ORG_CODE", "ERROR", provider & code.eq(""), "Org Code", "Provider code is required")
    record("MISSING_ORG_NAME", "ERROR", provider & name.eq(""), "Org name", "Provider name is required")
    record("MISSING_PARENT_ORG", "WARNING", provider & parent.eq(""), "Parent Org", "Missing regional grouping")
    record("MISSING_SOURCE_FILE", "ERROR", data["source_file"].str.strip().eq(""), "source_file", "Source file missing")
    record("INVALID_SOURCE_SHA256", "ERROR",
           ~data["source_sha256"].str.strip().str.fullmatch(r"[0-9a-fA-F]{64}").fillna(False),
           "source_sha256", "Expected SHA-256 string")
    record("INVALID_SOURCE_RECORD_NUMBER", "ERROR",
           ~data["source_record_number"].str.strip().str.fullmatch(r"[1-9]\d*").fillna(False),
           "source_record_number", "Expected positive source row ordinal")
    source_duplicate = data.duplicated(["source_file", "source_record_number"], keep=False)
    record("DUPLICATE_SOURCE_ORDINAL", "ERROR", source_duplicate, "source_file+source_record_number",
           "A source record was included multiple times")
    key_dup = provider & data.assign(_m=month, _c=code).duplicated(["_m", "_c"], keep=False) & code.ne("")
    record("DUPLICATE_PROVIDER_MONTH_KEY", "ERROR", key_dup, "source_month+Org Code",
           "More than one provider row shares the same code in a month")
    derived = data.loc[provider, "Period"].map(period_month)
    period_issue = pd.Series(False, index=data.index)
    period_issue.loc[provider] = derived.isna() | derived.ne(month.loc[provider])
    record("PERIOD_SOURCE_MONTH_MISMATCH", "ERROR", period_issue, "Period",
           "Provider Period must equal source_month")
    # The folder/filename should refer to the same month where extract filenames encode it;
    # M01 checks month from filename, M03 checks consistency of the derived provenance.
    folder_year = data["source_file"].str.extract(r"^data/raw/(20\d{2})/[^/]+\.csv$", expand=False)
    record("SOURCE_PATH_YEAR_MISMATCH", "ERROR",
           folder_year.isna() | folder_year.ne(month.str[:4]), "source_file",
           "Source path must be data/raw/YYYY/*.csv with matching source_month")
    # B. Validate all published counts as nonnegative, whole-number values.
    for field in MEASURES:
        values = data[field].str.strip()
        is_blank = values.eq("")
        is_integer = values.str.fullmatch(r"\d+").fillna(False)
        negatives = values.str.fullmatch(r"-\d+").fillna(False)
        record("MISSING_COUNT", "ERROR", is_blank, field, "Published count is blank, not zero")
        record("NEGATIVE_COUNT", "ERROR", negatives, field, "Published counts cannot be negative")
        record("NON_INTEGER_COUNT", "ERROR", (~is_integer) & ~negatives & ~is_blank,
               field, "Published counts must be non-negative whole numbers")
        numbers = pd.to_numeric(values.where(is_integer), errors="coerce")
        overflow = is_integer & numbers.isna()
        record("COUNT_OUT_OF_RANGE", "ERROR", overflow, field, "Count could not be represented numerically")
        numeric[field] = numbers
        valid_numeric[field] = is_integer & ~overflow

    # C. National reconciliation, one national TOTAL per month, for every numeric measure.
    months = sorted(month.loc[month_valid].unique().tolist())
    row_count = Counter(month.tolist())
    total_count = Counter(month.loc[total].tolist())
    monthly_rows = []
    recon_rows = []
    for m in months:
        subset = month.eq(m)
        p_mask = subset & provider
        t_mask = subset & total
        t_count = int(t_mask.sum())
        if t_count != 1:
            record("INVALID_TOTAL_ROW_COUNT", "ERROR", subset, "Org Code",
                   "Expected exactly one national TOTAL record per reporting month")
        zero_type1 = p_mask & valid_numeric[MEASURES[0]] & numeric[MEASURES[0]].eq(0)
        monthly_rows.append({
            "source_month": m, "rows_including_total": row_count[m],
            "provider_rows": int(p_mask.sum()), "national_total_rows": t_count,
            "unique_provider_codes": int(code.loc[p_mask].loc[code.loc[p_mask].ne("")].nunique()),
            "type1_zero_provider_rows": int(zero_type1.sum()),
            "type1_zero_provider_share": round(float(zero_type1.sum() / p_mask.sum()), 5) if p_mask.sum() else None,
            "type1_provider_sum_if_valid": (int(numeric[MEASURES[0]].loc[p_mask].sum())
                                            if valid_numeric[MEASURES[0]].loc[p_mask].all() else None),
        })
        for field in MEASURES:
            complete = (t_count == 1 and bool(valid_numeric[field].loc[subset].all()))
            if complete:
                p_sum = int(numeric[field].loc[p_mask].sum())
                total_val = int(numeric[field].loc[t_mask].iloc[0])
                diff = p_sum - total_val
                status = "MATCH" if diff == 0 else "MISMATCH"
                if diff:
                    record("NATIONAL_TOTAL_MISMATCH", "ERROR", t_mask, field,
                           "Sum of provider counts differs from the published national total")
            else:
                p_sum, total_val, diff, status = None, None, None, "NOT_COMPARABLE"
            recon_rows.append({"source_month": m, "measure": field,
                               "provider_sum": p_sum, "national_total": total_val,
                               "difference_provider_minus_total": diff,
                               "status": status})

    # M02/M01 ingest cross-check; does not rely on matching user data to sample fixtures.
    m02_path = repo_root / "data/staging/m02_ingestion_summary.json"
    m02_check = "NOT_AVAILABLE"
    if m02_path.exists():
        m02 = json.loads(m02_path.read_text(encoding="utf-8"))
        m02_check = "MATCH" if (int(m02.get("combined_rows_including_totals", -1)) == len(data) and
                               int(m02.get("national_total_rows_retained", -1)) == int(total.sum())) else "MISMATCH"
    if m02_check == "MISMATCH":
        record("M02_SUMMARY_MISMATCH", "ERROR", pd.Series(True, index=data.index),
               "m02_ingestion_summary.json", "M02 recorded row counts disagree with staged file")

    # Cross-check the staged data against M01's file/coverage manifest, when present.
    manifest_path = repo_root / "docs/source_manifest.csv"
    manifest_check = "NOT_AVAILABLE"
    if manifest_path.exists():
        manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
        manifest_check = "MATCH"
        if not {"source_file", "sha256", "content_month", "data_rows"}.issubset(manifest.columns):
            manifest_check = "INVALID_MANIFEST_SCHEMA"
            finding_rows.append({"check": "M01_MANIFEST_SCHEMA", "severity": "ERROR", "source_month": "",
                                 "field": "source_manifest.csv", "affected_rows": 1,
                                 "sample_records": str(manifest_path), "meaning": "Required M01 manifest fields are missing"})
        else:
            actual_files = set(data["source_file"].unique().tolist())
            expected_files = set(manifest["source_file"].tolist())
            for missing_file in sorted(expected_files - actual_files):
                manifest_check = "MISMATCH"
                m = manifest.loc[manifest["source_file"] == missing_file, "content_month"].iloc[0]
                finding_rows.append({"check": "M01_FILE_MISSING_IN_M02", "severity": "ERROR", "source_month": m,
                                     "field": "source_file", "affected_rows": 1,
                                     "sample_records": missing_file, "meaning": "File in M01 manifest absent from combined M02 data"})
            for extra_file in sorted(actual_files - expected_files):
                manifest_check = "MISMATCH"
                record("M02_FILE_NOT_IN_M01", "ERROR", data["source_file"].eq(extra_file),
                       "source_file", "Combined source_file is not listed by M01")
            for _, entry in manifest.iterrows():
                filename = entry["source_file"]
                if filename not in actual_files:
                    continue
                selected = data["source_file"].eq(filename)
                count_ok = int(selected.sum()) == int(entry["data_rows"])
                hash_ok = (data.loc[selected, "source_sha256"] == entry["sha256"]).all()
                month_ok = (data.loc[selected, "source_month"] == entry["content_month"]).all()
                if not (count_ok and hash_ok and month_ok):
                    manifest_check = "MISMATCH"
                    record("M01_M02_PROVENANCE_MISMATCH", "ERROR", selected, "source_file",
                           "Source count, content month or SHA-256 differs from M01 manifest")
    coverage_path = repo_root / "docs/m01_coverage.json"
    coverage_check = "NOT_AVAILABLE"
    if coverage_path.exists():
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        wanted = set(expected_months(coverage["start_month"], coverage["end_month"]))
        observed = set(months)
        missing = sorted(wanted - observed)
        extra = sorted(observed - wanted)
        coverage_check = "MISMATCH" if missing or extra else "MATCH"
        if missing or extra:
            finding_rows.append({"check": "M01_M02_MONTH_COVERAGE_MISMATCH", "severity": "ERROR",
                                 "source_month": "", "field": "source_month",
                                 "affected_rows": len(missing) + len(extra),
                                 "sample_records": f"missing={missing[:8]}, unexpected={extra[:8]}",
                                 "meaning": "Reporting months disagree with M01 expected coverage"})

    # D. Longitudinal provider continuity: flags only, not automatic deletion.
    p = data.loc[provider & code.ne("") & month_valid, ["source_month", "Org name", "Org Code"]].copy()
    p["key"] = code.loc[p.index].to_numpy()
    p["normalised_name"] = name.loc[p.index].str.upper().to_numpy()
    p["type1"] = numeric[MEASURES[0]].loc[p.index].to_numpy()
    continuum = []
    changes = []
    for provider_code, group in p.groupby("key", sort=True):
        # Duplicates have already been reported; unique month counts are used for audit.
        observed = sorted(group["source_month"].drop_duplicates().tolist())
        in_span = expected_months(observed[0], observed[-1])
        gaps = sorted(set(in_span) - set(observed))
        names = sorted(group["normalised_name"].dropna().unique().tolist())
        type1_vals = pd.to_numeric(group["type1"], errors="coerce")
        continuum.append({"org_code": provider_code, "first_month": observed[0],
                          "last_month": observed[-1], "observed_months": len(observed),
                          "months_in_span": len(in_span), "missing_within_span": len(gaps),
                          "missing_months_example": " | ".join(gaps[:10]),
                          "distinct_provider_names": len(names),
                          "name_change_flag": len(names) > 1,
                          "zero_type1_observations": int(type1_vals.eq(0).sum()),
                          "nonzero_type1_observations": int(type1_vals.gt(0).sum())})
        # Screening for large relative *and* absolute consecutive-month changes.
        # They are review candidates, never assumed incorrect or automatically corrected.
        g = group.drop_duplicates("source_month").sort_values("source_month")
        for a, b in zip(g.to_dict("records"), g.to_dict("records")[1:]):
            if (pd.Period(b["source_month"], "M").ordinal -
                    pd.Period(a["source_month"], "M").ordinal) != 1:
                continue
            prev, curr = a["type1"], b["type1"]
            if pd.notna(prev) and pd.notna(curr) and float(prev) > 0:
                difference = float(curr) - float(prev)
                if abs(difference) >= 2000 and abs(difference / float(prev)) >= 1:
                    changes.append({"org_code": provider_code, "previous_month": a["source_month"],
                                    "current_month": b["source_month"], "previous_type1": int(prev),
                                    "current_type1": int(curr), "absolute_change": int(difference),
                                    "relative_change": round(difference / float(prev), 4)})

    continuity_df = pd.DataFrame(continuum, columns=["org_code", "first_month", "last_month", "observed_months",
        "months_in_span", "missing_within_span", "missing_months_example", "distinct_provider_names",
        "name_change_flag", "zero_type1_observations", "nonzero_type1_observations"])
    candidates_df = pd.DataFrame(changes, columns=["org_code", "previous_month", "current_month", "previous_type1",
        "current_type1", "absolute_change", "relative_change"])
    findings_df = pd.DataFrame(finding_rows, columns=["check", "severity", "source_month", "field",
        "affected_rows", "sample_records", "meaning"])
    monthly_df = pd.DataFrame(monthly_rows)
    recon_df = pd.DataFrame(recon_rows)
    error_rows = int(findings_df.loc[findings_df["severity"] == "ERROR", "affected_rows"].sum())
    failed_recon = int((recon_df["status"] == "MISMATCH").sum())
    incomplete_recon = int((recon_df["status"] == "NOT_COMPARABLE").sum())
    summary = {
        "source_input": source_label, "input_rows": int(len(data)),
        "source_integrity": identity,
        "source_columns": int(len(data.columns)),
        "provider_rows": int(provider.sum()), "aggregate_rows": int(total.sum()),
        "observed_months": len(months), "first_month": months[0] if months else None,
        "last_month": months[-1] if months else None,
        "expected_measure_columns": len(MEASURES),
        "checks": {"error_groups": int((findings_df["severity"] == "ERROR").sum()),
                   "error_affected_row_occurrences": error_rows,
                   "warning_groups": int((findings_df["severity"] == "WARNING").sum()),
                   "reconciliations_matched": int((recon_df["status"] == "MATCH").sum()),
                   "reconciliations_mismatched": failed_recon,
                   "reconciliations_not_comparable": incomplete_recon,
                   "providers_with_internal_month_gaps": int((continuity_df["missing_within_span"] > 0).sum()),
                   "providers_with_name_variants": int((continuity_df["distinct_provider_names"] > 1).sum()),
                   "type1_change_review_candidates": int(len(candidates_df)),
                   "m02_row_count_check": m02_check,
                   "m01_manifest_check": manifest_check,
                   "m01_month_coverage_check": coverage_check},
        "quality_gate": "REVIEW_REQUIRED" if (findings_df["severity"] == "ERROR").any() else "PASS_CORE_CHECKS_WITH_ADVISORIES",
        "method": "M03 audit only: no values corrected, no rows removed, no feature engineering",
    }
    # Exports: fixed names, clearly separated from staged and raw data.
    for rel in OUTPUTS.values():
        (output_root / rel).parent.mkdir(parents=True, exist_ok=True)
    _json_write(output_root / OUTPUTS["summary"], summary)
    findings_df.to_csv(output_root / OUTPUTS["findings"], index=False)
    monthly_df.to_csv(output_root / OUTPUTS["monthly"], index=False)
    recon_df.to_csv(output_root / OUTPUTS["reconciliation"], index=False)
    continuity_df.to_csv(output_root / OUTPUTS["continuity"], index=False)
    candidates_df.to_csv(output_root / OUTPUTS["changes"], index=False)
    dominant = findings_df.groupby(["check", "severity"], as_index=False)["affected_rows"].sum().sort_values(
        "affected_rows", ascending=False) if not findings_df.empty else findings_df
    heading = ["# NHS A&E M03 — Data Quality Validation", "", "## Source and unit of analysis", "",
        f"- Source: `{source_label}`", f"- Rows: {len(data):,} ({int(provider.sum()):,} provider, {int(total.sum()):,} aggregate).",
        f"- Observed reporting months: {len(months)} ({months[0] if months else 'n/a'}–{months[-1] if months else 'n/a'}).",
        "- Expected grain for modelling: organisation code × reporting month, excluding national totals *only after M03*.",
        "- NHS counts were checked but not changed; zero demand is not treated as missing.", "",
        "## Validation outcomes", "",
        f"- Gate: **{summary['quality_gate']}**", f"- Error finding groups: {summary['checks']['error_groups']}",
        f"- National metric-month reconciliations: {summary['checks']['reconciliations_matched']} matched; "
        f"{failed_recon} mismatched; {incomplete_recon} not comparable.",
        f"- Providers with gaps between first/last recorded months: {summary['checks']['providers_with_internal_month_gaps']}.",
        f"- Providers with name variants: {summary['checks']['providers_with_name_variants']}.",
        f"- Consecutive-month Type 1 changes flagged for human review: {len(candidates_df)}.", "",
        "## Highest-volume source issues", ""]
    if dominant.empty:
        heading.append("No row-level errors or warnings detected by the implemented checks.")
    else:
        for _, f in dominant.head(12).iterrows():
            heading.append(f"- {f['severity']} — `{f['check']}`: {int(f['affected_rows']):,} affected row/check occurrences.")
    heading += ["", "## Interpretation", "",
        "A passed core gate does not establish clinical suitability or longitudinal provider comparability. "
        "Provider restructures, structural zero Type 1 activity, metadata changes and large demand shifts require context before modelling.",
        "", "M04 should document any standardisation decisions and M05 should resolve historical provider-identity questions.",
        "", "## Outputs", "", "All checks are reproducible from the M02 staged file. Detailed grouped evidence is in "
        "`data/quality/m03_findings.csv`, with monthly profiles, reconciliation and continuity reports under `docs/`.", ""]
    (output_root / OUTPUTS["report"]).write_text("\n".join(heading), encoding="utf-8")
    return {"summary": summary, "monthly": monthly_df, "reconciliation": recon_df,
            "continuity": continuity_df, "change_candidates": candidates_df,
            "findings": findings_df, "outputs": {k: str(output_root / v) for k, v in OUTPUTS.items()}}


def cli() -> None:
    parser = argparse.ArgumentParser(description="NHS A&E M03 data quality validation (no cleaning)")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="NHS-A-E-IDSS repository root")
    parser.add_argument("--input", type=Path, default=None, help="Optional M02 staged CSV or Parquet")
    parser.add_argument("--output", type=Path, default=None, help="Optional separate root for reports")
    parser.add_argument("--fail-on-errors", action="store_true", help="Return exit status 2 if any core check fails")
    args = parser.parse_args()
    result = validate_dataset(args.repo, args.input, args.output)
    print(json.dumps({"summary": result["summary"], "outputs": result["outputs"]}, indent=2))
    if args.fail_on_errors and result["summary"]["checks"]["error_groups"]:
        raise SystemExit(2)


if __name__ == "__main__":
    cli()
