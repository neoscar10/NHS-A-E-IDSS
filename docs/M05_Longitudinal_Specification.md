# M05 | Longitudinal data specification

Source: [NHS A&E IDSS](https://github.com/neoscar10/NHS-A-E-IDSS), verified M04 outputs.

## Method

| Component | Definition |
|---|---|
| Calendar grain | One organisation code per calendar month, from its first reported observation to the end of the collection. |
| Observed record | Original M04 submission, all published counts preserved. |
| Absent record | Analytical calendar placeholder; counts, source metadata and provider attributes remain null. |
| Internal gap | Absent month between first and last observed records; retrospective diagnostic only. |
| Post-observation absence | Absent month after the last reported record; does not establish closure. |
| Recorded identity variation | Number of distinct observed names or parent groups; no automatic crosswalk. |
| History window | Default 12 consecutive calendar months ending at the reporting origin. |
| Provisional candidate | Observed origin, all 12 months observed, at least one positive Type 1 observation in that window. |

## Added calendar fields

| Field | Meaning |
|---|---|
| `is_observed` | True for actual M04 source records. |
| `observation_state` | Reported positive, reported zero, or absent record. |
| `observed_last_n_months` | Number of observed records in the trailing window, including the origin. |
| `positive_last_n_months` | Number of positive Type 1 observations within the trailing window. |
| `history_ready` | Whether the entire trailing window is observed. |
| `type1_candidate` | Provisional time-aware eligibility flag. |
| `candidate_status` | Mutually exclusive candidate, no recent positive activity, insufficient consecutive history, or no reported record. |
| `history_window_months` | Window length used for eligibility. |

## Implications for forecasting
The 12-month window supports a seasonal baseline and is a methodological choice, not an official NHS rule. Assess sensitivity using training history only. Historical names and gaps are descriptive and must not determine earlier membership using future information. A forecast and its evaluation require publication-aware feature availability, calendar-aligned targets and chronological splits. Do not treat calendar placeholders as targets or blindly use data-quality flags as model features. Candidate counts are not counts of evaluable forecast pairs.
