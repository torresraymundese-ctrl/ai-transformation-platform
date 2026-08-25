"""Reviewed resource/announcement aggregates and fail-closed public projections."""

from dataclasses import dataclass, replace

import models
from content_clock import as_shanghai, format_shanghai
from content_contracts import ContentBlock, ContentDraft
from content_validation import ContentValidationError
from media_validation import ATTACHMENT_MIMES, IMAGE_MIMES
from pagination import Page, PageRequest
import publishing_repository
import publishing_service
from publishing_repository import ContentNotFoundError


RESOURCE_TYPES = frozenset({"article", "guide", "report", "template", "policy"})
RESOURCE_TYPE_LABELS = {
    "article": "文章",
    "guide": "指南",
    "report": "报告",
    "template": "模板",
    "policy": "政策",
}


@dataclass(frozen=True)
class SaveResult:
    content_id: int
    lock_version: int
    published: bool


@dataclass(frozen=True)
class MediaChoice:
    id: int
    display_name: str
    detected_mime: str


@dataclass(frozen=True)
class ResourceForm:
    id: int | None
    content_group_id: int | None
    revision_number: int
    status: str
    lock_version: int
    slug: str
    title: str
    summary: str
    seo_title: str
    seo_description: str
    share_image_media_id: int | None
    resource_type: str
    is_original: int
    source_name: str
    source_url: str
    source_url_sha256: str | None
    source_check_code: str | None
    source_checked_at: str | None
    source_check_expires_at: str | None
    source_check_url_sha256: str | None
    original_published_at: str
    copyright_notice: str
    attachment_media_id: int | None
    blocks: tuple[ContentBlock, ...]


@dataclass(frozen=True)
class AnnouncementForm:
    id: int | None
    content_group_id: int | None
    revision_number: int
    status: str
    lock_version: int
    slug: str
    title: str
    summary: str
    seo_title: str
    seo_description: str
    share_image_media_id: int | None
    valid_from: str
    valid_until: str
    cta_url: str
    blocks: tuple[ContentBlock, ...]


@dataclass(frozen=True)
class EditorView:
    form: ResourceForm | AnnouncementForm
    public_revision: ResourceForm | AnnouncementForm | None
    media_choices: tuple[MediaChoice, ...]
    share_image_choices: tuple[MediaChoice, ...]
    attachment_choices: tuple[MediaChoice, ...]


@dataclass(frozen=True)
class AdminContentRow:
    id: int
    slug: str
    title: str
    status: str
    revision_number: int
    lock_version: int
    updated_at: str


@dataclass(frozen=True)
class ResourceFilters:
    resource_type: str | None = None

    def __post_init__(self):
        if self.resource_type is not None and (
            type(self.resource_type) is not str
            or self.resource_type not in RESOURCE_TYPES
        ):
            raise ValueError("invalid resource type filter")


@dataclass(frozen=True)
class ResourceCard:
    slug: str
    title: str
    summary: str
    seo_title: str
    seo_description: str
    share_image_media_id: int | None
    resource_type: str
    resource_type_label: str
    is_original: bool
    source_name: str | None
    source_url: str | None
    original_published_at: str
    copyright_notice: str
    attachment_media_id: int | None
    blocks: tuple[ContentBlock, ...]
    redirect: bool = False


ResourceDetail = ResourceCard


@dataclass(frozen=True)
class AnnouncementCard:
    slug: str
    title: str
    summary: str
    seo_title: str
    seo_description: str
    share_image_media_id: int | None
    valid_from: str
    valid_until: str
    cta_url: str | None
    blocks: tuple[ContentBlock, ...]
    redirect: bool = False


AnnouncementDetail = AnnouncementCard


def blank_resource_form():
    return ResourceForm(
        None, None, 1, "draft", 1, "", "", "", "", "", None,
        "guide", 1, "", "", None, None, None, None, None, "", "", None,
        (ContentBlock("rich_text", "", "", {}, None, 0),),
    )


def blank_announcement_form():
    return AnnouncementForm(
        None, None, 1, "draft", 1, "", "", "", "", "", None,
        "", "", "", (ContentBlock("rich_text", "", "", {}, None, 0),),
    )


def submitted_resource_form(draft, content_id=None, lock_version=1):
    extension = draft.extension
    return ResourceForm(
        content_id, draft.content_group_id, 1, "draft", lock_version,
        draft.slug, draft.title, draft.summary, draft.seo_title,
        draft.seo_description, draft.share_image_media_id,
        extension["resource_type"], extension["is_original"],
        extension.get("source_name") or "", extension.get("source_url") or "",
        extension.get("source_url_sha256"), extension.get("source_check_code"),
        extension.get("source_checked_at"), extension.get("source_check_expires_at"),
        extension.get("source_check_url_sha256"),
        extension.get("original_published_at") or "",
        extension.get("copyright_notice") or "",
        extension.get("attachment_media_id"), draft.blocks,
    )


def submitted_announcement_form(draft, content_id=None, lock_version=1):
    extension = draft.extension
    return AnnouncementForm(
        content_id, draft.content_group_id, 1, "draft", lock_version,
        draft.slug, draft.title, draft.summary, draft.seo_title,
        draft.seo_description, draft.share_image_media_id,
        extension.get("valid_from") or "", extension.get("valid_until") or "",
        extension.get("cta_url") or "", draft.blocks,
    )


def _form(db, content_id, entry_type):
    item = db.execute(
        "SELECT * FROM content_items WHERE id=? AND entry_type=?",
        (content_id, entry_type),
    ).fetchone()
    if item is None:
        raise ContentNotFoundError()
    draft = publishing_repository.load_content_draft(db, content_id)
    if entry_type == "resource":
        form = submitted_resource_form(draft, content_id, item["lock_version"])
    else:
        form = submitted_announcement_form(draft, content_id, item["lock_version"])
    return replace(
        form, revision_number=item["revision_number"], status=item["status"]
    )


def _media_choices(db):
    choices = tuple(
        MediaChoice(row["id"], row["display_name"], row["detected_mime"])
        for row in db.execute(
            "SELECT id,display_name,detected_mime FROM media_assets "
            "WHERE status='ready' ORDER BY display_name,id"
        )
    )
    return (
        choices,
        tuple(choice for choice in choices if choice.detected_mime in IMAGE_MIMES),
        tuple(choice for choice in choices if choice.detected_mime in ATTACHMENT_MIMES),
    )


def get_editor(entry_type, content_id=None, *, form=None):
    if entry_type not in {"resource", "announcement"}:
        raise ContentNotFoundError()
    db = models.get_db()
    try:
        if content_id is None:
            current = (
                blank_resource_form()
                if entry_type == "resource"
                else blank_announcement_form()
            )
        else:
            current = _form(db, content_id, entry_type)
        public = None
        if current.content_group_id is not None:
            row = db.execute(
                "SELECT id FROM content_items WHERE content_group_id=? "
                "AND entry_type=? AND status='published'",
                (current.content_group_id, entry_type),
            ).fetchone()
            if row is not None:
                public = _form(db, row["id"], entry_type)
        media, images, attachments = _media_choices(db)
        return EditorView(form or current, public, media, images, attachments)
    finally:
        db.close()


def editable_revision(content_id, entry_type):
    db = models.get_db()
    try:
        item = db.execute(
            "SELECT * FROM content_items WHERE id=? AND entry_type=?",
            (content_id, entry_type),
        ).fetchone()
        if item is None:
            raise ContentNotFoundError()
        if item["status"] == "draft":
            return content_id
        draft = db.execute(
            "SELECT id FROM content_items WHERE content_group_id=? "
            "AND entry_type=? AND status='draft'",
            (item["content_group_id"], entry_type),
        ).fetchone()
        return draft["id"] if draft is not None else None
    finally:
        db.close()


def copy_revision(content_id, expected_lock_version, entry_type, *, actor, now):
    return publishing_service.copy_revision(
        content_id,
        actor=actor,
        now=now,
        expected_lock_version=expected_lock_version,
        expected_entry_type=entry_type,
    )


def admin_entries(entry_type, page_request):
    if entry_type not in {"resource", "announcement"}:
        raise ContentNotFoundError()
    db = models.get_db()
    try:
        total = db.execute(
            "SELECT COUNT(*) FROM content_items WHERE entry_type=?", (entry_type,)
        ).fetchone()[0]
        if total == 0:
            return Page((), 1, page_request.per_page, 0, 0)
        total_pages = (total + page_request.per_page - 1) // page_request.per_page
        page_number = min(page_request.page, total_pages)
        items = tuple(
            AdminContentRow(
                row["id"], row["slug"], row["title"], row["status"],
                row["revision_number"], row["lock_version"], row["updated_at"],
            )
            for row in db.execute(
                "SELECT id,slug,title,status,revision_number,lock_version,updated_at "
                "FROM content_items WHERE entry_type=? ORDER BY updated_at DESC,id DESC "
                "LIMIT ? OFFSET ?",
                (
                    entry_type,
                    page_request.per_page,
                    (page_number - 1) * page_request.per_page,
                ),
            )
        )
        return Page(items, page_number, page_request.per_page, total, total_pages)
    finally:
        db.close()


def _assert_draft_media_ready(db, draft):
    media_ids = [draft.share_image_media_id]
    media_ids.extend(block.media_asset_id for block in draft.blocks)
    if draft.entry_type == "resource":
        media_ids.append(draft.extension.get("attachment_media_id"))
    for media_id in media_ids:
        if media_id is None:
            continue
        if db.execute(
            "SELECT 1 FROM media_assets WHERE id=? AND status='ready'", (media_id,)
        ).fetchone() is None:
            raise ContentValidationError("media_not_ready")


def _finish_action(db, content_id, lock_version, action, actor, instant):
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
        lock_version += 1
        published = True
    return SaveResult(content_id, lock_version, published)


def create_entry(draft, *, action, actor, now):
    if draft.entry_type not in {"resource", "announcement"}:
        raise ContentValidationError("entry_type_invalid")
    if action not in {"save", "review", "publish"}:
        raise ContentValidationError("action_invalid")
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        _assert_draft_media_ready(db, draft)
        content_id = publishing_repository.insert_content_draft(
            db, draft, actor=actor, now=instant
        )
        result = _finish_action(db, content_id, 1, action, actor, instant)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_entry(content_id, expected_lock_version, draft, *, action, actor, now):
    if draft.entry_type not in {"resource", "announcement"}:
        raise ContentValidationError("entry_type_invalid")
    if action not in {"save", "review", "publish"}:
        raise ContentValidationError("action_invalid")
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        item = db.execute(
            "SELECT content_group_id FROM content_items WHERE id=? AND entry_type=?",
            (content_id, draft.entry_type),
        ).fetchone()
        if item is None:
            raise ContentNotFoundError()
        _assert_draft_media_ready(db, draft)
        lock_version = publishing_repository.update_content_draft(
            db, content_id, expected_lock_version, draft, actor=actor, now=instant
        )
        result = _finish_action(
            db, content_id, lock_version, action, actor, instant
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def archive_entry(content_id, expected_lock_version, entry_type, *, actor, now):
    db = models.get_db()
    try:
        if db.execute(
            "SELECT 1 FROM content_items WHERE id=? AND entry_type=?",
            (content_id, entry_type),
        ).fetchone() is None:
            raise ContentNotFoundError()
    finally:
        db.close()
    publishing_service.archive_content(
        content_id, expected_lock_version, actor=actor, now=now
    )


def refresh_resource_source_check(
    content_id, expected_lock_version, expected_url_sha256, *, actor, transport, now
):
    db = models.get_db()
    try:
        row = db.execute(
            "SELECT rc.is_original FROM content_items ci JOIN resource_content rc "
            "ON rc.content_item_id=ci.id WHERE ci.id=? AND ci.entry_type='resource'",
            (content_id,),
        ).fetchone()
        if row is None:
            raise ContentNotFoundError()
        if row["is_original"] != 0:
            raise ContentValidationError("source_check_not_required")
    finally:
        db.close()
    return publishing_service.refresh_content_source_check(
        content_id,
        expected_lock_version,
        expected_url_sha256,
        actor=actor,
        transport=transport,
        now=now,
    )


def parse_resource_filters(values):
    try:
        raw = values.get("type")
    except (AttributeError, TypeError):
        raw = None
    return ResourceFilters(raw if raw in RESOURCE_TYPES else None)


def _validated_resource(db, content_id, now, *, redirect=False):
    try:
        draft = publishing_repository.validate_resource_public_completeness(
            db, content_id, now
        )
    except (ContentValidationError, TypeError, ValueError):
        return None
    item = db.execute(
        "SELECT status,publish_at,slug FROM content_items WHERE id=?", (content_id,)
    ).fetchone()
    if item is None or item["status"] != "published":
        return None
    if item["publish_at"] is not None and item["publish_at"] > format_shanghai(now):
        return None
    extension = draft.extension
    is_original = extension["is_original"] == 1
    return ResourceCard(
        item["slug"], draft.title, draft.summary, draft.seo_title,
        draft.seo_description, draft.share_image_media_id,
        extension["resource_type"], RESOURCE_TYPE_LABELS[extension["resource_type"]],
        is_original, None if is_original else extension["source_name"],
        None if is_original else extension["source_url"],
        extension["original_published_at"], extension["copyright_notice"],
        extension["attachment_media_id"], draft.blocks, redirect,
    )


def list_published_resources(filters, page, *, now):
    if type(filters) is not ResourceFilters or type(page) is not PageRequest:
        raise TypeError("exact filters and page contracts required")
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        db.execute("BEGIN")
        params = [format_shanghai(instant)]
        query = (
            "SELECT ci.id FROM content_items ci JOIN resource_content rc "
            "ON rc.content_item_id=ci.id WHERE ci.entry_type='resource' "
            "AND ci.status='published' AND (ci.publish_at IS NULL OR ci.publish_at<=?)"
        )
        if filters.resource_type is not None:
            query += " AND rc.resource_type=?"
            params.append(filters.resource_type)
        query += " ORDER BY ci.published_at DESC,ci.id DESC"
        valid = tuple(
            resource
            for row in db.execute(query, params)
            if (resource := _validated_resource(db, row["id"], instant)) is not None
        )
        total = len(valid)
        if total == 0:
            return Page((), 1, page.per_page, 0, 0)
        total_pages = (total + page.per_page - 1) // page.per_page
        page_number = min(page.page, total_pages)
        start = (page_number - 1) * page.per_page
        return Page(
            valid[start : start + page.per_page], page_number, page.per_page,
            total, total_pages,
        )
    finally:
        db.rollback()
        db.close()


def get_published_resource(slug, *, now):
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        db.execute("BEGIN")
        row = db.execute(
            "SELECT id FROM content_items WHERE entry_type='resource' AND slug=? "
            "AND status='published' AND (publish_at IS NULL OR publish_at<=?)",
            (slug, format_shanghai(instant)),
        ).fetchone()
        if row is not None:
            return _validated_resource(db, row["id"], instant)
        alias = db.execute(
            "SELECT ci.id FROM content_slug_aliases a JOIN content_items ci "
            "ON ci.content_group_id=a.content_group_id "
            "WHERE a.entry_type='resource' AND a.old_slug=? "
            "AND ci.entry_type='resource' AND ci.status='published' "
            "AND (ci.publish_at IS NULL OR ci.publish_at<=?)",
            (slug, format_shanghai(instant)),
        ).fetchone()
        if alias is None:
            return None
        return _validated_resource(db, alias["id"], instant, redirect=True)
    finally:
        db.rollback()
        db.close()


def _validated_announcement(db, content_id, now, *, redirect=False):
    try:
        draft = publishing_repository.validate_announcement_public_completeness(
            db, content_id, now
        )
    except (ContentValidationError, TypeError, ValueError):
        return None
    item = db.execute(
        "SELECT status,publish_at,slug FROM content_items WHERE id=?", (content_id,)
    ).fetchone()
    now_text = format_shanghai(now)
    if item is None or item["status"] != "published":
        return None
    if item["publish_at"] is not None and item["publish_at"] > now_text:
        return None
    extension = draft.extension
    if not (extension["valid_from"] <= now_text <= extension["valid_until"]):
        return None
    return AnnouncementCard(
        item["slug"], draft.title, draft.summary, draft.seo_title,
        draft.seo_description, draft.share_image_media_id,
        extension["valid_from"], extension["valid_until"],
        extension["cta_url"], draft.blocks, redirect,
    )


def list_current_announcements(*, now):
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        db.execute("BEGIN")
        return tuple(
            announcement
            for row in db.execute(
                "SELECT id FROM content_items WHERE entry_type='announcement' "
                "AND status='published' AND (publish_at IS NULL OR publish_at<=?) "
                "ORDER BY published_at DESC,id DESC",
                (format_shanghai(instant),),
            )
            if (
                announcement := _validated_announcement(db, row["id"], instant)
            ) is not None
        )
    finally:
        db.rollback()
        db.close()


def get_current_announcement(slug, *, now):
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        db.execute("BEGIN")
        row = db.execute(
            "SELECT id FROM content_items WHERE entry_type='announcement' AND slug=? "
            "AND status='published' AND (publish_at IS NULL OR publish_at<=?)",
            (slug, format_shanghai(instant)),
        ).fetchone()
        if row is not None:
            return _validated_announcement(db, row["id"], instant)
        alias = db.execute(
            "SELECT ci.id FROM content_slug_aliases a JOIN content_items ci "
            "ON ci.content_group_id=a.content_group_id "
            "WHERE a.entry_type='announcement' AND a.old_slug=? "
            "AND ci.entry_type='announcement' AND ci.status='published' "
            "AND (ci.publish_at IS NULL OR ci.publish_at<=?)",
            (slug, format_shanghai(instant)),
        ).fetchone()
        if alias is None:
            return None
        return _validated_announcement(db, alias["id"], instant, redirect=True)
    finally:
        db.rollback()
        db.close()
