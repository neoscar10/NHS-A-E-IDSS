"""Leakage-safe historical feature engineering for NHS Type 1 A&E forecasting.

Converts the verified M06 provider calendar (referenced in
``docs/model_input_manifest.json``) into historical forecasting examples aligned
with the operational publication protocol documented in
``docs/FORECAST_PROTOCOL.md``:

- Target month: ``T`` (month-start date)
- Forecast decision date: last calendar day before ``T`` begins (end of ``T - 1``)
- Latest published NHS England report available on decision date: ``o = T - 2``
- Forecast horizon from latest published reporting month: ``h = 2`` months

All numerical predictors use strictly published observations from months
``<= o``; unpublished month ``T - 1`` and target month ``T`` are never used as
predictors.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.cohort_selection import (
    MANIFEST_REL_PATH,
    build_cohorts,
    load_accepted_m06,
    sha256_file,
)
from src.data.data_preprocessing import TARGET

HORIZON_MONTHS = 2
HISTORY_WINDOW_MONTHS = 12
TARGET_COLUMN = "target_type1_attendances"

METADATA_COLUMNS = [
    "org_code",
    "origin_period",
    "decision_date",
    "target_period",
    "target_year",
    "horizon_months",
    "history_window_months",
    "is_eligible_origin",
    "target_observed",
    "is_future_forecast",
    "has_complete_core_features",
    "has_complete_all_features",
]

ATTENDANCE_FEATURE_COLUMNS = [
    "type1_origin",
    "type1_origin_lag_1",
    "type1_origin_lag_2",
    "type1_origin_lag_3",
    "type1_origin_lag_12",
    "type1_target_lag_12",
]

ROLLING_FEATURE_COLUMNS = [
    "type1_origin_roll_mean_3",
    "type1_origin_roll_mean_6",
    "type1_origin_roll_mean_12",
]

CALENDAR_FEATURE_COLUMNS = [
    "target_month",
    "target_days_in_month",
    "target_month_sin",
    "target_month_cos",
]

CORE_FEATURE_COLUMNS = [
    *ATTENDANCE_FEATURE_COLUMNS,
    *ROLLING_FEATURE_COLUMNS,
    *CALENDAR_FEATURE_COLUMNS,
]

OPTIONAL_ADMISSION_FEATURE_COLUMNS = [
    "type1_emergency_admissions_origin",
    "type1_emergency_admissions_roll_mean_3",
    "type1_admission_rate_origin",
]

OPTIONAL_FOUR_HOUR_FEATURE_COLUMNS = [
    "type1_over_4hrs_origin",
    "type1_within_4hrs_rate_origin",
    "type1_within_4hrs_rate_roll_mean_3",
]

OPTIONAL_FEATURE_COLUMNS = [
    *OPTIONAL_ADMISSION_FEATURE_COLUMNS,
    *OPTIONAL_FOUR_HOUR_FEATURE_COLUMNS,
]

ALL_FEATURE_COLUMNS = [*CORE_FEATURE_COLUMNS, *OPTIONAL_FEATURE_COLUMNS]

PROHIBITED_PREDICTOR_COLUMNS = {
    TARGET_COLUMN,
    "org_code",
    "origin_period",
    "decision_date",
    "target_period",
    "target_year",
    "source_period",
    "source_month",
    "source_file",
    "source_sha256",
    "source_record_number",
    "material_continuity_concern",
    "sensitivity_eligible",
    "continuity_category",
}


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Compute numerator / denominator as float, returning NaN where denominator <= 0 or NA."""
    num = pd.to_numeric(numerator, errors="coerce").astype("float64")
    den = pd.to_numeric(denominator, errors="coerce").astype("float64")
    out = pd.Series(np.nan, index=numerator.index, dtype="float64")
    valid = num.notna() & den.notna() & (den > 0)
    out.loc[valid] = num.loc[valid] / den.loc[valid]
    return out


def _calendar_lookup(series_by_period: pd.Series, target_periods: pd.Index) -> pd.Series:
    """Align a per-provider monthly Series to explicit calendar dates without shifting over gaps."""
    return series_by_period.reindex(target_periods)


def build_feature_dataset(
    calendar_df: pd.DataFrame,
    window: int = HISTORY_WINDOW_MONTHS,
    horizon: int = HORIZON_MONTHS,
    verify_existing_eligibility: bool = True,
) -> pd.DataFrame:
    """Build leakage-safe historical forecasting examples from an M06 provider calendar.

    Parameters
    ----------
    calendar_df:
        Verified M06 provider calendar (or synthetic test calendar) containing
        explicit monthly rows from each provider's first observation through the
        collection end date.
    window:
        Consecutive observed months required for primary cohort eligibility at
        data origin ``o`` (default ``12``).
    horizon:
        Reporting-month offset from latest published report ``o`` to target
        month ``T = o + horizon`` (default ``2`` per ``docs/FORECAST_PROTOCOL.md``).
    verify_existing_eligibility:
        If True, verify Step 3 recomputed eligibility agrees with existing M06
        columns when present.

    Returns
    -------
    pd.DataFrame
        One row per eligible provider-origin ``(org_code, origin_period)`` with
        metadata, target label ``target_type1_attendances`` (nullable Int64),
        core historical/calendar features, and optional published operational
        features. No rows are discarded due to missing optional or lag-12
        features, and absent targets remain ``<NA>``.
    """
    if not isinstance(horizon, int) or horizon < 1:
        raise ValueError("Forecast horizon must be a positive integer")
    if horizon != HORIZON_MONTHS:
        raise ValueError(
            f"Forecast protocol requires horizon={HORIZON_MONTHS} (o = T - 2); got {horizon}"
        )

    cohorts = build_cohorts(
        calendar_df,
        window=window,
        verify_existing=verify_existing_eligibility,
    )
    cal = cohorts["cohort_calendar"].copy()
    cal["period"] = pd.to_datetime(cal["period"], errors="raise")
    max_dataset_period = cal["period"].max()

    has_admissions = "type1_emergency_admissions" in cal.columns
    has_over_4hrs = "type1_over_4hrs" in cal.columns

    parts: list[pd.DataFrame] = []
    for code, grp in cal.groupby("org_code", sort=True):
        g = grp.sort_values("period").set_index("period")
        full_index = pd.date_range(g.index.min(), g.index.max(), freq="MS")
        if len(g) != len(full_index) or not (g.index.to_numpy() == full_index.to_numpy()).all():
            raise ValueError(f"Non-contiguous calendar for org_code={code!r}")

        # Keep missing months as explicit NaN; never forward-fill or drop before lagging.
        t1_float = pd.to_numeric(g[TARGET], errors="coerce").astype("float64")
        t1_float = t1_float.where(g["is_observed"], np.nan)

        # Strictly trailing rolling means over contiguous monthly calendar [o - w + 1, o].
        roll3 = t1_float.rolling(3, min_periods=3).mean()
        roll6 = t1_float.rolling(6, min_periods=6).mean()
        roll12 = t1_float.rolling(12, min_periods=12).mean()

        # Optional published operational series (all strictly <= o).
        if has_admissions:
            adm_float = pd.to_numeric(g["type1_emergency_admissions"], errors="coerce").astype("float64")
            adm_float = adm_float.where(g["is_observed"], np.nan)
            adm_roll3 = adm_float.rolling(3, min_periods=3).mean()
            adm_rate = _safe_ratio(adm_float, t1_float)
        else:
            adm_float = pd.Series(np.nan, index=g.index, dtype="float64")
            adm_roll3 = pd.Series(np.nan, index=g.index, dtype="float64")
            adm_rate = pd.Series(np.nan, index=g.index, dtype="float64")

        if has_over_4hrs:
            ov4_float = pd.to_numeric(g["type1_over_4hrs"], errors="coerce").astype("float64")
            ov4_float = ov4_float.where(g["is_observed"], np.nan)
            within4_rate = 1.0 - _safe_ratio(ov4_float, t1_float)
            within4_roll3 = within4_rate.rolling(3, min_periods=3).mean()
        else:
            ov4_float = pd.Series(np.nan, index=g.index, dtype="float64")
            within4_rate = pd.Series(np.nan, index=g.index, dtype="float64")
            within4_roll3 = pd.Series(np.nan, index=g.index, dtype="float64")

        # Select Step 3 primary past-only eligible origins AFTER computing calendar-aligned history.
        elig_origins = g.index[g["provisional_eligible"]]
        if len(elig_origins) == 0:
            continue

        origin_idx = pd.DatetimeIndex(elig_origins)
        target_idx = pd.DatetimeIndex([p + pd.DateOffset(months=horizon) for p in origin_idx])
        decision_idx = pd.DatetimeIndex([t - pd.DateOffset(days=1) for t in target_idx])

        # Explicit actual-calendar-date lookups (never positional shift over filtered rows).
        lag1_idx = pd.DatetimeIndex([p - pd.DateOffset(months=1) for p in origin_idx])
        lag2_idx = pd.DatetimeIndex([p - pd.DateOffset(months=2) for p in origin_idx])
        lag3_idx = pd.DatetimeIndex([p - pd.DateOffset(months=3) for p in origin_idx])
        lag12_idx = pd.DatetimeIndex([p - pd.DateOffset(months=12) for p in origin_idx])
        # Same calendar month as T one year earlier: T - 12 = (o + 2) - 12 = o - 10.
        target_lag12_idx = pd.DatetimeIndex([t - pd.DateOffset(months=12) for t in target_idx])

        # Target lookup strictly at (org_code, T); absent or out-of-range remains NA.
        target_vals_raw = _calendar_lookup(g[TARGET].where(g["is_observed"], pd.NA), target_idx)
        target_obs_raw = _calendar_lookup(g["is_observed"].astype("boolean"), target_idx).fillna(False)

        target_months = target_idx.month.astype("int64")
        angles = 2.0 * math.pi * target_months / 12.0

        block = pd.DataFrame(
            {
                "org_code": pd.Series([str(code)] * len(origin_idx), dtype="string"),
                "origin_period": origin_idx,
                "decision_date": decision_idx,
                "target_period": target_idx,
                "target_year": target_idx.year.astype("int64"),
                "horizon_months": int(horizon),
                "history_window_months": int(window),
                "is_eligible_origin": True,
                "target_observed": target_obs_raw.to_numpy(dtype=bool),
                "is_future_forecast": (target_idx > max_dataset_period).astype(bool),
                TARGET_COLUMN: pd.array(target_vals_raw.to_list(), dtype="Int64"),
                # Core attendance features (strictly <= o)
                "type1_origin": _calendar_lookup(t1_float, origin_idx).to_numpy(dtype="float64"),
                "type1_origin_lag_1": _calendar_lookup(t1_float, lag1_idx).to_numpy(dtype="float64"),
                "type1_origin_lag_2": _calendar_lookup(t1_float, lag2_idx).to_numpy(dtype="float64"),
                "type1_origin_lag_3": _calendar_lookup(t1_float, lag3_idx).to_numpy(dtype="float64"),
                "type1_origin_lag_12": _calendar_lookup(t1_float, lag12_idx).to_numpy(dtype="float64"),
                "type1_target_lag_12": _calendar_lookup(t1_float, target_lag12_idx).to_numpy(dtype="float64"),
                # Core rolling features ending at o
                "type1_origin_roll_mean_3": _calendar_lookup(roll3, origin_idx).to_numpy(dtype="float64"),
                "type1_origin_roll_mean_6": _calendar_lookup(roll6, origin_idx).to_numpy(dtype="float64"),
                "type1_origin_roll_mean_12": _calendar_lookup(roll12, origin_idx).to_numpy(dtype="float64"),
                # Target calendar features (deterministic)
                "target_month": target_months,
                "target_days_in_month": target_idx.days_in_month.astype("int64"),
                "target_month_sin": np.sin(angles),
                "target_month_cos": np.cos(angles),
                # Optional published operational features (strictly <= o)
                "type1_emergency_admissions_origin": _calendar_lookup(adm_float, origin_idx).to_numpy(dtype="float64"),
                "type1_emergency_admissions_roll_mean_3": _calendar_lookup(adm_roll3, origin_idx).to_numpy(dtype="float64"),
                "type1_admission_rate_origin": _calendar_lookup(adm_rate, origin_idx).to_numpy(dtype="float64"),
                "type1_over_4hrs_origin": _calendar_lookup(ov4_float, origin_idx).to_numpy(dtype="float64"),
                "type1_within_4hrs_rate_origin": _calendar_lookup(within4_rate, origin_idx).to_numpy(dtype="float64"),
                "type1_within_4hrs_rate_roll_mean_3": _calendar_lookup(within4_roll3, origin_idx).to_numpy(dtype="float64"),
            }
        )

        block["has_complete_core_features"] = block[CORE_FEATURE_COLUMNS].notna().all(axis=1)
        block["has_complete_all_features"] = block[ALL_FEATURE_COLUMNS].notna().all(axis=1)
        parts.append(block)

    ordered_cols = [
        *METADATA_COLUMNS,
        TARGET_COLUMN,
        *CORE_FEATURE_COLUMNS,
        *OPTIONAL_FEATURE_COLUMNS,
    ]
    if not parts:
        return pd.DataFrame(columns=ordered_cols)

    features = (
        pd.concat(parts, ignore_index=True)
        .sort_values(["origin_period", "org_code"])
        .reset_index(drop=True)[ordered_cols]
    )

    if features.duplicated(["org_code", "origin_period"]).any():
        raise ValueError("Duplicate (org_code, origin_period) keys produced")
    if features.duplicated(["org_code", "target_period"]).any():
        raise ValueError("Duplicate (org_code, target_period) keys produced")
    if (features.loc[~features["target_observed"], TARGET_COLUMN].notna()).any():
        raise ValueError("Unobserved target row unexpectedly contains a target value")

    return features


def get_predictor_matrix(
    feature_df: pd.DataFrame,
    include_optional: bool = True,
) -> pd.DataFrame:
    """Extract only leakage-safe predictor columns (never target, metadata, or flags)."""
    cols = list(ALL_FEATURE_COLUMNS if include_optional else CORE_FEATURE_COLUMNS)
    overlap = set(cols) & PROHIBITED_PREDICTOR_COLUMNS
    if overlap:
        raise ValueError(f"Prohibited columns detected in predictor list: {sorted(overlap)}")
    missing = [c for c in cols if c not in feature_df.columns]
    if missing:
        raise ValueError(f"Feature frame missing predictor columns: {missing}")
    return feature_df[cols].copy()


def summarise_feature_dataset(feature_df: pd.DataFrame) -> dict[str, Any]:
    """Return structured completeness, target-observability, and missingness counts."""
    missing_by_feature = {
        col: int(feature_df[col].isna().sum()) for col in ALL_FEATURE_COLUMNS
    }
    in_range = ~feature_df["is_future_forecast"]
    absent_in_range = in_range & ~feature_df["target_observed"]
    evaluable = feature_df["target_observed"]
    return {
        "eligible_origins": int(len(feature_df)),
        "distinct_providers": int(feature_df["org_code"].nunique()),
        "origin_period_start": (
            feature_df["origin_period"].min().strftime("%Y-%m") if len(feature_df) else ""
        ),
        "origin_period_end": (
            feature_df["origin_period"].max().strftime("%Y-%m") if len(feature_df) else ""
        ),
        "target_period_start": (
            feature_df["target_period"].min().strftime("%Y-%m") if len(feature_df) else ""
        ),
        "target_period_end": (
            feature_df["target_period"].max().strftime("%Y-%m") if len(feature_df) else ""
        ),
        "in_range_origins": int(in_range.sum()),
        "target_observed_rows": int(evaluable.sum()),
        "absent_target_rows_in_range": int(absent_in_range.sum()),
        "future_forecast_rows": int(feature_df["is_future_forecast"].sum()),
        "complete_core_feature_rows": int(feature_df["has_complete_core_features"].sum()),
        "complete_all_feature_rows": int(feature_df["has_complete_all_features"].sum()),
        "evaluable_with_complete_core_features": int(
            (evaluable & feature_df["has_complete_core_features"]).sum()
        ),
        "evaluable_with_complete_all_features": int(
            (evaluable & feature_df["has_complete_all_features"]).sum()
        ),
        "core_feature_count": len(CORE_FEATURE_COLUMNS),
        "optional_feature_count": len(OPTIONAL_FEATURE_COLUMNS),
        "total_predictor_count": len(ALL_FEATURE_COLUMNS),
        "missing_counts_by_feature": missing_by_feature,
    }


def export_feature_dataset(
    repo: Path,
    output_dir: Path | None = None,
    manifest_rel_path: Path = MANIFEST_REL_PATH,
) -> dict[str, Any]:
    """Load accepted M06 input, build features, and materialise outputs into a local ignored directory."""
    repo = Path(repo).resolve()
    panel, manifest = load_accepted_m06(repo, manifest_rel_path=manifest_rel_path)
    features = build_feature_dataset(panel, window=HISTORY_WINDOW_MONTHS, horizon=HORIZON_MONTHS)
    summary = summarise_feature_dataset(features)

    dest = (repo / "outputs/features") if output_dir is None else Path(output_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    csv_path = dest / "m06_historical_features.csv"
    pq_path = dest / "m06_historical_features.parquet"
    meta_path = dest / "feature_metadata.json"

    features.to_csv(csv_path, index=False, date_format="%Y-%m-%d")
    features.to_parquet(pq_path, index=False, engine="pyarrow")

    metadata = {
        "schema_version": "1.0",
        "source_manifest": manifest_rel_path.as_posix(),
        "input_m06_run_id": manifest["provenance"]["m06_run_id"],
        "input_m06_path": manifest["dataset"]["repository_relative_path"],
        "input_m06_sha256": manifest["dataset"]["sha256"],
        "horizon_months": HORIZON_MONTHS,
        "history_window_months": HISTORY_WINDOW_MONTHS,
        "metadata_columns": METADATA_COLUMNS,
        "target_column": TARGET_COLUMN,
        "core_feature_columns": CORE_FEATURE_COLUMNS,
        "optional_feature_columns": OPTIONAL_FEATURE_COLUMNS,
        "outputs": {
            "csv": {"path": csv_path.relative_to(repo).as_posix() if csv_path.is_relative_to(repo) else str(csv_path), "sha256": sha256_file(csv_path), "rows": int(len(features))},
            "parquet": {"path": pq_path.relative_to(repo).as_posix() if pq_path.is_relative_to(repo) else str(pq_path), "sha256": sha256_file(pq_path), "rows": int(len(features))},
        },
        "summary": summary,
    }
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"features": features, "metadata": metadata, "metadata_path": str(meta_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    result = export_feature_dataset(args.repo, output_dir=args.output_dir)
    print(json.dumps(result["metadata"], indent=2))


if __name__ == "__main__":
    main()
