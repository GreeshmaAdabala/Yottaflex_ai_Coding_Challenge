# Business rules and assumptions

## Demand and capacity

- The default horizon starts on 2026-01-01 and contains 52 consecutive 7-day periods. Project demand is generated only while the project is in its effective dates.
- Each weekly `DemandPlan` is the unique planned requirement for its project/role/skill/week. A repeated import event is ingestion evidence, not a second plan, so aggregation counts each `demand_id` once.
- Employee weekly capacity comes from contracted hours (full-time or part-time). Monthly `Availability` records translate that schedule into weekdays and subtract generated leave. Effective capacity is never negative.
- Allocation rows store weekly hours and effective dates. Multiple non-overlapping assignments are preserved; the anomaly dataset adds a separately labelled over-capacity assignment and a distinct overlapping pair.
- Utilization below 50% is underutilized; 50–100% inclusive is normally utilized; above 100% is overutilized. These thresholds are analytical conventions, not HR policy.

## Skill currency and gaps

- Proficiency is ordinal 1–5. A skill is current at a demand date only if its status is `verified`, its expiry is not before the demand period, and its last verification is within 365 days.
- Candidate coverage is role-aligned, proficiency-qualified, current, and has remaining weekly capacity after assignments and a proportional leave adjustment.
- A skill gap is recorded for a demand row when qualified available employees are fewer than required headcount. The output prioritizes stale verification, proficiency, missing skill, then capacity as the gap explanation.
- Gap results are persisted for the first eight weeks and may be recalculated for other windows. Recommendations are only generated from actual demand-backed gaps.
- Recommendation type follows evidence: hire when the role has no matching skill holders, train when skill holders fall below proficiency, reverify when only stale profiles match, and reassign when qualified capacity is committed.

## Forecasting

- Synthetic weekly `DemandPlan` values are the historical planning series in this demo; they are not actual observed data.
- Evaluation uses chronological training and holdout periods; no random split is used. Models use week index/seasonality and the role, skill, project, or group identifiers.
- The baseline is the trailing four-week moving average. The secondary model is a seeded scikit-learn Random Forest regressor.
- MAE, RMSE and WAPE are reported for the same holdout. WAPE is 0 when both total actual demand and total error are zero.
- Future predictions assume that generated patterns continue and do not anticipate project cancellations, economic shifts, or new project intake. Model superiority is never asserted except through the measured metric comparison.

## Anomalies and validation

- Four anomaly cases are injected after baseline records: allocated hours above employee weekly capacity, stale skill evidence still marked verified, duplicate demand import source reference, and overlapping assignments to distinct projects.
- Baseline entities are retained. Ground-truth records live in a separate table and CSV/JSON exports. Detectors inspect only operational data; validation joins labels only after detection.
- Expected labelled anomalies are reported separately from unexpected relational or rule failures.

## Data generation

- Python `random.Random` and Faker use seed `20261022`. Names/client labels are fictional Faker-generated values.
- Dataset: 5,000 employees, 300 skills, 500 projects.
- Baseline project allocation collisions are avoided; the labelled overlap case is intentionally separate.
