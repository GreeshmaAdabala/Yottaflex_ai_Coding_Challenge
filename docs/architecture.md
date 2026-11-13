# System architecture

## Components and data flow

```text
Faker + seeded random.Random
            |
            v
generator/generate_data.py -----> SQLAlchemy models / SQLite
            |                              |
            |                              +--> demand + allocation + availability
            |                              +--> independent anomaly ground truth
            v
exports/export_data.py                    modules/analysis.py
  CSV / JSON / SQLite SQL dump                 |-- utilization
                                               |-- skill gaps / recommendations
                                               |-- anomaly detector
                                                    |
                                                    v
                                      modules/forecasting.py
                                      moving average + Random Forest
                                                    |
                                                    v
                                  Flask routes -> Jinja -> Plotly dashboard
                                                    |
                                                    v
                                      validation/ and pytest
```

## Runtime shape

- `app.py` builds the Flask application, registers routes and CLI commands, and creates the schema. A new local SQLite database is seeded with the starter configuration by default.
- `database/models.py` is the canonical schema. `database/db.py` enables SQLite foreign-key enforcement on every connection.
- `generator/generate_data.py` creates parent/master entities first, then dependent rows, anomaly injection evidence, and separate ground-truth labels. The generator accepts dataset sizes, seed, horizon, and reset behavior.
- `modules/analysis.py` computes capacity and demand-backed skill gaps, builds recommendations from those gaps, and detects anomalies without reading ground-truth labels.
- `modules/forecasting.py` aggregates demand by role, project, or skill; trains on earlier weeks; evaluates the later holdout; and produces future weekly predictions.
- `validation/validate.py` reports integrity checks and evaluates injected cases against ground truth after detection. `validation/reproducibility.py` builds two isolated databases and compares row counts, IDs, exports, ground truth, and calculations.
- `exports/export_data.py` exports the ten core tables to CSV/JSON, the separate anomaly truth set, a SQLite SQL dump, and a source manifest.
- `templates/` and `static/` provide the responsive server-rendered dashboard. The application serves Plotly's JavaScript locally from the installed package rather than depending on a chart CDN.

## Entity relationships

- `Role` 1—many `Employee`; `Role` many—many `Skill` through `RoleSkill`.
- `Employee` many—many `Skill` through `EmployeeSkill`.
- `Project` 1—many `DemandPlan` and `Allocation`.
- `Role` and `Skill` each 1—many `DemandPlan` records.
- `Employee` 1—many `Allocation`, `Availability`, and `Training`; `Skill` 1—many `Training`.
- `DemandPlan` 1—many `GapAnalysis` (one gap type per demand).
- `DemandPlan` 1—many `DemandImportEvent`. Duplicate source references represent repeated ingestion evidence; calculations count the unique demand-plan row, not repeated events.
- `AnomalyGroundTruth` stores labels separately from operational records. It is not referenced by detection or forecasting.
- `modules/lifecycle.py` audits ORM status changes for `Employee.status`, `Project.status`, `Training.status`, and the `lifecycle_state` fields on `Role` and `Skill`. It validates each transition against the allowed transition map and rejects invalid changes before flush. Valid changes persist a `status_transition` `AuditEvent` with entity type/ID, timestamp, and previous/new status details in the same transaction. Existing rows are not backfilled. Direct SQL and ORM bulk updates bypass these hooks and must not be used for audited lifecycle changes.

## Storage and deployment

SQLite is the default local database. Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL for Render or another PostgreSQL service; the schema uses portable SQLAlchemy types and checks. The complete SQL data dump is intentionally a SQLite export. No external API or hosted service is required for local operation.
