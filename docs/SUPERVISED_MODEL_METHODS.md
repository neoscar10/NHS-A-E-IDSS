# Supervised Regression Candidate Models Methodology

## 1. Purpose and Scope

This document specifies the three initial supervised regression candidates built in Step 8 ([src/models/supervised_models.py](../src/models/supervised_models.py), tested in [tests/test_supervised_models.py](../tests/test_supervised_models.py), demonstrated in [notebooks/09_supervised_models.ipynb](../notebooks/09_supervised_models.ipynb)).

- **Objective:** Establish reproducible, leakage-safe regression pipelines using the exact 13 core predictors and the publication-aware historical training fold.
- **Step 8 boundary:** Initial model fitting and in-sample sanity verification only. No hyperparameter search, no 2025 validation scoring/comparison, and no 2026 test evaluation are performed here (reserved for Step 9+).

---

## 2. Three Regression Candidates and Justification

All three candidates perform continuous regression for `target_type1_attendances` and represent distinct model families suited to tabular monthly demand forecasting:

| Candidate | Estimator & Pipeline | Initial Hyperparameters | Random Seed | Justification |
| --- | --- | --- | --- | --- |
| **`ridge`** | `Pipeline([("scaler", StandardScaler()), ("model", Ridge(...))])` | `alpha=10.0` | Deterministic (closed-form / SVD) | Fast, interpretable linear baseline with L2 regularisation to stabilise highly collinear attendance lags and rolling averages; serves as a direct test of whether linear combinations of level + seasonality beat deterministic naive benchmarks. |
| **`random_forest`** | `Pipeline([("model", RandomForestRegressor(...))])` | `n_estimators=200`, `max_depth=12`, `min_samples_leaf=5`, `n_jobs=1` | `random_state=42` | Non-linear bagged tree ensemble capturing interaction effects (e.g. provider scale $\times$ month length / seasonality) without requiring feature scaling; conservative depth and leaf size limit overfitting and laptop memory usage. |
| **`hist_gradient_boosting`** | `Pipeline([("model", HistGradientBoostingRegressor(...))])` | `learning_rate=0.05`, `max_iter=200`, `max_leaf_nodes=31`, `min_samples_leaf=20`, `l2_regularization=1.0`, **`early_stopping=False`** | `random_state=42` | Fast histogram-based gradient boosting well suited to smooth non-linear tabular relationships; `early_stopping=False` is explicitly enforced so scikit-learn never creates an internal random validation split that would compromise chronological evaluation discipline. |

---

## 3. Approved 13 Core Predictors (Fixed Canonical Order)

Enforced programmatically by `get_core_feature_columns()` and `prepare_feature_matrix()` (definitions in [docs/FEATURE_ENGINEERING.md](FEATURE_ENGINEERING.md)):

1. `type1_origin` ($o = T - 2$)
2. `type1_origin_lag_1` ($o - 1$)
3. `type1_origin_lag_2` ($o - 2$)
4. `type1_origin_lag_3` ($o - 3$)
5. `type1_origin_lag_12` ($o - 12$)
6. `type1_target_lag_12` ($T - 12 = o - 10$)
7. `type1_origin_roll_mean_3` ($[o - 2, o]$)
8. `type1_origin_roll_mean_6` ($[o - 5, o]$)
9. `type1_origin_roll_mean_12` ($[o - 11, o]$)
10. `target_month` (`1`–`12`)
11. `target_days_in_month` (`28`–`31`)
12. `target_month_sin` ($\sin(2\pi \cdot \text{target\_month}/12)$)
13. `target_month_cos` ($\cos(2\pi \cdot \text{target\_month}/12)$)

- **Target label:** `target_type1_attendances` (never in predictor matrix $X$).
- **Explicitly excluded from initial predictors:** `org_code`, `target_year`, other metadata/date columns, unpublished month $T - 1$, target month $T$, the 6 optional operational features (admissions / 4-hour metrics), and retrospective continuity/sensitivity flags.

---

## 4. Initial Training Population and Publication Cutoff

The initial reproducible fit simulates the **January 2025 (`2025-01`)** forecast using `select_training_fold(split_df, "2025-01-01", complete_core_only=True)` (reusing [src/models/evaluation_splits.py](../src/models/evaluation_splits.py)):

- **Forecast target month ($T$):** `2025-01`
- **Forecast decision date ($d_T$):** `2024-12-31`
- **Latest published NHS report ($o = T - 2$):** `2024-11` (published `2024-12-12`)
- **Excluded unpublished $T - 1$ labels (`2024-12`):** `122` rows (not published until `2025-01-09`)
- **Permissible observed training labels (`target_period <= 2024-11`):** **`2,691`** rows (`2023-02` – `2024-11`, `124` providers)
- **Excluded incomplete-core rows:** **`124`** rows (`target_period == 2023-02`, missing only `type1_origin_lag_12`; **not** imputed)
- **Actual fitted complete-core training population (identical for all 3 models):** **`2,567`** rows (`2023-03` – `2024-11`, `124` distinct providers)

---

## 5. Preprocessing, Missing Values, and Non-Negative Prediction Policy

- **Training-only preprocessing:** `StandardScaler` is encapsulated strictly inside Ridge's scikit-learn `Pipeline`. Calling `fit_model("ridge", train_df)` fits scaling means and standard deviations solely on the supplied historical training fold (`scaler.n_samples_seen_ == 2,567` for the initial `2025-01` fold). Tree models (`random_forest`, `hist_gradient_boosting`) receive unscaled features directly.
- **Missing-value treatment:** No imputation is applied to `type1_origin_lag_12`. All three candidates fit on the identical complete-core training population (`complete_core_only=True`), ensuring fair comparison without synthetic lag inflation.
- **Non-negative count prediction policy:** Because Type 1 A&E attendance is a non-negative count, `predict_with_model(..., clip_non_negative=True)` applies a fixed domain rule `prediction = max(0.0, raw_prediction)` while always preserving `raw_prediction` and `was_clipped` for diagnostics. This rule is fixed by domain definition and is never tuned on validation or test outcomes.

---

## 6. Reproducibility, Environment, and Local Artefacts

- **Verified data provenance:**
  - Frozen M06 CSV: `.work/rebuild/data/processed/m06/20261121T204848Z_03520dac/ae_provider_calendar_final.csv` (`sha256: 16500cdcd05cb1cd4cac4e8b6b973c5586770696c2cf115f5157b9051a146aef`)
  - Step 5 Feature CSV: `outputs/features/m06_historical_features.csv` (`sha256: adfd18831c2d6e4151f9739fa387f0496f8438b3cbe0cbadba3314d7fe626d14`)
- **Verified `.venv` package versions (`requirements.txt` updated with `scikit-learn>=1.5,<2`):**
  - `Python 3.12.10`, `scikit-learn 1.9.1`, `scipy 1.18.1`, `joblib 1.6.0`, `numpy 2.5.5`, `pandas 2.3.3`
- **Local Git-ignored artefacts (`outputs/models/initial_fit/`):**
  - `ridge_2025-01.joblib`, `random_forest_2025-01.joblib`, `hist_gradient_boosting_2025-01.joblib`
  - `initial_fit_metadata_2025-01.json` (records dataset SHA-256s, 13 features, cutoff, configurations, preprocessing stats, artefact hashes, and `validation_evaluated: false`, `test_evaluated: false`)
- **Reproduction command:**
  ```powershell
  .\.venv\Scripts\python.exe -m src.models.supervised_models
  ```

---

## 7. Limitations and Items for Step 9 Validation

1. **No out-of-sample evidence yet:** Step 8 verifies fitting and reproducibility only; true predictive performance against the Step 7 baselines (`MAE 656.44`, `RMSE 914.66`, `WAPE 5.74%`) will be measured via expanding-window 2025 validation in Step 9.
2. **Tree extrapolation on large or newly merged trusts:** Tree models (`RandomForestRegressor`, `HistGradientBoostingRegressor`) cannot extrapolate beyond the maximum attendance seen in the training fold; Step 9 validation should inspect large trusts and post-merger `RAL` (`2025-01`) vs. Ridge's linear extrapolation.
3. **Optional operational features & hyperparameter tuning:** Ablating the 6 optional operational features (admissions / 4-hour metrics) and tuning regularisation/tree depth strictly on 2025 validation remain for Step 9.
