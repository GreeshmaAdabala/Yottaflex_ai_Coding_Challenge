import calendar
from collections import defaultdict
from datetime import date, timedelta
from math import ceil

from sqlalchemy import func

from database.db import db
from database.models import (
    Allocation,
    Availability,
    DemandImportEvent,
    DemandPlan,
    Employee,
    EmployeeSkill,
    GapAnalysis,
    Project,
)


def _week_starts(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=7)


def detect_anomalies(session=None, as_of=date(2026, 1, 1)):
    """Detect anomalies from operational records; ground-truth labels are never read."""
    session = session or db.session
    results = []
    employees = {
        employee.employee_id: employee
        for employee in session.query(Employee).all()
    }

    allocations_by_employee = defaultdict(list)
    for allocation in session.query(Allocation).order_by(
        Allocation.employee_id, Allocation.start_date, Allocation.allocation_id
    ):
        allocations_by_employee[allocation.employee_id].append(allocation)
        employee = employees[allocation.employee_id]
        if allocation.weekly_hours > employee.weekly_hours:
            results.append(
                {
                    "issue_type": "allocation_exceeds_availability",
                    "entity_type": "Allocation",
                    "entity_id": allocation.allocation_id,
                    "expected_detection": "Allocated weekly hours exceed contracted weekly capacity.",
                }
            )

    for employee_id, allocations in allocations_by_employee.items():
        for index, left in enumerate(allocations):
            for right in allocations[index + 1 :]:
                if right.start_date > left.end_date:
                    break
                if left.project_id != right.project_id and max(
                    left.start_date, right.start_date
                ) <= min(left.end_date, right.end_date):
                    pair_id = "|".join(sorted((left.allocation_id, right.allocation_id)))
                    results.append(
                        {
                            "issue_type": "overlapping_projects",
                            "entity_type": "Allocation",
                            "entity_id": right.allocation_id,
                            "pair_id": pair_id,
                            "expected_detection": "One employee is assigned to distinct projects over overlapping dates.",
                        }
                    )

    for profile in session.query(EmployeeSkill).all():
        stale = (
            profile.verification_status != "verified"
            or (profile.expires_on is not None and profile.expires_on < as_of)
            or profile.verified_on < as_of - timedelta(days=365)
        )
        if stale:
            results.append(
                {
                    "issue_type": "stale_skill_current",
                    "entity_type": "EmployeeSkill",
                    "entity_id": profile.employee_skill_id,
                    "expected_detection": "Skill verification older than 365 days or expired.",
                }
            )

    duplicate_refs = (
        session.query(
            DemandImportEvent.source_reference,
            func.count(DemandImportEvent.event_id).label("event_count"),
        )
        .group_by(DemandImportEvent.source_reference)
        .having(func.count(DemandImportEvent.event_id) > 1)
        .all()
    )
    for source_reference, _count in duplicate_refs:
        events = (
            session.query(DemandImportEvent)
            .filter_by(source_reference=source_reference)
            .order_by(DemandImportEvent.event_id)
            .all()
        )
        for duplicate in events[1:]:
            results.append(
                {
                    "issue_type": "demand_double_counted",
                    "entity_type": "DemandImportEvent",
                    "entity_id": duplicate.event_id,
                    "expected_detection": "Repeated source reference is deduplicated by demand_id.",
                }
            )
    return results


def calculate_utilization(employee_id, period_start, period_end, session=None):
    """Return capacity, allocated hours, utilization percent, and utilization class."""
    session = session or db.session
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise ValueError(f"Unknown employee_id: {employee_id}")

    availability_rows = (
        session.query(Availability)
        .filter(
            Availability.employee_id == employee_id,
            Availability.period_start <= period_end,
            Availability.period_end >= period_start,
        )
        .all()
    )
    effective_capacity = 0.0
    for availability in availability_rows:
        overlap_start = max(period_start, availability.period_start)
        overlap_end = min(period_end, availability.period_end)
        overlap_days = (overlap_end - overlap_start).days + 1
        period_days = (availability.period_end - availability.period_start).days + 1
        monthly_effective = availability.capacity_hours - availability.leave_hours
        effective_capacity += monthly_effective * overlap_days / period_days

    allocations = (
        session.query(Allocation)
        .filter(
            Allocation.employee_id == employee_id,
            Allocation.start_date <= period_end,
            Allocation.end_date >= period_start,
            Allocation.status.in_(("active", "planned")),
        )
        .all()
    )
    allocated_hours = 0.0
    for allocation in allocations:
        overlap_start = max(period_start, allocation.start_date)
        overlap_end = min(period_end, allocation.end_date)
        overlap_days = (overlap_end - overlap_start).days + 1
        allocated_hours += allocation.weekly_hours * overlap_days / 7

    utilization = (
        allocated_hours / effective_capacity * 100 if effective_capacity > 0 else 0.0
    )
    classification = (
        "overutilized"
        if utilization > 100
        else "underutilized"
        if utilization < 50
        else "normally utilized"
    )
    return {
        "employee_id": employee_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "available_hours": round(effective_capacity, 2),
        "allocated_hours": round(allocated_hours, 2),
        "utilization_pct": round(utilization, 2),
        "classification": classification,
    }


def calculate_workforce_utilization(period_start, period_end, session=None, limit=None):
    session = session or db.session
    employees_query = session.query(Employee).filter(Employee.status == "active").order_by(
        Employee.employee_id
    )
    if limit is not None:
        employees_query = employees_query.limit(limit)
    employees = employees_query.all()
    employee_ids = [employee.employee_id for employee in employees]
    if not employee_ids:
        return []
    capacity_by_employee = defaultdict(float)
    for availability in session.query(Availability).filter(
        Availability.employee_id.in_(employee_ids),
        Availability.period_start <= period_end,
        Availability.period_end >= period_start,
    ):
        overlap_start = max(period_start, availability.period_start)
        overlap_end = min(period_end, availability.period_end)
        overlap_days = (overlap_end - overlap_start).days + 1
        period_days = (availability.period_end - availability.period_start).days + 1
        capacity_by_employee[availability.employee_id] += (
            (availability.capacity_hours - availability.leave_hours)
            * overlap_days
            / period_days
        )
    allocations_by_employee = defaultdict(float)
    for allocation in session.query(Allocation).filter(
        Allocation.employee_id.in_(employee_ids),
        Allocation.start_date <= period_end,
        Allocation.end_date >= period_start,
        Allocation.status.in_(("active", "planned")),
    ):
        overlap_start = max(period_start, allocation.start_date)
        overlap_end = min(period_end, allocation.end_date)
        overlap_days = (overlap_end - overlap_start).days + 1
        allocations_by_employee[allocation.employee_id] += (
            allocation.weekly_hours * overlap_days / 7
        )
    output = []
    for employee in employees:
        capacity = capacity_by_employee[employee.employee_id]
        allocated = allocations_by_employee[employee.employee_id]
        utilization = allocated / capacity * 100 if capacity > 0 else 0.0
        output.append(
            {
                "employee_id": employee.employee_id,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "available_hours": round(capacity, 2),
                "allocated_hours": round(allocated, 2),
                "utilization_pct": round(utilization, 2),
                "classification": (
                    "overutilized"
                    if utilization > 100
                    else "underutilized"
                    if utilization < 50
                    else "normally utilized"
                ),
            }
        )
    return output


def find_skill_gaps(
    period_start=date(2026, 1, 1), weeks=8, session=None, persist=False
):
    """Find shortages in a bounded demand window with links to their demand records."""
    session = session or db.session
    period_end = period_start + timedelta(days=weeks * 7 - 1)
    demands = (
        session.query(DemandPlan)
        .filter(
            DemandPlan.period_start <= period_end,
            DemandPlan.period_end >= period_start,
        )
        .order_by(DemandPlan.period_start, DemandPlan.demand_id)
        .all()
    )
    employees = (
        session.query(Employee)
        .filter(Employee.status == "active")
        .all()
    )
    employees_by_role = defaultdict(list)
    for employee in employees:
        employees_by_role[employee.role_id].append(employee)
    profiles = {
        (profile.employee_id, profile.skill_id): profile
        for profile in session.query(EmployeeSkill).all()
    }
    assignments = defaultdict(list)
    for allocation in session.query(Allocation).filter(
        Allocation.status.in_(("planned", "active"))
    ):
        assignments[allocation.employee_id].append(allocation)
    availability = {}
    for record in session.query(Availability).all():
        availability[(record.employee_id, record.period_start.year, record.period_start.month)] = record

    gaps = []
    for demand in demands:
        employees_for_role = employees_by_role.get(demand.role_id, [])
        valid_available = 0
        matching_skill = 0
        low_proficiency = 0
        stale_profiles = 0
        for employee in employees_for_role:
            profile = profiles.get((employee.employee_id, demand.skill_id))
            if profile is None:
                continue
            matching_skill += 1
            stale = (
                profile.verification_status != "verified"
                or (profile.expires_on is not None and profile.expires_on < demand.period_start)
                or profile.verified_on < demand.period_start - timedelta(days=365)
            )
            if stale:
                stale_profiles += 1
                continue
            if profile.proficiency < demand.required_proficiency:
                low_proficiency += 1
                continue

            assigned = sum(
                allocation.weekly_hours
                for allocation in assignments[employee.employee_id]
                if allocation.start_date <= demand.period_end
                and allocation.end_date >= demand.period_start
            )
            month_key = (
                employee.employee_id,
                demand.period_start.year,
                demand.period_start.month,
            )
            available_record = availability.get(month_key)
            leave_ratio = (
                available_record.leave_hours / available_record.capacity_hours
                if available_record and available_record.capacity_hours > 0
                else 0.0
            )
            spare_hours = employee.weekly_hours * (1 - leave_ratio) - assigned
            if spare_hours >= min(8.0, demand.required_hours / demand.required_headcount):
                valid_available += 1

        shortage = max(0, demand.required_headcount - valid_available)
        if not shortage:
            continue
        if stale_profiles and matching_skill <= stale_profiles:
            gap_type = "stale_skill"
        elif low_proficiency and matching_skill <= low_proficiency + stale_profiles:
            gap_type = "proficiency"
        elif not matching_skill:
            gap_type = "missing_skill"
        else:
            gap_type = "capacity"
        gaps.append(
            {
                "gap_id": f"GAP-{demand.demand_id}",
                "demand_id": demand.demand_id,
                "project_id": demand.project_id,
                "role_id": demand.role_id,
                "skill_id": demand.skill_id,
                "gap_type": gap_type,
                "shortage": shortage,
                "required_headcount": demand.required_headcount,
                "available_qualified": valid_available,
                "required_hours": demand.required_hours,
            }
        )

    if persist:
        session.query(GapAnalysis).delete(synchronize_session=False)
        session.add_all(
            [
                GapAnalysis(
                    gap_id=gap["gap_id"],
                    demand_id=gap["demand_id"],
                    project_id=gap["project_id"],
                    role_id=gap["role_id"],
                    skill_id=gap["skill_id"],
                    gap_type=gap["gap_type"],
                    shortage=gap["shortage"],
                    status="open",
                    analyzed_on=period_start,
                )
                for gap in gaps
            ]
        )
        session.commit()
    return gaps


def build_recommendations(gaps, session=None):
    """Produce explainable actions only for demand-backed skill/capacity shortages."""
    session = session or db.session
    recommendations = []
    for gap in gaps:
        demand = session.get(DemandPlan, gap["demand_id"])
        if demand is None:
            raise ValueError(f"Gap references missing demand: {gap['demand_id']}")
        project = session.get(Project, demand.project_id)
        action, reason = {
            "missing_skill": (
                "hire",
                "No active employee in the required role has the requested skill profile.",
            ),
            "proficiency": (
                "train",
                "Existing skill holders do not meet the demanded proficiency level.",
            ),
            "stale_skill": (
                "reverify",
                "Potentially qualified employees have expired or stale verification.",
            ),
            "capacity": (
                "reassign",
                "Qualified employees are committed; reassign them or redistribute their workload.",
            ),
        }[gap["gap_type"]]
        recommendations.append(
            {
                "action": action,
                "alternative_action": (
                    "redistribute" if action == "reassign" else None
                ),
                "reason": reason,
                "project_id": project.project_id,
                "project_name": project.name,
                "demand_id": demand.demand_id,
                "role_id": demand.role_id,
                "skill_id": demand.skill_id,
                "issue_type": gap["gap_type"],
                "shortage": gap["shortage"],
                "supporting_calculation": (
                    f"{gap['available_qualified']} qualified and available employee(s) "
                    f"for {gap['required_headcount']} required; "
                    f"{gap['required_hours']:.0f} weekly demand hours."
                ),
                "assumption": (
                    "A candidate is available when verified proficiency meets demand and "
                    "remaining contracted weekly hours cover at least 8 hours or the "
                    "per-person demand share."
                ),
            }
        )
    return recommendations
