from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, UniqueConstraint

from database.db import db


def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(db.Model):
    __tablename__ = "roles"

    role_id = db.Column(db.String(24), primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    family = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    lifecycle_state = db.Column(db.String(16), nullable=False, default="active")

    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('active', 'retired')", name="ck_role_lifecycle"
        ),
    )
    employees = db.relationship("Employee", back_populates="role")
    role_skills = db.relationship("RoleSkill", back_populates="role")


class Skill(db.Model):
    __tablename__ = "skills"

    skill_id = db.Column(db.String(24), primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    category = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    lifecycle_state = db.Column(db.String(16), nullable=False, default="active")

    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('active', 'retired')", name="ck_skill_lifecycle"
        ),
    )
    employee_skills = db.relationship("EmployeeSkill", back_populates="skill")
    role_skills = db.relationship("RoleSkill", back_populates="skill")


class RoleSkill(db.Model):
    __tablename__ = "role_skills"

    role_id = db.Column(db.String(24), db.ForeignKey("roles.role_id"), primary_key=True)
    skill_id = db.Column(
        db.String(24), db.ForeignKey("skills.skill_id"), primary_key=True
    )
    target_proficiency = db.Column(db.Integer, nullable=False, default=3)
    is_required = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            "target_proficiency BETWEEN 1 AND 5", name="ck_role_skill_proficiency"
        ),
    )
    role = db.relationship("Role", back_populates="role_skills")
    skill = db.relationship("Skill", back_populates="role_skills")


class Employee(db.Model):
    __tablename__ = "employees"

    employee_id = db.Column(db.String(16), primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    role_id = db.Column(db.String(24), db.ForeignKey("roles.role_id"), nullable=False)
    hire_date = db.Column(db.Date, nullable=False)
    employment_type = db.Column(db.String(16), nullable=False)
    weekly_hours = db.Column(db.Float, nullable=False)
    experience_years = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="active")
    lifecycle_end = db.Column(db.Date, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "employment_type IN ('full_time', 'part_time')",
            name="ck_employee_employment_type",
        ),
        CheckConstraint(
            "status IN ('active', 'leave', 'inactive')", name="ck_employee_status"
        ),
        CheckConstraint("weekly_hours > 0 AND weekly_hours <= 60"),
        CheckConstraint("experience_years >= 0"),
        CheckConstraint("lifecycle_end IS NULL OR lifecycle_end >= hire_date"),
    )
    role = db.relationship("Role", back_populates="employees")
    skills = db.relationship(
        "EmployeeSkill", back_populates="employee", cascade="all, delete-orphan"
    )
    allocations = db.relationship("Allocation", back_populates="employee")
    availability = db.relationship("Availability", back_populates="employee")
    trainings = db.relationship("Training", back_populates="employee")


class EmployeeSkill(db.Model):
    __tablename__ = "employee_skills"

    employee_skill_id = db.Column(db.String(40), primary_key=True)
    employee_id = db.Column(
        db.String(16), db.ForeignKey("employees.employee_id"), nullable=False
    )
    skill_id = db.Column(db.String(24), db.ForeignKey("skills.skill_id"), nullable=False)
    proficiency = db.Column(db.Integer, nullable=False)
    verified_on = db.Column(db.Date, nullable=False)
    expires_on = db.Column(db.Date, nullable=True)
    verification_status = db.Column(db.String(16), nullable=False, default="verified")

    __table_args__ = (
        UniqueConstraint("employee_id", "skill_id", name="uq_employee_skill"),
        CheckConstraint("proficiency BETWEEN 1 AND 5", name="ck_employee_skill_level"),
        CheckConstraint(
            "verification_status IN ('verified', 'pending', 'expired')",
            name="ck_employee_skill_status",
        ),
        CheckConstraint(
            "expires_on IS NULL OR expires_on >= verified_on",
            name="ck_employee_skill_dates",
        ),
    )
    employee = db.relationship("Employee", back_populates="skills")
    skill = db.relationship("Skill", back_populates="employee_skills")


class Project(db.Model):
    __tablename__ = "projects"

    project_id = db.Column(db.String(24), primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    client = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="planned")
    priority = db.Column(db.String(12), nullable=False, default="medium")

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_project_dates"),
        CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'cancelled')",
            name="ck_project_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="ck_project_priority",
        ),
    )
    demand = db.relationship("DemandPlan", back_populates="project")
    allocations = db.relationship("Allocation", back_populates="project")


class DemandPlan(db.Model):
    __tablename__ = "demand_plans"

    demand_id = db.Column(db.String(64), primary_key=True)
    project_id = db.Column(
        db.String(24), db.ForeignKey("projects.project_id"), nullable=False
    )
    role_id = db.Column(db.String(24), db.ForeignKey("roles.role_id"), nullable=False)
    skill_id = db.Column(db.String(24), db.ForeignKey("skills.skill_id"), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    required_hours = db.Column(db.Float, nullable=False)
    required_headcount = db.Column(db.Integer, nullable=False)
    required_proficiency = db.Column(db.Integer, nullable=False)
    demand_type = db.Column(db.String(16), nullable=False, default="planned")
    instance_number = db.Column(db.Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "role_id",
            "skill_id",
            "period_start",
            "instance_number",
            name="uq_demand_logical_instance",
        ),
        CheckConstraint("period_end >= period_start", name="ck_demand_dates"),
        CheckConstraint("required_hours > 0", name="ck_demand_hours"),
        CheckConstraint("required_headcount > 0", name="ck_demand_headcount"),
        CheckConstraint(
            "required_proficiency BETWEEN 1 AND 5", name="ck_demand_proficiency"
        ),
        CheckConstraint("instance_number >= 1", name="ck_demand_instance"),
        CheckConstraint(
            "demand_type IN ('planned', 'observed')", name="ck_demand_type"
        ),
    )
    project = db.relationship("Project", back_populates="demand")
    role = db.relationship("Role")
    skill = db.relationship("Skill")


class Allocation(db.Model):
    __tablename__ = "allocations"

    allocation_id = db.Column(db.String(24), primary_key=True)
    employee_id = db.Column(
        db.String(16), db.ForeignKey("employees.employee_id"), nullable=False
    )
    project_id = db.Column(
        db.String(24), db.ForeignKey("projects.project_id"), nullable=False
    )
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    weekly_hours = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="active")
    is_injected_anomaly = db.Column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_allocation_dates"),
        CheckConstraint("weekly_hours > 0 AND weekly_hours <= 80"),
        CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'cancelled')",
            name="ck_allocation_status",
        ),
    )
    employee = db.relationship("Employee", back_populates="allocations")
    project = db.relationship("Project", back_populates="allocations")


class Availability(db.Model):
    __tablename__ = "availability"

    availability_id = db.Column(db.String(40), primary_key=True)
    employee_id = db.Column(
        db.String(16), db.ForeignKey("employees.employee_id"), nullable=False
    )
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    capacity_hours = db.Column(db.Float, nullable=False)
    leave_hours = db.Column(db.Float, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("employee_id", "period_start", name="uq_employee_availability"),
        CheckConstraint("period_end >= period_start", name="ck_availability_dates"),
        CheckConstraint("capacity_hours >= 0", name="ck_availability_capacity"),
        CheckConstraint(
            "leave_hours >= 0 AND leave_hours <= capacity_hours",
            name="ck_availability_leave",
        ),
    )
    employee = db.relationship("Employee", back_populates="availability")


class Training(db.Model):
    __tablename__ = "trainings"

    training_id = db.Column(db.String(24), primary_key=True)
    employee_id = db.Column(
        db.String(16), db.ForeignKey("employees.employee_id"), nullable=False
    )
    skill_id = db.Column(db.String(24), db.ForeignKey("skills.skill_id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    hours = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="planned")

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_training_dates"),
        CheckConstraint("hours > 0", name="ck_training_hours"),
        CheckConstraint(
            "status IN ('planned', 'in_progress', 'completed', 'cancelled')",
            name="ck_training_status",
        ),
    )
    employee = db.relationship("Employee", back_populates="trainings")
    skill = db.relationship("Skill")


class GapAnalysis(db.Model):
    __tablename__ = "gap_analyses"

    gap_id = db.Column(db.String(48), primary_key=True)
    demand_id = db.Column(
        db.String(64), db.ForeignKey("demand_plans.demand_id"), nullable=False
    )
    project_id = db.Column(
        db.String(24), db.ForeignKey("projects.project_id"), nullable=False
    )
    skill_id = db.Column(db.String(24), db.ForeignKey("skills.skill_id"), nullable=False)
    role_id = db.Column(db.String(24), db.ForeignKey("roles.role_id"), nullable=False)
    gap_type = db.Column(db.String(24), nullable=False)
    shortage = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="open")
    analyzed_on = db.Column(db.Date, nullable=False)

    __table_args__ = (
        UniqueConstraint("demand_id", "gap_type", name="uq_gap_demand_type"),
        CheckConstraint(
            "gap_type IN ('missing_skill', 'proficiency', 'stale_skill', 'capacity')",
            name="ck_gap_type",
        ),
        CheckConstraint("shortage > 0", name="ck_gap_shortage"),
        CheckConstraint(
            "status IN ('open', 'mitigated', 'closed')", name="ck_gap_status"
        ),
    )
    demand = db.relationship("DemandPlan")
    project = db.relationship("Project")
    skill = db.relationship("Skill")
    role = db.relationship("Role")


class DemandImportEvent(db.Model):
    __tablename__ = "demand_import_events"

    event_id = db.Column(db.String(32), primary_key=True)
    demand_id = db.Column(
        db.String(64), db.ForeignKey("demand_plans.demand_id"), nullable=False
    )
    source_reference = db.Column(db.String(64), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    received_at = db.Column(db.DateTime, nullable=False, default=utc_now_naive)

    demand = db.relationship("DemandPlan")


class AnomalyGroundTruth(db.Model):
    __tablename__ = "anomaly_ground_truth"

    ground_truth_id = db.Column(db.String(32), primary_key=True)
    issue_type = db.Column(db.String(40), nullable=False)
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.String(64), nullable=False)
    expected_detection = db.Column(db.String(240), nullable=False)
    ground_truth_label = db.Column(db.String(20), nullable=False, default="anomaly")
    details = db.Column(db.Text, nullable=False, default="")
    recorded_at = db.Column(db.Date, nullable=False, default=date.today)

    __table_args__ = (
        CheckConstraint(
            "ground_truth_label IN ('anomaly', 'baseline')",
            name="ck_ground_truth_label",
        ),
    )


class AuditEvent(db.Model):
    __tablename__ = "audit_events"

    audit_id = db.Column(db.String(32), primary_key=True)
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.String(64), nullable=False)
    action = db.Column(db.String(40), nullable=False)
    event_time = db.Column(db.DateTime, nullable=False, default=utc_now_naive)
    details = db.Column(db.Text, nullable=False, default="")
