import hashlib
import json
import re
from datetime import datetime, timezone
import uuid

import pytest
from bs4 import BeautifulSoup

import analytics_repository
import models
import report_pdf
from blueprints import assessment as assessment_blueprint


CLIENT_EVENTS = (
    "home_viewed",
    "assessment_started",
    "assessment_step_completed",
    "service_inquiry_clicked",
    "wechat_clicked",
    "phone_clicked",
)
SERVER_EVENTS = (
    "assessment_completed",
    "lead_submitted",
    "report_viewed",
    "report_pdf_downloaded",
    "appointment_submitted",
)
VALID_METADATA = {
    "step": "profile",
    "branch_code": "manufacturing",
    "subbranch_code": "discrete_manufacturing",
    "department_code": "production",
    "maturity_code": "pilot",
    "scenario_code": "data_process_foundation",
    "source": "website",
    "page": "home",
    "utm_source": "organic",
    "utm_medium": "website",
    "utm_campaign": "task-12",
}
QUESTION_CODES = (
    "business_value_frequency",
    "business_value_scope",
    "process_documentation",
    "process_stability",
    "data_availability",
    "data_quality",
    "systems_foundation",
    "systems_automation",
    "organization_owner",
    "organization_adoption",
    "delivery_budget",
    "delivery_timeline",
)


def _authorize_events(client, token="analytics-csrf"):
    with client.session_transaction() as current_session:
        current_session["csrf_token"] = token
    return {"X-CSRF-Token": token}


def _post_event(client, event_name, metadata=None, *, headers=None, extra=None):
    payload = {"event_name": event_name, "metadata": metadata or {}}
    if extra:
        payload.update(extra)
    return client.post(
        "/api/v2/events",
        json=payload,
        headers=headers or _authorize_events(client),
    )


def _analytics_rows():
    db = models.get_db()
    try:
        return db.execute("SELECT * FROM analytics_events ORDER BY id").fetchall()
    finally:
        db.close()


def _event_quota_count():
    db = models.get_db()
    try:
        row = db.execute(
            "SELECT COALESCE(SUM(request_count),0) FROM request_rate_limits "
            "WHERE bucket='assessment_v2_events'"
        ).fetchone()
        return row[0]
    finally:
        db.close()


def _complete_assessment(client):
    client.application.config.update(
        PRIVACY_PROCESSOR_NAME="测试处理者",
        PRIVACY_CONTACT="privacy@example.invalid",
        PRIVACY_POLICY_URL="https://example.invalid/privacy",
    )
    config = client.get("/api/v2/assessment/config/manufacturing")
    assert config.status_code == 200
    csrf = config.get_json()["csrf_token"]
    response = client.post(
        "/api/v2/assessment/complete",
        json={
            "submission_key": str(uuid.uuid4()),
            "assessment": {
                "schema_version": "2.0",
                "profile": {
                    "branch_code": "manufacturing",
                    "subbranch_code": "discrete_manufacturing",
                    "department_code": "production",
                    "company_size_code": "50_200",
                    "pain_codes": ["production_reporting"],
                },
                "answers": {code: "level_3" for code in QUESTION_CODES},
                "roi_choices": {
                    "headcount": "6_20",
                    "monthly_hours": "20_80",
                    "monthly_cost": "8000_15000",
                    "loss_factor": "normal",
                    "budget": "50000_200000",
                },
            },
            "contact": {
                "company_name": "埋点测试企业",
                "contact_name": "埋点测试联系人",
                "phone": "13800138000",
            },
            "consent": {"accepted": True, "policy_version": "2026-08-19"},
            "attribution": {"source": "website_assessment"},
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    return response.get_json()["assessment_id"], csrf


def _assessment_events(assessment_id):
    return [
        row
        for row in _analytics_rows()
        if row["assessment_id"] == assessment_id
    ]


def test_client_endpoint_accepts_only_the_six_client_events_and_preserves_repeats(
    client,
):
    headers = _authorize_events(client)

    responses = [
        _post_event(client, event_name, {"page": "home"}, headers=headers)
        for event_name in CLIENT_EVENTS
    ]
    responses.append(
        _post_event(client, "home_viewed", {"page": "home"}, headers=headers)
    )

    assert [response.status_code for response in responses] == [204] * 7
    rows = _analytics_rows()
    assert [row["event_name"] for row in rows] == [*CLIENT_EVENTS, "home_viewed"]
    assert all(row["assessment_id"] is None for row in rows)


@pytest.mark.parametrize("event_name", (*SERVER_EVENTS, "arbitrary_event"))
def test_client_endpoint_rejects_server_and_unknown_events_without_quota_or_write(
    client, event_name
):
    marker = f"private-{event_name}-marker"

    response = _post_event(client, event_name, {"source": marker})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert marker.encode() not in response.data
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


@pytest.mark.parametrize("event_name", ([], {}, 1, True, None))
def test_client_endpoint_rejects_container_and_non_string_event_names(
    client, event_name
):
    response = _post_event(client, event_name, {})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


def test_client_cannot_forge_assessment_ownership(client):
    response = _post_event(
        client,
        "assessment_started",
        {"branch_code": "manufacturing"},
        extra={"assessment_id": 42},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


def test_metadata_exact_allowlist_is_normalized_and_persisted_without_pii(client):
    headers = _authorize_events(client)

    response = _post_event(
        client,
        "assessment_step_completed",
        {key: f"  {value}  " for key, value in VALID_METADATA.items()},
        headers=headers,
    )

    assert response.status_code == 204
    row = _analytics_rows()[0]
    assert row["branch_code"] == "manufacturing"
    stored = json.loads(row["metadata_json"])
    assert stored == {key: value for key, value in VALID_METADATA.items() if key != "branch_code"}
    serialized = json.dumps(dict(row), ensure_ascii=False)
    assert "127.0.0.1" not in serialized
    assert "analytics-csrf" not in serialized


@pytest.mark.parametrize(
    "metadata",
    (
        {"phone": "13800138000"},
        {"contact_name": "测试联系人"},
        {"company_name": "测试企业"},
        {"email": "private@example.invalid"},
        {"wechat": "private-wechat"},
        {"ip": "127.0.0.1"},
        {"unknown": "value"},
    ),
)
def test_metadata_rejects_extra_and_contact_shaped_keys(client, metadata):
    response = _post_event(client, "assessment_started", metadata)

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


@pytest.mark.parametrize("value", ([], {}, 1, True, None, "x" * 101))
def test_metadata_rejects_containers_non_strings_and_overlong_strings(client, value):
    response = _post_event(client, "assessment_started", {"source": value})

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


@pytest.mark.parametrize(
    "private_value",
    (
        "call-13800138000-now",
        "call +86 (138) 0013/8000 now",
        "call ١٣٨٠٠١٣٨٠٠٠ now",
        "call १३८००१३८००० now",
        "private@example.invalid",
        "private @ example.invalid",
        "用户＠例子.公司",
        "127.0.0.1",
        "source-from-2001:db8::1",
    ),
)
def test_metadata_rejects_embedded_unicode_obfuscated_contact_and_ip_values(
    client, private_value
):
    response = _post_event(
        client, "assessment_started", {"utm_campaign": private_value}
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert private_value.encode("utf-8") not in response.data
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


@pytest.mark.parametrize(
    "metadata",
    (
        {"step": "not_a_step"},
        {"branch_code": "not_a_branch"},
        {"maturity_code": "not_a_maturity"},
        {"scenario_code": "not_a_scenario"},
        {"subbranch_code": "not-a-stable-code"},
        {"department_code": "部门"},
    ),
)
def test_metadata_code_fields_use_stable_or_exact_domains(client, metadata):
    response = _post_event(client, "assessment_step_completed", metadata)

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


def test_session_analytics_identifier_stores_only_a_sha256_hash(
    client, monkeypatch
):
    random_bytes = b"task-12-random-session-analytics-id"
    expected_hash = hashlib.sha256(random_bytes).hexdigest()
    monkeypatch.setattr(analytics_repository.secrets, "token_bytes", lambda size: random_bytes)

    response = _post_event(client, "home_viewed", {"page": "home"})

    assert response.status_code == 204
    row = _analytics_rows()[0]
    assert row["analytics_id_hash"] == expected_hash
    assert re.fullmatch(r"[0-9a-f]{64}", row["analytics_id_hash"])
    with client.session_transaction() as current_session:
        assert current_session["analytics_id_hash"] == expected_hash
        assert random_bytes.hex() not in json.dumps(dict(current_session))


def test_session_analytics_identifier_is_safe_without_a_request_session():
    assert analytics_repository.session_analytics_id_hash() is None


def test_csrf_failure_precedes_validation_and_quota(client):
    response = client.post(
        "/api/v2/events",
        json={"event_name": "home_viewed", "metadata": {}},
    )

    assert response.status_code == 403
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


def test_event_rate_limit_is_120_validated_requests_per_hour(client):
    headers = _authorize_events(client)

    responses = [
        _post_event(client, "home_viewed", {"page": "home"}, headers=headers)
        for _ in range(121)
    ]

    assert [response.status_code for response in responses] == [204] * 120 + [429]
    assert responses[-1].get_json() == {"error": "rate limit exceeded"}
    assert len(_analytics_rows()) == 120
    assert _event_quota_count() == 121


@pytest.mark.parametrize("failure_type", (RuntimeError, OSError))
def test_repository_failure_returns_generic_503_without_echo(
    client, monkeypatch, failure_type
):
    marker = "private-analytics-database-marker"

    def fail_record(*args, **kwargs):
        raise failure_type(marker)

    monkeypatch.setattr(analytics_repository, "record_event", fail_record)

    response = _post_event(client, "home_viewed", {"source": "website"})

    assert response.status_code == 503
    assert response.get_json() == {"error": "analytics temporarily unavailable"}
    assert marker.encode() not in response.data
    assert _analytics_rows() == []
    assert _event_quota_count() == 1


def test_authorized_html_records_one_report_view_only_after_render_success(
    client, monkeypatch
):
    assessment_id, _ = _complete_assessment(client)
    real_render = assessment_blueprint.render_template
    render_succeeded = False

    def render(template_name, **context):
        nonlocal render_succeeded
        rendered = real_render(template_name, **context)
        if template_name == "assessment/report.html" and not render_succeeded:
            assert not any(
                row["event_name"] == "report_viewed"
                for row in _assessment_events(assessment_id)
            )
            render_succeeded = True
        return rendered

    monkeypatch.setattr(assessment_blueprint, "render_template", render)

    first = client.get(f"/assessment/report/{assessment_id}")
    second = client.get(f"/assessment/report/{assessment_id}")

    assert first.status_code == second.status_code == 200
    assert render_succeeded is True
    events = _assessment_events(assessment_id)
    assert [row["event_name"] for row in events].count("report_viewed") == 1
    hashes = {row["analytics_id_hash"] for row in events}
    assert len(hashes) == 1
    assert re.fullmatch(r"[0-9a-f]{64}", hashes.pop())


def test_unauthorized_or_failed_html_does_not_record_report_view(client, monkeypatch):
    assessment_id, _ = _complete_assessment(client)
    other_client = client.application.test_client()

    unauthorized = other_client.get(f"/assessment/report/{assessment_id}")

    real_render = assessment_blueprint.render_template

    def fail_only_report(template_name, **context):
        if template_name == "assessment/report.html":
            raise RuntimeError("private-render-marker")
        return real_render(template_name, **context)

    monkeypatch.setattr(assessment_blueprint, "render_template", fail_only_report)
    failed = client.get(f"/assessment/report/{assessment_id}")

    assert unauthorized.status_code == 404
    assert failed.status_code == 500
    assert b"private-render-marker" not in failed.data
    assert not any(
        row["event_name"] == "report_viewed"
        for row in _assessment_events(assessment_id)
    )


def test_pdf_event_requires_successful_nonempty_bytes_and_is_idempotent(
    client, monkeypatch
):
    assessment_id, _ = _complete_assessment(client)

    monkeypatch.setattr(
        report_pdf,
        "render_pdf",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("private-pdf-marker")
        ),
    )
    failed = client.get(f"/assessment/report/{assessment_id}/pdf")
    assert failed.status_code == 503
    assert b"private-pdf-marker" not in failed.data
    assert not any(
        row["event_name"] == "report_pdf_downloaded"
        for row in _assessment_events(assessment_id)
    )

    monkeypatch.setattr(report_pdf, "render_pdf", lambda *args, **kwargs: b"%PDF-test")
    first = client.get(f"/assessment/report/{assessment_id}/pdf")
    second = client.get(f"/assessment/report/{assessment_id}/pdf")

    assert first.status_code == second.status_code == 200
    assert first.data == second.data == b"%PDF-test"
    assert [
        row["event_name"] for row in _assessment_events(assessment_id)
    ].count("report_pdf_downloaded") == 1


def test_report_analytics_failure_never_breaks_html_or_pdf(
    client, monkeypatch, caplog
):
    assessment_id, _ = _complete_assessment(client)
    attempted_events = []

    def fail_analytics(event_name, **kwargs):
        attempted_events.append(event_name)
        raise RuntimeError("private-report-analytics-marker")

    monkeypatch.setattr(analytics_repository, "record_event", fail_analytics)
    monkeypatch.setattr(report_pdf, "render_pdf", lambda *args, **kwargs: b"%PDF-test")

    html = client.get(f"/assessment/report/{assessment_id}")
    pdf = client.get(f"/assessment/report/{assessment_id}/pdf")

    assert html.status_code == 200
    assert pdf.status_code == 200
    assert attempted_events == ["report_viewed", "report_pdf_downloaded"]
    assert b"private-report-analytics-marker" not in html.data
    assert b"private-report-analytics-marker" not in pdf.data
    assert "private-report-analytics-marker" not in "\n".join(
        record.getMessage() for record in caplog.records
    )


def test_appointment_event_is_atomic_idempotent_and_server_owned(client):
    assessment_id, csrf = _complete_assessment(client)
    client.application.config["APPOINTMENT_NOW_PROVIDER"] = lambda: datetime(
        2026, 8, 19, 16, 30, tzinfo=timezone.utc
    )
    payload = {
        "assessment_id": assessment_id,
        "submission_key": str(uuid.uuid4()),
        "preferred_date": "2026-08-20",
        "time_slot": "afternoon",
        "note": "",
    }
    headers = {"X-CSRF-Token": csrf}

    first = client.post("/api/v2/appointments", json=payload, headers=headers)
    second = client.post("/api/v2/appointments", json=payload, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.get_json()["appointment_id"] == second.get_json()["appointment_id"]
    assert [
        row["event_name"] for row in _assessment_events(assessment_id)
    ].count("appointment_submitted") == 1


def test_appointment_event_failure_rolls_back_the_appointment(
    client, monkeypatch
):
    assessment_id, csrf = _complete_assessment(client)
    client.application.config["APPOINTMENT_NOW_PROVIDER"] = lambda: datetime(
        2026, 8, 19, 16, 30, tzinfo=timezone.utc
    )
    real_insert = analytics_repository.insert_server_event

    def fail_appointment_event(db, event_name, current_assessment_id):
        if event_name == "appointment_submitted":
            raise RuntimeError("private-appointment-analytics-marker")
        return real_insert(db, event_name, current_assessment_id)

    monkeypatch.setattr(
        analytics_repository, "insert_server_event", fail_appointment_event
    )
    response = client.post(
        "/api/v2/appointments",
        json={
            "assessment_id": assessment_id,
            "submission_key": str(uuid.uuid4()),
            "preferred_date": "2026-08-20",
            "time_slot": "afternoon",
            "note": "",
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 503
    assert b"private-appointment-analytics-marker" not in response.data
    db = models.get_db()
    try:
        assert db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 0
    finally:
        db.close()
    assert not any(
        row["event_name"] == "appointment_submitted"
        for row in _assessment_events(assessment_id)
    )


def test_public_pages_expose_safe_analytics_data_and_external_click_markers(client):
    home = client.get("/")
    services = client.get("/services")
    assessment = client.get("/assessment")
    assert home.status_code == services.status_code == assessment.status_code == 200

    pages = [
        BeautifulSoup(response.data, "html.parser")
        for response in (home, services, assessment)
    ]
    for page in pages:
        body = page.select_one(
            'body[data-analytics-endpoint="/api/v2/events"]'
            "[data-analytics-csrf-token][data-analytics-page]"
        )
        assert body is not None
        assert re.fullmatch(r"[-_A-Za-z0-9]{20,}", body["data-analytics-csrf-token"])
        assert not page.select("[onclick]")
        assert not page.select("script:not([src])")

    assert pages[0].body["data-analytics-page"] == "home"
    marker_events = {
        marker["data-analytics-event"]
        for page in pages
        for marker in page.select("[data-analytics-event]")
    }
    assert marker_events == {
        "service_inquiry_clicked",
        "wechat_clicked",
        "phone_clicked",
    }
