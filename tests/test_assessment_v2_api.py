import copy
import json
import uuid

import models
import pytest


PRIVACY_CONFIG = {
    "PRIVACY_PROCESSOR_NAME": "测试处理者",
    "PRIVACY_CONTACT": "privacy@example.invalid",
    "PRIVACY_POLICY_URL": "https://example.invalid/privacy",
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


def valid_assessment():
    return {
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
    }


def valid_completion(*, submission_key=None):
    return {
        "submission_key": submission_key or str(uuid.uuid4()),
        "assessment": valid_assessment(),
        "contact": {
            "company_name": "示例企业",
            "contact_name": "张先生",
            "phone": "13800138000",
            "email": "private@example.invalid",
            "wechat": "private-wechat",
        },
        "consent": {"accepted": True, "policy_version": "2026-08-19"},
        "attribution": {
            "source": "website_assessment",
            "utm_source": "organic",
            "utm_medium": "website",
            "utm_campaign": "task-8",
        },
    }


def enable_v2(client):
    client.application.config.update(PRIVACY_CONFIG)
    response = client.get("/api/v2/assessment/config/manufacturing")
    assert response.status_code == 200
    return response.get_json()["csrf_token"]


def domain_counts():
    db = models.get_db()
    try:
        return {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("leads", "lead_consents", "assessments", "roi_estimates")
        }
    finally:
        db.close()


def rate_limit_row_count():
    db = models.get_db()
    try:
        return db.execute("SELECT COUNT(*) FROM request_rate_limits").fetchone()[0]
    finally:
        db.close()


def test_config_exposes_only_published_branch_rules_and_required_disclosure(client):
    client.application.config.update(PRIVACY_CONFIG)
    db = models.get_db()
    try:
        industry_id = db.execute(
            "SELECT id FROM industries WHERE code='manufacturing'"
        ).fetchone()[0]
        version_id = db.execute(
            "SELECT id FROM assessment_versions WHERE code='v2.0-2026-08-19'"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO industry_branches "
            "(industry_id,code,name,status,sort_order) VALUES (?,?,?,?,?)",
            (industry_id, "private-draft-branch", "草稿分支", "draft", 999),
        )
        db.execute(
            "INSERT INTO assessment_questions "
            "(assessment_version_id,code,dimension_code,prompt,sort_order,status) "
            "VALUES (?,?,?,?,?,?)",
            (
                version_id,
                "private_draft_question",
                "business_value",
                "草稿问题",
                999,
                "draft",
            ),
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v2/assessment/config/manufacturing")

    assert response.status_code == 200
    body = response.get_json()
    serialized = json.dumps(body, ensure_ascii=False)
    assert body["schema_version"] == "2.0"
    assert body["rule_version"] == "v2.0-2026-08-19"
    assert body["consent_policy_version"] == "2026-08-19"
    assert body["branch"] == {"code": "manufacturing", "label": "制造业"}
    assert len(body["subbranches"]) == 4
    assert len(body["departments"]) == 6
    assert len(body["pain_points"]) == 8
    assert len(body["company_sizes"]) == 4
    assert len(body["questions"]) == 12
    assert [option["score"] for option in body["questions"][0]["options"]] == [
        0,
        1,
        2,
        3,
    ]
    assert body["pain_selection"] == {"minimum": 1, "maximum": 3}
    assert body["reference_line"]["label"] == "平台建议就绪参考线"
    assert body["privacy_disclosure"] == {
        "processor_name": "测试处理者",
        "contact": "privacy@example.invalid",
        "policy_url": "https://example.invalid/privacy",
        "purpose": "用于生成评估报告、联系需求诊断并改进平台服务。",
        "required_data_categories": ["企业名称", "联系人", "手机号", "隐私与联系授权"],
        "optional_data_categories": ["邮箱", "微信"],
        "retention": "未成交线索在最后一次有效跟进后保存365天。",
        "expiry_action": "到期后匿名化联系信息和跟进备注，仅保留不可回溯个人的评估与转化统计。",
        "rights": "可通过上述联系方式申请查阅、更正、撤回同意或删除个人信息。",
    }
    assert isinstance(body["csrf_token"], str) and body["csrf_token"]
    assert "private-draft-branch" not in serialized
    assert "private_draft_question" not in serialized
    assert "行业平均" not in serialized


def test_config_requires_real_privacy_values_and_rejects_unknown_branch(client):
    client.application.config.update(PRIVACY_CONFIG)
    client.application.config["PRIVACY_CONTACT"] = ""

    unavailable = client.get("/api/v2/assessment/config/manufacturing")
    invalid_branch = client.get("/api/v2/assessment/config/not-a-branch")

    assert unavailable.status_code == 503
    assert unavailable.get_json() == {
        "error": "assessment temporarily unavailable",
        "recoverable": True,
    }
    assert invalid_branch.status_code == 400
    assert invalid_branch.get_json() == {"error": "invalid assessment payload"}
    assert "默认".encode() not in unavailable.data


def test_preview_returns_only_the_three_safe_summary_fields(client):
    enable_v2(client)

    response = client.post("/api/v2/assessment/preview", json=valid_assessment())

    assert response.status_code == 200
    assert response.get_json() == {
        "maturity": "collaborate",
        "strongest": "business_value",
        "weakest": "business_value",
    }
    serialized = json.dumps(response.get_json())
    for forbidden in ("recommendations", "roi", "contact", "phone", "email"):
        assert forbidden not in serialized


def test_preview_rejects_invalid_profile_answer_and_roi_codes_without_writes(client):
    enable_v2(client)
    payloads = []
    for path, bad_value in (
        (("profile", "subbranch_code"), "other-branch"),
        (("answers", "business_value_frequency"), "secret-option"),
        (("roi_choices", "budget"), "unbounded-budget"),
    ):
        payload = copy.deepcopy(valid_assessment())
        payload[path[0]][path[1]] = bad_value
        payloads.append(payload)

    responses = [
        client.post("/api/v2/assessment/preview", json=payload)
        for payload in payloads
    ]

    assert [response.status_code for response in responses] == [400, 400, 400]
    assert all(
        response.get_json() == {"error": "invalid assessment payload"}
        for response in responses
    )
    assert domain_counts() == {
        "leads": 0,
        "lead_consents": 0,
        "assessments": 0,
        "roi_estimates": 0,
    }
    assert rate_limit_row_count() == 0


def test_completion_requires_public_csrf_and_accepted_consent_before_writes(client):
    enable_v2(client)
    without_csrf = client.post(
        "/api/v2/assessment/complete", json=valid_completion()
    )
    token = enable_v2(client)
    refused = valid_completion()
    refused["consent"]["accepted"] = False
    without_consent = client.post(
        "/api/v2/assessment/complete",
        json=refused,
        headers={"X-CSRF-Token": token},
    )

    assert without_csrf.status_code == 403
    assert without_consent.status_code == 400
    assert without_consent.get_json() == {"error": "invalid assessment payload"}
    assert domain_counts() == {
        "leads": 0,
        "lead_consents": 0,
        "assessments": 0,
        "roi_estimates": 0,
    }


def test_completion_requires_the_configured_frozen_consent_policy_version(client):
    token = enable_v2(client)
    payload = valid_completion()
    payload["consent"]["policy_version"] = "2026-08-18"

    response = client.post(
        "/api/v2/assessment/complete",
        json=payload,
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid assessment payload"}
    assert domain_counts() == {
        "leads": 0,
        "lead_consents": 0,
        "assessments": 0,
        "roi_estimates": 0,
    }
    assert rate_limit_row_count() == 0


def test_completion_rejects_attribution_contact_fields_and_overlong_values(client):
    token = enable_v2(client)
    with_contact = valid_completion()
    with_contact["attribution"]["phone"] = "13800138000"
    overlong = valid_completion()
    overlong["attribution"]["utm_campaign"] = "x" * 101

    responses = [
        client.post(
            "/api/v2/assessment/complete",
            json=payload,
            headers={"X-CSRF-Token": token},
        )
        for payload in (with_contact, overlong)
    ]

    assert [response.status_code for response in responses] == [400, 400]
    assert all(
        response.get_json() == {"error": "invalid assessment payload"}
        for response in responses
    )
    assert domain_counts()["assessments"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source", "partner user+lead@example.invalid campaign"),
        ("utm_source", "referral-13800138000"),
        ("utm_medium", "referral 138 0013 8000"),
        ("utm_campaign", "referral +86 138-0013-8000"),
        ("source", "+86 (138) 0013-8000"),
        ("utm_source", "referral/138/0013/8000"),
        ("utm_medium", "partner lead @ example.com campaign"),
        ("utm_campaign", "ｌｅａｄ＠ｅｘａｍｐｌｅ．ｃｏｍ"),
        ("source", "١٣٨٠٠١٣٨٠٠٠"),
        ("utm_source", "१३८००१३८०००"),
        ("utm_medium", "用户@例子.公司"),
    ),
)
def test_completion_rejects_contact_values_embedded_in_attribution(
    client, field, value
):
    token = enable_v2(client)
    payload = valid_completion()
    payload["attribution"][field] = value

    response = client.post(
        "/api/v2/assessment/complete",
        json=payload,
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid assessment payload"}
    assert domain_counts() == {
        "leads": 0,
        "lead_consents": 0,
        "assessments": 0,
        "roi_estimates": 0,
    }
    assert rate_limit_row_count() == 0


def test_legacy_assessment_submission_does_not_change_report_session_access(client):
    with client.session_transaction() as session:
        session["assessment_report_ids"] = [91, 92]

    response = client.post(
        "/api/assessment",
        json={
            "company": "兼容性测试企业",
            "email": "legacy@example.invalid",
            "scores": {"strategy": 60},
            "result": "starter",
        },
    )

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["assessment_report_ids"] == [91, 92]


def test_completion_returns_private_urls_and_bounds_session_to_last_five_ids(client):
    token = enable_v2(client)
    responses = [
        client.post(
            "/api/v2/assessment/complete",
            json=valid_completion(),
            headers={"X-CSRF-Token": token},
        )
        for _ in range(6)
    ]

    assert all(response.status_code == 200 for response in responses)
    bodies = [response.get_json() for response in responses]
    assessment_ids = [body["assessment_id"] for body in bodies]
    for body, assessment_id in zip(bodies, assessment_ids):
        assert body == {
            "success": True,
            "assessment_id": assessment_id,
            "report_url": f"/assessment/report/{assessment_id}",
            "pdf_url": f"/assessment/report/{assessment_id}/pdf",
        }
        serialized = json.dumps(body, ensure_ascii=False)
        for private_value in (
            "示例企业",
            "张先生",
            "13800138000",
            "private@example.invalid",
            "private-wechat",
        ):
            assert private_value not in serialized
    with client.session_transaction() as session:
        assert session["assessment_report_ids"] == assessment_ids[-5:]
    assert domain_counts()["assessments"] == 6


def test_same_session_completion_retry_keeps_report_authorization(client):
    token = enable_v2(client)
    payload = valid_completion(
        submission_key="550e8400-e29b-41d4-a716-446655440000"
    )

    first = client.post(
        "/api/v2/assessment/complete",
        json=payload,
        headers={"X-CSRF-Token": token},
    )
    retry = client.post(
        "/api/v2/assessment/complete",
        json=payload,
        headers={"X-CSRF-Token": token},
    )

    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.get_json() == first.get_json()
    with client.session_transaction() as session:
        assert session["assessment_report_ids"] == [
            first.get_json()["assessment_id"]
        ]
    assert domain_counts()["assessments"] == 1


def test_other_session_cannot_replay_submission_key_into_report_access(client):
    first_token = enable_v2(client)
    payload = valid_completion(
        submission_key="550e8400-e29b-41d4-a716-446655440000"
    )
    first = client.post(
        "/api/v2/assessment/complete",
        json=payload,
        headers={"X-CSRF-Token": first_token},
    )
    assessment_id = first.get_json()["assessment_id"]

    other = client.application.test_client()
    other_token = enable_v2(other)
    replay = other.post(
        "/api/v2/assessment/complete",
        json=payload,
        headers={"X-CSRF-Token": other_token},
    )

    assert replay.status_code == 409
    assert replay.get_json() == {"error": "assessment conflict"}
    assert str(assessment_id).encode() not in replay.data
    assert b"report_url" not in replay.data
    assert b"pdf_url" not in replay.data
    with other.session_transaction() as session:
        assert "assessment_report_ids" not in session
    with client.session_transaction() as session:
        assert session["assessment_report_ids"] == [assessment_id]
    assert domain_counts()["assessments"] == 1


def test_missing_published_rules_return_recoverable_503_without_domain_writes(client):
    client.application.config.update(PRIVACY_CONFIG)
    with client.session_transaction() as session:
        session["csrf_token"] = "public-csrf"
    db = models.get_db()
    try:
        db.execute(
            "UPDATE assessment_versions SET status='draft' "
            "WHERE code='v2.0-2026-08-19'"
        )
        db.commit()
    finally:
        db.close()

    responses = (
        client.get("/api/v2/assessment/config/manufacturing"),
        client.post("/api/v2/assessment/preview", json=valid_assessment()),
        client.post(
            "/api/v2/assessment/complete",
            json=valid_completion(),
            headers={"X-CSRF-Token": "public-csrf"},
        ),
    )

    assert [response.status_code for response in responses] == [503, 503, 503]
    assert all(
        response.get_json()
        == {"error": "assessment temporarily unavailable", "recoverable": True}
        for response in responses
    )
    assert domain_counts() == {
        "leads": 0,
        "lead_consents": 0,
        "assessments": 0,
        "roi_estimates": 0,
    }
    assert rate_limit_row_count() == 0


def test_inconsistent_published_rules_return_503_instead_of_partial_results(client):
    token = enable_v2(client)
    db = models.get_db()
    try:
        db.execute(
            "DELETE FROM assessment_options WHERE id=("
            "SELECT ao.id FROM assessment_options ao "
            "JOIN assessment_questions q ON q.id=ao.question_id "
            "WHERE q.code='business_value_frequency' AND ao.code='level_0')"
        )
        db.commit()
    finally:
        db.close()

    config = client.get("/api/v2/assessment/config/manufacturing")
    preview = client.post("/api/v2/assessment/preview", json=valid_assessment())
    complete = client.post(
        "/api/v2/assessment/complete",
        json=valid_completion(),
        headers={"X-CSRF-Token": token},
    )

    assert [config.status_code, preview.status_code, complete.status_code] == [
        503,
        503,
        503,
    ]
    assert domain_counts()["assessments"] == 0
    assert rate_limit_row_count() == 0


@pytest.mark.parametrize(
    "mutation",
    (
        "UPDATE assessment_branch_weights SET business_value_weight=-1,"
        "process_weight=41 WHERE assessment_version_id=(SELECT id FROM "
        "assessment_versions WHERE code='v2.0-2026-08-19') AND industry_id=("
        "SELECT id FROM industries WHERE code='manufacturing')",
        "UPDATE roi_option_ranges SET low_value=-3,mid_value=-2,high_value=-1 "
        "WHERE option_group='headcount' AND code='1_5'",
        "UPDATE services SET min_budget=-100,max_budget=-1 "
        "WHERE code='foundation_workshop'",
        "UPDATE services SET min_budget=100,max_budget=10 "
        "WHERE code='foundation_workshop'",
        "UPDATE scenarios SET min_weeks=1.5 "
        "WHERE code='mfg_operations_reporting'",
        "UPDATE scenario_budget_options SET budget_code='unsupported_budget' "
        "WHERE scenario_id=(SELECT id FROM scenarios "
        "WHERE code='mfg_operations_reporting') AND budget_code='50000_200000'",
        "UPDATE scenarios SET risk_codes_json='[\"unsupported_risk\"]' "
        "WHERE code='mfg_operations_reporting'",
        "UPDATE scenario_roi_profiles SET efficiency_mid=-1 WHERE id=("
        "SELECT MIN(id) FROM scenario_roi_profiles)",
        "UPDATE scenario_roi_profiles SET efficiency_low=.3,efficiency_mid=.2,"
        "efficiency_high=.1 WHERE id=(SELECT MIN(id) "
        "FROM scenario_roi_profiles)",
        "UPDATE scenario_roi_profiles SET efficiency_mid='not-a-number' WHERE id=("
        "SELECT MIN(id) FROM scenario_roi_profiles)",
        "DELETE FROM scenario_roi_profiles WHERE scenario_id=("
        "SELECT id FROM scenarios WHERE code='mfg_operations_reporting')",
        "DELETE FROM scenario_services WHERE scenario_id=("
        "SELECT id FROM scenarios WHERE code='mfg_operations_reporting')",
        "INSERT INTO scenario_services (scenario_id,service_id) SELECT "
        "(SELECT id FROM scenarios WHERE code='mfg_operations_reporting'),"
        "(SELECT id FROM services WHERE code='foundation_workshop')",
    ),
)
def test_numeric_and_link_rule_corruption_fails_closed_without_writes(
    client, mutation
):
    enable_v2(client)
    db = models.get_db()
    try:
        db.execute(mutation)
        db.commit()
    finally:
        db.close()

    response = client.post("/api/v2/assessment/preview", json=valid_assessment())

    assert response.status_code == 503
    assert response.get_json() == {
        "error": "assessment temporarily unavailable",
        "recoverable": True,
    }
    assert domain_counts()["assessments"] == 0
    assert rate_limit_row_count() == 0


@pytest.mark.parametrize(
    "mutations",
    (
        (
            "UPDATE roi_option_ranges SET high_value=1.2 "
            "WHERE option_group='loss_factor' AND code='severe'",
        ),
        (
            "UPDATE scenarios SET category_code='unsupported_category' "
            "WHERE code='mfg_operations_reporting'",
        ),
        (
            "DELETE FROM scenario_budget_options WHERE scenario_id=("
            "SELECT id FROM scenarios WHERE code='mfg_operations_reporting') "
            "AND budget_code='50000_200000'",
        ),
        (
            "UPDATE scenarios SET risk_codes_json='[\"metric_definition\"]' "
            "WHERE code='mfg_operations_reporting'",
        ),
        (
            "DELETE FROM scenario_services WHERE scenario_id=("
            "SELECT id FROM scenarios WHERE code='mfg_operations_reporting')",
            "INSERT INTO scenario_services (scenario_id,service_id) SELECT "
            "(SELECT id FROM scenarios WHERE code='mfg_operations_reporting'),"
            "(SELECT id FROM services WHERE code='foundation_workshop')",
        ),
    ),
    ids=(
        "loss-factor-above-one",
        "unsupported-category",
        "partial-budget-links",
        "partial-risk-links",
        "wrong-nonempty-service-link",
    ),
)
def test_frozen_scenario_manifest_corruption_blocks_preview_and_completion(
    client, mutations
):
    token = enable_v2(client)
    db = models.get_db()
    try:
        for mutation in mutations:
            db.execute(mutation)
        db.commit()
    finally:
        db.close()

    responses = (
        client.post("/api/v2/assessment/preview", json=valid_assessment()),
        client.post(
            "/api/v2/assessment/complete",
            json=valid_completion(),
            headers={"X-CSRF-Token": token},
        ),
    )

    assert [response.status_code for response in responses] == [503, 503]
    assert all(
        response.get_json()
        == {"error": "assessment temporarily unavailable", "recoverable": True}
        for response in responses
    )
    assert domain_counts() == {
        "leads": 0,
        "lead_consents": 0,
        "assessments": 0,
        "roi_estimates": 0,
    }
    assert rate_limit_row_count() == 0


@pytest.mark.parametrize(
    "mutation",
    (
        "UPDATE services SET public_name='自定义名称' "
        "WHERE code='foundation_workshop'",
        "UPDATE services SET category='pilot' "
        "WHERE code='foundation_workshop'",
        "UPDATE services SET min_budget=21000,max_budget=50000 "
        "WHERE code='foundation_workshop'",
        "UPDATE services SET min_weeks=3,max_weeks=4 "
        "WHERE code='foundation_workshop'",
        "UPDATE service_deliverables SET title='自定义交付物' WHERE id=("
        "SELECT MIN(sd.id) FROM service_deliverables sd "
        "JOIN services sv ON sv.id=sd.service_id "
        "WHERE sv.code='foundation_workshop')",
        "UPDATE services SET implementation_steps_json='[\"自定义步骤\"]' "
        "WHERE code='foundation_workshop'",
        "UPDATE services SET prerequisites_json='[\"自定义前提\"]' "
        "WHERE code='foundation_workshop'",
        "UPDATE services SET not_included_json='[\"自定义边界\"]' "
        "WHERE code='foundation_workshop'",
        "UPDATE services SET acceptance_json='[\"自定义验收\"]' "
        "WHERE code='foundation_workshop'",
        "UPDATE services SET support_days=16 "
        "WHERE code='foundation_workshop'",
    ),
    ids=(
        "public-name",
        "category",
        "budget",
        "weeks",
        "deliverables",
        "implementation-steps",
        "prerequisites",
        "not-included",
        "acceptance",
        "support-days",
    ),
)
def test_every_service_snapshot_field_must_match_the_frozen_manifest_before_writes(
    client, mutation
):
    token = enable_v2(client)
    before_domain = domain_counts()
    before_quota = rate_limit_row_count()
    db = models.get_db()
    try:
        db.execute(mutation)
        db.commit()
    finally:
        db.close()

    config = client.get("/api/v2/assessment/config/manufacturing")
    complete = client.post(
        "/api/v2/assessment/complete",
        json=valid_completion(),
        headers={"X-CSRF-Token": token},
    )

    for response in (config, complete):
        assert response.status_code == 503
        assert response.get_json() == {
            "error": "assessment temporarily unavailable",
            "recoverable": True,
        }
    assert domain_counts() == before_domain
    assert rate_limit_row_count() == before_quota


def test_reinit_preserves_custom_service_boundary_and_completion_fails_closed(
    client
):
    token = enable_v2(client)
    custom = '["客户已审批的定制边界"]'
    db = models.get_db()
    try:
        db.execute(
            "UPDATE services SET not_included_json=? "
            "WHERE code='foundation_workshop' AND status='published'",
            (custom,),
        )
        db.commit()
    finally:
        db.close()

    models.init_db()
    db = models.get_db()
    try:
        stored = db.execute(
            "SELECT not_included_json FROM services "
            "WHERE code='foundation_workshop'"
        ).fetchone()[0]
    finally:
        db.close()
    before_domain = domain_counts()
    before_quota = rate_limit_row_count()

    responses = (
        client.get("/api/v2/assessment/config/manufacturing"),
        client.post(
            "/api/v2/assessment/complete",
            json=valid_completion(),
            headers={"X-CSRF-Token": token},
        ),
    )

    assert stored == custom
    assert all(response.status_code == 503 for response in responses)
    assert all(
        response.get_json()
        == {"error": "assessment temporarily unavailable", "recoverable": True}
        for response in responses
    )
    assert domain_counts() == before_domain
    assert rate_limit_row_count() == before_quota


def test_default_preview_and_completion_rate_limits_are_60_and_10_per_hour(client):
    token = enable_v2(client)

    for _ in range(60):
        assert client.post(
            "/api/v2/assessment/preview", json=valid_assessment()
        ).status_code == 200
    preview_blocked = client.post(
        "/api/v2/assessment/preview", json=valid_assessment()
    )

    for _ in range(10):
        assert client.post(
            "/api/v2/assessment/complete",
            json=valid_completion(),
            headers={"X-CSRF-Token": token},
        ).status_code == 200
    completion_blocked = client.post(
        "/api/v2/assessment/complete",
        json=valid_completion(),
        headers={"X-CSRF-Token": token},
    )

    assert preview_blocked.status_code == 429
    assert completion_blocked.status_code == 429
    assert preview_blocked.headers["Retry-After"] == "3600"
    assert completion_blocked.headers["Retry-After"] == "3600"


def test_v2_rate_limits_keep_proxy_forwarded_public_identities_separate(client):
    token = enable_v2(client)
    client.application.config.update(
        ASSESSMENT_PREVIEW_RATE_LIMIT=1,
        ASSESSMENT_COMPLETE_RATE_LIMIT=1,
    )
    proxy = {"X-Forwarded-Proto": "https"}

    previews = [
        client.post(
            "/api/v2/assessment/preview",
            json=valid_assessment(),
            headers={**proxy, "X-Forwarded-For": address},
        )
        for address in ("198.51.100.10", "198.51.100.11")
    ]
    completions = [
        client.post(
            "/api/v2/assessment/complete",
            json=valid_completion(),
            headers={
                **proxy,
                "X-Forwarded-For": address,
                "X-CSRF-Token": token,
            },
        )
        for address in ("198.51.100.10", "198.51.100.11")
    ]

    assert [response.status_code for response in previews] == [200, 200]
    assert [response.status_code for response in completions] == [200, 200]
