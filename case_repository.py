"""Verified-case aggregate transactions and fail-closed public projections."""

from dataclasses import dataclass, replace

import models
from content_clock import as_shanghai, format_shanghai
from content_contracts import CaseMetric, ContentBlock, ContentDraft
from content_validation import ContentValidationError
from media_validation import IMAGE_MIMES
from pagination import Page, PageRequest
import publishing_repository
import publishing_service
from publishing_repository import ContentNotFoundError


VERIFICATION_LABELS = {
    "public_verified": "真实公开案例",
    "authorized_anonymous": "经授权匿名案例",
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
class CaseForm:
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
    verification_code: str
    is_verified: int
    basis_type: str
    private_basis_reference: str
    source_url: str
    source_url_sha256: str | None
    source_check_code: str | None
    source_checked_at: str | None
    source_check_expires_at: str | None
    source_check_url_sha256: str | None
    review_confirmed: int
    verified_at: str | None
    blocks: tuple[ContentBlock, ...]
    metrics: tuple[CaseMetric, ...]


@dataclass(frozen=True)
class EditorView:
    form: CaseForm
    public_revision: CaseForm | None
    media_choices: tuple[MediaChoice, ...]
    share_image_choices: tuple[MediaChoice, ...]


@dataclass(frozen=True)
class AdminCaseRow:
    id: int
    slug: str
    title: str
    status: str
    revision_number: int
    lock_version: int
    updated_at: str


@dataclass(frozen=True)
class PublicCase:
    slug: str
    title: str
    summary: str
    seo_title: str
    seo_description: str
    share_image_media_id: int | None
    verification_label: str
    verified_at: str
    blocks: tuple[ContentBlock, ...]
    metrics: tuple[CaseMetric, ...]
    redirect: bool = False


def blank_case_form() -> CaseForm:
    return CaseForm(
        id=None,
        content_group_id=None,
        revision_number=1,
        status="draft",
        lock_version=1,
        slug="",
        title="",
        summary="",
        seo_title="",
        seo_description="",
        share_image_media_id=None,
        verification_code="authorized_anonymous",
        is_verified=0,
        basis_type="client_authorization",
        private_basis_reference="",
        source_url="",
        source_url_sha256=None,
        source_check_code=None,
        source_checked_at=None,
        source_check_expires_at=None,
        source_check_url_sha256=None,
        review_confirmed=0,
        verified_at=None,
        blocks=(ContentBlock("rich_text", "", "", {}, None, 0),),
        metrics=(CaseMetric("", "", "", "", "", "", 0),),
    )


def submitted_form(draft: ContentDraft, content_id=None, lock_version=1) -> CaseForm:
    extension = draft.extension
    return CaseForm(
        id=content_id,
        content_group_id=draft.content_group_id,
        revision_number=1,
        status="draft",
        lock_version=lock_version,
        slug=draft.slug,
        title=draft.title,
        summary=draft.summary,
        seo_title=draft.seo_title,
        seo_description=draft.seo_description,
        share_image_media_id=draft.share_image_media_id,
        verification_code=extension["verification_code"],
        is_verified=extension["is_verified"],
        basis_type=extension["basis_type"],
        private_basis_reference=extension.get("private_basis_reference") or "",
        source_url=extension.get("source_url") or "",
        source_url_sha256=extension.get("source_url_sha256"),
        source_check_code=extension.get("source_check_code"),
        source_checked_at=extension.get("source_checked_at"),
        source_check_expires_at=extension.get("source_check_expires_at"),
        source_check_url_sha256=extension.get("source_check_url_sha256"),
        review_confirmed=extension["review_confirmed"],
        verified_at=extension.get("verified_at"),
        blocks=draft.blocks,
        metrics=draft.metrics,
    )


def _case_form(db, content_id) -> CaseForm:
    item = db.execute(
        "SELECT * FROM content_items WHERE id=? AND entry_type='case'", (content_id,)
    ).fetchone()
    if item is None:
        raise ContentNotFoundError()
    draft = publishing_repository.load_content_draft(db, content_id)
    form = submitted_form(draft, content_id, item["lock_version"])
    return replace(
        form,
        revision_number=item["revision_number"],
        status=item["status"],
    )


def _media_choices(db):
    choices = tuple(
        MediaChoice(row["id"], row["display_name"], row["detected_mime"])
        for row in db.execute(
            "SELECT id,display_name,detected_mime FROM media_assets "
            "WHERE status='ready' ORDER BY display_name,id"
        )
    )
    return choices, tuple(
        media for media in choices if media.detected_mime in IMAGE_MIMES
    )


def get_editor(content_id=None, *, form=None) -> EditorView:
    db = models.get_db()
    try:
        current = _case_form(db, content_id) if content_id is not None else blank_case_form()
        public = None
        group_id = current.content_group_id
        if group_id is not None:
            row = db.execute(
                "SELECT id FROM content_items WHERE content_group_id=? "
                "AND entry_type='case' AND status='published'",
                (group_id,),
            ).fetchone()
            if row is not None:
                public = _case_form(db, row["id"])
        media, images = _media_choices(db)
        return EditorView(form or current, public, media, images)
    finally:
        db.close()


def ensure_editable(content_id, *, actor, now) -> int:
    db = models.get_db()
    try:
        item = db.execute(
            "SELECT * FROM content_items WHERE id=? AND entry_type='case'", (content_id,)
        ).fetchone()
        if item is None:
            raise ContentNotFoundError()
        if item["status"] == "draft":
            return content_id
        draft = db.execute(
            "SELECT id FROM content_items WHERE content_group_id=? "
            "AND entry_type='case' AND status='draft'",
            (item["content_group_id"],),
        ).fetchone()
        if draft is not None:
            return draft["id"]
    finally:
        db.close()
    return publishing_service.copy_revision(content_id, actor=actor, now=now)


def admin_cases(page_request: PageRequest) -> Page[AdminCaseRow]:
    db = models.get_db()
    try:
        total = db.execute(
            "SELECT COUNT(*) FROM content_items WHERE entry_type='case'"
        ).fetchone()[0]
        if total == 0:
            return Page((), 1, page_request.per_page, 0, 0)
        total_pages = (total + page_request.per_page - 1) // page_request.per_page
        page_number = min(page_request.page, total_pages)
        rows = tuple(
            AdminCaseRow(
                row["id"], row["slug"], row["title"], row["status"],
                row["revision_number"], row["lock_version"], row["updated_at"],
            )
            for row in db.execute(
                "SELECT id,slug,title,status,revision_number,lock_version,updated_at "
                "FROM content_items WHERE entry_type='case' "
                "ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
                (page_request.per_page, (page_number - 1) * page_request.per_page),
            )
        )
        return Page(rows, page_number, page_request.per_page, total, total_pages)
    finally:
        db.close()


def _assert_media_ready(db, draft):
    ids = [draft.share_image_media_id]
    ids.extend(block.media_asset_id for block in draft.blocks)
    for media_id in ids:
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


def create_case(draft, *, action, actor, now):
    if action not in {"save", "review", "publish"}:
        raise ContentValidationError("action_invalid")
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        _assert_media_ready(db, draft)
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


def save_case(content_id, expected_lock_version, draft, *, action, actor, now):
    if action not in {"save", "review", "publish"}:
        raise ContentValidationError("action_invalid")
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        item = db.execute(
            "SELECT content_group_id FROM content_items "
            "WHERE id=? AND entry_type='case'", (content_id,)
        ).fetchone()
        if item is None:
            raise ContentNotFoundError()
        _assert_media_ready(db, draft)
        lock_version = publishing_repository.update_content_draft(
            db,
            content_id,
            expected_lock_version,
            draft,
            actor=actor,
            now=instant,
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


def archive_case(content_id, expected_lock_version, *, actor, now):
    db = models.get_db()
    try:
        row = db.execute(
            "SELECT 1 FROM content_items WHERE id=? AND entry_type='case'", (content_id,)
        ).fetchone()
        if row is None:
            raise ContentNotFoundError()
    finally:
        db.close()
    publishing_service.archive_content(
        content_id, expected_lock_version, actor=actor, now=now
    )


def refresh_source_check(
    content_id, expected_lock_version, expected_url_sha256, *, actor, transport, now
):
    db = models.get_db()
    try:
        row = db.execute(
            "SELECT cc.basis_type FROM content_items ci JOIN case_content cc "
            "ON cc.content_item_id=ci.id WHERE ci.id=? AND ci.entry_type='case'",
            (content_id,),
        ).fetchone()
        if row is None:
            raise ContentNotFoundError()
        if row["basis_type"] != "public_source":
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


def _validated_public_case(db, content_id, now, *, redirect=False):
    try:
        draft = publishing_repository.validate_for_publication(db, content_id, now)
    except ContentValidationError:
        return None
    item = db.execute(
        "SELECT status,publish_at,slug FROM content_items WHERE id=?", (content_id,)
    ).fetchone()
    if item is None or item["status"] != "published":
        return None
    if item["publish_at"] is not None and item["publish_at"] > format_shanghai(now):
        return None
    label = VERIFICATION_LABELS.get(draft.extension.get("verification_code"))
    if label is None:
        return None
    return PublicCase(
        slug=item["slug"],
        title=draft.title,
        summary=draft.summary,
        seo_title=draft.seo_title,
        seo_description=draft.seo_description,
        share_image_media_id=draft.share_image_media_id,
        verification_label=label,
        verified_at=draft.extension["verified_at"],
        blocks=draft.blocks,
        metrics=draft.metrics,
        redirect=redirect,
    )


def public_cases(page_request: PageRequest, now) -> Page[PublicCase]:
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        ids = tuple(
            row["id"]
            for row in db.execute(
                "SELECT id FROM content_items WHERE entry_type='case' "
                "AND status='published' AND (publish_at IS NULL OR publish_at<=?) "
                "ORDER BY published_at DESC,id DESC",
                (format_shanghai(instant),),
            )
        )
        valid = tuple(
            case
            for content_id in ids
            if (case := _validated_public_case(db, content_id, instant)) is not None
        )
        total = len(valid)
        if total == 0:
            return Page((), 1, page_request.per_page, 0, 0)
        total_pages = (total + page_request.per_page - 1) // page_request.per_page
        page_number = min(page_request.page, total_pages)
        start = (page_number - 1) * page_request.per_page
        return Page(
            valid[start : start + page_request.per_page],
            page_number,
            page_request.per_page,
            total,
            total_pages,
        )
    finally:
        db.close()


def public_case(slug, now):
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        row = db.execute(
            "SELECT id FROM content_items WHERE entry_type='case' AND slug=? "
            "AND status='published' AND (publish_at IS NULL OR publish_at<=?)",
            (slug, format_shanghai(instant)),
        ).fetchone()
        if row is not None:
            return _validated_public_case(db, row["id"], instant)
        alias = db.execute(
            "SELECT ci.id FROM content_slug_aliases a JOIN content_items ci "
            "ON ci.content_group_id=a.content_group_id "
            "WHERE a.entry_type='case' AND a.old_slug=? "
            "AND ci.entry_type='case' AND ci.status='published' "
            "AND (ci.publish_at IS NULL OR ci.publish_at<=?)",
            (slug, format_shanghai(instant)),
        ).fetchone()
        if alias is None:
            return None
        return _validated_public_case(db, alias["id"], instant, redirect=True)
    finally:
        db.close()
