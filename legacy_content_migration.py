"""Deterministic review, source preflight, and approved legacy conversion.

Inventory remains local and read-only. Network preflight and conversion are
explicit later operations; conversion creates drafts and never deletes or
publishes a legacy row.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from html import escape
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
from types import MappingProxyType
from typing import Literal, Mapping
import unicodedata
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from content_clock import as_shanghai, format_shanghai, parse_shanghai
from content_contracts import CaseMetric, ContentBlock, ContentDraft
from content_validation import ContentValidationError, validate_content_draft
import publishing_repository
from source_url_checker import (
    PinnedHttpTransport,
    check_source_url,
    normalize_source_url,
    source_state_for_check,
)


PROJECT_ROOT = Path(__file__).resolve().parent
MAPPING_RULES_PATH = PROJECT_ROOT / "seed_data" / "legacy_content_mapping_rules.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")

SOURCE_TABLES = ("announcements", "articles", "cases", "services")
TARGET_TYPES = ("announcement", "case", "resource", "service")
SERVICE_GROUPS = (
    "foundation_workshop",
    "knowledge_assistant_pilot",
    "customer_growth_pilot",
    "workflow_automation",
    "data_insight",
    "industry_integration",
)
ACTIONS = ("keep", "clean", "archive", "delete_later")
SOURCE_STATES = ("reachable", "unreachable", "invalid", "missing", "unchecked")
_RULE_KEYS = {
    "version",
    "allowed_source_tables",
    "allowed_target_types",
    "allowed_target_groups",
    "service_code_targets",
}
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_NUMERIC_HOST_LABEL = re.compile(r"(?:[0-9]+|0[xX][0-9a-fA-F]+)\Z")
DECISION_VERSION = 1
MAX_DECISION_BYTES = 1_048_576
MAX_DECISION_LINES = 10_000
MAX_DECISION_DEPTH = 8
SQLITE_MAX_INT = 9_223_372_036_854_775_807
SOURCE_CHECK_TTL = timedelta(days=7)
DECISION_KEYS = frozenset(
    {
        "version",
        "source_table",
        "source_id",
        "source_checksum",
        "action",
        "confirmations",
        "target",
    }
)
CONVERTIBLE_ACTIONS = {
    "services": "keep",
    "cases": "clean",
    "articles": "clean",
    "announcements": "clean",
}
SUCCESS_MIGRATION_STATUSES = frozenset(
    {"ready", "target_draft_exists", "migrated", "already_mapped"}
)


@dataclass(frozen=True)
class ReviewItem:
    source_table: str
    source_id: int
    source_checksum: str
    title_summary: str
    proposed_action: Literal["keep", "clean", "archive", "delete_later"]
    reason_code: str
    target_type: str | None
    target_group: str | None
    source_state: Literal[
        "reachable", "unreachable", "invalid", "missing", "unchecked"
    ]
    required_confirmations: tuple[str, ...]
    target_preview: Mapping[str, object] | None

    @property
    def action(self) -> str:
        return self.proposed_action


class LegacyDecisionError(ValueError):
    """Raised when an operator decision artifact is not exact JSONL."""


@dataclass(frozen=True)
class LegacyDecision:
    source_table: str
    source_id: int
    source_checksum: str
    action: str
    confirmations: tuple[str, ...]
    target: Mapping[str, object]


@dataclass(frozen=True)
class LegacyCheckItem:
    source_table: str
    source_id: int
    state: str
    code: str


@dataclass(frozen=True)
class LegacyCheckResult:
    items: tuple[LegacyCheckItem, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class LegacyMigrationItem:
    source_table: str
    source_id: int
    status: str
    target_content_id: int | None = None
    target_content_group_id: int | None = None
    target_lock_version: int | None = None
    preview: Mapping[str, object] | None = None


@dataclass(frozen=True)
class LegacyMigrationResult:
    items: tuple[LegacyMigrationItem, ...]

    @property
    def target_ids(self):
        return tuple(
            item.target_content_id
            for item in self.items
            if item.status in {"migrated", "already_mapped"}
            and item.target_content_id is not None
        )

    @property
    def errors(self):
        return tuple(
            item.status
            for item in self.items
            if item.status not in SUCCESS_MIGRATION_STATUSES
        )


def current_shanghai_datetime() -> datetime:
    return datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)


def _timestamp() -> str:
    return current_shanghai_datetime().strftime("%Y-%m-%d %H:%M:%S")


def _load_mapping_rules() -> dict[str, object]:
    try:
        raw = json.loads(MAPPING_RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid legacy content mapping rules") from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != _RULE_KEYS
        or type(raw.get("version")) is not int
        or raw.get("version") != 1
    ):
        raise ValueError("invalid legacy content mapping rules")
    for key, expected in (
        ("allowed_source_tables", SOURCE_TABLES),
        ("allowed_target_types", TARGET_TYPES),
        ("allowed_target_groups", SERVICE_GROUPS),
    ):
        values = raw.get(key)
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) for value in values)
            or len(values) != len(set(values))
            or set(values) != set(expected)
        ):
            raise ValueError(f"invalid legacy content mapping rules {key}")
    targets = raw.get("service_code_targets")
    if not isinstance(targets, dict) or set(targets) != set(SERVICE_GROUPS):
        raise ValueError("invalid legacy content mapping rules service targets")
    for code, target in targets.items():
        if (
            not isinstance(target, dict)
            or set(target) != {"target_type", "target_group"}
            or target.get("target_type") != "service"
            or target.get("target_group") != code
        ):
            raise ValueError("invalid legacy content mapping rules service target")
    return raw


def _title_summary(value: object, source_table: str, source_id: int) -> str:
    normalized = " ".join(str(value or "").split())
    return (normalized or f"{source_table} #{source_id}")[:300]


def _canonical_checksum(source_table: str, row: sqlite3.Row) -> str:
    payload = {
        "source_table": source_table,
        "row": {key: row[key] for key in sorted(row.keys())},
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_public_url(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    candidate = value
    if (
        any(char.isspace() or unicodedata.category(char).startswith("C") for char in candidate)
        or "\\" in candidate
        or _INVALID_PERCENT_ESCAPE.search(candidate)
    ):
        return None
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    bracketed_literal = parsed.netloc.startswith("[")
    try:
        ascii_host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if ascii_host == "localhost" or ascii_host.endswith(".localhost"):
        return None
    try:
        ip = ipaddress.ip_address(ascii_host)
    except ValueError:
        labels = ascii_host.split(".")
        if (
            bracketed_literal
            or all(_NUMERIC_HOST_LABEL.fullmatch(label) for label in labels)
        ):
            return None
        if (
            len(ascii_host) > 253
            or len(labels) < 2
            or any(_DNS_LABEL.fullmatch(label) is None for label in labels)
        ):
            return None
    else:
        if not ip.is_global or (ip.version == 6 and not bracketed_literal):
            return None
        if ip.version == 6:
            ascii_host = f"[{ascii_host}]"
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    authority = ascii_host if port is None or default_port else f"{ascii_host}:{port}"
    display = urlunsplit((scheme, authority, parsed.path or "", "", ""))
    if (
        not (display.startswith("https://") or display.startswith("http://"))
        or any(character in display for character in "?#@")
    ):
        return None
    full_normalized = urlunsplit(
        (scheme, authority, parsed.path or "", parsed.query, "")
    )
    return display, hashlib.sha256(full_normalized.encode("utf-8")).hexdigest()


def _service_item(row: sqlite3.Row, rules: Mapping[str, object]) -> ReviewItem:
    source_id = row["id"]
    title = _title_summary(row["name"], "services", source_id)
    code = row["code"]
    targets = rules["service_code_targets"]
    target = targets.get(code) if isinstance(targets, dict) else None
    if target is None:
        return ReviewItem(
            "services", source_id, _canonical_checksum("services", row), title,
            "archive", "service_unmappable", None, None, "unchecked", (), None,
        )
    return ReviewItem(
        "services", source_id, _canonical_checksum("services", row), title,
        "keep", "service_code_matches_v2", "service", target["target_group"],
        "unchecked", ("service_scope_review", "deliverables_review"),
        {
            "entry_type": "service", "service_code": code, "title": title,
            "status": "draft", "publishable": False,
        },
    )


def _case_item(row: sqlite3.Row) -> ReviewItem:
    source_id = row["id"]
    title = _title_summary(row["title"], "cases", source_id)
    return ReviewItem(
        "cases", source_id, _canonical_checksum("cases", row), title,
        "delete_later", "case_source_or_metric_unverified", "case", None,
        "unchecked", ("source_or_authorization", "metric_basis", "privacy_review"),
        {"entry_type": "case", "title": title, "status": "draft", "publishable": False},
    )


def _article_item(row: sqlite3.Row) -> ReviewItem:
    source_id = row["id"]
    title = _title_summary(row["title"], "articles", source_id)
    source_url = row["source_url"]
    url_metadata = _normalized_public_url(source_url)
    if url_metadata is None:
        reason = (
            "article_source_url_missing"
            if not isinstance(source_url, str) or not source_url.strip()
            else "article_source_url_invalid"
        )
        return ReviewItem(
            "articles", source_id, _canonical_checksum("articles", row), title,
            "archive", reason, None, None, "unchecked", (), None,
        )
    display, _ = url_metadata
    return ReviewItem(
        "articles", source_id, _canonical_checksum("articles", row), title,
        "clean", "article_source_requires_check", "resource", None, "unchecked",
        ("source_reachable", "content_valid", "summary_suitable", "copyright_review"),
        {
            "entry_type": "resource", "resource_type": "article", "title": title,
            "status": "draft", "source_url_display": display, "publishable": False,
        },
    )


def _announcement_item(row: sqlite3.Row) -> ReviewItem:
    source_id = row["id"]
    title = _title_summary(row["title"], "announcements", source_id)
    return ReviewItem(
        "announcements", source_id, _canonical_checksum("announcements", row), title,
        "archive", "announcement_validity_unconfirmed", "announcement", None,
        "unchecked", ("valid_from", "valid_until"),
        {
            "entry_type": "announcement", "title": title, "status": "draft",
            "valid_from": None, "valid_until": None, "publishable": False,
        },
    )


def inventory_legacy_content(db: sqlite3.Connection) -> tuple[ReviewItem, ...]:
    """Return a stable, zero-write inventory of all four legacy content tables."""
    rules = _load_mapping_rules()
    classifiers = {
        "announcements": _announcement_item,
        "articles": _article_item,
        "cases": _case_item,
    }
    items: list[ReviewItem] = []
    for source_table in SOURCE_TABLES:
        rows = db.execute(f"SELECT * FROM {source_table} ORDER BY id").fetchall()
        for row in rows:
            items.append(
                _service_item(row, rules)
                if source_table == "services"
                else classifiers[source_table](row)
            )
    return tuple(items)


def _json(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_item(item: ReviewItem, rules: Mapping[str, object]) -> None:
    if not isinstance(item, ReviewItem):
        raise ValueError("inventory item must be a ReviewItem")
    if item.source_table not in SOURCE_TABLES:
        raise ValueError("invalid source_table")
    if (
        type(item.source_id) is not int
        or not 1 <= item.source_id <= SQLITE_MAX_INT
    ):
        raise ValueError("invalid source_id")
    if not _HEX_SHA256.fullmatch(item.source_checksum):
        raise ValueError("invalid source_checksum")
    if not 1 <= len(item.title_summary) <= 300:
        raise ValueError("invalid title_summary")
    if item.proposed_action not in ACTIONS or not 1 <= len(item.reason_code) <= 80:
        raise ValueError("invalid proposed action")
    if item.source_state not in SOURCE_STATES:
        raise ValueError("invalid source state")
    if item.target_type is not None and item.target_type not in rules["allowed_target_types"]:
        raise ValueError("invalid target type")
    if item.target_group is not None and (
        item.target_type != "service"
        or item.target_group not in rules["allowed_target_groups"]
    ):
        raise ValueError("invalid target group")
    expected_types = {
        "services": {None, "service"}, "cases": {None, "case"},
        "articles": {None, "resource"}, "announcements": {None, "announcement"},
    }[item.source_table]
    if item.target_type not in expected_types:
        raise ValueError("target type does not match source table")
    if any(
        not isinstance(code, str) or not code or len(code) > 80
        for code in item.required_confirmations
    ):
        raise ValueError("invalid required confirmation")
    preview_json = _json(item.target_preview)
    if preview_json is not None and len(preview_json) > 100_000:
        raise ValueError("target preview is too large")


def _current_source_row(db: sqlite3.Connection, item: ReviewItem) -> sqlite3.Row:
    row = db.execute(
        f"SELECT * FROM {item.source_table} WHERE id=?", (item.source_id,)
    ).fetchone()
    if row is None:
        raise ValueError("legacy source row no longer exists")
    if _canonical_checksum(item.source_table, row) != item.source_checksum:
        raise ValueError("legacy source row changed after inventory")
    return row


def _source_url_fields(item: ReviewItem, row: sqlite3.Row) -> tuple[str | None, str | None]:
    if item.source_table != "articles":
        return None, None
    metadata = _normalized_public_url(row["source_url"])
    return metadata if metadata is not None else (None, None)


def record_legacy_inventory(
    db: sqlite3.Connection, items: tuple[ReviewItem, ...]
) -> int:
    """Atomically upsert review artifacts without changing legacy or V2 content."""
    rules = _load_mapping_rules()
    identities: set[tuple[str, int]] = set()
    for item in items:
        _validate_item(item, rules)
        identity = (item.source_table, item.source_id)
        if identity in identities:
            raise ValueError("duplicate legacy source identity")
        identities.add(identity)
    if db.in_transaction:
        raise RuntimeError("record_legacy_inventory requires a transaction-free connection")

    now = _timestamp()
    try:
        db.execute("BEGIN IMMEDIATE")
        for item in items:
            source_row = _current_source_row(db, item)
            source_url_display, source_url_sha256 = _source_url_fields(item, source_row)
            required_json = _json(item.required_confirmations)
            preview_json = _json(item.target_preview)
            existing = db.execute(
                "SELECT source_checksum FROM legacy_content_reviews "
                "WHERE source_table=? AND source_id=?",
                (item.source_table, item.source_id),
            ).fetchone()
            derived = (
                item.title_summary, item.source_checksum, item.proposed_action,
                item.reason_code, item.target_type, item.target_group, required_json,
                preview_json, source_url_display, source_url_sha256, now,
                item.source_table, item.source_id,
            )
            if existing is None:
                db.execute(
                    "INSERT INTO legacy_content_reviews "
                    "(source_table,source_id,title_summary,source_checksum,"
                    "proposed_action,reason_code,source_state,target_type,target_group,"
                    "required_confirmations_json,target_preview_json,source_url_display,"
                    "source_url_sha256,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        item.source_table, item.source_id, item.title_summary,
                        item.source_checksum, item.proposed_action, item.reason_code,
                        item.source_state, item.target_type, item.target_group,
                        required_json, preview_json, source_url_display,
                        source_url_sha256, now, now,
                    ),
                )
            elif existing["source_checksum"] == item.source_checksum:
                db.execute(
                    "UPDATE legacy_content_reviews SET title_summary=?,source_checksum=?,"
                    "proposed_action=?,reason_code=?,target_type=?,target_group=?,"
                    "required_confirmations_json=?,target_preview_json=?,"
                    "source_url_display=?,source_url_sha256=?,updated_at=? "
                    "WHERE source_table=? AND source_id=?",
                    derived,
                )
            else:
                db.execute(
                    "UPDATE legacy_content_reviews SET title_summary=?,source_checksum=?,"
                    "proposed_action=?,reason_code=?,target_type=?,target_group=?,"
                    "required_confirmations_json=?,target_preview_json=?,"
                    "source_url_display=?,source_url_sha256=?,updated_at=?,"
                    "review_stale_at=? WHERE source_table=? AND source_id=?",
                    (*derived[:-2], now, *derived[-2:]),
                )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(items)


def _jsonl_object(item: ReviewItem) -> dict[str, object]:
    return {
        "source_table": item.source_table,
        "source_id": item.source_id,
        "source_checksum": item.source_checksum,
        "title_summary": item.title_summary,
        "proposed_action": item.proposed_action,
        "reason_code": item.reason_code,
        "target_type": item.target_type,
        "target_group": item.target_group,
        "source_state": item.source_state,
        "required_confirmations": list(item.required_confirmations),
        "target_preview": item.target_preview,
    }


def items_to_jsonl(items: tuple[ReviewItem, ...]) -> str:
    """Serialize only the review checklist's intentionally safe fields."""
    return "\n".join(
        json.dumps(
            _jsonl_object(item), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        for item in items
    )


def _decision_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LegacyDecisionError("duplicate decision key")
        result[key] = value
    return result


def _reject_json_constant(_value):
    raise LegacyDecisionError("non-finite JSON value")


def _json_depth(value, depth=0):
    if depth > MAX_DECISION_DEPTH:
        raise LegacyDecisionError("decision JSON is too deep")
    if type(value) is dict:
        for item in value.values():
            _json_depth(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _json_depth(item, depth + 1)


def _exact_timestamp(value):
    if type(value) is not str or re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value
    ) is None:
        return False
    try:
        parse_shanghai(value)
    except ValueError:
        return False
    return True


def _exact_nonblank(value, maximum):
    return (
        type(value) is str
        and "\x00" not in value
        and value == value.strip()
        and bool(value)
        and len(value) <= maximum
    )


def _freeze_target(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze_target(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze_target(item) for item in value)
    return value


def _validate_metric_target(value):
    keys = {
        "name",
        "before_value",
        "after_value",
        "unit",
        "statistical_period",
        "evidence_explanation",
    }
    if type(value) is not dict or set(value) != keys:
        raise LegacyDecisionError("invalid case metric")
    limits = {
        "name": 120,
        "before_value": 120,
        "after_value": 120,
        "unit": 40,
        "statistical_period": 120,
        "evidence_explanation": 1000,
    }
    if any(not _exact_nonblank(value[key], limits[key]) for key in keys):
        raise LegacyDecisionError("invalid case metric")


def _validate_decision_target(source_table, target):
    if type(target) is not dict:
        raise LegacyDecisionError("decision target must be an object")
    if source_table == "services":
        base = {"target_group"}
        approved = base | {
            "target_content_id",
            "expected_lock_version",
            "merge_approved",
        }
        if set(target) not in (base, approved):
            raise LegacyDecisionError("invalid service target")
        if target.get("target_group") not in SERVICE_GROUPS:
            raise LegacyDecisionError("invalid service target")
        if set(target) == approved and not (
            type(target["target_content_id"]) is int
            and 1 <= target["target_content_id"] <= SQLITE_MAX_INT
            and type(target["expected_lock_version"]) is int
            and 1 <= target["expected_lock_version"] <= SQLITE_MAX_INT
            and type(target["merge_approved"]) is bool
            and target["merge_approved"] is True
        ):
            raise LegacyDecisionError("invalid service merge approval")
        return
    if source_table == "articles":
        if set(target) != {"copyright_notice", "original_published_at"}:
            raise LegacyDecisionError("invalid article target")
        if not _exact_nonblank(target["copyright_notice"], 500) or not _exact_timestamp(
            target["original_published_at"]
        ):
            raise LegacyDecisionError("invalid article target")
        return
    if source_table == "announcements":
        if set(target) != {"valid_from", "valid_until", "cta_url"}:
            raise LegacyDecisionError("invalid announcement target")
        if (
            not _exact_timestamp(target["valid_from"])
            or not _exact_timestamp(target["valid_until"])
            or target["valid_from"] >= target["valid_until"]
            or not (
                target["cta_url"] is None
                or _exact_nonblank(target["cta_url"], 2048)
            )
        ):
            raise LegacyDecisionError("invalid announcement target")
        return
    if source_table == "cases":
        keys = {
            "verification_code",
            "is_anonymized",
            "basis_type",
            "private_basis_reference",
            "metrics",
        }
        if set(target) != keys:
            raise LegacyDecisionError("invalid case target")
        if (
            target["verification_code"]
            not in {"public_verified", "authorized_anonymous"}
            or type(target["is_anonymized"]) is not int
            or target["is_anonymized"] not in (0, 1)
            or (
                target["verification_code"], target["is_anonymized"]
            ) not in {
                ("public_verified", 0),
                ("authorized_anonymous", 1),
            }
            or target["basis_type"]
            not in {"client_authorization", "internal_delivery_record"}
            or not _exact_nonblank(target["private_basis_reference"], 300)
            or type(target["metrics"]) is not list
            or len(target["metrics"]) > 20
        ):
            raise LegacyDecisionError("invalid case target")
        for metric in target["metrics"]:
            _validate_metric_target(metric)
        return
    raise LegacyDecisionError("invalid source table")


def _decision_from_object(value):
    if type(value) is not dict or set(value) != DECISION_KEYS:
        raise LegacyDecisionError("invalid decision object")
    _json_depth(value)
    if type(value["version"]) is not int or value["version"] != DECISION_VERSION:
        raise LegacyDecisionError("invalid decision version")
    source_table = value["source_table"]
    source_id = value["source_id"]
    source_checksum = value["source_checksum"]
    action = value["action"]
    confirmations = value["confirmations"]
    if source_table not in SOURCE_TABLES:
        raise LegacyDecisionError("invalid decision source")
    if (
        type(source_id) is not int
        or not 1 <= source_id <= SQLITE_MAX_INT
    ):
        raise LegacyDecisionError("invalid decision source id")
    if type(source_checksum) is not str or _HEX_SHA256.fullmatch(source_checksum) is None:
        raise LegacyDecisionError("invalid decision checksum")
    if type(action) is not str or action not in ACTIONS:
        raise LegacyDecisionError("invalid decision action")
    if (
        type(confirmations) is not list
        or any(not _exact_nonblank(code, 80) for code in confirmations)
        or len(confirmations) != len(set(confirmations))
    ):
        raise LegacyDecisionError("invalid decision confirmations")
    _validate_decision_target(source_table, value["target"])
    return LegacyDecision(
        source_table,
        source_id,
        source_checksum,
        action,
        tuple(confirmations),
        _freeze_target(value["target"]),
    )


def load_legacy_decisions(path) -> tuple[LegacyDecision, ...]:
    """Read one strict, bounded operator-authored JSON object per line."""
    try:
        decision_path = Path(path)
        with decision_path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if before.st_size > MAX_DECISION_BYTES:
                raise LegacyDecisionError("decision file is too large")
            data = handle.read(MAX_DECISION_BYTES + 1)
            after = os.fstat(handle.fileno())
            before_shape = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            after_shape = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
        if (
            before_shape != after_shape
            or len(data) > MAX_DECISION_BYTES
            or len(data) != after.st_size
        ):
            raise LegacyDecisionError("decision file changed while reading")
        text = data.decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as error:
        raise LegacyDecisionError("decision file unavailable") from error
    lines = text.splitlines()
    if not lines or len(lines) > MAX_DECISION_LINES or any(not line.strip() for line in lines):
        raise LegacyDecisionError("decision file is empty or malformed")
    decisions = []
    identities = set()
    for line in lines:
        if len(line.encode("utf-8")) > 100_000:
            raise LegacyDecisionError("decision line is too large")
        try:
            raw = json.loads(
                line,
                object_pairs_hook=_decision_object,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, LegacyDecisionError, RecursionError) as error:
            raise LegacyDecisionError("invalid decision JSON") from error
        decision = _decision_from_object(raw)
        identity = (decision.source_table, decision.source_id)
        if identity in identities:
            raise LegacyDecisionError("duplicate decision identity")
        identities.add(identity)
        decisions.append(decision)
    return tuple(decisions)


def _thaw_decision_value(value):
    if isinstance(value, Mapping):
        return {key: _thaw_decision_value(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_decision_value(item) for item in value]
    return value


def _validated_decision_sequence(decisions):
    if type(decisions) not in (tuple, list):
        raise LegacyDecisionError("invalid decisions")
    validated = []
    identities = set()
    for decision in decisions:
        if type(decision) is not LegacyDecision:
            raise LegacyDecisionError("invalid decisions")
        normalized = _decision_from_object(
            {
                "version": DECISION_VERSION,
                "source_table": decision.source_table,
                "source_id": decision.source_id,
                "source_checksum": decision.source_checksum,
                "action": decision.action,
                "confirmations": list(decision.confirmations),
                "target": _thaw_decision_value(decision.target),
            }
        )
        identity = (normalized.source_table, normalized.source_id)
        if identity in identities:
            raise LegacyDecisionError("duplicate decision identity")
        identities.add(identity)
        validated.append(normalized)
    return tuple(validated)


def _source_row_by_identity(db, source_table, source_id):
    return db.execute(
        f"SELECT * FROM {source_table} WHERE id=?", (source_id,)
    ).fetchone()


def _selected_review_rows(db, identities):
    if identities is None:
        return tuple(
            db.execute(
                "SELECT * FROM legacy_content_reviews ORDER BY source_table,source_id"
            ).fetchall()
        )
    selected = []
    seen = set()
    for identity in identities:
        if (
            type(identity) not in (tuple, list)
            or len(identity) != 2
            or identity[0] not in SOURCE_TABLES
            or type(identity[1]) is not int
            or not 1 <= identity[1] <= SQLITE_MAX_INT
            or tuple(identity) in seen
        ):
            raise ValueError("invalid source-check identity")
        seen.add(tuple(identity))
        row = db.execute(
            "SELECT * FROM legacy_content_reviews WHERE source_table=? AND source_id=?",
            tuple(identity),
        ).fetchone()
        if row is None:
            raise ValueError("source review not found")
        selected.append(row)
    return tuple(selected)


def check_legacy_sources(
    db: sqlite3.Connection,
    *,
    transport: PinnedHttpTransport,
    actor: str,
    now: datetime,
    identities=None,
) -> LegacyCheckResult:
    """Fetch every selected source before atomically persisting generic results."""
    if db.in_transaction:
        raise RuntimeError("source checking requires a transaction-free connection")
    if not _exact_nonblank(actor, 200):
        raise ValueError("invalid source-check actor")
    instant = as_shanghai(now)
    checked_at = format_shanghai(instant)
    expires_at = format_shanghai(instant + timedelta(days=7))
    reviews = _selected_review_rows(db, identities)
    staged = []
    for review in reviews:
        source_row = _source_row_by_identity(
            db, review["source_table"], review["source_id"]
        )
        if source_row is None or _canonical_checksum(review["source_table"], source_row) != review[
            "source_checksum"
        ]:
            return LegacyCheckResult((), ("source_changed",))
        raw_url = source_row["source_url"] if review["source_table"] == "articles" else None
        has_source = type(raw_url) is str and bool(raw_url.strip())
        if has_source:
            result = check_source_url(raw_url, transport, instant)
            state = source_state_for_check(result, has_source=True)
            code = result.code
            item_checked_at = result.checked_at
            item_expires_at = result.expires_at
        else:
            state = "missing"
            code = "source_missing"
            item_checked_at = checked_at
            item_expires_at = expires_at
        staged.append(
            (
                review["source_table"],
                review["source_id"],
                review["source_checksum"],
                state,
                code,
                item_checked_at,
                item_expires_at,
            )
        )
    if db.in_transaction:
        raise RuntimeError("network phase retained a database transaction")
    try:
        db.execute("BEGIN IMMEDIATE")
        for source_table, source_id, checksum, state, code, item_checked_at, item_expires_at in staged:
            review = db.execute(
                "SELECT * FROM legacy_content_reviews WHERE source_table=? AND source_id=?",
                (source_table, source_id),
            ).fetchone()
            source_row = _source_row_by_identity(db, source_table, source_id)
            if (
                review is None
                or source_row is None
                or review["source_checksum"] != checksum
                or _canonical_checksum(source_table, source_row) != checksum
            ):
                raise ContentValidationError("source_changed")
            db.execute(
                "UPDATE legacy_content_reviews SET source_state=?,source_check_code=?,"
                "source_checked_at=?,source_check_expires_at=?,check_source_checksum=?,"
                "updated_at=? WHERE source_table=? AND source_id=? AND source_checksum=?",
                (
                    state,
                    code,
                    item_checked_at,
                    item_expires_at,
                    checksum,
                    checked_at,
                    source_table,
                    source_id,
                    checksum,
                ),
            )
        db.commit()
    except ContentValidationError as error:
        db.rollback()
        return LegacyCheckResult((), (error.code,))
    except Exception:
        db.rollback()
        raise
    return LegacyCheckResult(
        tuple(
            LegacyCheckItem(source_table, source_id, state, code)
            for source_table, source_id, _checksum, state, code, _checked, _expires in staged
        )
    )


def _safe_legacy_text(value, fallback, maximum):
    normalized = " ".join(str(value or "").replace("\x00", "").split())
    return (normalized or fallback)[:maximum]


def _body_from_legacy(row, fields):
    html_value = row["content_html"] if "content_html" in row.keys() else None
    if type(html_value) is str and html_value.strip():
        return html_value
    parts = []
    for field in fields:
        value = row[field] if field in row.keys() else None
        if type(value) is str and value.strip():
            parts.append(f"<p>{escape(value.strip())}</p>")
    return "".join(parts) or "<p>旧版内容已进入人工审阅草稿。</p>"


def _base_draft(entry_type, slug, title, summary, body, extension, *, metrics=()):
    safe_title = _safe_legacy_text(title, "", 120)
    if not safe_title:
        raise ContentValidationError("title_invalid")
    safe_summary = _safe_legacy_text(summary, safe_title, 300)
    return ContentDraft(
        entry_type=entry_type,
        slug=slug,
        title=safe_title,
        summary=safe_summary,
        seo_title=safe_title[:60],
        seo_description=safe_summary[:160],
        extension=extension,
        blocks=(
            ContentBlock(
                "rich_text",
                title="旧版内容审阅",
                body_html=body,
                settings={},
            ),
        ),
        metrics=tuple(metrics),
    )


def _article_draft(source_row, decision):
    url_metadata = _normalized_public_url(source_row["source_url"])
    if url_metadata is None:
        raise ContentValidationError("source_not_allowed")
    normalized, error = normalize_source_url(url_metadata[0])
    if error or not normalized or urlsplit(normalized).scheme != "https":
        raise ContentValidationError("source_not_allowed")
    target = decision.target
    source_name = _safe_legacy_text(source_row["source"], "", 200)
    if not source_name:
        raise ContentValidationError("article_draft_invalid")
    return _base_draft(
        "resource",
        f"legacy-article-{decision.source_id}",
        source_row["title"],
        source_row["summary"],
        _body_from_legacy(source_row, ("summary",)),
        {
            "resource_type": "article",
            "is_original": 0,
            "source_name": source_name,
            "source_url": normalized,
            "source_url_sha256": None,
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "original_published_at": target["original_published_at"],
            "copyright_notice": target["copyright_notice"],
            "attachment_media_id": None,
        },
    )


def _announcement_draft(source_row, decision):
    target = decision.target
    return _base_draft(
        "announcement",
        f"legacy-announcement-{decision.source_id}",
        source_row["title"],
        source_row["title"],
        _body_from_legacy(source_row, ("content_html",)),
        {
            "valid_from": target["valid_from"],
            "valid_until": target["valid_until"],
            "cta_url": target["cta_url"],
        },
    )


def _case_draft(source_row, decision, now):
    target = decision.target
    if not target["metrics"]:
        raise ContentValidationError("case_evidence_incomplete")
    metrics = tuple(
        CaseMetric(
            metric["name"],
            metric["before_value"],
            metric["after_value"],
            metric["unit"],
            metric["statistical_period"],
            metric["evidence_explanation"],
            index,
        )
        for index, metric in enumerate(target["metrics"])
    )
    summary = next(
        (
            source_row[field]
            for field in ("result", "solution", "pain_point")
            if type(source_row[field]) is str and source_row[field].strip()
        ),
        None,
    )
    return _base_draft(
        "case",
        f"legacy-case-{decision.source_id}",
        source_row["title"],
        summary,
        _body_from_legacy(source_row, ("pain_point", "solution", "result")),
        {
            "verification_code": target["verification_code"],
            "is_anonymized": target["is_anonymized"],
            "basis_type": target["basis_type"],
            "private_basis_reference": target["private_basis_reference"],
            "source_url": None,
            "source_url_sha256": None,
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "is_verified": 1,
            "review_confirmed": 1,
            "verified_at": format_shanghai(as_shanghai(now)),
        },
        metrics=metrics,
    )


def _service_target(db, decision):
    if decision.target["target_group"] not in SERVICE_GROUPS:
        return None
    return db.execute(
        "SELECT cg.id AS group_id,ci.id AS content_id,ci.lock_version "
        "FROM content_groups cg JOIN services s ON s.id=cg.service_id "
        "JOIN content_items ci ON ci.content_group_id=cg.id AND ci.status='draft' "
        "WHERE cg.entry_type='service' AND s.code=?",
        (decision.target["target_group"],),
    ).fetchone()


def _service_merge_draft(db, source_row, target_row):
    current = publishing_repository.load_content_draft(db, target_row["content_id"])
    summary = _safe_legacy_text(
        source_row["description"], current.summary, 300
    )
    merged_block = ContentBlock(
        "rich_text",
        title="旧版服务内容审阅合并",
        body_html=_body_from_legacy(
            source_row, ("description", "pain_point", "timeline")
        ),
        settings={},
        sort_order=len(current.blocks),
    )
    return replace(current, summary=summary, blocks=current.blocks + (merged_block,))


def _validated_mapping(
    db,
    source_table,
    source_id,
    *,
    require_draft=False,
    expected_service_code=None,
):
    mapping = db.execute(
        "SELECT m.*,ci.content_group_id AS actual_group_id,ci.entry_type AS item_type,"
        "ci.status AS item_status,cg.entry_type AS group_type,s.code AS service_code "
        "FROM legacy_content_mappings m "
        "LEFT JOIN content_items ci ON ci.id=m.target_content_item_id "
        "LEFT JOIN content_groups cg ON cg.id=m.target_content_group_id "
        "LEFT JOIN services s ON s.id=cg.service_id "
        "WHERE m.source_table=? AND m.source_id=?",
        (source_table, source_id),
    ).fetchone()
    if mapping is None:
        return None, None
    expected_type = {
        "services": "service",
        "cases": "case",
        "articles": "resource",
        "announcements": "announcement",
    }[source_table]
    if (
        mapping["actual_group_id"] != mapping["target_content_group_id"]
        or mapping["item_type"] != expected_type
        or mapping["group_type"] != expected_type
        or (require_draft and mapping["item_status"] != "draft")
    ):
        return mapping, "mapping_invalid"
    if source_table == "services" and (
        expected_service_code not in SERVICE_GROUPS
        or mapping["service_code"] != expected_service_code
    ):
        return mapping, "service_mapping_invalid"
    return mapping, None


def _review_gate(db, decision, now):
    source_row = _source_row_by_identity(
        db, decision.source_table, decision.source_id
    )
    if source_row is None:
        return None, None, "source_changed"
    current_checksum = _canonical_checksum(decision.source_table, source_row)
    review = db.execute(
        "SELECT * FROM legacy_content_reviews WHERE source_table=? AND source_id=?",
        (decision.source_table, decision.source_id),
    ).fetchone()
    if review is None:
        return source_row, None, "unreviewed"
    if review["source_checksum"] != current_checksum:
        return source_row, review, "source_changed"
    if decision.source_checksum != review["source_checksum"]:
        return source_row, review, "decision_stale"
    if review["decision_source_checksum"] is not None:
        if (
            review["decision_source_checksum"] == decision.source_checksum
            and review["decision_action"] != decision.action
        ):
            return source_row, review, "decision_conflict"
    required = json.loads(review["required_confirmations_json"] or "[]")
    if (
        type(required) is not list
        or any(type(code) is not str for code in required)
        or len(required) != len(set(required))
        or set(required) != set(decision.confirmations)
    ):
        return source_row, review, "confirmations_incomplete"
    if decision.action != CONVERTIBLE_ACTIONS[decision.source_table]:
        return source_row, review, "action_not_convertible"
    if review["source_state"] == "unchecked" or review["source_check_code"] is None:
        return source_row, review, "source_unchecked"
    if review["check_source_checksum"] != decision.source_checksum:
        return source_row, review, "source_check_stale"
    expected_pair = (
        ("reachable", "https_ok")
        if decision.source_table == "articles"
        else ("missing", "source_missing")
    )
    if (review["source_state"], review["source_check_code"]) != expected_pair:
        return source_row, review, "source_not_allowed"
    try:
        if not _exact_timestamp(review["source_checked_at"]) or not _exact_timestamp(
            review["source_check_expires_at"]
        ):
            raise ValueError("invalid source check timestamp")
        checked = parse_shanghai(review["source_checked_at"])
        expiry = parse_shanghai(review["source_check_expires_at"])
    except (TypeError, ValueError):
        return source_row, review, "source_check_stale"
    current = as_shanghai(now)
    if (
        checked > current
        or expiry < current
        or expiry - checked != SOURCE_CHECK_TTL
    ):
        return source_row, review, "source_check_stale"
    if review["target_type"] != {
        "services": "service",
        "cases": "case",
        "articles": "resource",
        "announcements": "announcement",
    }[decision.source_table]:
        return source_row, review, "review_target_invalid"
    return source_row, review, None


@dataclass(frozen=True)
class _PreparedMigration:
    item: LegacyMigrationItem
    draft: ContentDraft | None = None
    mode: str | None = None


def _migration_item(decision, status, **kwargs):
    return LegacyMigrationItem(
        decision.source_table, decision.source_id, status, **kwargs
    )


def _prepare_decision(db, decision, now, *, require_merge_approval):
    source_row = _source_row_by_identity(
        db, decision.source_table, decision.source_id
    )
    if source_row is None:
        return _PreparedMigration(_migration_item(decision, "source_changed"))
    current_checksum = _canonical_checksum(decision.source_table, source_row)
    expected_service_code = (
        decision.target.get("target_group")
        if decision.source_table == "services"
        else None
    )
    mapping, mapping_error = _validated_mapping(
        db,
        decision.source_table,
        decision.source_id,
        expected_service_code=expected_service_code,
    )
    if mapping is not None:
        if mapping["source_checksum"] != current_checksum:
            return _PreparedMigration(_migration_item(decision, "source_changed"))
        if decision.source_checksum != current_checksum:
            return _PreparedMigration(_migration_item(decision, "decision_stale"))
        if mapping_error:
            return _PreparedMigration(_migration_item(decision, mapping_error))
        if decision.source_table == "services":
            review_target = db.execute(
                "SELECT target_group FROM legacy_content_reviews "
                "WHERE source_table='services' AND source_id=?",
                (decision.source_id,),
            ).fetchone()
            if (
                source_row["code"] != expected_service_code
                or review_target is None
                or review_target["target_group"] != expected_service_code
            ):
                return _PreparedMigration(
                    _migration_item(decision, "service_mapping_invalid")
                )
        item = db.execute(
            "SELECT lock_version FROM content_items WHERE id=?",
            (mapping["target_content_item_id"],),
        ).fetchone()
        return _PreparedMigration(
            _migration_item(
                decision,
                "already_mapped",
                target_content_id=mapping["target_content_item_id"],
                target_content_group_id=mapping["target_content_group_id"],
                target_lock_version=item["lock_version"] if item is not None else None,
            )
        )
    if mapping_error:
        return _PreparedMigration(_migration_item(decision, mapping_error))
    source_row, review, error = _review_gate(db, decision, now)
    if error:
        return _PreparedMigration(_migration_item(decision, error))
    try:
        if decision.source_table == "services":
            if review["target_group"] not in SERVICE_GROUPS or decision.target[
                "target_group"
            ] != review["target_group"]:
                return _PreparedMigration(
                    _migration_item(decision, "service_mapping_invalid")
                )
            target = _service_target(db, decision)
            if target is None:
                return _PreparedMigration(
                    _migration_item(decision, "target_draft_missing")
                )
            approved = set(decision.target) == {
                "target_group",
                "target_content_id",
                "expected_lock_version",
                "merge_approved",
            }
            preview = MappingProxyType(
                {
                    "kind": "service_narrative_merge",
                    "changes": ("summary", "review_block"),
                }
            )
            if not approved:
                status = "merge_not_approved" if require_merge_approval else "target_draft_exists"
                return _PreparedMigration(
                    _migration_item(
                        decision,
                        status,
                        target_content_id=target["content_id"],
                        target_content_group_id=target["group_id"],
                        target_lock_version=target["lock_version"],
                        preview=preview,
                    )
                )
            if (
                decision.target["target_content_id"] != target["content_id"]
                or decision.target["expected_lock_version"] != target["lock_version"]
            ):
                return _PreparedMigration(
                    _migration_item(decision, "stale_lock_version")
                )
            draft = validate_content_draft(_service_merge_draft(db, source_row, target))
            return _PreparedMigration(
                _migration_item(
                    decision,
                    "ready",
                    target_content_id=target["content_id"],
                    target_content_group_id=target["group_id"],
                    target_lock_version=target["lock_version"],
                    preview=preview,
                ),
                draft,
                "merge",
            )
        if decision.source_table == "articles":
            draft = _article_draft(source_row, decision)
        elif decision.source_table == "announcements":
            valid_from = parse_shanghai(decision.target["valid_from"])
            valid_until = parse_shanghai(decision.target["valid_until"])
            current = as_shanghai(now)
            if not valid_from <= current <= valid_until:
                return _PreparedMigration(
                    _migration_item(decision, "announcement_not_current")
                )
            draft = _announcement_draft(source_row, decision)
        else:
            draft = _case_draft(source_row, decision, now)
        draft = validate_content_draft(draft)
        collision = db.execute(
            "SELECT 1 FROM content_groups WHERE entry_type=? AND canonical_slug=?",
            (draft.entry_type, draft.slug),
        ).fetchone()
        if collision is not None:
            return _PreparedMigration(_migration_item(decision, "target_conflict"))
        return _PreparedMigration(
            _migration_item(
                decision,
                "ready",
                preview=MappingProxyType(
                    {
                        "entry_type": draft.entry_type,
                        "slug": draft.slug,
                        "status": "draft",
                    }
                ),
            ),
            draft,
            "insert",
        )
    except ContentValidationError as error:
        stable = (
            "case_evidence_incomplete"
            if decision.source_table == "cases"
            else f"{decision.source_table[:-1]}_draft_invalid"
        )
        if error.code in {
            "source_not_allowed",
            "case_evidence_incomplete",
            "obvious_pii_detected",
        }:
            stable = error.code
        return _PreparedMigration(_migration_item(decision, stable))


def preview_legacy_decisions(db, decisions, *, now):
    """Validate decisions and return safe previews without opening a write transaction."""
    if db.in_transaction:
        raise RuntimeError("preview requires a transaction-free connection")
    decisions = _validated_decision_sequence(decisions)
    return LegacyMigrationResult(
        tuple(
            _prepare_decision(
                db, decision, now, require_merge_approval=False
            ).item
            for decision in decisions
        )
    )


def _insert_mapping(
    db, decision, target_content_group_id, target_content_item_id, now_text
):
    db.execute(
        "INSERT INTO legacy_content_mappings "
        "(source_table,source_id,source_checksum,target_content_group_id,"
        "target_content_item_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
        (
            decision.source_table,
            decision.source_id,
            decision.source_checksum,
            target_content_group_id,
            target_content_item_id,
            now_text,
            now_text,
        ),
    )


def _write_migration_audit(db, content_id, decision, actor, now):
    publishing_repository.write_audit_event(
        db,
        content_id,
        "legacy_content_migrated",
        actor,
        now,
        {
            "source_table": decision.source_table,
            "source_id": decision.source_id,
        },
    )


def apply_legacy_decisions(db, decisions, *, actor, now):
    """Apply each approved conversion in its own rollback-safe immediate transaction."""
    if db.in_transaction:
        raise RuntimeError("legacy conversion requires a transaction-free connection")
    if not _exact_nonblank(actor, 200):
        raise ValueError("invalid migration actor")
    decisions = _validated_decision_sequence(decisions)
    now_text = format_shanghai(as_shanghai(now))
    results = []
    for decision in decisions:
        try:
            db.execute("BEGIN IMMEDIATE")
            prepared = _prepare_decision(
                db, decision, now, require_merge_approval=True
            )
            if prepared.item.status == "already_mapped":
                db.rollback()
                results.append(prepared.item)
                continue
            if prepared.item.status != "ready" or prepared.draft is None:
                db.rollback()
                results.append(prepared.item)
                continue
            db.execute(
                "UPDATE legacy_content_reviews SET decision_action=?,decision_at=?,"
                "decision_source_checksum=?,updated_at=? "
                "WHERE source_table=? AND source_id=? AND source_checksum=?",
                (
                    decision.action,
                    now_text,
                    decision.source_checksum,
                    now_text,
                    decision.source_table,
                    decision.source_id,
                    decision.source_checksum,
                ),
            )
            if prepared.mode == "merge":
                content_id = prepared.item.target_content_id
                publishing_repository.update_content_draft(
                    db,
                    content_id,
                    prepared.item.target_lock_version,
                    prepared.draft,
                    actor=actor,
                    now=now,
                )
                group_id = prepared.item.target_content_group_id
            else:
                content_id = publishing_repository.insert_content_draft(
                    db, prepared.draft, actor=actor, now=now
                )
                target_item = db.execute(
                    "SELECT content_group_id FROM content_items WHERE id=?",
                    (content_id,),
                ).fetchone()
                group_id = target_item["content_group_id"]
            _insert_mapping(db, decision, group_id, content_id, now_text)
            mapping, mapping_error = _validated_mapping(
                db,
                decision.source_table,
                decision.source_id,
                require_draft=True,
                expected_service_code=(
                    decision.target.get("target_group")
                    if decision.source_table == "services"
                    else None
                ),
            )
            if mapping_error or mapping is None:
                raise ContentValidationError("mapping_invalid")
            _write_migration_audit(db, content_id, decision, actor, now)
            lock = db.execute(
                "SELECT lock_version FROM content_items WHERE id=?", (content_id,)
            ).fetchone()["lock_version"]
            db.commit()
            results.append(
                _migration_item(
                    decision,
                    "migrated",
                    target_content_id=content_id,
                    target_content_group_id=group_id,
                    target_lock_version=lock,
                    preview=prepared.item.preview,
                )
            )
        except ContentValidationError as error:
            db.rollback()
            results.append(_migration_item(decision, error.code))
        except Exception:
            db.rollback()
            results.append(_migration_item(decision, "migration_failed"))
    return LegacyMigrationResult(tuple(results))


def migration_result_to_jsonl(result):
    if not isinstance(result, LegacyMigrationResult):
        raise TypeError("result must be a LegacyMigrationResult")
    lines = []
    for item in result.items:
        payload = {
            "source_table": item.source_table,
            "source_id": item.source_id,
            "status": item.status,
            "target_content_id": item.target_content_id,
            "target_content_group_id": item.target_content_group_id,
            "target_lock_version": item.target_lock_version,
            "preview": dict(item.preview) if item.preview is not None else None,
        }
        lines.append(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    return "\n".join(lines)


def check_result_to_lines(result):
    if not isinstance(result, LegacyCheckResult):
        raise TypeError("result must be a LegacyCheckResult")
    return tuple(
        f"source_table={item.source_table} source_id={item.source_id} "
        f"state={item.state} code={item.code}"
        for item in result.items
    )
