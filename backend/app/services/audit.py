from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    action: str,
    actor_id=None,
    subject_type: str | None = None,
    subject_id=None,
    ip: str | None = None,
    **details,
) -> None:
    """Add an audit entry to the current transaction (committed with it)."""
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            action=action,
            subject_type=subject_type,
            subject_id=str(subject_id) if subject_id else None,
            details={k: (str(v) if not isinstance(v, int | float | bool | list | dict | None) else v)
                     for k, v in details.items()},
            ip_address=ip,
        )
    )
