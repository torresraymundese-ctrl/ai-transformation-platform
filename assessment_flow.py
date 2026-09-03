"""Bounded Session credentials for exact rule and legal assessment versions."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
import secrets
import sqlite3

from content_clock import as_shanghai
from assessment_validation import BRANCH_CODES
from legal_repository import (
    LegalBundle,
    LegalVersionIds,
    load_active_legal_bundle,
    load_legal_bundle,
)
from models import get_db
from rule_release_runtime import (
    RuleBundle,
    load_active_rule_bundle,
    load_rule_bundle,
)


FLOW_TTL = timedelta(hours=24)
MAX_LIVE_FLOWS = 8
MAX_FLOW_ID_ATTEMPTS = 8
FLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32}$")
_SESSION_KEY = "assessment_flows"
_RECORD_KEYS = frozenset(
    {
        "branch",
        "rule_version_id",
        "privacy_id",
        "terms_id",
        "roi_disclaimer_id",
        "ai_notice_id",
        "issued_at",
    }
)


class AssessmentFlowError(ValueError):
    """A generic failure for unknown, expired, or inconsistent flow credentials."""


@dataclass(frozen=True)
class IssuedFlow:
    flow_id: str
    branch_code: str
    rule_version_id: int
    privacy_id: int
    terms_id: int
    roi_disclaimer_id: int
    ai_notice_id: int
    issued_at: datetime
    _rule_bundle: RuleBundle | None = field(default=None, repr=False, compare=False)
    _legal_bundle: LegalBundle | None = field(default=None, repr=False, compare=False)

    @property
    def rule_bundle(self) -> RuleBundle:
        if self._rule_bundle is None:
            raise AssessmentFlowError("invalid assessment flow")
        return self._rule_bundle

    @property
    def legal_bundle(self) -> LegalBundle:
        if self._legal_bundle is None:
            raise AssessmentFlowError("invalid assessment flow")
        return self._legal_bundle


def issue_config_flow(session, branch_code: str, now: datetime) -> IssuedFlow:
    """Issue one flow while this owner manages its single database connection."""
    db = get_db()
    try:
        return issue_assessment_flow(db, session, branch_code, now)
    finally:
        db.close()


def load_issued_flow_bundles(flow: IssuedFlow) -> tuple[RuleBundle, LegalBundle]:
    """Load a flow's exact historical rule/legal bundles in one read transaction."""
    if type(flow) is not IssuedFlow:
        raise AssessmentFlowError("invalid assessment flow")
    db = get_db()
    try:
        db.execute("BEGIN")
        rule = load_rule_bundle(db, flow.rule_version_id, flow.branch_code)
        legal = load_legal_bundle(
            db,
            LegalVersionIds(
                privacy=flow.privacy_id,
                terms=flow.terms_id,
                roi_disclaimer=flow.roi_disclaimer_id,
                ai_content_notice=flow.ai_notice_id,
            ),
        )
        db.commit()
        return rule, legal
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def issue_assessment_flow(
    db: sqlite3.Connection, session, branch_code: str, now: datetime
) -> IssuedFlow:
    """Read one consistent active rule/legal snapshot, then store its Session nonce."""
    if (
        not isinstance(db, sqlite3.Connection)
        or not hasattr(session, "get")
        or not hasattr(session, "__setitem__")
        or type(branch_code) is not str
        or db.in_transaction
    ):
        raise AssessmentFlowError("invalid assessment flow")
    moment = _moment(now)
    try:
        db.execute("BEGIN")
        rule = load_active_rule_bundle(db, branch_code)
        legal = load_active_legal_bundle(db, moment)
        db.commit()
    except Exception:
        db.rollback()
        raise

    records = _live_records(session.get(_SESSION_KEY), moment)
    flow_id = _unique_flow_id(records)
    issued = IssuedFlow(
        flow_id=flow_id,
        branch_code=branch_code,
        rule_version_id=rule.version_id,
        privacy_id=legal.privacy.id,
        terms_id=legal.terms.id,
        roi_disclaimer_id=legal.roi_disclaimer.id,
        ai_notice_id=legal.ai_content_notice.id,
        issued_at=moment,
        _rule_bundle=rule,
        _legal_bundle=legal,
    )
    while len(records) >= MAX_LIVE_FLOWS:
        oldest = min(
            enumerate(records.items()),
            key=lambda item: (_record_moment(item[1][1]), item[0]),
        )[1][0]
        del records[oldest]
    records[flow_id] = _record(issued)
    session[_SESSION_KEY] = records
    return issued


def require_assessment_flow(
    session, flow_id: str, branch_code: str, now: datetime
) -> IssuedFlow:
    """Return one unexpired exact binding or raise the same generic failure."""
    moment = _moment(now)
    if (
        not hasattr(session, "get")
        or type(flow_id) is not str
        or FLOW_ID_PATTERN.fullmatch(flow_id) is None
        or type(branch_code) is not str
    ):
        raise AssessmentFlowError("invalid assessment flow")
    records = _live_records(session.get(_SESSION_KEY), moment)
    if hasattr(session, "__setitem__"):
        session[_SESSION_KEY] = records
    value = records.get(flow_id)
    try:
        if type(value) is not dict or set(value) != _RECORD_KEYS:
            raise AssessmentFlowError("invalid assessment flow")
        if value["branch"] != branch_code:
            raise AssessmentFlowError("invalid assessment flow")
        ids = tuple(
            value[name]
            for name in (
                "rule_version_id",
                "privacy_id",
                "terms_id",
                "roi_disclaimer_id",
                "ai_notice_id",
            )
        )
        if any(type(item) is not int or item <= 0 for item in ids):
            raise AssessmentFlowError("invalid assessment flow")
        issued_at = _record_moment(value)
        return IssuedFlow(
            flow_id=flow_id,
            branch_code=branch_code,
            rule_version_id=ids[0],
            privacy_id=ids[1],
            terms_id=ids[2],
            roi_disclaimer_id=ids[3],
            ai_notice_id=ids[4],
            issued_at=issued_at,
        )
    except (KeyError, TypeError, ValueError):
        raise AssessmentFlowError("invalid assessment flow") from None


def _record(flow):
    return {
        "branch": flow.branch_code,
        "rule_version_id": flow.rule_version_id,
        "privacy_id": flow.privacy_id,
        "terms_id": flow.terms_id,
        "roi_disclaimer_id": flow.roi_disclaimer_id,
        "ai_notice_id": flow.ai_notice_id,
        "issued_at": flow.issued_at.isoformat(),
    }


def _live_records(value, now):
    if type(value) is not dict:
        return {}
    records = {}
    for flow_id, record in value.items():
        try:
            issued_at = _record_moment(record)
            if (
                type(flow_id) is str
                and FLOW_ID_PATTERN.fullmatch(flow_id) is not None
                and type(record) is dict
                and set(record) == _RECORD_KEYS
                and record["branch"] in BRANCH_CODES
                and all(
                    type(record[name]) is int and record[name] > 0
                    for name in (
                        "rule_version_id",
                        "privacy_id",
                        "terms_id",
                        "roi_disclaimer_id",
                        "ai_notice_id",
                    )
                )
                and now - issued_at <= FLOW_TTL
                and issued_at <= now
            ):
                records[flow_id] = dict(record)
        except (KeyError, TypeError, ValueError):
            continue
    return records


def _unique_flow_id(records):
    for _ in range(MAX_FLOW_ID_ATTEMPTS):
        candidate = secrets.token_urlsafe(24)
        if (
            type(candidate) is str
            and FLOW_ID_PATTERN.fullmatch(candidate) is not None
            and candidate not in records
        ):
            return candidate
    raise AssessmentFlowError("invalid assessment flow")


def _record_moment(record):
    value = record["issued_at"]
    if type(value) is not str:
        raise ValueError("invalid assessment flow")
    return _moment(datetime.fromisoformat(value))


def _moment(value):
    try:
        return as_shanghai(value)
    except (TypeError, ValueError):
        raise AssessmentFlowError("invalid assessment flow") from None
