"""Atomic content revision state machine and source-check orchestration."""

from dataclasses import replace
import sqlite3

import models
from content_clock import as_shanghai, format_shanghai, parse_shanghai, shanghai_now
from content_contracts import (
    ContentDraft,
    PublishDueResult,
    PublishResult,
    PublicRevisionResolution,
    ScheduleResult,
)
from content_validation import ContentValidationError
import publishing_repository as repository
from publishing_repository import (
    ContentConflictError,
    ContentNotFoundError,
    ContentStateError,
)
from source_url_checker import PinnedHttpTransport, check_source_url


def _instant(now):
    return as_shanghai(now if now is not None else shanghai_now())


def _write_transaction(callback):
    db = models.get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        result = callback(db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_content_draft(draft: ContentDraft, *, actor: str, now=None) -> int:
    instant = _instant(now)
    return _write_transaction(
        lambda db: repository.insert_content_draft(db, draft, actor=actor, now=instant)
    )


def save_content_draft(
    content_id: int,
    expected_lock_version: int,
    draft: ContentDraft,
    *,
    actor: str,
    now=None,
) -> int:
    instant = _instant(now)
    return _write_transaction(
        lambda db: repository.update_content_draft(
            db,
            content_id,
            expected_lock_version,
            draft,
            actor=actor,
            now=instant,
        )
    )


def copy_revision(content_id: int, *, actor: str, now=None) -> int:
    instant = _instant(now)

    def operation(db):
        item = db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
        if item is None:
            raise ContentNotFoundError()
        if item["status"] not in {"published", "archived"}:
            raise ContentStateError("copy_source_not_immutable")
        draft = repository.load_content_draft(db, content_id)
        draft = replace(draft, publish_at=None)
        return repository._insert_content_draft(
            db,
            draft,
            actor=actor,
            now=instant,
            event_code="content_revision_copied",
        )

    return _write_transaction(operation)


def schedule_content(
    content_id: int,
    expected_lock_version: int,
    publish_at,
    *,
    actor: str,
    now=None,
) -> ScheduleResult:
    instant = _instant(now)
    due = as_shanghai(publish_at)
    if due <= instant:
        raise ContentValidationError("publish_at_not_future")
    due_text = format_shanghai(due)

    def operation(db):
        item = db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
        _require_draft_lock(item, expected_lock_version)
        repository.validate_for_publication(db, content_id, instant)
        expiry, required = repository.source_check_expiry(db, content_id)
        if required and (expiry is None or expiry < due_text):
            raise ContentValidationError("source_check_expires_before_publish")
        timestamp = format_shanghai(instant)
        db.execute(
            "UPDATE content_items SET publish_at=?,lock_version=lock_version+1,updated_at=? WHERE id=?",
            (due_text, timestamp, content_id),
        )
        repository.write_audit_event(
            db, content_id, "content_scheduled", actor, instant, {"publish_at": due_text}
        )
        return ScheduleResult(content_id, due_text, expected_lock_version + 1)

    return _write_transaction(operation)


def _require_draft_lock(item, expected_lock_version):
    if item is None:
        raise ContentNotFoundError()
    if item["status"] != "draft":
        raise ContentStateError("content_not_draft")
    if item["lock_version"] != expected_lock_version:
        raise ContentConflictError("stale_lock_version")


def _publish_in_transaction(db, content_id, expected_lock_version, actor, instant):
    item = db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
    _require_draft_lock(item, expected_lock_version)
    timestamp = format_shanghai(instant)
    if item["publish_at"] is not None and item["publish_at"] > timestamp:
        raise ContentStateError("content_not_due")
    repository.validate_for_publication(db, content_id, instant)
    group = db.execute(
        "SELECT * FROM content_groups WHERE id=?", (item["content_group_id"],)
    ).fetchone()
    old = db.execute(
        "SELECT * FROM content_items WHERE content_group_id=? AND status='published'",
        (item["content_group_id"],),
    ).fetchone()
    archived_id = None
    if old is not None:
        archived_id = old["id"]
        db.execute(
            "UPDATE content_items SET status='archived',archived_at=?,"
            "lock_version=lock_version+1,updated_at=? WHERE id=? AND status='published'",
            (timestamp, timestamp, archived_id),
        )
    if group["canonical_slug"] != item["slug"]:
        old_slug = group["canonical_slug"]
        try:
            db.execute(
                "UPDATE content_groups SET canonical_slug=?,updated_at=? WHERE id=?",
                (item["slug"], timestamp, group["id"]),
            )
            db.execute(
                "INSERT INTO content_slug_aliases "
                "(entry_type,old_slug,content_group_id,created_at) VALUES (?,?,?,?)",
                (item["entry_type"], old_slug, group["id"], timestamp),
            )
        except sqlite3.IntegrityError as error:
            raise ContentValidationError("slug_conflict") from error
    db.execute(
        "UPDATE content_items SET status='published',published_at=?,"
        "lock_version=lock_version+1,updated_at=? WHERE id=? AND status='draft'",
        (timestamp, timestamp, content_id),
    )
    repository.write_audit_event(
        db,
        content_id,
        "content_published",
        actor,
        instant,
        {"archived_id": archived_id},
    )
    return PublishResult(content_id, archived_id)


def publish_content(
    content_id: int,
    expected_lock_version: int,
    *,
    actor: str,
    now=None,
) -> PublishResult:
    instant = _instant(now)
    return _write_transaction(
        lambda db: _publish_in_transaction(
            db, content_id, expected_lock_version, actor, instant
        )
    )


def archive_content(
    content_id: int,
    expected_lock_version: int,
    *,
    actor: str,
    now=None,
) -> None:
    instant = _instant(now)

    def operation(db):
        item = db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
        if item is None:
            raise ContentNotFoundError()
        if item["status"] != "published":
            raise ContentStateError("content_not_published")
        if item["lock_version"] != expected_lock_version:
            raise ContentConflictError("stale_lock_version")
        timestamp = format_shanghai(instant)
        db.execute(
            "UPDATE content_items SET status='archived',archived_at=?,"
            "lock_version=lock_version+1,updated_at=? WHERE id=?",
            (timestamp, timestamp, content_id),
        )
        repository.write_audit_event(db, content_id, "content_archived", actor, instant)

    _write_transaction(operation)


def _fail_due_item(db, item, actor, instant, reason_code):
    timestamp = format_shanghai(instant)
    db.execute(
        "UPDATE content_items SET publish_at=NULL,lock_version=lock_version+1,updated_at=? "
        "WHERE id=? AND status='draft'",
        (timestamp, item["id"]),
    )
    repository.write_audit_event(
        db,
        item["id"],
        "content_due_failed",
        actor,
        instant,
        {"reason_code": reason_code},
    )


def publish_due_content(*, actor="publish_due_content", now=None) -> PublishDueResult:
    instant = _instant(now)
    timestamp = format_shanghai(instant)
    snapshot = models.get_db()
    try:
        candidates = tuple(
            row["id"]
            for row in snapshot.execute(
                "SELECT id FROM content_items WHERE status='draft' AND publish_at IS NOT NULL "
                "AND publish_at<=? ORDER BY publish_at,id",
                (timestamp,),
            )
        )
    finally:
        snapshot.close()
    published = []
    failures = []
    for content_id in candidates:
        db = models.get_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            item = db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
            if item is None or item["status"] != "draft" or item["publish_at"] is None or item["publish_at"] > timestamp:
                db.rollback()
                continue
            db.execute("SAVEPOINT publish_due_attempt")
            try:
                _publish_in_transaction(
                    db, content_id, item["lock_version"], actor, instant
                )
            except ContentValidationError:
                db.execute("ROLLBACK TO publish_due_attempt")
                db.execute("RELEASE publish_due_attempt")
                _fail_due_item(db, item, actor, instant, "validation_failed")
                failures.append((content_id, "validation_failed"))
            except (ContentConflictError, ContentStateError):
                db.execute("ROLLBACK TO publish_due_attempt")
                db.execute("RELEASE publish_due_attempt")
                _fail_due_item(db, item, actor, instant, "state_changed")
                failures.append((content_id, "state_changed"))
            else:
                db.execute("RELEASE publish_due_attempt")
                published.append(content_id)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    return PublishDueResult(tuple(published), tuple(failures))


def get_public_revision(entry_type: str, slug: str, now):
    timestamp = format_shanghai(_instant(now))
    db = models.get_db()
    try:
        return db.execute(
            "SELECT * FROM content_items WHERE entry_type=? AND slug=? AND status='published' "
            "AND (publish_at IS NULL OR publish_at<=?)",
            (entry_type, slug, timestamp),
        ).fetchone()
    finally:
        db.close()


def resolve_public_revision(entry_type: str, slug: str, now):
    direct = get_public_revision(entry_type, slug, now)
    if direct is not None:
        return PublicRevisionResolution(direct, direct["slug"], False)
    timestamp = format_shanghai(_instant(now))
    db = models.get_db()
    try:
        row = db.execute(
            "SELECT ci.* FROM content_slug_aliases alias "
            "JOIN content_items ci ON ci.content_group_id=alias.content_group_id "
            "WHERE alias.entry_type=? AND alias.old_slug=? AND ci.status='published' "
            "AND (ci.publish_at IS NULL OR ci.publish_at<=?)",
            (entry_type, slug, timestamp),
        ).fetchone()
        if row is None:
            return None
        return PublicRevisionResolution(row, row["slug"], True)
    finally:
        db.close()


def _load_source_state(db, content_id):
    item = db.execute(
        "SELECT id,entry_type,status,lock_version FROM content_items WHERE id=?",
        (content_id,),
    ).fetchone()
    if item is None:
        raise ContentNotFoundError()
    if item["entry_type"] not in {"case", "resource"}:
        raise ContentValidationError("source_check_not_supported")
    table = repository.EXTENSION_TABLES[item["entry_type"]][0]
    source = db.execute(
        f"SELECT source_url,source_url_sha256 FROM {table} WHERE content_item_id=?",
        (content_id,),
    ).fetchone()
    if source is None or source["source_url"] is None or source["source_url_sha256"] is None:
        raise ContentValidationError("source_required")
    return item, table, source


def refresh_content_source_check(
    content_id: int,
    expected_lock_version: int,
    expected_url_sha256: str,
    *,
    actor: str,
    transport: PinnedHttpTransport,
    now,
):
    instant = _instant(now)
    read_db = models.get_db()
    try:
        item, _, source = _load_source_state(read_db, content_id)
        if item["status"] != "draft":
            raise ContentStateError("content_not_editable")
        if item["lock_version"] != expected_lock_version or source["source_url_sha256"] != expected_url_sha256:
            raise ContentConflictError("source_check_conflict")
        source_url = source["source_url"]
    finally:
        read_db.close()

    result = check_source_url(source_url, transport, instant)

    def operation(db):
        current, table, source = _load_source_state(db, content_id)
        if (
            current["status"] != "draft"
            or current["lock_version"] != expected_lock_version
            or source["source_url_sha256"] != expected_url_sha256
            or source["source_url"] != source_url
        ):
            raise ContentConflictError("source_check_conflict")
        db.execute(
            f"UPDATE {table} SET source_check_code=?,source_checked_at=?,"
            "source_check_expires_at=?,source_check_url_sha256=? WHERE content_item_id=?",
            (
                result.code,
                result.checked_at,
                result.expires_at,
                result.source_check_url_sha256,
                content_id,
            ),
        )
        db.execute(
            "UPDATE content_items SET lock_version=lock_version+1,updated_at=? WHERE id=?",
            (format_shanghai(instant), content_id),
        )
        repository.write_audit_event(
            db,
            content_id,
            "content_source_checked",
            actor,
            instant,
            {"result_code": result.code},
        )
        return result

    return _write_transaction(operation)
