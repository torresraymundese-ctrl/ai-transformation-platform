"""Privacy-safe persistence for allowlisted conversion events."""

import hashlib
import ipaddress
import json
import re
import secrets
import unicodedata

from flask import session

from assessment_validation import BRANCH_CODES, CODE_PATTERN, SCENARIO_CODES
from models import get_db
from validation import ValidationError


CLIENT_EVENTS = frozenset(
    {
        "home_viewed",
        "assessment_started",
        "assessment_step_completed",
        "service_inquiry_clicked",
        "wechat_clicked",
        "phone_clicked",
    }
)
SERVER_EVENTS = frozenset(
    {
        "assessment_completed",
        "lead_submitted",
        "report_viewed",
        "report_pdf_downloaded",
        "appointment_submitted",
    }
)
ALLOWED_EVENTS = CLIENT_EVENTS | SERVER_EVENTS
METADATA_KEYS = frozenset(
    {
        "step",
        "branch_code",
        "subbranch_code",
        "department_code",
        "maturity_code",
        "scenario_code",
        "source",
        "page",
        "utm_source",
        "utm_medium",
        "utm_campaign",
    }
)
ASSESSMENT_STEPS = frozenset(
    {"profile", "pain", "value_process", "data_systems", "org_delivery", "roi"}
)
MATURITY_CODES = frozenset({"explore", "pilot", "scale", "collaborate"})
EXACT_CODE_DOMAINS = {
    "step": ASSESSMENT_STEPS,
    "branch_code": BRANCH_CODES,
    "maturity_code": MATURITY_CODES,
    "scenario_code": SCENARIO_CODES,
}
STABLE_CODE_FIELDS = frozenset(
    {
        "step",
        "branch_code",
        "subbranch_code",
        "department_code",
        "maturity_code",
        "scenario_code",
    }
)
EMBEDDED_MAINLAND_MOBILE_DIGITS = re.compile(r"(?:86)?1[3-9]\d{9}")
IPV4_CANDIDATE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
IPV6_CANDIDATE = re.compile(
    r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{1,4}:){2,}[0-9a-f:]*[0-9a-f](?![0-9a-f:])"
)


def parse_client_event_payload(data):
    if not isinstance(data, dict) or set(data) != {"event_name", "metadata"}:
        raise ValidationError("invalid event payload")
    event_name = data["event_name"]
    if not isinstance(event_name, str) or event_name not in CLIENT_EVENTS:
        raise ValidationError("invalid event payload")
    return event_name, validate_metadata(data["metadata"])


def validate_metadata(metadata):
    if not isinstance(metadata, dict) or not set(metadata) <= METADATA_KEYS:
        raise ValidationError("invalid event payload")
    normalized = {}
    for key, raw_value in metadata.items():
        if not isinstance(raw_value, str):
            raise ValidationError("invalid event payload")
        value = unicodedata.normalize("NFKC", raw_value).strip()
        if len(value) > 100 or _contains_private_value(value):
            raise ValidationError("invalid event payload")
        if key in STABLE_CODE_FIELDS:
            if CODE_PATTERN.fullmatch(value) is None:
                raise ValidationError("invalid event payload")
            exact_domain = EXACT_CODE_DOMAINS.get(key)
            if exact_domain is not None and value not in exact_domain:
                raise ValidationError("invalid event payload")
        normalized[key] = value
    return normalized


def session_analytics_id_hash():
    """Return only a random Session identifier's SHA-256 hash, when available."""
    try:
        current_hash = session.get("analytics_id_hash")
    except RuntimeError:
        return None
    if isinstance(current_hash, str) and re.fullmatch(r"[0-9a-f]{64}", current_hash):
        return current_hash
    hashed = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    try:
        session["analytics_id_hash"] = hashed
    except RuntimeError:
        return None
    return hashed


def record_event(
    event_name: str,
    *,
    assessment_id=None,
    branch_code=None,
    metadata=None,
):
    normalized = validate_metadata(metadata or {})
    if branch_code is not None:
        normalized["branch_code"] = branch_code
        normalized = validate_metadata(normalized)
    branch_code = normalized.pop("branch_code", None)
    if assessment_id is None:
        if not isinstance(event_name, str) or event_name not in CLIENT_EVENTS:
            raise ValidationError("invalid event payload")
    elif (
        not isinstance(event_name, str)
        or event_name not in SERVER_EVENTS
        or type(assessment_id) is not int
        or assessment_id < 1
    ):
        raise ValidationError("invalid event payload")

    db = get_db()
    try:
        _insert_event(
            db,
            event_name,
            assessment_id,
            session_analytics_id_hash(),
            branch_code,
            normalized,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def insert_server_event(db, event_name: str, assessment_id: int) -> None:
    if (
        not isinstance(event_name, str)
        or event_name not in SERVER_EVENTS
        or type(assessment_id) is not int
        or assessment_id < 1
    ):
        raise ValidationError("event_name has an invalid value")
    _insert_event(
        db,
        event_name,
        assessment_id,
        session_analytics_id_hash(),
        None,
        {},
    )


def _insert_event(
    db,
    event_name,
    assessment_id,
    analytics_id_hash,
    branch_code,
    metadata,
):
    db.execute(
        "INSERT OR IGNORE INTO analytics_events "
        "(event_name,assessment_id,analytics_id_hash,branch_code,metadata_json) "
        "VALUES (?,?,?,?,?)",
        (
            event_name,
            assessment_id,
            analytics_id_hash,
            branch_code,
            json.dumps(
                metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ),
        ),
    )


def _contains_private_value(value):
    if "@" in re.sub(r"\s+", "", value):
        return True
    digits = []
    for character in value:
        digit = unicodedata.decimal(character, None)
        if digit is not None:
            digits.append(str(digit))
    if EMBEDDED_MAINLAND_MOBILE_DIGITS.search("".join(digits)):
        return True
    return _contains_ip_address(value)


def _contains_ip_address(value):
    for pattern in (IPV4_CANDIDATE, IPV6_CANDIDATE):
        for match in pattern.finditer(value):
            try:
                ipaddress.ip_address(match.group(0))
            except ValueError:
                continue
            return True
    return False
