"""Sole test adapter for governed assessment-flow credentials."""

from datetime import datetime

from content_clock import SHANGHAI
from assessment_flow import issue_assessment_flow
from legal_repository import (
    confirm_legal_review,
    create_legal_draft,
    publish_legal_version,
)
import models


FLOW_NOW = datetime(2026, 9, 3, 10, 0, 0, tzinfo=SHANGHAI)
LEGAL_TYPES = ("privacy", "terms", "roi_disclaimer", "ai_content_notice")


def publish_test_legal_bundle(*, suffix="v1", now=FLOW_NOW):
    """Publish four clearly test-only reviewed internal legal documents."""
    ids = {}
    for document_type in LEGAL_TYPES:
        version_id = create_legal_draft(
            document_type=document_type,
            version_code=f"test-{document_type}-{suffix}",
            title=f"TEST ONLY {document_type}",
            body_summary=f"TEST ONLY {document_type} summary",
            body_html=f"<p>TEST ONLY {document_type} body</p>",
            effective_at=now,
            actor="test-admin",
            now=now,
        )
        lock_version = confirm_legal_review(
            version_id,
            expected_lock_version=1,
            actor="test-admin",
            now=now,
        )
        publish_legal_version(
            version_id,
            lock_version,
            actor="test-admin",
            now=now,
        )
        ids[document_type] = version_id
    return ids


def ensure_test_legal_bundle(*, now=FLOW_NOW):
    """Return the active test bundle, publishing it once for a fresh fixture DB."""
    db = models.get_db()
    try:
        active = {
            row["document_type"]: row["legal_document_id"]
            for row in db.execute(
                "SELECT a.document_type,a.legal_document_id "
                "FROM active_legal_documents a JOIN legal_documents d "
                "ON d.id=a.legal_document_id WHERE d.mode='internal' "
                "AND d.status='published' "
                "AND d.reviewed_content_sha256=d.content_sha256"
            )
        }
    finally:
        db.close()
    return active if set(active) == set(LEGAL_TYPES) else publish_test_legal_bundle(now=now)


def issue_real_config_flow(client, branch_code="manufacturing", *, now=FLOW_NOW):
    """Issue one real config response and require its public flow credential."""
    client.application.config.update(
        PRIVACY_PROCESSOR_NAME="测试处理者",
        PRIVACY_CONTACT="privacy@test.example",
        PRIVACY_POLICY_URL="https://test.example/legal/privacy/test-privacy-v1",
        ASSESSMENT_FLOW_NOW_PROVIDER=lambda: now,
    )
    response = client.get(f"/api/v2/assessment/config/{branch_code}")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload.get("flow_id"), str)
    return payload


def issue_test_service_flow(branch_code="manufacturing", *, now=FLOW_NOW):
    """Issue the same real governed binding for direct service-level tests."""
    ensure_test_legal_bundle(now=now)

    db = models.get_db()
    try:
        return issue_assessment_flow(db, {}, branch_code, now)
    finally:
        db.close()


def bound_preview_payload(config):
    """Build one exact valid preview from a real governed config response."""
    return {
        "flow_id": config["flow_id"],
        "rule_version": config["rule_version"],
        "schema_version": "2.0",
        "profile": {
            "branch_code": config["branch"]["code"],
            "subbranch_code": config["subbranches"][0]["code"],
            "department_code": config["departments"][0]["code"],
            "company_size_code": config["company_sizes"][0]["code"],
            "pain_codes": [config["pain_points"][0]["code"]],
        },
        "answers": {
            question["code"]: question["options"][-1]["code"]
            for question in config["questions"]
        },
        "roi_choices": {
            group: options[0]
            for group, options in config["roi_options"].items()
        },
    }


def bound_completion_payload(config, *, submission_key):
    """Build one consented completion bound to the config's exact versions."""
    return {
        "flow_id": config["flow_id"],
        "submission_key": submission_key,
        "assessment": {
            key: value
            for key, value in bound_preview_payload(config).items()
            if key != "flow_id"
        },
        "contact": {
            "company_name": "TEST ONLY company",
            "contact_name": "TEST ONLY contact",
            "phone": "13800138000",
            "email": "test@example.invalid",
            "wechat": "",
        },
        "consent": {
            "accepted": True,
            "policy_version": config["consent_policy_version"],
        },
        "attribution": {"source": "task21_test"},
    }
