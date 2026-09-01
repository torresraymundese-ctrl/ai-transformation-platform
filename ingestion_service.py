"""Reviewed ingestion orchestration and atomic candidate decisions."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
import sqlite3
from urllib.parse import urlsplit

import models
import publishing_repository
from content_clock import format_shanghai, shanghai_now
from content_contracts import ContentBlock, ContentDraft
from ingestion_contracts import FetchedItem, IngestResult
from ingestion_repository import (
    canonicalize_url,
    record_fetch_attempt,
    store_candidates,
    write_governance_audit_event,
)
from ingestion_sources import (
    SourceRegistryError,
    fetch_reviewed_source,
    load_source_registry,
    source_policy,
)
from security import sanitize_html
from source_url_checker import PinnedHttpTransport


REJECTION_CODES = frozenset(
    {
        "duplicate",
        "irrelevant",
        "outdated",
        "licensing_restricted",
        "unsafe_content",
        "insufficient_evidence",
    }
)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_NOTE = re.compile(r"[a-z0-9][a-z0-9_-]{0,199}\Z")


class IngestionDecisionError(RuntimeError):
    """A candidate decision is invalid or has lost an optimistic race."""


@dataclass(frozen=True)
class AcceptDecision:
    slug: str

    def __post_init__(self):
        if type(self.slug) is not str or _SLUG.fullmatch(self.slug) is None or len(self.slug) > 120:
            raise IngestionDecisionError("decision_invalid")


@dataclass(frozen=True)
class IngestionRunResult:
    created_ids: tuple[int, ...]
    deduplicated: int
    attempted_sources: int
    failed_sources: int


def list_candidates(limit=200):
    """Return a bounded newest-first private queue projection."""
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("candidate_limit_invalid")
    db = models.get_db()
    try:
        return tuple(
            db.execute(
                "SELECT id,source_code,source_name,title,licensed_summary,state,"
                "lock_version,created_at FROM ingestion_candidates "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        )
    finally:
        db.close()


def _candidate_row(db, candidate_id, expected_lock_version):
    if (
        type(candidate_id) is not int
        or candidate_id <= 0
        or type(expected_lock_version) is not int
        or expected_lock_version <= 0
    ):
        raise IngestionDecisionError("candidate_conflict")
    row = db.execute(
        "SELECT * FROM ingestion_candidates WHERE id=? AND state='pending_review' "
        "AND lock_version=?",
        (candidate_id, expected_lock_version),
    ).fetchone()
    if row is None:
        raise IngestionDecisionError("candidate_conflict")
    return row


def _draft_for_candidate(candidate, decision, policy):
    published_at = candidate["original_published_at"] or candidate["created_at"]
    source_url = canonicalize_url(candidate["canonical_url"])
    parsed_source = urlsplit(source_url)
    if parsed_source.scheme != policy.scheme or parsed_source.hostname not in policy.hosts:
        raise IngestionDecisionError("candidate_source_invalid")
    body = (
        candidate["body_html"]
        if policy.retain_body and candidate["body_html"]
        else f"<p>{candidate['licensed_summary']}</p>"
    )
    source_hash = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    return ContentDraft(
        entry_type="resource",
        slug=decision.slug,
        title=candidate["title"],
        summary=candidate["licensed_summary"],
        seo_title=candidate["title"][:60],
        seo_description=candidate["licensed_summary"][:160],
        extension={
            "resource_type": "article",
            "is_original": 0,
            "source_name": policy.name,
            "source_url": source_url,
            "source_url_sha256": source_hash,
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "original_published_at": published_at,
            "copyright_notice": f"licensed_source_{policy.license_basis_reference}",
            "attachment_media_id": None,
        },
        blocks=(
            ContentBlock(
                "rich_text",
                "正文",
                str(sanitize_html(body)),
                {},
                None,
                0,
            ),
        ),
    )


def accept_candidate(
    candidate_id: int,
    decision: AcceptDecision,
    expected_lock_version: int,
    actor: str,
    now: datetime,
) -> int:
    """Atomically convert one pending candidate into an ordinary private draft."""
    if type(decision) is not AcceptDecision:
        raise IngestionDecisionError("decision_invalid")
    db = models.get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        candidate = _candidate_row(db, candidate_id, expected_lock_version)
        policy = source_policy(candidate["source_code"])
        if policy.robots_policy != "allow":
            raise IngestionDecisionError("candidate_source_invalid")
        draft = _draft_for_candidate(candidate, decision, policy)
        content_id = publishing_repository.insert_content_draft(
            db,
            draft,
            actor=actor,
            now=now,
            allow_private_http_source=True,
        )
        cursor = db.execute(
            "UPDATE ingestion_candidates SET state='accepted',target_content_id=?,"
            "lock_version=lock_version+1,updated_at=? WHERE id=? AND state='pending_review' "
            "AND lock_version=?",
            (
                content_id,
                format_shanghai(now),
                candidate_id,
                expected_lock_version,
            ),
        )
        if cursor.rowcount != 1:
            raise IngestionDecisionError("candidate_conflict")
        write_governance_audit_event(
            db,
            action="ingestion_accepted",
            target_type="ingestion_candidate",
            target_id=candidate_id,
            actor=actor,
            metadata={"target_content_id": content_id},
            now=now,
        )
        db.commit()
        return content_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reject_candidate(
    candidate_id: int,
    reason_code: str,
    note: str,
    expected_lock_version: int,
    actor: str,
    now: datetime,
) -> None:
    """Atomically reject one pending candidate using bounded fixed codes."""
    if reason_code not in REJECTION_CODES or type(note) is not str or _NOTE.fullmatch(note) is None:
        raise IngestionDecisionError("decision_invalid")
    db = models.get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        _candidate_row(db, candidate_id, expected_lock_version)
        cursor = db.execute(
            "UPDATE ingestion_candidates SET state='rejected',rejection_code=?,"
            "rejection_note=?,lock_version=lock_version+1,updated_at=? "
            "WHERE id=? AND state='pending_review' AND lock_version=?",
            (
                reason_code,
                note,
                format_shanghai(now),
                candidate_id,
                expected_lock_version,
            ),
        )
        if cursor.rowcount != 1:
            raise IngestionDecisionError("candidate_conflict")
        write_governance_audit_event(
            db,
            action="ingestion_rejected",
            target_type="ingestion_candidate",
            target_id=candidate_id,
            actor=actor,
            metadata={"reason_code": reason_code},
            now=now,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_enabled_sources(
    *,
    registry_path=None,
    transport=None,
    adapters=None,
    now: datetime | None = None,
) -> IngestionRunResult:
    """Fetch all and only enabled reviewed sources; never publish."""
    instant = now or shanghai_now()
    policies = load_source_registry(registry_path)
    enabled = tuple(policy for policy in policies if policy.enabled)
    if not enabled:
        return IngestionRunResult((), 0, 0, 0)
    pinned = transport or PinnedHttpTransport(connect_timeout=3.0, read_timeout=5.0)
    items: list[FetchedItem] = []
    failed = 0
    for policy in enabled:
        started = instant
        fetched = ()
        error_code = None
        try:
            fetched = fetch_reviewed_source(
                policy, transport=pinned, adapters=adapters, now=instant
            )
            items.extend(fetched)
        except SourceRegistryError:
            failed += 1
            error_code = "source_fetch_failed"
        db = models.get_db()
        try:
            record_fetch_attempt(
                db,
                source_code=policy.code,
                source_name=policy.name,
                outcome_code="failed" if error_code else "succeeded",
                error_code=error_code,
                fetched_count=len(fetched),
                started_at=started,
                completed_at=instant,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    stored: IngestResult = store_candidates(tuple(items), instant)
    if stored.created_ids:
        db = models.get_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            for candidate_id in stored.created_ids:
                cursor = db.execute(
                    "UPDATE ingestion_candidates SET state='pending_review',"
                    "lock_version=lock_version+1,updated_at=? "
                    "WHERE id=? AND state='fetched' AND lock_version=1",
                    (format_shanghai(instant), candidate_id),
                )
                if cursor.rowcount != 1:
                    raise IngestionDecisionError("candidate_conflict")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    return IngestionRunResult(
        stored.created_ids,
        stored.deduplicated,
        len(enabled),
        failed,
    )
