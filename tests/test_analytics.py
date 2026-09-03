import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Lock
from types import SimpleNamespace
import uuid

import pytest
from bs4 import BeautifulSoup

import analytics_repository
import models
import report_pdf
from blueprints import assessment as assessment_blueprint
from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME
from tests.assessment_flow_helpers import (
    FLOW_NOW,
    bound_completion_payload,
    ensure_test_legal_bundle,
    issue_real_config_flow,
)


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
VALID_CLIENT_METADATA = {
    "home_viewed": {"page": "home"},
    "assessment_started": {
        "branch_code": "manufacturing",
        "page": "assessment",
        "source": "website_assessment",
    },
    "assessment_step_completed": {
        "step": "profile",
        "branch_code": "manufacturing",
        "subbranch_code": "discrete_manufacturing",
        "department_code": "production",
        "source": "website_assessment",
        "page": "assessment",
    },
    "service_inquiry_clicked": {
        "page": "services",
        "source": "service_packages",
    },
    "wechat_clicked": {"page": "home", "source": "footer"},
    "phone_clicked": {"page": "home", "source": "footer"},
}
REQUIRED_CLIENT_METADATA_KEYS = {
    "home_viewed": frozenset({"page"}),
    "assessment_started": frozenset({"branch_code", "page", "source"}),
    "assessment_step_completed": frozenset(
        {
            "step",
            "branch_code",
            "subbranch_code",
            "department_code",
            "page",
            "source",
        }
    ),
    "service_inquiry_clicked": frozenset({"page", "source"}),
    "wechat_clicked": frozenset({"page", "source"}),
    "phone_clicked": frozenset({"page", "source"}),
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


def _assert_exact_private_no_store(response):
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"


def _complete_assessment(client):
    ensure_test_legal_bundle()
    config = issue_real_config_flow(client)
    csrf = config["csrf_token"]
    payload = bound_completion_payload(config, submission_key=str(uuid.uuid4()))
    payload["contact"] = {
        "company_name": "埋点测试企业",
        "contact_name": "埋点测试联系人",
        "phone": "13800138000",
    }
    response = client.post(
        "/api/v2/assessment/complete",
        json=payload,
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
        _post_event(
            client,
            event_name,
            VALID_CLIENT_METADATA[event_name],
            headers=headers,
        )
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


def test_client_event_metadata_is_normalized_and_uses_exact_frozen_domains(client):
    headers = _authorize_events(client)
    metadata = VALID_CLIENT_METADATA["assessment_step_completed"]

    response = _post_event(
        client,
        "assessment_step_completed",
        {key: f"  {value}  " for key, value in metadata.items()},
        headers=headers,
    )

    assert response.status_code == 204
    row = _analytics_rows()[0]
    assert row["branch_code"] == "manufacturing"
    stored = json.loads(row["metadata_json"])
    assert stored == {key: value for key, value in metadata.items() if key != "branch_code"}
    serialized = json.dumps(dict(row), ensure_ascii=False)
    assert "127.0.0.1" not in serialized
    assert "analytics-csrf" not in serialized


@pytest.mark.parametrize(
    ("event_name", "missing_key"),
    tuple(
        (event_name, key)
        for event_name, keys in REQUIRED_CLIENT_METADATA_KEYS.items()
        for key in keys
    ),
)
def test_each_client_event_requires_its_explicit_metadata_shape(
    client, event_name, missing_key
):
    metadata = dict(VALID_CLIENT_METADATA[event_name])
    metadata.pop(missing_key)

    response = _post_event(client, event_name, metadata)

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


@pytest.mark.parametrize(
    ("event_name", "extra_metadata"),
    (
        ("home_viewed", {"source": "website_assessment"}),
        ("assessment_started", {"step": "profile"}),
        ("assessment_step_completed", {"utm_source": "organic"}),
        ("assessment_step_completed", {"maturity_code": "pilot"}),
        (
            "assessment_step_completed",
            {"scenario_code": "data_process_foundation"},
        ),
        ("service_inquiry_clicked", {"branch_code": "manufacturing"}),
        ("wechat_clicked", {"scenario_code": "data_process_foundation"}),
        ("phone_clicked", {"maturity_code": "pilot"}),
    ),
)
def test_each_client_event_rejects_other_master_allowlist_fields(
    client, event_name, extra_metadata
):
    metadata = {**VALID_CLIENT_METADATA[event_name], **extra_metadata}

    response = _post_event(client, event_name, metadata)

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


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
    response = _post_event(
        client,
        "assessment_started",
        {**VALID_CLIENT_METADATA["assessment_started"], **metadata},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


@pytest.mark.parametrize("value", ([], {}, 1, True, None, "x" * 101))
def test_metadata_rejects_containers_non_strings_and_overlong_strings(client, value):
    metadata = dict(VALID_CLIENT_METADATA["assessment_started"])
    metadata["source"] = value
    response = _post_event(client, "assessment_started", metadata)

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


@pytest.mark.parametrize(
    "private_value",
    (
        "张先生",
        "示例企业有限公司",
        "wechat_private_id",
        "call-13800138000-now",
        "call +86 (138) 0013/8000 now",
        "call ١٣٨٠٠١٣٨٠٠٠ now",
        "call १३८००१३८००० now",
        "private@example.invalid",
        "private @ example.invalid",
        "用户＠例子.公司",
        "127.0.0.1",
        "１２７。０。０。１",
        "::1",
        "source-from-2001:db8::1",
        "source-from-２００１：ｄｂ８：：１",
        "::ffff:１２７。０。０。１",
    ),
)
def test_allowed_metadata_keys_reject_free_text_and_obfuscated_private_values(
    client, private_value
):
    metadata = dict(VALID_CLIENT_METADATA["assessment_started"])
    metadata["source"] = private_value
    response = _post_event(client, "assessment_started", metadata)

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert private_value.encode("utf-8") not in response.data
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


@pytest.mark.parametrize(
    ("event_name", "field", "private_value"),
    (
        ("home_viewed", "page", "张先生"),
        ("assessment_started", "source", "示例企业有限公司"),
        ("assessment_step_completed", "department_code", "wechat_private_id"),
        ("service_inquiry_clicked", "source", "source-from-2001:db8::1"),
        ("wechat_clicked", "page", "２００１：ｄｂ８：：１"),
        ("phone_clicked", "source", "private@example.invalid"),
    ),
)
def test_private_values_in_each_events_allowed_keys_are_generic_prequota_400(
    client, event_name, field, private_value
):
    metadata = dict(VALID_CLIENT_METADATA[event_name])
    metadata[field] = private_value

    response = _post_event(client, event_name, metadata)

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert private_value.encode("utf-8") not in response.data
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


def test_master_metadata_allowlist_is_only_an_internal_upper_bound():
    assert analytics_repository.METADATA_KEYS == frozenset(
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
    assert all(
        not {"utm_source", "utm_medium", "utm_campaign"}
        & schema["allowed"]
        for schema in analytics_repository.CLIENT_EVENT_SCHEMAS.values()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("step", "not_a_step"),
        ("branch_code", "not_a_branch"),
        ("maturity_code", "not_a_maturity"),
        ("scenario_code", "not_a_scenario"),
        ("subbranch_code", "unknown_but_stable_subbranch"),
        ("department_code", "unknown_but_stable_department"),
        ("subbranch_code", "ecommerce"),
        ("department_code", "merchandising"),
    ),
)
def test_metadata_code_fields_use_exact_branch_scoped_frozen_domains(
    client, field, value
):
    metadata = dict(VALID_CLIENT_METADATA["assessment_step_completed"])
    metadata[field] = value
    response = _post_event(client, "assessment_step_completed", metadata)

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid event payload"}
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


def test_current_server_events_reject_client_style_metadata_and_branch_fields(client):
    assessment_id, _ = _complete_assessment(client)

    with pytest.raises(analytics_repository.ValidationError):
        analytics_repository.record_event(
            "report_viewed",
            assessment_id=assessment_id,
            metadata={"page": "report"},
        )
    with pytest.raises(analytics_repository.ValidationError):
        analytics_repository.record_event(
            "report_viewed",
            assessment_id=assessment_id,
            branch_code="manufacturing",
        )

    assert not any(
        row["event_name"] == "report_viewed"
        for row in _assessment_events(assessment_id)
    )


def test_session_analytics_identifier_stores_only_a_sha256_hash(
    client, monkeypatch
):
    random_bytes = b"task-12-random-session-analytics-id"
    expected_hash = hashlib.sha256(random_bytes).hexdigest()
    monkeypatch.setattr(
        analytics_repository,
        "secrets",
        SimpleNamespace(token_bytes=lambda size: random_bytes),
    )
    headers = _authorize_events(client)

    page = client.get("/")

    assert page.status_code == 200
    assert random_bytes.hex().encode() not in page.data
    assert expected_hash.encode() not in page.data
    with client.session_transaction() as current_session:
        assert current_session["analytics_id_hash"] == expected_hash
        assert random_bytes.hex() not in json.dumps(dict(current_session))

    response = _post_event(
        client,
        "home_viewed",
        VALID_CLIENT_METADATA["home_viewed"],
        headers=headers,
    )
    assert response.status_code == 204
    row = _analytics_rows()[0]
    assert row["analytics_id_hash"] == expected_hash
    assert re.fullmatch(r"[0-9a-f]{64}", row["analytics_id_hash"])


def test_successful_config_bootstrap_establishes_analytics_session_hash(
    client, monkeypatch
):
    ensure_test_legal_bundle()
    client.application.config.update(
        PRIVACY_PROCESSOR_NAME="测试处理者",
        PRIVACY_CONTACT="privacy@example.invalid",
        PRIVACY_POLICY_URL="https://example.invalid/privacy",
        ASSESSMENT_FLOW_NOW_PROVIDER=lambda: FLOW_NOW,
    )
    _authorize_events(client)
    random_bytes = b"task-12-config-session-analytics-id"
    expected_hash = hashlib.sha256(random_bytes).hexdigest()
    monkeypatch.setattr(
        analytics_repository,
        "secrets",
        SimpleNamespace(token_bytes=lambda size: random_bytes),
    )

    response = client.get("/api/v2/assessment/config/manufacturing")

    assert response.status_code == 200
    assert expected_hash.encode() not in response.data
    assert random_bytes.hex().encode() not in response.data
    _assert_exact_private_no_store(response)
    with client.session_transaction() as current_session:
        assert current_session["analytics_id_hash"] == expected_hash


def test_page_bootstrap_prevents_parallel_first_events_from_splitting_identity(
    client, monkeypatch
):
    headers = _authorize_events(client)
    random_call_count = 0
    random_call_lock = Lock()

    def unique_random_bytes(size):
        nonlocal random_call_count
        assert size == 32
        with random_call_lock:
            random_call_count += 1
            return bytes([random_call_count]) * size

    monkeypatch.setattr(
        analytics_repository,
        "secrets",
        SimpleNamespace(token_bytes=unique_random_bytes),
    )
    page = client.get("/")
    assert page.status_code == 200
    session_cookie_name = client.application.config["SESSION_COOKIE_NAME"]
    session_cookie = client.get_cookie(session_cookie_name)
    assert session_cookie is not None
    start = Barrier(2)

    def post_from_independent_browser_connection():
        browser = client.application.test_client()
        browser.set_cookie(session_cookie_name, session_cookie.value)
        start.wait(timeout=5)
        response = _post_event(
            browser,
            "home_viewed",
            VALID_CLIENT_METADATA["home_viewed"],
            headers=headers,
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(
            executor.map(
                lambda _: post_from_independent_browser_connection(), range(2)
            )
        )

    assert statuses == [204, 204]
    assert random_call_count == 1
    hashes = {row["analytics_id_hash"] for row in _analytics_rows()}
    assert hashes == {hashlib.sha256(bytes([1]) * 32).hexdigest()}


def test_unmatched_404_bootstraps_private_analytics_and_footer_post(
    client, monkeypatch
):
    headers = _authorize_events(client)
    random_bytes = b"task-12-unmatched-error-analytics-id"
    expected_hash = hashlib.sha256(random_bytes).hexdigest()
    monkeypatch.setattr(
        analytics_repository,
        "secrets",
        SimpleNamespace(token_bytes=lambda size: random_bytes),
    )

    response = client.get("/definitely-unmatched-task-12-page")

    assert response.status_code == 404
    page = BeautifulSoup(response.data, "html.parser")
    body = page.select_one(
        'body[data-analytics-endpoint="/api/v2/events"]'
        '[data-analytics-csrf-token][data-analytics-page="error"]'
    )
    assert body is not None
    footer_markers = page.select("footer [data-analytics-event]")
    assert {
        marker["data-analytics-event"] for marker in footer_markers
    } == {"wechat_clicked", "phone_clicked"}
    assert random_bytes.hex().encode() not in response.data
    assert expected_hash.encode() not in response.data
    with client.session_transaction() as current_session:
        assert current_session["analytics_id_hash"] == expected_hash
    _assert_exact_private_no_store(response)

    phone_marker = page.select_one(
        'footer [data-analytics-event="phone_clicked"]'
    )
    event_response = _post_event(
        client,
        phone_marker["data-analytics-event"],
        {
            "page": body["data-analytics-page"],
            "source": phone_marker["data-analytics-source"],
        },
        headers=headers,
    )

    assert event_response.status_code == 204
    assert len(_analytics_rows()) == 1
    assert _analytics_rows()[0]["analytics_id_hash"] == expected_hash


def test_unmatched_404_prevents_parallel_first_footer_events_splitting_hash(
    client, monkeypatch
):
    headers = _authorize_events(client)
    random_call_count = 0
    random_call_lock = Lock()

    def unique_random_bytes(size):
        nonlocal random_call_count
        assert size == 32
        with random_call_lock:
            random_call_count += 1
            return bytes([random_call_count]) * size

    monkeypatch.setattr(
        analytics_repository,
        "secrets",
        SimpleNamespace(token_bytes=unique_random_bytes),
    )
    response = client.get("/another-unmatched-task-12-page")
    assert response.status_code == 404
    assert random_call_count == 1
    _assert_exact_private_no_store(response)
    session_cookie_name = client.application.config["SESSION_COOKIE_NAME"]
    session_cookie = client.get_cookie(session_cookie_name)
    assert session_cookie is not None
    start = Barrier(2)

    def post_from_independent_browser_connection(event_name):
        browser = client.application.test_client()
        browser.set_cookie(session_cookie_name, session_cookie.value)
        start.wait(timeout=5)
        result = _post_event(
            browser,
            event_name,
            {"page": "error", "source": "footer"},
            headers=headers,
        )
        return result.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(
            executor.map(
                post_from_independent_browser_connection,
                ("wechat_clicked", "phone_clicked"),
            )
        )

    assert statuses == [204, 204]
    assert random_call_count == 1
    assert {
        row["analytics_id_hash"] for row in _analytics_rows()
    } == {hashlib.sha256(bytes([1]) * 32).hexdigest()}


def test_admin_base_shell_does_not_enable_public_analytics(client):
    login = client.get("/admin/login")
    login_page = BeautifulSoup(login.data, "html.parser")
    csrf = login_page.select_one('input[name="csrf_token"]')["value"]
    authenticated = client.post(
        "/admin/login",
        data={
            "csrf_token": csrf,
            "username": TEST_ADMIN_USERNAME,
            "password": TEST_ADMIN_PASSWORD,
        },
    )
    assert authenticated.status_code == 302

    response = client.get("/admin")

    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    assert page.select_one("[data-analytics-endpoint]") is None
    assert not page.select("[data-analytics-event]")
    assert b"/api/v2/events" not in response.data
    with client.session_transaction() as current_session:
        assert "analytics_id_hash" not in current_session


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


def test_proxy_identities_have_separate_analytics_rate_buckets_without_ip_storage(
    client,
):
    client.application.config["ANALYTICS_EVENT_RATE_LIMIT"] = 1
    csrf_headers = _authorize_events(client)
    assert client.get("/").status_code == 200

    def post_from(proxy_ip):
        return _post_event(
            client,
            "home_viewed",
            VALID_CLIENT_METADATA["home_viewed"],
            headers={**csrf_headers, "X-Forwarded-For": proxy_ip},
        )

    first = post_from("198.51.100.10")
    throttled = post_from("198.51.100.10")
    separate_proxy = post_from("203.0.113.20")

    assert [first.status_code, throttled.status_code, separate_proxy.status_code] == [
        204,
        429,
        204,
    ]
    assert throttled.get_json() == {"error": "rate limit exceeded"}
    serialized_rows = json.dumps(
        [dict(row) for row in _analytics_rows()], ensure_ascii=False
    )
    assert len(_analytics_rows()) == 2
    assert "198.51.100.10" not in serialized_rows
    assert "203.0.113.20" not in serialized_rows
    assert len({row["analytics_id_hash"] for row in _analytics_rows()}) == 1
    db = models.get_db()
    try:
        buckets = db.execute(
            "SELECT identity_hash,request_count FROM request_rate_limits "
            "WHERE bucket='assessment_v2_events' ORDER BY request_count DESC"
        ).fetchall()
        assert [row["request_count"] for row in buckets] == [2, 1]
        assert len({row["identity_hash"] for row in buckets}) == 2
    finally:
        db.close()


@pytest.mark.parametrize("failure_type", (RuntimeError, OSError))
def test_repository_failure_returns_generic_503_without_echo(
    client, monkeypatch, failure_type
):
    marker = "private-analytics-database-marker"

    def fail_record(*args, **kwargs):
        raise failure_type(marker)

    monkeypatch.setattr(analytics_repository, "record_event", fail_record)

    response = _post_event(
        client, "home_viewed", VALID_CLIENT_METADATA["home_viewed"]
    )

    assert response.status_code == 503
    assert response.get_json() == {"error": "analytics temporarily unavailable"}
    assert marker.encode() not in response.data
    assert _analytics_rows() == []
    assert _event_quota_count() == 1


def test_rate_limit_repository_failure_returns_generic_503_without_echo(
    client, monkeypatch
):
    marker = "private-analytics-rate-database-marker"

    def fail_rate_limit(*args, **kwargs):
        raise OSError(marker)

    monkeypatch.setattr(
        assessment_blueprint, "consume_rate_limit", fail_rate_limit
    )

    response = _post_event(
        client, "home_viewed", VALID_CLIENT_METADATA["home_viewed"]
    )

    assert response.status_code == 503
    assert response.get_json() == {"error": "analytics temporarily unavailable"}
    assert marker.encode() not in response.data
    assert _analytics_rows() == []
    assert _event_quota_count() == 0


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


def test_concurrent_server_event_inserts_are_exactly_once_per_assessment(client):
    assessment_id, _ = _complete_assessment(client)
    start = Barrier(4)

    def record_from_independent_connection(_):
        start.wait(timeout=5)
        analytics_repository.record_event(
            "report_viewed", assessment_id=assessment_id
        )
        return True

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(record_from_independent_connection, range(4)))

    assert outcomes == [True] * 4
    assert [
        row["event_name"] for row in _assessment_events(assessment_id)
    ].count("report_viewed") == 1


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

    def fail_appointment_event(
        db, event_name, current_assessment_id, **event_options
    ):
        if event_name == "appointment_submitted":
            raise RuntimeError("private-appointment-analytics-marker")
        return real_insert(
            db, event_name, current_assessment_id, **event_options
        )

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
    services = client.get("/service-packages")
    assessment = client.get("/assessment")
    cases = client.get("/cases")
    resources = client.get("/resources")
    insights = client.get("/insights?category=announcement&next=https://evil.test")
    about = client.get("/about")
    assert all(
        response.status_code == 200
        for response in (home, services, assessment, cases, resources, about)
    )
    assert insights.status_code == 301
    assert insights.headers["Location"] == "/resources"

    pages = [
        BeautifulSoup(response.data, "html.parser")
        for response in (home, services, assessment, cases, resources, about)
    ]
    for page in pages:
        body = page.select_one(
            'body[data-analytics-endpoint="/api/v2/events"]'
            "[data-analytics-csrf-token][data-analytics-page]"
        )
        assert body is not None
        assert re.fullmatch(r"[-_A-Za-z0-9]{20,}", body["data-analytics-csrf-token"])
    for response in (home, services, assessment, cases, resources, about):
        _assert_exact_private_no_store(response)
    for page in pages[:3]:
        assert not page.select("[onclick]")
        assert not page.select("script:not([src])")

    assert [page.body["data-analytics-page"] for page in pages] == [
        "home",
        "services",
        "assessment",
        "cases",
        "resources",
        "about",
    ]
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
