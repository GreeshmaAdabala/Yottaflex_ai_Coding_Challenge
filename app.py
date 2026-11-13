import json
import os
import calendar
from datetime import date, timedelta
from pathlib import Path

import click
import pandas as pd
import plotly.express as px
from flask import Flask, Response, abort, jsonify, render_template, request, send_file
from flask import current_app
from sqlalchemy import case, func, or_

from config import Config, PROJECT_ROOT
from database.db import db
from database.models import (
    Allocation,
    AnomalyGroundTruth,
    Availability,
    DemandPlan,
    Employee,
    EmployeeSkill,
    GapAnalysis,
    Project,
    Role,
    Skill,
    Training,
)
from exports.export_data import export_all
from generator.generate_data import dataset_counts, generate_dataset
from modules.analysis import (
    build_recommendations,
    calculate_workforce_utilization,
    calculate_utilization,
    detect_anomalies,
    find_skill_gaps,
)
from modules.forecasting import forecast_demand
from validation.validate import validate_dataset


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    app.config["SQLALCHEMY_DATABASE_URI"] = normalize_database_uri(
        app.config["SQLALCHEMY_DATABASE_URI"]
    )
    db.init_app(app)
    app.jinja_env.globals["timedelta"] = timedelta

    with app.app_context():
        db.create_all()
        if app.config.get("AUTO_SEED") and not Employee.query.first():
            generate_dataset(
                employees=50,
                skills=30,
                projects=10,
                seed=app.config["SEED"],
                horizon_start=date.fromisoformat(app.config["HORIZON_START"]),
                horizon_weeks=app.config["HORIZON_WEEKS"],
            )

    register_commands(app)
    register_routes(app)
    return app


def normalize_database_uri(uri):
    if uri.startswith("postgres://"):
        return uri.replace("postgres://", "postgresql+psycopg://", 1)
    if uri.startswith("postgresql://"):
        return uri.replace("postgresql://", "postgresql+psycopg://", 1)
    return uri


def _dashboard_context():
    period_start = date.fromisoformat(
        current_app_config("HORIZON_START")
    )
    period_end = date(
        period_start.year, period_start.month,
        calendar.monthrange(period_start.year, period_start.month)[1],
    )
    utilization = calculate_workforce_utilization(period_start, period_end)
    effective_capacity = (
        db.session.query(
            func.coalesce(func.sum(Availability.capacity_hours - Availability.leave_hours), 0)
        )
        .filter(
            Availability.period_start == period_start.replace(day=1),
        )
        .scalar()
    )
    demand = db.session.query(func.coalesce(func.sum(DemandPlan.required_hours), 0)).scalar()
    gaps = GapAnalysis.query.filter_by(status="open").count()
    recommendations = build_recommendations(
        find_skill_gaps(period_start=period_start, weeks=8, persist=False)
    )
    average_utilization = (
        sum(item["utilization_pct"] for item in utilization) / len(utilization)
        if utilization
        else 0.0
    )
    return {
        "employees": Employee.query.count(),
        "projects": Project.query.count(),
        "skills": Skill.query.count(),
        "total_demand_hours": round(demand, 1),
        "available_capacity_hours": round(effective_capacity or 0, 1),
        "average_utilization": round(average_utilization, 1),
        "skill_gaps": gaps,
        "hiring_requirements": sum(
            item["shortage"]
            for item in recommendations
            if item["action"] == "hire"
        ),
        "anomalies": len(detect_anomalies(as_of=period_start)),
        "period_start": period_start,
        "period_end": period_end,
        "utilization_rows": utilization,
    }


def current_app_config(key):
    return current_app.config[key]


def _plot_html(forecast, title, dimension, max_groups=6):
    records = forecast["series"]
    frame = pd.DataFrame(records)
    if frame.empty:
        return "<p class='muted'>No forecast data is available yet.</p>"
    historic = frame[frame["record_type"] == "synthetic_historical"]
    top_keys = (
        historic.groupby("key")["synthetic_historical_demand"]
        .sum()
        .nlargest(max_groups)
        .index.tolist()
    )
    selected = frame[frame["key"].isin(top_keys)]
    chart_rows = []
    for row in selected.to_dict("records"):
        if row["record_type"] == "synthetic_historical":
            value = row["synthetic_historical_demand"]
            series_name = "Synthetic historical demand"
        elif row["record_type"] == "predicted_future":
            value = row["random_forest_forecast"]
            series_name = "Random Forest future forecast"
        else:
            value = row["random_forest_forecast"]
            series_name = "Random Forest backtest"
        chart_rows.append(
            {
                "period": row["period_start"],
                "value": value,
                "entity": row["key"],
                "series": series_name,
            }
        )
        if row["record_type"] == "backtest":
            chart_rows.append(
                {
                    "period": row["period_start"],
                    "value": row["moving_average_forecast"],
                    "entity": row["key"],
                    "series": "Moving average backtest",
                }
            )
    chart = px.line(
        pd.DataFrame(chart_rows),
        x="period",
        y="value",
        color="entity",
        line_dash="series",
        title=title,
        labels={"period": "Week", "value": "Required hours"},
    )
    chart.update_layout(
        template="plotly_white",
        margin=dict(l=20, r=20, t=55, b=20),
        legend_title_text=dimension.title(),
        hovermode="x unified",
    )
    return chart.to_html(full_html=False, include_plotlyjs=False)


def _forecast_table_rows(forecast, max_groups=6, history_weeks=4):
    frame = pd.DataFrame(forecast["series"])
    if frame.empty:
        return []

    historical = frame[frame["record_type"] == "synthetic_historical"]
    if historical.empty:
        return []
    top_keys = (
        historical.groupby("key")["synthetic_historical_demand"]
        .sum()
        .nlargest(max_groups)
        .index.tolist()
    )
    recent_periods = {
        key: set(
            historical.loc[historical["key"] == key]
            .sort_values("period_start")["period_start"]
            .tail(history_weeks)
        )
        for key in top_keys
    }
    selected = [
        row
        for row in forecast["series"]
        if row["key"] in top_keys
        and (
            row["record_type"] != "synthetic_historical"
            or row["period_start"] in recent_periods[row["key"]]
        )
    ]
    record_type_order = {
        "synthetic_historical": 0,
        "backtest": 1,
        "predicted_future": 2,
    }
    return sorted(
        selected,
        key=lambda row: (
            row["key"],
            row["period_start"],
            record_type_order[row["record_type"]],
        ),
    )


def register_routes(app):
    @app.get("/assets/plotly.min.js")
    def plotly_js():
        from plotly.offline import get_plotlyjs

        return Response(get_plotlyjs(), mimetype="application/javascript")

    @app.get("/")
    def dashboard():
        summary = _dashboard_context()
        role_forecast = forecast_demand("role", horizon=8)
        chart = _plot_html(
            role_forecast, "Role demand: plan and forecast", "Role"
        )
        priority_order = case(
            (Project.priority == "critical", 0),
            (Project.priority == "high", 1),
            (Project.priority == "medium", 2),
            (Project.priority == "low", 3),
            else_=4,
        )
        return render_template(
            "dashboard.html",
            summary=summary,
            chart=chart,
            recent_projects=Project.query.order_by(
                priority_order, Project.start_date, Project.project_id
            )
            .limit(6)
            .all(),
        )

    @app.get("/employees")
    def employees():
        search = request.args.get("q", "").strip()
        page = max(1, request.args.get("page", 1, type=int))
        query = Employee.query.join(Role)
        if search:
            query = query.filter(
                or_(
                    Employee.employee_id.ilike(f"%{search}%"),
                    Employee.full_name.ilike(f"%{search}%"),
                    Role.name.ilike(f"%{search}%"),
                )
            )
        pagination = query.order_by(Employee.employee_id).paginate(
            page=page, per_page=50, error_out=False
        )
        return render_template(
            "employees.html", pagination=pagination, search=search
        )

    @app.get("/employees/<employee_id>")
    def employee_detail(employee_id):
        employee = db.session.get(Employee, employee_id)
        if employee is None:
            abort(404)
        start = date.fromisoformat(current_app_config("HORIZON_START"))
        period_end = date(
            start.year,
            start.month,
            calendar.monthrange(start.year, start.month)[1],
        )
        employee_utilization = calculate_utilization(
            employee_id, start, period_end
        )
        return render_template(
            "employee_detail.html",
            employee=employee,
            utilization=employee_utilization,
            allocations=Allocation.query.filter_by(employee_id=employee_id)
            .order_by(Allocation.start_date)
            .all(),
            availability=Availability.query.filter_by(employee_id=employee_id)
            .order_by(Availability.period_start)
            .limit(6)
            .all(),
            trainings=Training.query.filter_by(employee_id=employee_id).all(),
            as_of=start,
        )

    @app.get("/projects")
    def projects():
        search = request.args.get("q", "").strip()
        page = max(1, request.args.get("page", 1, type=int))
        query = Project.query
        if search:
            query = query.filter(
                or_(
                    Project.project_id.ilike(f"%{search}%"),
                    Project.name.ilike(f"%{search}%"),
                    Project.client.ilike(f"%{search}%"),
                )
            )
        pagination = query.order_by(
            Project.start_date, Project.project_id
        ).paginate(page=page, per_page=50, error_out=False)
        return render_template(
            "projects.html",
            projects=pagination.items,
            pagination=pagination,
            search=search,
        )

    @app.get("/forecast")
    def forecast():
        dimension = request.args.get("dimension", "role")
        try:
            result = forecast_demand(dimension, horizon=8)
        except ValueError as error:
            abort(400, description=str(error))
        return render_template(
            "forecast.html",
            forecast=result,
            forecast_rows=_forecast_table_rows(result),
            dimension=dimension,
            chart=_plot_html(
                result, f"Weekly demand by {dimension}", dimension
            ),
        )

    @app.get("/utilization")
    def utilization():
        start = date.fromisoformat(current_app_config("HORIZON_START"))
        end = date(
            start.year,
            start.month,
            calendar.monthrange(start.year, start.month)[1],
        )
        query = Employee.query.filter(Employee.status == "active")
        search = request.args.get("q", "").strip()
        page = max(1, request.args.get("page", 1, type=int))
        if search:
            query = query.filter(
                db.or_(
                    Employee.employee_id.ilike(f"%{search}%"),
                    Employee.full_name.ilike(f"%{search}%"),
                )
            )
        pagination = query.order_by(Employee.employee_id).paginate(
            page=page, per_page=50, error_out=False
        )
        all_rows = calculate_workforce_utilization(start, end)
        rows_by_id = {row["employee_id"]: row for row in all_rows}
        rows = [rows_by_id[employee.employee_id] for employee in pagination.items]
        return render_template(
            "utilization.html",
            rows=rows,
            pagination=pagination,
            search=search,
        )

    @app.get("/gaps")
    def gaps():
        start = date.fromisoformat(current_app_config("HORIZON_START"))
        gap_rows = find_skill_gaps(period_start=start, weeks=8, persist=False)
        recommendations = build_recommendations(gap_rows)
        entities = {
            gap["demand_id"]: {
                "gap": gap,
                "project": db.session.get(Project, gap["project_id"]),
                "role": db.session.get(Role, gap["role_id"]),
                "skill": db.session.get(Skill, gap["skill_id"]),
            }
            for gap in gap_rows
        }
        return render_template(
            "gaps.html",
            gaps=list(entities.values()),
            recommendations=recommendations,
        )

    @app.get("/anomalies")
    def anomalies():
        start = date.fromisoformat(current_app_config("HORIZON_START"))
        findings = detect_anomalies(as_of=start)
        truth = {
            (item.issue_type, item.entity_id): item
            for item in AnomalyGroundTruth.query.all()
        }
        for finding in findings:
            expected = truth.get((finding["issue_type"], finding["entity_id"]))
            finding["ground_truth_match"] = expected is not None
            finding["ground_truth_label"] = (
                expected.ground_truth_label if expected else "not labelled"
            )
            finding["details"] = expected.details if expected else ""
        return render_template(
            "anomalies.html",
            findings=findings,
            expected_count=len(truth),
            matched_count=sum(item["ground_truth_match"] for item in findings),
        )

    @app.get("/api/summary")
    def api_summary():
        summary = _dashboard_context()
        summary["period_start"] = summary["period_start"].isoformat()
        summary["period_end"] = summary["period_end"].isoformat()
        summary.pop("utilization_rows")
        return jsonify(summary)

    @app.get("/api/forecast")
    def api_forecast():
        dimension = request.args.get("dimension", "role")
        try:
            return jsonify(forecast_demand(dimension, horizon=8))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

    @app.get("/exports/sql")
    def download_sql():
        path = PROJECT_ROOT / "exports" / "sql" / "workforce_dump.sql"
        if not path.exists():
            export_all()
        return send_file(path, as_attachment=True)


def register_commands(app):
    @app.cli.command("seed-data")
    @click.option("--full", is_flag=True, help="Generate the full 5,000/300/500 dataset.")
    @click.option("--reset", is_flag=True, help="Replace all existing tables and data.")
    def seed_data(full, reset):
        counts = generate_dataset(
            employees=5000 if full else 50,
            skills=300 if full else 30,
            projects=500 if full else 10,
            seed=app.config["SEED"],
            horizon_start=date.fromisoformat(app.config["HORIZON_START"]),
            horizon_weeks=app.config["HORIZON_WEEKS"],
            reset=reset,
        )
        click.echo(json.dumps(counts, indent=2))

    @app.cli.command("export-data")
    @click.option("--output-dir", default="exports", show_default=True)
    def export_data(output_dir):
        click.echo(json.dumps(export_all(output_dir), indent=2))

    @app.cli.command("validate-data")
    def validate_data():
        report = validate_dataset(
            as_of=date.fromisoformat(app.config["HORIZON_START"]),
            horizon_weeks=app.config["HORIZON_WEEKS"],
        )
        output = PROJECT_ROOT / "docs" / "validation_report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        click.echo(json.dumps(report, indent=2))
        if report["status"] != "PASS":
            raise click.ClickException("Dataset validation failed.")

    @app.cli.command("check-reproducibility")
    @click.option("--full", is_flag=True, help="Compare two full dataset generations.")
    def check_reproducibility(full):
        from validation.reproducibility import verify_reproducibility

        report = verify_reproducibility(
            employees=5000 if full else 50,
            skills=300 if full else 30,
            projects=500 if full else 10,
            seed=app.config["SEED"],
            horizon_weeks=app.config["HORIZON_WEEKS"],
        )
        output = PROJECT_ROOT / "docs" / "reproducibility_report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        click.echo(json.dumps(report, indent=2))
        if not report["identical"]:
            raise click.ClickException("Reproducibility comparison failed.")

    @app.cli.command("forecast-evaluation")
    @click.option(
        "--dimension",
        type=click.Choice(["all", "role", "project", "skill"]),
        default="all",
    )
    def forecast_evaluation(dimension):
        dimensions = ["role", "project", "skill"] if dimension == "all" else [dimension]
        report = {}
        for item in dimensions:
            result = forecast_demand(item, horizon=8)
            report[item] = {
                "metrics": result["metrics"],
                "note": result["note"],
            }
        output = PROJECT_ROOT / "docs" / "forecast_evaluation.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        click.echo(json.dumps(report, indent=2))


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
