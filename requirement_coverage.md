# Requirement coverage

Implementation and verification status at completion. "Verified" means exercised in this workspace; it does not claim that the candidate personally reviewed the work.

| Requirement | Implementation | Status |
|---|---|---|
| Flask, SQLAlchemy, SQLite, Pandas, NumPy, Faker, scikit-learn, Plotly, Pytest | `requirements.txt`, application modules | Verified dependencies installed; tests run on local Python 3.13.3 |
| Ten core entities and documented constraints/relationships | `database/models.py`, `docs/data_dictionary.md` | Verified by schema creation, FK checks, and tests |
| SQLite foreign-key enforcement and optional PostgreSQL URL | `database/db.py`, `app.py` | SQLite verified; PostgreSQL URL normalization tested; no live PostgreSQL service available |
| Starter (50/30/10) and full (5,000/300/500) generation, seed 20261022 | `generator/generate_data.py`, `flask seed-data` | Existing full dataset verified without regeneration: 5,000 employees, 500 projects, 300 skills, 52 weeks |
| Fixed-format IDs and 52 weekly planning periods | `generator/generate_data.py` | Verified: ID checks pass and demand spans 52 consecutive weeks |
| Employee skill profiles, availability, leave, training, allocations and gaps | Generator and `modules/analysis.py` | Full counts validated, including 60,000 availability rows |
| Capacity, utilization, stale/missing/proficiency gaps and explainable recommendations | `modules/analysis.py` | Verified by tests and full-data validation; 91 gaps in the initial 8-week window |
| Moving average and Random Forest, chronological evaluation, MAE/RMSE/WAPE | `modules/forecasting.py` | Role/project/skill holdouts evaluated; moving average performed better in this synthetic run |
| Four isolated labelled anomaly scenarios and separate ground truth | `DemandImportEvent`, `AnomalyGroundTruth`, generator, detector | Verified: all 4/4 labelled cases matched; 0 additional findings |
| Full-data reproducibility | `validation/reproducibility.py`, `flask check-reproducibility --full` | Verified 2026-11-12: two isolated full-size runs identical; counts, primary-key hashes, derived calculations, anomaly results, and export checksums all matched |
| Validation and integrity | `validation/validate.py` | Read-only full-data run PASS (13 checks, 0 failures); primary-key uniqueness and foreign-key integrity passed |
| Expected anomaly detection | `modules/analysis.py`, `validation/validate.py` | 4/4 expected cases detected; 0 unexpected findings |
| Lifecycle transition auditing | `modules/lifecycle.py`, `database/models.py` | ORM transitions for Employee, Project, Training, Role, and Skill are validated and persisted as transaction-bound `AuditEvent` records; valid/invalid paths tested |
| Existing database and exports preserved | `workforce.db`, `exports/` | Database SHA-256 and aggregate fingerprint of all 27 export-directory files matched before and after verification; row counts unchanged |
| Database-backed responsive dashboard and required views | `app.py`, `templates/`, `static/` | All routes passed starter-data tests; full-data overview and API smoke-tested |
| CSV, JSON, SQL dump, ground-truth exports | `exports/export_data.py` | Existing ten core CSV/JSON exports, SQLite SQL dump, and separate ground-truth files verified unchanged; reproducibility checksums were produced only in temporary directories |
| Automated tests | `tests/` | `python -m pytest -q`: 16 passed |
| README, architecture, data dictionary, business rules, prompt history | Root docs and `docs/` | Complete; prompt history records only the prompt available in this session |
| Exclude the three supplied reference documents from the final project | `.gitignore` and source files | Verified: all three originals were removed from the deliverable folder; exact-name ignore rules remain |


