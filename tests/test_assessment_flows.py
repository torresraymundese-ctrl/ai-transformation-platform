"""Assessment flow credentials bind one Session to exact governed versions."""

from datetime import timedelta
from pathlib import Path
import json
import re
import sqlite3

import pytest

from tests.assessment_flow_helpers import (
    FLOW_NOW,
    bound_completion_payload,
    bound_preview_payload,
    issue_real_config_flow,
    publish_test_legal_bundle,
)


FLOW_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32}$")


def test_config_issues_192_bit_flow_bound_to_rule_and_four_legal_versions(client):
    legal_ids = publish_test_legal_bundle()
    client.application.config.update(
        PRIVACY_PROCESSOR_NAME="测试处理者",
        PRIVACY_CONTACT="privacy@test.example",
        PRIVACY_POLICY_URL="https://test.example/legal/privacy/test-privacy-v1",
        ASSESSMENT_FLOW_NOW_PROVIDER=lambda: FLOW_NOW,
    )

    response = client.get("/api/v2/assessment/config/manufacturing")

    assert response.status_code == 200
    payload = response.get_json()
    assert FLOW_TOKEN.fullmatch(payload["flow_id"])
    with client.session_transaction() as browser_session:
        stored = browser_session["assessment_flows"][payload["flow_id"]]
    assert stored == {
        "branch": "manufacturing",
        "rule_version_id": 1,
        "privacy_id": legal_ids["privacy"],
        "terms_id": legal_ids["terms"],
        "roi_disclaimer_id": legal_ids["roi_disclaimer"],
        "ai_notice_id": legal_ids["ai_content_notice"],
        "issued_at": FLOW_NOW.isoformat(),
    }


def test_require_assessment_flow_rejects_expired_and_branch_mismatched_tokens():
    from assessment_flow import require_assessment_flow

    browser_session = {
        "assessment_flows": {
            "A" * 32: {
                "branch": "manufacturing",
                "rule_version_id": 7,
                "privacy_id": 11,
                "terms_id": 12,
                "roi_disclaimer_id": 13,
                "ai_notice_id": 14,
                "issued_at": FLOW_NOW.isoformat(),
            }
        }
    }

    assert require_assessment_flow(
        browser_session, "A" * 32, "manufacturing", FLOW_NOW
    ).rule_version_id == 7
    for branch, now in (
        ("retail_ecommerce", FLOW_NOW),
        ("manufacturing", FLOW_NOW + timedelta(hours=24, seconds=1)),
    ):
        try:
            require_assessment_flow(browser_session, "A" * 32, branch, now)
        except ValueError as error:
            assert str(error) == "invalid assessment flow"
        else:
            raise AssertionError("invalid flow was accepted")


def test_session_keeps_only_eight_independent_live_flows_with_oldest_eviction(
    db, monkeypatch
):
    import assessment_flow

    publish_test_legal_bundle()
    tokens = [f"{index:032d}" for index in range(9)]
    token_iter = iter(tokens)
    monkeypatch.setattr(
        assessment_flow.secrets, "token_urlsafe", lambda _bytes: next(token_iter)
    )
    browser_session = {}

    for index in range(9):
        issued = assessment_flow.issue_assessment_flow(
            db,
            browser_session,
            "manufacturing",
            FLOW_NOW + timedelta(seconds=index),
        )
        assert issued.flow_id == tokens[index]

    assert tuple(browser_session["assessment_flows"]) == tuple(tokens[1:])
    assert len(browser_session["assessment_flows"]) == 8


@pytest.mark.parametrize(
    ("field", "invalid"),
    (
        ("branch", ""),
        ("rule_version_id", 0),
        ("privacy_id", False),
        ("terms_id", -1),
        ("roi_disclaimer_id", "13"),
        ("ai_notice_id", None),
    ),
)
def test_flow_cleanup_removes_records_with_invalid_branch_or_version_ids(
    field, invalid
):
    from assessment_flow import require_assessment_flow

    good_token = "A" * 32
    bad_token = "B" * 32
    record = {
        "branch": "manufacturing",
        "rule_version_id": 7,
        "privacy_id": 11,
        "terms_id": 12,
        "roi_disclaimer_id": 13,
        "ai_notice_id": 14,
        "issued_at": FLOW_NOW.isoformat(),
    }
    invalid_record = dict(record, **{field: invalid})
    browser_session = {
        "assessment_flows": {good_token: record, bad_token: invalid_record}
    }

    assert require_assessment_flow(
        browser_session, good_token, "manufacturing", FLOW_NOW
    ).rule_version_id == 7
    assert browser_session["assessment_flows"] == {good_token: record}


def test_flow_token_collision_retries_before_evicting_the_oldest_valid_record(
    db, monkeypatch
):
    import assessment_flow

    publish_test_legal_bundle()
    tokens = [f"{index:032d}" for index in range(8)]
    records = {
        token: {
            "branch": "manufacturing",
            "rule_version_id": 1,
            "privacy_id": 1,
            "terms_id": 2,
            "roi_disclaimer_id": 3,
            "ai_notice_id": 4,
            "issued_at": (FLOW_NOW + timedelta(seconds=index)).isoformat(),
        }
        for index, token in enumerate(tokens)
    }
    new_token = "N" * 32
    generated = iter((tokens[-1], new_token))
    monkeypatch.setattr(
        assessment_flow.secrets, "token_urlsafe", lambda _bytes: next(generated)
    )
    browser_session = {"assessment_flows": records}

    issued = assessment_flow.issue_assessment_flow(
        db,
        browser_session,
        "manufacturing",
        FLOW_NOW + timedelta(seconds=9),
    )

    assert issued.flow_id == new_token
    assert tuple(browser_session["assessment_flows"]) == (*tokens[1:], new_token)


def test_persistent_flow_token_collision_fails_without_mutating_session(db, monkeypatch):
    import assessment_flow

    publish_test_legal_bundle()
    existing_token = "A" * 32
    record = {
        "branch": "manufacturing",
        "rule_version_id": 1,
        "privacy_id": 1,
        "terms_id": 2,
        "roi_disclaimer_id": 3,
        "ai_notice_id": 4,
        "issued_at": FLOW_NOW.isoformat(),
    }
    browser_session = {"assessment_flows": {existing_token: record}}
    before = {"assessment_flows": {existing_token: dict(record)}}
    monkeypatch.setattr(
        assessment_flow.secrets, "token_urlsafe", lambda _bytes: existing_token
    )

    with pytest.raises(
        assessment_flow.AssessmentFlowError, match="^invalid assessment flow$"
    ):
        assessment_flow.issue_assessment_flow(
            db, browser_session, "manufacturing", FLOW_NOW
        )

    assert browser_session == before


def test_internal_privacy_flow_does_not_require_legacy_policy_url(
    client, monkeypatch
):
    publish_test_legal_bundle()
    client.application.config.update(
        PRIVACY_PROCESSOR_NAME="测试处理者",
        PRIVACY_CONTACT="privacy@test.example",
        PRIVACY_POLICY_URL=None,
        ASSESSMENT_FLOW_NOW_PROVIDER=lambda: FLOW_NOW,
    )

    config_response = client.get("/api/v2/assessment/config/manufacturing")
    assert config_response.status_code == 200
    config = config_response.get_json()
    assert config["privacy_disclosure"]["policy_url"].startswith("/legal/privacy/")
    assert client.post(
        "/api/v2/assessment/preview", json=bound_preview_payload(config)
    ).status_code == 200
    completed = client.post(
        "/api/v2/assessment/complete",
        json=bound_completion_payload(
            config, submission_key="550e8400-e29b-41d4-a716-446655440121"
        ),
        headers={"X-CSRF-Token": config["csrf_token"]},
    )
    assert completed.status_code == 200

    for required_setting in ("PRIVACY_PROCESSOR_NAME", "PRIVACY_CONTACT"):
        monkeypatch.setitem(client.application.config, required_setting, "")
        assert client.get(
            "/api/v2/assessment/config/manufacturing"
        ).status_code == 503
        monkeypatch.setitem(
            client.application.config,
            required_setting,
            "测试处理者" if required_setting.endswith("NAME") else "privacy@test.example",
        )


def test_preview_rejects_unknown_flow_before_rate_quota_and_accepts_real_flow(
    client, monkeypatch
):
    import blueprints.assessment as assessment_blueprint

    publish_test_legal_bundle()
    config = issue_real_config_flow(client)
    valid = bound_preview_payload(config)
    assert client.post("/api/v2/assessment/preview", json=valid).status_code == 200

    monkeypatch.setattr(
        assessment_blueprint,
        "consume_rate_limit",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("quota reached before flow validation")
        ),
    )
    invalid = dict(valid, flow_id="Z" * 32)
    response = client.post("/api/v2/assessment/preview", json=invalid)
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid assessment payload"}


def test_display_rule_version_cannot_select_or_mislabel_flow_history(client):
    publish_test_legal_bundle()
    config = issue_real_config_flow(client)
    payload = bound_preview_payload(config)
    payload["rule_version"] = "forged-display-version"

    response = client.post("/api/v2/assessment/preview", json=payload)

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid assessment payload"}


def test_completion_persists_exact_flow_rule_consent_and_four_legal_versions(client, db):
    publish_test_legal_bundle()
    config = issue_real_config_flow(client)
    payload = bound_completion_payload(
        config, submission_key="550e8400-e29b-41d4-a716-446655440101"
    )

    response = client.post(
        "/api/v2/assessment/complete",
        json=payload,
        headers={"X-CSRF-Token": config["csrf_token"]},
    )

    assert response.status_code == 200
    assessment_id = response.get_json()["assessment_id"]
    assessment = db.execute(
        "SELECT rule_version_id,branch_code FROM assessments WHERE id=?",
        (assessment_id,),
    ).fetchone()
    legal = tuple(
        db.execute(
            "SELECT document_type,legal_version_id FROM assessment_legal_versions "
            "WHERE assessment_id=? ORDER BY document_type",
            (assessment_id,),
        )
    )
    consent = db.execute(
        "SELECT c.policy_version,c.legal_version_id FROM lead_consents c "
        "JOIN assessments a ON a.lead_id=c.lead_id WHERE a.id=?",
        (assessment_id,),
    ).fetchone()
    with client.session_transaction() as browser_session:
        flow = browser_session["assessment_flows"][config["flow_id"]]
    assert tuple(assessment) == (flow["rule_version_id"], "manufacturing")
    assert tuple((row[0], row[1]) for row in legal) == tuple(
        sorted(
            (
                ("privacy", flow["privacy_id"]),
                ("terms", flow["terms_id"]),
                ("roi_disclaimer", flow["roi_disclaimer_id"]),
                ("ai_content_notice", flow["ai_notice_id"]),
            )
        )
    )
    assert tuple(consent) == (config["consent_policy_version"], flow["privacy_id"])


def test_submission_key_replay_requires_exact_rule_and_all_four_legal_bindings(
    client, db
):
    publish_test_legal_bundle()
    first_config = issue_real_config_flow(client)
    submission_key = "550e8400-e29b-41d4-a716-446655440102"
    first = client.post(
        "/api/v2/assessment/complete",
        json=bound_completion_payload(first_config, submission_key=submission_key),
        headers={"X-CSRF-Token": first_config["csrf_token"]},
    )
    same_config = issue_real_config_flow(client)
    same = client.post(
        "/api/v2/assessment/complete",
        json=bound_completion_payload(same_config, submission_key=submission_key),
        headers={"X-CSRF-Token": same_config["csrf_token"]},
    )

    next_now = FLOW_NOW + timedelta(minutes=1)
    publish_test_legal_bundle(suffix="v2", now=next_now)
    changed_config = issue_real_config_flow(client, now=next_now)
    before = {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "leads",
            "lead_consents",
            "assessments",
            "assessment_legal_versions",
            "roi_estimates",
            "analytics_events",
        )
    }
    changed = client.post(
        "/api/v2/assessment/complete",
        json=bound_completion_payload(changed_config, submission_key=submission_key),
        headers={"X-CSRF-Token": changed_config["csrf_token"]},
    )
    after = {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in before
    }

    assert first.status_code == same.status_code == 200
    assert first.get_json()["assessment_id"] == same.get_json()["assessment_id"]
    assert changed.status_code == 409
    assert changed.get_json() == {"error": "assessment conflict"}
    assert after == before


def test_flow_nonce_never_enters_domain_rows_report_html_or_analytics_metadata(client, db):
    publish_test_legal_bundle()
    config = issue_real_config_flow(client)
    response = client.post(
        "/api/v2/assessment/complete",
        json=bound_completion_payload(
            config, submission_key="550e8400-e29b-41d4-a716-446655440103"
        ),
        headers={"X-CSRF-Token": config["csrf_token"]},
    )
    assert response.status_code == 200
    assessment_id = response.get_json()["assessment_id"]
    serialized_database = "\n".join(db.iterdump())
    report = client.get(f"/assessment/report/{assessment_id}")
    metadata = tuple(
        row[0]
        for row in db.execute(
            "SELECT metadata_json FROM analytics_events WHERE assessment_id=?",
            (assessment_id,),
        )
    )

    assert config["flow_id"] not in serialized_database
    assert config["flow_id"].encode() not in report.data
    assert all(config["flow_id"] not in value for value in metadata)


def test_report_21_freezes_four_legal_identities_notices_and_safe_version_links(
    client, db, monkeypatch
):
    import assessment_repository
    import report_pdf

    publish_test_legal_bundle()
    config = issue_real_config_flow(client)
    response = client.post(
        "/api/v2/assessment/complete",
        json=bound_completion_payload(
            config, submission_key="550e8400-e29b-41d4-a716-446655440104"
        ),
        headers={"X-CSRF-Token": config["csrf_token"]},
    )
    assessment_id = response.get_json()["assessment_id"]
    serialized = db.execute(
        "SELECT report_snapshot_json FROM assessments WHERE id=?", (assessment_id,)
    ).fetchone()[0]
    snapshot = json.loads(serialized)
    legal_rows = {
        row["document_type"]: row
        for row in db.execute(
            "SELECT d.document_type,d.id,d.version_code,d.content_sha256,d.body_summary "
            "FROM assessment_legal_versions a JOIN legal_documents d "
            "ON d.id=a.legal_version_id WHERE a.assessment_id=?",
            (assessment_id,),
        )
    }

    assert response.status_code == 200
    assert snapshot["schema_version"] == "2.1"
    assert tuple(item["document_type"] for item in snapshot["legal"]) == (
        "privacy",
        "terms",
        "roi_disclaimer",
        "ai_content_notice",
    )
    for item in snapshot["legal"]:
        row = legal_rows[item["document_type"]]
        assert item == {
            "document_type": item["document_type"],
            "legal_version_id": row["id"],
            "version_code": row["version_code"],
            "content_sha256": row["content_sha256"],
            "public_path": f'/legal/{item["document_type"]}/{row["version_code"]}',
            "external_url": None,
        }
    assert snapshot["legal_notices"] == {
        "roi_disclaimer": legal_rows["roi_disclaimer"]["body_summary"],
        "ai_content_notice": legal_rows["ai_content_notice"]["body_summary"],
    }
    assert assessment_repository.report_summary_from_snapshot(serialized) == (
        snapshot["scores"]["maturity_code"],
        snapshot["recommendations"][0]["scenario"]["code"],
    )
    report = client.get(f"/assessment/report/{assessment_id}")
    assert report.status_code == 200
    assert legal_rows["roi_disclaimer"]["body_summary"].encode() in report.data
    assert legal_rows["ai_content_notice"]["body_summary"].encode() in report.data
    for item in snapshot["legal"]:
        assert item["public_path"].encode() in report.data

    captured = {}

    def render_pdf(html, _base_url):
        captured["html"] = html
        return b"%PDF-test"

    monkeypatch.setattr(report_pdf, "render_pdf", render_pdf)
    pdf = client.get(f"/assessment/report/{assessment_id}/pdf")
    assert pdf.status_code == 200
    assert legal_rows["roi_disclaimer"]["body_summary"] in captured["html"]
    assert legal_rows["ai_content_notice"]["body_summary"] in captured["html"]
    for item in snapshot["legal"]:
        assert item["public_path"] in captured["html"]


def test_report_21_load_rejects_relational_legal_mismatch_and_oversize(client, db):
    import assessment_repository

    publish_test_legal_bundle()
    config = issue_real_config_flow(client)
    response = client.post(
        "/api/v2/assessment/complete",
        json=bound_completion_payload(
            config, submission_key="550e8400-e29b-41d4-a716-446655440105"
        ),
        headers={"X-CSRF-Token": config["csrf_token"]},
    )
    source_id = response.get_json()["assessment_id"]
    snapshot = json.loads(
        db.execute(
            "SELECT report_snapshot_json FROM assessments WHERE id=?", (source_id,)
        ).fetchone()[0]
    )
    snapshot["legal"][0]["content_sha256"] = "0" * 64

    mismatch_id = db.execute(
        "INSERT INTO assessments "
        "(submission_key,lead_id,rule_version_id,branch_code,subbranch_code,"
        "department_code,company_size_code,answers_json,dimension_scores_json,"
        "overall_score,maturity_code,report_snapshot_json,attribution_json,completed_at) "
        "SELECT ?,lead_id,rule_version_id,branch_code,subbranch_code,"
        "department_code,company_size_code,answers_json,dimension_scores_json,"
        "overall_score,maturity_code,?,attribution_json,completed_at "
        "FROM assessments WHERE id=?",
        ("550e8400-e29b-41d4-a716-446655440106", json.dumps(snapshot), source_id),
    ).lastrowid
    db.execute(
        "INSERT INTO assessment_legal_versions "
        "(assessment_id,document_type,legal_version_id,version_code,digest) "
        "SELECT ?,document_type,legal_version_id,version_code,digest "
        "FROM assessment_legal_versions WHERE assessment_id=?",
        (mismatch_id, source_id),
    )
    oversize_id = db.execute(
        "INSERT INTO assessments "
        "(submission_key,lead_id,rule_version_id,branch_code,subbranch_code,"
        "department_code,company_size_code,answers_json,dimension_scores_json,"
        "overall_score,maturity_code,report_snapshot_json,attribution_json,completed_at) "
        "SELECT ?,lead_id,rule_version_id,branch_code,subbranch_code,"
        "department_code,company_size_code,answers_json,dimension_scores_json,"
        "overall_score,maturity_code,?,attribution_json,completed_at "
        "FROM assessments WHERE id=?",
        (
            "550e8400-e29b-41d4-a716-446655440107",
            " " * (assessment_repository.MAX_REPORT_SNAPSHOT_BYTES + 1),
            source_id,
        ),
    ).lastrowid
    db.commit()

    assert assessment_repository.load_report_snapshot(mismatch_id) is None
    assert assessment_repository.load_report_snapshot(oversize_id) is None


def test_016_consent_insert_requires_exact_reviewed_internal_privacy_binding(db):
    from legal_repository import reconcile_external_privacy_reference

    legal_ids = publish_test_legal_bundle()
    privacy = db.execute(
        "SELECT version_code FROM legal_documents WHERE id=?",
        (legal_ids["privacy"],),
    ).fetchone()
    lead_id = db.execute(
        "INSERT INTO leads(company_name,contact_name,created_at,updated_at) "
        "VALUES ('TEST company','TEST contact',?,?)",
        ("2026-09-03 10:00:00", "2026-09-03 10:00:00"),
    ).lastrowid
    consent_id = db.execute(
        "INSERT INTO lead_consents "
        "(lead_id,policy_version,consented_at,source,identity_hash,legal_version_id) "
        "VALUES (?,?,?,?,?,?)",
        (
            lead_id,
            privacy["version_code"],
            "2026-09-03 10:00:00",
            "assessment",
            "identity-1",
            legal_ids["privacy"],
        ),
    ).lastrowid
    db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="invalid consent legal update"):
        db.execute(
            "UPDATE lead_consents SET policy_version='forged-policy' WHERE id=?",
            (consent_id,),
        )
    db.rollback()

    for policy_version, legal_version_id in (
        (privacy["version_code"], None),
        ("wrong-policy", legal_ids["privacy"]),
    ):
        with pytest.raises(sqlite3.IntegrityError, match="invalid consent legal binding"):
            db.execute(
                "INSERT INTO lead_consents "
                "(lead_id,policy_version,consented_at,source,identity_hash,legal_version_id) "
                "VALUES (?,?,?,?,?,?)",
                (
                    lead_id,
                    policy_version,
                    "2026-09-03 10:00:00",
                    "assessment",
                    "identity-invalid",
                    legal_version_id,
                ),
            )
    db.rollback()

    external_id = reconcile_external_privacy_reference(
        db,
        "legacy-test-v1",
        "https://legal.example/privacy/legacy-test-v1",
        FLOW_NOW,
    )
    with pytest.raises(sqlite3.IntegrityError, match="invalid consent legal binding"):
        db.execute(
            "INSERT INTO lead_consents "
            "(lead_id,policy_version,consented_at,source,identity_hash,legal_version_id) "
            "VALUES (?,?,?,?,?,?)",
            (
                lead_id,
                "legacy-test-v1",
                "2026-09-03 10:00:00",
                "assessment",
                "identity-external",
                external_id,
            ),
        )
    db.rollback()
    db.execute("DELETE FROM lead_consents WHERE id=?", (consent_id,))
    assert db.execute(
        "SELECT COUNT(*) FROM lead_consents WHERE id=?", (consent_id,)
    ).fetchone()[0] == 0


def test_016_assessment_legal_snapshot_requires_exact_internal_reviewed_identity(db):
    legal_ids = publish_test_legal_bundle()
    privacy = db.execute(
        "SELECT version_code,content_sha256 FROM legal_documents WHERE id=?",
        (legal_ids["privacy"],),
    ).fetchone()
    assessment_id = db.execute(
        "INSERT INTO assessments(company_name,created_at) VALUES ('TEST',?)",
        ("2026-09-03 10:00:00",),
    ).lastrowid
    db.execute(
        "INSERT INTO assessment_legal_versions "
        "(assessment_id,document_type,legal_version_id,version_code,digest) "
        "VALUES (?,?,?,?,?)",
        (
            assessment_id,
            "privacy",
            legal_ids["privacy"],
            privacy["version_code"],
            privacy["content_sha256"],
        ),
    )
    for document_type, version_code, digest in (
        ("terms", privacy["version_code"], privacy["content_sha256"]),
        ("privacy", "wrong-version", privacy["content_sha256"]),
        ("privacy", privacy["version_code"], "0" * 64),
    ):
        with pytest.raises(
            sqlite3.IntegrityError, match="invalid assessment legal snapshot"
        ):
            db.execute(
                "INSERT INTO assessment_legal_versions "
                "(assessment_id,document_type,legal_version_id,version_code,digest) "
                "VALUES (?,?,?,?,?)",
                (
                    assessment_id + 1,
                    document_type,
                    legal_ids["privacy"],
                    version_code,
                    digest,
                ),
            )


def test_016_consent_update_never_rebinds_but_exact_legacy_reconciliation_is_allowed(db):
    from legal_repository import reconcile_external_privacy_reference

    legal_ids = publish_test_legal_bundle()
    privacy = db.execute(
        "SELECT version_code FROM legal_documents WHERE id=?",
        (legal_ids["privacy"],),
    ).fetchone()
    lead_id = db.execute(
        "INSERT INTO leads(company_name,contact_name,created_at,updated_at) "
        "VALUES ('TEST company','TEST contact',?,?)",
        ("2026-09-03 10:00:00", "2026-09-03 10:00:00"),
    ).lastrowid
    bound_id = db.execute(
        "INSERT INTO lead_consents "
        "(lead_id,policy_version,consented_at,source,identity_hash,legal_version_id) "
        "VALUES (?,?,?,?,?,?)",
        (
            lead_id,
            privacy["version_code"],
            "2026-09-03 10:00:00",
            "assessment",
            "identity-bound",
            legal_ids["privacy"],
        ),
    ).lastrowid
    db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="invalid consent legal update"):
        db.execute(
            "UPDATE lead_consents SET legal_version_id=NULL WHERE id=?", (bound_id,)
        )
    db.rollback()

    db.execute("DROP TRIGGER lead_consent_insert_legal_guard")
    legacy_id = db.execute(
        "INSERT INTO lead_consents "
        "(lead_id,policy_version,consented_at,source,identity_hash) "
        "VALUES (?,?,?,?,?)",
        (
            lead_id,
            "legacy-test-v2",
            "2026-09-03 10:00:00",
            "assessment",
            "identity-legacy-ok",
        ),
    ).lastrowid
    db.commit()
    migration_sql = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "016_assessment_flow_enforcement.sql"
    ).read_text(encoding="utf-8")
    db.executescript(migration_sql)

    external_id = reconcile_external_privacy_reference(
        db,
        "legacy-test-v2",
        "https://legal.example/privacy/legacy-test-v2",
        FLOW_NOW,
    )
    assert db.execute(
        "SELECT legal_version_id FROM lead_consents WHERE id=?", (legacy_id,)
    ).fetchone()[0] == external_id
    first_audits = db.execute(
        "SELECT COUNT(*) FROM governance_audit_events"
    ).fetchone()[0]
    assert reconcile_external_privacy_reference(
        db,
        "legacy-test-v2",
        "https://legal.example/privacy/legacy-test-v2",
        FLOW_NOW,
    ) == external_id
    assert db.execute(
        "SELECT COUNT(*) FROM governance_audit_events"
    ).fetchone()[0] == first_audits

    db.execute("DROP TRIGGER lead_consent_insert_legal_guard")
    forged_id = db.execute(
        "INSERT INTO lead_consents "
        "(lead_id,policy_version,consented_at,source,identity_hash) "
        "VALUES (?,?,?,?,?)",
        (
            lead_id,
            "legacy-test-v2",
            "2026-09-03 10:00:00",
            "assessment",
            "identity-legacy-forged",
        ),
    ).lastrowid
    db.commit()
    db.executescript(migration_sql)
    with pytest.raises(sqlite3.IntegrityError, match="invalid consent legal update"):
        db.execute(
            "UPDATE lead_consents SET legal_version_id=?,source='forged' WHERE id=?",
            (external_id, forged_id),
        )
    db.rollback()
