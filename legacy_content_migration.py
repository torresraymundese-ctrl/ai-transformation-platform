"""Deterministic, local-only inventory for legacy public content.

This module classifies old rows and records review artifacts. It deliberately
does not fetch source URLs, create V2 content, publish, or delete source rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
from typing import Literal, Mapping
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo


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


def current_shanghai_datetime() -> datetime:
    return datetime.now(SHANGHAI).replace(tzinfo=None, microsecond=0)


def _timestamp() -> str:
    return current_shanghai_datetime().strftime("%Y-%m-%d %H:%M:%S")


def _load_mapping_rules() -> dict[str, object]:
    try:
        raw = json.loads(MAPPING_RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid legacy content mapping rules") from exc
    if not isinstance(raw, dict) or set(raw) != _RULE_KEYS or raw.get("version") != 1:
        raise ValueError("invalid legacy content mapping rules")
    if set(raw.get("allowed_source_tables", ())) != set(SOURCE_TABLES):
        raise ValueError("invalid legacy content mapping rules source tables")
    if set(raw.get("allowed_target_types", ())) != set(TARGET_TYPES):
        raise ValueError("invalid legacy content mapping rules target types")
    if set(raw.get("allowed_target_groups", ())) != set(SERVICE_GROUPS):
        raise ValueError("invalid legacy content mapping rules target groups")
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
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if any(ord(char) < 32 for char in candidate) or "\\" in candidate:
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
    try:
        ascii_host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if ascii_host == "localhost" or ascii_host.endswith(".localhost"):
        return None
    try:
        ip = ipaddress.ip_address(ascii_host)
    except ValueError:
        if "." not in ascii_host or any(not label for label in ascii_host.split(".")):
            return None
    else:
        if not ip.is_global:
            return None
        if ip.version == 6:
            ascii_host = f"[{ascii_host}]"
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    authority = ascii_host if port is None or default_port else f"{ascii_host}:{port}"
    display = urlunsplit((scheme, authority, parsed.path or "", "", ""))
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
    if not isinstance(item.source_id, int) or item.source_id <= 0:
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
