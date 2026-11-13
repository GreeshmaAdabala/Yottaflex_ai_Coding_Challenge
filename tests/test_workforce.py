import json
import re
from datetime import date

import pytest
from sqlalchemy import text

from database.db import db
from database.models import (
    Allocation,
    AnomalyGroundTruth,
    AuditEvent,
    Availability,
    DemandPlan,
    Employee,
    GapAnalysis,
    Project,
    Role,
    Skill,
    Training,
)
from modules.analysis import (
    build_recommendations,
    calculate_utilization,
    detect_anomalies,
    find_skill_gaps,
)
from modules.forecasting import forecast_demand
from validation.reproducibility import verify_reproducibility
from validation.validate import _transition_failures, validate_dataset
from app import normalize_database_uri
from modules.lifecycle import InvalidStatusTransition


def test_generator_volumes_ids_and_horizon(workforce_app):
    with workforce_app.app_context():
        assert Employee.query.count() == 50
        assert Skill.query.count() == 30
        assert Project.query.count() == 10
        assert Availability.query.count() == 50 * 12
        assert DemandPlan.query.count() > 0
        assert AnomalyGroundTruth.query.count() == 4
        assert Employee.query.order_by(Employee.employee_id).first().employee_id == "EMP-000001"
        assert DemandPlan.query.order_by(DemandPlan.demand_id).first().demand_id.startswith(
            "DEM-PRJ-2026-"
        )
        periods = [
            row[0]
            for row in db.session.query(DemandPlan.period_start)
            .distinct()
            .order_by(DemandPlan.period_start)
        ]
        assert len(set(periods)) == 52
        assert periods[0] == date(2026, 1, 1)
        assert all(
            (right - left).days == 7 for left, right in zip(periods, periods[1:])
        )


def test_sqlite_foreign_keys_and_validation(workforce_app):
    with workforce_app.app_context():
        assert db.session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        report = validate_dataset(as_of=date(2026, 1, 1))
        assert report["status"] == "PASS"
        assert report["expected_anomaly_count"] == 4
        assert report["detected_expected_anomalies"] == 4
        assert report["failed_checks"] == 0


def test_utilization_uses_effective_monthly_capacity(workforce_app):
    with workforce_app.app_context():
        employee = Employee.query.order_by(Employee.employee_id).first()
        availability = Availability.query.filter_by(
            employee_id=employee.employee_id,
            period_start=date(2026, 1, 1),
        ).one()
        result = calculate_utilization(
            employee.employee_id, date(2026, 1, 1), date(2026, 1, 31)
        )
        assert result["available_hours"] == round(
            availability.capacity_hours - availability.leave_hours, 2
        )
        assert result["allocated_hours"] >= 0
        assert result["utilization_pct"] >= 0


def test_gap_trace_and_recommendation_are_demand_backed(workforce_app):
    with workforce_app.app_context():
        demand = DemandPlan.query.order_by(DemandPlan.demand_id).first()
        demand.required_headcount = 10000
        demand.required_hours = 400000
        db.session.flush()
        actual_gaps = find_skill_gaps(
            period_start=date(2026, 1, 1), weeks=52, persist=True
        )
        matching_gap = next(gap for gap in actual_gaps if gap["demand_id"] == demand.demand_id)
        recommendation = build_recommendations([matching_gap])[0]
        assert recommendation["demand_id"] == demand.demand_id
        assert recommendation["action"] in {"train", "reverify", "reassign"}
        assert all(gap["demand_id"] in {row.demand_id for row in DemandPlan.query.all()} for gap in actual_gaps)
        assert GapAnalysis.query.filter_by(demand_id=demand.demand_id).count() == 1


def test_all_required_anomalies_are_detected_without_truth_input(workforce_app):
    with workforce_app.app_context():
        findings = detect_anomalies(as_of=date(2026, 1, 1))
        issue_types = {item["issue_type"] for item in findings}
        assert {
            "allocation_exceeds_availability",
            "stale_skill_current",
            "demand_double_counted",
            "overlapping_projects",
        }.issubset(issue_types)
        detail = AnomalyGroundTruth.query.filter_by(
            issue_type="allocation_exceeds_availability"
        ).one().details
        assert "weekly capacity" in detail


def test_forecast_has_chronological_metrics_and_future_values(workforce_app):
    with workforce_app.app_context():
        result = forecast_demand("role", horizon=2)
        assert result["metrics"]["test_period_start"]
        assert set(result["metrics"]["baseline_moving_average"]) == {
            "mae",
            "rmse",
            "wape_pct",
        }
        assert set(result["metrics"]["random_forest"]) == {
            "mae",
            "rmse",
            "wape_pct",
        }
        future = [row for row in result["series"] if row["record_type"] == "predicted_future"]
        assert len(future) == 2 * db.session.query(DemandPlan.role_id).distinct().count()
        assert all(row["actual_observed_demand"] is None for row in future)


def test_forecast_table_renders_history_backtest_and_future(client):
    response = client.get("/forecast?dimension=role")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<td>synthetic historical</td>" in html
    assert "<td>backtest</td>" in html
    assert "<td>predicted future</td>" in html
    future_row = re.search(
        r"<tr><td>[^<]*</td><td>[^<]*</td><td>predicted future</td>"
        r"<td>[^<]*</td><td>[^<]*</td><td>([^<]*)</td><td>([^<]*)</td></tr>",
        html,
    )
    assert future_row
    assert all(value.strip() != "—" for value in future_row.groups())


def test_project_demand_header_describes_horizon_total(client):
    response = client.get("/projects")
    html = response.get_data(as_text=True)
    assert "<th>Horizon demand</th>" in html
    assert "<th>Weekly demand</th>" not in html


def test_dashboard_projects_follow_explicit_priority_order(client, workforce_app):
    with workforce_app.app_context():
        projects = Project.query.order_by(Project.project_id).all()
        priorities = [
            "low",
            "critical",
            "medium",
            "high",
            "low",
            "critical",
            "medium",
            "high",
            "low",
            "low",
        ]
        for project, priority in zip(projects, priorities):
            project.priority = priority
        db.session.commit()

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    project_section = html.split("<h2>Priority projects</h2>", 1)[1].split(
        "</article>", 1
    )[0]
    assert re.findall(
        r'class="tag tag-(critical|high|medium|low)"', project_section
    ) == ["critical", "critical", "high", "high", "medium", "medium"]


def test_projects_and_utilization_paginate_with_search(client, workforce_app):
    with workforce_app.app_context():
        role_id = Role.query.first().role_id
        db.session.add_all(
            [
                Project(
                    project_id=f"PRJ-2026-9{index:05d}",
                    name=f"Paged Project {index:03d}",
                    client="Pagination Test",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                    status="planned",
                    priority="medium",
                )
                for index in range(1, 56)
            ]
        )
        db.session.add_all(
            [
                Employee(
                    employee_id=f"EMP-9{index:05d}",
                    full_name=f"Paged Employee {index:03d}",
                    role_id=role_id,
                    hire_date=date(2020, 1, 1),
                    employment_type="full_time",
                    weekly_hours=40,
                    experience_years=2,
                    status="active",
                )
                for index in range(1, 56)
            ]
        )
        db.session.commit()

    projects_response = client.get("/projects?q=Paged%20Project&page=2")
    projects_html = projects_response.get_data(as_text=True)
    projects_body = projects_html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert projects_response.status_code == 200
    assert "Page 2 of 2" in projects_html
    assert projects_body.count("<tr>") == 5
    assert 'value="Paged Project"' in projects_html

    utilization_response = client.get(
        "/utilization?q=Paged%20Employee&page=2"
    )
    utilization_html = utilization_response.get_data(as_text=True)
    utilization_body = utilization_html.split("<tbody>", 1)[1].split(
        "</tbody>", 1
    )[0]
    assert utilization_response.status_code == 200
    assert "Page 2 of 2" in utilization_html
    assert utilization_body.count("<tr>") == 5
    assert 'value="Paged Employee"' in utilization_html


def test_reproducibility_compares_two_runs():
    report = verify_reproducibility(
        employees=50, skills=30, projects=10, seed=20261022, horizon_weeks=52
    )
    assert report["identical"] is True
    assert report["first_run"]["counts"] == report["second_run"]["counts"]
    assert report["first_run"]["file_checksums"] == report["second_run"]["file_checksums"]


def test_full_data_reproducibility_compares_all_outputs():
    report = verify_reproducibility(
        employees=5000,
        skills=300,
        projects=500,
        seed=20261022,
        horizon_weeks=52,
    )
    assert report["identical"] is True
    assert all(report["comparisons"].values())
    assert report["first_run"]["counts"]["employees"] == 5000
    assert report["first_run"]["counts"]["projects"] == 500
    assert report["first_run"]["counts"]["skills"] == 300
    assert report["first_run"]["expected_anomaly_detection"]["missing_expected"] == []
    assert report["first_run"]["expected_anomaly_detection"]["unexpected"] == []


def test_dashboard_routes_use_database_data(client):
    for path in [
        "/",
        "/employees",
        "/projects",
        "/forecast",
        "/utilization",
        "/gaps",
        "/anomalies",
        "/api/summary",
        "/api/forecast",
    ]:
        response = client.get(path)
        assert response.status_code == 200, path
    assert client.get("/employees?q=EMP-000001").status_code == 200
    assert client.get("/employees/not-a-real-employee").status_code == 404


def test_postgres_render_urls_use_declared_psycopg_driver():
    assert normalize_database_uri("postgres://user:pass@host/db") == (
        "postgresql+psycopg://user:pass@host/db"
    )
    assert normalize_database_uri("postgresql://host/db") == (
        "postgresql+psycopg://host/db"
    )


def test_lifecycle_transitions_persist_audit_events(workforce_app):
    with workforce_app.app_context():
        transitions = [
            (Employee.query.filter_by(status="active").first(), "status", "leave"),
            (Project.query.filter_by(status="planned").first(), "status", "active"),
            (Training.query.filter_by(status="planned").first(), "status", "in_progress"),
            (Role.query.filter_by(lifecycle_state="active").first(), "lifecycle_state", "retired"),
            (Skill.query.filter_by(lifecycle_state="active").first(), "lifecycle_state", "retired"),
        ]
        assert all(entity is not None for entity, _, _ in transitions)
        for entity, field, new_status in transitions:
            setattr(entity, field, new_status)
        db.session.commit()

        events = AuditEvent.query.filter_by(action="status_transition").all()
        assert len(events) == len(transitions)
        events_by_type = {event.entity_type: event for event in events}
        for entity, field, new_status in transitions:
            entity_type = type(entity).__name__
            event = events_by_type[entity_type]
            details = json.loads(event.details)
            assert event.entity_id == getattr(
                entity,
                {
                    "Employee": "employee_id",
                    "Project": "project_id",
                    "Training": "training_id",
                    "Role": "role_id",
                    "Skill": "skill_id",
                }[entity_type],
            )
            assert event.event_time is not None
            assert details == {
                "from_status": {
                    "Employee": "active",
                    "Project": "planned",
                    "Training": "planned",
                    "Role": "active",
                    "Skill": "active",
                }[entity_type],
                "status_field": field,
                "to_status": new_status,
            }
        assert _transition_failures(db.session) == (5, 0)


def test_lifecycle_transition_audit_rejects_invalid_edges(workforce_app):
    with workforce_app.app_context():
        project = Project.query.filter_by(status="planned").first()
        project_id = project.project_id
        project.status = "completed"
        with pytest.raises(InvalidStatusTransition, match="Project status transition"):
            db.session.flush()
        db.session.rollback()
        assert db.session.get(Project, project_id).status == "planned"
        assert AuditEvent.query.count() == 0
