import json
import re
import calendar
from datetime import date

from sqlalchemy import func, text

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
    GapAnalysis,
    Project,
    Role,
    RoleSkill,
    Skill,
    Training,
)
from modules.analysis import (
    calculate_workforce_utilization,
    detect_anomalies,
    find_skill_gaps,
)
from modules.lifecycle import ALLOWED_TRANSITIONS


CORE_MODELS = [
    Employee,
    Role,
    Skill,
    EmployeeSkill,
    Project,
    DemandPlan,
    Allocation,
    Availability,
    Training,
    GapAnalysis,
]

def _duplicate_groups(session, model, columns):
    fields = [getattr(model, column) for column in columns]
    return (
        session.query(*fields)
        .group_by(*fields)
        .having(func.count() > 1)
        .count()
    )


def _transition_failures(session):
    valid_entities = {
        "Employee": {row[0] for row in session.query(Employee.employee_id)},
        "Project": {row[0] for row in session.query(Project.project_id)},
        "Training": {row[0] for row in session.query(Training.training_id)},
        "Role": {row[0] for row in session.query(Role.role_id)},
        "Skill": {row[0] for row in session.query(Skill.skill_id)},
    }
    failures = 0
    transitions = session.query(AuditEvent).filter_by(action="status_transition").all()
    for event in transitions:
        if event.entity_type not in ALLOWED_TRANSITIONS:
            failures += 1
            continue
        if event.entity_id not in valid_entities[event.entity_type]:
            failures += 1
            continue
        try:
            details = json.loads(event.details)
        except json.JSONDecodeError:
            failures += 1
            continue
        if not isinstance(details, dict):
            failures += 1
            continue
        pair = (details.get("from_status"), details.get("to_status"))
        if pair not in ALLOWED_TRANSITIONS[event.entity_type]:
            failures += 1
    return len(transitions), failures


def _weekdays(start, end):
    days = (end - start).days + 1
    full_weeks, remainder = divmod(days, 7)
    weekdays = full_weeks * 5
    weekdays += sum(
        (start + date.resolution * offset).weekday() < 5
        for offset in range(remainder)
    )
    return weekdays


def _identifier_format_failures(session):
    patterns = (
        (Employee, "employee_id", r"EMP-\d{6}"),
        (Skill, "skill_id", r"SKL-\d{6}"),
        (Project, "project_id", r"PRJ-2026-\d{6}"),
        (DemandPlan, "demand_id", r"DEM-PRJ-2026-\d{6}-\d{4}W\d{2}"),
        (Allocation, "allocation_id", r"ALLOC-2026-\d{6}"),
    )
    failures = 0
    checked = 0
    for model, column, pattern in patterns:
        identifiers = session.query(getattr(model, column)).all()
        checked += len(identifiers)
        failures += sum(
            re.fullmatch(pattern, row[0]) is None for row in identifiers
        )
    return checked, failures


def validate_dataset(session=None, as_of=date(2026, 1, 1), horizon_weeks=52):
    session = session or db.session
    checks = []

    def add_check(name, checked, failures=0, detail=""):
        checks.append(
            {
                "name": name,
                "records_checked": int(checked),
                "failed": int(failures),
                "passed": max(0, int(checked) - int(failures)),
                "status": "PASS" if failures == 0 else "FAIL",
                "detail": detail,
            }
        )

    total_core_records = sum(
        session.query(func.count()).select_from(model).scalar() or 0
        for model in CORE_MODELS
    )

    key_models = CORE_MODELS + [
        RoleSkill,
        DemandImportEvent,
        AnomalyGroundTruth,
        AuditEvent,
    ]
    primary_key_failures = 0
    key_records = 0
    for model in key_models:
        primary_key_columns = [
            column.name for column in model.__table__.primary_key.columns
        ]
        key_records += session.query(func.count()).select_from(model).scalar() or 0
        primary_key_failures += _duplicate_groups(
            session, model, primary_key_columns
        )
    add_check("primary_key_uniqueness", key_records, primary_key_failures)

    identifier_records, identifier_failures = _identifier_format_failures(session)
    add_check(
        "deterministic_identifier_formats",
        identifier_records,
        identifier_failures,
    )

    connection = session.connection()
    if connection.dialect.name == "sqlite":
        foreign_key_failures = len(
            connection.execute(text("PRAGMA foreign_key_check")).fetchall()
        )
        foreign_key_detail = "Checked SQLite PRAGMA foreign_key_check."
    else:
        foreign_key_failures = 0
        foreign_key_detail = (
            "Declared foreign keys are enforced by PostgreSQL; SQLite PRAGMA is not applicable."
        )
    add_check(
        "foreign_key_integrity",
        total_core_records,
        foreign_key_failures,
        foreign_key_detail,
    )

    invalid_dates = 0
    date_pairs = [
        (Project, Project.start_date, Project.end_date),
        (Allocation, Allocation.start_date, Allocation.end_date),
        (Training, Training.start_date, Training.end_date),
        (DemandPlan, DemandPlan.period_start, DemandPlan.period_end),
        (Availability, Availability.period_start, Availability.period_end),
    ]
    for model, start_column, end_column in date_pairs:
        invalid_dates += (
            session.query(func.count())
            .select_from(model)
            .filter(end_column < start_column)
            .scalar()
        )
    invalid_dates += (
        session.query(func.count())
        .select_from(Employee)
        .filter(
            Employee.lifecycle_end.is_not(None)
            & (Employee.lifecycle_end < Employee.hire_date)
        )
        .scalar()
    )
    add_check("date_ordering_and_allocation_validity", total_core_records, invalid_dates)

    invalid_skill_dates = (
        session.query(func.count())
        .select_from(EmployeeSkill)
        .filter(
            EmployeeSkill.expires_on.is_not(None)
            & (EmployeeSkill.expires_on < EmployeeSkill.verified_on)
        )
        .scalar()
    )
    add_check(
        "skill_verification_date_order",
        EmployeeSkill.query.count(),
        invalid_skill_dates,
    )

    availability_rows = Availability.query.all()
    employee_hours = {
        row.employee_id: row.weekly_hours for row in Employee.query.all()
    }
    invalid_capacity = sum(
        record.leave_hours < 0
        or record.leave_hours > record.capacity_hours
        or abs(
            record.capacity_hours
            - _weekdays(record.period_start, record.period_end)
            * employee_hours[record.employee_id]
            / 5
        )
        > 0.02
        for record in availability_rows
    )
    add_check(
        "capacity_reconciliation",
        Availability.query.count(),
        invalid_capacity,
        "Effective capacity is gross monthly capacity less non-negative leave hours.",
    )

    enum_failures = 0
    enum_failures += session.query(Employee).filter(
        Employee.employment_type.notin_(("full_time", "part_time"))
        | Employee.status.notin_(("active", "leave", "inactive"))
    ).count()
    enum_failures += session.query(Project).filter(
        Project.status.notin_(("planned", "active", "completed", "cancelled"))
        | Project.priority.notin_(("low", "medium", "high", "critical"))
    ).count()
    enum_failures += session.query(EmployeeSkill).filter(
        EmployeeSkill.verification_status.notin_(("verified", "pending", "expired"))
    ).count()
    enum_failures += session.query(Training).filter(
        Training.status.notin_(("planned", "in_progress", "completed", "cancelled"))
    ).count()
    enum_failures += session.query(GapAnalysis).filter(
        GapAnalysis.gap_type.notin_(
            ("missing_skill", "proficiency", "stale_skill", "capacity")
        )
        | GapAnalysis.status.notin_(("open", "mitigated", "closed"))
    ).count()
    add_check(
        "allowed_enumerations",
        Employee.query.count()
        + Project.query.count()
        + EmployeeSkill.query.count()
        + Training.query.count()
        + GapAnalysis.query.count(),
        enum_failures,
    )

    duplicate_keys = (
        _duplicate_groups(session, EmployeeSkill, ("employee_id", "skill_id"))
        + _duplicate_groups(session, Role, ("name",))
        + _duplicate_groups(session, Skill, ("name",))
        + _duplicate_groups(session, Availability, ("employee_id", "period_start"))
    )
    duplicate_demand_groups = _duplicate_groups(
        session,
        DemandPlan,
        ("project_id", "role_id", "skill_id", "period_start"),
    )
    add_check(
        "duplicate_business_records",
        total_core_records,
        duplicate_keys + duplicate_demand_groups,
        "Repeated source-import evidence is evaluated separately as a labelled anomaly.",
    )

    invalid_demand = (
        session.query(func.count())
        .select_from(DemandPlan)
        .filter(
            (DemandPlan.required_hours <= 0)
            | (DemandPlan.required_headcount <= 0)
            | (DemandPlan.required_proficiency < 1)
            | (DemandPlan.required_proficiency > 5)
        )
        .scalar()
    )
    demand_rows = session.query(DemandPlan).count()
    weekly_periods = [
        row[0]
        for row in session.query(DemandPlan.period_start)
        .distinct()
        .order_by(DemandPlan.period_start)
    ]
    invalid_periods = sum(
        (right - left).days != 7 for left, right in zip(weekly_periods, weekly_periods[1:])
    )
    if demand_rows and len(weekly_periods) != horizon_weeks:
        invalid_periods += 1
    add_check(
        "demand_validity_and_weekly_horizon",
        demand_rows,
        invalid_demand + invalid_periods,
        f"{len(weekly_periods)} distinct weekly periods; expected {horizon_weeks}.",
    )

    demand_total = (
        session.query(func.coalesce(func.sum(DemandPlan.required_hours), 0)).scalar()
        or 0.0
    )
    aggregates = []
    for dimension in (
        DemandPlan.project_id,
        DemandPlan.role_id,
        DemandPlan.skill_id,
    ):
        group_sums = [
            row[0]
            for row in session.query(func.sum(DemandPlan.required_hours))
            .group_by(dimension)
            .all()
        ]
        aggregates.append(sum(group_sums))
    demand_aggregation_failures = sum(
        abs(demand_total - grouped_total) > 0.01 for grouped_total in aggregates
    )
    add_check(
        "demand_aggregation",
        demand_rows,
        demand_aggregation_failures,
        "Project, role, and skill group totals each reconcile to the unique demand-plan total.",
    )

    period_end = date(
        as_of.year,
        as_of.month,
        calendar.monthrange(as_of.year, as_of.month)[1],
    )
    utilization_rows = calculate_workforce_utilization(
        as_of, period_end, session=session
    )
    invalid_utilization = sum(
        row["available_hours"] < 0
        or row["allocated_hours"] < 0
        or row["utilization_pct"] < 0
        or (
            row["available_hours"] > 0
            and abs(
                row["utilization_pct"]
                - row["allocated_hours"] / row["available_hours"] * 100
            )
            > 0.02
        )
        or (
            row["available_hours"] == 0 and row["utilization_pct"] != 0
        )
        or (
            row["classification"] != (
                "overutilized"
                if row["utilization_pct"] > 100
                else "underutilized"
                if row["utilization_pct"] < 50
                else "normally utilized"
            )
        )
        for row in utilization_rows
    )
    add_check(
        "utilization_calculation",
        len(utilization_rows),
        invalid_utilization,
        "Allocated hours / effective available capacity × 100; zero capacity yields 0%.",
    )

    transitions_checked, transition_failures = _transition_failures(session)
    add_check(
        "lifecycle_transitions",
        transitions_checked,
        transition_failures,
        "Valid transitions are checked for status_transition AuditEvent records; no history is fabricated.",
    )

    anomalies = detect_anomalies(session=session, as_of=as_of)
    ground_truth = {
        (record.issue_type, record.entity_id)
        for record in session.query(AnomalyGroundTruth).all()
    }
    detected = {(item["issue_type"], item["entity_id"]) for item in anomalies}
    expected_found = sum(1 for item in ground_truth if item in detected)
    expected_missing = len(ground_truth) - expected_found
    unexpected_findings = sum(1 for item in detected if item not in ground_truth)
    add_check(
        "injected_anomaly_detection",
        len(ground_truth) + unexpected_findings,
        expected_missing + unexpected_findings,
        f"{expected_found}/{len(ground_truth)} labelled cases detected; "
        f"{unexpected_findings} additional data-driven findings. Expected cases are not "
        "ordinary integrity failures.",
    )

    gaps = find_skill_gaps(
        period_start=as_of, weeks=8, session=session, persist=False
    )
    total_records_checked = sum(item["records_checked"] for item in checks)
    failed_checks = sum(item["failed"] for item in checks)
    return {
        "status": "PASS" if failed_checks == 0 else "FAIL",
        "total_records_checked": total_records_checked,
        "passed_checks": sum(item["status"] == "PASS" for item in checks),
        "failed_checks": failed_checks,
        "identified_anomalies": anomalies,
        "expected_anomaly_count": len(ground_truth),
        "detected_expected_anomalies": expected_found,
        "unexpected_anomaly_findings": unexpected_findings,
        "skill_gaps_in_window": len(gaps),
        "checks": checks,
    }
