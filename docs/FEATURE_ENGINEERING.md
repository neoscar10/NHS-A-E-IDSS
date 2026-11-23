# Historical Feature Engineering Methodology

## 1. Input Dataset and Protocol Reference

This document specifies the leakage-safe historical feature pipeline implemented in [src/models/feature_engineering.py](../src/models/feature_engineering.py) and tested in [tests/test_feature_engineering.py](../tests/test_feature_engineering.py).

- **Accepted input manifest:** [docs/model_input_manifest.json](model_input_manifest.json)
- **Frozen M06 input file:** `.work/rebuild/data/processed/m06/20261121T204848Z_03520dac/ae_provider_calendar_final.csv` (`run_id: 20261121T204848Z_03520dac`, isolated rebuild verified byte-identical to archived M06 run `20261118T153942Z_fbc5f80f`)
- **Input CSV SHA-256:** `16500cdcd05cb1cd4cac4e8b6b973c5586770696c2cf115f5157b9051a146aef`
- **Cohort selection reused:** `load_accepted_m06` and `build_cohorts` from [src/data/cohort_selection.py](../src/data/cohort_selection.py) ([docs/COHORT_METHODOLOGY.md](COHORT_METHODOLOGY.md))
- **Forecasting protocol:** [docs/FORECAST_PROTOCOL.md](FORECAST_PROTOCOL.md)

---

## 2. Origin, Decision-Date, and Target Timing Convention

Per [docs/FORECAST_PROTOCOL.md](FORECAST_PROTOCOL.md):

- **Target month ($T$):** Calendar month whose Type 1 A&E attendances (`target_type1_attendances`) are predicted (`target_period = YYYY-MM-01`).
- **Forecast decision date ($d_T$):** Last calendar day before $T$ begins (`decision_date = target_period - 1 day`, i.e. final day of month $T - 1$).
- **Data-origin month ($o$):** Latest published NHS England A&E monthly report available on $d_T$: **$o = T - 2$** (`origin_period = target_period - 2 months`, `horizon_months = 2`).
- **Unpublished month ($T - 1 = o + 1$):** Not published until the 2nd (occasionally 3rd) Thursday of month $T$; strictly excluded from all predictors.
- **No target-relative lag 1:** Because $T - 1$ is unpublished on $d_T$, the most recent observed attendance count is `type1_origin` (at $o = T - 2$).

---

## 3. Feature Definitions

All features are grouped by `org_code` and aligned by **exact calendar month dates** on the contiguous monthly M06 calendar (never via positional row shifting after dropping missing rows, and never forward-filling absent months).

### A. Core Predictors (`CORE_FEATURE_COLUMNS`, 13 features)

| Group | Feature Name | Formula / Calendar Reference | Missingness on M06 |
| --- | --- | --- | ---: |
| Attendance | `type1_origin` | `type1_attendances` at $o$ | 0 |
| Attendance | `type1_origin_lag_1` | `type1_attendances` at $o - 1$ | 0 |
| Attendance | `type1_origin_lag_2` | `type1_attendances` at $o - 2$ | 0 |
| Attendance | `type1_origin_lag_3` | `type1_attendances` at $o - 3$ | 0 |
| Attendance | `type1_origin_lag_12` | `type1_attendances` at $o - 12$ (13 months before $o + 1$) | **124** (initial `2022-12` origins) |
| Attendance | `type1_target_lag_12` | `type1_attendances` at **$T - 12 = o - 10$** (same calendar month as target $T$ one year earlier) | 0 |
| Rolling | `type1_origin_roll_mean_3` | Mean of `type1_attendances` over $[o - 2, o]$ (`min_periods=3`) | 0 |
| Rolling | `type1_origin_roll_mean_6` | Mean of `type1_attendances` over $[o - 5, o]$ (`min_periods=6`) | 0 |
| Rolling | `type1_origin_roll_mean_12` | Mean of `type1_attendances` over $[o - 11, o]$ (`min_periods=12`) | 0 |
| Calendar | `target_month` | Integer month of $T$ (`1`–`12`) | 0 |
| Calendar | `target_days_in_month` | Calendar days in month $T$ (`28`, `29`, `30`, `31`) | 0 |
| Calendar | `target_month_sin` | $\sin(2\pi \cdot \text{target\_month} / 12)$ (cyclical seasonality encoding for linear/distance models) | 0 |
| Calendar | `target_month_cos` | $\cos(2\pi \cdot \text{target\_month} / 12)$ | 0 |

### B. Optional Published Operational Predictors (`OPTIONAL_FEATURE_COLUMNS`, 6 features)

All optional features use strictly published M06 counts from months $\le o$:

| Group | Feature Name | Formula / Definition | Missingness on M06 |
| --- | --- | --- | ---: |
| Admissions | `type1_emergency_admissions_origin` | `type1_emergency_admissions` at $o$ | 0 |
| Admissions | `type1_emergency_admissions_roll_mean_3` | Mean of `type1_emergency_admissions` over $[o - 2, o]$ (`min_periods=3`) | 0 |
| Admissions | `type1_admission_rate_origin` | `type1_emergency_admissions / type1_attendances` at $o$ (`NaN` if denominator $\le 0$ or missing) | 0 |
| 4-Hour Perf. | `type1_over_4hrs_origin` | `type1_over_4hrs` (Type 1 attendances waiting over 4 hours) at $o$ | 0 |
| 4-Hour Perf. | `type1_within_4hrs_rate_origin` | $1 - (\text{type1\_over\_4hrs} / \text{type1\_attendances})$ at $o$ (NHS 4-hour compliance proportion; `NaN` if denominator $\le 0$ or missing) | 0 |
| 4-Hour Perf. | `type1_within_4hrs_rate_roll_mean_3` | Mean of `type1_within_4hrs_rate` over $[o - 2, o]$ (`min_periods=3`) | 0 |

> **NHS Clinical Review of Standards (CRS) Caveat:** Fourteen eligible trusts (`R0D`, `RC9`, `RDU`, `RFR`, `RGR`, `RGT`, `RHU`, `RK9`, `RNQ`, `RQM`, `RVW`, `RX1`, `RXF`, `RYJ`) reported `type1_over_4hrs = 0` through `2023-05` (`84` eligible origin rows) under NHS England's CRS field-testing exemption rather than true 100% 4-hour compliance. Keeping 4-hour indicators in the separate optional feature set allows models to be evaluated with and without them.

---

## 4. Output Schema and Materialised Location

Materialised outputs are written to the Git-ignored directory `outputs/features/`:
- `outputs/features/m06_historical_features.csv`
- `outputs/features/m06_historical_features.parquet`
- `outputs/features/feature_metadata.json` (records the input M06 `run_id`, input CSV SHA-256, output SHA-256 hashes, column groups, and summary counts)

### Schema Structure (32 columns total)
- **Metadata (`12` columns):** `org_code`, `origin_period`, `decision_date`, `target_period`, `target_year` (metadata initially, not a predictor), `horizon_months`, `history_window_months`, `is_eligible_origin`, `target_observed`, `is_future_forecast`, `has_complete_core_features`, `has_complete_all_features`.
- **Target (`1` column):** `target_type1_attendances` (nullable `Int64`; matched strictly on `("org_code", target_period)` where `is_observed == True`, otherwise `<NA>`).
- **Predictors (`19` columns):** `13` core + `6` optional features, extracted safely via `get_predictor_matrix(df, include_optional=...)`.

---

## 5. Missing-Feature, Missing-Target, and Eligibility Handling

1. **Primary past-only cohort preserved:** Every eligible origin from Step 3 (`provisional_eligible == True`) is retained (`5,599` rows across `124` providers; `origin_period` `2022-12` to `2026-09`).
2. **Initial `type1_origin_lag_12` handled explicitly:** Because `2022-12` is the 12th month of the dataset, `o - 12 = 2021-12` lies before `2022-01`. Those **`124` rows** remain in the dataset with `type1_origin_lag_12 = NaN` and `has_complete_core_features = False` rather than altering the 12-month eligibility rule or silently dropping rows. Notably, `type1_target_lag_12` ($T - 12 = o - 10 = \text{2022-02}$) **is** available for all `5,599` origins.
3. **Clear 4-way row classification:**

| Subset | Row Count | Description |
| --- | ---: | --- |
| **1. Eligible forecast origins** (`is_eligible_origin`) | **5,599** | All Step 3 primary causal origins (`2022-12` – `2026-09`, `124` providers) |
| **2. Observed target labels** (`target_observed`) | **5,351** | In-range origins (`2022-12` – `2026-07`) with observed `type1_attendances` at $T = o + 2$ |
| — *Absent targets in range* (`~is_future_forecast & ~target_observed`) | **8** | Final 2 eligible origins of the 4 dissolved trusts (`RA4`, `RVY`, `RAP`, `RVJ`); `target_type1_attendances` stays `<NA>` (never zeroed) |
| **3. Complete feature rows** (`has_complete_core_features` / `has_complete_all_features`) | **5,475** | All origins from `2023-01` – `2026-09` (`5,227` among the `5,351` target-observed rows) |
| **4. Future forecast origins** (`is_future_forecast`) | **240** | `2026-08` $\to$ `2026-10` (`120`) and `2026-09` $\to$ `2026-11` (`120`); complete features, no target in frozen M06 |

---

## 6. Leakage Safeguards

- `get_predictor_matrix` explicitly forbids `target_type1_attendances`, metadata (`target_year`, dates, `org_code`), provenance fields (`source_*`), national totals, and Step 3 retrospective continuity flags (`material_continuity_concern`, `sensitivity_eligible`, `continuity_category`).
- Calendar alignment uses explicit `pd.DateOffset` date indexing on the unpruned monthly calendar, preventing missing-month shift corruption.
- Automated tests in [tests/test_feature_engineering.py](../tests/test_feature_engineering.py) verify invariance to arbitrary mutations of unpublished month $T - 1$, target month $T$, and any later periods.

---

## 7. Known Limitations

- **Frozen post-revision snapshot:** As documented in [docs/FORECAST_PROTOCOL.md](FORECAST_PROTOCOL.md), `43` of `57` raw NHS England CSVs are revised releases; historical features reflect the frozen M06 snapshot rather than original unrevised publication vintages.
- **Merger transitions inside trailing windows:** For the 5 absorbing acute trusts (`RH8`, `RH5`, `RBN`, `RAL`, `RA7`), 12-month trailing features straddle pre- and post-merger footprints for the 12 months following each merger. No retrospective merger flags are added as predictors; sensitivity evaluation remains available via Step 3's companion `sensitivity_eligible` cohort.
- **No modelling performed:** Train/validation/test splits, feature scaling, hyperparameter tuning, and model training remain for subsequent roadmap steps.
