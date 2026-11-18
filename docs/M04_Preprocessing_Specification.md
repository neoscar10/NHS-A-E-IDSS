# M04 | Preprocessing specification

**Source:** [NHS A&E IDSS repository](https://github.com/neoscar10/NHS-A-E-IDSS), M01 inventory and M02 combined records. The actual reporting and source fingerprints are captured in the generated evidence manifest.

| Rule | Method | Rationale |
|---|---|---|
| Source integrity | Compare every raw file fingerprint with the M01 manifest; rerun M03 | Avoid standardising changed or invalid inputs |
| Reporting period | Derive a month-start date from source_month; retain original source_period | A common temporal key without fabricating attendance dates |
| Fields | Explicit source-to-output name mapping | Readable, stable schema |
| Identifiers | Trim outer whitespace; uppercase organisation code only | Consistent key representation, not cross-organisation matching |
| Counts | Exact integer conversion, reject invalid representations | Preserve published activity; avoid rounding or imputing |
| National totals | Separate using the existing M03 rule | Prevent provider-level double counting while retaining published benchmarks |
| Conservation | Compare all 18 measures in provider and aggregate populations; reconcile monthly totals | Demonstrate that no numerical activity has been lost |
| Reported zeros | Preserve unchanged | A reported zero is not an absent provider-month |
| Missing periods and anomalous observations | Preserve and investigate at M05 | Avoid unsupported gap filling, outlier removal or historical merging |

The processed schema contains 27 fields: month-start period, 22 renamed source columns (including original period text), and four unchanged provenance fields. Its intended provider grain is one organisation code per reporting month. This is a standardised dataset, not a training or test cohort. Later eligibility decisions and feature creation must be time-aware and avoid future information. No method claims to identify organisational mergers from formatting changes alone.
