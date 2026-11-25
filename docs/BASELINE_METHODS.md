# Common Forecasting Baselines Methodology and 2025 Validation Results

## 1. Purpose and Dataset Provenance

This document defines and records the two deterministic, publication-aware benchmark baselines required prior to supervised machine-learning regression modelling. All baseline calculations reuse [src/models/feature_engineering.py](../src/models/feature_engineering.py) and [src/models/evaluation_splits.py](../src/models/evaluation_splits.py) without modification.

- **Implementation & tests:** [src/models/baselines.py](../src/models/baselines.py), [tests/test_baselines.py](../tests/test_baselines.py)
- **Exploration notebook:** [notebooks/08_baseline_forecasting.ipynb](../notebooks/08_baseline_forecasting.ipynb)
- **Frozen M06 input manifest:** [docs/model_input_manifest.json](model_input_manifest.json) (`run_id: 20261121T204848Z_03520dac`, CSV SHA-256 `16500cdcd05cb1cd4cac4e8b6b973c5586770696c2cf115f5157b9051a146aef`)
- **Step 5 feature dataset:** `outputs/features/m06_historical_features.csv` (`5,599` rows, CSV SHA-256 `adfd18831c2d6e4151f9739fa387f0496f8438b3cbe0cbadba3314d7fe626d14`)
- **Materialised baseline outputs (Git-ignored `outputs/baselines/`):**
  - `outputs/baselines/validation_baseline_predictions.csv` (`1,452` rows, SHA-256 `fad423330262431fce36360ec2d2fdd235ea727284e157d3c1df7109ab80cfdc`)
  - `outputs/baselines/validation_baseline_comparison.csv` (`2` rows, SHA-256 `fb0cd9bc842ba84268c21442718da23058a70af3da1b7242c819cafd8ebb7f6d`)
  - `outputs/baselines/validation_baseline_monthly.csv` (`12` rows, SHA-256 `6a653420b201c32009c34429bfa73b96dbcdae1b6d52843f48ca204837812700`)
  - `outputs/baselines/baseline_metadata.json`

---

## 2. Baseline Formulas and Protocol Alignment

Under [docs/FORECAST_PROTOCOL.md](FORECAST_PROTOCOL.md), a forecast for target month $T$ is issued on decision date $d_T = T - 1\text{ day}$ (last calendar day of month $T - 1$), when the latest published NHS England report is **$o = T - 2$**. Both baselines are strictly deterministic (no fitted parameters) and never use unpublished month $T - 1$ or target month $T$:

1. **Latest-published attendance baseline (`latest_published_t_minus_2`):**
   $$\hat{y}_{i,T}^{\text{latest}} = y_{i,\,T-2} = y_{i,\,o} \quad (\text{column: } \texttt{type1\_origin})$$
2. **Seasonal naive baseline (`seasonal_naive_t_minus_12`):**
   $$\hat{y}_{i,T}^{\text{seasonal}} = y_{i,\,T-12} = y_{i,\,o-10} \quad (\text{column: } \texttt{type1\_target\_lag\_12})$$

### Evaluation Metrics

Across the common validation sample of $N$ provider-month observations with actuals $y_k$ and predictions $\hat{y}_k$:

$$\text{MAE} = \frac{1}{N}\sum_{k=1}^{N} |y_k - \hat{y}_k|, \qquad \text{RMSE} = \sqrt{\frac{1}{N}\sum_{k=1}^{N} (\hat{y}_k - y_k)^2}, \qquad \text{WAPE (\%)} = 100 \times \frac{\sum_{k=1}^{N} |y_k - \hat{y}_k|}{\sum_{k=1}^{N} |y_k|}$$

WAPE is used instead of MAPE because WAPE remains well-defined if genuine zero provider actuals occur and weights errors proportionally to NHS operational attendance volume.

---

## 3. Approved 2025 Validation Population

- **Selection filter:** `split == "validation"` (`target_period` `2025-01` – `2025-12`, 12 months) and `evaluation_eligible == True` (`target_observed == True`).
- **Counts:**
  - Total eligible validation origins: `1,454` (`122` distinct providers)
  - Excluded absent targets: **`2`** (`RAP` in `2025-01` and `2025-02` following its `2025-01-01` merger into `RAL`; target stays `<NA>`, never zeroed)
  - Excluded missing baseline inputs: **`0`** (both `type1_origin` and `type1_target_lag_12` are 100% populated; if any input were missing on a future dataset, both baselines would exclude the affected row from the common sample and report it transparently rather than imputing)
  - **Scored common validation population:** **`1,452` observations** across **`121` distinct providers** (`0` reported zero actuals in 2025 validation; genuine zeros are preserved by `compute_regression_metrics`)
- **Final test set protection:** The 2026 final test partition (`2026-01` – `2026-09`) was **not** accessed, scored, or examined (`test_set_evaluated = False`).

---

## 4. 2025 Validation Comparison Results

| Baseline | Source Column | Scored Observations | Providers | MAE (attendances) | RMSE (attendances) | WAPE (%) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| **Latest-published attendance (`T - 2`)** | `type1_origin` | 1,452 | 121 | **656.44** | **914.66** | **5.74%** |
| **Seasonal naive (`T - 12`)** | `type1_target_lag_12` | 1,452 | 121 | **744.28** | **1,377.78** | **6.51%** |

### Monthly Validation Breakdown (`2025-01` – `2025-12`, `121` providers/month)

| Target Month | Decision Date | Latest Report (`T - 2`) | Latest-Published MAE | Latest-Published WAPE (%) | Seasonal Naive MAE | Seasonal Naive WAPE (%) |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `2025-01` | `2024-12-31` | `2024-11` | 798.42 | 7.28% | 786.54 | 7.17% |
| `2025-02` | `2025-01-31` | `2024-12` | 1,448.27 | 14.11% | 836.74 | 8.15% |
| `2025-03` | `2025-02-28` | `2025-01` | 803.40 | 6.85% | 745.19 | 6.36% |
| `2025-04` | `2025-03-31` | `2025-02` | 1,014.35 | 9.06% | 757.86 | 6.77% |
| `2025-05` | `2025-04-30` | `2025-03` | 284.93 | 2.43% | 649.78 | 5.54% |
| `2025-06` | `2025-05-31` | `2025-04` | 377.91 | 3.28% | 672.99 | 5.84% |
| `2025-07` | `2025-06-30` | `2025-05` | 299.82 | 2.53% | 742.21 | 6.27% |
| `2025-08` | `2025-07-31` | `2025-06` | 485.74 | 4.35% | 806.31 | 7.22% |
| `2025-09` | `2025-08-31` | `2025-07` | 481.91 | 4.21% | 796.78 | 6.96% |
| `2025-10` | `2025-09-30` | `2025-08` | 920.39 | 7.68% | 806.04 | 6.73% |
| `2025-11` | `2025-10-31` | `2025-09` | 484.79 | 4.13% | 670.58 | 5.71% |
| `2025-12` | `2025-11-30` | `2025-10` | 477.38 | 4.10% | 660.36 | 5.68% |

### Analytical Interpretation
- **Why Latest-Published (`T - 2`) outperforms Seasonal Naive (`T - 12`) overall:** Two documented January 2025 structural level shifts dominate Seasonal Naive's RMSE (`1,377.78` vs. `914.66`): `RAL` (Royal Free London absorbing `RAP` North Middlesex on `2025-01-01`, Seasonal Naive MAE = `7,865.9` vs. Latest-Published `1,936.4`) and `RWD` (United Lincolnshire Type 1/Other step-up in `2025-01`, Seasonal Naive MAE = `6,442.9` vs. Latest-Published `1,142.8`). Because `T - 12` stays anchored to pre-shift 2024 volumes for all 12 months of 2025, its squared errors accumulate heavily, whereas `T - 2` adapts within two months.
- **Where Seasonal Naive (`T - 12`) outperforms Latest-Published (`T - 2`):** In months with sharp month-length or seasonal transitions — notably **February (`2025-02`: 8.15% vs. 14.11% WAPE)**, **April (`2025-04`: 6.77% vs. 9.06%)**, **March (`2025-03`: 6.36% vs. 6.85%)**, and **October (`2025-10`: 6.73% vs. 7.68%)** — `T - 2` suffers because it ignores calendar-day length (e.g., predicting 28-day February from 31-day December) and autumn/spring seasonality.
- **Implication for Step 8+ supervised models:** Combining recent demand level (`type1_origin`, rolling averages) with calendar length (`target_days_in_month`) and seasonal lags (`type1_target_lag_12`, `target_month_sin/cos`) directly addresses the complementary weaknesses of both baselines.

---

## 5. Manual Worked Verification (`R0A`, Target October 2025)

Verified directly against `outputs/features/m06_historical_features.csv` and `outputs/baselines/validation_baseline_predictions.csv`:

| Field | Verified Value |
| --- | --- |
| Provider (`org_code`) | `R0A` (Manchester University NHS Foundation Trust) |
| Forecast decision date (`decision_date`) | `2025-09-30` |
| Latest published reporting month (`origin_period = T - 2`) | `2025-08` (`2025-08-01`) |
| Target month (`target_period = T`) | `2025-10` (`2025-10-01`) |
| Actual target (`actual_type1_attendances`) | **`27,673`** |
| Latest-published prediction (`type1_origin`, `2025-08`) | **`23,856`** (error = `-3,817`, absolute error = `3,817`) |
| Seasonal naive prediction (`type1_target_lag_12`, `2024-10`) | **`25,876`** (error = `-1,797`, absolute error = `1,797`) |

---

## 6. Limitations

- Neither baseline adjusts for calendar days in the target month, multi-month demand trends, or concurrent operational load indicators.
- Both baselines are scored on the frozen post-revision M06 snapshot rather than original unrevised historical vintages (as disclosed in [docs/FORECAST_PROTOCOL.md](FORECAST_PROTOCOL.md)).
- Structural breaks from NHS trust mergers (`RAL` in `2025-01`) and service/coding shifts (`RWD` in `2025-01`) remain inside the primary causal validation cohort by design; post-hoc sensitivity breakdowns on Step 3's `109`-provider sensitivity subset can be contrasted alongside primary metrics during supervised model evaluation.
