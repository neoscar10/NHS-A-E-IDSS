# Chronological Evaluation Protocol and Split Validation

## 1. Input Provenance and Reused Contracts

This protocol defines the fixed chronological partitions and publication-aware expanding-window backtesting rules for monthly Type 1 A&E attendance forecasting (`target_type1_attendances`).

- **Frozen M06 input manifest:** [docs/model_input_manifest.json](model_input_manifest.json) (`run_id: 20261121T204848Z_03520dac`, CSV SHA-256 `16500cdcd05cb1cd4cac4e8b6b973c5586770696c2cf115f5157b9051a146aef`)
- **Step 5 feature dataset:** `outputs/features/m06_historical_features.csv` (`5,599` rows, CSV SHA-256 `adfd18831c2d6e4151f9739fa387f0496f8438b3cbe0cbadba3314d7fe626d14`, linked via `outputs/features/feature_metadata.json`)
- **Forecasting & cohort contracts:** [docs/COHORT_METHODOLOGY.md](COHORT_METHODOLOGY.md), [docs/FORECAST_PROTOCOL.md](FORECAST_PROTOCOL.md), [docs/FEATURE_ENGINEERING.md](FEATURE_ENGINEERING.md)
- **Implementation & tests:** [src/models/evaluation_splits.py](../src/models/evaluation_splits.py), [tests/test_evaluation_splits.py](../tests/test_evaluation_splits.py)
- **Generated local split summaries (Git-ignored):** `outputs/splits/split_summary.json` and `outputs/splits/expanding_window_schedule.csv`

---

## 2. Fixed Chronological Partitions (by `target_period`)

All records are partitioned deterministically by **`target_period`** (never randomly, and never by `origin_period`). Because the operational publication horizon is $T = o + 2$, the corresponding data-origin ranges precede each partition by two calendar months:

| Partition | Target Period Range (`target_period`) | Target Months | Data-Origin Range (`origin_period`) | Total Eligible Rows | Observed Targets (Evaluable) | Absent / Unlabelled Rows | Distinct Providers (Eligible / Evaluable) | Evaluable Rows with Complete Features |
| --- | --- | ---: | --- | ---: | ---: | ---: | --- | ---: |
| **`train`** | `2023-02` – `2024-12` | 23 | `2022-12` – `2024-10` | 2,817 | **2,813** | 4 | 124 / 124 | 2,689 *(124 in `2023-02` lack `type1_origin_lag_12`)* |
| **`validation`** | `2025-01` – `2025-12` | 12 | `2024-11` – `2025-10` | 1,454 | **1,452** | 2 | 122 / 121 | **1,452 (100%)** |
| **`test`** | `2026-01` – `2026-09` | 9 | `2025-11` – `2026-07` | 1,088 | **1,086** | 2 | 121 / 121 | **1,086 (100%)** |
| **Labelled subtotal** | `2023-02` – `2026-09` | 44 | `2022-12` – `2026-07` | 5,359 | **5,351** | 8 | 124 / 124 | 5,227 |
| **`future_unlabelled`** | `2026-10` – `2026-11` | 2 | `2026-08` – `2026-09` | 240 | **0** | 240 | 120 / 0 | 0 *(240 operational rows, complete features)* |
| **Total** | `2023-02` – `2026-11` | 46 | `2022-12` – `2026-09` | **5,599** | **5,351** | **248** | **124 / 124** | — |

### Treatment of Non-Evaluable Rows (Metadata Preserved, Excluded from Scoring)
- **8 absent in-range targets (`exclusion_reason = "absent_target_provider_unreported"`):** The final two eligible origins prior to dissolution of the four post-2022 acute-merger trusts — `RA4` (`2023-04`, `2023-05` in `train`), `RVY` (`2023-07`, `2023-08` in `train`), `RAP` (`2025-01`, `2025-02` in `validation`), and `RVJ` (`2026-07`, `2026-08` in `test`). Their target remains `<NA>` and is **never** imputed as zero.
- **240 future unlabelled rows (`exclusion_reason = "future_target_beyond_m06"`):** Target months `2026-10` and `2026-11` lie beyond the frozen `2022-01`–`2026-09` M06 dataset and are strictly excluded from `train`, `validation`, and `test`.

---

## 3. Publication-Aware Expanding-Window Backtesting Protocol

To mirror operational NHS deployment without publication-timing leakage, evaluation across both **validation** (`2025-01` – `2025-12`, 12 monthly decision dates) and **test** (`2026-01` – `2026-09`, 9 monthly decision dates) follows a **monthly expanding-window refit protocol**:

For each target month $T$:
1. **Forecast decision date:** $d_T = T - 1\text{ day}$ (last calendar day of month $T - 1$).
2. **Latest published NHS report:** $o = T - 2\text{ months}$ (published on the 2nd/3rd Thursday of month $T - 1$, verified in [docs/publication_availability.csv](publication_availability.csv)).
3. **Permissible training rows:** All rows with `evaluation_eligible == True` and **`target_period <= o`** (`target_period <= T - 2`).
   - Training labels from **$T - 1$** are **strictly prohibited** because month $T - 1$ has not been published on decision date $d_T$.
   - Training labels from **$T$** (or later) are strictly prohibited.
4. **Evaluation rows:** Eligible rows with `target_period == T` (all of which have `origin_period == o`), scored exclusively on `evaluation_eligible == True` (`target_observed == True`).
5. **Origin-specific refitting & preprocessing rule:** Any fitted model parameters, feature scalers, imputers, or categorical encoders must be fitted **solely** on that decision date's permissible `train_df` (`target_period <= o`) and then applied without refitting to the evaluation rows at $T$. No transformation may be fitted across the full dataset.

### Legitimate Expanding-Window Refitting vs. Prohibited Leakage

| Aspect | Validation (`2025-01` – `2025-12`) | Final Test (`2026-01` – `2026-09`) |
| --- | --- | --- |
| **Permissible training labels at target $T$** | All observed targets with `target_period <= T - 2` (starting `2023-02` – `2024-11` for $T = \text{2025-01}$, expanding monthly to `2023-02` – `2025-10` for $T = \text{2025-12}$). | All observed targets with `target_period <= T - 2` (starting `2023-02` – `2025-11` for $T = \text{2026-01}$, expanding monthly to `2023-02` – `2026-07` for $T = \text{2026-09}$). |
| **Role of newly published validation/test months** | Legitimate operational parameter refitting on already-published historical months $\le T - 2$. | Legitimate operational parameter refitting on already-published historical months $\le T - 2$ **only after** model architecture, feature set, and hyperparameters are permanently frozen from validation. |
| **Model selection & hyperparameter tuning** | **Permitted** on validation metrics only. | **Strictly prohibited.** Never inspect test errors to tune hyperparameters, add/remove features, or pick the winning model. |

### Worked Expanding-Window Examples

| Target Month ($T$) | Partition | Decision Date ($d_T$) | Latest Published Cutoff ($o = T - 2$) | Excluded Unpublished $T - 1$ | Permissible Training Range | Training Rows (All / Complete Features) | Eval Rows (Eligible / Evaluable / Absent) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **`2025-01`** | `validation` | `2024-12-31` | **`2024-11`** (pub. `2024-12-12`) | `2024-12` (`122` rows; pub. `2025-01-09`) | `2023-02` – `2024-11` (`124` orgs) | `2,691` / `2,567` | `122` / **`121`** / `1` (`RAP`) |
| **`2026-01`** | `test` | `2025-12-31` | **`2025-11`** (pub. `2025-12-11`) | `2025-12` (`121` rows; pub. `2026-01-15`) | `2023-02` – `2025-11` (`124` orgs) | `4,144` / `4,020` | `121` / **`121`** / `0` |

---

## 4. Rules for Fair Model Comparisons

1. **Identical evaluation target population:** Every baseline and candidate model must be scored on the exact same **`1,452` validation target rows** (`2025-01` – `2025-12`) and, once frozen, on the exact same **`1,086` test target rows** (`2026-01` – `2026-09`).
2. **Handling the 124 early missing `type1_origin_lag_12` rows:** All `124` rows with missing `type1_origin_lag_12` occur in `target_period == 2023-02` (inside `train`). Every single validation (`1,452 / 1,452`) and test (`1,086 / 1,086`) evaluation row has complete core and optional features. Models that cannot natively accept `NaN` in training should either pass `complete_features_only=True` to `get_expanding_window_split` (dropping only those `124` `2023-02` training rows) or fit a training-only imputer inside each expanding fold — in both cases scoring against the identical `1,452` validation / `1,086` test targets.
3. **Core vs. core-plus-optional feature comparisons:** Compare `CORE_FEATURE_COLUMNS` (13 features) against `ALL_FEATURE_COLUMNS` (19 features) on the identical evaluation population (`1,452` validation / `1,086` test rows), remembering the 14-trust NHS CRS 4-hour reporting exemption through `2023-05` documented in [docs/FEATURE_ENGINEERING.md](FEATURE_ENGINEERING.md).
4. **Genuine zeros and absent targets:** Genuine reported zero attendances remain `0`; absent targets remain `<NA>` and are excluded from scoring (`evaluation_eligible == False`).
5. **Provider mergers and continuity sensitivity:** Primary model selection and headline evaluation use the strictly causal **primary provisional cohort** (retaining all merger and step-change trusts without retrospective filtering). Secondary sensitivity metrics may additionally be reported on Step 3's companion `sensitivity_eligible` subset (`109` providers) purely as a post-hoc diagnostic breakdown — never to filter training data retrospectively.

---

## 5. Unresolved Methodological Considerations

- **Post-revision historical snapshot:** As documented in [docs/FORECAST_PROTOCOL.md](FORECAST_PROTOCOL.md), `43 / 57` raw CSVs are semi-annually revised NHS England releases; backtesting therefore enforces exact publication-lag cutoffs on the frozen M06 snapshot rather than original unrevised vintages.
- **Test-window merger impact (`RVJ -> RA7`, `2026-07`):** Within the 9-month test window (`2026-01` – `2026-09`), `RVJ` merges into `RA7` on `2026-07-01`, causing `2` excluded absent targets for `RVJ` (`2026-07`, `2026-08`) and a `+59.6%` volume jump for `RA7` in `2026-07` – `2026-09`. Primary test metrics will include `RA7` honestly, with secondary sensitivity reporting showing error with and without the 15 continuity-flagged trusts.
- **Scope boundary:** No scalers, imputers, baselines, or models have been fitted in this step.
