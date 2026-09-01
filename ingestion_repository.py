"""SQLite ingestion queue operations with explicit connection ownership."""

import hashlib
import json
import posixpath
import re
import sqlite3
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import idna
from bs4 import BeautifulSoup

from content_clock import format_shanghai, parse_shanghai
from ingestion_contracts import (
    FetchedItem,
    IngestResult,
    IngestionCandidate,
    IngestionContractError,
    require_source_code,
)
from models import get_db
from security import sanitize_html


_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_URL_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_TRACKING_QUERY_NAMES = frozenset(
    {"dclid", "fbclid", "gclid", "mc_cid", "mc_eid", "msclkid"}
)
_CODE_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_AUDIT_ACTOR_PATTERN = re.compile(r"[A-Za-z0-9_.-]{3,64}\Z")
_AUDIT_INTEGER_MAX = 2_147_483_647
_SENSITIVE_ACTOR_FILE_EXTENSIONS = frozenset(
    {
        "7z",
        "bat",
        "cmd",
        "csv",
        "db",
        "doc",
        "docx",
        "exe",
        "gif",
        "gz",
        "htm",
        "html",
        "jpeg",
        "jpg",
        "js",
        "json",
        "log",
        "pdf",
        "png",
        "ps1",
        "py",
        "sh",
        "sql",
        "sqlite",
        "svg",
        "tar",
        "txt",
        "xls",
        "xlsx",
        "xml",
        "zip",
    }
)
_FORBIDDEN_AUDIT_KEY_PARTS = (
    "body",
    "url",
    "filename",
    "file_name",
    "contact",
    "email",
    "phone",
    "mobile",
    "wechat",
    "search",
    "query",
)


class IngestionConflictError(RuntimeError):
    def __init__(self, code="candidate_conflict"):
        self.code = code
        super().__init__(code)


def _normalize_path_percent_encoding(value: str) -> str:
    normalized = []
    index = 0
    while index < len(value):
        if value[index] != "%":
            normalized.append(value[index])
            index += 1
            continue
        octet = int(value[index + 1 : index + 3], 16)
        decoded = chr(octet)
        normalized.append(decoded if decoded in _URL_UNRESERVED else f"%{octet:02X}")
        index += 3
    return "".join(normalized)


def canonicalize_url(value: str) -> str:
    """Return a stable HTTP(S) URL without userinfo, fragments or trackers."""
    if type(value) is not str or not value or value != value.strip():
        raise IngestionContractError("url_invalid")
    if (
        "\\" in value
        or _INVALID_PERCENT_ESCAPE.search(value)
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise IngestionContractError("url_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise IngestionContractError("url_invalid") from error
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise IngestionContractError("url_invalid")
    if parsed.username is not None or parsed.password is not None:
        raise IngestionContractError("url_userinfo_not_allowed")
    try:
        host = idna.encode(
            parsed.hostname.rstrip("."), uts46=True, std3_rules=True
        ).decode("ascii").lower()
    except (idna.IDNAError, UnicodeError) as error:
        raise IngestionContractError("url_invalid") from error
    default_port = 443 if scheme == "https" else 80
    if port not in (None, default_port):
        raise IngestionContractError("url_port_not_allowed")

    raw_path = _normalize_path_percent_encoding(parsed.path or "/")
    trailing_slash = raw_path.endswith("/")
    normalized_path = posixpath.normpath("/" + raw_path.lstrip("/"))
    while "//" in normalized_path:
        normalized_path = normalized_path.replace("//", "/")
    if trailing_slash and normalized_path != "/":
        normalized_path += "/"
    path = quote(normalized_path, safe="/%:@-._~!$&'()*+,;=")

    query_items = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in _TRACKING_QUERY_NAMES
    ]
    query = urlencode(sorted(query_items), doseq=True)
    canonical_url = urlunsplit((scheme, host, path, query, ""))
    if len(canonical_url) > 2048:
        raise IngestionContractError("url_invalid")
    return canonical_url


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _normalized_item(item: FetchedItem):
    if type(item) is not FetchedItem:
        raise IngestionContractError("fetched_item_invalid")
    source_code = require_source_code(item.source_code)
    source_name = _normalized_text(item.source_name)
    title = _normalized_text(item.title)
    summary = _normalized_text(item.summary)
    if not source_name or len(source_name) > 200:
        raise IngestionContractError("source_name_invalid")
    if not title or len(title) > 300:
        raise IngestionContractError("title_invalid")
    if len(summary) > 2000:
        raise IngestionContractError("summary_invalid")
    if type(item.body_html) is not str:
        raise IngestionContractError("fetched_item_invalid")
    body_html = _normalized_text(str(sanitize_html(item.body_html or ""))) or None
    if body_html is not None and len(body_html.encode("utf-8")) > 262144:
        raise IngestionContractError("body_html_invalid")
    return (
        source_code,
        source_name,
        canonicalize_url(item.url),
        title,
        summary,
        body_html,
    )


def normalized_content_sha256(item: FetchedItem) -> str:
    """Hash normalized licensed content independently from its source URL."""
    _, _, _, title, summary, body_html = _normalized_item(item)
    return _content_sha256(title, summary, body_html)


def _content_sha256(title: str, summary: str, body_html: str | None) -> str:
    body_text = _normalized_text(
        BeautifulSoup(body_html or "", "html.parser").get_text(" ", strip=True)
    )
    payload = {"body_text": body_text, "summary": summary, "title": title}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prepare_candidate(item: FetchedItem):
    source_code, source_name, canonical_url, title, summary, body_html = (
        _normalized_item(item)
    )
    content_sha256 = _content_sha256(title, summary, body_html)
    original_published_at = (
        format_shanghai(item.original_published_at)
        if item.original_published_at is not None
        else None
    )
    return (
        source_code,
        source_name,
        canonical_url,
        content_sha256,
        title,
        summary,
        body_html,
        original_published_at,
    )


def store_candidates(
    items: tuple[FetchedItem, ...], now: datetime
) -> IngestResult:
    """Validate and atomically store unique candidates on an owned connection."""
    if type(items) is not tuple:
        raise IngestionContractError("fetched_items_invalid")
    timestamp = format_shanghai(now)
    prepared = tuple(_prepare_candidate(item) for item in items)
    db = get_db()
    created_ids = []
    deduplicated = 0
    try:
        for candidate in prepared:
            (
                source_code,
                source_name,
                canonical_url,
                content_sha256,
                title,
                summary,
                body_html,
                original_published_at,
            ) = candidate
            try:
                cursor = db.execute(
                    "INSERT INTO ingestion_candidates "
                    "(source_code,source_name,canonical_url,content_sha256,title,"
                    "licensed_summary,body_html,original_published_at,state,lock_version,"
                    "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,'fetched',1,?,?)",
                    (
                        source_code,
                        source_name,
                        canonical_url,
                        content_sha256,
                        title,
                        summary,
                        body_html,
                        original_published_at,
                        timestamp,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError:
                duplicate = db.execute(
                    "SELECT 1 FROM ingestion_candidates "
                    "WHERE canonical_url=? OR content_sha256=? LIMIT 1",
                    (canonical_url, content_sha256),
                ).fetchone()
                if duplicate is None:
                    raise
                deduplicated += 1
            else:
                created_ids.append(cursor.lastrowid)
        db.commit()
        return IngestResult(tuple(created_ids), deduplicated)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _candidate_from_row(row) -> IngestionCandidate:
    return IngestionCandidate(
        id=row["id"],
        source_code=row["source_code"],
        source_name=row["source_name"],
        canonical_url=row["canonical_url"],
        content_sha256=row["content_sha256"],
        title=row["title"],
        licensed_summary=row["licensed_summary"],
        body_html=row["body_html"],
        original_published_at=(
            parse_shanghai(row["original_published_at"])
            if row["original_published_at"] is not None
            else None
        ),
        state=row["state"],
        rejection_code=row["rejection_code"],
        rejection_note=row["rejection_note"],
        lock_version=row["lock_version"],
        target_content_id=row["target_content_id"],
        created_at=parse_shanghai(row["created_at"]),
        updated_at=parse_shanghai(row["updated_at"]),
    )


def load_candidate(candidate_id: int) -> IngestionCandidate | None:
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM ingestion_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        return _candidate_from_row(row) if row is not None else None
    finally:
        db.close()


def record_fetch_attempt(
    db: sqlite3.Connection,
    *,
    source_code: str,
    source_name: str,
    outcome_code: str,
    error_code: str | None,
    fetched_count: int,
    started_at,
    completed_at,
) -> int:
    """Record generic fetch outcome metadata without committing the caller."""
    require_source_code(source_code)
    normalized_source_name = _normalized_text(source_name)
    if not normalized_source_name or len(normalized_source_name) > 200:
        raise IngestionContractError("source_name_invalid")
    if outcome_code not in {"succeeded", "failed"}:
        raise IngestionContractError("fetch_outcome_invalid")
    if type(fetched_count) is not int or fetched_count < 0:
        raise IngestionContractError("fetched_count_invalid")
    if error_code is not None and (
        type(error_code) is not str or _CODE_PATTERN.fullmatch(error_code) is None
    ):
        raise IngestionContractError("fetch_error_code_invalid")
    if (outcome_code == "succeeded") != (error_code is None):
        raise IngestionContractError("fetch_outcome_invalid")
    if outcome_code == "failed" and fetched_count != 0:
        raise IngestionContractError("fetch_outcome_invalid")
    started_text = format_shanghai(started_at)
    completed_text = format_shanghai(completed_at)
    if completed_text < started_text:
        raise IngestionContractError("fetch_time_invalid")
    return db.execute(
        "INSERT INTO ingestion_fetch_attempts "
        "(source_code,source_name,outcome_code,error_code,fetched_count,started_at,"
        "completed_at,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            source_code,
            normalized_source_name,
            outcome_code,
            error_code,
            fetched_count,
            started_text,
            completed_text,
            completed_text,
        ),
    ).lastrowid


def mark_candidate_pending(
    db: sqlite3.Connection,
    candidate_id: int,
    expected_lock_version: int,
    now: datetime,
) -> None:
    timestamp = format_shanghai(now)
    if type(candidate_id) is not int or candidate_id <= 0:
        raise IngestionConflictError()
    if type(expected_lock_version) is not int or expected_lock_version <= 0:
        raise IngestionConflictError()
    cursor = db.execute(
        "UPDATE ingestion_candidates SET state='pending_review',"
        "lock_version=lock_version+1,updated_at=? "
        "WHERE id=? AND state='fetched' AND lock_version=?",
        (timestamp, candidate_id, expected_lock_version),
    )
    if cursor.rowcount != 1:
        raise IngestionConflictError()


def _validate_audit_metadata(value, *, depth=0):
    if depth > 8:
        raise IngestionContractError("audit_metadata_invalid")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                type(key) is not str
                or _CODE_PATTERN.fullmatch(key) is None
                or any(part in key for part in _FORBIDDEN_AUDIT_KEY_PARTS)
            ):
                raise IngestionContractError("audit_metadata_invalid")
            _validate_audit_metadata(item, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_audit_metadata(item, depth=depth + 1)
        return
    if value is None or type(value) is bool:
        return
    if type(value) is int and 0 <= value <= _AUDIT_INTEGER_MAX:
        return
    if (
        type(value) is str
        and _CODE_PATTERN.fullmatch(value) is not None
        and not (
            7 <= len(value.replace("-", "")) <= 20
            and value.replace("-", "").isdigit()
        )
    ):
        return
    raise IngestionContractError("audit_metadata_invalid")


def _is_non_sensitive_code_token(value) -> bool:
    if type(value) is not str or _AUDIT_ACTOR_PATTERN.fullmatch(value) is None:
        return False
    digits = value.translate(str.maketrans("", "", "-._"))
    if 7 <= len(digits) <= 20 and digits.isdigit():
        return False
    extension = value.rsplit(".", 1)[-1].casefold() if "." in value else ""
    return extension not in _SENSITIVE_ACTOR_FILE_EXTENSIONS


def write_governance_audit_event(
    db: sqlite3.Connection,
    *,
    action: str,
    target_type: str,
    target_id: int,
    actor: str,
    metadata,
    now,
) -> int:
    if type(action) is not str or _CODE_PATTERN.fullmatch(action) is None:
        raise IngestionContractError("audit_action_invalid")
    if type(target_type) is not str or _CODE_PATTERN.fullmatch(target_type) is None:
        raise IngestionContractError("audit_target_type_invalid")
    if type(target_id) is not int or target_id <= 0:
        raise IngestionContractError("audit_target_invalid")
    if not _is_non_sensitive_code_token(actor):
        raise IngestionContractError("audit_actor_invalid")
    if metadata is not None:
        if not isinstance(metadata, Mapping):
            raise IngestionContractError("audit_metadata_invalid")
        _validate_audit_metadata(metadata)
        metadata_json = json.dumps(
            metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if len(metadata_json.encode("utf-8")) > 2000:
            raise IngestionContractError("audit_metadata_invalid")
    else:
        metadata_json = None
    return db.execute(
        "INSERT INTO governance_audit_events "
        "(action,target_type,target_id,actor,metadata_json,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            action,
            target_type,
            target_id,
            actor,
            metadata_json,
            format_shanghai(now),
        ),
    ).lastrowid
