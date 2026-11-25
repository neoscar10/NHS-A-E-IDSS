"""Automated tests for Step 7 common forecasting baselines."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.cohort_selection import MANIFEST_REL_PATH, sha256_file
from src.data.data_preprocessing import TARGET
from src.models.baselines import (
    compute_regression_metrics,
    evaluate_validation_baselines,
)
from src.models.evaluation_splits import (
    FEATURE_METADATA_REL_PATH,
    assign_chronological_splits,
    load_verified_features,
)
from src.models.feature_engineering import TARGET_COLUMN, build_feature_dataset


def _make_full_synthetic_calendar() -> pd.DataFrame:
    """Build a synthetic monthly calendar spanning 2022-01 through 2026-09 (57 months)."""
    months = pd.date_range("2022-01-01", "2026-09-01", freq="MS")
    rows = []
    for idx, m in enumerate(months):
        # R01: distinct deterministic values 1000 + 10*idx
        # R02: includes a genuine zero at 2025-06 (idx=41) and stops after 2025-11 (absent target in 2025-12)
        for code in ("R01", "R02"):
            if code == "R01":
                val: int | None = 1000 + 10 * idx
            else:
                if m == pd.Timestamp("2025-12-01"):
                    val = None  # absent validation target -> must be excluded, never zeroed
                elif m == pd.Timestamp("2025-06-01"):
                    val = 0  # genuine reported zero -> must be preserved
                else:
                    val = 500 + 5 * idx
            obs = val is not None
            rows.append(
                {
                    "period": m,
                    "org_code": code,
                    "parent_org": "TEST REGION" if obs else pd.NA,
                    "org_name": f"TRUST {code}" if obs else pd.NA,
                    TARGET: pd.NA if not obs else int(val),
                    "type1_emergency_admissions": pd.NA if not obs else int(val // 4),
                    "type1_over_4hrs": pd.NA if not obs else int(val // 5),
                    "is_observed": obs,
                }
            )
    return pd.DataFrame(rows)


def test_exact_t_minus_2_and_t_minus_12_alignment_without_t_minus_1_or_target_leakage():
    cal = _make_full_synthetic_calendar()
    feat = build_feature_dataset(cal, verify_existing_eligibility=False)
    split_df = assign_chronological_splits(feat)
    res = evaluate_validation_baselines(split_df)
    preds = res["predictions_df"]

    # Check R01 for target 2025-10 (month index 45: actual=1450)
    # T - 2 = 2025-08 (idx 43: value=1430); T - 1 = 2025-09 (idx 44: value=1440, MUST NOT be used)
    # T - 12 = 2024-10 (idx 33: value=1330)
    r01_oct = preds.loc[(preds["org_code"] == "R01") & (preds["target_period"] == pd.Timestamp("2025-10-01"))].iloc[0]
    assert r01_oct["decision_date"] == pd.Timestamp("2025-09-30")
    assert r01_oct["origin_period"] == pd.Timestamp("2025-08-01")
    assert int(r01_oct["actual_type1_attendances"]) == 1450
    assert r01_oct["pred_latest_published"] == 1430.0
    assert r01_oct["pred_seasonal_naive"] == 1330.0
    assert r01_oct["abs_error_latest_published"] == 20.0
    assert r01_oct["abs_error_seasonal_naive"] == 120.0

    # Mutate unpublished T - 1 (2025-09) in raw calendar and verify predictions for 2025-10 are unchanged!
    cal_mut = cal.copy()
    cal_mut.loc[(cal_mut["org_code"] == "R01") & (cal_mut["period"] == pd.Timestamp("2025-09-01")), TARGET] = 999999
    res_mut = evaluate_validation_baselines(assign_chronological_splits(build_feature_dataset(cal_mut, verify_existing_eligibility=False)))
    r01_oct_mut = res_mut["predictions_df"].loc[
        (res_mut["predictions_df"]["org_code"] == "R01")
        & (res_mut["predictions_df"]["target_period"] == pd.Timestamp("2025-10-01"))
    ].iloc[0]
    assert r01_oct_mut["pred_latest_published"] == 1430.0
    assert r01_oct_mut["pred_seasonal_naive"] == 1330.0


def test_mae_rmse_wape_calculations_and_genuine_zero_preservation():
    # Include a genuine zero actual: actual = [100, 0, 300], pred = [110, 20, 270]
    # Errors = [+10, +20, -30], Abs errors = [10, 20, 30]
    # MAE = 60 / 3 = 20.0
    # RMSE = sqrt((100 + 400 + 900) / 3) = sqrt(1400 / 3)
    # WAPE = 100 * 60 / 400 = 15.0%
    m = compute_regression_metrics(np.array([100, 0, 300]), np.array([110, 20, 270]))
    assert math.isclose(m["mae"], 20.0)
    assert math.isclose(m["rmse"], math.sqrt(1400.0 / 3.0))
    assert math.isclose(m["wape_pct"], 15.0)

    with pytest.raises(ValueError, match="NaN"):
        compute_regression_metrics(np.array([100.0, np.nan]), np.array([100.0, 100.0]))


def test_missing_targets_genuine_zeros_and_missing_baseline_inputs_handled_transparently():
    cal = _make_full_synthetic_calendar()
    split_df = assign_chronological_splits(build_feature_dataset(cal, verify_existing_eligibility=False))
    res = evaluate_validation_baselines(split_df)
    preds = res["predictions_df"]

    # R02's absent target in 2025-12 is excluded (not zeroed), while R02's genuine 0 in 2025-06 is preserved
    assert len(res["excluded_absent_target_df"]) == 1
    assert list(res["excluded_absent_target_df"]["org_code"]) == ["R02"]
    assert res["summary"]["scored_observations"] == 23  # 12 for R01 + 11 for R02
    assert res["summary"]["reported_zero_actuals_in_validation"] == 1
    r02_jun = preds.loc[(preds["org_code"] == "R02") & (preds["target_period"] == pd.Timestamp("2025-06-01"))].iloc[0]
    assert int(r02_jun["actual_type1_attendances"]) == 0

    # If one baseline predictor is missing on a validation row, BOTH baselines drop it (common sample, no imputation)
    split_missing = split_df.copy()
    mask_one = (split_missing["org_code"] == "R01") & (split_missing["target_period"] == pd.Timestamp("2025-03-01"))
    split_missing.loc[mask_one, "type1_target_lag_12"] = np.nan
    res_missing = evaluate_validation_baselines(split_missing)
    assert len(res_missing["excluded_missing_baseline_df"]) == 1
    assert res_missing["summary"]["scored_observations"] == 22
    assert list(res_missing["comparison_df"]["n_observations"]) == [22, 22]


def test_test_set_targets_are_never_examined_by_validation_baselines():
    cal = _make_full_synthetic_calendar()
    split_a = assign_chronological_splits(build_feature_dataset(cal, verify_existing_eligibility=False))
    split_b = split_a.copy()
    # Wildly mutate all 2026 test targets and predictors; validation baseline outputs must stay bit-identical
    test_mask = split_b["split"] == "test"
    split_b.loc[test_mask & split_b["target_observed"], TARGET_COLUMN] = 8888888
    split_b.loc[test_mask, "type1_origin"] = 7777777.0
    split_b.loc[test_mask, "type1_target_lag_12"] = 6666666.0

    res_a = evaluate_validation_baselines(split_a)
    res_b = evaluate_validation_baselines(split_b)

    pd.testing.assert_frame_equal(res_a["predictions_df"], res_b["predictions_df"])
    pd.testing.assert_frame_equal(res_a["comparison_df"], res_b["comparison_df"])
    assert res_a["summary"]["test_set_evaluated"] is False
    assert (res_a["predictions_df"]["target_period"].dt.year == 2025).all()


def test_real_validation_baselines_counts_r0a_example_and_frozen_hashes():
    repo = Path(__file__).resolve().parents[1]
    manifest_path = repo / MANIFEST_REL_PATH
    meta_path = repo / FEATURE_METADATA_REL_PATH
    if not manifest_path.is_file() or not meta_path.is_file():
        pytest.skip("Manifest or feature metadata not present")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fmeta = json.loads(meta_path.read_text(encoding="utf-8"))
    m06_path = repo / manifest["dataset"]["repository_relative_path"]
    feat_path = repo / fmeta["outputs"]["csv"]["path"]
    if not m06_path.is_file() or not feat_path.is_file():
        pytest.skip("Local rebuilt M06 or feature CSV not present in this checkout")

    m06_sha_before = sha256_file(m06_path)
    feat_sha_before = sha256_file(feat_path)

    feat_df, prov = load_verified_features(repo)
    split_df = assign_chronological_splits(feat_df)
    res = evaluate_validation_baselines(split_df)

    preds = res["predictions_df"]
    comp = res["comparison_df"]

    assert res["summary"]["test_set_evaluated"] is False
    assert res["summary"]["scored_observations"] == 1452
    assert res["summary"]["scored_distinct_providers"] == 121
    assert res["summary"]["excluded_absent_target_rows"] == 2
    assert res["summary"]["excluded_missing_baseline_rows"] == 0
    assert (preds["target_period"].dt.year == 2025).all()
    assert not preds.duplicated(["org_code", "target_period"]).any()
    assert list(comp["n_observations"]) == [1452, 1452]
    assert list(comp["n_providers"]) == [121, 121]

    # Manual worked verification: provider R0A, target October 2025
    r0a = preds.loc[(preds["org_code"] == "R0A") & (preds["target_period"] == pd.Timestamp("2025-10-01"))].iloc[0]
    assert r0a["decision_date"] == pd.Timestamp("2025-09-30")
    assert r0a["origin_period"] == pd.Timestamp("2025-08-01")
    assert int(r0a["actual_type1_attendances"]) == 27673
    assert r0a["pred_latest_published"] == 23856.0
    assert r0a["pred_seasonal_naive"] == 25876.0
    assert r0a["abs_error_latest_published"] == 3817.0
    assert r0a["abs_error_seasonal_naive"] == 1797.0

    # Frozen input hashes untouched
    assert sha256_file(m06_path) == m06_sha_before == prov["m06_csv_sha256"]
    assert sha256_file(feat_path) == feat_sha_before == prov["feature_csv_sha256"]
