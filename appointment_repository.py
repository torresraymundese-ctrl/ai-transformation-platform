"""Atomic persistence for report-linked diagnostic appointment intent."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import analytics_repository
from models import get_db
from repository import DataConflictError


SHANGHAI = ZoneInfo("Asia/Shanghai")
ALLOWED_TRANSITIONS = {
    "pending": frozenset({"confirmed", "cancelled"}),
    "confirmed": frozenset({"completed", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}
STATUS_TIMESTAMPS = {
    "confirmed": "confirmed_at",
    "completed": "completed_at",
    "cancelled": "cancelled_at",
}


@dataclass(frozen=True)
class AppointmentResult:
    appointment_id: int
    status: str


def submit_appointment_intent(
    assessment_id: int,
    submission_key: str,
    preferred_date,
    time_slot: str,
    note: str,
) -> AppointmentResult:
    """Own the connection while delegating the atomic write primitive."""
    db = get_db()
    try:
        appointment_id = create_appointment(
            db,
            assessment_id,
            submission_key,
            preferred_date,
            time_slot,
            note,
        )
        appointment = get_appointment(db, appointment_id)
        if appointment is None:
            raise RuntimeError("appointment write unavailable")
        return AppointmentResult(appointment_id, appointment["status"])
    finally:
        db.close()


def create_appointment(
    db,
    assessment_id: int,
    submission_key: str,
    preferred_date,
    time_slot: str,
    note: str,
) -> int:
    """Create one pending intent using the assessment's persisted lead."""
    try:
        db.execute("BEGIN IMMEDIATE")
        assessment = db.execute(
            "SELECT lead_id FROM assessments "
            "WHERE id=? AND lead_id IS NOT NULL AND completed_at IS NOT NULL",
            (assessment_id,),
        ).fetchone()
        if assessment is None:
            raise DataConflictError("appointment conflict")
        existing = db.execute(
            "SELECT id,assessment_id,lead_id FROM appointments "
            "WHERE submission_key=?",
            (submission_key,),
        ).fetchone()
        if existing is not None:
            if (
                existing["assessment_id"] == assessment_id
                and existing["lead_id"] == assessment["lead_id"]
            ):
                analytics_repository.insert_server_event(
                    db, "appointment_submitted", assessment_id
                )
                db.commit()
                return existing["id"]
            raise DataConflictError("appointment conflict")
        appointment_id = db.execute(
            "INSERT INTO appointments "
            "(assessment_id,lead_id,submission_key,preferred_date,time_slot,note) "
            "VALUES (?,?,?,?,?,?)",
            (
                assessment_id,
                assessment["lead_id"],
                submission_key,
                preferred_date.isoformat(),
                time_slot,
                note or None,
            ),
        ).lastrowid
        analytics_repository.insert_server_event(
            db, "appointment_submitted", assessment_id
        )
        db.commit()
        return appointment_id
    except sqlite3.IntegrityError:
        db.rollback()
        raise DataConflictError("appointment conflict") from None
    except Exception:
        db.rollback()
        raise


def get_appointment(db, appointment_id: int):
    return db.execute(
        "SELECT * FROM appointments WHERE id=?", (appointment_id,)
    ).fetchone()


def list_appointments(*, status=None):
    """Return appointment tasks with their lead contact context."""
    parameters = ()
    where = ""
    if status:
        where = "WHERE a.status=?"
        parameters = (status,)
    db = get_db()
    try:
        return db.execute(
            "SELECT a.*,l.company_name,l.contact_name,l.phone_normalized,"
            "l.email,l.wechat FROM appointments a "
            "JOIN leads l ON l.id=a.lead_id "
            f"{where} ORDER BY a.preferred_date,a.time_slot,a.id",
            parameters,
        ).fetchall()
    finally:
        db.close()


def transition_appointment_status(appointment_id: int, new_status: str) -> None:
    """Own and close the connection around the existing atomic transition."""
    db = get_db()
    try:
        transition_appointment(db, appointment_id, new_status)
    finally:
        db.close()


def transition_appointment(db, appointment_id: int, new_status: str) -> None:
    """Apply one allowed workflow edge, or fail without modifying the row."""
    try:
        db.execute("BEGIN IMMEDIATE")
        appointment = db.execute(
            "SELECT status FROM appointments WHERE id=?", (appointment_id,)
        ).fetchone()
        if (
            appointment is None
            or not isinstance(new_status, str)
            or new_status not in ALLOWED_TRANSITIONS.get(
                appointment["status"], frozenset()
            )
        ):
            raise DataConflictError("appointment transition conflict")
        timestamp = (
            datetime.now(SHANGHAI)
            .replace(microsecond=0, tzinfo=None)
            .isoformat(sep=" ")
        )
        timestamp_column = STATUS_TIMESTAMPS[new_status]
        updated = db.execute(
            f"UPDATE appointments SET status=?,{timestamp_column}=?,updated_at=? "
            "WHERE id=? AND status=?",
            (
                new_status,
                timestamp,
                timestamp,
                appointment_id,
                appointment["status"],
            ),
        )
        if updated.rowcount != 1:
            raise DataConflictError("appointment transition conflict")
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise DataConflictError("appointment transition conflict") from None
    except Exception:
        db.rollback()
        raise
