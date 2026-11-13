# Full dataset validation report

## Execution

- Dataset: full synthetic configuration, seed `20261022`.
- Environment: project `.venv`, Python 3.13.3, SQLite.
- Command: `flask --app app validate-data`.
- Result: **PASS** — 13 check groups, 0 failures; 645,931 record/check evaluations.

## Generated volumes

| Entity/table | Rows |
|---|---:|
| Employees | 5,000 |
| Roles | 15 |
| Skills | 300 |
| RoleSkill | 151 |
| EmployeeSkill | 34,627 |
| Projects | 500 |
| DemandPlan | 9,023 |
| DemandImportEvent | 9,024 |
| Allocation | 4,226 |
| Availability | 60,000 |
| Training | 936 |
| GapAnalysis | 91 |
| AnomalyGroundTruth | 4 |

Demand has 52 distinct, consecutive weekly periods from 2026-01-01 through 2026-12-24.

## Checks

Primary-key uniqueness, deterministic identifier formats, foreign-key integrity, date ordering/allocation validity, skill date ordering, availability/capacity reconciliation, allowed enumerations, duplicate business keys, demand validity/horizon, demand aggregation, utilization calculations, lifecycle transition audit rules, and injected anomaly detection all passed.

The lifecycle check found no transition records in generated data; its invalid-edge behavior is covered by a unit test. Expected anomaly cases are not counted as ordinary data-integrity failures.

## Anomaly evaluation

| Issue | Affected record | Result |
|---|---|---|
| Allocation exceeds availability | `ALLOC-2026-004224` | Detected and matched |
| Stale skill treated as current | `EMP-000001-SKL-000003` | Detected and matched |
| Duplicate demand import | `DME-DUP-00000001` | Detected and matched; demand counted once |
| Overlapping projects | `ALLOC-2026-004226` | Detected and matched |

**Ground-truth match rate: 4/4. Additional unexpected findings: 0.**

Machine-readable results: [validation_report.json](./validation_report.json).

## Test evidence and limitations

The Pytest suite covers generator volumes/IDs/horizon, SQLite foreign keys, validations, utilization, demand-backed gap/recommendation traceability, all four anomalies, forecast metrics/future output, reproducibility, dashboard routes, and lifecycle transition rejection. **Final targeted suite: 10 passed.**

Validation ran under Python 3.13.3, not Python 3.12 (not installed locally). PostgreSQL and Render deployment were not exercised against a hosted service.
