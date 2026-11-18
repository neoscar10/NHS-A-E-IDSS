# M04 | Cleaning and standardisation

## Objective
Create a typed provider-month dataset while preserving source counts and national totals.

## Results
- 11,449 input records became 11,392 provider records and 57 national records. No source records were discarded.
- 57 reporting months; 18 of 18 measures conserved in both row groups.
- 4,426 provider records with zero Type 1 activity retained.
- Fresh M03 validation passed its implemented core checks.

## Interpretation and decision
The national aggregate is a separate grain, not a provider. Separating it prevents double-counting while retaining a benchmark. Date and identifier formatting establish a consistent key, not proof that organisations are historically comparable. Zeros are reported values, not missing records. No gap filling, provider merging, outlier removal, model training or cohort restriction has been performed. M05 must investigate provider continuity, service eligibility and gaps before feature engineering.

Source: https://github.com/neoscar10/NHS-A-E-IDSS (local M02 staged export; fingerprint in summary).
