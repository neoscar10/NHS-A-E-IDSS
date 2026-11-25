"""Deterministic, publication-aware forecasting baselines for NHS Type 1 A&E demand.

Implements two common benchmark baselines evaluated strictly on the approved
2025 validation population (``split == "validation"`` and
``evaluation_eligible == True``), reusing Step 5 features and Step 6
chronological splits without modification:

1. Latest-published attendance baseline: ``y_hat(T) = y(o) = y(T - 2)``
   using ``type1_origin``.
2. Seasonal naive baseline: ``y_hat(T) = y(T - 12) = y(o - 10)``
   using ``type1_target_lag_12``.

The 2026 final test partition is intentionally excluded from baseline scoring
and exploratory evaluation in Step 7.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.cohort_selection import sha256_file
from src.models.evaluation_splits import (
    assign_chronological_splits,
    get_fixed_partitions,
    load_verified_features,
)
from src.models.feature_engineering import TARGET_COLUMN

LATEST_PUBLISHED_COL = "type1_origin"
SEASONAL_NAIVE_COL = "type1_target_lag_12"

BASELINE_SPECS = (
    {
        "baseline": "latest_published_t_minus_2",
        "display_name": "Latest-published attendance (T - 2)",
        "source_column": LATEST_PUBLISHED_COL,
        "prediction_column": "pred_latest_published",
        "error_column": "error_latest_published",
        "abs_error_column": "abs_error_latest_published",
        "lag_definition": "Actual Type 1 attendance at latest published report o = T - 2",
    },
    {
        "baseline": "seasonal_naive_t_minus_12",
        "display_name": "Seasonal naive (T - 12)",
        "source_column": SEASONAL_NAIVE_COL,
        "prediction_column": "pred_seasonal_naive",
        "error_column": "error_seasonal_naive",
        "abs_error_column": "abs_error_seasonal_naive",
        "lag_definition": "Actual Type 1 attendance in same calendar month one year earlier (T - 12 = o - 10)",
    },
)


def predict_latest_published(df: pd.DataFrame) -> pd.Series:
    """Predict target month T using the latest published reporting month o = T - 2."""
    if LATEST_PUBLISHED_COL not in df.columns:
        raise ValueError(f"Missing required column for latest-published baseline: {LATEST_PUBLISHED_COL}")
    return pd.to_numeric(df[LATEST_PUBLISHED_COL], errors="raise").astype("float64")


def predict_seasonal_naive(df: pd.DataFrame) -> pd.Series:
    """Predict target month T using the same calendar month one year earlier (T - 12)."""
    if SEASONAL_NAIVE_COL not in df.columns:
        raise ValueError(f"Missing required column for seasonal naive baseline: {SEASONAL_NAIVE_COL}")
    return pd.to_numeric(df[SEASONAL_NAIVE_COL], errors="raise").astype("float64")


def compute_regression_metrics(
    actual: pd.Series | np.ndarray,
    predicted: pd.Series | np.ndarray,
) -> dict[str, float]:
    """Compute MAE (attendances), RMSE (attendances), and WAPE (%).

    Genuine zero actuals are preserved untouched. Raises ValueError if inputs
    differ in length, are empty, or contain NaN/null values.
    """
    y_true = np.asarray(actual, dtype="float64")
    y_pred = np.asarray(predicted, dtype="float64")
    if y_true.shape != y_pred.shape:
        raise ValueError(f"Shape mismatch between actual {y_true.shape} and predicted {y_pred.shape}")
    if y_true.size == 0:
        raise ValueError("Cannot compute metrics on an empty evaluation sample")
    if np.isnan(y_true).any() or np.isnan(y_pred).any():
        raise ValueError("Actual and predicted arrays must not contain NaN values")

    errors = y_pred - y_true
    abs_errors = np.abs(errors)
    mae = float(np.mean(abs_errors))
    rmse = float(math.sqrt(float(np.mean(errors ** 2))))
    denom = float(np.sum(np.abs(y_true)))
    wape_pct = float(100.0 * float(np.sum(abs_errors)) / denom) if denom > 0.0 else float("nan")
    return {
        "mae": mae,
        "rmse": rmse,
        "wape_pct": wape_pct,
    }


def evaluate_validation_baselines(split_df: pd.DataFrame) -> dict[str, Any]:
    """Generate and evaluate both deterministic baselines on the 2025 validation partition only.

    The 2026 final test partition and beyond-M06 rows are never accessed or
    scored. Both baselines are strictly evaluated on the exact same common
    validation population; any row missing a required historical baseline input
    is transparently reported in ``excluded_missing_baseline_df`` rather than
    silently imputed.
    """
    if "split" not in split_df.columns or "evaluation_eligible" not in split_df.columns:
        split_df = assign_chronological_splits(split_df)

    # Strictly isolate the validation partition only; never touch test targets.
    parts_all = get_fixed_partitions(split_df, evaluable_only=False)
    val_all = parts_all["validation"].copy()
    if val_all.empty:
        raise ValueError("Validation partition is empty")
    if (val_all["split"] != "validation").any():
        raise ValueError("Non-validation row detected inside validation partition")

    excluded_absent_target_df = val_all.loc[~val_all["evaluation_eligible"]].reset_index(drop=True)
    val_evaluable = val_all.loc[val_all["evaluation_eligible"]].copy().reset_index(drop=True)

    if val_evaluable.duplicated(["org_code", "target_period"]).any():
        raise ValueError("Duplicate (org_code, target_period) keys in validation population")
    if val_evaluable[TARGET_COLUMN].isna().any():
        raise ValueError("Evaluable validation row contains missing target value")

    pred_latest = predict_latest_published(val_evaluable)
    pred_seasonal = predict_seasonal_naive(val_evaluable)

    # Common-sample rule: evaluate both baselines on identical records with non-null inputs.
    common_valid_mask = pred_latest.notna() & pred_seasonal.notna()
    excluded_missing_baseline_df = val_evaluable.loc[~common_valid_mask].reset_index(drop=True)

    scored = val_evaluable.loc[common_valid_mask].copy().reset_index(drop=True)
    if scored.empty:
        raise ValueError("No validation rows have complete baseline inputs")

    actual = scored[TARGET_COLUMN].astype("float64")
    p_latest = pred_latest.loc[common_valid_mask].reset_index(drop=True)
    p_seasonal = pred_seasonal.loc[common_valid_mask].reset_index(drop=True)

    predictions_df = pd.DataFrame(
        {
            "org_code": scored["org_code"].astype("string"),
            "origin_period": scored["origin_period"],
            "decision_date": scored["decision_date"],
            "target_period": scored["target_period"],
            "actual_type1_attendances": scored[TARGET_COLUMN].astype("Int64"),
            "pred_latest_published": p_latest,
            "pred_seasonal_naive": p_seasonal,
            "error_latest_published": p_latest - actual,
            "abs_error_latest_published": (p_latest - actual).abs(),
            "error_seasonal_naive": p_seasonal - actual,
            "abs_error_seasonal_naive": (p_seasonal - actual).abs(),
        }
    ).sort_values(["target_period", "org_code"]).reset_index(drop=True)

    if predictions_df.duplicated(["org_code", "target_period"]).any():
        raise ValueError("Duplicate (org_code, target_period) keys in baseline predictions")

    comparison_rows = []
    for spec in BASELINE_SPECS:
        m = compute_regression_metrics(
            predictions_df["actual_type1_attendances"].astype("float64"),
            predictions_df[spec["prediction_column"]],
        )
        comparison_rows.append(
            {
                "baseline": spec["baseline"],
                "display_name": spec["display_name"],
                "source_column": spec["source_column"],
                "lag_definition": spec["lag_definition"],
                "n_observations": int(len(predictions_df)),
                "n_providers": int(predictions_df["org_code"].nunique()),
                "mae": round(m["mae"], 4),
                "rmse": round(m["rmse"], 4),
                "wape_pct": round(m["wape_pct"], 4),
            }
        )
    comparison_df = pd.DataFrame(comparison_rows)

    monthly_rows = []
    for target_period, g in predictions_df.groupby("target_period", sort=True):
        m_latest = compute_regression_metrics(
            g["actual_type1_attendances"].astype("float64"),
            g["pred_latest_published"],
        )
        m_seasonal = compute_regression_metrics(
            g["actual_type1_attendances"].astype("float64"),
            g["pred_seasonal_naive"],
        )
        monthly_rows.append(
            {
                "target_period": target_period,
                "decision_date": g["decision_date"].iloc[0],
                "origin_period": g["origin_period"].iloc[0],
                "n_providers": int(len(g)),
                "total_actual_type1": int(g["actual_type1_attendances"].sum()),
                "latest_published_mae": round(m_latest["mae"], 4),
                "latest_published_rmse": round(m_latest["rmse"], 4),
                "latest_published_wape_pct": round(m_latest["wape_pct"], 4),
                "seasonal_naive_mae": round(m_seasonal["mae"], 4),
                "seasonal_naive_rmse": round(m_seasonal["rmse"], 4),
                "seasonal_naive_wape_pct": round(m_seasonal["wape_pct"], 4),
            }
        )
    monthly_breakdown_df = pd.DataFrame(monthly_rows)

    summary = {
        "partition": "validation",
        "test_set_evaluated": False,
        "target_period_start": predictions_df["target_period"].min().strftime("%Y-%m"),
        "target_period_end": predictions_df["target_period"].max().strftime("%Y-%m"),
        "target_months": int(predictions_df["target_period"].nunique()),
        "total_validation_eligible_rows": int(len(val_all)),
        "excluded_absent_target_rows": int(len(excluded_absent_target_df)),
        "excluded_absent_target_codes": excluded_absent_target_df["org_code"].tolist(),
        "excluded_missing_baseline_rows": int(len(excluded_missing_baseline_df)),
        "scored_observations": int(len(predictions_df)),
        "scored_distinct_providers": int(predictions_df["org_code"].nunique()),
        "reported_zero_actuals_in_validation": int((predictions_df["actual_type1_attendances"] == 0).sum()),
        "metrics": comparison_df.to_dict(orient="records"),
    }

    return {
        "predictions_df": predictions_df,
        "comparison_df": comparison_df,
        "monthly_breakdown_df": monthly_breakdown_df,
        "excluded_absent_target_df": excluded_absent_target_df,
        "excluded_missing_baseline_df": excluded_missing_baseline_df,
        "summary": summary,
    }


def export_validation_baselines(
    repo: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Load verified features, evaluate 2025 validation baselines, and export local evidence."""
    repo = Path(repo).resolve()
    feat_df, provenance = load_verified_features(repo)
    split_df = assign_chronological_splits(feat_df)
    results = evaluate_validation_baselines(split_df)

    dest = (repo / "outputs/baselines") if output_dir is None else Path(output_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    pred_path = dest / "validation_baseline_predictions.csv"
    comp_path = dest / "validation_baseline_comparison.csv"
    monthly_path = dest / "validation_baseline_monthly.csv"
    meta_path = dest / "baseline_metadata.json"

    results["predictions_df"].to_csv(pred_path, index=False, date_format="%Y-%m-%d")
    results["comparison_df"].to_csv(comp_path, index=False)
    results["monthly_breakdown_df"].to_csv(monthly_path, index=False, date_format="%Y-%m-%d")

    def _rel(p: Path) -> str:
        return p.relative_to(repo).as_posix() if p.is_relative_to(repo) else str(p)

    metadata = {
        "schema_version": "1.0",
        "provenance": provenance,
        "summary": results["summary"],
        "outputs": {
            "predictions_csv": {
                "path": _rel(pred_path),
                "sha256": sha256_file(pred_path),
                "rows": int(len(results["predictions_df"])),
            },
            "comparison_csv": {
                "path": _rel(comp_path),
                "sha256": sha256_file(comp_path),
                "rows": int(len(results["comparison_df"])),
            },
            "monthly_csv": {
                "path": _rel(monthly_path),
                "sha256": sha256_file(monthly_path),
                "rows": int(len(results["monthly_breakdown_df"])),
            },
        },
    }
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    return {
        **results,
        "provenance": provenance,
        "metadata": metadata,
        "metadata_path": str(meta_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    res = export_validation_baselines(args.repo, output_dir=args.output_dir)
    print(json.dumps(res["metadata"], indent=2))


if __name__ == "__main__":
    main()
