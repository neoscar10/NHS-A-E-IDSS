# Provider Continuity Review Report

**Accepted M06 Dataset:** `.work/rebuild/data/processed/m06/20261121T204848Z_03520dac/ae_provider_calendar_final.csv`  
**SHA-256:** `16500cdcd05cb1cd4cac4e8b6b973c5586770696c2cf115f5157b9051a146aef`  
**Scope:** All `223` provider codes across `57` reporting months (`2022-01` to `2026-09`)  
**Machine-readable table:** [docs/provider_continuity_review.csv](provider_continuity_review.csv)

---

## 1. Executive Summary

Across all `223` distinct NHS provider codes in the M06 calendar:
- `125` codes recorded at least one positive Type 1 attendance; `124` qualified as provisional forecasting candidates (`5,599` origins). Only `RBZ` (3 observed months before merging into `RH8`) had positive Type 1 activity without ever reaching the 12-month history threshold.
- `98` codes recorded exclusively zero Type 1 attendances (`0` eligible origins).
- `0` codes had mixed zero-and-positive Type 1 histories, and `0` codes had `parent_org` (NHS England region) variations.
- **All `12` internal-gap providers** identified by M05 are non-Type-1 providers (`0` positive Type 1 attendances, `0` eligible origins).
- **Of the `18` name-variant providers** identified by M05, `13` are in the provisional eligible cohort (`3` acute mergers, `2` acute-community mergers with stable Type 1 volume, `7` simple title/name rebrands, and `1` title rebrand `RWD` with a separate unresolved Type 1/Other step shift) and `5` are non-Type-1 providers (`0` eligible origins).
- **Beyond the M05 name-variant list**, continuity screening identified **2 silent acute-to-acute mergers with no name change** (`RA4 -> RH5` and `RAP -> RAL`) and **5 additional unresolved Type 1 $\leftrightarrow$ Other A&E step changes** (`RXN`, `RVV`, `RTR`, `RJL`, `RTK`), plus `RWD` (`6` unresolved step-change trusts total).

No provider codes were merged, renamed, or removed from the main provisional cohort. Cases with material Type 1 structural breaks (`15` eligible providers, `585` origins) are flagged for review and excluded only in the companion sensitivity cohort (`109` providers, `5,014` origins).

---

## 2. Verified Acute-to-Acute Type 1 Trust Mergers (Material Structural Breaks)

All five acute Type 1 mergers in England during `2022-01` – `2026-09` are corroborated by both public NHS merger records and arithmetic conservation across the pre- and post-merger 3-month Type 1 means:

| Effective Date | Dissolved Code (Eligible Origins) | Absorbing Code (Eligible Origins) | Absorbing Name Change? | Pre-3m Sum (Dissolved + Absorber) | Post-3m Absorber Mean | Post / Pre Sum Ratio | Absorber Step | Primary Public Source |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `2022-04-01` | `RBZ` Northern Devon Healthcare (0; ended `2022-03`) | `RH8` Royal Devon University Healthcare (46) | Yes (`2022-04`) | 3,887 + 6,796 = 10,683 | 11,686 | 1.094 | +72.0% | NHS England / ODS merger records (`RBZ -> RH8`) |
| `2023-04-01` | `RA4` Yeovil District Hospital (4; ended `2023-03`) | `RH5` Somerset NHS FT (46) | **No** | 5,181 + 6,247 = 11,428 | 12,424 | 1.087 | +98.9% | Somerset NHS FT / NHS Digital ODS (`RA4 -> RH5`) |
| `2023-07-01` | `RVY` Southport & Ormskirk (7; ended `2023-06`) | `RBN` Mersey & West Lancashire Teaching (46) | Yes (`2023-07`) | 7,392 + 9,812 = 17,204 | 16,868 | 0.981 | +71.9% | GOV.UK / NHS Digital ODS (`RVY -> RBN`) |
| `2025-01-01` | `RAP` North Middlesex Univ. Hospital (25; ended `2024-12`) | `RAL` Royal Free London NHS FT (46) | **No** | 8,536 + 17,778 = 26,314 | 24,456 | 0.929 | +37.6% | NHS England / CQC (`RAP -> RAL`) |
| `2026-07-01` | `RVJ` North Bristol NHS Trust (43; ended `2026-06`) | `RA7` Bristol NHS FT (46) | Yes (`2026-07`) | 9,664 + 16,130 = 25,794 | 25,740 | 0.998 | +59.6% | Bristol NHS FT / NBT & UHBW (`RVJ -> RA7`) |

**Modelling implication:** Every one of the four post-2022 step-downs in monthly eligible provider counts (`124 -> 123 -> 122 -> 121 -> 120`) corresponds directly to one of these mergers (`RA4`, `RVY`, `RAP`, `RVJ`). For the five absorbing trusts (`RH8`, `RH5`, `RBN`, `RAL`, `RA7`), historical lag features in the 12 months immediately after merger straddle pre- and post-merger organisational footprints. Notably, `RH5` and `RAL` had **no trust name change**, demonstrating why name-variant checks alone are insufficient.

---

## 3. Complete Review of the 18 M05 Name-Variant Providers

| Code | Eligible Origins | Change Month | Recorded Names | Classification | Type 1 Pre-3m $\to$ Post-3m | Action |
| --- | ---: | --- | --- | --- | --- | --- |
| `RH8` | 46 | `2022-04` | Royal Devon and Exeter $\to$ Royal Devon University Healthcare NHS FT | Verified acute merger (`RBZ -> RH8`) | 6,796 $\to$ 11,686 (+72.0%) | Flagged; excluded in sensitivity |
| `RBN` | 46 | `2023-07` | St Helens and Knowsley $\to$ Mersey and West Lancashire Teaching Hospitals | Verified acute merger (`RVY -> RBN`) | 9,812 $\to$ 16,868 (+71.9%) | Flagged; excluded in sensitivity |
| `RA7` | 46 | `2026-07` | University Hospitals Bristol and Weston $\to$ Bristol NHS FT | Verified acute merger (`RVJ -> RA7`) | 16,130 $\to$ 25,740 (+59.6%) | Flagged; excluded in sensitivity |
| `RAX` | 46 | `2024-11` | Kingston Hospital $\to$ Kingston and Richmond NHS FT | Verified acute + community merger (`RY9 -> RAX`, eff. `2024-11-01`; `RY9` had 0 Type 1) | 6,859 $\to$ 7,356 (+7.2%) | Retained in both cohorts |
| `RWW` | 46 | `2026-04` | Warrington and Halton Teaching $\to$ North Cheshire and Mersey NHS FT | Verified acute + community merger (`RY2 -> RWW`, eff. `2026-04-01`; `RY2` had 0 Type 1; `other_attendances` rose +128.6%) | 6,569 $\to$ 6,961 (+6.0%) | Retained in both cohorts |
| `RWD` | 46 | `2024-11` | United Lincolnshire Hospitals $\to$ United Lincolnshire Teaching Hospitals | Simple teaching-status rename in `2024-11`, **but** separate unresolved Type 1/Other step shift in `2025-01` (Section 4) | 10,825 $\to$ 15,629 (+44.4% at `2025-01`) | Flagged (`review_required`); excluded in sensitivity |
| `RA2` | 46 | `2025-09` | Royal Surrey County Hospital $\to$ Royal Surrey NHS FT | Simple name variation (rebrand) | 6,612 $\to$ 6,844 (+3.5%) | Retained in both cohorts |
| `RHU` | 46 | `2025-04` | Portsmouth Hospitals University National Health Service $\to$ ...NHS Trust | Simple name variation (abbreviation) | 10,220 $\to$ 10,255 (+0.3%) | Retained in both cohorts |
| `RJC` | 46 | `2022-09` | South Warwickshire $\to$ South Warwickshire University NHS FT | Simple name variation (university title) | 7,185 $\to$ 7,451 (+3.7%) | Retained in both cohorts |
| `RQX` | 46 | `2022-04` | Homerton University Hospital $\to$ Homerton Healthcare NHS FT | Simple name variation (rebrand) | 9,555 $\to$ 10,413 (+9.0%) | Retained in both cohorts |
| `RRF` | 46 | `2026-01` | Wrightington, Wigan and Leigh $\to$ ...Teaching Hospitals NHS FT | Simple name variation (teaching title) | 8,098 $\to$ 6,848 (-15.4%, seasonal Jan dip) | Retained in both cohorts |
| `RWH` | 46 | `2025-09` | East and North Hertfordshire $\to$ ...Teaching NHS Trust | Simple name variation (teaching title) | 8,612 $\to$ 9,096 (+5.6%) | Retained in both cohorts |
| `RXF` | 46 | `2023-05` | Mid Yorkshire Hospitals $\to$ Mid Yorkshire Teaching NHS Trust | Simple name variation (teaching title) | 15,016 $\to$ 17,020 (+13.3%) | Retained in both cohorts |
| `A5D4Q` | 0 | `2025-07` | NEMS UTC $\to$ NEMS CBS (UTC) | Non-Type-1 provider (all zero Type 1) | 0 $\to$ 0 | Excluded by provisional rule |
| `NNJ15` | 0 | `2026-04` | Oakham $\to$ Rutland Minor Illness & Injury Service (formerly WLHH) | Non-Type-1 provider (all zero Type 1) | 0 $\to$ 0 | Excluded by provisional rule |
| `RW1` | 0 | `2024-10` | Southern Health $\to$ Hampshire & Isle of Wight Healthcare NHS FT | Non-Type-1 community/MH merger (all zero Type 1) | 0 $\to$ 0 | Excluded by provisional rule |
| `RXG` | 0 | `2026-07` | South West Yorkshire Partnership $\to$ ...Teaching NHS FT | Non-Type-1 provider (all zero Type 1) | 0 $\to$ 0 | Excluded by provisional rule |
| `Y02428` | 0 | `2023-05` | Putnoe Medical Centre Walk In Centre $\to$ Putnoe Walk In Centre | Non-Type-1 provider (all zero Type 1) | 0 $\to$ 0 | Excluded by provisional rule |

---

## 4. Unresolved Material Type 1 vs. Other A&E Step Changes (`review_required`)

M03's exploratory change screen (`>= 2,000` absolute and `>= 100%` relative MoM change) flagged `0` rows (`docs/m03_type1_change_candidates.csv` is empty). Screening at a persistent 3-month shift threshold (`|MoM diff| >= 1,500`, `|MoM rel| >= 25%`, and `|3m step| >= 24%`) identified **6 non-merger eligible trusts** with large, sustained shifts between `type1_attendances` and `other_attendances` while combined total A&E attendance stayed comparatively stable:

| Code | Trust Name | Shift Month | Type 1 Pre-3m $\to$ Post-3m | Other A&E Pre-3m $\to$ Post-3m | Total A&E Pre-3m $\to$ Post-3m | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `RXN` | Lancashire Teaching Hospitals NHS FT | `2022-08` | 6,623 $\to$ 11,493 (+73.5%) | 8,852 $\to$ 3,669 (-58.6%) | 15,475 $\to$ 15,162 (-2.0%) | Unresolved (`review_required`) |
| `RVV` | East Kent Hospitals University NHS FT | `2023-02` | 18,118 $\to$ 11,453 (-36.8%) | 5,648 $\to$ 11,329 (+100.6%) | 23,766 $\to$ 22,783 (-4.1%) | Unresolved (`review_required`) |
| `RTR` | South Tees Hospitals NHS FT | `2024-04` | 10,261 $\to$ 7,774 (-24.2%) | 4,836 $\to$ 9,249 (+91.3%) | 15,098 $\to$ 17,023 (+12.8%) | Unresolved (`review_required`) |
| `RJL` | Northern Lincolnshire and Goole NHS FT | `2024-05` | 15,116 $\to$ 8,994 (-40.5%) | 163 $\to$ 6,729 | 15,279 $\to$ 15,723 (+2.9%) | Unresolved (`review_required`) |
| `RWD` | United Lincolnshire Teaching Hospitals | `2025-01` | 10,825 $\to$ 15,629 (+44.4%) | 9,843 $\to$ 3,610 (-63.3%) | 20,668 $\to$ 19,239 (-6.9%) | Unresolved (`review_required`) |
| `RTK` | Ashford and St Peter's Hospitals NHS FT | `2025-04` | 10,014 $\to$ 7,061 (-29.5%) | 0 $\to$ 4,817 | 10,014 $\to$ 11,878 (+18.6%) | Unresolved (`review_required`) |

These patterns are characteristic of Urgent Treatment Centre (UTC) streaming or ECDS department-type coding changes rather than sudden population-level demand shocks. Because authoritative local service-reclassification records are not present in this repository, all six are retained unchanged in the main provisional cohort and excluded in the sensitivity cohort.

---

## 5. Complete Review of the 12 M05 Internal-Gap Providers

All `12` provider codes with internal reporting gaps (`30` internal gap rows total) recorded **zero Type 1 attendances** in every observed month (`0` provisional eligible origins). Verification confirmed that every internal gap correctly sets `history_ready = False` and `candidate_status = "Insufficient consecutive history"` upon resumption until 12 consecutive observed months are rebuilt:

| Code | Recorded Name | Span | Observed | Internal Gaps | Gap Months | Type 1 Positive Months | Eligible Origins |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: |
| `RAT` | North East London NHS FT | `2022-01` – `2026-09` | 47 | 10 | `2024-03` .. `2024-12` | 0 | 0 |
| `RYG` | Coventry and Warwickshire Partnership | `2022-01` – `2026-09` | 49 | 8 | `2022-08` .. `2023-03` | 0 | 0 |
| `RET` | The Walton Centre NHS FT | `2022-01` – `2026-09` | 55 | 2 | `2024-01`, `2024-09` | 0 | 0 |
| `RNU` | Oxford Health NHS FT | `2022-01` – `2026-09` | 55 | 2 | `2022-08`, `2022-09` | 0 | 0 |
| `AAH` | Tetbury Hospital Trust Ltd | `2022-01` – `2026-09` | 56 | 1 | `2022-04` | 0 | 0 |
| `AD913` | Beckenham Beacon UCC | `2022-01` – `2026-09` | 56 | 1 | `2022-08` | 0 | 0 |
| `C82009` | Market Harborough Med. Ctr | `2022-01` – `2026-09` | 56 | 1 | `2025-05` | 0 | 0 |
| `NDA57` | Haslemere Minor Injuries Unit | `2022-01` – `2023-12` | 23 | 1 | `2022-07` (+33 trailing absent) | 0 | 0 |
| `NNJ` | DHU Health Care C.I.C | `2022-01` – `2026-09` | 56 | 1 | `2022-08` | 0 | 0 |
| `NNJ10` | Enderby Leisure Centre | `2026-03` – `2026-09` | 6 | 1 | `2026-04` | 0 | 0 |
| `NNJ11` | Lutterworth Hospital | `2026-03` – `2026-09` | 6 | 1 | `2026-04` | 0 | 0 |
| `RWX` | Berkshire Healthcare NHS FT | `2022-01` – `2026-09` | 56 | 1 | `2022-08` | 0 | 0 |

---

## 6. Cohort Comparison Summary

| Cohort | Distinct Providers | Eligible Origins | Monthly Range (`2022-12`–`2026-09`) | Role in Modelling |
| --- | ---: | ---: | --- | --- |
| **Main Provisional Cohort** (`provisional_eligible`) | 124 | 5,599 | 120 – 124 / month | Primary, strictly causal modelling cohort (all continuity cases retained) |
| **Sensitivity Cohort** (`sensitivity_eligible`) | 109 | 5,014 | 109 / month (constant) | Retrospective sensitivity benchmark excluding 15 providers (9 acute-merger + 6 unresolved Type 1/Other step-change codes) |
