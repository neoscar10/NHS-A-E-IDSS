"""Automated tests for Step 5 leakage-safe historical feature engineering."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.cohort_selection import MANIFEST_REL_PATH, load_accepted_m06, sha256_file
from src.data.data_preprocessing import TARGET
from src.models.feature_engineering import (
    ALL_FEATURE_COLUMNS,
    CORE_FEATURE_COLUMNS,
    OPTIONAL_FEATURE_COLUMNS,
    PROHIBITED_PREDICTOR_COLUMNS,
    TARGET_COLUMN,
    build_feature_dataset,
    get_predictor_matrix,
    summarise_feature_dataset,
)


def _make_synthetic_calendar(
    specs: dict[str, list[int | None]],
    start: str = "2022-01-01",
    admissions_offset: int = 10,
    over_4hrs_divisor: int = 4,
) -> pd.DataFrame:
    """Build a synthetic monthly provider calendar with distinct deterministic counts."""
    rows = []
    for code, series in specs.items():
        months = pd.date_range(start, periods=len(series), freq="MS")
        for month, val in zip(months, series):
            observed = val is not None
            adm = pd.NA if not observed else int(max(0, val // 3 + admissions_offset))
            ov4 = pd.NA if not observed else int(val // over_4hrs_divisor)
            rows.append(
                {
                    "period": month,
                    "org_code": code,
                    "parent_org": "TEST REGION" if observed else pd.NA,
                    "org_name": f"TRUST {code}" if observed else pd.NA,
                    TARGET: pd.NA if not observed else int(val),
                    "type1_emergency_admissions": adm,
                    "type1_over_4hrs": ov4,
                    "is_observed": observed,
                }
            )
    return pd.DataFrame(rows)


def test_target_is_exactly_two_months_after_origin_and_decision_date_is_prior_month_end():
    cal = _make_synthetic_calendar({"R01": [100 + i for i in range(18)]})
    feat = build_feature_dataset(cal, verify_existing_eligibility=False)

    assert len(feat) == 7  # origins 2022-12 .. 2023-06
    for r in feat.itertuples(index=False):
        expected_target = r.origin_period + pd.DateOffset(months=2)
        expected_decision = expected_target - pd.DateOffset(days=1)
        assert r.target_period == expected_target
        assert r.decision_date == expected_decision
        assert r.horizon_months == 2
        assert r.target_month == expected_target.month
        assert r.target_year == expected_target.year
        assert r.target_days_in_month == expected_target.days_in_month
        assert math.isclose(r.target_month_sin, math.sin(2 * math.pi * expected_target.month / 12.0))
        assert math.isclose(r.target_month_cos, math.cos(2 * math.pi * expected_target.month / 12.0))


def test_lags_and_t_minus_12_match_exact_calendar_months():
    # Assign unique values 1000, 1001, ..., 1029 across 30 consecutive months (2022-01..2024-06)
    vals = [1000 + i for i in range(30)]
    cal = _make_synthetic_calendar({"R01": vals})
    feat = build_feature_dataset(cal, verify_existing_eligibility=False)

    # Inspect origin o = 2023-08 (index 19, value=1019) -> target T = 2023-10 (index 21, value=1021)
    row = feat.loc[feat["origin_period"] == pd.Timestamp("2023-08-01")].iloc[0]
    assert row["target_period"] == pd.Timestamp("2023-10-01")
    assert row["decision_date"] == pd.Timestamp("2023-09-30")
    assert int(row[TARGET_COLUMN]) == 1021
    assert row["type1_origin"] == 1019.0
    assert row["type1_origin_lag_1"] == 1018.0  # 2023-07
    assert row["type1_origin_lag_2"] == 1017.0  # 2023-06
    assert row["type1_origin_lag_3"] == 1016.0  # 2023-05
    assert row["type1_origin_lag_12"] == 1007.0  # o - 12 = 2022-08
    # Same calendar month as T (2023-10) one year earlier is 2022-10 (index 9, value=1009) = o - 10 != o - 12!
    assert row["type1_target_lag_12"] == 1009.0
    assert row["type1_target_lag_12"] != row["type1_origin_lag_12"]

    # Rolling means strictly over [o-w+1, o]
    assert math.isclose(row["type1_origin_roll_mean_3"], np.mean([1017, 1018, 1019]))
    assert math.isclose(row["type1_origin_roll_mean_6"], np.mean(vals[14:20]))
    assert math.isclose(row["type1_origin_roll_mean_12"], np.mean(vals[8:20]))


def test_initial_origin_lag_12_is_missing_explicitly_without_changing_eligibility():
    # 15 months (2022-01..2023-03) -> first eligible origin is 2022-12 (index 11)
    vals = [100 + i for i in range(15)]
    cal = _make_synthetic_calendar({"R01": vals})
    feat = build_feature_dataset(cal, verify_existing_eligibility=False)

    first = feat.loc[feat["origin_period"] == pd.Timestamp("2022-12-01")].iloc[0]
    assert bool(first["is_eligible_origin"]) is True
    assert pd.isna(first["type1_origin_lag_12"])  # 2021-12 does not exist
    assert bool(first["has_complete_core_features"]) is False
    # T = 2023-02, so T - 12 = 2022-02 (index 1, value=101) IS available!
    assert first["type1_target_lag_12"] == 101.0

    # Second eligible origin 2023-01 (index 12) HAS 2022-01 (index 0, value=100) for o - 12.
    second = feat.loc[feat["origin_period"] == pd.Timestamp("2023-01-01")].iloc[0]
    assert second["type1_origin_lag_12"] == 100.0
    assert bool(second["has_complete_core_features"]) is True


def test_no_feature_depends_on_unpublished_t_minus_1_or_target_t():
    cal_a = _make_synthetic_calendar({"R01": [1000 + 10 * i for i in range(20)]})
    cal_b = cal_a.copy()

    # For origin o = 2023-03 (index 14), T - 1 is 2023-04 (index 15) and T is 2023-05 (index 16).
    # Wildly mutate all measures in 2023-04 and 2023-05 (and everything after 2023-03).
    future_mask = cal_b["period"] > pd.Timestamp("2023-03-01")
    cal_b.loc[future_mask, TARGET] = 999999
    cal_b.loc[future_mask, "type1_emergency_admissions"] = 888888
    cal_b.loc[future_mask, "type1_over_4hrs"] = 777777

    fa = build_feature_dataset(cal_a, verify_existing_eligibility=False)
    fb = build_feature_dataset(cal_b, verify_existing_eligibility=False)

    cutoff = pd.Timestamp("2023-03-01")
    xa = get_predictor_matrix(fa.loc[fa["origin_period"] <= cutoff], include_optional=True).reset_index(drop=True)
    xb = get_predictor_matrix(fb.loc[fb["origin_period"] <= cutoff], include_optional=True).reset_index(drop=True)
    pd.testing.assert_frame_equal(xa, xb)


def test_adding_or_removing_future_months_does_not_change_earlier_features():
    base_vals = [500 + 5 * i for i in range(18)]
    cal_short = _make_synthetic_calendar({"R01": base_vals})
    cal_long = _make_synthetic_calendar({"R01": base_vals + [9000, 9500, None, 10000]})

    f_short = build_feature_dataset(cal_short, verify_existing_eligibility=False)
    f_long = build_feature_dataset(cal_long, verify_existing_eligibility=False)

    cutoff = pd.Timestamp("2023-06-01")
    xs = get_predictor_matrix(f_short.loc[f_short["origin_period"] <= cutoff]).reset_index(drop=True)
    xl = get_predictor_matrix(f_long.loc[f_long["origin_period"] <= cutoff]).reset_index(drop=True)
    pd.testing.assert_frame_equal(xs, xl)


def test_missing_reports_absent_targets_and_genuine_zeros_remain_distinct():
    # R01: 11 positive months + genuine reported zero at month 12 (2022-12) + 2 positive months, then stops (absent target)
    # R02: internal gap at month 13 (2023-01) breaks consecutive history for 11 subsequent months
    series_r01: list[int | None] = [400] * 11 + [0] + [400, None, None]
    series_r02: list[int | None] = [300] * 12 + [None] + [300] * 13
    cal = _make_synthetic_calendar({"R01": series_r01, "R02": series_r02})
    feat = build_feature_dataset(cal, verify_existing_eligibility=False)

    # R01 at origin 2022-12 has genuine reported zero at origin, and absent target at 2023-02 (index 13 = None)
    r01_dec = feat.loc[(feat["org_code"] == "R01") & (feat["origin_period"] == pd.Timestamp("2022-12-01"))].iloc[0]
    assert r01_dec["type1_origin"] == 0.0
    assert pd.isna(r01_dec["type1_admission_rate_origin"])  # safe division by zero -> NaN
    assert pd.isna(r01_dec["type1_within_4hrs_rate_origin"])
    assert bool(r01_dec["target_observed"]) is False
    assert bool(r01_dec["is_future_forecast"]) is False
    assert pd.isna(r01_dec[TARGET_COLUMN])  # absent target NEVER converted to zero!

    # R02 after internal gap at 2023-01 cannot appear as eligible until 2024-01 (index 24),
    # and its origin_lag_12 at 2024-01 points to 2023-01 (the absent month -> must be NaN, NOT shifted!).
    r02 = feat.loc[feat["org_code"] == "R02"].sort_values("origin_period")
    assert pd.Timestamp("2023-02-01") not in set(r02["origin_period"])
    assert pd.Timestamp("2023-12-01") not in set(r02["origin_period"])
    r02_jan24 = r02.loc[r02["origin_period"] == pd.Timestamp("2024-01-01")].iloc[0]
    assert pd.isna(r02_jan24["type1_origin_lag_12"])  # 2023-01 was missing -> stays NaN!
    assert r02_jan24["type1_origin_roll_mean_12"] == 300.0


def test_predictor_matrix_excludes_target_and_prohibited_columns_and_keys_unique():
    cal = _make_synthetic_calendar({"R01": [200 + i for i in range(18)], "R02": [500 + i for i in range(18)]})
    feat = build_feature_dataset(cal, verify_existing_eligibility=False)

    assert not feat.duplicated(["org_code", "origin_period"]).any()
    assert not feat.duplicated(["org_code", "target_period"]).any()

    x_core = get_predictor_matrix(feat, include_optional=False)
    x_all = get_predictor_matrix(feat, include_optional=True)

    assert list(x_core.columns) == CORE_FEATURE_COLUMNS
    assert list(x_all.columns) == ALL_FEATURE_COLUMNS
    assert TARGET_COLUMN not in x_all.columns
    assert not (set(x_all.columns) & PROHIBITED_PREDICTOR_COLUMNS)
    assert len(OPTIONAL_FEATURE_COLUMNS) == 6


def test_accepted_m06_feature_engineering_preserves_input_and_protocol_counts():
    repo = Path(__file__).resolve().parents[1]
    manifest_path = repo / MANIFEST_REL_PATH
    if not manifest_path.is_file():
        pytest.skip("docs/model_input_manifest.json not present")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    csv_path = repo / manifest["dataset"]["repository_relative_path"]
    if not csv_path.is_file():
        pytest.skip("Local rebuilt M06 dataset not present in this checkout")

    sha_before = sha256_file(csv_path)
    panel, _ = load_accepted_m06(repo)
    feat = build_feature_dataset(panel, verify_existing_eligibility=True)
    summary = summarise_feature_dataset(feat)
    sha_after = sha256_file(csv_path)

    # Accepted M06 input file untouched
    assert sha_before == sha_after == manifest["dataset"]["sha256"]

    # Exact Step 3 & Step 4 counts preserved
    assert summary["eligible_origins"] == 5599
    assert summary["distinct_providers"] == 124
    assert summary["in_range_origins"] == 5359
    assert summary["target_observed_rows"] == 5351
    assert summary["absent_target_rows_in_range"] == 8
    assert summary["future_forecast_rows"] == 240
    assert summary["complete_core_feature_rows"] == 5475
    assert summary["complete_all_feature_rows"] == 5475
    assert summary["evaluable_with_complete_core_features"] == 5227
    # Only type1_origin_lag_12 has missing values (124 initial 2022-12 origins)
    assert summary["missing_counts_by_feature"]["type1_origin_lag_12"] == 124
    for col in ALL_FEATURE_COLUMNS:
        if col != "type1_origin_lag_12":
            assert summary["missing_counts_by_feature"][col] == 0
    assert not feat.duplicated(["org_code", "origin_period"]).any()
