"""Minimal allowlisted persistence for server-critical completion events."""

from validation import ValidationError


COMPLETION_EVENTS = frozenset({"assessment_completed", "lead_submitted"})


def insert_server_event(db, event_name: str, assessment_id: int) -> None:
    if event_name not in COMPLETION_EVENTS:
        raise ValidationError("event_name has an invalid value")
    db.execute(
        "INSERT OR IGNORE INTO analytics_events (event_name,assessment_id) "
        "VALUES (?,?)",
        (event_name, assessment_id),
    )
