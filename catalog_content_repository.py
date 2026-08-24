"""Read models and transaction services for the core content catalog."""

from dataclasses import dataclass
from typing import Any

import models
from content_clock import as_shanghai
from content_contracts import ContentDraft
from content_validation import ContentValidationError
from pagination import Page, PageRequest
import publishing_repository
import publishing_service
from publishing_repository import ContentConflictError, ContentNotFoundError


KIND_CONFIG = {
    "industry": {
        "table": "industries",
        "identity": "industry_id",
        "fields": (
            ("code", "稳定代码"),
            ("name", "核心名称"),
            ("sort_order", "目录顺序"),
        ),
    },
    "scenario": {
        "table": "scenarios",
        "identity": "scenario_id",
        "fields": (
            ("code", "稳定代码"),
            ("category_code", "类别代码"),
            ("minimum_business_value", "业务价值门槛"),
            ("minimum_process", "流程门槛"),
            ("minimum_data", "数据门槛"),
            ("minimum_systems", "系统门槛"),
            ("minimum_organization", "组织门槛"),
            ("minimum_delivery", "交付门槛"),
            ("integration_level", "集成级别"),
            ("min_weeks", "最短周期"),
            ("max_weeks", "最长周期"),
            ("risk_codes_json", "风险代码"),
            ("fallback_only", "仅作兜底"),
            ("sort_order", "目录顺序"),
        ),
    },
    "service": {
        "table": "services",
        "identity": "service_id",
        "fields": (
            ("code", "稳定代码"),
            ("public_name", "核心名称"),
            ("category", "服务类别"),
            ("min_budget", "预算下限"),
            ("max_budget", "预算上限"),
            ("min_weeks", "最短周期"),
            ("max_weeks", "最长周期"),
            ("implementation_steps_json", "实施步骤"),
            ("prerequisites_json", "客户配合"),
            ("not_included_json", "不包含范围"),
            ("acceptance_json", "验收标准"),
            ("support_days", "支持天数"),
            ("support_description", "支持说明"),
            ("public_disclaimer", "公开声明"),
            ("sort_order", "目录顺序"),
        ),
    },
}


class CatalogKindError(LookupError):
    pass


@dataclass(frozen=True)
class CatalogRow:
    kind: str
    core_id: int
    code: str
    group_key: str
    group_id: int
    slug: str
    title: str
    status: str
    draft_id: int | None
    public_id: int | None


@dataclass(frozen=True)
class RevisionProjection:
    id: int
    revision_number: int
    status: str
    lock_version: int
    slug: str
    title: str
    summary: str
    seo_title: str
    seo_description: str
    share_image_media_id: int | None
    blocks: tuple[Any, ...]
    relations: tuple[Any, ...]
    maturity_codes: tuple[str, ...]


@dataclass(frozen=True)
class RelationChoice:
    group_id: int
    entry_type: str
    title: str


@dataclass(frozen=True)
class MediaChoice:
    id: int
    display_name: str
    detected_mime: str


@dataclass(frozen=True)
class EditorProjection:
    kind: str
    core_id: int
    code: str
    group_key: str
    group_id: int
    slug: str
    readonly_fields: tuple[tuple[str, Any], ...]
    public_revision: RevisionProjection | None
    draft_revision: RevisionProjection | None
    latest_archived: RevisionProjection | None
    relation_choices: tuple[RelationChoice, ...]
    media_choices: tuple[MediaChoice, ...]


@dataclass(frozen=True)
class SaveResult:
    content_id: int
    lock_version: int
    published: bool


def _config(kind):
    try:
        return KIND_CONFIG[kind]
    except (KeyError, TypeError) as error:
        raise CatalogKindError(kind) from error


def list_catalog(db, kind: str, page_request: PageRequest) -> Page[CatalogRow]:
    config = _config(kind)
    table = config["table"]
    identity = config["identity"]
    total = db.execute(
        f"SELECT COUNT(*) FROM content_groups g JOIN {table} core "
        f"ON core.id=g.{identity} WHERE g.entry_type=? AND core.status='published' "
        "AND core.code IS NOT NULL",
        (kind,),
    ).fetchone()[0]
    if total == 0:
        return Page((), 1, page_request.per_page, 0, 0)
    total_pages = (total + page_request.per_page - 1) // page_request.per_page
    page_number = page_request.page if page_request.page <= total_pages else 1
    rows = db.execute(
        f"SELECT core.id AS core_id,core.code,g.id AS group_id,g.canonical_slug,"
        "d.id AS draft_id,d.title AS draft_title,p.id AS public_id,p.title AS public_title "
        f"FROM content_groups g JOIN {table} core ON core.id=g.{identity} "
        "LEFT JOIN content_items d ON d.content_group_id=g.id AND d.status='draft' "
        "LEFT JOIN content_items p ON p.content_group_id=g.id AND p.status='published' "
        "WHERE g.entry_type=? AND core.status='published' AND core.code IS NOT NULL "
        "ORDER BY core.sort_order,core.id LIMIT ? OFFSET ?",
        (
            kind,
            page_request.per_page,
            (page_number - 1) * page_request.per_page,
        ),
    ).fetchall()
    items = tuple(
        CatalogRow(
            kind=kind,
            core_id=row["core_id"],
            code=row["code"],
            group_key=f"{kind}:{row['code']}",
            group_id=row["group_id"],
            slug=row["canonical_slug"],
            title=row["draft_title"] or row["public_title"] or row["code"],
            status="draft" if row["draft_id"] else "published" if row["public_id"] else "archived",
            draft_id=row["draft_id"],
            public_id=row["public_id"],
        )
        for row in rows
    )
    return Page(items, page_number, page_request.per_page, total, total_pages)


def get_catalog_page(kind: str, page_request: PageRequest) -> Page[CatalogRow]:
    db = models.get_db()
    try:
        return list_catalog(db, kind, page_request)
    finally:
        db.close()


def _load_identity(db, kind, core_id):
    config = _config(kind)
    if type(core_id) is not int or core_id < 1:
        raise ContentNotFoundError()
    row = db.execute(
        f"SELECT core.*,g.id AS group_id,g.canonical_slug FROM {config['table']} core "
        f"JOIN content_groups g ON g.{config['identity']}=core.id "
        "WHERE core.id=? AND core.code IS NOT NULL AND core.status='published' "
        "AND g.entry_type=?",
        (core_id, kind),
    ).fetchone()
    if row is None:
        raise ContentNotFoundError()
    return row, config


def _revision(db, content_id):
    if content_id is None:
        return None
    item = db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
    if item is None:
        return None
    aggregate = publishing_repository.load_content_draft(db, content_id)
    return RevisionProjection(
        id=item["id"],
        revision_number=item["revision_number"],
        status=item["status"],
        lock_version=item["lock_version"],
        slug=item["slug"],
        title=aggregate.title,
        summary=aggregate.summary,
        seo_title=aggregate.seo_title,
        seo_description=aggregate.seo_description,
        share_image_media_id=aggregate.share_image_media_id,
        blocks=aggregate.blocks,
        relations=aggregate.relations,
        maturity_codes=aggregate.maturity_codes,
    )


def load_editor(db, kind: str, core_id: int) -> EditorProjection:
    identity_row, config = _load_identity(db, kind, core_id)
    group_id = identity_row["group_id"]
    states = {
        row["status"]: row["id"]
        for row in db.execute(
            "SELECT id,status FROM content_items WHERE content_group_id=? "
            "AND status IN ('draft','published')",
            (group_id,),
        )
    }
    archived = db.execute(
        "SELECT id FROM content_items WHERE content_group_id=? AND status='archived' "
        "ORDER BY revision_number DESC LIMIT 1",
        (group_id,),
    ).fetchone()
    relation_choices = tuple(
        RelationChoice(row["group_id"], row["entry_type"], row["title"])
        for row in db.execute(
            "SELECT g.id AS group_id,g.entry_type,ci.title FROM content_groups g "
            "JOIN content_items ci ON ci.content_group_id=g.id AND ci.status='published' "
            "WHERE g.entry_type IN ('case','resource') "
            "ORDER BY g.entry_type,ci.title,g.id"
        )
    )
    media_choices = tuple(
        MediaChoice(row["id"], row["display_name"], row["detected_mime"])
        for row in db.execute(
            "SELECT id,display_name,detected_mime FROM media_assets "
            "WHERE status='ready' ORDER BY display_name,id"
        )
    )
    return EditorProjection(
        kind=kind,
        core_id=core_id,
        code=identity_row["code"],
        group_key=f"{kind}:{identity_row['code']}",
        group_id=group_id,
        slug=identity_row["canonical_slug"],
        readonly_fields=tuple(
            (label, identity_row[column]) for column, label in config["fields"]
        ),
        public_revision=_revision(db, states.get("published")),
        draft_revision=_revision(db, states.get("draft")),
        latest_archived=_revision(db, archived["id"] if archived else None),
        relation_choices=relation_choices,
        media_choices=media_choices,
    )


def get_editor(kind: str, core_id: int) -> EditorProjection:
    db = models.get_db()
    try:
        return load_editor(db, kind, core_id)
    finally:
        db.close()


def ensure_editable_revision(kind: str, core_id: int, *, actor: str, now) -> EditorProjection:
    view = get_editor(kind, core_id)
    if view.draft_revision is not None:
        return view
    source = view.public_revision or view.latest_archived
    if source is None:
        raise ContentNotFoundError()
    try:
        publishing_service.copy_revision(source.id, actor=actor, now=now)
    except ContentConflictError as error:
        if error.code != "draft_already_exists":
            raise
    return get_editor(kind, core_id)


def _assert_content_identity(db, kind, core_id, content_id):
    identity_row, _ = _load_identity(db, kind, core_id)
    item = db.execute(
        "SELECT * FROM content_items WHERE id=? AND content_group_id=? AND entry_type=?",
        (content_id, identity_row["group_id"], kind),
    ).fetchone()
    if item is None:
        raise ContentNotFoundError()
    return item


def _assert_relation_targets(db, draft):
    for relation in draft.relations:
        expected_type = "case" if relation.relation_type.endswith("_case") else "resource"
        target = db.execute(
            "SELECT 1 FROM content_groups g JOIN content_items ci ON ci.content_group_id=g.id "
            "WHERE g.id=? AND g.entry_type=? AND ci.status='published'",
            (relation.target_group_id, expected_type),
        ).fetchone()
        if target is None:
            raise ContentValidationError("relation_target_not_published")


def _assert_media_choices(db, draft):
    media_ids = [draft.share_image_media_id]
    media_ids.extend(block.media_asset_id for block in draft.blocks)
    for media_id in media_ids:
        if media_id is None:
            continue
        ready = db.execute(
            "SELECT 1 FROM media_assets WHERE id=? AND status='ready'",
            (media_id,),
        ).fetchone()
        if ready is None:
            raise ContentValidationError("media_not_ready")


def save_catalog_draft(
    kind: str,
    core_id: int,
    content_id: int,
    expected_lock_version: int,
    draft: ContentDraft,
    *,
    action: str,
    actor: str,
    now,
) -> SaveResult:
    if action not in {"save", "review", "publish"}:
        raise ContentValidationError("action_invalid")
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        _assert_content_identity(db, kind, core_id, content_id)
        _assert_relation_targets(db, draft)
        _assert_media_choices(db, draft)
        lock_version = publishing_repository.update_content_draft(
            db,
            content_id,
            expected_lock_version,
            draft,
            actor=actor,
            now=instant,
        )
        published = False
        if action == "review":
            publishing_repository.validate_for_publication(db, content_id, instant)
            publishing_repository.write_audit_event(
                db, content_id, "content_reviewed", actor, instant
            )
        elif action == "publish":
            publishing_service._publish_in_transaction(
                db, content_id, lock_version, actor, instant
            )
            published = True
            lock_version += 1
        db.commit()
        return SaveResult(content_id, lock_version, published)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def archive_catalog_revision(
    kind: str,
    core_id: int,
    content_id: int,
    expected_lock_version: int,
    *,
    actor: str,
    now,
):
    db = models.get_db()
    try:
        _assert_content_identity(db, kind, core_id, content_id)
    finally:
        db.close()
    publishing_service.archive_content(
        content_id,
        expected_lock_version,
        actor=actor,
        now=now,
    )
