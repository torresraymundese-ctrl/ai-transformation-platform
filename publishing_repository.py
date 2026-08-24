"""SQLite repository for content aggregates; caller owns every transaction."""

from dataclasses import replace
import json
import sqlite3

from content_clock import format_shanghai
from content_contracts import CaseMetric, ContentBlock, ContentDraft, ContentRelation
from content_validation import ContentValidationError, validate_content_draft


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


def _clear_changed_source_check(db, content_id, entry_type, extension):
    if entry_type not in {"case", "resource"}:
        return extension
    table = EXTENSION_TABLES[entry_type][0]
    current = db.execute(
        f"SELECT source_url_sha256 FROM {table} WHERE content_item_id=?", (content_id,)
    ).fetchone()
    if current is not None and current["source_url_sha256"] != extension.get("source_url_sha256"):
        extension = dict(extension)
        for key in (
            "source_check_code", "source_checked_at", "source_check_expires_at",
            "source_check_url_sha256",
        ):
            extension[key] = None
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
    return _insert_content_draft(db, draft, actor=actor, now=now, event_code="content_created")


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
    extension = _clear_changed_source_check(db, content_id, row["entry_type"], dict(validated.extension))
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
            settings=json.loads(row["settings_json"] or "{}"),
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


def validate_for_publication(db, content_id, now):
    draft = validate_content_draft(load_content_draft(db, content_id))
    if draft.share_image_media_id is not None and db.execute(
        "SELECT 1 FROM media_assets WHERE id=? AND status='ready'", (draft.share_image_media_id,)
    ).fetchone() is None:
        raise ContentValidationError("media_not_ready")
    for block in draft.blocks:
        if block.media_asset_id is not None and db.execute(
            "SELECT 1 FROM media_assets WHERE id=? AND status='ready'", (block.media_asset_id,)
        ).fetchone() is None:
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
        if (
            draft.extension.get("source_check_code") != "https_ok"
            or draft.extension.get("source_check_url_sha256") != source_hash
            or not draft.extension.get("source_check_expires_at")
            or draft.extension["source_check_expires_at"] < format_shanghai(now)
        ):
            raise ContentValidationError("source_check_invalid")
    if draft.entry_type == "case":
        if not draft.extension.get("is_verified") or not draft.extension.get("review_confirmed") or not draft.metrics:
            raise ContentValidationError("case_verification_incomplete")
    return draft


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
