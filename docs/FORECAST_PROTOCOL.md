# Forecasting Protocol and Publication Availability Audit

**Accepted Input Dataset:** `.work/rebuild/data/processed/m06/20261121T204848Z_03520dac/ae_provider_calendar_final.csv`  
**Manifest Reference:** [docs/model_input_manifest.json](model_input_manifest.json) (`sha256: 16500cdcd05cb1cd4cac4e8b6b973c5586770696c2cf115f5157b9051a146aef`, isolated rebuild run `20261121T204848Z_03520dac`)  
**Cohort Specification:** [docs/COHORT_METHODOLOGY.md](COHORT_METHODOLOGY.md) (`src/data/cohort_selection.py`)  
**Publication Audit Table:** [docs/publication_availability.csv](publication_availability.csv)

---

## 1. Exact Forecasting Problem Definition

The primary modelling task is **provider-level, next-calendar-month forecasting of Type 1 A&E attendances** to support operational capacity planning prior to the start of each calendar month.

| Protocol Element | Exact Definition |
| --- | --- |
| **Forecast target month ($T$)** | The upcoming calendar month being predicted, indexed by its month-start date (`period = YYYY-MM-01`). |
| **Forecast decision date ($d_T$)** | The **last calendar day before target month $T$ begins** — i.e., the final calendar day of month $T - 1$ (e.g., `2025-09-30` when forecasting `2025-10`, `2026-09-30` when forecasting `2026-10`). |
| **Target variable** | `type1_attendances` for (`org_code`, $T$) — monthly non-negative integer count of Type 1 A&E attendances. |
| **Latest published reporting month at $d_T$ ($o$)** | **$o = T - 2$** (two months before target month $T$), because NHS England does not publish reporting month $T - 1$ until the 2nd (occasionally 3rd) Thursday of month $T$. |
| **Forecast horizon** | **Next calendar month from decision date $d_T$** (calendar lead = 1 day before $T$ starts), which corresponds to an **operational data horizon of $h = 2$ reporting months** from the latest published report ($o = T - 2 \to T$). |
| **Available historical information at $d_T$** | All published provider monthly A&E records with `period <= o` ($o = T - 2$) from the accepted M06 calendar, plus deterministic calendar attributes of $T$ known in advance (calendar month, days in month, UK bank holidays). |
| **Provider eligibility at $d_T$** | Step 3 time-aware `type1_candidate` evaluated at the latest published reporting month **$o = T - 2$**: observed at $o$, 12 consecutive observed calendar months $[o - 11, o]$, and $\ge 1$ positive `type1_attendances` in $[o - 11, o]$. |
| **Target observability for evaluation** | A forecast for eligible provider (`org_code`, $o = T - 2$) is **evaluable** if and only if (`org_code`, $T$) exists in the M06 calendar with `is_observed == True` (`type1_attendances` non-null). Absent targets (`is_observed == False`, e.g., dissolved trusts) or targets beyond `2026-09` are **not evaluable** and are never imputed as zero. |

### Why $o = T - 2$ ($h = 2$) Is Mandatory

Do **not** confuse a reporting month with its publication date. On the last day of month $T - 1$, reporting month $T - 1$ has barely ended and has not yet been collected, validated, or published by NHS England. Treating month $T - 1$ as an available predictor on decision date $d_T$ would introduce **1-month publication-timing leakage** that is impossible to replicate in operational deployment.

---

## 2. NHS England Publication-Availability Audit

NHS England's official [A&E Waiting Times and Activity](https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/) portal states:

> *"Regular NHS performance statistics publication are scheduled for the 2nd Thursday of each month and include A&E data from the previous month. For example, the publication on August will include A&E data for July."*

All 58 reporting months from **January 2022 through October 2026** (the 57 months in the frozen M06 dataset plus October 2026 to verify the September/October 2026 boundary) were audited against official **GOV.UK Statistics API** records and **NHS England Statistical Commentary / CSV HTTP upload headers** ([docs/publication_availability.csv](publication_availability.csv)):

- **53 of 58 months verified** with authoritative release dates (`47` directly via GOV.UK `first_published_at`, `4` via NHS England upload headers where GOV.UK was missing, late-posted, or offset by 1–5 days, and `2` via GOV.UK release announcements — `2023-07` corroborated by NHS England commentary upload and `2022-04` provisional announcement).
- **5 early months unverified (`2022-02`, `2022-03`, `2022-07`, `2022-12`, `2023-01`):** GOV.UK backfilled all five statistical pages in bulk on `2023-03-02` (`12:00–12:30 UTC`), and NHS England's 2021–22 / 2022–23 archive pages no longer host individual monthly commentary PDFs. Their `actual_publication_date` cells are intentionally left blank in [docs/publication_availability.csv](publication_availability.csv) rather than invented.
- **Verified publication lag across all 53 verified releases:**
  - Every single verified release occurred in **month $m + 1$**, on a **Thursday** between the **8th and 16th** of month $m + 1$ (**8 to 16 calendar days after reporting month end**; zero releases occurred on or before the last day of reporting month $m$).
  - Occasional 3rd-Thursday releases occurred (e.g., `2022-05` $\to$ `2022-06-16`, `2025-04` $\to$ `2025-05-15`, `2025-12` $\to$ `2026-01-15`, `2026-03` $\to$ `2026-04-16`), still well before the end of month $m + 1$, confirming that month $T - 2$ is **always** published before decision date $d_T$ (end of $T - 1$) and month $T - 1$ is **never** published before $d_T$.

### Verification of the September / October 2026 Publication-Lag Boundary

| Reporting Month | Verified NHS England Publication Date | GOV.UK Statistics Record | Availability on Decision Date `2026-09-30` |
| --- | --- | --- | --- |
| `2026-08` (Aug 2026) | **`2026-09-10`** (Thu, 09:30 BST) | `2026-09-10` ([gov.uk](https://www.gov.uk/government/statistics/ae-attendances-and-emergency-admissions-for-august-2026)) | **Available** (published 20 days earlier) |
| `2026-09` (Sep 2026) | **`2026-10-08`** (Thu; `September-2026-CSV-Re72Eh.csv` uploaded `07:55 GMT`) | `2026-10-09` (1-day GOV.UK listing offset; [gov.uk](https://www.gov.uk/government/statistics/ae-attendances-and-emergency-admissions-for-september-2026-and-quarterly-report-q2)) | **Not available** (published 8–9 days *after* decision date) |
| `2026-10` (Oct 2026) | **`2026-11-12`** (Thu, 09:30 GMT; confirmed on NHS England 2026–27 page) | `2026-11-12` ([gov.uk](https://www.gov.uk/government/statistics/ae-attendances-and-emergency-admissions-for-october-2026)) | **Target month** (outside frozen M06 `2022-01`–`2026-09` window) |

---

## 3. Application of Cohort Rules and Evaluable Coverage

At each historical decision date $d_T$ (last day of month $T - 1$):

1. Identify the latest published reporting month $o = T - 2$.
2. Select the **primary provisional cohort** using Step 3's `provisional_eligible` (`type1_candidate`) flag at `period == o` (`src/data/cohort_selection.py`).
   - First eligible origin in M06 is $o = \text{2022-12}$ (first 12-month window `2022-01`–`2022-12`), so the **first protocol-compliant forecast decision date** is **`2023-01-31`**, targeting **`2023-02`** ($o = \text{2022-12}$, $T = \text{2023-02}$).
   - Last protocol-compliant decision date whose target lies inside the frozen M06 dataset is **`2026-08-31`**, targeting **`2026-09`** from latest published report **$o = \text{2026-07}$** (published `2026-08-13`).
   - Decision dates **`2026-09-30`** ($o = \text{2026-08} \to T = \text{2026-10}$) and **`2026-10-31`** ($o = \text{2026-09} \to T = \text{2026-11}$) have valid eligible cohorts (`120` providers each), but their targets lie beyond `2026-09` and cannot be evaluated against the frozen M06 dataset.
3. Evaluate model error **only** on eligible pairs (`org_code`, $o$) whose target (`org_code`, $T = o + 2$) is observed (`is_observed == True`).

### Frozen M06 Protocol Coverage (`o = T - 2`, $h = 2$)

| Category | Provider-Month Pairs | Notes |
| --- | ---: | --- |
| Total provisional eligible origins in M06 (`o` in `2022-12` – `2026-09`) | 5,599 | Across `46` active origin months and `124` distinct providers |
| Origins with target $T = o + 2$ inside M06 (`o` in `2022-12` – `2026-07`; $T$ in `2023-02` – `2026-09`) | 5,359 | Across `44` historical decision dates (`2023-01-31` – `2026-08-31`) |
| — **Target observed (evaluable pairs)** | **5,351** | Non-null `type1_attendances` at $T$ |
| — **Target absent (non-evaluable; never scored as zero)** | **8** | Final 2 eligible origins before each of the 4 dissolved trusts ceased reporting: `RA4` (`2023-02`, `2023-03`), `RVY` (`2023-05`, `2023-06`), `RAP` (`2024-11`, `2024-12`), `RVJ` (`2026-05`, `2026-06`) |
| Origins with target $T = o + 2$ beyond frozen M06 (`o` in `2026-08`, `2026-09` $\to$ $T$ in `2026-10`, `2026-11`) | 240 | `120` providers per month; operational forecast origins only |

---

## 4. Information-Leakage Prevention Rules

At every forecast decision date $d_T$ (end of $T - 1$, targeting $T$ with information cutoff $o = T - 2$):

1. **Strict publication cutoff (`period <= T - 2`):** Features, lag statistics, rolling means/variances, provider encodings, and scalers must use **only** rows with `period <= o` ($o = T - 2$). Month $T - 1$ (unpublished) and month $T$ (target month) are strictly forbidden as predictors.
2. **No contemporaneous target-month covariates:** Target-month waiting times (`*_over_4hrs`, `dta_wait_*`), emergency admissions (`*_emergency_admissions`), booked attendances, Type 2/Other attendances, and national totals for months $T - 1$ or $T$ must never be used as features.
3. **Causal cohort selection:** Primary-cohort eligibility (`provisional_eligible`) is determined exclusively at $o = T - 2$ using $[o - 11, o]$. Future exits, future mergers, or future September 2026 eligibility must never retroactively drop or add historical providers in the primary cohort. (Step 3's `sensitivity_eligible` cohort is strictly a secondary retrospective robustness benchmark.)
4. **No imputation of missing targets or dissolved providers:** If a provider is eligible at $o = T - 2$ (e.g., `RAP` at `2024-11` or `2024-12`) and ceases reporting before $T$ (`2025-01`, `2025-02`), its target at $T$ is `NULL` (`is_observed == False`) and must be excluded from scoring rather than set to zero.
5. **No provenance or identifier leakage:** `source_month`, `source_file`, `source_sha256`, `source_record_number`, `source_period`, and national aggregate totals (`ae_national_final.csv`) are prohibited as model predictors.
6. **Reporting-time vs. retrospective dataset distinction:**
   - **Reporting-time knowledge at $d_T$:** Published observations for `period <= T - 2`, provider names/codes recorded up to $T - 2$, and deterministic calendar features of $T$.
   - **Retrospective knowledge present in M06 (forbidden in primary features/filtering):** Observations in months $\ge T - 1$, future trust mergers/dissolutions (`RA4`, `RVY`, `RAP`, `RVJ`), full-period continuity flags (`material_continuity_concern`), and post-publication statistical revisions.

---

## 5. Worked Historical Forecast Examples

| # | Decision Date ($d_T$) | Latest Report Available ($o = T - 2$) | Unpublished Month ($T - 1$) | Target Month ($T$) | Eligible-History Cutoff $[o - 11, o]$ | Eligible Providers at $o$ (Primary / Sensitivity) | Target Evaluable in Frozen M06? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **1 (2023)** | `2023-06-30` | **`2023-05`** (published `2023-06-08`) | `2023-06` (published `2023-07-13`) | **`2023-07`** | `2022-06` – `2023-05` | `123` / `109` | **Yes (`122` observable, `1` absent):** `RVY` merged into `RBN` on `2023-07-01` so `RVY` has no `2023-07` observation (excluded from scoring, not zeroed). |
| **2 (2024/25)** | `2024-12-31` | **`2024-11`** (published `2024-12-12`) | `2024-12` (published `2025-01-09`) | **`2025-01`** | `2023-12` – `2024-11` | `122` / `109` | **Yes (`121` observable, `1` absent):** `RAP` merged into `RAL` on `2025-01-01`; `RAP` was still eligible at `2024-11` under causal rules, and its absent `2025-01` target is excluded from scoring. |
| **3 (2025)** | `2025-09-30` | **`2025-08`** (published `2025-09-11`) | `2025-09` (published `2025-10-09`) | **`2025-10`** | `2024-09` – `2025-08` | `121` / `109` | **Yes (`121` observable, `0` absent):** All `121` eligible providers reported in `2025-10`. |
| **4 (2026 Boundary)** | `2026-09-30` | **`2026-08`** (published `2026-09-10`) | `2026-09` (published `2026-10-08` NHSE / `2026-10-09` GOV.UK) | **`2026-10`** (published `2026-11-12`) | `2025-09` – `2026-08` | `120` / `109` | **No (outside frozen M06):** `2026-10` is beyond the frozen `2022-01`–`2026-09` M06 dataset; illustrates an operational live forecast origin. |

*(Note: For the last fully evaluable decision date inside frozen M06, `2026-08-31` predicts `2026-09` from latest report `2026-07` published `2026-08-13`, with `120` eligible providers and `120` observable targets.)*

---

## 6. Known Limitations and Revision Disclosure

1. **Post-revision snapshot vs. point-in-time vintage data:**
   - NHS England publishes scheduled revisions approximately every six months (typically May and November) and replaces monthly files in place on its portal.
   - In our frozen `data/raw/` baseline (`57` CSVs), **`43` files are revised releases** (`2022-01` through `2026-03` mostly revised on `2022-05-12`, `2023-05-11`, `2024-06-13`, `2024-11-14`, `2025-05-15`, `2025-11-13`, and `2026-05-14`), while **`14` files** (including `2026-04`–`2026-09`, captured before NHS England's `2026-11-12` semi-annual revision) are unrevised initial releases.
   - **Handling and disclosure:** Because historical initial-vintage CSVs are not preserved on NHS England's archive, historical backtesting uses the frozen M06 dataset as a **publication-lag-aligned retrospective benchmark** rather than a true real-time vintage archive. All downstream modelling reports must disclose that revised historical figures may differ slightly from numbers originally published on each historical decision date.
2. **Unverified early 2022–2023 publication dates:** Five early reporting months (`2022-02`, `2022-03`, `2022-07`, `2022-12`, `2023-01`) had bulk GOV.UK backfill timestamps (`2023-03-02`) and no preserved NHS England monthly commentary upload timestamps. They are explicitly flagged as `UNVERIFIED_GOVUK_BACKFILL` in [docs/publication_availability.csv](publication_availability.csv); because the first eligible forecast origin is `2022-12` (decision date `2023-01-31` $\to$ target `2023-02`), these five early months affect only initial 2022 burn-in history and do not affect the `T - 2` availability rule for any 2023–2026 decision date.
3. **1-day GOV.UK vs. NHS England listing offset (`2026-09`) and late GOV.UK pointers (`2025-07`, `2026-01`):** NHS England's own portal is the primary release venue (always Thursday 09:30 UK time, day 8–16 of $m + 1$); GOV.UK pointers occasionally lagged NHS England. This has zero effect on the end-of-month decision rule ($d_T$ is always $\ge 14$ days after release of $T - 2$).
4. **Scope boundary:** No features, target labels, chronological train/validation/test splits, or models have been implemented in this step.
