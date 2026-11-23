"""Time-aware Type 1 provider cohort selection and continuity review.

Loads the verified M06 provider calendar referenced in
``docs/model_input_manifest.json``, independently verifies strictly causal
origin-level eligibility rules without altering preprocessing outputs, and
produces reproducible provisional and sensitivity cohort summaries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.data_preprocessing import MEASURE_NAMES, TARGET
from src.data.longitudinal_preparation import STATUSES

MANIFEST_REL_PATH = Path("docs/model_input_manifest.json")
ACCEPTED_MANIFEST_STATUSES = {"VERIFIED_REBUILT_INPUT", "VERIFIED_ACCEPTED_INPUT"}
REQUIRED_COHORT_COLUMNS = (
    "period",
    "org_code",
    "parent_org",
    "org_name",
    TARGET,
    "is_observed",
    "observation_state",
    "observed_last_n_months",
    "positive_last_n_months",
    "history_ready",
    "type1_candidate",
    "candidate_status",
    "history_window_months",
)

# Documented NHS provider continuity classifications grounded in public NHS
# merger records and observed M06 attendance trajectories (Jan 2022 - Sep 2026).
# All flagged cases remain in the main provisional cohort; only material
# Type 1 continuity breaks are excluded in the retrospective sensitivity cohort.
DOCUMENTED_CONTINUITY_EVENTS: dict[str, dict[str, Any]] = {
    # Verified acute-to-acute Type 1 NHS trust mergers (5 mergers; 10 codes, 9 eligible)
    "RBZ": {
        "continuity_category": "acute_merger_dissolved",
        "effective_month": "2022-04",
        "related_org_code": "RH8",
        "material_continuity_concern": True,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "Northern Devon Healthcare NHS Trust merged into Royal Devon and Exeter "
            "NHS FT (RH8) on 2022-04-01; RBZ ceased reporting after 2022-03 (0 eligible origins)."
        ),
    },
    "RH8": {
        "continuity_category": "acute_merger_absorber",
        "effective_month": "2022-04",
        "related_org_code": "RBZ",
        "material_continuity_concern": True,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "Acquired RBZ on 2022-04-01 and renamed Royal Devon University Healthcare "
            "NHS FT; 3-month Type 1 mean rose +72.0% (6,796 -> 11,686)."
        ),
    },
    "RA4": {
        "continuity_category": "acute_merger_dissolved",
        "effective_month": "2023-04",
        "related_org_code": "RH5",
        "material_continuity_concern": True,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "Yeovil District Hospital NHS FT merged into Somerset NHS FT (RH5) on "
            "2023-04-01; RA4 ceased reporting after 2023-03 (4 eligible origins)."
        ),
    },
    "RH5": {
        "continuity_category": "acute_merger_absorber",
        "effective_month": "2023-04",
        "related_org_code": "RA4",
        "material_continuity_concern": True,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "Acquired RA4 on 2023-04-01 with no trust name change; 3-month Type 1 "
            "mean rose +98.9% (6,247 -> 12,424)."
        ),
    },
    "RVY": {
        "continuity_category": "acute_merger_dissolved",
        "effective_month": "2023-07",
        "related_org_code": "RBN",
        "material_continuity_concern": True,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "Southport and Ormskirk Hospital NHS Trust acquired by RBN on 2023-07-01; "
            "RVY ceased reporting after 2023-06 (7 eligible origins)."
        ),
    },
    "RBN": {
        "continuity_category": "acute_merger_absorber",
        "effective_month": "2023-07",
        "related_org_code": "RVY",
        "material_continuity_concern": True,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "Acquired RVY on 2023-07-01 and renamed Mersey and West Lancashire Teaching "
            "Hospitals NHS Trust; 3-month Type 1 mean rose +71.9% (9,812 -> 16,868)."
        ),
    },
    "RAP": {
        "continuity_category": "acute_merger_dissolved",
        "effective_month": "2025-01",
        "related_org_code": "RAL",
        "material_continuity_concern": True,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "North Middlesex University Hospital NHS Trust merged into Royal Free London "
            "NHS FT (RAL) on 2025-01-01; RAP ceased reporting after 2024-12 (25 eligible origins)."
        ),
    },
    "RAL": {
        "continuity_category": "acute_merger_absorber",
        "effective_month": "2025-01",
        "related_org_code": "RAP",
        "material_continuity_concern": True,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "Acquired RAP on 2025-01-01 with no trust name change; 3-month Type 1 "
            "mean rose +37.6% (17,778 -> 24,456)."
        ),
    },
    "RVJ": {
        "continuity_category": "acute_merger_dissolved",
        "effective_month": "2026-07",
        "related_org_code": "RA7",
        "material_continuity_concern": True,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "North Bristol NHS Trust merged with RA7 on 2026-07-01 to form Bristol NHS FT; "
            "RVJ ceased reporting after 2026-06 (43 eligible origins)."
        ),
    },
    "RA7": {
        "continuity_category": "acute_merger_absorber",
        "effective_month": "2026-07",
        "related_org_code": "RVJ",
        "material_continuity_concern": True,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "Merged with RVJ on 2026-07-01 and renamed Bristol NHS Foundation Trust; "
            "3-month Type 1 mean rose +59.6% (16,130 -> 25,740)."
        ),
    },
    # Verified acute + community mergers (community partner had zero Type 1 activity)
    "RAX": {
        "continuity_category": "community_merger_no_type1_break",
        "effective_month": "2024-11",
        "related_org_code": "RY9",
        "material_continuity_concern": False,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "Merged with Hounslow and Richmond Community Healthcare (RY9, zero Type 1) "
            "on 2024-11-01 as Kingston and Richmond NHS FT; Type 1 volume remained stable (+7.2%)."
        ),
    },
    "RWW": {
        "continuity_category": "community_merger_no_type1_break",
        "effective_month": "2026-04",
        "related_org_code": "RY2",
        "material_continuity_concern": False,
        "review_status": "verified_organisational_change",
        "evidence_note": (
            "Merged with Bridgewater Community Healthcare (RY2, zero Type 1) on 2026-04-01 "
            "as North Cheshire and Mersey NHS FT; Type 1 stable (+6.0%), Other A&E rose +128.6%."
        ),
    },
    # Unresolved material Type 1 <-> Other A&E step changes (total A&E roughly stable)
    "RXN": {
        "continuity_category": "unresolved_type1_step_change",
        "effective_month": "2022-08",
        "related_org_code": "",
        "material_continuity_concern": True,
        "review_status": "review_required",
        "evidence_note": (
            "Persistent Type 1 step-up (+73.5%, 6,623 -> 11,493) paired with Other A&E "
            "drop (8,852 -> 3,669) while total A&E stayed flat (-2.0%); likely Type 1/UTC reclassification."
        ),
    },
    "RVV": {
        "continuity_category": "unresolved_type1_step_change",
        "effective_month": "2023-02",
        "related_org_code": "",
        "material_continuity_concern": True,
        "review_status": "review_required",
        "evidence_note": (
            "Persistent Type 1 step-down (-36.8%, 18,118 -> 11,453) paired with Other A&E "
            "rise (5,648 -> 11,329) while total A&E stayed flat (-4.1%); likely Type 1/UTC reclassification."
        ),
    },
    "RTR": {
        "continuity_category": "unresolved_type1_step_change",
        "effective_month": "2024-04",
        "related_org_code": "",
        "material_continuity_concern": True,
        "review_status": "review_required",
        "evidence_note": (
            "Persistent Type 1 step-down (-24.2%, 10,261 -> 7,774) paired with Other A&E "
            "rise (4,836 -> 9,249); unverified service streaming or reporting shift."
        ),
    },
    "RJL": {
        "continuity_category": "unresolved_type1_step_change",
        "effective_month": "2024-05",
        "related_org_code": "",
        "material_continuity_concern": True,
        "review_status": "review_required",
        "evidence_note": (
            "Persistent Type 1 step-down (-40.5%, 15,116 -> 8,994) paired with Other A&E "
            "rise (163 -> 6,729) while total A&E stayed flat (+2.9%); likely Type 1/UTC reclassification."
        ),
    },
    "RWD": {
        "continuity_category": "unresolved_type1_step_change",
        "effective_month": "2025-01",
        "related_org_code": "",
        "material_continuity_concern": True,
        "review_status": "review_required",
        "evidence_note": (
            "Teaching-trust rename in 2024-11 followed by persistent 2025-01 Type 1 step-up "
            "(+44.4%, 10,825 -> 15,629) paired with Other A&E drop (9,843 -> 3,610); review required."
        ),
    },
    "RTK": {
        "continuity_category": "unresolved_type1_step_change",
        "effective_month": "2025-04",
        "related_org_code": "",
        "material_continuity_concern": True,
        "review_status": "review_required",
        "evidence_note": (
            "Persistent Type 1 step-down (-29.5%, 10,014 -> 7,061) paired with new Other A&E "
            "reporting (0 -> 4,817); likely co-located UTC/Type 3 streaming change."
        ),
    },
}


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_accepted_m06(
    repo: Path,
    manifest_rel_path: Path = MANIFEST_REL_PATH,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load and verify the accepted M06 provider calendar from the manifest."""
    repo = Path(repo).resolve()
    manifest_path = repo / manifest_rel_path
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Model input manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") not in ACCEPTED_MANIFEST_STATUSES:
        raise ValueError(f"Model input manifest is not verified: status={manifest.get('status')!r}")

    dataset_info = manifest.get("dataset", {})
    rel_csv = dataset_info.get("repository_relative_path")
    expected_sha = dataset_info.get("sha256")
    if not rel_csv or not expected_sha:
        raise ValueError("Model input manifest is missing dataset path or sha256")

    csv_path = (repo / rel_csv).resolve()
    if not csv_path.is_file():
        raise FileNotFoundError(f"Accepted M06 dataset missing on disk: {csv_path}")

    actual_sha = sha256_file(csv_path)
    if actual_sha != expected_sha:
        raise ValueError(
            f"Accepted M06 dataset SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"
        )

    string_cols = {
        "org_code": "string",
        "source_period": "string",
        "parent_org": "string",
        "org_name": "string",
        "source_month": "string",
        "source_file": "string",
        "source_sha256": "string",
        "source_record_number": "string",
        "observation_state": "string",
        "candidate_status": "string",
    }
    df = pd.read_csv(csv_path, dtype=string_cols)
    missing_cols = [c for c in REQUIRED_COHORT_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"M06 calendar is missing required columns: {missing_cols}")

    df["period"] = pd.to_datetime(df["period"], format="%Y-%m-%d", errors="raise")
    for col in MEASURE_NAMES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="raise").astype("Int64")

    for bcol in ("is_observed", "history_ready", "type1_candidate"):
        df[bcol] = df[bcol].astype(bool)

    for icol in ("observed_last_n_months", "positive_last_n_months", "history_window_months"):
        df[icol] = df[icol].astype("int64")

    if len(df) != dataset_info.get("counts", {}).get("rows"):
        raise ValueError("Loaded M06 row count does not match manifest")
    if df["org_code"].nunique() != dataset_info.get("counts", {}).get("provider_codes"):
        raise ValueError("Loaded M06 provider count does not match manifest")

    return df, manifest


def evaluate_time_aware_eligibility(
    calendar_df: pd.DataFrame,
    window: int = 12,
    verify_existing: bool = True,
) -> pd.DataFrame:
    """Compute strictly causal origin-level Type 1 eligibility on a monthly calendar.

    Eligibility at forecast origin month ``t`` depends exclusively on records with
    ``period <= t`` for the same ``org_code``:
    - ``is_observed`` is True at ``t`` (missing records remain missing/null).
    - ``window`` consecutive calendar months ending at ``t`` are all observed.
    - At least one observed month in that trailing window has ``type1_attendances > 0``.
    - Genuine reported zeros remain ``0`` and do not break ``history_ready``.
    """
    if not isinstance(window, int) or window < 1:
        raise ValueError("History window must be a positive integer")

    required = {"period", "org_code", TARGET, "is_observed"}
    missing = required - set(calendar_df.columns)
    if missing:
        raise ValueError(f"Calendar frame missing required columns: {sorted(missing)}")

    df = calendar_df.copy()
    df["period"] = pd.to_datetime(df["period"], errors="raise")
    if df["period"].isna().any() or not df["period"].dt.is_month_start.all():
        raise ValueError("All periods must be valid month-start dates")
    if df["org_code"].isna().any() or df["org_code"].astype(str).str.strip().eq("").any():
        raise ValueError("Missing or blank org_code found")
    if df["org_code"].astype(str).str.upper().eq("TOTAL").any():
        raise ValueError("National TOTAL rows must be excluded from provider cohort")
    if df.duplicated(["org_code", "period"]).any():
        raise ValueError("Duplicate (org_code, period) keys detected")

    df["is_observed"] = df["is_observed"].astype(bool)
    df[TARGET] = pd.to_numeric(df[TARGET], errors="raise").astype("Int64")

    obs_mask = df["is_observed"]
    abs_mask = ~obs_mask
    if df.loc[obs_mask, TARGET].isna().any():
        raise ValueError("Observed provider-month record has missing Type 1 count")
    if df.loc[abs_mask, TARGET].notna().any():
        raise ValueError("Absent calendar row contains non-null Type 1 count")

    present_measures = [c for c in MEASURE_NAMES if c in df.columns]
    for col in present_measures:
        vals = pd.to_numeric(df[col], errors="raise").astype("Int64")
        if vals.loc[abs_mask].notna().any():
            raise ValueError(f"Absent calendar row contains non-null count in {col}")
        if vals.loc[obs_mask].isna().any():
            raise ValueError(f"Observed row contains null count in {col}")
        if (vals.loc[obs_mask] < 0).any():
            raise ValueError(f"Negative reported count found in {col}")

    df = df.sort_values(["org_code", "period"]).reset_index(drop=True)
    parts: list[pd.DataFrame] = []
    for _, grp in df.groupby("org_code", sort=True):
        g = grp.sort_values("period").copy()
        expected_cal = pd.date_range(g["period"].min(), g["period"].max(), freq="MS")
        if len(g) != len(expected_cal) or not (g["period"].to_numpy() == expected_cal.to_numpy()).all():
            raise ValueError(
                f"Non-contiguous monthly calendar for org_code={g['org_code'].iloc[0]!r}; "
                "all absent months after first observation must be explicitly represented."
            )

        observed = g["is_observed"]
        positive = observed & g[TARGET].gt(0).fillna(False)

        obs_state = pd.Series("Absent record", index=g.index, dtype="string")
        obs_state.loc[observed & ~positive] = "Reported zero"
        obs_state.loc[observed & positive] = "Reported positive"

        # Trailing calendar window [t - window + 1, t] uses only current and past rows.
        obs_last_n = observed.astype("int64").rolling(window, min_periods=1).sum().astype("int64")
        pos_last_n = positive.astype("int64").rolling(window, min_periods=1).sum().astype("int64")
        history_ready = obs_last_n.eq(window)
        type1_candidate = observed & history_ready & pos_last_n.gt(0)

        cand_status = pd.Series(STATUSES[2], index=g.index, dtype="string")
        cand_status.loc[~observed] = STATUSES[3]
        cand_status.loc[observed & history_ready & pos_last_n.eq(0)] = STATUSES[1]
        cand_status.loc[type1_candidate] = STATUSES[0]

        if verify_existing and "type1_candidate" in g.columns:
            checks = {
                "observation_state": obs_state,
                "observed_last_n_months": obs_last_n,
                "positive_last_n_months": pos_last_n,
                "history_ready": history_ready,
                "type1_candidate": type1_candidate,
                "candidate_status": cand_status,
            }
            for col_name, computed in checks.items():
                if col_name in g.columns:
                    if not (g[col_name].astype(str).to_numpy() == computed.astype(str).to_numpy()).all():
                        raise ValueError(
                            f"Recomputed {col_name} disagrees with M06 column for org_code={g['org_code'].iloc[0]!r}"
                        )

        g["observation_state"] = obs_state
        g["observed_last_n_months"] = obs_last_n
        g["positive_last_n_months"] = pos_last_n
        g["history_ready"] = history_ready
        g["type1_candidate"] = type1_candidate
        g["candidate_status"] = cand_status
        g["history_window_months"] = int(window)
        parts.append(g)

    out = pd.concat(parts, ignore_index=True).sort_values(["period", "org_code"]).reset_index(drop=True)
    if out.duplicated(["org_code", "period"]).any():
        raise ValueError("Duplicate (org_code, period) keys produced")
    return out


def build_continuity_review(evaluated_df: pd.DataFrame) -> pd.DataFrame:
    """Build a provider-level continuity and cohort review table across all providers."""
    df = evaluated_df.sort_values(["org_code", "period"]).copy()
    records: list[dict[str, Any]] = []

    for code, g in df.groupby("org_code", sort=True):
        obs = g.loc[g["is_observed"]].sort_values("period")
        first_obs = obs["period"].min()
        last_obs = obs["period"].max()
        span_months = (last_obs.year - first_obs.year) * 12 + (last_obs.month - first_obs.month) + 1
        internal_gaps = int(span_months - len(obs))
        absent_after = int(len(g) - span_months)

        names = sorted(obs["org_name"].dropna().astype(str).unique().tolist())
        parents = sorted(obs["parent_org"].dropna().astype(str).unique().tolist())
        elig_rows = g.loc[g["type1_candidate"]]
        elig_count = int(len(elig_rows))
        elig_zero_count = int((elig_rows[TARGET] == 0).sum()) if elig_count else 0

        zero_obs = int((obs[TARGET] == 0).sum())
        pos_obs = int((obs[TARGET] > 0).sum())

        # Detect largest persistent 3-month step change in observed Type 1 counts.
        max_step_month = ""
        max_step_abs = 0
        max_step_pct = 0.0
        if pos_obs >= 6:
            vals = obs[TARGET].astype(float).reset_index(drop=True)
            pers = obs["period"].dt.strftime("%Y-%m").reset_index(drop=True)
            for i in range(1, len(vals)):
                prev_v, curr_v = vals.iloc[i - 1], vals.iloc[i]
                diff = curr_v - prev_v
                rel = diff / prev_v if prev_v > 0 else 0.0
                if abs(diff) >= 1500 and abs(rel) >= 0.25:
                    pre3 = vals.iloc[max(0, i - 3) : i].mean()
                    post3 = vals.iloc[i : min(len(vals), i + 3)].mean()
                    step_pct = ((post3 - pre3) / pre3 * 100.0) if pre3 > 0 else 0.0
                    if abs(step_pct) >= 24.0 and abs(diff) > abs(max_step_abs):
                        max_step_month = str(pers.iloc[i])
                        max_step_abs = int(round(diff))
                        max_step_pct = round(float(step_pct), 1)

        doc = DOCUMENTED_CONTINUITY_EVENTS.get(str(code))
        if doc is not None:
            category = doc["continuity_category"]
            effective_month = doc["effective_month"]
            related_code = doc["related_org_code"]
            material_concern = bool(doc["material_continuity_concern"])
            review_status = doc["review_status"]
            evidence_note = doc["evidence_note"]
        elif internal_gaps > 0:
            category = "internal_gap_non_type1" if pos_obs == 0 else "internal_gap_type1"
            gap_months = g.loc[~g["is_observed"] & g["period"].le(last_obs), "period"].dt.strftime("%Y-%m").tolist()
            effective_month = gap_months[0] if gap_months else ""
            related_code = ""
            material_concern = pos_obs > 0
            review_status = "review_required" if pos_obs > 0 else "non_type1_monitored"
            evidence_note = (
                f"{internal_gaps} internal missing month(s) ({', '.join(gap_months[:4])}"
                f"{'...' if len(gap_months) > 4 else ''}); zero positive Type 1 activity."
                if pos_obs == 0
                else f"{internal_gaps} internal missing month(s) affecting Type 1 history."
            )
        elif len(names) > 1:
            # Find first month where name changed
            obs_names = obs["org_name"].astype(str).tolist()
            obs_months = obs["period"].dt.strftime("%Y-%m").tolist()
            change_m = next((obs_months[i] for i in range(1, len(obs_names)) if obs_names[i] != obs_names[i - 1]), "")
            category = "name_variant_only" if pos_obs > 0 else "non_type1_name_variant"
            effective_month = change_m
            related_code = ""
            material_concern = False
            review_status = "simple_name_variation" if pos_obs > 0 else "non_type1_monitored"
            evidence_note = (
                "Recorded trust name/title update with no associated acute merger or material Type 1 step break."
                if pos_obs > 0
                else "Recorded name variation in non-Type-1 provider (0 eligible origins)."
            )
        else:
            category = "no_flag"
            effective_month = ""
            related_code = ""
            material_concern = False
            review_status = "clear" if elig_count > 0 else "non_type1_excluded"
            evidence_note = ""

        in_provisional = elig_count > 0
        in_sensitivity = in_provisional and not material_concern

        records.append(
            {
                "org_code": str(code),
                "first_observed_month": first_obs.strftime("%Y-%m"),
                "last_observed_month": last_obs.strftime("%Y-%m"),
                "observed_months": int(len(obs)),
                "missing_within_observed_span": internal_gaps,
                "absent_after_last_observation": absent_after,
                "zero_type1_observations": zero_obs,
                "positive_type1_observations": pos_obs,
                "distinct_recorded_names": len(names),
                "distinct_recorded_parent_groups": len(parents),
                "provisional_eligible_origins": elig_count,
                "eligible_zero_origins": elig_zero_count,
                "first_eligible_month": elig_rows["period"].min().strftime("%Y-%m") if elig_count else "",
                "last_eligible_month": elig_rows["period"].max().strftime("%Y-%m") if elig_count else "",
                "in_provisional_cohort": in_provisional,
                "in_sensitivity_cohort": in_sensitivity,
                "material_continuity_concern": material_concern,
                "continuity_category": category,
                "review_status": review_status,
                "event_month": effective_month,
                "related_org_code": related_code,
                "flagged_step_month": max_step_month,
                "flagged_step_abs": max_step_abs,
                "flagged_step_3m_pct": max_step_pct,
                "recorded_names": " | ".join(names),
                "recorded_parent_groups": " | ".join(parents),
                "evidence_note": evidence_note,
            }
        )

    return pd.DataFrame(records).sort_values("org_code").reset_index(drop=True)


def build_cohorts(
    calendar_df: pd.DataFrame,
    window: int = 12,
    verify_existing: bool = True,
) -> dict[str, pd.DataFrame]:
    """Produce provisional and sensitivity cohorts plus monthly/status/continuity summaries."""
    evaluated = evaluate_time_aware_eligibility(
        calendar_df,
        window=window,
        verify_existing=verify_existing,
    )
    continuity = build_continuity_review(evaluated)

    flagged_codes = set(
        continuity.loc[continuity["material_continuity_concern"], "org_code"].tolist()
    )
    cohort_calendar = evaluated.copy()
    cohort_calendar["provisional_eligible"] = cohort_calendar["type1_candidate"]
    cohort_calendar["material_continuity_concern"] = cohort_calendar["org_code"].isin(flagged_codes)
    cohort_calendar["sensitivity_eligible"] = (
        cohort_calendar["provisional_eligible"] & ~cohort_calendar["material_continuity_concern"]
    )

    monthly = (
        cohort_calendar.groupby("period", sort=True)
        .agg(
            calendar_rows=("org_code", "size"),
            observed_rows=("is_observed", "sum"),
            candidate_rows=("provisional_eligible", "sum"),
            sensitivity_candidate_rows=("sensitivity_eligible", "sum"),
        )
        .reset_index()
    )
    monthly["absent_rows"] = monthly["calendar_rows"] - monthly["observed_rows"]
    status_pivot = (
        cohort_calendar.groupby(["period", "candidate_status"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=STATUSES, fill_value=0)
        .reset_index()
    )
    monthly = monthly.merge(status_pivot, on="period", validate="one_to_one")
    monthly = monthly[
        [
            "period",
            "calendar_rows",
            "observed_rows",
            "candidate_rows",
            "sensitivity_candidate_rows",
            "absent_rows",
            *STATUSES,
        ]
    ]

    status_summary = (
        cohort_calendar.groupby("candidate_status", sort=False)
        .agg(
            provider_month_rows=("org_code", "size"),
            distinct_providers=("org_code", "nunique"),
        )
        .reindex(STATUSES, fill_value=0)
        .reset_index()
    )

    return {
        "cohort_calendar": cohort_calendar,
        "provisional_cohort": cohort_calendar.loc[cohort_calendar["provisional_eligible"]].reset_index(drop=True),
        "sensitivity_cohort": cohort_calendar.loc[cohort_calendar["sensitivity_eligible"]].reset_index(drop=True),
        "monthly_summary": monthly,
        "status_summary": status_summary,
        "continuity_review": continuity,
    }


def compare_with_m05(repo: Path, monthly_summary: pd.DataFrame, continuity_review: pd.DataFrame) -> dict[str, Any]:
    """Compare computed cohort counts against archived M05 evidence reports."""
    m05_root = Path(repo).resolve() / "docs/evidence/M05_Longitudinal_Preparation"
    runs = sorted(p for p in m05_root.iterdir() if p.is_dir())
    if not runs:
        raise FileNotFoundError(f"No M05 evidence runs found in {m05_root}")
    m05_reports = runs[-1] / "reports"

    m05_monthly = pd.read_csv(m05_reports / "m05_monthly_eligibility.csv")
    m05_monthly["period"] = pd.to_datetime(m05_monthly["period"], format="%Y-%m-%d")
    compare_cols = ["period", "calendar_rows", "observed_rows", "candidate_rows", "absent_rows", *STATUSES]
    monthly_match = monthly_summary[compare_cols].reset_index(drop=True).equals(
        m05_monthly[compare_cols].reset_index(drop=True)
    )

    m05_cont = pd.read_csv(m05_reports / "m05_provider_continuity.csv")
    cont_cols = [
        "org_code",
        "first_observed_month",
        "last_observed_month",
        "observed_months",
        "missing_within_observed_span",
        "absent_after_last_observation",
        "zero_type1_observations",
        "positive_type1_observations",
        "distinct_recorded_names",
        "distinct_recorded_parent_groups",
    ]
    continuity_match = (
        continuity_review[cont_cols].sort_values("org_code").reset_index(drop=True).equals(
            m05_cont[cont_cols].sort_values("org_code").reset_index(drop=True)
        )
    )
    return {
        "m05_run_id": runs[-1].name,
        "monthly_eligibility_exact_match": bool(monthly_match),
        "provider_continuity_exact_match": bool(continuity_match),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--window", type=int, default=12)
    parser.add_argument(
        "--export-continuity-csv",
        type=Path,
        default=None,
        help="Optional path to write the provider continuity review CSV.",
    )
    args = parser.parse_args()

    panel, manifest = load_accepted_m06(args.repo)
    results = build_cohorts(panel, window=args.window, verify_existing=True)
    m05_check = compare_with_m05(args.repo, results["monthly_summary"], results["continuity_review"])

    if args.export_continuity_csv is not None:
        out_path = args.export_continuity_csv
        out_path.parent.mkdir(parents=True, exist_ok=True)
        results["continuity_review"].to_csv(out_path, index=False)

    prov = results["provisional_cohort"]
    sens = results["sensitivity_cohort"]
    summary = {
        "manifest_status": manifest["status"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "calendar_rows": int(len(results["cohort_calendar"])),
        "provisional_eligible_origins": int(len(prov)),
        "provisional_distinct_providers": int(prov["org_code"].nunique()),
        "sensitivity_eligible_origins": int(len(sens)),
        "sensitivity_distinct_providers": int(sens["org_code"].nunique()),
        "status_counts": results["status_summary"].to_dict(orient="records"),
        "m05_comparison": m05_check,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
