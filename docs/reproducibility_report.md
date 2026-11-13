# Full-run reproducibility report

- Seed: `20261022`
- Configuration: 5,000 employees, 300 skills, 500 projects, 52 weeks.
- Method: generate two isolated SQLite databases with the same configuration; compare table row counts, ordered primary-key SHA-256 values, detected ground-truth cases, derived gap output, and CSV/JSON/SQLite SQL export checksums.
- Result: **identical: true**.

## Compared table counts

| Table | Rows |
|---|---:|
| employees | 5,000 |
| roles | 15 |
| skills | 300 |
| role_skills | 151 |
| employee_skills | 34,627 |
| projects | 500 |
| demand_plans | 9,023 |
| demand_import_events | 9,024 |
| allocations | 4,226 |
| availability | 60,000 |
| trainings | 936 |
| gap_analyses | 91 |
| anomaly_ground_truth | 4 |
| audit_events | 0 |

Both runs detected the same four labelled anomaly entity IDs and produced 22 gaps in the four-week derived-calculation comparison window. CSV, JSON, source-manifest, and SQLite SQL export checksums matched; primary-key hashes for all listed tables matched.

