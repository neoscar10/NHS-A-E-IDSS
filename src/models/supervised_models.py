"""Reusable supervised regression candidate pipelines for NHS Type 1 A&E forecasting.

Implements three deterministic scikit-learn regression pipelines using the
exact 13 core predictors from ``src/models/feature_engineering.py`` and the
publication-aware expanding-window training cutoffs from
``src/models/evaluation_splits.py``:

1. ``ridge`` — ``StandardScaler`` + ``Ridge`` inside an sklearn ``Pipeline``
2. ``random_forest`` — ``RandomForestRegressor`` (no scaling)
3. ``hist_gradient_boosting`` — ``HistGradientBoostingRegressor`` with
   ``early_stopping=False`` (no scaling, no internal random validation split)

All functions are horizon- and month-agnostic so they can be reused directly
in Step 9 expanding-window validation without modification. Step 8 performs
initial training-fold fitting only and does not evaluate 2025 validation or
2026 test targets.
"""
from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.base import is_regressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.data.cohort_selection import sha256_file
from src.models.evaluation_splits import (
    assign_chronological_splits,
    get_expanding_window_split,
    load_verified_features,
)
from src.models.feature_engineering import (
    CORE_FEATURE_COLUMNS,
    PROHIBITED_PREDICTOR_COLUMNS,
    TARGET_COLUMN,
)

EXPECTED_CORE_FEATURES: tuple[str, ...] = (
    "type1_origin",
    "type1_origin_lag_1",
    "type1_origin_lag_2",
    "type1_origin_lag_3",
    "type1_origin_lag_12",
    "type1_target_lag_12",
    "type1_origin_roll_mean_3",
    "type1_origin_roll_mean_6",
    "type1_origin_roll_mean_12",
    "target_month",
    "target_days_in_month",
    "target_month_sin",
    "target_month_cos",
)

MODEL_NAMES: tuple[str, ...] = (
    "ridge",
    "random_forest",
    "hist_gradient_boosting",
)

RANDOM_SEED = 42
INITIAL_DEMO_TARGET_MONTH = "2025-01-01"

DEFAULT_MODEL_PARAMS: dict[str, dict[str, Any]] = {
    "ridge": {
        "alpha": 10.0,
    },
    "random_forest": {
        "n_estimators": 200,
        "max_depth": 12,
        "min_samples_leaf": 5,
        "random_state": RANDOM_SEED,
        "n_jobs": 1,
    },
    "hist_gradient_boosting": {
        "learning_rate": 0.05,
        "max_iter": 200,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 20,
        "l2_regularization": 1.0,
        "early_stopping": False,
        "random_state": RANDOM_SEED,
    },
}


def get_core_feature_columns() -> list[str]:
    """Return the verified 13 core predictor columns in fixed canonical order."""
    cols = list(CORE_FEATURE_COLUMNS)
    if tuple(cols) != EXPECTED_CORE_FEATURES:
        raise ValueError(
            f"CORE_FEATURE_COLUMNS {cols} disagrees with approved 13-feature contract "
            f"{list(EXPECTED_CORE_FEATURES)}"
        )
    if set(cols) & PROHIBITED_PREDICTOR_COLUMNS:
        raise ValueError("Prohibited metadata or target column found in core features")
    return cols


def create_model_pipeline(model_name: str, **param_overrides: Any) -> Pipeline:
    """Construct an unfitted scikit-learn regression Pipeline for the named candidate."""
    if model_name not in MODEL_NAMES:
        raise ValueError(f"Unknown model_name={model_name!r}; expected one of {MODEL_NAMES}")

    params = {**DEFAULT_MODEL_PARAMS[model_name], **param_overrides}

    if model_name == "ridge":
        pipe = Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                ("model", Ridge(**params)),
            ]
        )
    elif model_name == "random_forest":
        pipe = Pipeline(
            steps=[
                ("model", RandomForestRegressor(**params)),
            ]
        )
    elif model_name == "hist_gradient_boosting":
        if params.get("early_stopping", False) is not False and "early_stopping" not in param_overrides:
            raise ValueError("Default HistGradientBoostingRegressor must disable early_stopping")
        pipe = Pipeline(
            steps=[
                ("model", HistGradientBoostingRegressor(**params)),
            ]
        )
    else:
        raise ValueError(f"Unsupported model_name={model_name!r}")

    if not is_regressor(pipe):
        raise TypeError(f"Pipeline for {model_name!r} is not a scikit-learn regressor")
    return pipe


def select_training_fold(
    split_df: pd.DataFrame,
    target_period: str | pd.Timestamp,
    *,
    complete_core_only: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Select publication-eligible historical training rows for forecasting ``target_period``.

    Uses ``src.models.evaluation_splits.get_expanding_window_split`` to enforce
    ``target_period <= T - 2`` (excluding unpublished ``T - 1`` and target ``T``).
    When ``complete_core_only=True`` (default), excludes rows missing any of the
    13 core features (e.g., the 124 early ``2023-02`` rows missing
    ``type1_origin_lag_12``) without imputing missing lag values.
    """
    if "split" not in split_df.columns or "evaluation_eligible" not in split_df.columns:
        split_df = assign_chronological_splits(split_df)

    step = get_expanding_window_split(split_df, target_period, complete_features_only=False)
    permissible = step["train_df"].copy()

    core_cols = get_core_feature_columns()
    complete_mask = permissible[core_cols].notna().all(axis=1)
    if complete_core_only:
        train_df = permissible.loc[complete_mask].reset_index(drop=True)
    else:
        train_df = permissible.reset_index(drop=True)

    # Strict leakage & completeness guards
    cutoff = step["latest_published_period"]
    if not train_df.empty and (train_df["target_period"] > cutoff).any():
        raise ValueError("Leakage violation: training fold contains rows after latest published cutoff")
    if not train_df["evaluation_eligible"].all():
        raise ValueError("Training fold contains non-evaluable rows")
    if train_df[TARGET_COLUMN].isna().any():
        raise ValueError("Training fold contains missing target labels")

    fold_info = {
        "forecast_target_period": step["target_period"].strftime("%Y-%m"),
        "decision_date": step["decision_date"].strftime("%Y-%m-%d"),
        "latest_published_period": cutoff.strftime("%Y-%m"),
        "unpublished_prior_period": step["unpublished_prior_period"].strftime("%Y-%m"),
        "excluded_unpublished_t_minus_1_rows": int(step["excluded_unpublished_t_minus_1_rows"]),
        "eligible_observed_training_rows": int(len(permissible)),
        "complete_core_training_rows": int(complete_mask.sum()),
        "excluded_incomplete_core_rows": int((~complete_mask).sum()),
        "fitted_training_rows": int(len(train_df)),
        "complete_core_only": bool(complete_core_only),
        "train_target_start": (
            train_df["target_period"].min().strftime("%Y-%m") if not train_df.empty else ""
        ),
        "train_target_end": (
            train_df["target_period"].max().strftime("%Y-%m") if not train_df.empty else ""
        ),
        "train_distinct_providers": int(train_df["org_code"].nunique()) if not train_df.empty else 0,
    }
    return train_df, fold_info


def prepare_feature_matrix(
    df: pd.DataFrame,
    feature_columns: list[str] | None = None,
    *,
    allow_missing: bool = False,
) -> pd.DataFrame:
    """Extract and validate the exact predictor matrix in canonical column order."""
    cols = get_core_feature_columns() if feature_columns is None else list(feature_columns)
    overlap = set(cols) & PROHIBITED_PREDICTOR_COLUMNS
    if overlap:
        raise ValueError(f"Prohibited columns in feature matrix: {sorted(overlap)}")
    missing_cols = [c for c in cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Input DataFrame missing predictor columns: {missing_cols}")

    X = df[cols].astype("float64").copy()
    if not allow_missing and X.isna().any().any():
        bad = X.columns[X.isna().any()].tolist()
        raise ValueError(f"Feature matrix contains missing values in columns: {bad}")
    if np.isinf(X.to_numpy()).any():
        raise ValueError("Feature matrix contains non-finite values")
    return X


def fit_model(
    model_name: str,
    train_df: pd.DataFrame,
    *,
    feature_columns: list[str] | None = None,
    **param_overrides: Any,
) -> Pipeline:
    """Instantiate and fit a candidate regression Pipeline strictly on ``train_df``."""
    if train_df.empty:
        raise ValueError("Cannot fit model on an empty training DataFrame")
    if TARGET_COLUMN not in train_df.columns:
        raise ValueError(f"Training DataFrame missing target column {TARGET_COLUMN!r}")
    if train_df[TARGET_COLUMN].isna().any():
        raise ValueError("Training DataFrame contains null target values")

    X_train = prepare_feature_matrix(train_df, feature_columns=feature_columns, allow_missing=False)
    y_train = train_df[TARGET_COLUMN].astype("float64").to_numpy()
    if np.isnan(y_train).any() or np.isinf(y_train).any():
        raise ValueError("Training target vector contains non-finite values")

    pipeline = create_model_pipeline(model_name, **param_overrides)
    pipeline.fit(X_train, y_train)
    return pipeline


def predict_with_model(
    fitted_pipeline: Pipeline,
    df: pd.DataFrame,
    *,
    clip_non_negative: bool = True,
    feature_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Generate predictions from a fitted pipeline, preserving raw and clipped outputs.

    Because Type 1 A&E attendance is a non-negative count, ``clip_non_negative=True``
    applies the fixed domain rule ``max(0.0, raw_prediction)`` while preserving
    ``raw_prediction`` and ``was_clipped`` for diagnostics.
    """
    X = prepare_feature_matrix(df, feature_columns=feature_columns, allow_missing=False)
    raw = np.asarray(fitted_pipeline.predict(X), dtype="float64")
    if raw.shape != (len(df),):
        raise ValueError(f"Unexpected prediction shape {raw.shape} for {len(df)} rows")
    if not np.isfinite(raw).all():
        raise ValueError("Model generated non-finite predictions")

    clipped = np.clip(raw, 0.0, None) if clip_non_negative else raw.copy()
    was_clipped = raw < 0.0 if clip_non_negative else np.zeros(len(raw), dtype=bool)
    return pd.DataFrame(
        {
            "raw_prediction": raw,
            "prediction": clipped,
            "was_clipped": was_clipped,
        },
        index=df.index,
    )


def extract_fitted_metadata(model_name: str, fitted_pipeline: Pipeline) -> dict[str, Any]:
    """Extract serialisable configuration and fitted preprocessing metadata."""
    estimator = fitted_pipeline.named_steps["model"]
    info: dict[str, Any] = {
        "model_name": model_name,
        "estimator_class": f"{type(estimator).__module__}.{type(estimator).__name__}",
        "pipeline_steps": list(fitted_pipeline.named_steps.keys()),
        "params": {
            k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v))
            for k, v in estimator.get_params().items()
        },
        "n_features_in": int(estimator.n_features_in_),
        "feature_names_in": (
            [str(c) for c in fitted_pipeline.feature_names_in_]
            if hasattr(fitted_pipeline, "feature_names_in_")
            else []
        ),
    }

    if "scaler" in fitted_pipeline.named_steps:
        scaler = fitted_pipeline.named_steps["scaler"]
        info["preprocessing"] = {
            "step": "StandardScaler",
            "n_samples_seen": int(scaler.n_samples_seen_),
            "feature_means": [round(float(x), 6) for x in scaler.mean_],
            "feature_scales": [round(float(x), 6) for x in scaler.scale_],
        }
    else:
        info["preprocessing"] = {"step": "none"}

    if model_name == "ridge":
        info["fitted_summary"] = {
            "intercept": round(float(estimator.intercept_), 6),
            "coefficients": {
                col: round(float(c), 6)
                for col, c in zip(info["feature_names_in"], estimator.coef_)
            },
        }
    elif model_name == "random_forest":
        info["fitted_summary"] = {
            "n_estimators_fitted": len(estimator.estimators_),
            "max_depth": estimator.max_depth,
            "min_samples_leaf": estimator.min_samples_leaf,
            "random_state": estimator.random_state,
        }
    elif model_name == "hist_gradient_boosting":
        info["fitted_summary"] = {
            "n_iter_fitted": int(estimator.n_iter_),
            "early_stopping": bool(estimator.early_stopping),
            "learning_rate": float(estimator.learning_rate),
            "max_leaf_nodes": estimator.max_leaf_nodes,
            "min_samples_leaf": int(estimator.min_samples_leaf),
            "l2_regularization": float(estimator.l2_regularization),
            "random_state": estimator.random_state,
        }
    return info


def save_model_artefact(fitted_pipeline: Pipeline, path: Path) -> dict[str, Any]:
    """Persist a fitted pipeline locally using joblib and return its SHA-256 metadata."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(fitted_pipeline, path)
    return {
        "path": str(path),
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def load_model_artefact(path: Path) -> Pipeline:
    """Load a previously saved local joblib pipeline."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Model artefact not found: {path}")
    loaded = joblib.load(path)
    if not isinstance(loaded, Pipeline) or not is_regressor(loaded):
        raise TypeError(f"Loaded artefact is not a scikit-learn regression Pipeline: {type(loaded)}")
    return loaded


def get_environment_versions() -> dict[str, str]:
    """Record exact Python and modelling dependency versions."""
    return {
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
        "joblib": joblib.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
    }


def run_initial_training_fit(
    repo: Path,
    target_period: str | pd.Timestamp = INITIAL_DEMO_TARGET_MONTH,
    *,
    output_dir: Path | None = None,
    save_artefacts: bool = True,
) -> dict[str, Any]:
    """Fit all three candidate models on the publication-aware training fold for ``target_period``.

    Strictly fits on ``target_period <= T - 2`` (complete core features only)
    and produces ONLY in-sample training-fold sanity diagnostics. Does NOT
    predict or score 2025 validation or 2026 test targets.
    """
    repo = Path(repo).resolve()
    feat_df, provenance = load_verified_features(repo)
    split_df = assign_chronological_splits(feat_df)
    train_df, fold_info = select_training_fold(split_df, target_period, complete_core_only=True)
    core_cols = get_core_feature_columns()

    dest = (repo / "outputs/models/initial_fit") if output_dir is None else Path(output_dir).resolve()
    if save_artefacts:
        dest.mkdir(parents=True, exist_ok=True)

    fitted_models: dict[str, Pipeline] = {}
    model_records: dict[str, Any] = {}
    in_sample_diagnostics = train_df[
        ["org_code", "origin_period", "decision_date", "target_period", TARGET_COLUMN]
    ].copy()

    tag = pd.Timestamp(target_period).strftime("%Y-%m")
    for name in MODEL_NAMES:
        pipe = fit_model(name, train_df, feature_columns=core_cols)
        preds = predict_with_model(pipe, train_df, clip_non_negative=True, feature_columns=core_cols)
        fitted_models[name] = pipe

        in_sample_diagnostics[f"in_sample_raw_{name}"] = preds["raw_prediction"].to_numpy()
        in_sample_diagnostics[f"in_sample_pred_{name}"] = preds["prediction"].to_numpy()

        rec: dict[str, Any] = {
            **extract_fitted_metadata(name, pipe),
            "in_sample_diagnostic_summary": {
                "n_rows": int(len(preds)),
                "min_raw_prediction": round(float(preds["raw_prediction"].min()), 2),
                "max_raw_prediction": round(float(preds["raw_prediction"].max()), 2),
                "clipped_negative_count": int(preds["was_clipped"].sum()),
                "note": "In-sample training-fold sanity check only; not out-of-sample generalisation evidence.",
            },
        }
        if save_artefacts:
            art_path = dest / f"{name}_{tag}.joblib"
            art_meta = save_model_artefact(pipe, art_path)
            art_meta["path"] = (
                art_path.relative_to(repo).as_posix() if art_path.is_relative_to(repo) else str(art_path)
            )
            rec["artefact"] = art_meta
        model_records[name] = rec

    metadata: dict[str, Any] = {
        "schema_version": "1.0",
        "stage": "step_8_initial_supervised_model_fit",
        "validation_evaluated": False,
        "test_evaluated": False,
        "prediction_policy": {
            "clip_non_negative": True,
            "preserve_raw_prediction": True,
            "rationale": "Type 1 A&E attendances are non-negative counts; fixed domain rule not tuned on validation or test data.",
        },
        "environment": get_environment_versions(),
        "provenance": provenance,
        "feature_columns": core_cols,
        "feature_count": len(core_cols),
        "target_column": TARGET_COLUMN,
        "training_fold": fold_info,
        "models": model_records,
    }

    meta_path = dest / f"initial_fit_metadata_{tag}.json"
    if save_artefacts:
        meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    return {
        "train_df": train_df,
        "fold_info": fold_info,
        "fitted_models": fitted_models,
        "in_sample_diagnostics": in_sample_diagnostics,
        "metadata": metadata,
        "metadata_path": str(meta_path) if save_artefacts else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--target-period", default=INITIAL_DEMO_TARGET_MONTH)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    res = run_initial_training_fit(
        args.repo,
        target_period=args.target_period,
        output_dir=args.output_dir,
        save_artefacts=True,
    )
    print(json.dumps(res["metadata"], indent=2))


if __name__ == "__main__":
    main()
