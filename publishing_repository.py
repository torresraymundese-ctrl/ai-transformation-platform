"""SQLite repository for content aggregates; caller owns every transaction."""

from dataclasses import replace
from datetime import timedelta
from html import unescape
import json
import re
import sqlite3

from assessment.reporting import RISK_EXPLANATIONS, RISK_LABELS
from content_clock import format_shanghai
from content_json import ContentJsonError, decode_database_json
from content_contracts import CaseMetric, ContentBlock, ContentDraft, ContentRelation
from content_validation import (
    CASE_BASIS_TYPES,
    CASE_VERIFICATION,
    ContentValidationError,
    is_exact_nonblank_text,
    is_valid_public_budget_range,
    is_valid_public_week_range,
    public_input_texts,
    validate_content_draft,
)
from media_validation import ATTACHMENT_MIMES, IMAGE_MIMES
from service_authority import load_service_authority


EXTENSION_TABLES = {
    "industry": ("industry_content", ("industry_id",)),
    "scenario": ("scenario_content", ("scenario_id",)),
    "service": ("service_content", ("service_id",)),
    "case": (
        "case_content",
        (
            "verification_code", "is_anonymized", "basis_type", "private_basis_reference",
            "source_url", "source_url_sha256", "source_check_code", "source_checked_at",
            "source_check_expires_at", "source_check_url_sha256", "is_verified",
            "review_confirmed", "verified_at",
        ),
    ),
    "resource": (
        "resource_content",
        (
            "resource_type", "is_original", "source_name", "source_url",
            "source_url_sha256", "source_check_code", "source_checked_at",
            "source_check_expires_at", "source_check_url_sha256",
            "original_published_at", "copyright_notice", "attachment_media_id",
        ),
    ),
    "announcement": ("announcement_content", ("valid_from", "valid_until", "cta_url")),
}

RELATION_TABLES = {
    "scenario_case": ("scenario_cases", "scenario_content_item_id", "case_content_group_id"),
    "scenario_resource": ("scenario_resources", "scenario_content_item_id", "resource_content_group_id"),
    "service_case": ("service_cases", "service_content_item_id", "case_content_group_id"),
    "service_resource": ("service_resources", "service_content_item_id", "resource_content_group_id"),
    "industry_case": ("industry_cases", "industry_content_item_id", "case_content_group_id"),
    "industry_resource": ("industry_resources", "industry_content_item_id", "resource_content_group_id"),
}
SOURCE_CHECK_COLUMNS = (
    "source_check_code",
    "source_checked_at",
    "source_check_expires_at",
    "source_check_url_sha256",
)
class ContentNotFoundError(LookupError):
    code = "content_not_found"


class ContentConflictError(RuntimeError):
    def __init__(self, code="content_conflict"):
        self.code = code
        super().__init__(code)


class ContentStateError(RuntimeError):
    def __init__(self, code="invalid_content_state"):
        self.code = code
        super().__init__(code)


def _decode_content_json(value):
    try:
        return decode_database_json(value)
    except ContentJsonError as error:
        raise ContentValidationError("content_json_invalid") from error


def write_audit_event(db, content_id, event_code, actor, now, details=None):
    if not isinstance(actor, str) or not actor.strip() or len(actor.strip()) > 200:
        raise ContentValidationError("actor_invalid")
    details_json = None
    if details is not None:
        details_json = json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    db.execute(
        "INSERT INTO content_audit_events "
        "(content_item_id,event_code,actor_text,details_json,created_at) VALUES (?,?,?,?,?)",
        (content_id, event_code, actor.strip(), details_json, format_shanghai(now)),
    )


def _group_for_draft(db, draft, timestamp):
    if draft.content_group_id is not None:
        row = db.execute(
            "SELECT * FROM content_groups WHERE id=?", (draft.content_group_id,)
        ).fetchone()
        if row is None:
            raise ContentNotFoundError()
        if row["entry_type"] != draft.entry_type:
            raise ContentValidationError("content_group_type_mismatch")
        identity_column = {
            "industry": "industry_id",
            "scenario": "scenario_id",
            "service": "service_id",
        }.get(draft.entry_type)
        if identity_column and row[identity_column] != draft.extension[identity_column]:
            raise ContentValidationError("content_group_identity_mismatch")
        return row

    identity_column = {
        "industry": "industry_id",
        "scenario": "scenario_id",
        "service": "service_id",
    }.get(draft.entry_type)
    if identity_column:
        identity = draft.extension[identity_column]
        row = db.execute(
            f"SELECT * FROM content_groups WHERE {identity_column}=?", (identity,)
        ).fetchone()
        if row is not None:
            if row["canonical_slug"] != draft.slug:
                raise ContentValidationError("core_group_slug_mismatch")
            return row
    columns = ["entry_type", "canonical_slug", "created_at", "updated_at"]
    values = [draft.entry_type, draft.slug, timestamp, timestamp]
    if identity_column:
        columns.append(identity_column)
        values.append(draft.extension[identity_column])
    try:
        cursor = db.execute(
            f"INSERT INTO content_groups ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            values,
        )
    except sqlite3.IntegrityError as error:
        raise ContentValidationError("slug_conflict") from error
    return db.execute("SELECT * FROM content_groups WHERE id=?", (cursor.lastrowid,)).fetchone()


def _source_tuple(extension):
    return tuple(extension.get(column) for column in SOURCE_CHECK_COLUMNS)


def _server_owned_source_extension(db, content_id, entry_type, extension):
    if entry_type not in {"case", "resource"}:
        return extension
    table = EXTENSION_TABLES[entry_type][0]
    current = db.execute(
        f"SELECT source_url_sha256,{','.join(SOURCE_CHECK_COLUMNS)} "
        f"FROM {table} WHERE content_item_id=?",
        (content_id,),
    ).fetchone()
    if current is not None and current["source_url_sha256"] != extension.get("source_url_sha256"):
        extension = dict(extension)
        for key in SOURCE_CHECK_COLUMNS:
            extension[key] = None
        return extension
    if current is not None:
        current_tuple = tuple(current[column] for column in SOURCE_CHECK_COLUMNS)
        supplied_tuple = _source_tuple(extension)
        if any(value is not None for value in supplied_tuple) and supplied_tuple != current_tuple:
            raise ContentValidationError("source_check_server_owned")
        extension = dict(extension)
        for key, value in zip(SOURCE_CHECK_COLUMNS, current_tuple):
            extension[key] = value
    return extension


def _replace_children(db, content_id, draft, *, delete_existing):
    extension_table, extension_columns = EXTENSION_TABLES[draft.entry_type]
    if delete_existing:
        for table, owner_column, _ in RELATION_TABLES.values():
            db.execute(f"DELETE FROM {table} WHERE {owner_column}=?", (content_id,))
        db.execute("DELETE FROM content_maturity_levels WHERE content_item_id=?", (content_id,))
        db.execute("DELETE FROM case_metrics WHERE case_content_item_id=?", (content_id,))
        db.execute("DELETE FROM content_blocks WHERE content_item_id=?", (content_id,))
        db.execute(f"DELETE FROM {extension_table} WHERE content_item_id=?", (content_id,))
    values = [content_id] + [draft.extension.get(column) for column in extension_columns]
    db.execute(
        f"INSERT INTO {extension_table} (content_item_id,{','.join(extension_columns)}) "
        f"VALUES ({','.join('?' for _ in values)})",
        values,
    )
    for block in draft.blocks:
        settings_json = json.dumps(
            dict(block.settings), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        db.execute(
            "INSERT INTO content_blocks "
            "(content_item_id,block_type,title,body_html,settings_json,media_asset_id,sort_order) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                content_id, block.block_type, block.title, block.body_html,
                settings_json, block.media_asset_id, block.sort_order,
            ),
        )
    for index, code in enumerate(draft.maturity_codes):
        db.execute(
            "INSERT INTO content_maturity_levels (content_item_id,maturity_code,sort_order) VALUES (?,?,?)",
            (content_id, code, index),
        )
    for metric in draft.metrics:
        db.execute(
            "INSERT INTO case_metrics "
            "(case_content_item_id,name,before_value,after_value,unit,statistical_period,"
            "evidence_explanation,sort_order) VALUES (?,?,?,?,?,?,?,?)",
            (
                content_id, metric.name, metric.before_value, metric.after_value,
                metric.unit, metric.statistical_period, metric.evidence_explanation,
                metric.sort_order,
            ),
        )
    for relation in draft.relations:
        table, owner_column, target_column = RELATION_TABLES[relation.relation_type]
        db.execute(
            f"INSERT INTO {table} ({owner_column},{target_column},sort_order) VALUES (?,?,?)",
            (content_id, relation.target_group_id, relation.sort_order),
        )


def _insert_content_draft(db, draft, *, actor, now, event_code):
    validated = validate_content_draft(draft)
    if validated.entry_type in {"case", "resource"} and any(
        value is not None for value in _source_tuple(validated.extension)
    ):
        raise ContentValidationError("source_check_server_owned")
    if validated.publish_at is not None:
        raise ContentValidationError("publish_at_managed_by_schedule")
    timestamp = format_shanghai(now)
    group = _group_for_draft(db, validated, timestamp)
    existing_draft = db.execute(
        "SELECT id FROM content_items WHERE content_group_id=? AND status='draft'",
        (group["id"],),
    ).fetchone()
    if existing_draft is not None:
        raise ContentConflictError("draft_already_exists")
    revision_number = db.execute(
        "SELECT COALESCE(MAX(revision_number),0)+1 FROM content_items WHERE content_group_id=?",
        (group["id"],),
    ).fetchone()[0]
    try:
        cursor = db.execute(
            "INSERT INTO content_items "
            "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
            "seo_description,share_image_media_id,status,publish_at,published_at,archived_at,"
            "lock_version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,'draft',?,NULL,NULL,1,?,?)",
            (
                group["id"], validated.entry_type, revision_number, validated.slug,
                validated.title, validated.summary, validated.seo_title,
                validated.seo_description, validated.share_image_media_id,
                validated.publish_at, timestamp, timestamp,
            ),
        )
    except sqlite3.IntegrityError as error:
        raise ContentConflictError("draft_already_exists") from error
    content_id = cursor.lastrowid
    _replace_children(db, content_id, validated, delete_existing=False)
    write_audit_event(db, content_id, event_code, actor, now)
    return content_id


def insert_content_draft(db: sqlite3.Connection, draft: ContentDraft, *, actor: str, now) -> int:
    """Insert a complete aggregate without committing the caller's transaction."""
    return _insert_content_draft(
        db, draft, actor=actor, now=now, event_code="content_created"
    )


def update_content_draft(
    db: sqlite3.Connection,
    content_id: int,
    expected_lock_version: int,
    draft: ContentDraft,
    *,
    actor: str,
    now,
) -> int:
    """Replace a draft aggregate without committing the caller's transaction."""
    row = db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
    if row is None:
        raise ContentNotFoundError()
    if row["status"] != "draft":
        raise ContentStateError("content_not_editable")
    if row["lock_version"] != expected_lock_version:
        raise ContentConflictError("stale_lock_version")
    normalized = draft
    if draft.content_group_id is None:
        normalized = replace(draft, content_group_id=row["content_group_id"])
    validated = validate_content_draft(normalized)
    if validated.content_group_id != row["content_group_id"] or validated.entry_type != row["entry_type"]:
        raise ContentValidationError("content_identity_immutable")
    if validated.publish_at != row["publish_at"]:
        raise ContentValidationError("publish_at_managed_by_schedule")
    group = db.execute(
        "SELECT * FROM content_groups WHERE id=?", (row["content_group_id"],)
    ).fetchone()
    identity_column = {
        "industry": "industry_id",
        "scenario": "scenario_id",
        "service": "service_id",
    }.get(row["entry_type"])
    if identity_column and group[identity_column] != validated.extension[identity_column]:
        raise ContentValidationError("content_group_identity_mismatch")
    extension = _server_owned_source_extension(
        db, content_id, row["entry_type"], dict(validated.extension)
    )
    validated = replace(validated, extension=extension)
    timestamp = format_shanghai(now)
    cursor = db.execute(
        "UPDATE content_items SET slug=?,title=?,summary=?,seo_title=?,seo_description=?,"
        "share_image_media_id=?,publish_at=?,lock_version=lock_version+1,updated_at=? "
        "WHERE id=? AND status='draft' AND lock_version=?",
        (
            validated.slug, validated.title, validated.summary, validated.seo_title,
            validated.seo_description, validated.share_image_media_id,
            validated.publish_at, timestamp, content_id, expected_lock_version,
        ),
    )
    if cursor.rowcount != 1:
        raise ContentConflictError("stale_lock_version")
    _replace_children(db, content_id, validated, delete_existing=True)
    write_audit_event(db, content_id, "content_updated", actor, now)
    return expected_lock_version + 1


def load_content_draft(db, content_id):
    item = db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
    if item is None:
        raise ContentNotFoundError()
    table, columns = EXTENSION_TABLES[item["entry_type"]]
    extension_row = db.execute(
        f"SELECT {','.join(columns)} FROM {table} WHERE content_item_id=?", (content_id,)
    ).fetchone()
    if extension_row is None:
        raise ContentValidationError("extension_missing")
    extension = {column: extension_row[column] for column in columns}
    blocks = tuple(
        ContentBlock(
            block_type=row["block_type"],
            title=row["title"],
            body_html=row["body_html"],
            settings=_decode_content_json(row["settings_json"]),
            media_asset_id=row["media_asset_id"],
            sort_order=row["sort_order"],
        )
        for row in db.execute(
            "SELECT * FROM content_blocks WHERE content_item_id=? ORDER BY sort_order,id",
            (content_id,),
        )
    )
    relations = []
    for relation_type, (relation_table, owner_column, target_column) in RELATION_TABLES.items():
        relations.extend(
            ContentRelation(relation_type, row[target_column], row["sort_order"])
            for row in db.execute(
                f"SELECT {target_column},sort_order FROM {relation_table} "
                f"WHERE {owner_column}=? ORDER BY sort_order,{target_column}",
                (content_id,),
            )
        )
    relations.sort(key=lambda relation: (relation.sort_order, relation.relation_type, relation.target_group_id))
    maturity = tuple(
        row["maturity_code"]
        for row in db.execute(
            "SELECT maturity_code FROM content_maturity_levels WHERE content_item_id=? ORDER BY sort_order,maturity_code",
            (content_id,),
        )
    )
    metrics = tuple(
        CaseMetric(
            row["name"], row["before_value"], row["after_value"], row["unit"],
            row["statistical_period"], row["evidence_explanation"], row["sort_order"],
        )
        for row in db.execute(
            "SELECT * FROM case_metrics WHERE case_content_item_id=? ORDER BY sort_order,id",
            (content_id,),
        )
    )
    return ContentDraft(
        entry_type=item["entry_type"],
        slug=item["slug"],
        title=item["title"],
        summary=item["summary"],
        seo_title=item["seo_title"],
        seo_description=item["seo_description"],
        content_group_id=item["content_group_id"],
        share_image_media_id=item["share_image_media_id"],
        publish_at=item["publish_at"],
        extension=extension,
        blocks=blocks,
        relations=tuple(relations),
        maturity_codes=maturity,
        metrics=metrics,
    )


def _load_validated_publication_draft(db, content_id):
    raw_draft = load_content_draft(db, content_id)
    try:
        draft = validate_content_draft(raw_draft)
    except ContentValidationError as error:
        if raw_draft.entry_type == "service" and error.code == "maturity_invalid":
            raise ContentValidationError("service_public_incomplete") from error
        if raw_draft.entry_type == "case" and error.code == "extension_invalid":
            raise ContentValidationError("case_verification_incomplete") from error
        raise
    if tuple(block.title for block in raw_draft.blocks) != tuple(
        block.title for block in draft.blocks
    ):
        raise ContentValidationError("block_title_invalid")
    return draft


def validate_for_publication(db, content_id, now):
    draft = _load_validated_publication_draft(db, content_id)
    if draft.share_image_media_id is not None:
        media = db.execute(
            "SELECT detected_mime FROM media_assets WHERE id=? AND status='ready'",
            (draft.share_image_media_id,),
        ).fetchone()
        if media is None:
            raise ContentValidationError("media_not_ready")
        if media["detected_mime"] not in IMAGE_MIMES:
            raise ContentValidationError("share_image_mime_invalid")
    for block in draft.blocks:
        if block.media_asset_id is None:
            continue
        media = db.execute(
            "SELECT detected_mime FROM media_assets WHERE id=? AND status='ready'",
            (block.media_asset_id,),
        ).fetchone()
        if media is None:
            raise ContentValidationError("media_not_ready")
        allowed = (
            IMAGE_MIMES if block.block_type == "image_text"
            else ATTACHMENT_MIMES if block.block_type == "download" else None
        )
        if allowed is not None and media["detected_mime"] not in allowed:
            raise ContentValidationError("block_media_mime_invalid")
    if (
        draft.entry_type == "resource"
        and draft.extension.get("attachment_media_id") is not None
        and db.execute(
            "SELECT 1 FROM media_assets WHERE id=? AND status='ready'",
            (draft.extension["attachment_media_id"],),
        ).fetchone()
        is None
    ):
        raise ContentValidationError("media_not_ready")
    for relation in draft.relations:
        target_type = "case" if relation.relation_type.endswith("_case") else "resource"
        if db.execute(
            "SELECT 1 FROM content_items WHERE content_group_id=? AND entry_type=? AND status='published'",
            (relation.target_group_id, target_type),
        ).fetchone() is None:
            raise ContentValidationError("relation_target_not_published")
    required_source = (
        draft.entry_type == "case" and draft.extension.get("basis_type") == "public_source"
    ) or (
        draft.entry_type == "resource" and draft.extension.get("is_original") == 0
    )
    if required_source:
        source_hash = draft.extension.get("source_url_sha256")
        checked_at = draft.extension.get("source_checked_at")
        now_text = format_shanghai(now)
        freshness_floor = format_shanghai(now - timedelta(days=7))
        if (
            draft.extension.get("source_check_code") != "https_ok"
            or draft.extension.get("source_check_url_sha256") != source_hash
            or not checked_at
            or checked_at < freshness_floor
            or checked_at > now_text
            or not draft.extension.get("source_check_expires_at")
            or draft.extension["source_check_expires_at"] < now_text
        ):
            raise ContentValidationError("source_check_invalid")
    if draft.entry_type == "case":
        verification_code = draft.extension.get("verification_code")
        expected_anonymized = 1 if verification_code == "authorized_anonymous" else 0
        if (
            verification_code not in CASE_VERIFICATION
            or draft.extension.get("basis_type") not in CASE_BASIS_TYPES
            or draft.extension.get("is_anonymized") != expected_anonymized
            or draft.extension.get("is_verified") != 1
            or draft.extension.get("review_confirmed") != 1
            or not draft.extension.get("verified_at")
            or draft.extension["verified_at"] > format_shanghai(now)
            or not draft.metrics
        ):
            raise ContentValidationError("case_verification_incomplete")
    if draft.entry_type == "industry":
        _validate_industry_publication(db, content_id, draft, now)
    if draft.entry_type == "scenario":
        _validate_scenario_publication(db, content_id, draft)
    if draft.entry_type == "service":
        _validate_service_publication(db, content_id, draft)
    return draft


def _nonblank_strings(value):
    return (
        type(value) is list and value
        and all(is_exact_nonblank_text(item) for item in value)
    )


def _meaningful_html(value):
    return type(value) is str and bool(
        unescape(re.sub(r"<[^>]*>", "", value)).strip()
    )


def _validate_service_publication(db, content_id, draft):
    service_id = draft.extension["service_id"]
    authority = load_service_authority(db, service_id)
    if (
        authority is None
        or not draft.maturity_codes
        or not draft.blocks
        or not any(_meaningful_html(block.body_html) for block in draft.blocks)
    ):
        raise ContentValidationError("service_public_incomplete")


def _scenario_source_rows(db, scenario_id, *, published_only_services=False):
    service_status_sql = (
        " AND svc.status='published'" if published_only_services else ""
    )
    return db.execute(
        "SELECT s.*,svc.id AS service_id,svc.public_name AS service_name,svc.min_budget,svc.max_budget,"
        "svc.min_weeks AS service_min_weeks,svc.max_weeks AS service_max_weeks,"
        "svc.implementation_steps_json,svc.prerequisites_json,svc.acceptance_json,svc.status AS service_status "
        "FROM scenarios s LEFT JOIN scenario_services link ON link.scenario_id=s.id "
        "LEFT JOIN services svc ON svc.id=link.service_id WHERE s.id=?"
        f"{service_status_sql}",
        (scenario_id,),
    ).fetchall()


def _has_only_exact_published_names(db, table, where_sql, arguments):
    rows = db.execute(
        f"SELECT name FROM {table} WHERE status='published' AND {where_sql}",
        arguments,
    ).fetchall()
    return bool(rows) and all(
        is_exact_nonblank_text(row["name"]) for row in rows
    )


def _validate_industry_publication(db, content_id, draft, now):
    industry_id = draft.extension["industry_id"]
    industry = db.execute(
        "SELECT id,status,name FROM industries WHERE id=?", (industry_id,)
    ).fetchone()
    if (
        industry is None
        or industry["status"] != "published"
        or not is_exact_nonblank_text(industry["name"])
        or not draft.blocks
        or not any(_meaningful_html(block.body_html) for block in draft.blocks)
        or not _has_only_exact_published_names(db, "pain_points", "industry_id=?", (industry_id,))
        or not _has_only_exact_published_names(db, "departments", "industry_id=?", (industry_id,))
        or not _has_only_exact_published_names(db, "company_sizes", "1=1", ())
    ):
        raise ContentValidationError("industry_public_incomplete")
    timestamp = format_shanghai(now)
    candidates = db.execute(
        "SELECT DISTINCT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenario_branches sb ON sb.scenario_id=g.scenario_id "
        "JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
        "WHERE ci.entry_type='scenario' AND ci.status='published' "
        "AND (ci.publish_at IS NULL OR ci.publish_at<=?) AND ib.industry_id=? "
        "AND ib.status='published' "
        "ORDER BY ci.id",
        (timestamp, industry_id),
    ).fetchall()
    for candidate in candidates:
        try:
            candidate_draft = _load_validated_publication_draft(db, candidate["id"])
            _validate_scenario_publication(
                db, candidate["id"], candidate_draft, published_only_core=True
            )
        except ContentValidationError:
            continue
        return
    raise ContentValidationError("industry_public_incomplete")


def _validate_scenario_publication(
    db, content_id, draft, *, published_only_core=False
):
    scenario_id = draft.extension["scenario_id"]
    rows = _scenario_source_rows(
        db, scenario_id, published_only_services=published_only_core
    )
    if not rows or rows[0]["status"] != "published":
        raise ContentValidationError("scenario_public_incomplete")
    scenario = rows[0]
    risk_codes = _decode_content_json(scenario["risk_codes_json"])
    if not _nonblank_strings(risk_codes) or any(
        code not in RISK_LABELS or code not in RISK_EXPLANATIONS for code in risk_codes
    ):
        raise ContentValidationError("scenario_public_incomplete")
    if not is_valid_public_week_range(scenario["min_weeks"], scenario["max_weeks"]):
        raise ContentValidationError("scenario_public_incomplete")
    industry_status_sql = (
        " AND ib.status='published' AND i.status='published'"
        if published_only_core else ""
    )
    department_status_sql = (
        " AND d.status='published'" if published_only_core else ""
    )
    pain_status_sql = (
        " AND p.status='published'" if published_only_core else ""
    )
    industry_rows = db.execute(
        "SELECT i.name,i.status AS industry_status,ib.status AS branch_status "
        "FROM scenario_branches sb JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
        "JOIN industries i ON i.id=ib.industry_id WHERE sb.scenario_id=?"
        f"{industry_status_sql} ORDER BY ib.id",
        (scenario_id,),
    ).fetchall()
    department_rows = db.execute(
        "SELECT d.name,d.status FROM scenario_departments link "
        "JOIN departments d ON d.id=link.department_id WHERE link.scenario_id=?"
        f"{department_status_sql} ORDER BY d.id",
        (scenario_id,),
    ).fetchall()
    pain_rows = db.execute(
        "SELECT p.name,p.status FROM scenario_pains link "
        "JOIN pain_points p ON p.id=link.pain_point_id WHERE link.scenario_id=?"
        f"{pain_status_sql} ORDER BY p.id",
        (scenario_id,),
    ).fetchall()
    input_rows = db.execute(
        "SELECT input_text,sort_order FROM scenario_public_inputs "
        "WHERE content_item_id=? ORDER BY sort_order,id",
        (content_id,),
    ).fetchall()
    maturity_codes = tuple(
        row["maturity_code"] for row in db.execute(
            "SELECT maturity_code FROM content_maturity_levels WHERE content_item_id=? "
            "ORDER BY sort_order,maturity_code", (content_id,)
        )
    )
    if (
        not industry_rows
        or any(
            row["branch_status"] != "published"
            or row["industry_status"] != "published"
            or not is_exact_nonblank_text(row["name"])
            for row in industry_rows
        )
        or not department_rows
        or any(
            row["status"] != "published" or not is_exact_nonblank_text(row["name"])
            for row in department_rows
        )
        or not pain_rows
        or any(
            row["status"] != "published" or not is_exact_nonblank_text(row["name"])
            for row in pain_rows
        )
        or public_input_texts(input_rows) is None
        or not maturity_codes
        or any(code not in {"explore", "pilot", "scale", "collaborate"} for code in maturity_codes)
    ):
        raise ContentValidationError("scenario_public_incomplete")
    if not draft.blocks or not any(_meaningful_html(block.body_html) for block in draft.blocks):
        raise ContentValidationError("scenario_public_incomplete")
    for service in rows:
        if (
            service["service_id"] is None or service["service_status"] != "published"
            or not is_exact_nonblank_text(service["service_name"])
            or not is_valid_public_budget_range(service["min_budget"], service["max_budget"])
            or not is_valid_public_week_range(service["service_min_weeks"], service["service_max_weeks"])
        ):
            raise ContentValidationError("scenario_public_incomplete")
        source_lists = tuple(
            _decode_content_json(service[column])
            for column in ("implementation_steps_json", "prerequisites_json", "acceptance_json")
        )
        if not all(_nonblank_strings(values) for values in source_lists):
            raise ContentValidationError("scenario_public_incomplete")
        deliverables = db.execute(
            "SELECT title FROM service_deliverables WHERE service_id=? AND status='published' "
            "ORDER BY sort_order,id", (service["service_id"],)
        ).fetchall()
        if not deliverables or not all(
            is_exact_nonblank_text(row["title"]) for row in deliverables
        ):
            raise ContentValidationError("scenario_public_incomplete")


def source_check_expiry(db, content_id):
    item = db.execute("SELECT entry_type FROM content_items WHERE id=?", (content_id,)).fetchone()
    if item is None:
        raise ContentNotFoundError()
    if item["entry_type"] not in {"case", "resource"}:
        return None, False
    table = EXTENSION_TABLES[item["entry_type"]][0]
    row = db.execute(
        f"SELECT * FROM {table} WHERE content_item_id=?", (content_id,)
    ).fetchone()
    required = (
        item["entry_type"] == "case" and row["basis_type"] == "public_source"
    ) or (
        item["entry_type"] == "resource" and row["is_original"] == 0
    )
    return row["source_check_expires_at"], required
