"""Automated tests for time-aware Type 1 provider cohort selection."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data.cohort_selection import (
    MANIFEST_REL_PATH,
    build_cohorts,
    compare_with_m05,
    evaluate_time_aware_eligibility,
    load_accepted_m06,
)
from src.data.data_preprocessing import TARGET
from src.data.longitudinal_preparation import STATUSES


def _make_calendar(specs: dict[str, list[int | None]], start: str = "2022-01-01") -> pd.DataFrame:
    """Build a synthetic monthly provider calendar for cohort-selection tests.

    ``specs`` maps ``org_code`` to a sequence of monthly ``type1_attendances``
    values where ``None`` represents an absent (unreported) provider-month.
    """
    rows = []
    for code, series in specs.items():
        months = pd.date_range(start, periods=len(series), freq="MS")
        for month, val in zip(months, series):
            observed = val is not None
            rows.append(
                {
                    "period": month,
                    "org_code": code,
                    "parent_org": "TEST REGION" if observed else pd.NA,
                    "org_name": f"TRUST {code}" if observed else pd.NA,
                    TARGET: pd.NA if not observed else int(val),
                    "is_observed": observed,
                }
            )
    return pd.DataFrame(rows)


def test_eligibility_uses_only_past_and_current_months():
    cal = _make_calendar({"R01": [100] * 15})
    out = evaluate_time_aware_eligibility(cal, window=12, verify_existing=False)
    r01 = out.loc[out["org_code"] == "R01"].sort_values("period")
    # Months 1..11 cannot have 12 consecutive months; months 12..15 qualify.
    assert r01["history_ready"].tolist() == [False] * 11 + [True] * 4
    assert r01["type1_candidate"].tolist() == [False] * 11 + [True] * 4
    assert r01["candidate_status"].tolist() == (
        ["Insufficient consecutive history"] * 11 + ["Candidate"] * 4
    )


def test_missing_month_breaks_consecutive_history_until_rebuilt():
    # Observed for 12 months (0..11), missing at index 12 (2023-01), observed 13..25
    series: list[int | None] = [500] * 12 + [None] + [500] * 13
    cal = _make_calendar({"R01": series})
    out = evaluate_time_aware_eligibility(cal, window=12, verify_existing=False)
    r01 = out.loc[out["org_code"] == "R01"].sort_values("period").reset_index(drop=True)

    # Index 11 (12th observed month) is eligible.
    assert bool(r01.loc[11, "type1_candidate"]) is True
    # Index 12 is absent -> Not observed, missing count stays NA, not eligible.
    assert bool(r01.loc[12, "is_observed"]) is False
    assert pd.isna(r01.loc[12, TARGET])
    assert r01.loc[12, "observation_state"] == "Absent record"
    assert r01.loc[12, "candidate_status"] == "No reported record"
    assert bool(r01.loc[12, "history_ready"]) is False
    assert bool(r01.loc[12, "type1_candidate"]) is False

    # Indices 13..23 (1..11 months after the gap) lack 12 consecutive observed months.
    for idx in range(13, 24):
        assert bool(r01.loc[idx, "history_ready"]) is False
        assert bool(r01.loc[idx, "type1_candidate"]) is False
        assert r01.loc[idx, "candidate_status"] == "Insufficient consecutive history"

    # Index 24 is the 12th consecutive observed month after the gap -> restored.
    assert bool(r01.loc[24, "history_ready"]) is True
    assert bool(r01.loc[24, "type1_candidate"]) is True
    assert r01.loc[24, "candidate_status"] == "Candidate"


def test_reported_zero_is_distinct_from_missing_and_preserves_eligibility():
    # 11 positive months followed by a genuine reported zero at month 12,
    # plus a separate all-zero provider over 14 months.
    cal = _make_calendar(
        {
            "R01": [250] * 11 + [0] + [250] * 2,
            "R02": [0] * 14,
        }
    )
    out = evaluate_time_aware_eligibility(cal, window=12, verify_existing=False)

    r01_m12 = out.loc[(out["org_code"] == "R01") & (out["period"] == pd.Timestamp("2022-12-01"))].iloc[0]
    assert bool(r01_m12["is_observed"]) is True
    assert int(r01_m12[TARGET]) == 0
    assert r01_m12["observation_state"] == "Reported zero"
    assert bool(r01_m12["history_ready"]) is True
    assert bool(r01_m12["type1_candidate"]) is True
    assert r01_m12["candidate_status"] == "Candidate"

    r02 = out.loc[out["org_code"] == "R02"].sort_values("period").reset_index(drop=True)
    assert (r02["observation_state"] == "Reported zero").all()
    assert bool(r02.loc[11, "history_ready"]) is True
    assert bool(r02.loc[11, "type1_candidate"]) is False
    assert r02.loc[11, "candidate_status"] == "No recent positive activity"


def test_future_changes_or_additions_do_not_alter_earlier_eligibility():
    cutoff = pd.Timestamp("2023-03-01")
    base = _make_calendar(
        {
            "R01": [100] * 15,
            "R02": [0] * 15,
            "R03": [50] * 10 + [None] + [50] * 4,
        }
    )
    # Perturb/extend future records strictly after cutoff:
    # - R02 flips from 0 to 5000 after cutoff
    # - R01 drops to absent after cutoff
    # - Add 6 new future months for all providers
    future = _make_calendar(
        {
            "R01": [100] * 15 + [None] * 6,
            "R02": [0] * 15 + [5000] * 6,
            "R03": [50] * 10 + [None] + [50] * 4 + [900] * 6,
        }
    )

    a = evaluate_time_aware_eligibility(base, window=12, verify_existing=False)
    b = evaluate_time_aware_eligibility(future, window=12, verify_existing=False)

    cols = [
        "period",
        "org_code",
        "is_observed",
        "observation_state",
        "observed_last_n_months",
        "positive_last_n_months",
        "history_ready",
        "type1_candidate",
        "candidate_status",
    ]
    a_pre = a.loc[a["period"] <= cutoff, cols].reset_index(drop=True)
    b_pre = b.loc[b["period"] <= cutoff, cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a_pre, b_pre)


def test_duplicate_provider_month_keys_rejected():
    cal = _make_calendar({"R01": [100] * 12})
    dup = pd.concat([cal, cal.iloc[:1]], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_time_aware_eligibility(dup, window=12, verify_existing=False)


def test_negative_reported_count_and_non_null_absent_rejected():
    cal_neg = _make_calendar({"R01": [100] * 11 + [-5]})
    with pytest.raises(ValueError, match="Negative"):
        evaluate_time_aware_eligibility(cal_neg, window=12, verify_existing=False)

    cal_bad_abs = _make_calendar({"R01": [100] * 12})
    cal_bad_abs.loc[5, "is_observed"] = False  # leaves non-null value on absent row
    with pytest.raises(ValueError, match="Absent calendar row"):
        evaluate_time_aware_eligibility(cal_bad_abs, window=12, verify_existing=False)


def test_sensitivity_cohort_preserves_main_provisional_cohort():
    # R01 has no continuity concern; RAL is a documented acute-merger absorber
    cal = _make_calendar({"R01": [1000] * 15, "RAL": [15000] * 15})
    out = build_cohorts(cal, window=12, verify_existing=False)

    assert len(out["provisional_cohort"]) == 8  # 4 origins x 2 providers
    assert set(out["provisional_cohort"]["org_code"]) == {"R01", "RAL"}
    assert len(out["sensitivity_cohort"]) == 4  # R01 only
    assert set(out["sensitivity_cohort"]["org_code"]) == {"R01"}
    assert not out["cohort_calendar"].duplicated(["org_code", "period"]).any()
    assert out["monthly_summary"][STATUSES].sum(axis=1).eq(out["monthly_summary"]["calendar_rows"]).all()


def test_manifest_loader_rejects_tampered_sha256(tmp_path: Path):
    csv_file = tmp_path / "m06.csv"
    csv_file.write_text("period,org_code\n2022-01-01,R01\n", encoding="utf-8")
    manifest = {
        "status": "VERIFIED_REBUILT_INPUT",
        "dataset": {
            "repository_relative_path": "m06.csv",
            "sha256": "0" * 64,
            "counts": {"rows": 1, "provider_codes": 1},
        },
    }
    manifest_file = tmp_path / "docs/model_input_manifest.json"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_accepted_m06(tmp_path)


def test_accepted_m06_cohort_matches_m05_evidence():
    repo = Path(__file__).resolve().parents[1]
    manifest_path = repo / MANIFEST_REL_PATH
    if not manifest_path.is_file():
        pytest.skip("docs/model_input_manifest.json not present")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not (repo / manifest["dataset"]["repository_relative_path"]).is_file():
        pytest.skip("Local rebuilt M06 dataset not present in this checkout")

    panel, _ = load_accepted_m06(repo)
    out = build_cohorts(panel, window=12, verify_existing=True)
    m05_check = compare_with_m05(repo, out["monthly_summary"], out["continuity_review"])

    assert m05_check["monthly_eligibility_exact_match"] is True
    assert m05_check["provider_continuity_exact_match"] is True
    assert len(out["provisional_cohort"]) == 5599
    assert out["provisional_cohort"]["org_code"].nunique() == 124
    assert len(out["sensitivity_cohort"]) == 5014
    assert out["sensitivity_cohort"]["org_code"].nunique() == 109
    assert not out["cohort_calendar"].duplicated(["org_code", "period"]).any()
