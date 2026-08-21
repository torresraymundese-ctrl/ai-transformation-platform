"""Privacy-safe persistence for allowlisted conversion events."""

import hashlib
import ipaddress
import json
import re
import secrets
import unicodedata
from datetime import datetime

from flask import session

from assessment.reporting import YEAR_1_BY_MATURITY
from assessment.seed import load_core_catalog_manifest
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
MATURITY_CODES = frozenset(YEAR_1_BY_MATURITY)
PUBLIC_PAGE_CODES = frozenset(
    {
        "about",
        "article",
        "assessment",
        "cases",
        "error",
        "home",
        "insights",
        "report",
        "services",
        "site",
    }
)
PUBLIC_SOURCE_CODES = frozenset(
    {"footer", "service_packages", "website_assessment"}
)
_CORE_CATALOG_MANIFEST = load_core_catalog_manifest()
SUBBRANCH_CODES_BY_BRANCH = {
    industry["code"]: frozenset(industry["subbranches"])
    for industry in _CORE_CATALOG_MANIFEST["industries"]
}
DEPARTMENT_CODES_BY_BRANCH = {
    industry["code"]: frozenset(industry["departments"])
    for industry in _CORE_CATALOG_MANIFEST["industries"]
}
SUBBRANCH_CODES = frozenset().union(*SUBBRANCH_CODES_BY_BRANCH.values())
DEPARTMENT_CODES = frozenset().union(*DEPARTMENT_CODES_BY_BRANCH.values())
EXACT_CODE_DOMAINS = {
    "step": ASSESSMENT_STEPS,
    "branch_code": BRANCH_CODES,
    "subbranch_code": SUBBRANCH_CODES,
    "department_code": DEPARTMENT_CODES,
    "maturity_code": MATURITY_CODES,
    "scenario_code": SCENARIO_CODES,
    "source": PUBLIC_SOURCE_CODES,
    "page": PUBLIC_PAGE_CODES,
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
IP_CANDIDATE = re.compile(r"(?i)(?<![0-9a-f:.])[0-9a-f:.]{2,}(?![0-9a-f:.])")
IP_SEPARATOR_TRANSLATION = str.maketrans(
    {"。": ".", "｡": ".", "：": ":", "∶": ":"}
)


CLIENT_EVENT_SCHEMAS = {
    "home_viewed": {
        "required": frozenset({"page"}),
        "allowed": frozenset({"page"}),
        "domains": {"page": frozenset({"home"})},
    },
    "assessment_started": {
        "required": frozenset({"branch_code", "page", "source"}),
        "allowed": frozenset({"branch_code", "page", "source"}),
        "domains": {
            "page": frozenset({"assessment"}),
            "source": frozenset({"website_assessment"}),
        },
    },
    "assessment_step_completed": {
        "required": frozenset(
            {
                "step",
                "branch_code",
                "subbranch_code",
                "department_code",
                "page",
                "source",
            }
        ),
        "allowed": frozenset(
            {
                "step",
                "branch_code",
                "subbranch_code",
                "department_code",
                "page",
                "source",
            }
        ),
        "domains": {
            "page": frozenset({"assessment"}),
            "source": frozenset({"website_assessment"}),
        },
    },
    "service_inquiry_clicked": {
        "required": frozenset({"page", "source"}),
        "allowed": frozenset({"page", "source"}),
        "domains": {
            "page": frozenset({"services"}),
            "source": frozenset({"service_packages"}),
        },
    },
    "wechat_clicked": {
        "required": frozenset({"page", "source"}),
        "allowed": frozenset({"page", "source"}),
        "domains": {
            "page": PUBLIC_PAGE_CODES,
            "source": frozenset({"footer"}),
        },
    },
    "phone_clicked": {
        "required": frozenset({"page", "source"}),
        "allowed": frozenset({"page", "source"}),
        "domains": {
            "page": PUBLIC_PAGE_CODES,
            "source": frozenset({"footer"}),
        },
    },
}


def parse_client_event_payload(data):
    if not isinstance(data, dict) or set(data) != {"event_name", "metadata"}:
        raise ValidationError("invalid event payload")
    event_name = data["event_name"]
    if not isinstance(event_name, str) or event_name not in CLIENT_EVENTS:
        raise ValidationError("invalid event payload")
    return event_name, validate_client_event_metadata(event_name, data["metadata"])


def validate_client_event_metadata(event_name, metadata):
    schema = CLIENT_EVENT_SCHEMAS.get(event_name)
    if schema is None:
        raise ValidationError("invalid event payload")
    normalized = validate_metadata(metadata)
    keys = set(normalized)
    if not schema["required"] <= keys or not keys <= schema["allowed"]:
        raise ValidationError("invalid event payload")
    for key, domain in schema["domains"].items():
        if normalized.get(key) not in domain:
            raise ValidationError("invalid event payload")
    branch_code = normalized.get("branch_code")
    if branch_code is not None:
        if (
            "subbranch_code" in normalized
            and normalized["subbranch_code"]
            not in SUBBRANCH_CODES_BY_BRANCH[branch_code]
        ):
            raise ValidationError("invalid event payload")
        if (
            "department_code" in normalized
            and normalized["department_code"]
            not in DEPARTMENT_CODES_BY_BRANCH[branch_code]
        ):
            raise ValidationError("invalid event payload")
    return normalized


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
    if assessment_id is None:
        if not isinstance(event_name, str) or event_name not in CLIENT_EVENTS:
            raise ValidationError("invalid event payload")
        client_metadata = {} if metadata is None else metadata
        if branch_code is not None:
            if not isinstance(client_metadata, dict):
                raise ValidationError("invalid event payload")
            client_metadata = {**client_metadata, "branch_code": branch_code}
        normalized = validate_client_event_metadata(event_name, client_metadata)
        branch_code = normalized.pop("branch_code", None)
    elif (
        not isinstance(event_name, str)
        or event_name not in SERVER_EVENTS
        or type(assessment_id) is not int
        or assessment_id < 1
        or branch_code is not None
        or (metadata is not None and metadata != {})
    ):
        raise ValidationError("invalid event payload")
    else:
        normalized = {}
        branch_code = None

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


def insert_server_event(
    db, event_name: str, assessment_id: int, *, created_at=None
) -> None:
    if (
        not isinstance(event_name, str)
        or event_name not in SERVER_EVENTS
        or type(assessment_id) is not int
        or assessment_id < 1
    ):
        raise ValidationError("event_name has an invalid value")
    if created_at is not None and not isinstance(created_at, datetime):
        raise ValidationError("event_name has an invalid value")
    _insert_event(
        db,
        event_name,
        assessment_id,
        session_analytics_id_hash(),
        None,
        {},
        created_at=created_at,
    )


def _insert_event(
    db,
    event_name,
    assessment_id,
    analytics_id_hash,
    branch_code,
    metadata,
    *,
    created_at=None,
):
    parameters = (
        event_name,
        assessment_id,
        analytics_id_hash,
        branch_code,
        json.dumps(
            metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ),
    )
    if created_at is None:
        db.execute(
            "INSERT OR IGNORE INTO analytics_events "
            "(event_name,assessment_id,analytics_id_hash,branch_code,metadata_json) "
            "VALUES (?,?,?,?,?)",
            parameters,
        )
        return
    timestamp = created_at.replace(microsecond=0).isoformat(sep=" ")
    db.execute(
        "INSERT OR IGNORE INTO analytics_events "
        "(event_name,assessment_id,analytics_id_hash,branch_code,metadata_json,"
        "created_at) VALUES (?,?,?,?,?,?)",
        (*parameters, timestamp),
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
    canonical = value.translate(IP_SEPARATOR_TRANSLATION)
    for match in IP_CANDIDATE.finditer(canonical):
        candidate = match.group(0)
        if candidate.count(".") != 3 and candidate.count(":") < 2:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return True
    return False
