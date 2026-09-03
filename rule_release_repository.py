"""Transactional repository for relational assessment release drafts."""

from dataclasses import replace
import re
import sqlite3

from assessment.contracts import (
    RuleReleaseDraft,
    RuleReleaseFilters,
    RuleReleaseRow,
)
from models import get_db
from pagination import Page, PageRequest
from repository import DataConflictError
from rule_release_seed import (
    _delete_all_release_children,
    _insert_all_release_children,
    _load_release_draft_from_db,
    _timestamp,
)
from rule_release_validation import (
    RELEASE_CODE_PATTERN,
    normalize_public_text,
    normalize_release_draft,
    validate_release_draft,
)


ACTOR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,99}$")


def copy_active_release(code: str, name: str, actor: str, now) -> int:
    """Deep-copy the complete active immutable release into a new draft."""
    if type(code) is not str or RELEASE_CODE_PATTERN.fullmatch(code) is None:
        raise ValueError("invalid release code")
    if type(name) is not str or not name.strip() or len(name) > 200:
        raise ValueError("invalid release name")
    name = normalize_public_text(name)
    if type(actor) is not str or ACTOR_PATTERN.fullmatch(actor) is None:
        raise ValueError("invalid actor")
    timestamp = _timestamp(now)
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        source = db.execute(
            "SELECT v.id FROM active_assessment_version a "
            "JOIN assessment_versions v ON v.id=a.assessment_version_id "
            "JOIN assessment_version_snapshots s ON s.assessment_version_id=v.id "
            "WHERE a.singleton_id=1 AND v.status='published' "
            "AND v.validated_digest=s.sha256"
        ).fetchone()
        if source is None:
            raise DataConflictError("active rule release is unavailable")
        source_draft = _load_release_draft_from_db(db, source["id"])
        release_id = db.execute(
            "INSERT INTO assessment_versions "
            "(code,name,pain_min_selections,pain_max_selections,status,created_at,published_at,"
            "copied_from_id,lock_version,validated_digest,updated_at) "
            "VALUES (?,?,?,?,'draft',?,NULL,?,1,NULL,?)",
            (
                code, name, source_draft.pain_min_selections,
                source_draft.pain_max_selections, timestamp, source["id"], timestamp,
            ),
        ).lastrowid
        copy = replace(
            source_draft,
            id=release_id,
            code=code,
            name=name,
            status="draft",
            copied_from_id=source["id"],
            lock_version=1,
            created_at=timestamp,
            updated_at=timestamp,
            published_at=None,
        )
        errors = validate_release_draft(copy)
        if errors:
            raise DataConflictError("active rule release is invalid: " + ",".join(errors))
        _insert_all_release_children(db, release_id, copy)
        db.commit()
        return release_id
    except sqlite3.IntegrityError as error:
        db.rollback()
        raise DataConflictError("rule release copy conflict") from error
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def load_release_draft(release_id: int) -> RuleReleaseDraft:
    if type(release_id) is not int or release_id <= 0:
        raise ValueError("invalid release id")
    db = get_db()
    try:
        return _load_release_draft_from_db(db, release_id)
    finally:
        db.close()


def load_release_draft_from_db(
    db: sqlite3.Connection, release_id: int
) -> RuleReleaseDraft:
    """Load a draft through a caller-owned connection without transaction control."""
    if not isinstance(db, sqlite3.Connection):
        raise ValueError("invalid database connection")
    if type(release_id) is not int or release_id <= 0:
        raise ValueError("invalid release id")
    return _load_release_draft_from_db(db, release_id)


def save_release_draft(
    release_id: int,
    expected_lock_version: int,
    draft: RuleReleaseDraft,
    now,
) -> int:
    """Replace one draft atomically, returning its incremented lock version."""
    if type(release_id) is not int or release_id <= 0:
        raise ValueError("invalid release id")
    if type(expected_lock_version) is not int or expected_lock_version <= 0:
        raise ValueError("invalid lock version")
    if type(draft) is not RuleReleaseDraft or draft.id != release_id:
        raise ValueError("invalid release draft")
    errors = validate_release_draft(draft)
    if errors:
        raise ValueError("invalid rule release: " + ",".join(errors))
    draft = normalize_release_draft(draft)
    normalized_errors = validate_release_draft(draft)
    if normalized_errors:
        raise ValueError("invalid rule release: " + ",".join(normalized_errors))
    timestamp = _timestamp(now)
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT code,status,lock_version FROM assessment_versions WHERE id=?",
            (release_id,),
        ).fetchone()
        if (
            current is None
            or current["status"] != "draft"
            or current["lock_version"] != expected_lock_version
            or draft.lock_version != expected_lock_version
            or draft.code != current["code"]
        ):
            raise DataConflictError("rule release update conflict")
        _delete_all_release_children(db, release_id)
        _insert_all_release_children(db, release_id, draft)
        next_lock = expected_lock_version + 1
        updated = db.execute(
            "UPDATE assessment_versions SET name=?,pain_min_selections=?,pain_max_selections=?,"
            "lock_version=?,validated_digest=NULL,updated_at=? "
            "WHERE id=? AND status='draft' AND lock_version=?",
            (
                draft.name, draft.pain_min_selections, draft.pain_max_selections,
                next_lock, timestamp, release_id, expected_lock_version,
            ),
        ).rowcount
        if updated != 1:
            raise DataConflictError("rule release update conflict")
        db.commit()
        return next_lock
    except sqlite3.IntegrityError as error:
        db.rollback()
        raise DataConflictError("rule release child conflict") from error
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def query_rule_releases(
    filters: RuleReleaseFilters, page: PageRequest
) -> Page[RuleReleaseRow]:
    if not isinstance(filters, RuleReleaseFilters) or not isinstance(page, PageRequest):
        raise TypeError("invalid rule release query")
    if filters.status not in (None, "draft", "published", "archived"):
        raise ValueError("invalid release status")
    where = "" if filters.status is None else " WHERE status=?"
    parameters = () if filters.status is None else (filters.status,)
    db = get_db()
    try:
        total = db.execute(
            "SELECT COUNT(*) FROM assessment_versions" + where, parameters
        ).fetchone()[0]
        if total == 0:
            return Page((), 1, page.per_page, 0, 0)
        total_pages = (total + page.per_page - 1) // page.per_page
        page_number = min(page.page, total_pages)
        rows = tuple(
            RuleReleaseRow(
                id=row["id"], code=row["code"], name=row["name"],
                status=row["status"], lock_version=row["lock_version"],
                updated_at=row["updated_at"],
            )
            for row in db.execute(
                "SELECT id,code,name,status,lock_version,updated_at FROM assessment_versions"
                + where
                + " ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
                (*parameters, page.per_page, (page_number - 1) * page.per_page),
            )
        )
        return Page(rows, page_number, page.per_page, total, total_pages)
    finally:
        db.close()
