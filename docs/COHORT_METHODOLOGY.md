# Provider Cohort Selection Methodology

## 1. Purpose and Dataset Reference

This document defines the reproducible, time-aware provider cohort selection for next-month Type 1 A&E attendance forecasting (`type1_attendances`). All cohort rules are derived strictly from the accepted M06 provider calendar recorded in [docs/model_input_manifest.json](model_input_manifest.json), without modifying earlierpreprocessing code (`src/data/longitudinal_preparation.py`, `src/data/dataset_finalisation.py`) or raw/processed datasets.

- **Accepted input dataset:** `.work/rebuild/data/processed/m06/20261121T204848Z_03520dac/ae_provider_calendar_final.csv`
- **Dataset provenance:** Isolated rebuild (`20261121T204848Z_03520dac`), exact CSV SHA-256 match with archived M06 run `20261118T153942Z_fbc5f80f`
- **CSV SHA-256:** `16500cdcd05cb1cd4cac4e8b6b973c5586770696c2cf115f5157b9051a146aef`
- **Schema version:** `1.0` (`12,263` calendar rows, `35` columns, `223` distinct provider codes, `57` reporting months from `2022-01` to `2026-09`)
- **Cohort implementation:** [src/data/cohort_selection.py](../src/data/cohort_selection.py)
- **Automated verification:** [tests/test_cohort_selection.py](../tests/test_cohort_selection.py)

---

## 2. Existing M05/M06 Calendar and Eligibility Rules

In `src/data/longitudinal_preparation.py` (`prepare_panel`), each provider enters the calendar in its first observed month and receives one row per calendar month through the end of the collection (`2026-09`). No counts or organisation attributes are imputed or forward-filled.

For each provider (`org_code`) and forecast origin month $t$, with configured window $n = 12$:

| Field | Definition (strictly using observations $\le t$) |
| --- | --- |
| `is_observed` | `True` if a published NHS provider record exists for (`org_code`, $t$); `False` for an absent calendar placeholder row. |
| `observation_state` | `"Absent record"` if `is_observed == False`; `"Reported zero"` if `is_observed == True` and `type1_attendances == 0`; `"Reported positive"` if `is_observed == True` and `type1_attendances > 0`. |
| `observed_last_n_months` | Rolling sum of `is_observed` over the trailing 12 calendar months $[t - 11, t]$. |
| `positive_last_n_months` | Rolling sum of `(is_observed & (type1_attendances > 0))` over $[t - 11, t]$. |
| `history_ready` | `observed_last_n_months == 12` (12 consecutive calendar months observed through $t$). |
| `type1_candidate` | `is_observed & history_ready & (positive_last_n_months > 0)`. |
| `candidate_status` | Mutually exclusive partition: `"Candidate"` if `type1_candidate`; `"No recent positive activity"` if observed, `history_ready`, and `positive_last_n_months == 0`; `"Insufficient consecutive history"` if observed and `not history_ready`; `"No reported record"` if `not is_observed`. |

---

## 3. Main Provisional Cohort Definition

The **main provisional cohort** adopts the time-aware `type1_candidate` rule directly at each forecast origin month $t$:

1. The provider has a published observation at origin month $t$ (`is_observed == True`).
2. The provider has 12 consecutive observed calendar months ending at $t$ (`history_ready == True`), supporting seasonal lag features and seasonal-naive benchmarking.
3. The provider has at least one positive `type1_attendances` count within those 12 months (`positive_last_n_months > 0`), serving as an activity-based proxy for Type 1 service operation without inspecting future periods.
4. Eligibility is computed strictly causally using only data at or before $t$. September 2026 eligibility is **never** projected backward to earlier years.
5. Genuine reported zero `type1_attendances` at origin $t$ are **retained** whenever the provider otherwise satisfies conditions (1)–(3). (In the verified Jan 2022 – Sep 2026 dataset, `0` eligible origins actually had a zero count at origin $t$, though the rule and tests explicitly preserve them.)

### Missing-Data and Zero-Value Guarantees

- **Missing reports remain missing:** All `871` absent calendar rows retain `NULL` across all 18 measures and empty source provenance (`observation_state == "Absent record"`).
- **Genuine zeros remain zero:** All `4,426` reported zero Type 1 rows retain `0` (`observation_state == "Reported zero"`).
- **Internal gaps invalidate history:** Any missing calendar month resets `observed_last_n_months < 12` for the subsequent 11 months, forcing `history_ready == False` until 12 uninterrupted monthly observations are re-established.
- **No future leakage:** Adding, altering, or truncating records after month $t$ leaves eligibility at all months $\le t$ unchanged.

---

## 4. Cohort Counts and Comparison with Preproccessing M05 Evidence

Recomputing eligibility from the accepted M06 calendar matches Preproccessing archived M05 evidence (`20261117T234951Z_969acc23`, `m05_monthly_eligibility.csv` and `m05_provider_continuity.csv`) with **exact parity across all 57 months and 223 providers**.

### Overall Status Partition (`12,263` Calendar Rows, `223` Providers)

| `candidate_status` | Provider-Month Rows | Distinct Providers |
| --- | ---: | ---: |
| `Candidate` (Main provisional cohort) | 5,599 | 124 |
| `No recent positive activity` | 3,313 | 90 |
| `Insufficient consecutive history` | 2,480 | 223 |
| `No reported record` | 871 | 43 |
| **Total** | **12,263** | **223** |

### Monthly Eligibility Trend (`2022-01` to `2026-09`)

| Period Window | Months | Provisional Eligible / Month | Sensitivity Eligible / Month | Explanation of Step Changes |
| --- | ---: | ---: | ---: | --- |
| `2022-01` – `2022-11` | 11 | 0 | 0 | 12-month history burn-in (`RBZ` exited after `2022-03`, never reaching 12 months) |
| `2022-12` – `2023-03` | 4 | 124 | 109 | First eligible cohort (`124` providers) |
| `2023-04` – `2023-06` | 3 | 123 | 109 | `RA4` (Yeovil) exited after merging into `RH5` (Somerset) |
| `2023-07` – `2024-12` | 18 | 122 | 109 | `RVY` (Southport & Ormskirk) exited after merging into `RBN` (Mersey & West Lancs) |
| `2025-01` – `2026-06` | 18 | 121 | 109 | `RAP` (North Middlesex) exited after merging into `RAL` (Royal Free London) |
| `2026-07` – `2026-09` | 3 | 120 | 109 | `RVJ` (North Bristol) exited after merging into `RA7` (Bristol NHS FT) |
| **Total Eligible Origins** | **46 active** | **5,599** | **5,014** | **124 provisional vs. 109 sensitivity providers** |

---

## 5. Continuity Flags and Sensitivity Cohort

Detailed provider-level findings are documented in [docs/provider_continuity_review.md](provider_continuity_review.md) and [docs/provider_continuity_review.csv](provider_continuity_review.csv). No providers are silently merged, renamed, or deleted from the main provisional cohort.

To support robustness testing during model evaluation, `src/data/cohort_selection.py` defines a **retrospective sensitivity cohort** (`sensitivity_eligible`) alongside the preserved main provisional cohort (`provisional_eligible`):

- **Excluded from sensitivity cohort only (`15` eligible providers, `585` origins — 10.4% of provisional origins):**
  - **9 acute-to-acute Type 1 merger providers (`309` origins):** 4 dissolved trusts (`RA4`, `RVY`, `RAP`, `RVJ`) and 5 absorbing trusts (`RH8`, `RH5`, `RBN`, `RAL`, `RA7`) whose Type 1 counts undergo documented merger step-changes (`+37.6%` to `+98.9%`).
  - **6 unresolved Type 1 / Other A&E step-change providers (`276` origins):** `RXN`, `RVV`, `RTR`, `RJL`, `RWD`, and `RTK`, each showing a sustained $\ge 24\%$ Type 1 level shift offset by an opposite shift in `other_attendances` (total A&E roughly flat).
- **Retained in both cohorts:**
  - Simple name/title updates without merger breaks (`RA2`, `RHU`, `RJC`, `RQX`, `RRF`, `RWH`, `RXF`) and acute-community mergers whose community partner had zero Type 1 activity (`RAX`, `RWW`).
- **Sensitivity cohort size:** `109` distinct providers and `5,014` eligible origins (`109` per active month across all `46` months from `2022-12` to `2026-09`).

**Important causal distinction:** The sensitivity cohort uses full-period continuity audits and is therefore a **retrospective sensitivity benchmark**, not a causal production filter. Primary model training and chronological evaluation must report performance on the **main provisional cohort** (`provisional_eligible`), with the sensitivity cohort used to quantify how sensitive forecast accuracy is to structural breaks and mergers.

---

## 6. Known Limitations and Next-Step Boundary

1. **Activity proxy vs. official Type 1 designation:** Positive Type 1 reporting in the trailing 12 months is an operational proxy, not an authoritative NHS service registry classification.
2. **Candidate origin $\neq$ evaluable forecast pair:** A provider eligible at origin $t$ only yields an evaluable next-month target if `type1_attendances` is actually observed at $t + 1$ (for example, `2026-09` origins have no $t + 1$ in this dataset, and the final month of a dissolved trust has an absent $t + 1$ that must never be scored as zero).
3. **Publication lag and historical revisions:** The raw NHS England CSVs include revised historical releases. As-of publication timing and chronological split design remain for feature engineering and evaluation setup.
4. **Scope boundary:** No forecasting features, target shifts ($t + 1$), train/validation/test splits, or models have been created in this step.
