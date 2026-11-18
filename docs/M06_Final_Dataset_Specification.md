# M06 | Final dataset specification

## Objective
Produce a versioned analytical dataset suitable for subsequent time-aware feature engineering, with verified source continuity and explicit separation of provider records and national totals.

## Verification methodology
1. Select a completed M05 run and verify its summary and calendar fingerprints against its evidence manifest. Verify the declared Parquet fingerprint if present.
2. Load the exact M04 provider and national inputs recorded by M05, checking the earlier manifest and fingerprints.
3. Reconstruct the provider calendar and historical eligibility with the same history window. Compare the stored M05 calendar against the reconstruction at field level.
4. Compare observed provider records to M04, retaining every original field and numeric value. Ensure absent calendar rows have null measures and are not counted as zero attendance.
5. Reconcile every published numerical measure across each reporting month using exact integer arithmetic.
6. Export three separate datasets and verify CSV and, where supported, Parquet round trips. Record output fingerprints, code fingerprints, dependency versions and test results in a timestamped evidence snapshot.

## Acceptance criteria
- Complete M04 and M05 evidence records with matching fingerprints.
- One provider-month calendar row per organisation code and reporting month, from first observation through the final reporting month.
- Every observed provider row retained with unchanged published measures and traceability.
- One separate national total per reporting month and exact reconciliation of all 18 measures.
- Missing and reported-zero observations remain distinct.
- Provisional candidate flags reproduce M05 from information through each reporting month, without future outcome filtering.
- Successful regression tests and verified export formats. Inspect the evidence manifest and summary together before use.

## Analytical boundaries
No source values are imputed, clipped, scaled or otherwise altered. No provider is removed from the calendar. Organisation identifiers are not continuous measures. The final dataset is not a training matrix. M07 must construct time-aware features and target alignment, account for the publication lag and retrospective revisions, and avoid using future-derived information. Service status, historical identity changes and discontinuities remain contextual limitations.
