import calendar
import random
from collections import defaultdict
from datetime import date, datetime, timedelta

from faker import Faker
from sqlalchemy import func

from database.db import db
from database.models import (
    Allocation,
    AnomalyGroundTruth,
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


ROLE_NAMES = [
    ("Data Analyst", "Data"),
    ("Data Engineer", "Data"),
    ("Data Scientist", "Data"),
    ("Machine Learning Engineer", "AI"),
    ("AI Product Manager", "Product"),
    ("Backend Engineer", "Engineering"),
    ("Frontend Engineer", "Engineering"),
    ("Full Stack Engineer", "Engineering"),
    ("Cloud Architect", "Cloud"),
    ("DevOps Engineer", "Cloud"),
    ("Cybersecurity Analyst", "Security"),
    ("UX Designer", "Design"),
    ("Product Designer", "Design"),
    ("Business Analyst", "Business"),
    ("Project Manager", "Delivery"),
]

SKILL_CATEGORIES = [
    "Python", "SQL", "Machine Learning", "Cloud", "Data Engineering",
    "Visualization", "Statistics", "Product", "Agile", "Security",
    "JavaScript", "Java", "Infrastructure", "Design", "Communication",
    "Testing", "Natural Language Processing", "Databases", "DevOps", "AI",
]

SKILL_SPECIALTIES = [
    "Foundations", "Modeling", "Automation", "Architecture", "Analytics",
    "Optimization", "Governance", "Deployment", "Research", "Integration",
    "Quality", "Strategy", "Monitoring", "Engineering", "Operations",
]


def _insert_in_batches(session, records, batch_size=2000):
    for offset in range(0, len(records), batch_size):
        session.add_all(records[offset : offset + batch_size])
        session.flush()


def _month_ranges(start, end):
    month = date(start.year, start.month, 1)
    while month <= end:
        final_day = calendar.monthrange(month.year, month.month)[1]
        yield month, date(month.year, month.month, final_day)
        if month.month == 12:
            month = date(month.year + 1, 1, 1)
        else:
            month = date(month.year, month.month + 1, 1)


def _working_days(start, end):
    return sum(
        (start + timedelta(days=offset)).weekday() < 5
        for offset in range((end - start).days + 1)
    )


def _ground_truth(
    issue_type, entity_type, entity_id, expected_detection, details, recorded_at
):
    return AnomalyGroundTruth(
        ground_truth_id=f"GT-{issue_type[:4].upper()}",
        issue_type=issue_type,
        entity_type=entity_type,
        entity_id=entity_id,
        expected_detection=expected_detection,
        ground_truth_label="anomaly",
        details=details,
        recorded_at=recorded_at,
    )


def generate_dataset(
    employees=50,
    skills=30,
    projects=10,
    seed=20261022,
    horizon_start=date(2026, 1, 1),
    horizon_weeks=52,
    reset=False,
):
    """Create a deterministic starter or full synthetic dataset in the active app DB."""
    session = db.session
    if reset:
        db.drop_all()
        db.create_all()
    elif session.query(Employee.employee_id).first():
        raise ValueError("Database already contains employees; pass reset=True to replace it.")
    if employees <= 0 or skills <= 0 or projects <= 0 or horizon_weeks <= 0:
        raise ValueError("Dataset sizes and horizon_weeks must be positive.")
    if skills > len(SKILL_CATEGORIES) * len(SKILL_SPECIALTIES):
        raise ValueError("The deterministic skill catalog supports at most 300 skills.")

    rng = random.Random(seed)
    faker = Faker("en_US")
    faker.seed_instance(seed)
    horizon_end = horizon_start + timedelta(days=7 * horizon_weeks - 1)
    week_starts = [
        horizon_start + timedelta(days=7 * index) for index in range(horizon_weeks)
    ]

    role_records = [
        Role(
            role_id=f"ROLE-{index + 1:03d}",
            name=name,
            family=family,
            description=f"Workforce role in the {family.lower()} family.",
        )
        for index, (name, family) in enumerate(ROLE_NAMES)
    ]
    _insert_in_batches(session, role_records)
    skill_names = [
        f"{category} {specialty}"
        for category in SKILL_CATEGORIES
        for specialty in SKILL_SPECIALTIES
    ][:skills]
    skill_records = [
        Skill(
            skill_id=f"SKL-{index + 1:06d}",
            name=name,
            category=name.split(" ", 1)[0],
            description=f"Synthetic capability for {name.lower()}.",
        )
        for index, name in enumerate(skill_names)
    ]
    _insert_in_batches(session, skill_records)

    role_skills_by_role = {}
    role_skill_records = []
    skill_ids = [record.skill_id for record in skill_records]
    for role in role_records:
        count = min(len(skill_ids), rng.randint(6, min(12, max(6, len(skill_ids)))))
        selected = rng.sample(skill_ids, count)
        role_skills_by_role[role.role_id] = selected
        role_skill_records.extend(
            RoleSkill(
                role_id=role.role_id,
                skill_id=skill_id,
                target_proficiency=rng.randint(2, 4),
                is_required=rng.random() < 0.8,
            )
            for skill_id in selected
        )
    _insert_in_batches(session, role_skill_records)

    employee_roles = {}
    employee_hours = {}
    employee_records = []
    for index in range(1, employees + 1):
        employee_id = f"EMP-{index:06d}"
        role_id = rng.choice(role_records).role_id
        employment_type = "part_time" if rng.random() < 0.16 else "full_time"
        weekly_hours = rng.choice([16, 20, 24, 28]) if employment_type == "part_time" else rng.choice([32, 36, 40])
        hire_date = horizon_start - timedelta(days=rng.randint(30, 3650))
        employee_roles[employee_id] = role_id
        employee_hours[employee_id] = weekly_hours
        employee_records.append(
            Employee(
                employee_id=employee_id,
                full_name=faker.name(),
                role_id=role_id,
                hire_date=hire_date,
                employment_type=employment_type,
                weekly_hours=weekly_hours,
                experience_years=round(rng.uniform(0.5, 25), 1),
                status="active",
            )
        )
    _insert_in_batches(session, employee_records)

    employee_skill_records = []
    profile_by_employee_skill = {}
    for employee_id, role_id in employee_roles.items():
        role_skill_ids = role_skills_by_role[role_id]
        number = min(len(skill_ids), rng.randint(4, min(10, max(4, len(skill_ids)))))
        selected = set(rng.sample(role_skill_ids, min(number, len(role_skill_ids))))
        if len(selected) < number:
            remaining = [skill_id for skill_id in skill_ids if skill_id not in selected]
            selected.update(rng.sample(remaining, number - len(selected)))
        for skill_id in sorted(selected):
            verified_on = horizon_start - timedelta(days=rng.randint(0, 330))
            employee_skill_id = f"{employee_id}-{skill_id}"
            record = EmployeeSkill(
                employee_skill_id=employee_skill_id,
                employee_id=employee_id,
                skill_id=skill_id,
                proficiency=rng.randint(1, 5),
                verified_on=verified_on,
                expires_on=verified_on + timedelta(days=730),
                verification_status="verified",
            )
            employee_skill_records.append(record)
            profile_by_employee_skill[(employee_id, skill_id)] = record
    _insert_in_batches(session, employee_skill_records)

    projects_by_role = defaultdict(list)
    project_records = []
    project_skill = {}
    project_role = {}
    for index in range(1, projects + 1):
        project_id = f"PRJ-2026-{index:06d}"
        role_id = rng.choice(role_records).role_id
        role_skills = role_skills_by_role[role_id]
        if role_skills and rng.random() < 0.82:
            skill_id = rng.choice(role_skills)
        else:
            skill_id = rng.choice(skill_ids)
        if index == 1:
            duration_weeks = horizon_weeks
            start = week_starts[0]
        else:
            duration_weeks = rng.randint(6, max(6, min(30, horizon_weeks)))
            latest_start_index = max(0, horizon_weeks - duration_weeks)
            start = week_starts[rng.randint(0, latest_start_index)]
        end = min(start + timedelta(days=duration_weeks * 7 - 1), horizon_end)
        status = "planned" if start > horizon_start + timedelta(days=30) else "active"
        priority = rng.choices(
            ["low", "medium", "high", "critical"], weights=[1, 4, 3, 1]
        )[0]
        project_records.append(
            Project(
                project_id=project_id,
                name=f"{faker.catch_phrase()} Initiative {index:03d}",
                client=faker.company(),
                start_date=start,
                end_date=end,
                status=status,
                priority=priority,
            )
        )
        projects_by_role[role_id].append(project_id)
        project_skill[project_id] = skill_id
        project_role[project_id] = role_id
    _insert_in_batches(session, project_records)

    demand_records = []
    demand_keys = []
    for project in project_records:
        role_id = project_role[project.project_id]
        skill_id = project_skill[project.project_id]
        for week_start in week_starts:
            week_end = min(week_start + timedelta(days=6), horizon_end)
            if week_start < project.start_date or week_start > project.end_date:
                continue
            iso_year, iso_week, _ = week_start.isocalendar()
            demand_id = f"DEM-{project.project_id}-{iso_year}W{iso_week:02d}"
            headcount = rng.randint(1, 4)
            demand_records.append(
                DemandPlan(
                    demand_id=demand_id,
                    project_id=project.project_id,
                    role_id=role_id,
                    skill_id=skill_id,
                    period_start=week_start,
                    period_end=min(week_end, project.end_date),
                    required_hours=float(headcount * rng.choice([28, 32, 36, 40])),
                    required_headcount=headcount,
                    required_proficiency=rng.randint(2, 5),
                    demand_type="planned",
                    instance_number=1,
                )
            )
            demand_keys.append(demand_id)
    _insert_in_batches(session, demand_records)

    import_events = [
        DemandImportEvent(
            event_id=f"DME-{index:08d}",
            demand_id=demand_id,
            source_reference=demand_id,
            payload_hash=f"{seed:08x}{index:056x}",
            received_at=datetime.combine(horizon_start, datetime.min.time()),
        )
        for index, demand_id in enumerate(demand_keys, start=1)
    ]
    _insert_in_batches(session, import_events)

    availability_records = []
    months = list(_month_ranges(horizon_start, horizon_end))
    for employee in employee_records:
        daily_hours = employee.weekly_hours / 5
        for period_start, period_end in months:
            workdays = _working_days(period_start, period_end)
            capacity = round(workdays * daily_hours, 2)
            leave_days = rng.randint(0, min(4, workdays))
            leave_hours = round(min(capacity, leave_days * daily_hours), 2)
            availability_records.append(
                Availability(
                    availability_id=f"{employee.employee_id}-{period_start:%Y%m}",
                    employee_id=employee.employee_id,
                    period_start=period_start,
                    period_end=period_end,
                    capacity_hours=capacity,
                    leave_hours=leave_hours,
                )
            )
    _insert_in_batches(session, availability_records)

    employee_ids_by_role = defaultdict(list)
    for employee_id, role_id in employee_roles.items():
        employee_ids_by_role[role_id].append(employee_id)
    rng_alloc = rng
    busy_intervals = defaultdict(list)
    allocation_records = []
    allocation_number = 1
    for employee in employee_records:
        if rng_alloc.random() >= 0.76:
            continue
        assignments = 2 if rng_alloc.random() < 0.12 else 1
        for _ in range(assignments):
            candidates = projects_by_role.get(employee.role_id, [])
            if not candidates:
                break
            selected_project = None
            for project_id in rng_alloc.sample(candidates, min(12, len(candidates))):
                project = next(item for item in project_records if item.project_id == project_id)
                if all(
                    project.end_date < occupied_start or project.start_date > occupied_end
                    for occupied_start, occupied_end in busy_intervals[employee.employee_id]
                ):
                    selected_project = project
                    break
            if selected_project is None:
                break
            duration = (selected_project.end_date - selected_project.start_date).days
            allocation_start = selected_project.start_date
            allocation_end = selected_project.end_date
            assigned_fraction = rng.uniform(0.28, 0.48) if assignments == 1 else 0.28
            weekly_hours = round(employee.weekly_hours * assigned_fraction, 2)
            allocation_records.append(
                Allocation(
                    allocation_id=f"ALLOC-2026-{allocation_number:06d}",
                    employee_id=employee.employee_id,
                    project_id=selected_project.project_id,
                    start_date=allocation_start,
                    end_date=allocation_end,
                    weekly_hours=weekly_hours,
                    status="active",
                )
            )
            allocation_number += 1
            busy_intervals[employee.employee_id].append((allocation_start, allocation_end))
    _insert_in_batches(session, allocation_records)

    training_records = []
    for index, employee in enumerate(employee_records, start=1):
        if rng.random() >= 0.18:
            continue
        skill_id = rng.choice(skill_ids)
        start = horizon_start + timedelta(days=rng.randint(0, max(0, (horizon_end - horizon_start).days - 21)))
        training_records.append(
            Training(
                training_id=f"TRN-2026-{len(training_records) + 1:06d}",
                employee_id=employee.employee_id,
                skill_id=skill_id,
                start_date=start,
                end_date=start + timedelta(days=14),
                hours=float(rng.choice([8, 12, 16, 24])),
                status="planned",
            )
        )
    _insert_in_batches(session, training_records)

    session.flush()
    duplicate_demand = demand_records[0]
    duplicate_event_id = "DME-DUP-00000001"
    session.add(
        DemandImportEvent(
            event_id=duplicate_event_id,
            demand_id=duplicate_demand.demand_id,
            source_reference=duplicate_demand.demand_id,
            payload_hash=f"{seed:08x}duplicate".ljust(64, "0")[:64],
            received_at=datetime.combine(horizon_start, datetime.min.time()),
        )
    )

    stale_profile = next(iter(profile_by_employee_skill.values()))
    stale_profile.verified_on = horizon_start - timedelta(days=900)
    stale_profile.expires_on = horizon_start + timedelta(days=365)
    stale_profile.verification_status = "verified"

    overbook_choice = None
    for overbook_project in project_records:
        for week_start in week_starts:
            if not overbook_project.start_date <= week_start <= overbook_project.end_date:
                continue
            week_end = min(week_start + timedelta(days=6), overbook_project.end_date)
            for candidate in employee_records:
                if all(
                    week_end < occupied_start or week_start > occupied_end
                    for occupied_start, occupied_end in busy_intervals[
                        candidate.employee_id
                    ]
                ):
                    overbook_choice = (candidate, overbook_project, week_start, week_end)
                    break
            if overbook_choice:
                break
        if overbook_choice:
            break
    if overbook_choice is None:
        raise RuntimeError("Could not construct the required over-capacity anomaly.")
    overbook_employee, overbook_project, over_capacity_start, over_capacity_end = (
        overbook_choice
    )
    over_capacity_id = f"ALLOC-2026-{allocation_number:06d}"
    over_capacity_hours = min(80, overbook_employee.weekly_hours + 32)
    session.add(
        Allocation(
            allocation_id=over_capacity_id,
            employee_id=overbook_employee.employee_id,
            project_id=overbook_project.project_id,
            start_date=over_capacity_start,
            end_date=over_capacity_end,
            weekly_hours=over_capacity_hours,
            status="active",
            is_injected_anomaly=True,
        )
    )
    allocation_number += 1

    overlapping_projects = None
    for role_id, role_project_ids in projects_by_role.items():
        for left_index, left_id in enumerate(role_project_ids):
            left = next(item for item in project_records if item.project_id == left_id)
            for right_id in role_project_ids[left_index + 1 :]:
                right = next(item for item in project_records if item.project_id == right_id)
                overlap_start = max(left.start_date, right.start_date)
                overlap_end = min(left.end_date, right.end_date)
                if overlap_start <= overlap_end:
                    employee = next(
                        (
                            candidate
                            for candidate in employee_records
                            if candidate.role_id == role_id
                            and all(
                                overlap_end < occupied_start
                                or overlap_start > occupied_end
                                for occupied_start, occupied_end in busy_intervals[
                                    candidate.employee_id
                                ]
                            )
                        ),
                        None,
                    )
                    if employee is not None:
                        overlapping_projects = (employee, left, right, overlap_start)
                        break
            if overlapping_projects:
                break
        if overlapping_projects:
            break
    if overlapping_projects is None:
        raise RuntimeError("Could not construct the required overlapping-project anomaly.")
    overlap_employee, left, right, overlap_start = overlapping_projects
    overlap_end = min(overlap_start + timedelta(days=6), left.end_date, right.end_date)
    overlap_ids = []
    for project in (left, right):
        allocation_id = f"ALLOC-2026-{allocation_number:06d}"
        allocation_number += 1
        overlap_ids.append(allocation_id)
        session.add(
            Allocation(
                allocation_id=allocation_id,
                employee_id=overlap_employee.employee_id,
                project_id=project.project_id,
                start_date=overlap_start,
                end_date=overlap_end,
                weekly_hours=min(10, overlap_employee.weekly_hours / 4),
                status="active",
                is_injected_anomaly=True,
            )
        )

    ground_truth = [
        _ground_truth(
            "allocation_exceeds_availability",
            "Allocation",
            over_capacity_id,
            "Allocated weekly hours exceed the employee's contracted weekly capacity.",
            f"A labelled {over_capacity_hours:g}-hour assignment exceeds the employee's "
            f"{overbook_employee.weekly_hours:g}-hour weekly capacity; baseline assignments remain unchanged.",
            horizon_start,
        ),
        _ground_truth(
            "stale_skill_current",
            "EmployeeSkill",
            stale_profile.employee_skill_id,
            "Skill verification older than 365 days is classified as stale.",
            "Verification predates the horizon by 900 days while the profile status remains verified.",
            horizon_start,
        ),
        _ground_truth(
            "demand_double_counted",
            "DemandImportEvent",
            duplicate_event_id,
            "Repeated source_reference is flagged; demand is counted once by demand_id.",
            f"A second ingestion event repeats source reference {duplicate_demand.demand_id}.",
            horizon_start,
        ),
        _ground_truth(
            "overlapping_projects",
            "Allocation",
            overlap_ids[1],
            "An employee with overlapping date ranges across distinct projects is flagged.",
            f"Allocation pair {overlap_ids[0]} and {overlap_ids[1]} shares dates on different projects.",
            horizon_start,
        ),
    ]
    session.add_all(ground_truth)
    session.commit()
    from modules.analysis import find_skill_gaps

    find_skill_gaps(
        period_start=horizon_start,
        weeks=min(8, horizon_weeks),
        session=session,
        persist=True,
    )

    counts = {
        "employees": employees,
        "roles": len(role_records),
        "skills": skills,
        "role_skills": len(role_skill_records),
        "projects": projects,
        "demand_plans": len(demand_records),
        "allocations": len(allocation_records) + 3,
        "availability": len(availability_records),
        "employee_skills": len(employee_skill_records),
        "trainings": len(training_records),
        "anomaly_ground_truth": len(ground_truth),
        "horizon_weeks": horizon_weeks,
        "seed": seed,
    }
    return counts


def dataset_counts():
    """Return row counts for all project data and supporting tables."""
    models = [
        Role, Skill, RoleSkill, Employee, EmployeeSkill, Project, DemandPlan,
        Allocation, Availability, Training, db.Model.metadata.tables["gap_analyses"],
        DemandImportEvent, AnomalyGroundTruth,
    ]
    counts = {}
    for model in models:
        if isinstance(model, type) and hasattr(model, "__tablename__"):
            table = model.__tablename__
            counts[table] = db.session.query(func.count()).select_from(model).scalar()
        else:
            table = model.name
            counts[table] = db.session.execute(
                db.select(func.count()).select_from(model)
            ).scalar_one()
    return counts
