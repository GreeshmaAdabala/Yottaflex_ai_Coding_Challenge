import calendar
import hashlib
import json
import tempfile
from datetime import date
from pathlib import Path

from app import create_app
from database.db import db
from database.models import (
    Allocation,
    AnomalyGroundTruth,
    AuditEvent,
    Availability,
    DemandImportEvent,
    DemandPlan,
    Employee,
    EmployeeSkill,
    Project,
    Role,
    RoleSkill,
    Skill,
    Training,
)
from exports.export_data import CORE_MODELS, export_all
from generator.generate_data import generate_dataset
from modules.analysis import (
    calculate_workforce_utilization,
    detect_anomalies,
    find_skill_gaps,
)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_once(directory, employees, skills, projects, seed, horizon_weeks):
    database_path = Path(directory) / "workforce.db"
    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "AUTO_SEED": False,
        }
    )
    with app.app_context():
        engine = db.engine
        db.create_all()
        generate_dataset(
            employees=employees,
            skills=skills,
            projects=projects,
            seed=seed,
            horizon_weeks=horizon_weeks,
        )
        export_all(Path(directory) / "exports")
        key_hashes = {}
        counts = {}
        tracked_models = CORE_MODELS + [
            RoleSkill,
            DemandImportEvent,
            AnomalyGroundTruth,
            AuditEvent,
        ]
        for model in tracked_models:
            ids = [
                row[0]
                for row in db.session.query(
                    *[getattr(model, column.name) for column in model.__table__.primary_key.columns]
                ).order_by(
                    *[getattr(model, column.name) for column in model.__table__.primary_key.columns]
                )
            ]
            table = model.__tablename__
            counts[table] = len(ids)
            key_hashes[table] = hashlib.sha256(
                json.dumps(ids, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        detections = sorted(
            (item["issue_type"], item["entity_id"])
            for item in detect_anomalies(
                as_of=date.fromisoformat(app.config["HORIZON_START"])
            )
        )
        as_of = date.fromisoformat(app.config["HORIZON_START"])
        expected_anomalies = sorted(
            (record.issue_type, record.entity_id)
            for record in db.session.query(AnomalyGroundTruth).all()
            if record.ground_truth_label == "anomaly"
        )
        detected_set = set(detections)
        expected_set = set(expected_anomalies)
        anomaly_comparison = {
            "expected": expected_anomalies,
            "detected": detections,
            "missing_expected": sorted(expected_set - detected_set),
            "unexpected": sorted(detected_set - expected_set),
        }
        gap_results = find_skill_gaps(
            period_start=as_of,
            weeks=min(4, horizon_weeks),
            session=db.session,
        )
        utilization_end = date(
            as_of.year,
            as_of.month,
            calendar.monthrange(as_of.year, as_of.month)[1],
        )
        utilization_results = calculate_workforce_utilization(
            as_of, utilization_end, session=db.session
        )
        derived = {
            "skill_gaps": {
                "count": len(gap_results),
                "sha256": _json_sha256(gap_results),
            },
            "workforce_utilization": {
                "count": len(utilization_results),
                "sha256": _json_sha256(utilization_results),
            },
        }
        export_files = sorted(
            path
            for path in [
                *(Path(directory) / "exports").rglob("*"),
                *(Path(directory) / "ground_truth").rglob("*"),
            ]
            if path.is_file()
        )
        checksums = {
            str(path.relative_to(directory)): _sha256(path)
            for path in export_files
        }
        result = {
            "counts": counts,
            "primary_key_hashes": key_hashes,
            "ground_truth": detections,
            "expected_anomaly_detection": anomaly_comparison,
            "derived_calculations": derived,
            "file_checksums": checksums,
        }
    engine.dispose()
    return result


def verify_reproducibility(
    employees=50,
    skills=30,
    projects=10,
    seed=20261022,
    horizon_weeks=52,
):
    """Generate twice in isolated temporary databases and compare durable outputs."""
    with tempfile.TemporaryDirectory(prefix="yottaflex-repro-") as root:
        first_dir, second_dir = Path(root) / "first", Path(root) / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        first = _run_once(first_dir, employees, skills, projects, seed, horizon_weeks)
        second = _run_once(second_dir, employees, skills, projects, seed, horizon_weeks)
    comparisons = {
        name: first[name] == second[name]
        for name in (
            "counts",
            "primary_key_hashes",
            "expected_anomaly_detection",
            "derived_calculations",
            "file_checksums",
        )
    }
    return {
        "seed": seed,
        "configuration": {
            "employees": employees,
            "skills": skills,
            "projects": projects,
            "horizon_weeks": horizon_weeks,
        },
        "identical": all(comparisons.values()),
        "comparisons": comparisons,
        "first_run": first,
        "second_run": second,
    }
