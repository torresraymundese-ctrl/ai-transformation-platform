"""Atomic media persistence, archival, lookup, and non-destructive recovery."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

from flask import current_app, has_app_context

from content_clock import format_shanghai, shanghai_now
from content_contracts import ContentContractError
from content_validation import ContentValidationError
from media_validation import (
    ATTACHMENT_MIMES,
    IMAGE_MIMES,
    MediaValidationError,
    upload_contract,
    validate_media_file,
)
import models
import publishing_repository
from pagination import Page, PageRequest, parse_bounded_search


DEFAULT_MEDIA_CONFIG = {
    "MEDIA_IMAGE_MAX_BYTES": 8 * 1024 * 1024,
    "MEDIA_ATTACHMENT_MAX_BYTES": 20 * 1024 * 1024,
    "MEDIA_IMAGE_MAX_PIXELS": 40_000_000,
    "MEDIA_OOXML_MAX_MEMBERS": 1024,
    "MEDIA_OOXML_MAX_UNCOMPRESSED_BYTES": 100 * 1024 * 1024,
    "MEDIA_OOXML_MAX_COMPRESSION_RATIO": 20,
    # Cumulative across inspected XML parts; depth is per XML document.
    "MEDIA_OOXML_XML_MAX_NODES": 250_000,
    "MEDIA_OOXML_XML_MAX_DEPTH": 128,
    "MEDIA_OOXML_XML_MAX_CHARACTERS": 8_000_000,
    "MEDIA_PDF_MAX_PAGES": 500,
}


class MediaNotFoundError(LookupError):
    """Raised when an asset is not in an operable state."""


class MediaInUseError(ValueError):
    """Raised when published content still references an asset."""


@dataclass(frozen=True)
class MediaAsset:
    id: int
    storage_name: str
    display_name: str
    detected_mime: str
    byte_size: int
    sha256: str
    status: str


@dataclass(frozen=True)
class MediaFilters:
    status: str | None = None
    search: str | None = None


def parse_media_filters(values) -> MediaFilters:
    try:
        raw_status = values.get("status", "")
    except (AttributeError, TypeError):
        raw_status = ""
    status = raw_status.strip() if type(raw_status) is str else ""
    return MediaFilters(
        status=status if status in {"pending", "ready", "archived"} else None,
        search=parse_bounded_search(values),
    )


def _media_predicate(filters: MediaFilters):
    clauses = []
    parameters = []
    if filters.status is not None:
        clauses.append("status=?")
        parameters.append(filters.status)
    if filters.search is not None:
        pattern = (
            "%"
            + filters.search.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            + "%"
        )
        clauses.append("display_name LIKE ? ESCAPE '\\'")
        parameters.append(pattern)
    return (
        " WHERE " + " AND ".join(clauses) if clauses else "",
        tuple(parameters),
    )


def query_media_assets(filters: MediaFilters, page: PageRequest) -> Page[MediaAsset]:
    where, parameters = _media_predicate(filters)
    connection = models.get_db()
    try:
        total = connection.execute(
            "SELECT COUNT(*) FROM media_assets" + where, parameters
        ).fetchone()[0]
        if total == 0:
            return Page((), 1, page.per_page, 0, 0)
        total_pages = (total + page.per_page - 1) // page.per_page
        page_number = min(page.page, total_pages)
        items = tuple(
            _asset(row)
            for row in connection.execute(
                "SELECT * FROM media_assets"
                + where
                + " ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
                (*parameters, page.per_page, (page_number - 1) * page.per_page),
            ).fetchall()
        )
        return Page(items, page_number, page.per_page, total, total_pages)
    finally:
        connection.close()


@dataclass(frozen=True)
class RecoveryFinding:
    asset_id: int | None
    status: str


@dataclass(frozen=True)
class RecoveryResult:
    findings: tuple[RecoveryFinding, ...]

    @property
    def count(self):
        return len(self.findings)


def media_root(root=None, *, create=True):
    """Resolve the trusted configured root without using an upload filename."""
    if root is None and has_app_context():
        root = current_app.config.get("MEDIA_UPLOAD_ROOT")
    if root is None:
        root = os.environ.get("AI_PLATFORM_MEDIA_ROOT")
    if root is None:
        root = Path(__file__).resolve().parent / "data" / "media"
    resolved = Path(root).expanduser().resolve()
    if create:
        resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.is_dir():
        raise OSError("media root is not a directory")
    return resolved


def _config():
    values = dict(DEFAULT_MEDIA_CONFIG)
    if has_app_context():
        values.update({key: current_app.config[key] for key in values})
    return values


def _asset(row):
    if row is None:
        return None
    return MediaAsset(
        id=row["id"],
        storage_name=row["storage_name"],
        display_name=row["display_name"],
        detected_mime=row["detected_mime"],
        byte_size=row["byte_size"],
        sha256=row["sha256"],
        status=row["status"],
    )


def _load_asset(connection, asset_id):
    return _asset(
        connection.execute(
            "SELECT * FROM media_assets WHERE id=?", (asset_id,)
        ).fetchone()
    )


def get_media_asset(asset_id):
    connection = models.get_db()
    try:
        return _load_asset(connection, asset_id)
    finally:
        connection.close()


def list_media_assets():
    connection = models.get_db()
    try:
        return tuple(
            _asset(row)
            for row in connection.execute(
                "SELECT * FROM media_assets ORDER BY id DESC"
            ).fetchall()
        )
    finally:
        connection.close()


def get_published_media_asset(asset_id, *, kind, now=None):
    """Return a ready asset only when a current publication references it."""
    if kind == "image":
        allowed = IMAGE_MIMES
        reference_clause = (
            "ci.share_image_media_id=? OR EXISTS ("
            "SELECT 1 FROM content_blocks cb WHERE cb.content_item_id=ci.id "
            "AND cb.block_type='image_text' AND cb.media_asset_id=?)"
        )
    elif kind == "download":
        allowed = ATTACHMENT_MIMES
        reference_clause = (
            "EXISTS (SELECT 1 FROM content_blocks cb WHERE cb.content_item_id=ci.id "
            "AND cb.block_type='download' AND cb.media_asset_id=?) OR EXISTS ("
            "SELECT 1 FROM resource_content rc WHERE rc.content_item_id=ci.id "
            "AND rc.attachment_media_id=?)"
        )
    else:
        raise ValueError("unknown public media kind")
    placeholders = ",".join("?" for _ in allowed)
    instant = shanghai_now() if now is None else now
    timestamp = format_shanghai(instant)
    connection = models.get_db()
    try:
        connection.execute("BEGIN")
        asset_row = connection.execute(
            f"SELECT * FROM media_assets WHERE id=? AND status='ready' "
            f"AND detected_mime IN ({placeholders})",
            (asset_id, *sorted(allowed)),
        ).fetchone()
        if asset_row is None:
            return None
        references = connection.execute(
            "SELECT ci.id,ci.entry_type FROM content_items ci "
            "WHERE ci.status='published' AND (ci.publish_at IS NULL OR ci.publish_at<=?) "
            f"AND ({reference_clause}) ORDER BY ci.id",
            (timestamp, asset_id, asset_id),
        ).fetchall()
        for reference in references:
            try:
                if reference["entry_type"] == "resource":
                    publishing_repository.validate_resource_public_completeness(
                        connection, reference["id"], instant
                    )
                elif reference["entry_type"] == "announcement":
                    draft = publishing_repository.validate_announcement_public_completeness(
                        connection, reference["id"], instant
                    )
                    if not (
                        draft.extension["valid_from"]
                        <= timestamp
                        <= draft.extension["valid_until"]
                    ):
                        continue
                else:
                    from catalog_content_repository import has_current_public_projection

                    if not has_current_public_projection(
                        connection, reference["id"], instant
                    ):
                        continue
            except (ContentContractError, ContentValidationError):
                continue
            return _asset(asset_row)
        return None
    finally:
        connection.rollback()
        connection.close()


def _stream_to_temp(upload, root, maximum):
    handle = tempfile.NamedTemporaryFile(
        mode="wb", prefix=".upload-", suffix=".tmp", dir=root, delete=False
    )
    path = Path(handle.name)
    total = 0
    try:
        while True:
            chunk = upload.stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise MediaValidationError("media exceeds its size limit")
            handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())
    except Exception:
        handle.close()
        path.unlink(missing_ok=True)
        raise
    handle.close()
    if total < 1:
        path.unlink(missing_ok=True)
        raise MediaValidationError("media file is empty")
    return path


def store_media(upload, *, metadata_review_confirmed=False):
    """Validate outside a transaction, then atomically bind bytes to a ready row."""
    if upload is None:
        raise MediaValidationError("media file is required")
    display_name, contract = upload_contract(upload.filename, upload.mimetype)
    config = _config()
    maximum = (
        int(config["MEDIA_IMAGE_MAX_BYTES"])
        if contract[0] in IMAGE_MIMES
        else int(config["MEDIA_ATTACHMENT_MAX_BYTES"])
    )
    root = media_root()
    temporary_path = _stream_to_temp(upload, root, maximum)
    asset_id = None
    try:
        validated = validate_media_file(
            temporary_path,
            filename=display_name,
            declared_mime=upload.mimetype,
            config=config,
            confirmed=metadata_review_confirmed is True,
        )
        timestamp = format_shanghai(shanghai_now())
        storage_name = f"{uuid.uuid4().hex}{validated.extension}"
        final_path = root / storage_name
        connection = models.get_db()
        try:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                "SELECT * FROM media_assets "
                "WHERE sha256=? AND status IN ('pending','ready')",
                (validated.sha256,),
            ).fetchone()
            if duplicate is not None:
                connection.commit()
                if duplicate["status"] != "ready":
                    raise MediaValidationError("matching media is pending recovery")
            else:
                cursor = connection.execute(
                    "INSERT INTO media_assets "
                    "(storage_name,display_name,detected_mime,byte_size,sha256,status,"
                    "created_at,updated_at) "
                    "VALUES (?,?,?,?,?,'pending',?,?)",
                    (
                        storage_name,
                        display_name,
                        validated.detected_mime,
                        validated.byte_size,
                        validated.sha256,
                        timestamp,
                        timestamp,
                    ),
                )
                asset_id = cursor.lastrowid
                connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        if duplicate is not None:
            return _reuse_or_restore_ready_duplicate(root, temporary_path, duplicate)

        try:
            os.replace(temporary_path, final_path)
        except Exception:
            _archive_pending_compensation(asset_id, timestamp)
            raise

        connection = models.get_db()
        try:
            connection.execute("BEGIN IMMEDIATE")
            _mark_media_ready(connection, asset_id, timestamp)
            connection.commit()
            return _load_asset(connection, asset_id)
        except Exception:
            connection.rollback()
            _archive_pending_compensation(asset_id, timestamp)
            raise
        finally:
            connection.close()
    finally:
        temporary_path.unlink(missing_ok=True)


def _reuse_or_restore_ready_duplicate(root, temporary_path, row):
    existing_path = root / row["storage_name"]
    if not _disk_matches(existing_path, row):
        try:
            existing_path.lstat()
        except FileNotFoundError:
            try:
                os.link(temporary_path, existing_path)
            except FileExistsError:
                pass
        if not _disk_matches(existing_path, row):
            raise MediaValidationError("matching media storage is inconsistent")
    return _recheck_ready_duplicate(existing_path, row)


def _recheck_ready_duplicate(existing_path, original_row):
    connection = models.get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT * FROM media_assets WHERE id=?", (original_row["id"],)
        ).fetchone()
        identity_fields = ("storage_name", "detected_mime", "byte_size", "sha256")
        if (
            current is None
            or current["status"] != "ready"
            or any(current[field] != original_row[field] for field in identity_fields)
            or not _disk_matches(existing_path, current)
        ):
            raise MediaValidationError("matching media is no longer ready")
        connection.commit()
        return _asset(current)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _mark_media_ready(connection, asset_id, timestamp):
    cursor = connection.execute(
        "UPDATE media_assets SET status='ready',scan_result_code='validated',"
        "scan_checked_at=?,ready_at=?,updated_at=? WHERE id=? AND status='pending'",
        (timestamp, timestamp, timestamp, asset_id),
    )
    if cursor.rowcount != 1:
        raise sqlite3.IntegrityError("media pending state was lost")


def _archive_pending_compensation(asset_id, timestamp):
    if asset_id is None:
        return
    connection = models.get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE media_assets SET status='archived',archived_at=?,updated_at=? "
            "WHERE id=? AND status='pending'",
            (timestamp, timestamp, asset_id),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
    finally:
        connection.close()


def archive_media(asset_id):
    """Archive an unreferenced asset without deleting its row or bytes."""
    timestamp = format_shanghai(shanghai_now())
    connection = models.get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        asset = _load_asset(connection, asset_id)
        if asset is None or asset.status == "archived":
            raise MediaNotFoundError()
        try:
            cursor = connection.execute(
                "UPDATE media_assets SET status='archived',archived_at=?,updated_at=? "
                "WHERE id=? AND status IN ('pending','ready')",
                (timestamp, timestamp, asset_id),
            )
        except sqlite3.IntegrityError as error:
            if "published content still references media" in str(error):
                raise MediaInUseError("published content still references media") from error
            raise
        if cursor.rowcount != 1:
            raise MediaNotFoundError()
        connection.commit()
        return _load_asset(connection, asset_id)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _disk_matches(path, row):
    try:
        if path.stat().st_size != row["byte_size"]:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == row["sha256"]
    except OSError:
        return False


def recover_media_storage(*, root=None, apply=False):
    """Report reconciliation by ID/status and optionally apply safe state transitions."""
    root_path = media_root(root, create=False)
    connection = models.get_db()
    findings = []
    try:
        rows = connection.execute("SELECT * FROM media_assets ORDER BY id").fetchall()
        known_names = {row["storage_name"] for row in rows}
        for row in rows:
            path = root_path / row["storage_name"]
            exists = path.is_file()
            if row["status"] == "pending":
                if not exists:
                    status = "pending_missing"
                    if apply:
                        _archive_recovery_row(connection, row["id"])
                        status = "pending_archived"
                elif _disk_matches(path, row):
                    status = "pending_recoverable"
                    if apply:
                        timestamp = format_shanghai(shanghai_now())
                        _mark_media_ready(connection, row["id"], timestamp)
                        status = "pending_recovered"
                else:
                    status = "pending_mismatch"
                    if apply:
                        _archive_recovery_row(connection, row["id"])
                        status = "pending_mismatch_archived"
                findings.append(RecoveryFinding(row["id"], status))
            elif row["status"] == "ready" and not exists:
                status = "ready_missing"
                if apply:
                    try:
                        _archive_recovery_row(connection, row["id"])
                        status = "missing_archived"
                    except sqlite3.IntegrityError:
                        status = "missing_archive_blocked"
                findings.append(RecoveryFinding(row["id"], status))

        for path in sorted(root_path.iterdir(), key=lambda item: item.name):
            if path.is_file() and path.name not in known_names:
                findings.append(RecoveryFinding(None, "orphan_file"))
        if apply:
            connection.commit()
        else:
            connection.rollback()
        return RecoveryResult(tuple(findings))
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _archive_recovery_row(connection, asset_id):
    timestamp = format_shanghai(shanghai_now())
    cursor = connection.execute(
        "UPDATE media_assets SET status='archived',archived_at=?,updated_at=? "
        "WHERE id=? AND status IN ('pending','ready')",
        (timestamp, timestamp, asset_id),
    )
    if cursor.rowcount != 1:
        raise sqlite3.IntegrityError("media recovery state was lost")


__all__ = [
    "MediaAsset",
    "MediaInUseError",
    "MediaNotFoundError",
    "MediaValidationError",
    "RecoveryFinding",
    "RecoveryResult",
    "archive_media",
    "get_media_asset",
    "get_published_media_asset",
    "list_media_assets",
    "media_root",
    "recover_media_storage",
    "store_media",
]
