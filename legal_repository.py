"""Immutable legal-document storage and publication contracts."""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from content_clock import as_shanghai, format_shanghai, parse_shanghai
from ingestion_repository import write_governance_audit_event
from models import get_db
from pagination import Page, PageRequest
from security import sanitize_html
from source_url_checker import normalize_source_url


DOCUMENT_TYPES = frozenset(
    {"privacy", "terms", "roi_disclaimer", "ai_content_notice"}
)
VERSION_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class LegalContractError(ValueError):
    """Raised when a legal-document contract is invalid."""


def _validated_code(value: str, *, field_name: str) -> str:
    if type(value) is not str or VERSION_CODE_PATTERN.fullmatch(value) is None:
        raise LegalContractError(f"{field_name}_invalid")
    return value


def _normalized_text(value, *, field_name: str, maximum: int) -> str:
    if type(value) is not str:
        raise LegalContractError(f"{field_name}_invalid")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(unicodedata.category(char).startswith("C") for char in normalized)
    ):
        raise LegalContractError(f"{field_name}_invalid")
    return normalized


def _normalized_body(value) -> str:
    if type(value) is not str or len(value) > 200_000:
        raise LegalContractError("body_html_invalid")
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n")
    if (
        len(normalized) > 200_000
        or any(
            char not in {"\n", "\t"}
            and unicodedata.category(char).startswith("C")
            for char in normalized
        )
    ):
        raise LegalContractError("body_html_invalid")
    cleaned = str(sanitize_html(normalized)).strip()
    browser_equivalent = html.unescape(cleaned)
    if (
        not cleaned
        or len(cleaned) > 200_000
        or any(
            char not in {"\n", "\t"}
            and unicodedata.category(char).startswith("C")
            for char in cleaned
        )
        or any(
            char not in {"\n", "\t"}
            and unicodedata.category(char).startswith("C")
            for char in browser_equivalent
        )
    ):
        raise LegalContractError("body_html_invalid")
    return cleaned


def normalize_external_legal_url(value: str) -> str:
    """Return one frozen, redirect-safe HTTPS URL."""
    if type(value) is not str or value != value.strip() or len(value) > 2048:
        raise LegalContractError("external_url_invalid")
    normalized, error = normalize_source_url(value)
    if error or normalized is None or urlsplit(normalized).scheme != "https":
        raise LegalContractError("external_url_invalid")
    return normalized


def validate_external_privacy_configuration(
    version_code: str, external_url: str
) -> tuple[str, str, str]:
    """Validate configuration before startup performs any database write."""
    version = _validated_code(version_code, field_name="version_code")
    normalized_url = normalize_external_legal_url(external_url)
    digest = canonical_legal_digest(
        document_type="privacy",
        version_code=version,
        mode="external_legacy",
        title=None,
        body_summary=None,
        body_html=None,
        external_url=normalized_url,
    )
    return version, normalized_url, digest


def _moment(value: datetime) -> tuple[datetime, str]:
    try:
        normalized = as_shanghai(value)
    except (TypeError, ValueError) as error:
        raise LegalContractError("now_invalid") from error
    return normalized, format_shanghai(normalized)


def _effective(value: datetime) -> str:
    try:
        return format_shanghai(value)
    except (TypeError, ValueError) as error:
        raise LegalContractError("effective_at_invalid") from error


@dataclass(frozen=True)
class LegalFilters:
    document_type: str | None = None
    status: str | None = None

    def __post_init__(self):
        if self.document_type is not None and self.document_type not in DOCUMENT_TYPES:
            raise LegalContractError("document_type_invalid")
        if self.status is not None and self.status not in {"draft", "published", "archived"}:
            raise LegalContractError("status_invalid")


@dataclass(frozen=True)
class LegalVersionRow:
    id: int
    document_type: str
    version_code: str
    mode: str
    title: str | None
    body_summary: str | None
    body_html: str | None
    external_url: str | None
    content_sha256: str
    reviewed_content_sha256: str | None
    status: str
    lock_version: int
    legal_review_confirmed_at: str | None
    effective_at: str
    published_at: str | None
    archived_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LegalVersionIds:
    privacy: int
    terms: int
    roi_disclaimer: int
    ai_content_notice: int


@dataclass(frozen=True)
class LegalBundle:
    privacy: LegalVersionRow
    terms: LegalVersionRow
    roi_disclaimer: LegalVersionRow
    ai_content_notice: LegalVersionRow

    @property
    def version_ids(self) -> LegalVersionIds:
        return LegalVersionIds(
            privacy=self.privacy.id,
            terms=self.terms.id,
            roi_disclaimer=self.roi_disclaimer.id,
            ai_content_notice=self.ai_content_notice.id,
        )


_ROW_COLUMNS = (
    "id,document_type,version_code,mode,title,body_summary,body_html,external_url,"
    "content_sha256,reviewed_content_sha256,status,lock_version,"
    "legal_review_confirmed_at,effective_at,published_at,archived_at,created_at,updated_at"
)


def _qualified_row_columns(alias: str) -> str:
    return ",".join(
        f"{alias}.{name} AS {name}" for name in LegalVersionRow.__dataclass_fields__
    )


def _as_version(row) -> LegalVersionRow:
    return LegalVersionRow(**{name: row[name] for name in LegalVersionRow.__dataclass_fields__})


def parse_legal_filters(values) -> LegalFilters:
    try:
        document_type = values.get("type", "")
        status = values.get("status", "")
    except (AttributeError, TypeError):
        document_type = status = ""
    return LegalFilters(
        document_type=document_type if document_type in DOCUMENT_TYPES else None,
        status=status if status in {"draft", "published", "archived"} else None,
    )


def canonical_legal_digest(
    *,
    document_type: str,
    version_code: str,
    mode: str,
    title: str | None,
    body_summary: str | None,
    body_html: str | None,
    external_url: str | None,
) -> str:
    """Hash the exact normalized legal content using canonical UTF-8 JSON."""
    if document_type not in DOCUMENT_TYPES:
        raise LegalContractError("document_type_invalid")
    _validated_code(version_code, field_name="version_code")
    if mode not in {"internal", "external_legacy"}:
        raise LegalContractError("mode_invalid")
    if mode == "internal":
        if (
            type(title) is not str or not title.strip()
            or type(body_summary) is not str or not body_summary.strip()
            or type(body_html) is not str or not body_html.strip()
            or external_url is not None
        ):
            raise LegalContractError("internal_content_invalid")
    elif (
        document_type != "privacy"
        or title is not None
        or body_summary is not None
        or body_html is not None
        or type(external_url) is not str
        or not external_url
    ):
        raise LegalContractError("external_content_invalid")
    payload = {
        "body_html": body_html,
        "body_summary": body_summary,
        "external_url": external_url,
        "mode": mode,
        "title": title,
        "type": document_type,
        "version": version_code,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stored_value(row, field_name: str):
    if isinstance(row, LegalVersionRow):
        return getattr(row, field_name)
    return row[field_name]


def _validated_stored_content(row) -> str:
    """Validate exact canonical storage and return its verified digest."""
    try:
        document_type = _stored_value(row, "document_type")
        version_code = _stored_value(row, "version_code")
        mode = _stored_value(row, "mode")
        title = _stored_value(row, "title")
        summary = _stored_value(row, "body_summary")
        body = _stored_value(row, "body_html")
        external_url = _stored_value(row, "external_url")
        if mode == "internal":
            if (
                _normalized_text(title, field_name="title", maximum=200) != title
                or _normalized_text(
                    summary, field_name="body_summary", maximum=1000
                )
                != summary
                or _normalized_body(body) != body
                or external_url is not None
            ):
                raise LegalContractError("stored_content_invalid")
        elif mode == "external_legacy":
            if (
                document_type != "privacy"
                or title is not None
                or summary is not None
                or body is not None
                or normalize_external_legal_url(external_url) != external_url
            ):
                raise LegalContractError("stored_content_invalid")
        else:
            raise LegalContractError("stored_content_invalid")
        digest = canonical_legal_digest(
            document_type=document_type,
            version_code=version_code,
            mode=mode,
            title=title,
            body_summary=summary,
            body_html=body,
            external_url=external_url,
        )
        if digest != _stored_value(row, "content_sha256"):
            raise LegalContractError("stored_content_invalid")
        return digest
    except (LegalContractError, KeyError, TypeError, IndexError, AttributeError):
        raise LegalContractError("stored_content_invalid") from None


def create_legal_draft(
    *,
    document_type: str,
    version_code: str,
    title: str,
    body_summary: str,
    body_html: str,
    effective_at: datetime,
    actor: str,
    now: datetime,
) -> int:
    if document_type not in DOCUMENT_TYPES:
        raise LegalContractError("document_type_invalid")
    version_code = _validated_code(version_code, field_name="version_code")
    title = _normalized_text(title, field_name="title", maximum=200)
    summary = _normalized_text(body_summary, field_name="body_summary", maximum=1000)
    body = _normalized_body(body_html)
    effective_text = _effective(effective_at)
    _, now_text = _moment(now)
    digest = canonical_legal_digest(
        document_type=document_type,
        version_code=version_code,
        mode="internal",
        title=title,
        body_summary=summary,
        body_html=body,
        external_url=None,
    )
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        version_id = db.execute(
            "INSERT INTO legal_documents "
            "(document_type,version_code,mode,title,body_summary,body_html,external_url,"
            "content_sha256,reviewed_content_sha256,status,lock_version,"
            "legal_review_confirmed_at,effective_at,published_at,archived_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,NULL,?,NULL,'draft',1,NULL,?,NULL,NULL,?,?)",
            (
                document_type,
                version_code,
                "internal",
                title,
                summary,
                body,
                digest,
                effective_text,
                now_text,
                now_text,
            ),
        ).lastrowid
        db.commit()
        return version_id
    except sqlite3.IntegrityError as error:
        db.rollback()
        raise LegalContractError("legal_version_conflict") from error
    finally:
        db.close()


def update_legal_draft(
    version_id: int,
    expected_lock_version: int,
    *,
    title: str,
    body_summary: str,
    body_html: str,
    effective_at: datetime,
    actor: str,
    now: datetime,
) -> int:
    if type(version_id) is not int or version_id <= 0:
        raise LegalContractError("version_id_invalid")
    if type(expected_lock_version) is not int or expected_lock_version <= 0:
        raise LegalContractError("lock_version_invalid")
    title = _normalized_text(title, field_name="title", maximum=200)
    summary = _normalized_text(body_summary, field_name="body_summary", maximum=1000)
    body = _normalized_body(body_html)
    effective_text = _effective(effective_at)
    _, now_text = _moment(now)
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT document_type,version_code,mode,status,lock_version FROM legal_documents WHERE id=?",
            (version_id,),
        ).fetchone()
        if row is None:
            raise LegalContractError("legal_version_not_found")
        if row["status"] != "draft" or row["mode"] != "internal":
            raise LegalContractError("legal_version_immutable")
        if row["lock_version"] != expected_lock_version:
            raise LegalContractError("legal_version_conflict")
        digest = canonical_legal_digest(
            document_type=row["document_type"],
            version_code=row["version_code"],
            mode="internal",
            title=title,
            body_summary=summary,
            body_html=body,
            external_url=None,
        )
        result = db.execute(
            "UPDATE legal_documents SET title=?,body_summary=?,body_html=?,"
            "content_sha256=?,reviewed_content_sha256=NULL,legal_review_confirmed_at=NULL,"
            "effective_at=?,updated_at=?,lock_version=lock_version+1 "
            "WHERE id=? AND status='draft' AND lock_version=?",
            (
                title,
                summary,
                body,
                digest,
                effective_text,
                now_text,
                version_id,
                expected_lock_version,
            ),
        )
        if result.rowcount != 1:
            raise LegalContractError("legal_version_conflict")
        db.commit()
        return expected_lock_version + 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def confirm_legal_review(
    version_id: int,
    expected_lock_version: int,
    actor: str,
    now: datetime,
) -> int:
    if type(version_id) is not int or version_id <= 0:
        raise LegalContractError("version_id_invalid")
    if type(expected_lock_version) is not int or expected_lock_version <= 0:
        raise LegalContractError("lock_version_invalid")
    _, now_text = _moment(now)
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            f"SELECT {_ROW_COLUMNS} FROM legal_documents WHERE id=?", (version_id,)
        ).fetchone()
        if row is None:
            raise LegalContractError("legal_version_not_found")
        if row["mode"] != "internal" or row["status"] != "draft":
            raise LegalContractError("legal_review_invalid")
        if row["lock_version"] != expected_lock_version:
            raise LegalContractError("legal_version_conflict")
        digest = _validated_stored_content(row)
        result = db.execute(
            "UPDATE legal_documents SET content_sha256=?,reviewed_content_sha256=?,"
            "legal_review_confirmed_at=?,updated_at=?,lock_version=lock_version+1 "
            "WHERE id=? AND status='draft' AND lock_version=?",
            (digest, digest, now_text, now_text, version_id, expected_lock_version),
        )
        if result.rowcount != 1:
            raise LegalContractError("legal_version_conflict")
        write_governance_audit_event(
            db,
            action="legal_review_confirmed",
            target_type="legal_document",
            target_id=version_id,
            actor=actor,
            metadata={"document_type": row["document_type"]},
            now=now,
        )
        db.commit()
        return expected_lock_version + 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def publish_legal_version(
    version_id: int,
    expected_lock_version: int,
    actor: str,
    now: datetime,
) -> None:
    if type(version_id) is not int or version_id <= 0:
        raise LegalContractError("version_id_invalid")
    if type(expected_lock_version) is not int or expected_lock_version <= 0:
        raise LegalContractError("lock_version_invalid")
    now_value, now_text = _moment(now)
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            f"SELECT {_ROW_COLUMNS} FROM legal_documents WHERE id=?", (version_id,)
        ).fetchone()
        if row is None:
            raise LegalContractError("legal_version_not_found")
        if row["status"] != "draft" or row["mode"] != "internal":
            raise LegalContractError("legal_publish_invalid")
        if row["lock_version"] != expected_lock_version:
            raise LegalContractError("legal_version_conflict")
        digest = _validated_stored_content(row)
        if (
            row["reviewed_content_sha256"] != digest
            or row["legal_review_confirmed_at"] is None
        ):
            raise LegalContractError("review_required")
        if parse_shanghai(row["effective_at"]) > now_value:
            raise LegalContractError("effective_at_future")
        old_pointer = db.execute(
            "SELECT legal_document_id FROM active_legal_documents WHERE document_type=?",
            (row["document_type"],),
        ).fetchone()
        result = db.execute(
            "UPDATE legal_documents SET status='published',published_at=?,updated_at=?,"
            "lock_version=lock_version+1 WHERE id=? AND status='draft' AND lock_version=?",
            (now_text, now_text, version_id, expected_lock_version),
        )
        if result.rowcount != 1:
            raise LegalContractError("legal_version_conflict")
        if old_pointer is None:
            db.execute(
                "INSERT INTO active_legal_documents(document_type,legal_document_id) VALUES (?,?)",
                (row["document_type"], version_id),
            )
        else:
            db.execute(
                "UPDATE active_legal_documents SET legal_document_id=? WHERE document_type=?",
                (version_id, row["document_type"]),
            )
            old_id = old_pointer["legal_document_id"]
            if old_id != version_id:
                db.execute(
                    "UPDATE legal_documents SET status='archived',archived_at=?,updated_at=?,"
                    "lock_version=lock_version+1 WHERE id=? AND status='published'",
                    (now_text, now_text, old_id),
                )
        write_governance_audit_event(
            db,
            action="legal_version_published",
            target_type="legal_document",
            target_id=version_id,
            actor=actor,
            metadata={"document_type": row["document_type"]},
            now=now,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reconcile_external_privacy_reference(
    db: sqlite3.Connection,
    version_code: str,
    external_url: str,
    now: datetime,
) -> int:
    """Atomically preserve configured legacy privacy policy and old consents."""
    if not isinstance(db, sqlite3.Connection):
        raise LegalContractError("connection_invalid")
    if db.in_transaction:
        raise LegalContractError("connection_transaction_active")
    version_code, normalized_url, digest = validate_external_privacy_configuration(
        version_code, external_url
    )
    _, now_text = _moment(now)
    changed = False
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            f"SELECT {_ROW_COLUMNS} FROM legal_documents "
            "WHERE document_type='privacy' AND version_code=?",
            (version_code,),
        ).fetchone()
        if existing is not None:
            if not (
                existing["mode"] == "external_legacy"
                and existing["external_url"] == normalized_url
                and existing["content_sha256"] == digest
                and existing["title"] is None
                and existing["body_summary"] is None
                and existing["body_html"] is None
                and existing["reviewed_content_sha256"] is None
                and existing["legal_review_confirmed_at"] is None
            ):
                raise LegalContractError("external_version_conflict")
            version_id = existing["id"]
        else:
            version_id = db.execute(
                "INSERT INTO legal_documents "
                "(document_type,version_code,mode,title,body_summary,body_html,external_url,"
                "content_sha256,reviewed_content_sha256,status,lock_version,"
                "legal_review_confirmed_at,effective_at,published_at,archived_at,created_at,updated_at) "
                "VALUES ('privacy',?,'external_legacy',NULL,NULL,NULL,?, ?,NULL,'published',1,"
                "NULL,?,?,NULL,?,?)",
                (version_code, normalized_url, digest, now_text, now_text, now_text, now_text),
            ).lastrowid
            changed = True

        active = db.execute(
            "SELECT d.id,d.mode,d.reviewed_content_sha256,d.content_sha256 "
            "FROM active_legal_documents a JOIN legal_documents d ON d.id=a.legal_document_id "
            "WHERE a.document_type='privacy'"
        ).fetchone()
        internal_active = bool(
            active is not None
            and active["mode"] == "internal"
            and active["reviewed_content_sha256"] == active["content_sha256"]
        )
        if not internal_active:
            if active is None:
                db.execute(
                    "INSERT INTO active_legal_documents(document_type,legal_document_id) "
                    "VALUES ('privacy',?)",
                    (version_id,),
                )
                changed = True
            elif active["id"] != version_id:
                db.execute(
                    "UPDATE active_legal_documents SET legal_document_id=? "
                    "WHERE document_type='privacy'",
                    (version_id,),
                )
                db.execute(
                    "UPDATE legal_documents SET status='archived',archived_at=?,updated_at=?,"
                    "lock_version=lock_version+1 WHERE id=? AND status='published'",
                    (now_text, now_text, active["id"]),
                )
                changed = True
        elif existing is None:
            db.execute(
                "UPDATE legal_documents SET status='archived',archived_at=?,updated_at=?,"
                "lock_version=lock_version+1 WHERE id=? AND status='published'",
                (now_text, now_text, version_id),
            )

        linked = db.execute(
            "UPDATE lead_consents SET legal_version_id=? "
            "WHERE legal_version_id IS NULL AND policy_version=?",
            (version_id, version_code),
        ).rowcount
        changed = changed or linked > 0
        if changed:
            write_governance_audit_event(
                db,
                action="external_legal_reconciled",
                target_type="legal_document",
                target_id=version_id,
                actor="system",
                metadata={"linked_count": linked},
                now=now,
            )
        db.commit()
        return version_id
    except Exception:
        db.rollback()
        raise


def query_legal_versions(filters: LegalFilters, page: PageRequest) -> Page[LegalVersionRow]:
    if not isinstance(filters, LegalFilters) or not isinstance(page, PageRequest):
        raise LegalContractError("legal_query_invalid")
    clauses = []
    parameters: list[object] = []
    if filters.document_type is not None:
        clauses.append("document_type=?")
        parameters.append(filters.document_type)
    if filters.status is not None:
        clauses.append("status=?")
        parameters.append(filters.status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    db = get_db()
    try:
        total = db.execute(
            "SELECT COUNT(*) FROM legal_documents" + where, parameters
        ).fetchone()[0]
        if total == 0:
            return Page((), 1, page.per_page, 0, 0)
        total_pages = (total + page.per_page - 1) // page.per_page
        page_number = min(page.page, total_pages)
        rows = tuple(
            _as_version(row)
            for row in db.execute(
                f"SELECT {_ROW_COLUMNS} FROM legal_documents"
                + where
                + " ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
                (*parameters, page.per_page, (page_number - 1) * page.per_page),
            ).fetchall()
        )
        return Page(rows, page_number, page.per_page, total, total_pages)
    finally:
        db.close()


def load_legal_version(version_id: int) -> LegalVersionRow | None:
    if type(version_id) is not int or version_id <= 0:
        return None
    db = get_db()
    try:
        row = db.execute(
            f"SELECT {_ROW_COLUMNS} FROM legal_documents WHERE id=?", (version_id,)
        ).fetchone()
        return _as_version(row) if row is not None else None
    finally:
        db.close()


def load_public_legal_version(
    document_type: str, version_code: str | None = None
) -> LegalVersionRow | None:
    if document_type not in DOCUMENT_TYPES:
        return None
    if version_code is not None and VERSION_CODE_PATTERN.fullmatch(version_code) is None:
        return None
    db = get_db()
    try:
        if version_code is None:
            row = db.execute(
                f"SELECT {_qualified_row_columns('d')} FROM active_legal_documents a "
                "JOIN legal_documents d ON d.id=a.legal_document_id "
                "WHERE a.document_type=? AND d.status='published'",
                (document_type,),
            ).fetchone()
        else:
            row = db.execute(
                f"SELECT {_ROW_COLUMNS} FROM legal_documents "
                "WHERE document_type=? AND version_code=? AND status IN ('published','archived')",
                (document_type, version_code),
            ).fetchone()
        if row is None:
            return None
        try:
            digest = _validated_stored_content(row)
        except LegalContractError:
            return None
        if row["mode"] == "internal" and (
            row["reviewed_content_sha256"] != digest
            or row["legal_review_confirmed_at"] is None
        ):
            return None
        if row["mode"] == "external_legacy" and (
            row["reviewed_content_sha256"] is not None
            or row["legal_review_confirmed_at"] is not None
        ):
            return None
        return _as_version(row)
    finally:
        db.close()


def _validated_bundle_row(row, *, now: datetime, require_published: bool) -> LegalVersionRow:
    if row is None:
        raise LegalContractError("legal_bundle_not_ready")
    version = _as_version(row)
    try:
        digest = _validated_stored_content(version)
    except LegalContractError:
        raise LegalContractError("legal_bundle_not_ready") from None
    if (
        version.mode != "internal"
        or version.reviewed_content_sha256 != digest
        or version.legal_review_confirmed_at is None
        or version.status not in ({"published"} if require_published else {"published", "archived"})
    ):
        raise LegalContractError("legal_bundle_not_ready")
    if require_published and parse_shanghai(version.effective_at) > as_shanghai(now):
        raise LegalContractError("legal_bundle_not_ready")
    return version


def load_active_legal_bundle(db: sqlite3.Connection, now: datetime) -> LegalBundle:
    if not isinstance(db, sqlite3.Connection):
        raise LegalContractError("connection_invalid")
    rows = {
        row["document_type"]: row
        for row in db.execute(
            f"SELECT {_qualified_row_columns('d')} FROM active_legal_documents a "
            "JOIN legal_documents d ON d.id=a.legal_document_id"
        ).fetchall()
    }
    versions = {
        document_type: _validated_bundle_row(
            rows.get(document_type), now=now, require_published=True
        )
        for document_type in DOCUMENT_TYPES
    }
    return LegalBundle(**versions)


def load_legal_bundle(
    db: sqlite3.Connection, version_ids: LegalVersionIds
) -> LegalBundle:
    if not isinstance(db, sqlite3.Connection) or not isinstance(version_ids, LegalVersionIds):
        raise LegalContractError("legal_bundle_invalid")
    requested = {
        "privacy": version_ids.privacy,
        "terms": version_ids.terms,
        "roi_disclaimer": version_ids.roi_disclaimer,
        "ai_content_notice": version_ids.ai_content_notice,
    }
    versions = {}
    for document_type, version_id in requested.items():
        if type(version_id) is not int or version_id <= 0:
            raise LegalContractError("legal_bundle_invalid")
        row = db.execute(
            f"SELECT {_ROW_COLUMNS} FROM legal_documents WHERE id=? AND document_type=?",
            (version_id, document_type),
        ).fetchone()
        versions[document_type] = _validated_bundle_row(
            row, now=datetime.now().astimezone(), require_published=False
        )
    return LegalBundle(**versions)
