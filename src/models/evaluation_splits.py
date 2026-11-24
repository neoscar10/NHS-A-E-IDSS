"""Reproducible chronological evaluation splits and publication-aware backtesting.

Loads the verified Step 5 historical feature dataset (checking provenance
against both ``outputs/features/feature_metadata.json`` and
``docs/model_input_manifest.json``), assigns fixed chronological partitions by
``target_period``, and provides publication-aware expanding-window training
cutoffs obeying the NHS England two-month reporting lag (``o = T - 2``).

No scalers, imputers, encoders, or forecasting models are fitted in this module.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from src.data.cohort_selection import MANIFEST_REL_PATH, sha256_file
from src.models.feature_engineering import (
    ALL_FEATURE_COLUMNS,
    CORE_FEATURE_COLUMNS,
    HORIZON_MONTHS,
    TARGET_COLUMN,
)

FEATURE_METADATA_REL_PATH = Path("outputs/features/feature_metadata.json")

# Fixed chronological partition boundaries (inclusive, by target_period month-start).
TRAIN_START = pd.Timestamp("2023-02-01")
TRAIN_END = pd.Timestamp("2024-12-01")
VALIDATION_START = pd.Timestamp("2025-01-01")
VALIDATION_END = pd.Timestamp("2025-12-01")
TEST_START = pd.Timestamp("2026-01-01")
TEST_END = pd.Timestamp("2026-09-01")
FUTURE_START = pd.Timestamp("2026-10-01")

PARTITION_ORDER = ("train", "validation", "test", "future_unlabelled")
LABELLED_PARTITIONS = ("train", "validation", "test")

EXCLUSION_NONE = ""
EXCLUSION_FUTURE_UNLABELLED = "future_target_beyond_m06"
EXCLUSION_ABSENT_TARGET = "absent_target_provider_unreported"


def load_verified_features(
    repo: Path,
    feature_metadata_rel_path: Path = FEATURE_METADATA_REL_PATH,
    manifest_rel_path: Path = MANIFEST_REL_PATH,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load the Step 5 feature dataset after verifying M06 and feature SHA-256 provenance."""
    repo = Path(repo).resolve()
    manifest_path = repo / manifest_rel_path
    meta_path = repo / feature_metadata_rel_path

    if not manifest_path.is_file():
        raise FileNotFoundError(f"Model input manifest not found: {manifest_path}")
    if not meta_path.is_file():
        raise FileNotFoundError(f"Feature metadata not found: {meta_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fmeta = json.loads(meta_path.read_text(encoding="utf-8"))

    m06_path = (repo / manifest["dataset"]["repository_relative_path"]).resolve()
    if not m06_path.is_file():
        raise FileNotFoundError(f"Accepted M06 dataset missing: {m06_path}")
    actual_m06_sha = sha256_file(m06_path)
    expected_m06_sha = manifest["dataset"]["sha256"]
    if actual_m06_sha != expected_m06_sha:
        raise ValueError(
            f"Accepted M06 SHA-256 mismatch: expected {expected_m06_sha}, got {actual_m06_sha}"
        )
    if fmeta.get("input_m06_sha256") != expected_m06_sha:
        raise ValueError(
            "Feature metadata input_m06_sha256 does not match docs/model_input_manifest.json"
        )
    if fmeta.get("input_m06_run_id") != manifest["provenance"]["m06_run_id"]:
        raise ValueError(
            "Feature metadata input_m06_run_id does not match docs/model_input_manifest.json"
        )

    csv_info = fmeta.get("outputs", {}).get("csv", {})
    feat_csv_path = (repo / csv_info["path"]).resolve()
    if not feat_csv_path.is_file():
        raise FileNotFoundError(f"Materialised feature CSV not found: {feat_csv_path}")
    actual_feat_sha = sha256_file(feat_csv_path)
    if actual_feat_sha != csv_info["sha256"]:
        raise ValueError(
            f"Feature CSV SHA-256 mismatch: expected {csv_info['sha256']}, got {actual_feat_sha}"
        )

    df = pd.read_csv(feat_csv_path, dtype={"org_code": "string"})
    for dcol in ("origin_period", "decision_date", "target_period"):
        df[dcol] = pd.to_datetime(df[dcol], format="%Y-%m-%d", errors="raise")
    for bcol in (
        "is_eligible_origin",
        "target_observed",
        "is_future_forecast",
        "has_complete_core_features",
        "has_complete_all_features",
    ):
        df[bcol] = df[bcol].astype(bool)
    df[TARGET_COLUMN] = pd.to_numeric(df[TARGET_COLUMN], errors="raise").astype("Int64")

    if len(df) != csv_info["rows"]:
        raise ValueError(f"Feature CSV row count mismatch: expected {csv_info['rows']}, got {len(df)}")

    provenance = {
        "manifest_path": manifest_rel_path.as_posix(),
        "m06_run_id": manifest["provenance"]["m06_run_id"],
        "m06_csv_path": manifest["dataset"]["repository_relative_path"],
        "m06_csv_sha256": expected_m06_sha,
        "feature_metadata_path": feature_metadata_rel_path.as_posix(),
        "feature_csv_path": csv_info["path"],
        "feature_csv_sha256": actual_feat_sha,
        "feature_rows": int(len(df)),
    }
    return df, provenance


def _classify_target_period(target_period: pd.Timestamp) -> str:
    if TRAIN_START <= target_period <= TRAIN_END:
        return "train"
    if VALIDATION_START <= target_period <= VALIDATION_END:
        return "validation"
    if TEST_START <= target_period <= TEST_END:
        return "test"
    if target_period >= FUTURE_START:
        return "future_unlabelled"
    raise ValueError(f"target_period outside defined chronological schedule: {target_period}")


def assign_chronological_splits(feature_df: pd.DataFrame) -> pd.DataFrame:
    """Assign deterministic chronological partitions by ``target_period`` without dropping rows.

    Validates key uniqueness, two-month reporting lag (``target_period == origin_period + 2m``),
    decision-date alignment (``decision_date == target_period - 1d``), partition
    disjointness, and explicit exclusion reasons for absent/unlabelled targets.
    """
    required = {
        "org_code",
        "origin_period",
        "decision_date",
        "target_period",
        "horizon_months",
        "is_eligible_origin",
        "target_observed",
        "is_future_forecast",
        "has_complete_core_features",
        "has_complete_all_features",
        TARGET_COLUMN,
    }
    missing = required - set(feature_df.columns)
    if missing:
        raise ValueError(f"Feature DataFrame missing required columns: {sorted(missing)}")

    df = feature_df.copy()
    for dcol in ("origin_period", "decision_date", "target_period"):
        df[dcol] = pd.to_datetime(df[dcol], errors="raise")

    if df.duplicated(["org_code", "origin_period"]).any():
        raise ValueError("Duplicate (org_code, origin_period) keys detected")
    if df.duplicated(["org_code", "target_period"]).any():
        raise ValueError("Duplicate (org_code, target_period) keys detected")
    if not (df["horizon_months"] == HORIZON_MONTHS).all():
        raise ValueError(f"All rows must obey horizon_months == {HORIZON_MONTHS}")

    # Verify strict two-month publication lag and prior-month-end decision date on every row.
    expected_targets = pd.DatetimeIndex(
        [p + pd.DateOffset(months=HORIZON_MONTHS) for p in df["origin_period"]]
    )
    expected_decisions = pd.DatetimeIndex([t - pd.DateOffset(days=1) for t in expected_targets])
    if not (df["target_period"].to_numpy() == expected_targets.to_numpy()).all():
        raise ValueError("One or more rows violate target_period == origin_period + 2 months")
    if not (df["decision_date"].to_numpy() == expected_decisions.to_numpy()).all():
        raise ValueError("One or more rows violate decision_date == target_period - 1 day")

    df["split"] = pd.Series(
        [_classify_target_period(t) for t in df["target_period"]],
        index=df.index,
        dtype="string",
    )

    # Confirm beyond-M06 rows match future_unlabelled exactly and carry no observed targets.
    is_future_part = df["split"] == "future_unlabelled"
    if not (is_future_part.to_numpy(dtype=bool) == df["is_future_forecast"].to_numpy(dtype=bool)).all():
        raise ValueError("future_unlabelled partition disagrees with is_future_forecast flag")
    if df.loc[is_future_part, "target_observed"].any():
        raise ValueError("future_unlabelled partition unexpectedly contains observed targets")
    if df.loc[~df["target_observed"], TARGET_COLUMN].notna().any():
        raise ValueError("Row with target_observed=False contains non-null target value")

    in_labelled_part = df["split"].isin(LABELLED_PARTITIONS)
    df["evaluation_eligible"] = (in_labelled_part & df["target_observed"]).astype(bool)

    exclusion = pd.Series(EXCLUSION_NONE, index=df.index, dtype="string")
    exclusion.loc[is_future_part] = EXCLUSION_FUTURE_UNLABELLED
    exclusion.loc[in_labelled_part & ~df["target_observed"]] = EXCLUSION_ABSENT_TARGET
    df["exclusion_reason"] = exclusion

    # Verify strict chronological non-overlap across partitions.
    prev_max: pd.Timestamp | None = None
    for part in PARTITION_ORDER:
        sub = df.loc[df["split"] == part, "target_period"]
        if sub.empty:
            continue
        cur_min, cur_max = sub.min(), sub.max()
        if prev_max is not None and cur_min <= prev_max:
            raise ValueError(f"Chronological overlap detected at partition {part!r}")
        prev_max = cur_max

    return df.sort_values(["target_period", "org_code"]).reset_index(drop=True)


def get_fixed_partitions(
    split_df: pd.DataFrame,
    *,
    evaluable_only: bool = True,
) -> dict[str, pd.DataFrame]:
    """Return fixed train, validation, test, and future_unlabelled DataFrames.

    When ``evaluable_only=True`` (default), ``train``, ``validation``, and
    ``test`` contain only rows with ``evaluation_eligible == True`` (observed
    targets); ``future_unlabelled`` always retains all beyond-M06 operational
    forecast rows (never included in labelled partitions).
    """
    if "split" not in split_df.columns or "evaluation_eligible" not in split_df.columns:
        split_df = assign_chronological_splits(split_df)

    out: dict[str, pd.DataFrame] = {}
    for part in LABELLED_PARTITIONS:
        mask = split_df["split"] == part
        if evaluable_only:
            mask = mask & split_df["evaluation_eligible"]
        out[part] = split_df.loc[mask].reset_index(drop=True)
    out["future_unlabelled"] = split_df.loc[split_df["split"] == "future_unlabelled"].reset_index(drop=True)
    return out


def get_expanding_window_split(
    split_df: pd.DataFrame,
    target_period: str | pd.Timestamp,
    *,
    complete_features_only: bool = False,
) -> dict[str, Any]:
    """Return publication-aware training and evaluation rows for a single target month ``T``.

    On forecast decision date ``d_T = T - 1 day``:
    - Latest published NHS reporting month is ``o = T - 2 months``.
    - Permissible historical training labels must already be published by ``d_T``:
      ``target_period <= o`` and ``evaluation_eligible == True``.
    - Target labels from ``T - 1`` (unpublished) and ``T`` (future) are strictly excluded.
    - All evaluation rows at ``T`` must have ``origin_period == o``.
    """
    if "split" not in split_df.columns or "evaluation_eligible" not in split_df.columns:
        split_df = assign_chronological_splits(split_df)

    T = pd.Timestamp(target_period)
    if not T.is_month_start:
        raise ValueError(f"target_period must be a month-start date; got {T}")

    latest_published = T - pd.DateOffset(months=HORIZON_MONTHS)
    unpublished_prev = T - pd.DateOffset(months=1)
    decision_date = T - pd.DateOffset(days=1)

    eval_all = split_df.loc[split_df["target_period"] == T].reset_index(drop=True)
    if eval_all.empty:
        raise ValueError(f"No forecast rows found for target_period={T.strftime('%Y-%m-%d')}")

    if not (eval_all["origin_period"] == latest_published).all():
        raise ValueError("Evaluation rows do not align with origin_period == T - 2")
    if not (eval_all["decision_date"] == decision_date).all():
        raise ValueError("Evaluation rows do not align with decision_date == T - 1 day")

    eval_evaluable = eval_all.loc[eval_all["evaluation_eligible"]].reset_index(drop=True)
    eval_excluded = eval_all.loc[~eval_all["evaluation_eligible"]].reset_index(drop=True)

    train_mask = (
        split_df["evaluation_eligible"]
        & (split_df["target_period"] <= latest_published)
    )
    if complete_features_only:
        train_mask = train_mask & split_df["has_complete_all_features"]

    train_df = split_df.loc[train_mask].reset_index(drop=True)

    # Strict anti-leakage assertions on every call.
    if not train_df.empty:
        if (train_df["target_period"] > latest_published).any():
            raise ValueError("Leakage violation: training row target_period exceeds o = T - 2")
        if (train_df["origin_period"] > latest_published - pd.DateOffset(months=HORIZON_MONTHS)).any():
            raise ValueError("Leakage violation: training row origin_period inconsistent with cutoff")
        if (train_df["target_period"] == unpublished_prev).any() or (train_df["target_period"] == T).any():
            raise ValueError("Leakage violation: unpublished T - 1 or target T label in training set")

    excluded_unpub_t_minus_1 = int(
        (split_df["evaluation_eligible"] & (split_df["target_period"] == unpublished_prev)).sum()
    )

    return {
        "target_period": T,
        "decision_date": decision_date,
        "latest_published_period": latest_published,
        "unpublished_prior_period": unpublished_prev,
        "partition": str(eval_all["split"].iloc[0]),
        "train_df": train_df,
        "eval_all_df": eval_all,
        "eval_evaluable_df": eval_evaluable,
        "eval_excluded_df": eval_excluded,
        "excluded_unpublished_t_minus_1_rows": excluded_unpub_t_minus_1,
    }


def iter_expanding_window_splits(
    split_df: pd.DataFrame,
    partition: str = "validation",
    *,
    complete_features_only: bool = False,
) -> Iterator[dict[str, Any]]:
    """Yield chronological publication-aware expanding-window splits for a partition."""
    if partition not in ("validation", "test"):
        raise ValueError(f"partition must be 'validation' or 'test'; got {partition!r}")
    if "split" not in split_df.columns:
        split_df = assign_chronological_splits(split_df)

    months = sorted(split_df.loc[split_df["split"] == partition, "target_period"].unique())
    for month in months:
        yield get_expanding_window_split(
            split_df,
            month,
            complete_features_only=complete_features_only,
        )


def summarise_splits(split_df: pd.DataFrame) -> dict[str, Any]:
    """Produce partition-level summaries and the full expanding-window schedule."""
    if "split" not in split_df.columns:
        split_df = assign_chronological_splits(split_df)

    partitions: dict[str, Any] = {}
    for part in PARTITION_ORDER:
        g = split_df.loc[split_df["split"] == part]
        ev = g.loc[g["evaluation_eligible"]]
        ex = g.loc[~g["evaluation_eligible"]]
        partitions[part] = {
            "target_start": g["target_period"].min().strftime("%Y-%m") if not g.empty else "",
            "target_end": g["target_period"].max().strftime("%Y-%m") if not g.empty else "",
            "target_months": int(g["target_period"].nunique()),
            "origin_start": g["origin_period"].min().strftime("%Y-%m") if not g.empty else "",
            "origin_end": g["origin_period"].max().strftime("%Y-%m") if not g.empty else "",
            "total_eligible_rows": int(len(g)),
            "evaluable_rows": int(len(ev)),
            "excluded_rows": int(len(ex)),
            "distinct_providers_eligible": int(g["org_code"].nunique()),
            "distinct_providers_evaluable": int(ev["org_code"].nunique()),
            "complete_core_features_evaluable": int(ev["has_complete_core_features"].sum()),
            "complete_all_features_evaluable": int(ev["has_complete_all_features"].sum()),
            "missing_origin_lag_12_rows": int(g["type1_origin_lag_12"].isna().sum()),
            "exclusion_reasons": ex["exclusion_reason"].value_counts().to_dict(),
        }

    schedule_rows: list[dict[str, Any]] = []
    for part in ("validation", "test"):
        for step in iter_expanding_window_splits(split_df, partition=part, complete_features_only=False):
            train_all = step["train_df"]
            train_comp = train_all.loc[train_all["has_complete_all_features"]]
            schedule_rows.append(
                {
                    "partition": part,
                    "decision_date": step["decision_date"].strftime("%Y-%m-%d"),
                    "latest_published_period": step["latest_published_period"].strftime("%Y-%m"),
                    "unpublished_prior_period": step["unpublished_prior_period"].strftime("%Y-%m"),
                    "target_period": step["target_period"].strftime("%Y-%m"),
                    "train_target_start": train_all["target_period"].min().strftime("%Y-%m"),
                    "train_target_end": train_all["target_period"].max().strftime("%Y-%m"),
                    "train_rows_all_evaluable": int(len(train_all)),
                    "train_rows_complete_features": int(len(train_comp)),
                    "train_distinct_providers": int(train_all["org_code"].nunique()),
                    "excluded_unpublished_t_minus_1_rows": step["excluded_unpublished_t_minus_1_rows"],
                    "eval_eligible_rows": int(len(step["eval_all_df"])),
                    "eval_evaluable_rows": int(len(step["eval_evaluable_df"])),
                    "eval_excluded_absent_rows": int(len(step["eval_excluded_df"])),
                    "eval_excluded_codes": ",".join(step["eval_excluded_df"]["org_code"].tolist()),
                }
            )

    labelled_total = sum(partitions[p]["evaluable_rows"] for p in LABELLED_PARTITIONS)
    absent_total = sum(partitions[p]["excluded_rows"] for p in LABELLED_PARTITIONS)

    return {
        "schema_version": "1.0",
        "boundaries": {
            "train": {"start": TRAIN_START.strftime("%Y-%m"), "end": TRAIN_END.strftime("%Y-%m")},
            "validation": {"start": VALIDATION_START.strftime("%Y-%m"), "end": VALIDATION_END.strftime("%Y-%m")},
            "test": {"start": TEST_START.strftime("%Y-%m"), "end": TEST_END.strftime("%Y-%m")},
            "future_unlabelled": {"start": FUTURE_START.strftime("%Y-%m")},
        },
        "totals": {
            "total_feature_rows": int(len(split_df)),
            "total_labelled_evaluable_rows": int(labelled_total),
            "total_absent_in_range_rows": int(absent_total),
            "total_future_unlabelled_rows": int(partitions["future_unlabelled"]["total_eligible_rows"]),
            "core_features": len(CORE_FEATURE_COLUMNS),
            "all_features": len(ALL_FEATURE_COLUMNS),
        },
        "partitions": partitions,
        "expanding_window_schedule": schedule_rows,
    }


def export_split_summary(
    repo: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Load verified features, validate splits, and save summary artifacts to an ignored directory."""
    repo = Path(repo).resolve()
    feat_df, provenance = load_verified_features(repo)
    split_df = assign_chronological_splits(feat_df)
    summary = summarise_splits(split_df)

    dest = (repo / "outputs/splits") if output_dir is None else Path(output_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    summary_payload = {
        "provenance": provenance,
        **summary,
    }
    summary_path = dest / "split_summary.json"
    schedule_path = dest / "expanding_window_schedule.csv"

    summary_path.write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(summary["expanding_window_schedule"]).to_csv(schedule_path, index=False)

    return {
        "split_df": split_df,
        "summary": summary_payload,
        "summary_path": str(summary_path),
        "schedule_path": str(schedule_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    res = export_split_summary(args.repo, output_dir=args.output_dir)
    print(json.dumps(res["summary"], indent=2))


if __name__ == "__main__":
    main()
