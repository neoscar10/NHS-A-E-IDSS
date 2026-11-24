"""Automated tests for Step 6 chronological splits and publication-aware backtesting."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data.cohort_selection import MANIFEST_REL_PATH, sha256_file
from src.models.evaluation_splits import (
    EXCLUSION_ABSENT_TARGET,
    EXCLUSION_FUTURE_UNLABELLED,
    EXCLUSION_NONE,
    FEATURE_METADATA_REL_PATH,
    FUTURE_START,
    LABELLED_PARTITIONS,
    TEST_END,
    TEST_START,
    TRAIN_END,
    TRAIN_START,
    VALIDATION_END,
    VALIDATION_START,
    assign_chronological_splits,
    get_expanding_window_split,
    get_fixed_partitions,
    iter_expanding_window_splits,
    load_verified_features,
    summarise_splits,
)
from src.models.feature_engineering import TARGET_COLUMN


def _make_synthetic_features() -> pd.DataFrame:
    """Create a synthetic feature table spanning 2023-02 through 2026-11 target months."""
    target_months = pd.date_range("2023-02-01", "2026-11-01", freq="MS")
    rows = []
    for code in ("R01", "R02"):
        for idx, t in enumerate(target_months):
            o = t - pd.DateOffset(months=2)
            d = t - pd.DateOffset(days=1)
            is_future = t >= FUTURE_START
            # Simulate R02 ceasing reporting for 2025-01 and 2025-02 (absent targets)
            absent_in_range = code == "R02" and t in (
                pd.Timestamp("2025-01-01"),
                pd.Timestamp("2025-02-01"),
            )
            obs = (not is_future) and (not absent_in_range)
            lag12_missing = t == pd.Timestamp("2023-02-01")
            rows.append(
                {
                    "org_code": code,
                    "origin_period": o,
                    "decision_date": d,
                    "target_period": t,
                    "target_year": t.year,
                    "horizon_months": 2,
                    "history_window_months": 12,
                    "is_eligible_origin": True,
                    "target_observed": obs,
                    "is_future_forecast": is_future,
                    "has_complete_core_features": not lag12_missing,
                    "has_complete_all_features": not lag12_missing,
                    TARGET_COLUMN: pd.NA if not obs else int(1000 + idx),
                    "type1_origin_lag_12": float("nan") if lag12_missing else float(900 + idx),
                }
            )
    return pd.DataFrame(rows).astype({"org_code": "string", TARGET_COLUMN: "Int64"})


def test_exact_chronological_boundaries_and_no_overlap():
    df = assign_chronological_splits(_make_synthetic_features())
    parts = get_fixed_partitions(df, evaluable_only=False)

    assert parts["train"]["target_period"].min() == TRAIN_START
    assert parts["train"]["target_period"].max() == TRAIN_END
    assert parts["validation"]["target_period"].min() == VALIDATION_START
    assert parts["validation"]["target_period"].max() == VALIDATION_END
    assert parts["test"]["target_period"].min() == TEST_START
    assert parts["test"]["target_period"].max() == TEST_END
    assert parts["future_unlabelled"]["target_period"].min() == FUTURE_START

    # Strict disjointness of target periods across all four partitions
    sets = [set(parts[p]["target_period"]) for p in ("train", "validation", "test", "future_unlabelled")]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            assert sets[i].isdisjoint(sets[j])
    assert parts["train"]["target_period"].max() < parts["validation"]["target_period"].min()
    assert parts["validation"]["target_period"].max() < parts["test"]["target_period"].min()
    assert parts["test"]["target_period"].max() < parts["future_unlabelled"]["target_period"].min()


def test_future_unlabelled_and_absent_targets_excluded_with_reasons():
    df = assign_chronological_splits(_make_synthetic_features())
    parts_eval = get_fixed_partitions(df, evaluable_only=True)

    # Future rows never appear in train, validation, or test
    for p in LABELLED_PARTITIONS:
        assert not parts_eval[p]["is_future_forecast"].any()
        assert parts_eval[p]["target_observed"].all()
        assert (parts_eval[p]["exclusion_reason"] == EXCLUSION_NONE).all()

    fut = df.loc[df["split"] == "future_unlabelled"]
    assert len(fut) == 4  # 2 providers x 2 future months
    assert not fut["evaluation_eligible"].any()
    assert (fut["exclusion_reason"] == EXCLUSION_FUTURE_UNLABELLED).all()

    absent = df.loc[(df["split"] == "validation") & (~df["target_observed"])]
    assert len(absent) == 2
    assert not absent["evaluation_eligible"].any()
    assert (absent["exclusion_reason"] == EXCLUSION_ABSENT_TARGET).all()
    assert absent[TARGET_COLUMN].isna().all()


def test_january_2025_cannot_train_on_december_2024_labels():
    df = assign_chronological_splits(_make_synthetic_features())
    step = get_expanding_window_split(df, "2025-01-01")

    assert step["decision_date"] == pd.Timestamp("2024-12-31")
    assert step["latest_published_period"] == pd.Timestamp("2024-11-01")
    assert step["unpublished_prior_period"] == pd.Timestamp("2024-12-01")
    assert step["train_df"]["target_period"].max() == pd.Timestamp("2024-11-01")
    assert pd.Timestamp("2024-12-01") not in set(step["train_df"]["target_period"])
    assert pd.Timestamp("2025-01-01") not in set(step["train_df"]["target_period"])
    assert step["excluded_unpublished_t_minus_1_rows"] == 2
    # R02 absent target in 2025-01 is excluded from evaluable set, preserved in eval_excluded_df
    assert list(step["eval_evaluable_df"]["org_code"]) == ["R01"]
    assert list(step["eval_excluded_df"]["org_code"]) == ["R02"]


def test_every_expanding_window_step_obeys_two_month_publication_lag():
    df = assign_chronological_splits(_make_synthetic_features())
    for part in ("validation", "test"):
        steps = list(iter_expanding_window_splits(df, partition=part))
        assert len(steps) == (12 if part == "validation" else 9)
        for step in steps:
            T = step["target_period"]
            o = T - pd.DateOffset(months=2)
            assert step["latest_published_period"] == o
            assert step["decision_date"] == T - pd.DateOffset(days=1)
            assert (step["train_df"]["target_period"] <= o).all()
            assert step["train_df"]["evaluation_eligible"].all()
            assert (step["eval_all_df"]["origin_period"] == o).all()


def test_deterministic_splits_and_no_future_leakage_through_mutation():
    base = _make_synthetic_features()
    # Shuffle input order to verify grouping/sorting never depends on input order or randomness
    shuffled = base.sample(frac=1.0, random_state=42).reset_index(drop=True)
    s1 = assign_chronological_splits(base)
    s2 = assign_chronological_splits(shuffled)
    pd.testing.assert_frame_equal(s1, s2)

    # Mutate observed future target values after 2024-11 and verify 2025-01 training set is bit-identical
    mutated = base.copy()
    mutated.loc[
        (mutated["target_period"] > pd.Timestamp("2024-11-01")) & mutated["target_observed"],
        TARGET_COLUMN,
    ] = 999999
    step_a = get_expanding_window_split(assign_chronological_splits(base), "2025-01-01")
    step_b = get_expanding_window_split(assign_chronological_splits(mutated), "2025-01-01")
    pd.testing.assert_frame_equal(step_a["train_df"], step_b["train_df"])


def test_complete_features_only_filters_training_without_changing_val_or_test_targets():
    df = assign_chronological_splits(_make_synthetic_features())
    step_all = get_expanding_window_split(df, "2025-01-01", complete_features_only=False)
    step_comp = get_expanding_window_split(df, "2025-01-01", complete_features_only=True)

    # 2 early 2023-02 rows dropped from training when complete_features_only=True
    assert len(step_all["train_df"]) - len(step_comp["train_df"]) == 2
    assert step_comp["train_df"]["has_complete_all_features"].all()
    # Identical evaluation target rows
    pd.testing.assert_frame_equal(step_all["eval_evaluable_df"], step_comp["eval_evaluable_df"])


def test_provenance_loader_rejects_tampered_feature_hash(tmp_path: Path):
    m06_file = tmp_path / "m06.csv"
    m06_file.write_text("period,org_code\n2022-01-01,R01\n", encoding="utf-8")
    m06_sha = sha256_file(m06_file)

    feat_file = tmp_path / "features.csv"
    feat_file.write_text("org_code\nR01\n", encoding="utf-8")

    manifest_path = tmp_path / "docs/model_input_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "dataset": {"repository_relative_path": "m06.csv", "sha256": m06_sha},
                "provenance": {"m06_run_id": "run_1"},
            }
        ),
        encoding="utf-8",
    )

    meta_path = tmp_path / "outputs/features/feature_metadata.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(
            {
                "input_m06_sha256": m06_sha,
                "input_m06_run_id": "run_1",
                "outputs": {"csv": {"path": "features.csv", "sha256": "0" * 64, "rows": 1}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Feature CSV SHA-256 mismatch"):
        load_verified_features(tmp_path)


def test_real_feature_dataset_splits_counts_and_hashes_unchanged():
    repo = Path(__file__).resolve().parents[1]
    manifest_path = repo / MANIFEST_REL_PATH
    meta_path = repo / FEATURE_METADATA_REL_PATH
    if not manifest_path.is_file() or not meta_path.is_file():
        pytest.skip("Manifest or materialised feature metadata not present")
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
    summary = summarise_splits(split_df)

    # Exact expected counts across fixed partitions
    assert summary["partitions"]["train"]["evaluable_rows"] == 2813
    assert summary["partitions"]["train"]["excluded_rows"] == 4
    assert summary["partitions"]["train"]["distinct_providers_evaluable"] == 124
    assert summary["partitions"]["train"]["missing_origin_lag_12_rows"] == 124

    assert summary["partitions"]["validation"]["evaluable_rows"] == 1452
    assert summary["partitions"]["validation"]["excluded_rows"] == 2
    assert summary["partitions"]["validation"]["distinct_providers_eligible"] == 122
    assert summary["partitions"]["validation"]["distinct_providers_evaluable"] == 121
    assert summary["partitions"]["validation"]["complete_all_features_evaluable"] == 1452

    assert summary["partitions"]["test"]["evaluable_rows"] == 1086
    assert summary["partitions"]["test"]["excluded_rows"] == 2
    assert summary["partitions"]["test"]["distinct_providers_evaluable"] == 121
    assert summary["partitions"]["test"]["complete_all_features_evaluable"] == 1086

    assert summary["totals"]["total_labelled_evaluable_rows"] == 5351
    assert summary["totals"]["total_absent_in_range_rows"] == 8
    assert summary["totals"]["total_future_unlabelled_rows"] == 240

    # Worked examples: Jan 2025 and Jan 2026 expanding windows
    jan25 = get_expanding_window_split(split_df, "2025-01-01")
    assert jan25["latest_published_period"] == pd.Timestamp("2024-11-01")
    assert len(jan25["train_df"]) == 2691
    assert jan25["excluded_unpublished_t_minus_1_rows"] == 122
    assert len(jan25["eval_evaluable_df"]) == 121
    assert list(jan25["eval_excluded_df"]["org_code"]) == ["RAP"]

    jan26 = get_expanding_window_split(split_df, "2026-01-01")
    assert jan26["latest_published_period"] == pd.Timestamp("2025-11-01")
    assert len(jan26["train_df"]) == 4144
    assert jan26["excluded_unpublished_t_minus_1_rows"] == 121
    assert len(jan26["eval_evaluable_df"]) == 121
    assert len(jan26["eval_excluded_df"]) == 0

    # Frozen M06 and feature CSV hashes completely untouched
    assert sha256_file(m06_path) == m06_sha_before == prov["m06_csv_sha256"]
    assert sha256_file(feat_path) == feat_sha_before == prov["feature_csv_sha256"]
