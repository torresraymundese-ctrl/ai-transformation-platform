"""Lead, consent, privacy-request, and retention persistence."""

from datetime import date, datetime, timedelta
from html import unescape
import re
import sqlite3
import unicodedata
from zoneinfo import ZoneInfo

import bleach

from models import get_db
from repository import DataConflictError
from validation import (
    ValidationError,
    normalized_mobile,
    validated_email,
    validated_wechat,
)


ORDINARY_QUEUE_STATUSES = ("new", "pending_contact")
LEAD_STATUSES = (
    "new",
    "pending_contact",
    "contacted",
    "diagnosis_scheduled",
    "proposal",
    "won",
    "not_progressing",
)
LEAD_TRANSITIONS = {
    "new": frozenset({"pending_contact"}),
    "pending_contact": frozenset({"contacted"}),
    "contacted": frozenset({"diagnosis_scheduled"}),
    "diagnosis_scheduled": frozenset({"proposal"}),
    "proposal": frozenset({"won", "not_progressing"}),
    "won": frozenset(),
    "not_progressing": frozenset({"pending_contact"}),
}
DATA_REQUEST_TYPES = frozenset(
    {"access", "correction", "withdrawal", "deletion"}
)
DATA_REQUEST_CHANNELS = frozenset({"email", "phone", "wechat", "other"})
DATA_REQUEST_STATUSES = frozenset(
    {"received", "verifying", "completed", "rejected"}
)
ANONYMIZATION_REASONS = frozenset(
    {"retention_expired", "consent_withdrawn", "deletion_requested"}
)
PRIVACY_REASON_BY_REQUEST = {
    "withdrawal": "consent_withdrawn",
    "deletion": "deletion_requested",
}
SHANGHAI = ZoneInfo("Asia/Shanghai")
SCRIPT_OR_STYLE = re.compile(
    r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>"
)
MAINLAND_MOBILE = re.compile(r"(?:86)?1[3-9]\d{9}")


def validate_contact(contact):
    return (
        _required_text(contact.company_name, "company_name", 200),
        _required_text(contact.contact_name, "contact_name", 100),
        normalized_mobile(contact.phone),
        validated_email(contact.email),
        validated_wechat(contact.wechat),
    )


def validate_consent(consent, identity_hash):
    if consent.accepted is not True:
        raise ValidationError("consent must be accepted")
    policy_version = _required_text(consent.policy_version, "policy_version", 50)
    source = _required_text(consent.source, "consent_source", 100)
    if (
        not isinstance(identity_hash, str)
        or not identity_hash
        or len(identity_hash) > 256
    ):
        raise ValidationError("identity_hash has an invalid value")
    return policy_version, source


def find_or_create(
    db, contact, source="website_assessment", submitted_at=None
):
    submitted_at = submitted_at or datetime.now().replace(microsecond=0)
    timestamp = submitted_at.isoformat(sep=" ")
    retention = (submitted_at + timedelta(days=365)).isoformat(sep=" ")
    company_name, contact_name, phone, email, wechat = validate_contact(contact)

    existing = db.execute(
        "SELECT id,status FROM leads WHERE phone_normalized=?",
        (phone,),
    ).fetchone()
    if existing is None:
        return db.execute(
            "INSERT INTO leads "
            "(company_name,contact_name,phone_normalized,email,wechat,source,"
            "retention_expires_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                company_name,
                contact_name,
                phone,
                email or None,
                wechat or None,
                source,
                retention,
                timestamp,
                timestamp,
            ),
        ).lastrowid

    lead_id = existing["id"]
    status = existing["status"]
    new_status = "pending_contact" if status == "not_progressing" else status
    new_retention = None if status == "won" else retention
    db.execute(
        "UPDATE leads SET company_name=?,contact_name=?,email=?,wechat=?,status=?,"
        "retention_expires_at=?,updated_at=? WHERE id=?",
        (
            company_name,
            contact_name,
            email or None,
            wechat or None,
            new_status,
            new_retention,
            timestamp,
            lead_id,
        ),
    )
    if new_status != status:
        db.execute(
            "INSERT INTO lead_status_history "
            "(lead_id,previous_status,new_status,actor_text,created_at) "
            "VALUES (?,?,?,?,?)",
            (lead_id, status, new_status, "assessment_submission", timestamp),
        )
    return lead_id


def record_consent(db, lead_id, consent, identity_hash, consented_at=None):
    policy_version, source = validate_consent(consent, identity_hash)
    timestamp = (consented_at or datetime.now().replace(microsecond=0)).isoformat(
        sep=" "
    )
    return db.execute(
        "INSERT INTO lead_consents "
        "(lead_id,policy_version,consented_at,source,identity_hash) "
        "VALUES (?,?,?,?,?)",
        (lead_id, policy_version, timestamp, source, identity_hash),
    ).lastrowid


def list_ordinary_queue(db):
    placeholders = ",".join("?" for _ in ORDINARY_QUEUE_STATUSES)
    return db.execute(
        f"SELECT * FROM leads WHERE status IN ({placeholders}) "
        "AND anonymized_at IS NULL ORDER BY created_at,id",
        ORDINARY_QUEUE_STATUSES,
    ).fetchall()


def list_leads(
    *,
    status=None,
    branch=None,
    date_from=None,
    date_to=None,
    include_anonymized=True,
):
    """Return leads matching the small operational filter set."""
    clauses = []
    parameters = []
    if not include_anonymized:
        clauses.append("l.anonymized_at IS NULL")
    if status:
        clauses.append("l.status=?")
        parameters.append(status)
    if branch:
        clauses.append(
            "EXISTS (SELECT 1 FROM assessments a "
            "WHERE a.lead_id=l.id AND a.branch_code=?)"
        )
        parameters.append(branch)
    if date_from:
        clauses.append("date(l.created_at)>=?")
        parameters.append(date_from)
    if date_to:
        clauses.append("date(l.created_at)<=?")
        parameters.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    db = get_db()
    try:
        return db.execute(
            "SELECT l.*,"
            "(SELECT COUNT(*) FROM assessments a WHERE a.lead_id=l.id) "
            "AS assessment_count,"
            "(SELECT a.branch_code FROM assessments a WHERE a.lead_id=l.id "
            "ORDER BY a.completed_at DESC,a.id DESC LIMIT 1) AS latest_branch "
            f"FROM leads l {where} ORDER BY l.created_at DESC,l.id DESC",
            tuple(parameters),
        ).fetchall()
    finally:
        db.close()


def get_lead_detail(lead_id):
    db = get_db()
    try:
        lead = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if lead is None:
            return None
        return {
            "lead": lead,
            "assessments": db.execute(
                "SELECT id,branch_code,subbranch_code,department_code,"
                "overall_score,maturity_code,report_snapshot_json,completed_at "
                "FROM assessments WHERE lead_id=? "
                "ORDER BY completed_at DESC,id DESC",
                (lead_id,),
            ).fetchall(),
            "followups": db.execute(
                "SELECT * FROM lead_followups WHERE lead_id=? "
                "ORDER BY effective_at DESC,id DESC",
                (lead_id,),
            ).fetchall(),
            "status_history": db.execute(
                "SELECT * FROM lead_status_history WHERE lead_id=? "
                "ORDER BY created_at DESC,id DESC",
                (lead_id,),
            ).fetchall(),
            "appointments": db.execute(
                "SELECT * FROM appointments WHERE lead_id=? "
                "ORDER BY created_at DESC,id DESC",
                (lead_id,),
            ).fetchall(),
            "data_requests": db.execute(
                "SELECT id,request_type,status,channel,requested_at,"
                "resolution_note,completed_at FROM data_subject_requests "
                "WHERE lead_id=? ORDER BY requested_at DESC,id DESC",
                (lead_id,),
            ).fetchall(),
        }
    finally:
        db.close()


def set_lead_owner(lead_id, owner_text, *, now=None):
    owner_text = _optional_text(owner_text, "owner_text", 100)
    timestamp = _timestamp(now)

    def operation(db):
        lead = _mutable_ordinary_lead(db, lead_id)
        updated = db.execute(
            "UPDATE leads SET owner_text=?,updated_at=? WHERE id=? AND status=?",
            (owner_text or None, timestamp, lead_id, lead["status"]),
        )
        if updated.rowcount != 1:
            raise DataConflictError("lead update conflict")

    _run_immediate(operation)


def transition_lead_status(lead_id, new_status, actor_text, *, now=None):
    if new_status not in LEAD_STATUSES:
        raise ValidationError("new_status has an invalid value")
    actor_text = _required_text(actor_text, "actor_text", 80)
    timestamp = _timestamp(now)

    def operation(db):
        lead = db.execute(
            "SELECT status,anonymized_at FROM leads WHERE id=?", (lead_id,)
        ).fetchone()
        if (
            lead is None
            or lead["anonymized_at"] is not None
            or new_status not in LEAD_TRANSITIONS.get(lead["status"], frozenset())
        ):
            raise DataConflictError("lead transition conflict")
        retention = None if new_status == "won" else _unchanged_retention(db, lead_id)
        updated = db.execute(
            "UPDATE leads SET status=?,retention_expires_at=?,updated_at=? "
            "WHERE id=? AND status=? AND anonymized_at IS NULL",
            (new_status, retention, timestamp, lead_id, lead["status"]),
        )
        if updated.rowcount != 1:
            raise DataConflictError("lead transition conflict")
        db.execute(
            "INSERT INTO lead_status_history "
            "(lead_id,previous_status,new_status,actor_text,created_at) "
            "VALUES (?,?,?,?,?)",
            (lead_id, lead["status"], new_status, actor_text, timestamp),
        )

    _run_immediate(operation)


def add_followup(
    lead_id, note, next_followup_at, actor_text, *, now=None
):
    note = _required_text(note, "followup_note", 2000)
    actor_text = _required_text(actor_text, "actor_text", 80)
    timestamp = _timestamp(now)
    next_timestamp = _optional_timestamp(next_followup_at, "next_followup_at")
    retention = (
        datetime.fromisoformat(timestamp) + timedelta(days=365)
    ).isoformat(sep=" ")

    def operation(db):
        lead = _mutable_ordinary_lead(db, lead_id)
        db.execute(
            "INSERT INTO lead_followups "
            "(lead_id,note,next_followup_at,effective_at,actor_text,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                lead_id,
                note,
                next_timestamp,
                timestamp,
                actor_text,
                timestamp,
            ),
        )
        updated = db.execute(
            "UPDATE leads SET next_followup_at=?,last_effective_followup_at=?,"
            "retention_expires_at=?,updated_at=? WHERE id=? AND status=? "
            "AND anonymized_at IS NULL",
            (
                next_timestamp,
                timestamp,
                retention,
                timestamp,
                lead_id,
                lead["status"],
            ),
        )
        if updated.rowcount != 1:
            raise DataConflictError("lead followup conflict")

    _run_immediate(operation)


def list_data_subject_requests(*, status=None):
    parameters = ()
    where = ""
    if status:
        where = "WHERE r.status=?"
        parameters = (status,)
    db = get_db()
    try:
        return db.execute(
            "SELECT r.id,r.lead_id,r.request_type,r.status,r.channel,"
            "r.requested_at,r.resolution_note,r.completed_at,r.admin_updated_at,"
            "l.company_name,l.contact_name "
            "FROM data_subject_requests r "
            "LEFT JOIN leads l ON l.id=r.lead_id "
            f"{where} ORDER BY r.requested_at DESC,r.id DESC",
            parameters,
        ).fetchall()
    finally:
        db.close()


def create_data_subject_request(
    lead_id,
    request_type,
    channel,
    requested_at,
    identity_hash,
    *,
    now=None,
):
    if request_type not in DATA_REQUEST_TYPES:
        raise ValidationError("request_type has an invalid value")
    if channel not in DATA_REQUEST_CHANNELS:
        raise ValidationError("channel has an invalid value")
    requested_timestamp = _required_timestamp(requested_at, "requested_at")
    if not isinstance(identity_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", identity_hash
    ):
        raise ValidationError("identity_hash has an invalid value")
    timestamp = _timestamp(now)

    def operation(db):
        lead = db.execute(
            "SELECT id FROM leads WHERE id=? AND anonymized_at IS NULL",
            (lead_id,),
        ).fetchone()
        if lead is None:
            raise DataConflictError("data request conflict")
        return db.execute(
            "INSERT INTO data_subject_requests "
            "(lead_id,identity_hash,request_type,status,channel,requested_at,"
            "admin_received_at,admin_updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                lead_id,
                identity_hash,
                request_type,
                "received",
                channel,
                requested_timestamp,
                timestamp,
                timestamp,
            ),
        ).lastrowid

    return _run_immediate(operation)


def transition_data_subject_request(
    request_id, new_status, resolution_note="", *, now=None
):
    if new_status not in {"verifying", "rejected"}:
        raise ValidationError("new_status has an invalid value")
    note = validate_resolution_note(
        resolution_note, required=new_status == "rejected"
    )
    timestamp = _timestamp(now)

    def operation(db):
        row = db.execute(
            "SELECT status FROM data_subject_requests WHERE id=?", (request_id,)
        ).fetchone()
        expected = "received" if new_status == "verifying" else "verifying"
        if row is None or row["status"] != expected:
            raise DataConflictError("data request transition conflict")
        completed_at = timestamp if new_status == "rejected" else None
        updated = db.execute(
            "UPDATE data_subject_requests SET status=?,resolution_note=?,"
            "completed_at=?,admin_updated_at=? WHERE id=? AND status=?",
            (
                new_status,
                note or None,
                completed_at,
                timestamp,
                request_id,
                expected,
            ),
        )
        if updated.rowcount != 1:
            raise DataConflictError("data request transition conflict")

    _run_immediate(operation)


def complete_data_subject_request(
    request_id,
    resolution_note,
    *,
    confirm_anonymization=False,
    now=None,
):
    note = validate_resolution_note(resolution_note, required=True)
    timestamp = _timestamp(now)

    def operation(db):
        request_row = db.execute(
            "SELECT lead_id,request_type,status FROM data_subject_requests "
            "WHERE id=?",
            (request_id,),
        ).fetchone()
        if request_row is None or request_row["status"] != "verifying":
            raise DataConflictError("data request completion conflict")
        reason = PRIVACY_REASON_BY_REQUEST.get(request_row["request_type"])
        if reason is not None:
            if confirm_anonymization is not True:
                raise DataConflictError("data request confirmation conflict")
            anonymize_lead(
                db,
                request_row["lead_id"],
                reason,
                now=datetime.fromisoformat(timestamp),
            )
        updated = db.execute(
            "UPDATE data_subject_requests SET status='completed',"
            "resolution_note=?,completed_at=?,admin_updated_at=? "
            "WHERE id=? AND status='verifying'",
            (note, timestamp, timestamp, request_id),
        )
        if updated.rowcount != 1:
            raise DataConflictError("data request completion conflict")

    _run_immediate(operation)


def validate_resolution_note(value, *, required):
    if not isinstance(value, str):
        raise ValidationError("resolution_note must be text")
    without_active_blocks = SCRIPT_OR_STYLE.sub("", value)
    note = unescape(
        bleach.clean(without_active_blocks, tags=set(), attributes={}, strip=True)
    ).strip()
    if required and not note:
        raise ValidationError("resolution_note is required")
    if len(note) > 1000:
        raise ValidationError("resolution_note is too long")
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", note))
    if "@" in compact:
        raise ValidationError("resolution_note contains a private value")
    digits = []
    for character in compact:
        digit = unicodedata.decimal(character, None)
        if digit is not None:
            digits.append(str(digit))
    if MAINLAND_MOBILE.search("".join(digits)):
        raise ValidationError("resolution_note contains a private value")
    return note


def anonymize_lead(db, lead_id, reason_code, *, now=None):
    """Anonymize one lead inside the caller's existing transaction."""
    if reason_code not in ANONYMIZATION_REASONS:
        raise ValidationError("reason_code has an invalid value")
    lead = db.execute(
        "SELECT status,anonymized_at FROM leads WHERE id=?", (lead_id,)
    ).fetchone()
    if (
        lead is None
        or lead["anonymized_at"] is not None
        or (reason_code == "retention_expired" and lead["status"] == "won")
    ):
        raise DataConflictError("lead anonymization conflict")
    timestamp = _timestamp(now)
    updated = db.execute(
        "UPDATE leads SET company_name='已匿名化',contact_name='已匿名化',"
        "phone_normalized=NULL,email=NULL,wechat=NULL,next_followup_at=NULL,"
        "retention_expires_at=NULL,anonymized_at=?,updated_at=? "
        "WHERE id=? AND anonymized_at IS NULL",
        (timestamp, timestamp, lead_id),
    )
    if updated.rowcount != 1:
        raise DataConflictError("lead anonymization conflict")
    db.execute("DELETE FROM lead_followups WHERE lead_id=?", (lead_id,))
    db.execute("DELETE FROM lead_consents WHERE lead_id=?", (lead_id,))
    db.execute("UPDATE appointments SET note=NULL WHERE lead_id=?", (lead_id,))
    db.execute(
        "UPDATE assessments SET company_name=NULL,contact_email=NULL WHERE lead_id=?",
        (lead_id,),
    )
    db.execute(
        "UPDATE lead_status_history SET note=NULL WHERE lead_id=?", (lead_id,)
    )
    db.execute(
        "INSERT INTO lead_status_history "
        "(lead_id,previous_status,new_status,note,actor_text,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            lead_id,
            lead["status"],
            lead["status"],
            reason_code,
            "privacy_retention_system",
            timestamp,
        ),
    )


def expired_lead_ids(*, now=None):
    timestamp = _timestamp(now)
    db = get_db()
    try:
        return tuple(_select_expired_ids(db, timestamp))
    finally:
        db.close()


def purge_expired_leads(*, now=None, apply=False):
    """Preview or atomically anonymize due, unconverted leads."""
    timestamp = _timestamp(now)
    db = get_db()
    try:
        if apply:
            db.execute("BEGIN IMMEDIATE")
        lead_ids = _select_expired_ids(db, timestamp)
        if apply:
            for lead_id in lead_ids:
                anonymize_lead(
                    db,
                    lead_id,
                    "retention_expired",
                    now=datetime.fromisoformat(timestamp),
                )
            db.commit()
        return len(lead_ids)
    except Exception:
        if apply:
            db.rollback()
        raise
    finally:
        db.close()


def _select_expired_ids(db, timestamp):
    return [
        row[0]
        for row in db.execute(
            "SELECT id FROM leads WHERE anonymized_at IS NULL "
            "AND status!='won' AND retention_expires_at IS NOT NULL "
            "AND retention_expires_at<=? ORDER BY id",
            (timestamp,),
        ).fetchall()
    ]


def _run_immediate(operation):
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        result = operation(db)
        db.commit()
        return result
    except sqlite3.IntegrityError as error:
        db.rollback()
        raise DataConflictError("lead operation conflict") from error
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _mutable_ordinary_lead(db, lead_id):
    lead = db.execute(
        "SELECT status,anonymized_at FROM leads WHERE id=?", (lead_id,)
    ).fetchone()
    if lead is None or lead["anonymized_at"] is not None or lead["status"] == "won":
        raise DataConflictError("lead operation conflict")
    return lead


def _unchanged_retention(db, lead_id):
    return db.execute(
        "SELECT retention_expires_at FROM leads WHERE id=?", (lead_id,)
    ).fetchone()[0]


def _timestamp(value=None):
    if value is None:
        value = datetime.now(SHANGHAI)
    elif callable(value):
        value = value()
    if not isinstance(value, datetime):
        raise RuntimeError("admin clock unavailable")
    if value.tzinfo is not None:
        value = value.astimezone(SHANGHAI).replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat(sep=" ")


def _required_timestamp(value, field_name):
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{field_name} has an invalid value") from None
    if parsed.tzinfo is not None:
        raise ValidationError(f"{field_name} has an invalid value")
    return parsed.replace(microsecond=0).isoformat(sep=" ")


def _optional_timestamp(value, field_name):
    if value in (None, ""):
        return None
    return _required_timestamp(value, field_name)


def parse_date_filter(value, field_name):
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{field_name} has an invalid value") from None
    return parsed.isoformat()


def _optional_text(value, field_name, maximum):
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    value = value.strip()
    if len(value) > maximum:
        raise ValidationError(f"{field_name} is too long")
    return value


def _required_text(value, field_name, maximum):
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be text")
    value = value.strip()
    if not value:
        raise ValidationError(f"{field_name} is required")
    if len(value) > maximum:
        raise ValidationError(f"{field_name} is too long")
    return value
