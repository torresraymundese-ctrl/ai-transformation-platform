"""Read-only projections for the authenticated two-person operations workspace."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3

import appointment_repository
from content_clock import as_shanghai, format_shanghai
import ingestion_repository
import lead_repository
from models import get_db
from pagination import Page, PageRequest


@dataclass(frozen=True)
class OperationCard:
    code: str
    label: str
    count: int


@dataclass(frozen=True)
class OperationsSnapshot:
    cards: tuple[OperationCard, ...]


@dataclass(frozen=True)
class _QueueQuery:
    select_sql: str
    from_sql: str
    where_sql: str
    parameters: tuple
    order_sql: str


QUEUE_LABELS = {
    "pending_contact": "待首次联系",
    "new_leads": "新线索",
    "followup_today": "今日应联系",
    "followup_overdue": "跟进已逾期",
    "pending_appointments": "待确认诊断预约",
    "pending_ingestion": "待复核接入候选",
    "scheduled_content": "已排期内容",
    "draft_missing_required": "必填字段待补",
    "draft_complete": "字段完整，待人工复核",
    "open_privacy": "待处理隐私请求",
}
QUEUE_CODES = tuple(QUEUE_LABELS)

_SQL_WHITESPACE = (
    "char(9)||char(10)||char(11)||char(12)||char(13)||"
    "char(28)||char(29)||char(30)||char(31)||char(32)||"
    "char(133)||char(160)||char(5760)||"
    "char(8192)||char(8193)||char(8194)||char(8195)||char(8196)||"
    "char(8197)||char(8198)||char(8199)||char(8200)||char(8201)||"
    "char(8202)||char(8232)||char(8233)||char(8239)||char(8287)||char(12288)"
)


_LEAD_SELECT = (
    "SELECT l.id,'lead' AS operation_type,l.company_name AS display_title,"
    "l.contact_name AS display_meta,l.status,l.next_followup_at,l.created_at,"
    "l.company_name,l.contact_name,l.phone_normalized,l.email,l.wechat,l.owner_text"
)
_CONTENT_SELECT = (
    "SELECT ci.id,ci.entry_type AS operation_type,ci.entry_type,"
    "ci.title AS display_title,ci.entry_type AS display_meta,ci.status,"
    "ci.publish_at,ci.updated_at"
)


def parse_operation_queue(values) -> str | None:
    """Return one allowlisted queue code, or the dashboard safe default."""
    try:
        value = values.get("queue", "")
    except (AttributeError, TypeError):
        return None
    normalized = value.strip() if type(value) is str else ""
    return normalized if normalized in QUEUE_LABELS else None


def _nonblank(expression):
    return f"length(trim(coalesce({expression},''),{_SQL_WHITESPACE}))>0"


def _structurally_complete_sql():
    extension_tables = (
        "industry_content",
        "scenario_content",
        "service_content",
        "case_content",
        "resource_content",
        "announcement_content",
    )

    def no_other_extensions(expected):
        return " AND ".join(
            f"NOT EXISTS (SELECT 1 FROM {table} wrong_ext "
            "WHERE wrong_ext.content_item_id=ci.id)"
            for table in extension_tables
            if table != expected
        )

    base_fields = " AND ".join(
        _nonblank(f"ci.{name}")
        for name in ("slug", "title", "summary", "seo_title", "seo_description")
    )
    industry = (
        "ci.entry_type='industry' AND EXISTS (SELECT 1 FROM industry_content ic "
        "WHERE ic.content_item_id=ci.id) AND EXISTS (SELECT 1 FROM content_blocks cb "
        "WHERE cb.content_item_id=ci.id) AND "
        + no_other_extensions("industry_content")
    )
    scenario = (
        "ci.entry_type='scenario' AND EXISTS (SELECT 1 FROM scenario_content sc "
        "WHERE sc.content_item_id=ci.id) AND EXISTS (SELECT 1 FROM content_blocks cb "
        "WHERE cb.content_item_id=ci.id) AND EXISTS (SELECT 1 FROM scenario_public_inputs spi "
        f"WHERE spi.content_item_id=ci.id AND {_nonblank('spi.input_text')}) AND EXISTS "
        "(SELECT 1 FROM content_maturity_levels ml WHERE ml.content_item_id=ci.id) AND "
        + no_other_extensions("scenario_content")
    )
    service = (
        "ci.entry_type='service' AND EXISTS (SELECT 1 FROM service_content svc "
        "WHERE svc.content_item_id=ci.id) AND EXISTS (SELECT 1 FROM content_blocks cb "
        "WHERE cb.content_item_id=ci.id) AND EXISTS (SELECT 1 FROM content_maturity_levels ml "
        "WHERE ml.content_item_id=ci.id) AND "
        + no_other_extensions("service_content")
    )
    metric_fields = " AND ".join(
        _nonblank(f"cm.{name}")
        for name in (
            "name",
            "before_value",
            "after_value",
            "unit",
            "statistical_period",
            "evidence_explanation",
        )
    )
    case = (
        "ci.entry_type='case' AND EXISTS (SELECT 1 FROM case_content cc "
        "WHERE cc.content_item_id=ci.id AND "
        f"{_nonblank('cc.verification_code')} AND cc.basis_type IN "
        "('public_source','client_authorization','internal_delivery_record',"
        "'private_authorization') AND ((cc.basis_type='public_source' AND "
        f"{_nonblank('cc.source_url')} AND {_nonblank('cc.source_url_sha256')}) OR "
        "(cc.basis_type IN ('client_authorization','internal_delivery_record',"
        f"'private_authorization') AND {_nonblank('cc.private_basis_reference')}))) "
        "AND ci.id IN (SELECT cm.case_content_item_id FROM case_metrics cm "
        f"WHERE {metric_fields}) AND "
        + no_other_extensions("case_content")
    )
    resource = (
        "ci.entry_type='resource' AND EXISTS (SELECT 1 FROM resource_content rc "
        "WHERE rc.content_item_id=ci.id AND rc.resource_type IN "
        "('article','guide','report','template','policy') AND rc.is_original IN (0,1) AND "
        f"{_nonblank('rc.original_published_at')} AND {_nonblank('rc.copyright_notice')} AND "
        "(rc.is_original=1 OR ("
        f"{_nonblank('rc.source_name')} AND {_nonblank('rc.source_url')} AND "
        f"{_nonblank('rc.source_url_sha256')}))) AND "
        + no_other_extensions("resource_content")
    )
    announcement = (
        "ci.entry_type='announcement' AND EXISTS (SELECT 1 FROM announcement_content ac "
        f"WHERE ac.content_item_id=ci.id AND {_nonblank('ac.valid_from')} AND "
        f"{_nonblank('ac.valid_until')} AND ac.valid_from<ac.valid_until) AND "
        + no_other_extensions("announcement_content")
    )
    matching_extension = " OR ".join(
        f"({item})" for item in (industry, scenario, service, case, resource, announcement)
    )
    return f"({base_fields}) AND ({matching_extension})"


_STRUCTURALLY_COMPLETE = _structurally_complete_sql()


def _queue_query(code: str, now: datetime) -> _QueueQuery:
    local_now = as_shanghai(now)
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    if code in {"pending_contact", "new_leads"}:
        status = "pending_contact" if code == "pending_contact" else "new"
        where, parameters = lead_repository._lead_predicate(
            lead_repository.LeadFilters(status=status)
        )
        return _QueueQuery(
            _LEAD_SELECT,
            " FROM leads l",
            where,
            parameters,
            "l.created_at DESC,l.id DESC",
        )
    if code in {"followup_today", "followup_overdue"}:
        if code == "followup_today":
            where = (
                " WHERE l.anonymized_at IS NULL AND l.next_followup_at IS NOT NULL "
                "AND l.next_followup_at>=? AND l.next_followup_at<?"
            )
            parameters = (format_shanghai(today_start), format_shanghai(tomorrow_start))
        else:
            where = (
                " WHERE l.anonymized_at IS NULL AND l.next_followup_at IS NOT NULL "
                "AND l.next_followup_at<?"
            )
            parameters = (format_shanghai(today_start),)
        return _QueueQuery(
            _LEAD_SELECT,
            " FROM leads l",
            where,
            parameters,
            "l.next_followup_at ASC,l.id ASC",
        )
    if code == "pending_appointments":
        where, parameters = appointment_repository._appointment_predicate(
            appointment_repository.AppointmentFilters(status="pending")
        )
        return _QueueQuery(
            "SELECT a.id,'appointment' AS operation_type,"
            "l.company_name AS display_title,"
            "(a.preferred_date||' '||a.time_slot) AS display_meta,a.status,"
            "a.preferred_date,a.time_slot,a.created_at,l.company_name,l.contact_name,"
            "l.phone_normalized,l.email,l.wechat,l.owner_text",
            " FROM appointments a JOIN leads l ON l.id=a.lead_id",
            where,
            parameters,
            "a.preferred_date ASC,a.time_slot ASC,a.id ASC",
        )
    if code == "pending_ingestion":
        where, parameters = ingestion_repository._ingestion_predicate(
            ingestion_repository.IngestionFilters(state="pending_review")
        )
        return _QueueQuery(
            "SELECT id,'ingestion' AS operation_type,title AS display_title,"
            "source_name AS display_meta,state AS status,updated_at",
            " FROM ingestion_candidates",
            where,
            parameters,
            "updated_at DESC,id DESC",
        )
    if code == "scheduled_content":
        return _QueueQuery(
            _CONTENT_SELECT,
            " FROM content_items ci",
            " WHERE ci.status='draft' AND ci.publish_at IS NOT NULL",
            (),
            "ci.publish_at ASC,ci.id ASC",
        )
    if code in {"draft_missing_required", "draft_complete"}:
        structural = (
            _STRUCTURALLY_COMPLETE
            if code == "draft_complete"
            else f"NOT ({_STRUCTURALLY_COMPLETE})"
        )
        return _QueueQuery(
            _CONTENT_SELECT,
            " FROM content_items ci",
            " WHERE ci.status='draft' AND ci.publish_at IS NULL AND " + structural,
            (),
            "ci.updated_at DESC,ci.id DESC",
        )
    if code == "open_privacy":
        where, parameters = lead_repository._data_request_predicate(
            lead_repository.DataRequestFilters(status="open")
        )
        masked = "CASE WHEN l.anonymized_at IS NULL THEN l.{field} END"
        return _QueueQuery(
            "SELECT r.id,'privacy' AS operation_type,"
            "CASE WHEN l.anonymized_at IS NULL THEN l.company_name "
            "ELSE '已匿名化请求' END AS display_title,r.request_type AS display_meta,"
            "r.status,r.request_type,r.requested_at,"
            + ",".join(
                f"{masked.format(field=field)} AS {field}"
                for field in (
                    "company_name",
                    "contact_name",
                    "phone_normalized",
                    "email",
                    "wechat",
                    "owner_text",
                )
            ),
            " FROM data_subject_requests r LEFT JOIN leads l ON l.id=r.lead_id",
            where,
            parameters,
            "r.requested_at DESC,r.id DESC",
        )
    raise ValueError("unsupported operations queue")


def _page_bounds(total: int, requested: PageRequest):
    if total == 0:
        return 1, 0
    total_pages = (total + requested.per_page - 1) // requested.per_page
    return min(requested.page, total_pages), total_pages


def dashboard_snapshot(now: datetime) -> OperationsSnapshot:
    """Count each stable queue with one read-only COUNT projection."""
    db = get_db()
    cards = []
    try:
        for code, label in QUEUE_LABELS.items():
            query = _queue_query(code, now)
            count = db.execute(
                "SELECT COUNT(*)" + query.from_sql + query.where_sql,
                query.parameters,
            ).fetchone()[0]
            cards.append(OperationCard(code, label, count))
        return OperationsSnapshot(tuple(cards))
    finally:
        db.close()


def query_operation_queue(
    code: str, requested: PageRequest, now: datetime
) -> Page[sqlite3.Row]:
    """Return one bounded queue page from the exact predicate used by its card."""
    if code not in QUEUE_LABELS:
        raise ValueError("unsupported operations queue")
    query = _queue_query(code, now)
    db = get_db()
    try:
        total = db.execute(
            "SELECT COUNT(*)" + query.from_sql + query.where_sql,
            query.parameters,
        ).fetchone()[0]
        page_number, total_pages = _page_bounds(total, requested)
        rows = tuple(
            db.execute(
                query.select_sql
                + query.from_sql
                + query.where_sql
                + " ORDER BY "
                + query.order_sql
                + " LIMIT ? OFFSET ?",
                (
                    *query.parameters,
                    requested.per_page,
                    (page_number - 1) * requested.per_page,
                ),
            ).fetchall()
        )
        if total == 0:
            return Page((), 1, requested.per_page, 0, 0)
        return Page(rows, page_number, requested.per_page, total, total_pages)
    finally:
        db.close()
