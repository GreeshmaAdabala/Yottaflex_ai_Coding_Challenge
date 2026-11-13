# Data dictionary

IDs are immutable primary keys. Dates are inclusive calendar dates; demand periods are consecutive 7-day windows. Text lifecycle and status values are constrained in the database.

## Ten core entities

| Entity | Primary key | Important fields and constraints | Relationships |
|---|---|---|---|
| Employee | `employee_id` (`EMP-000001`) | Name, role, hire date, full/part-time, weekly hours (0–60), experience, active/leave/inactive status, optional lifecycle end | Role; skills, allocations, availability, training |
| Role | `role_id` | Unique name, family, description, active/retired lifecycle | Employees; skills through RoleSkill; demand |
| Skill | `skill_id` (`SKL-000001`) | Unique name, category, description, active/retired lifecycle | Employees through EmployeeSkill; roles through RoleSkill; demand and training |
| EmployeeSkill | `employee_skill_id` | Unique employee/skill pair; proficiency 1–5; verification date; optional expiry no earlier than verification; verified/pending/expired | Employee and Skill |
| Project | `project_id` (`PRJ-2026-000001`) | Client, inclusive dates, planned/active/completed/cancelled status, low/medium/high/critical priority | DemandPlan and Allocation |
| DemandPlan | `demand_id` (`DEM-<project>-<ISO-year>W<week>`) | Project, role, skill, weekly dates, positive hours/headcount, required proficiency 1–5, planned/observed type; unique project-role-skill-period-instance | Project, Role, Skill; GapAnalysis and import evidence |
| Allocation | `allocation_id` (`ALLOC-2026-000001`) | Employee, project, dates, positive weekly hours (≤80), lifecycle status | Employee and Project |
| Availability | `availability_id` | Employee/month unique; gross capacity and leave hours (0≤leave≤capacity) | Employee |
| Training | `training_id` | Employee, skill, dates, positive hours, planned/in-progress/completed/cancelled status | Employee and Skill |
| GapAnalysis | `gap_id` | Demand, project, role, skill, gap type, positive shortage, status and analysis date; one type per demand | DemandPlan, Project, Role, Skill |

## Supporting entities

| Entity | Purpose |
|---|---|
| RoleSkill | Role-to-skill bridge with target proficiency 1–5 and required flag. |
| DemandImportEvent | Ingestion evidence linked to a demand row; a repeated `source_reference` is a duplicate-import anomaly. |
| AnomalyGroundTruth | Separate labels, issue types, affected record IDs, expected detector outcome, and scenario description. Never used as model/detector input. |
| AuditEvent | Optional audit trail for entity/action/time/details. |

## Cardinality and optional fields

Every employee has one role; employee skill associations, allocations, availability rows, and training records are optional collections. Projects may have zero or many demand/allocation records. Demand is always associated with exactly one project, role and skill. A demand may have zero or many gap records and import events. A skill may have no employees or role mappings. Employee lifecycle end, skill expiry, demand observation type, and audit records are optional where applicable.

## Effective capacity

`Availability.capacity_hours` is gross scheduled hours for the month: weekday count × weekly contracted hours ÷ five. `leave_hours` is subtracted before use. For partial-month analysis, the monthly effective capacity is prorated by the number of overlapping calendar days. Allocation hours are stored as weekly hours and prorated by overlapping days ÷ seven. Utilization is allocated hours divided by effective available capacity × 100; zero capacity yields 0% and is identified as no available capacity rather than causing division by zero.
