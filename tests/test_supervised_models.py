"""Automated tests for Step 8 supervised regression model pipelines."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.cohort_selection import MANIFEST_REL_PATH, sha256_file
from src.data.data_preprocessing import TARGET
from src.models.evaluation_splits import (
    FEATURE_METADATA_REL_PATH,
    assign_chronological_splits,
    load_verified_features,
)
from src.models.feature_engineering import (
    OPTIONAL_FEATURE_COLUMNS,
    PROHIBITED_PREDICTOR_COLUMNS,
    TARGET_COLUMN,
    build_feature_dataset,
)
from src.models.supervised_models import (
    EXPECTED_CORE_FEATURES,
    INITIAL_DEMO_TARGET_MONTH,
    MODEL_NAMES,
    RANDOM_SEED,
    create_model_pipeline,
    extract_fitted_metadata,
    fit_model,
    get_core_feature_columns,
    load_model_artefact,
    predict_with_model,
    prepare_feature_matrix,
    run_initial_training_fit,
    save_model_artefact,
    select_training_fold,
)


def _make_synthetic_split_df() -> pd.DataFrame:
    """Build a synthetic calendar -> features -> chronological splits frame (2022-01..2026-09)."""
    months = pd.date_range("2022-01-01", "2026-09-01", freq="MS")
    rng = np.random.default_rng(123)
    rows = []
    for c_idx, code in enumerate(("R01", "R02", "R03", "R04")):
        base = 5000 + 2500 * c_idx
        for m_idx, m in enumerate(months):
            seasonal = int(400 * np.sin(2 * np.pi * m.month / 12.0))
            val = int(max(100, base + 20 * m_idx + seasonal + rng.integers(-150, 151)))
            rows.append(
                {
                    "period": m,
                    "org_code": code,
                    "parent_org": "TEST REGION",
                    "org_name": f"TRUST {code}",
                    TARGET: val,
                    "type1_emergency_admissions": int(val // 4),
                    "type1_over_4hrs": int(val // 5),
                    "is_observed": True,
                }
            )
    cal = pd.DataFrame(rows)
    feat = build_feature_dataset(cal, verify_existing_eligibility=False)
    return assign_chronological_splits(feat)


def test_exact_13_core_features_in_order_and_no_leakage():
    cols = get_core_feature_columns()
    assert len(cols) == 13
    assert tuple(cols) == EXPECTED_CORE_FEATURES
    assert TARGET_COLUMN not in cols
    assert not (set(cols) & PROHIBITED_PREDICTOR_COLUMNS)
    assert not (set(cols) & set(OPTIONAL_FEATURE_COLUMNS))
    assert "org_code" not in cols
    assert "target_year" not in cols

    # Prohibited columns explicitly rejected by prepare_feature_matrix
    split_df = _make_synthetic_split_df()
    train_df, _ = select_training_fold(split_df, INITIAL_DEMO_TARGET_MONTH, complete_core_only=True)
    with pytest.raises(ValueError, match="Prohibited"):
        prepare_feature_matrix(train_df, feature_columns=[*cols, TARGET_COLUMN])
    with pytest.raises(ValueError, match="Prohibited"):
        prepare_feature_matrix(train_df, feature_columns=[*cols, "target_year"])


def test_all_three_models_fit_predict_finite_and_reproducible_with_seeds():
    split_df = _make_synthetic_split_df()
    train_df, fold_info = select_training_fold(split_df, INITIAL_DEMO_TARGET_MONTH, complete_core_only=True)
    assert fold_info["latest_published_period"] == "2024-11"
    assert fold_info["excluded_incomplete_core_rows"] == 4  # 4 providers missing 2023-02 lag-12
    assert fold_info["excluded_unpublished_t_minus_1_rows"] == 4  # 2024-12 unpublished

    for name in MODEL_NAMES:
        pipe_a = fit_model(name, train_df)
        pipe_b = fit_model(name, train_df)

        meta = extract_fitted_metadata(name, pipe_a)
        assert meta["n_features_in"] == 13
        assert tuple(meta["feature_names_in"]) == EXPECTED_CORE_FEATURES

        if name in ("random_forest", "hist_gradient_boosting"):
            assert pipe_a.named_steps["model"].random_state == RANDOM_SEED
        if name == "hist_gradient_boosting":
            assert pipe_a.named_steps["model"].early_stopping is False

        pred_a = predict_with_model(pipe_a, train_df)
        pred_b = predict_with_model(pipe_b, train_df)

        assert pred_a.shape == (len(train_df), 3)
        assert np.isfinite(pred_a["raw_prediction"]).all()
        assert np.isfinite(pred_a["prediction"]).all()
        assert (pred_a["prediction"] >= 0.0).all()
        # Repeated training with identical seed produces exact reproducible predictions
        pd.testing.assert_frame_equal(pred_a, pred_b)


def test_ridge_scaler_fitted_exclusively_on_supplied_training_fold():
    split_df = _make_synthetic_split_df()
    train_df, _ = select_training_fold(split_df, INITIAL_DEMO_TARGET_MONTH, complete_core_only=True)

    # Fit Ridge on train_df
    ridge_pipe = fit_model("ridge", train_df)
    scaler = ridge_pipe.named_steps["scaler"]
    X_train = prepare_feature_matrix(train_df)

    assert int(scaler.n_samples_seen_) == len(train_df)
    np.testing.assert_allclose(scaler.mean_, X_train.mean(axis=0).to_numpy(), rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(scaler.scale_, X_train.std(axis=0, ddof=0).to_numpy(), rtol=1e-12, atol=1e-12)

    # Mutate all validation & test rows wildly and confirm training fold & fitted Ridge are bit-identical
    mutated = split_df.copy()
    val_test_mask = mutated["split"].isin(["validation", "test"])
    mutated.loc[val_test_mask, TARGET_COLUMN] = 9999999
    mutated.loc[val_test_mask, "type1_origin"] = 9999999.0

    train_mut, _ = select_training_fold(mutated, INITIAL_DEMO_TARGET_MONTH, complete_core_only=True)
    pd.testing.assert_frame_equal(train_df, train_mut)

    ridge_mut = fit_model("ridge", train_mut)
    np.testing.assert_array_equal(
        ridge_pipe.named_steps["scaler"].mean_,
        ridge_mut.named_steps["scaler"].mean_,
    )
    np.testing.assert_array_equal(
        ridge_pipe.named_steps["model"].coef_,
        ridge_mut.named_steps["model"].coef_,
    )


def test_non_negative_prediction_clipping_preserves_raw_prediction():
    cols = get_core_feature_columns()
    # Simple synthetic positive linear relationship in feature 0 -> negative value when feature 0 is negative
    train = pd.DataFrame({c: np.linspace(1.0, 20.0, 20) for c in cols})
    train[TARGET_COLUMN] = pd.array([int(10 * i) for i in range(1, 21)], dtype="Int64")
    pipe = fit_model("ridge", train, alpha=0.01)

    extreme = pd.DataFrame({c: [-500.0] for c in cols})
    out = predict_with_model(pipe, extreme, clip_non_negative=True)
    assert out["raw_prediction"].iloc[0] < 0.0
    assert out["prediction"].iloc[0] == 0.0
    assert bool(out["was_clipped"].iloc[0]) is True


def test_save_and_load_model_artefact_round_trip(tmp_path: Path):
    split_df = _make_synthetic_split_df()
    train_df, _ = select_training_fold(split_df, INITIAL_DEMO_TARGET_MONTH, complete_core_only=True)
    pipe = fit_model("random_forest", train_df, n_estimators=20)
    art_path = tmp_path / "rf.joblib"

    meta = save_model_artefact(pipe, art_path)
    assert art_path.is_file()
    assert len(meta["sha256"]) == 64

    reloaded = load_model_artefact(art_path)
    pd.testing.assert_frame_equal(
        predict_with_model(pipe, train_df),
        predict_with_model(reloaded, train_df),
    )


def test_real_initial_training_fit_counts_reproducibility_and_frozen_hashes(tmp_path: Path):
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

    res = run_initial_training_fit(
        repo,
        target_period=INITIAL_DEMO_TARGET_MONTH,
        output_dir=tmp_path,
        save_artefacts=True,
    )
    info = res["fold_info"]
    meta = res["metadata"]

    # Exact January 2025 training cutoff and row counts
    assert info["forecast_target_period"] == "2025-01"
    assert info["decision_date"] == "2024-12-31"
    assert info["latest_published_period"] == "2024-11"
    assert info["eligible_observed_training_rows"] == 2691
    assert info["complete_core_training_rows"] == 2567
    assert info["fitted_training_rows"] == 2567
    assert info["excluded_incomplete_core_rows"] == 124
    assert info["excluded_unpublished_t_minus_1_rows"] == 122
    assert (res["train_df"]["target_period"] <= pd.Timestamp("2024-11-01")).all()

    # Neither validation nor test set evaluated in Step 8
    assert meta["validation_evaluated"] is False
    assert meta["test_evaluated"] is False
    assert meta["feature_count"] == 13
    assert tuple(meta["feature_columns"]) == EXPECTED_CORE_FEATURES

    # All three models fitted on identical 2,567 rows
    assert set(res["fitted_models"].keys()) == set(MODEL_NAMES)
    assert meta["models"]["ridge"]["preprocessing"]["n_samples_seen"] == 2567
    assert meta["models"]["hist_gradient_boosting"]["fitted_summary"]["early_stopping"] is False
    assert meta["models"]["random_forest"]["fitted_summary"]["random_state"] == RANDOM_SEED

    # Frozen dataset hashes remain unchanged
    assert sha256_file(m06_path) == m06_sha_before
    assert sha256_file(feat_path) == feat_sha_before
