import json
from uuid import uuid4

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from database.models import (
    AuditEvent,
    Employee,
    Project,
    Role,
    Skill,
    Training,
    utc_now_naive,
)


STATUS_FIELDS = {
    Employee: ("status", "employee_id"),
    Project: ("status", "project_id"),
    Training: ("status", "training_id"),
    Role: ("lifecycle_state", "role_id"),
    Skill: ("lifecycle_state", "skill_id"),
}

ALLOWED_TRANSITIONS = {
    "Employee": {
        ("active", "leave"),
        ("active", "inactive"),
        ("leave", "active"),
        ("leave", "inactive"),
    },
    "Project": {
        ("planned", "active"),
        ("planned", "cancelled"),
        ("active", "completed"),
        ("active", "cancelled"),
    },
    "Training": {
        ("planned", "in_progress"),
        ("planned", "completed"),
        ("planned", "cancelled"),
        ("in_progress", "completed"),
        ("in_progress", "cancelled"),
    },
    "Role": {("active", "retired")},
    "Skill": {("active", "retired")},
}


class InvalidStatusTransition(ValueError):
    """Raised when an entity is assigned a disallowed lifecycle transition."""


def _capture_previous_status(target, value, old_value, initiator):
    return value


def _audit_status_transitions(session, flush_context, instances):
    for entity in session.dirty:
        entity_type = type(entity)
        status_config = STATUS_FIELDS.get(entity_type)
        if status_config is None:
            continue

        state = inspect(entity)
        if not state.persistent or state.deleted:
            continue

        status_field, id_field = status_config
        history = state.attrs[status_field].history
        if not history.has_changes():
            continue
        if not history.deleted or not history.added:
            raise RuntimeError(
                f"Unable to determine previous status for {entity_type.__name__}."
            )

        previous_status = history.deleted[0]
        new_status = history.added[0]
        if previous_status == new_status:
            continue

        name = entity_type.__name__
        if (previous_status, new_status) not in ALLOWED_TRANSITIONS[name]:
            raise InvalidStatusTransition(
                f"Invalid {name} status transition: "
                f"{previous_status} -> {new_status}."
            )

        session.add(
            AuditEvent(
                audit_id=uuid4().hex,
                entity_type=name,
                entity_id=str(getattr(entity, id_field)),
                action="status_transition",
                event_time=utc_now_naive(),
                details=json.dumps(
                    {
                        "from_status": previous_status,
                        "status_field": status_field,
                        "to_status": new_status,
                    },
                    sort_keys=True,
                ),
            )
        )


for model, (status_field, _) in STATUS_FIELDS.items():
    event.listen(
        getattr(model, status_field),
        "set",
        _capture_previous_status,
        retval=True,
        active_history=True,
    )

event.listen(Session, "before_flush", _audit_status_transitions)
