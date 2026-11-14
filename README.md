# YottaFlex Workforce Intelligence

A locally runnable workforce planning application for synthetic project demand, employee capacity, skill coverage, utilization, anomaly detection, forecasting, and explainable workforce recommendations.

## What it does

- Stores the ten required workforce entities in SQLAlchemy with SQLite foreign-key enforcement.
- Generates a reproducible 50/30/10 starter dataset or a 5,000/300/500 full dataset from seed `20261022`, including 52 weekly planning periods.
- Calculates effective capacity after part-time schedules and leave, assignment utilization, demand-backed skill gaps, and hiring/training/reverification/reassignment recommendations.
- Injects four labelled negative scenarios after baseline creation and keeps their ground-truth records separate from detector/model inputs.
- Compares a trailing moving-average baseline to a Random Forest using a chronological holdout and MAE, RMSE, and WAPE.
- Serves a responsive Flask dashboard from the actual database, including searchable employee/project lists, forecast views, utilization, gaps, recommendations, and anomaly checks.
- Exports ten core-table CSV/JSON files, a SQLite SQL dump, source manifest, and separate ground-truth CSV/JSON.

Synthetic demand is not actual observed demand. The dashboard and forecast output make this distinction explicit; the `actual_observed_demand` field remains null because no observed data was provided.

## Technology

Python 3.12+, Flask, SQLAlchemy/Flask-SQLAlchemy, SQLite (local) or PostgreSQL (optional), Pandas, NumPy, Faker, scikit-learn, Plotly, and Pytest. Dependencies are free and no external API is required.

## Architecture

See [architecture](docs/architecture.md), [data dictionary](docs/data_dictionary.md), and [business rules](docs/business_rules.md). `database/models.py` is the canonical schema; generator, analytics, forecasting, validation, exports, Flask routes, and templates are kept in separate modules.

## Documentation

- [User Guide](USER_GUIDE.md) – Step-by-step instructions for using the application.
## Project Resources
- [Application Screenshots](APPLICATION_SCREENSHOTS.md) – View all 14 application screenshots.
- [Pytest Cases and Screenshots](pytest%20cases/) – Test case evidence and screenshots.
- [Workforce Database](workforce.db) – SQLite database containing the project tables and synthetic workforce data.
 Workforce.db to review or to see the tables

## Project Demonstration Videos

The project demonstration videos are hosted on Google Drive because their large file sizes prevent them from being conveniently viewed directly on GitHub.

Both videos are available through the links below for reviewing the application workflow, functionality, and implementation.

1. **[Project Demonstration – Video 1](https://drive.google.com/file/d/1-Imae938pGDlSNlmE__5UWHqCsmAVu4Q/view?usp=drive_link)**
2. **[Project Demonstration – Video 2](https://drive.google.com/file/d/1xCafe2MpsxhjSohDMIZHPdk4TpF6YJPT/view?usp=drive_link)**


The application uses SQLite as its primary database for storing and managing workforce intelligence data.

- **SQLite Database (`workforce.db`):** The complete database is included in the repository and contains 14 tables with synthetic workforce data. The database file is approximately 17.5 MB.
- **Database Exports (`exports/`):** Contains exported data from all 14 database tables for convenient access and inspection.

**Data Accessibility:** The `exports/` folder provides an easy way to review and explore the data from all 14 tables individually, without downloading the complete SQLite database.

**Note:** GitHub does not display the contents of binary database files directly in the browser. The `workforce.db` file can be downloaded and inspected using an SQLite-compatible database viewer.
 
## Local setup (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Python 3.12+ is the target; this workspace was tested on Python 3.13.3. The application uses a local `workforce.db` SQLite file by default. Launching the application creates the schema and seeds the starter dataset if no employees exist:

```powershell
python app.py
```

Open <http://127.0.0.1:5000>. Plotly's JavaScript is served by the application itself; no hosted chart library is needed.

## Dataset generation

```powershell

# Full: 5,000 employees, 300 skills, 500 projects; 
flask --app app seed-data --full --reset
```

The default horizon starts on 2026-01-01 and contains 52 consecutive weekly periods. Supply `HORIZON_START` and `HORIZON_WEEKS` to configure the planning window. The generator creates parent records before dependent records, uses immutable IDs, and rejects a second generation unless `--reset` is specified. The four injected scenarios are preserved alongside the baseline and receive a separate `AnomalyGroundTruth` record.

The ID patterns are `EMP-000001`, `SKL-000001`, `PRJ-2026-000001`, `DEM-PRJ-2026-000001-2026W01`, and `ALLOC-2026-000001`. Demand week suffixes use the ISO year/week of the period start.

## Business calculations

- **Capacity:** contracted weekly hours are converted to monthly weekday capacity; recorded leave is subtracted. Part-time employees use their own contracted hours.
- **Utilization:** allocated hours / effective available capacity × 100. Partial periods prorate monthly availability by overlapping calendar days and weekly allocation hours by overlapping days ÷ 7. A zero-capacity period returns 0% and avoids division by zero.
- **Classification:** below 50% is underutilized; 50–100% is normally utilized; above 100% is overutilized.
- **Skill validity:** verified proficiency must meet the demand requirement; expiry must not precede the demand period; last verification must be within 365 days.
- **Skill gaps:** only project demand records with fewer qualified and available people than required can create gaps/recommendations. Each gap stores its `demand_id`.
- **Forecasting:** the first 80% of weekly dates are training data and the later dates form the holdout. The Random Forest is seeded; the moving average uses up to four preceding weekly observations. No performance advantage is assumed without the calculated metrics.

## Lifecycle audit

ORM status changes for `Employee.status`, `Project.status`, `Training.status`, and the `lifecycle_state` fields on `Role` and `Skill` are checked against the allowed transition map in `modules/lifecycle.py`. A disallowed transition raises `InvalidStatusTransition` before the flush. Each valid persisted change creates a `status_transition` `AuditEvent` in the same transaction, with entity type/ID, UTC event time, and JSON details containing the previous status, new status, and field name. New records do not create transition events, and existing records are not backfilled. Bulk SQL updates bypass ORM event hooks and should not be used for lifecycle status changes.

## CLI and verification

```powershell
flask --app app validate-data
flask --app app forecast-evaluation --dimension all
flask --app app export-data
flask --app app check-reproducibility
python -m pytest
```

`validate-data` writes `docs/validation_report.json`; the accompanying [validation summary](docs/validation_report.md) records the verified run. `check-reproducibility` generates the same configuration independently in two isolated temporary databases. The `--full` option uses 5,000 employees, 300 skills, 500 projects, 52 weeks, and seed `20261022`. It compares counts and primary-key hashes for all entities, derived skill-gap and workforce-utilization calculations, expected versus detected anomalies, and CSV/JSON/SQL export checksums. Its report is written to `docs/reproducibility_report.json`; see the [reproducibility summary](docs/reproducibility_report.md). The reproducibility runs themselves use temporary database and export directories. Because Flask initializes its configured app database at startup, use an in-memory URL for a CLI verification that must not touch the configured database:

```powershell
$env:DATABASE_URL = "sqlite://"
$env:AUTO_SEED = "false"
flask --app app check-reproducibility --full
Remove-Item Env:DATABASE_URL, Env:AUTO_SEED
```

Verification on 2026-11-12, using the in-memory CLI setup above: full reproducibility returned `identical: true`; all five comparison groups matched. Full-data validation through a read-only SQLite connection passed all 13 checks, including primary-key uniqueness and foreign-key integrity, detected all 4 expected anomalies, and found 0 unexpected anomalies. `python -m pytest -q` passed all 12 tests. The original database and all 27 files under `exports/` retained their pre-verification fingerprints.

Exports are created under `exports/csv/`, `exports/json/`, `exports/sql/`, and `ground_truth/`. Core CSV/JSON names correspond to the ten core tables. `exports/sql/workforce_dump.sql` is a SQLite schema-and-seed-data dump. Generated files can be recreated after a reset.

## Optional Render / PostgreSQL deployment

The repository includes a Render blueprint. Configure `DATABASE_URL` with the PostgreSQL connection string from Render and run `flask --app app seed-data --full --reset` once as a deployment/one-off command to populate full synthetic data. PostgreSQL support requires the declared `psycopg` driver. The SQL dump exporter is SQLite-specific; PostgreSQL database export should use the provider's own backup tooling.

For a manual Render web service, use:

- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app`

Do not commit credentials; use Render environment variables. `SECRET_KEY` should be set to a deployment-specific secret.

## Limitations and assumptions

- All workforce data is synthetic. It must not be interpreted as a real staffing forecast.
- The generated horizon is a weekly planning series, not an actual-demand history. Project/role/skill forecasts are a prototype and do not account for external economic indicators, cancellations, or changing project scope.
- Recommendation thresholds and skill verification age are explicit demo assumptions, not organizational policy.
- Data volume and model runtime vary by machine; the full configuration is more resource-intensive than the starter configuration.
- PostgreSQL schema support is provided, but validation/reproducibility and generated SQL dump workflows are primarily exercised with local SQLite.
- Supplied requirements and PDF references are input-only and are excluded from the final project folder/repository.


