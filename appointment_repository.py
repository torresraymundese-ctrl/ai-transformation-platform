"""Atomic persistence for report-linked diagnostic appointment intent."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import analytics_repository
from models import get_db
from pagination import Page, PageRequest, parse_bounded_search
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


@dataclass(frozen=True)
class AppointmentFilters:
    status: str | None = None
    search: str | None = None


def parse_appointment_filters(values) -> AppointmentFilters:
    try:
        raw_status = values.get("status", "")
    except (AttributeError, TypeError):
        raw_status = ""
    status = raw_status.strip() if type(raw_status) is str else ""
    return AppointmentFilters(
        status=status if status in ALLOWED_TRANSITIONS else None,
        search=parse_bounded_search(values),
    )


def _appointment_predicate(filters):
    clauses = ["l.anonymized_at IS NULL"]
    parameters = []
    if filters.status is not None:
        clauses.append("a.status=?")
        parameters.append(filters.status)
    if filters.search is not None:
        pattern = "%" + filters.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append(
            "(l.company_name LIKE ? ESCAPE '\\' OR l.contact_name LIKE ? ESCAPE '\\')"
        )
        parameters.extend((pattern, pattern))
    return " WHERE " + " AND ".join(clauses), tuple(parameters)


def query_appointments(
    filters: AppointmentFilters, page: PageRequest
) -> Page[sqlite3.Row]:
    where, parameters = _appointment_predicate(filters)
    base = " FROM appointments a JOIN leads l ON l.id=a.lead_id"
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*)" + base + where, parameters).fetchone()[0]
        if total == 0:
            return Page((), 1, page.per_page, 0, 0)
        total_pages = (total + page.per_page - 1) // page.per_page
        page_number = min(page.page, total_pages)
        rows = tuple(
            db.execute(
                "SELECT a.*,l.company_name,l.contact_name,l.phone_normalized,l.email,l.wechat" +
                base + where + " ORDER BY a.preferred_date ASC,a.time_slot ASC,a.id ASC LIMIT ? OFFSET ?",
                (*parameters, page.per_page, (page_number - 1) * page.per_page),
            ).fetchall()
        )
        return Page(rows, page_number, page.per_page, total, total_pages)
    finally:
        db.close()


def submit_appointment_intent(
    assessment_id: int,
    submission_key: str,
    preferred_date,
    time_slot: str,
    note: str,
    submitted_at=None,
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
            submitted_at,
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
    submitted_at=None,
) -> int:
    """Create one pending intent using the assessment's persisted lead."""
    submitted_at = submitted_at or datetime.now(SHANGHAI).replace(
        tzinfo=None, microsecond=0
    )
    if not isinstance(submitted_at, datetime):
        raise TypeError("appointment timestamp must be a datetime")
    timestamp = submitted_at.replace(tzinfo=None, microsecond=0).isoformat(
        sep=" "
    )
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
                    db,
                    "appointment_submitted",
                    assessment_id,
                    created_at=submitted_at,
                )
                db.commit()
                return existing["id"]
            raise DataConflictError("appointment conflict")
        appointment_id = db.execute(
            "INSERT INTO appointments "
            "(assessment_id,lead_id,submission_key,preferred_date,time_slot,note,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                assessment_id,
                assessment["lead_id"],
                submission_key,
                preferred_date.isoformat(),
                time_slot,
                note or None,
                timestamp,
                timestamp,
            ),
        ).lastrowid
        analytics_repository.insert_server_event(
            db,
            "appointment_submitted",
            assessment_id,
            created_at=submitted_at,
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
