"""Lead, consent, privacy-request, and retention persistence."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
import sqlite3
import unicodedata
from zoneinfo import ZoneInfo

import assessment_repository
from assessment_validation import BRANCH_CODES
from models import get_db
from pagination import Page, PageRequest, parse_bounded_search
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
COMPLETION_OUTCOMES = {
    "access": (
        ("access_copy_provided", "已向申请人提供个人信息副本"),
        ("access_no_data", "核验后确认无可提供的个人信息"),
    ),
    "correction": (
        ("correction_completed", "已按核验结果完成信息更正"),
        ("correction_no_change", "核验后确认无需更正"),
    ),
    "withdrawal": (
        ("withdrawal_anonymized", "已完成授权撤回并匿名化相关信息"),
    ),
    "deletion": (
        ("deletion_anonymized", "已完成删除请求并匿名化相关信息"),
    ),
}
REJECTION_OUTCOMES = (
    ("identity_verification_failed", "身份核验未通过"),
    ("request_scope_incomplete", "请求范围不明确，需补充信息"),
    ("request_not_applicable", "经核验，该请求不符合处理条件"),
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
EXPORT_FORM_KEYS = frozenset(
    {"csrf_token", "status", "branch", "date_from", "date_to", "queue", "q"}
)


class ExportSnapshotError(RuntimeError):
    """Raised when a persisted report cannot be exported safely."""


@dataclass(frozen=True)
class RetentionPurgeResult:
    lead_ids: tuple[int, ...]

    @property
    def count(self) -> int:
        return len(self.lead_ids)


@dataclass(frozen=True)
class LeadFilters:
    status: str | None = None
    branch: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    queue: str = "ordinary"
    search: str | None = None


@dataclass(frozen=True)
class DataRequestFilters:
    status: str | None = None
    request_type: str | None = None
    search: str | None = None


def _query_value(values, name):
    try:
        value = values.get(name, "")
    except (AttributeError, TypeError):
        return ""
    return value.strip() if type(value) is str else ""


def parse_lead_filters(values) -> LeadFilters:
    status = _query_value(values, "status")
    branch = _query_value(values, "branch")
    queue = _query_value(values, "queue")
    return LeadFilters(
        status=status if status in LEAD_STATUSES else None,
        branch=branch if branch in BRANCH_CODES else None,
        date_from=parse_date_filter(_query_value(values, "date_from"), "date_from"),
        date_to=parse_date_filter(_query_value(values, "date_to"), "date_to"),
        queue=queue if queue in {"ordinary", "followup"} else "ordinary",
        search=parse_bounded_search(values),
    )


def parse_export_filters(values) -> LeadFilters:
    """Strictly parse the Task 15 filter DTO from an export form."""
    try:
        supplied_keys = set(values.keys())
    except (AttributeError, TypeError):
        raise ValidationError("export filters have an invalid value") from None
    if not supplied_keys <= EXPORT_FORM_KEYS:
        raise ValidationError("export filters have an invalid value")
    if hasattr(values, "getlist") and any(
        len(values.getlist(key)) != 1 for key in supplied_keys
    ):
        raise ValidationError("export filters have an invalid value")

    def supplied(name):
        value = values.get(name, "")
        if not isinstance(value, str):
            raise ValidationError(f"{name} must be text")
        return value.strip()

    status = supplied("status")
    branch = supplied("branch")
    queue = supplied("queue")
    if status and status not in LEAD_STATUSES:
        raise ValidationError("status has an invalid value")
    if branch and branch not in BRANCH_CODES:
        raise ValidationError("branch has an invalid value")
    if queue and queue not in {"ordinary", "followup"}:
        raise ValidationError("queue has an invalid value")

    raw_search = values.get("q", "")
    if not isinstance(raw_search, str):
        raise ValidationError("q must be text")
    search = unicodedata.normalize("NFKC", raw_search).strip()
    if len(search) > 100 or any(
        unicodedata.category(character).startswith("C") for character in search
    ):
        raise ValidationError("q has an invalid value")

    return LeadFilters(
        status=status or None,
        branch=branch or None,
        date_from=parse_date_filter(supplied("date_from"), "date_from"),
        date_to=parse_date_filter(supplied("date_to"), "date_to"),
        queue=queue or "ordinary",
        search=search or None,
    )


def parse_data_request_filters(values) -> DataRequestFilters:
    status = _query_value(values, "status")
    request_type = _query_value(values, "request_type")
    return DataRequestFilters(
        status=status if status in DATA_REQUEST_STATUSES | {"open"} else None,
        request_type=(
            request_type if request_type in DATA_REQUEST_TYPES else None
        ),
        search=parse_bounded_search(values),
    )


def _like_pattern(value):
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _lead_predicate(filters: LeadFilters):
    clauses = ["l.anonymized_at IS NULL"]
    parameters = []
    if filters.status is not None:
        clauses.append("l.status=?")
        parameters.append(filters.status)
    if filters.branch is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM assessments branch_a "
            "WHERE branch_a.lead_id=l.id AND branch_a.branch_code=?)"
        )
        parameters.append(filters.branch)
    if filters.date_from is not None:
        clauses.append("date(l.created_at)>=?")
        parameters.append(filters.date_from)
    if filters.date_to is not None:
        clauses.append("date(l.created_at)<=?")
        parameters.append(filters.date_to)
    if filters.queue == "followup":
        clauses.append("l.next_followup_at IS NOT NULL")
    if filters.search is not None:
        pattern = _like_pattern(filters.search)
        clauses.append(
            "(l.company_name LIKE ? ESCAPE '\\' OR l.contact_name LIKE ? ESCAPE '\\' "
            "OR COALESCE(l.owner_text,'') LIKE ? ESCAPE '\\')"
        )
        parameters.extend((pattern, pattern, pattern))
    return " WHERE " + " AND ".join(clauses), tuple(parameters)


def _page_bounds(total, request):
    if total == 0:
        return 1, 0
    total_pages = (total + request.per_page - 1) // request.per_page
    return min(request.page, total_pages), total_pages


def query_leads(filters: LeadFilters, page: PageRequest) -> Page[sqlite3.Row]:
    where, parameters = _lead_predicate(filters)
    order = (
        "l.next_followup_at ASC,l.id ASC"
        if filters.queue == "followup"
        else "l.created_at DESC,l.id DESC"
    )
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM leads l" + where, parameters).fetchone()[0]
        page_number, total_pages = _page_bounds(total, page)
        if total == 0:
            return Page((), 1, page.per_page, 0, 0)
        rows = tuple(
            db.execute(
                "SELECT l.*,(SELECT COUNT(*) FROM assessments count_a WHERE count_a.lead_id=l.id) "
                "AS assessment_count,(SELECT latest_a.branch_code FROM assessments latest_a "
                "WHERE latest_a.lead_id=l.id ORDER BY latest_a.completed_at DESC,latest_a.id DESC "
                "LIMIT 1) AS latest_branch FROM leads l" + where + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                (*parameters, page.per_page, (page_number - 1) * page.per_page),
            ).fetchall()
        )
        return Page(rows, page_number, page.per_page, total, total_pages)
    finally:
        db.close()


def export_rows(filters: LeadFilters, limit=10_000):
    if not isinstance(filters, LeadFilters):
        raise TypeError("filters must be LeadFilters")
    if type(limit) is not int or not 1 <= limit <= 10_000:
        raise ValueError("limit has an invalid value")
    where, parameters = _lead_predicate(filters)
    order = (
        "l.next_followup_at ASC,l.id ASC"
        if filters.queue == "followup"
        else "l.created_at DESC,l.id DESC"
    )
    latest_assessment = (
        "SELECT a.{field} FROM assessments a WHERE a.lead_id=l.id "
        "AND a.completed_at IS NOT NULL "
        "ORDER BY a.completed_at DESC,a.id DESC LIMIT 1"
    )
    latest_appointment = (
        "SELECT ap.{field} FROM appointments ap WHERE ap.lead_id=l.id "
        "ORDER BY ap.created_at DESC,ap.id DESC LIMIT 1"
    )
    statement = (
        "SELECT l.company_name,l.contact_name,l.phone_normalized AS phone,"
        "l.email,l.wechat,l.status,l.owner_text,"
        f"({latest_assessment.format(field='branch_code')}) AS industry_branch,"
        f"({latest_assessment.format(field='department_code')}) AS department,"
        f"({latest_assessment.format(field='id')}) AS assessment_number,"
        f"({latest_assessment.format(field='report_snapshot_json')}) AS "
        "report_snapshot_json,"
        f"({latest_appointment.format(field='status')}) AS appointment_status,"
        f"({latest_appointment.format(field='preferred_date')}) AS preferred_date,"
        f"({latest_appointment.format(field='time_slot')}) AS time_slot,"
        "l.last_effective_followup_at,l.next_followup_at FROM leads l"
        + where
        + " ORDER BY "
        + order
        + " LIMIT ?"
    )
    db = get_db()
    try:
        selected = tuple(db.execute(statement, (*parameters, limit + 1)).fetchall())
    finally:
        db.close()
    if len(selected) > limit:
        raise ValidationError("export exceeds row limit")

    exported = []
    for row in selected:
        item = dict(row)
        serialized_snapshot = item.pop("report_snapshot_json")
        if item["assessment_number"] is None:
            maturity, primary_scenario = None, None
        else:
            summary = assessment_repository.report_summary_from_snapshot(
                serialized_snapshot
            )
            if summary is None:
                raise ExportSnapshotError("report snapshot is unavailable")
            maturity, primary_scenario = summary
        item["maturity"] = maturity
        item["primary_scenario"] = primary_scenario
        exported.append(item)
    return tuple(exported)


def record_export_audit(actor, filter_json, row_count, created_at):
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT INTO admin_export_logs "
            "(actor,filter_json,row_count,created_at) VALUES (?,?,?,?)",
            (actor, filter_json, row_count, created_at),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _data_request_predicate(filters: DataRequestFilters):
    clauses = []
    parameters = []
    if filters.status == "open":
        clauses.append("r.status IN ('received','verifying')")
    elif filters.status is not None:
        clauses.append("r.status=?")
        parameters.append(filters.status)
    if filters.request_type is not None:
        clauses.append("r.request_type=?")
        parameters.append(filters.request_type)
    if filters.search is not None:
        pattern = _like_pattern(filters.search)
        clauses.append(
            "(l.anonymized_at IS NULL AND (l.company_name LIKE ? ESCAPE '\\' "
            "OR l.contact_name LIKE ? ESCAPE '\\'))"
        )
        parameters.extend((pattern, pattern))
    prefix = " WHERE " if clauses else ""
    return prefix + " AND ".join(clauses), tuple(parameters)


def query_data_subject_requests(
    filters: DataRequestFilters, page: PageRequest
) -> Page[sqlite3.Row]:
    where, parameters = _data_request_predicate(filters)
    base = " FROM data_subject_requests r LEFT JOIN leads l ON l.id=r.lead_id"
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*)" + base + where, parameters).fetchone()[0]
        page_number, total_pages = _page_bounds(total, page)
        if total == 0:
            return Page((), 1, page.per_page, 0, 0)
        rows = tuple(
            db.execute(
                "SELECT r.id,r.lead_id,r.request_type,r.status,r.channel,r.requested_at,"
                "r.resolution_note,r.completed_at,r.admin_updated_at,"
                "CASE WHEN l.anonymized_at IS NULL THEN l.company_name END AS company_name,"
                "CASE WHEN l.anonymized_at IS NULL THEN l.contact_name END AS contact_name" + base + where +
                " ORDER BY r.requested_at DESC,r.id DESC LIMIT ? OFFSET ?",
                (*parameters, page.per_page, (page_number - 1) * page.per_page),
            ).fetchall()
        )
        return Page(rows, page_number, page.per_page, total, total_pages)
    finally:
        db.close()


def search_lead_choices(search) -> tuple[sqlite3.Row, ...]:
    """Return at most twenty non-anonymized leads for an explicit search."""
    normalized = parse_bounded_search({"q": search})
    if normalized is None:
        return ()
    pattern = _like_pattern(normalized)
    db = get_db()
    try:
        return tuple(
            db.execute(
                "SELECT id,company_name,contact_name FROM leads "
                "WHERE anonymized_at IS NULL AND "
                "(company_name LIKE ? ESCAPE '\\' OR contact_name LIKE ? ESCAPE '\\') "
                "ORDER BY created_at DESC,id DESC LIMIT 20",
                (pattern, pattern),
            ).fetchall()
        )
    finally:
        db.close()


def current_shanghai_datetime() -> datetime:
    """Return a timezone-explicit, database-ready Shanghai wall time."""
    return datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)


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
    submitted_at = submitted_at or current_shanghai_datetime()
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


def record_consent(
    db, lead_id, consent, identity_hash, legal_version_id, consented_at=None
):
    policy_version, source = validate_consent(consent, identity_hash)
    if type(legal_version_id) is not int or legal_version_id <= 0:
        raise ValidationError("legal_version_id has an invalid value")
    timestamp = (consented_at or current_shanghai_datetime()).isoformat(
        sep=" "
    )
    return db.execute(
        "INSERT INTO lead_consents "
        "(lead_id,policy_version,consented_at,source,identity_hash,created_at,legal_version_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            lead_id,
            policy_version,
            timestamp,
            source,
            identity_hash,
            timestamp,
            legal_version_id,
        ),
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
    filters=None,
    page=None,
):
    """Return leads matching the small operational filter set."""
    if filters is not None or page is not None:
        if not isinstance(filters, LeadFilters) or not isinstance(page, PageRequest):
            raise TypeError("paginated lead filters are incomplete")
        return query_leads(filters, page)
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
    request_id, new_status, outcome_code="", *, now=None
):
    if new_status not in {"verifying", "rejected"}:
        raise ValidationError("new_status has an invalid value")
    timestamp = _timestamp(now)

    def operation(db):
        row = db.execute(
            "SELECT request_type,status FROM data_subject_requests WHERE id=?",
            (request_id,),
        ).fetchone()
        expected = "received" if new_status == "verifying" else "verifying"
        if row is None or row["status"] != expected:
            raise DataConflictError("data request transition conflict")
        if new_status == "rejected":
            outcome_label = _resolve_privacy_outcome(
                outcome_code, REJECTION_OUTCOMES
            )
        elif outcome_code not in {"", None}:
            raise ValidationError("privacy outcome has an invalid value")
        else:
            outcome_label = None
        completed_at = timestamp if new_status == "rejected" else None
        updated = db.execute(
            "UPDATE data_subject_requests SET status=?,resolution_note=?,"
            "completed_at=?,admin_updated_at=? WHERE id=? AND status=?",
            (
                new_status,
                outcome_label,
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
    outcome_code,
    *,
    confirm_anonymization=False,
    now=None,
):
    timestamp = _timestamp(now)

    def operation(db):
        request_row = db.execute(
            "SELECT lead_id,request_type,status FROM data_subject_requests "
            "WHERE id=?",
            (request_id,),
        ).fetchone()
        if request_row is None or request_row["status"] != "verifying":
            raise DataConflictError("data request completion conflict")
        outcome_label = _resolve_privacy_outcome(
            outcome_code,
            COMPLETION_OUTCOMES.get(request_row["request_type"], ()),
        )
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
            (outcome_label, timestamp, timestamp, request_id),
        )
        if updated.rowcount != 1:
            raise DataConflictError("data request completion conflict")

    _run_immediate(operation)


def _resolve_privacy_outcome(outcome_code, choices):
    if isinstance(outcome_code, str):
        for code, label in choices:
            if outcome_code == code:
                return label
    raise ValidationError("privacy outcome has an invalid value")


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
        "phone_normalized=NULL,email=NULL,wechat=NULL,source=NULL,"
        "next_followup_at=NULL,"
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
        "UPDATE assessments SET company_name=NULL,contact_email=NULL,"
        "attribution_json='{}' WHERE lead_id=?",
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
    return run_retention_purge(now=now, apply=False).lead_ids


def purge_expired_leads(*, now=None, apply=False):
    """Preview or atomically anonymize due, unconverted leads."""
    return run_retention_purge(now=now, apply=apply).count


def run_retention_purge(*, now=None, apply=False):
    """Return the exact IDs selected and optionally anonymized in one snapshot."""
    timestamp = _timestamp(now)
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        lead_ids = tuple(_select_expired_ids(db, timestamp))
        if apply:
            for lead_id in lead_ids:
                anonymize_lead(
                    db,
                    lead_id,
                    "retention_expired",
                    now=datetime.fromisoformat(timestamp),
                )
        db.commit()
        return RetentionPurgeResult(lead_ids)
    except Exception:
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
        value = current_shanghai_datetime()
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
