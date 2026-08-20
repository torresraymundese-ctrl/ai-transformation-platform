import builtins
from copy import deepcopy
import hashlib
import importlib
from itertools import product
import json
import re
import uuid

from bs4 import BeautifulSoup

import assessment_repository
from assessment.contracts import AssessmentProfile
from assessment.reporting import (
    DIMENSION_EXPLANATIONS,
    DIMENSION_IMPROVEMENT_EXPLANATIONS,
    YEAR_1_BY_MATURITY,
)
from assessment.scoring import DIMENSION_ORDER, score_assessment
from assessment.seed import load_core_catalog_manifest
import models
import pytest
import report_pdf


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

PRIVATE_VALUES = (
    "示例企业",
    "张先生",
    "13800138000",
    "private@example.invalid",
    "private-wechat",
)

LEGACY_SERVICE_EXCLUSIONS = {
    "foundation_workshop": (
        "software development",
        "system integration",
        "data cleansing execution",
    ),
    "knowledge_assistant_pilot": (
        "source-document creation",
        "unrestricted internet answers",
        "custom core-system integration",
    ),
    "customer_growth_pilot": (
        "media spend",
        "guaranteed conversion results",
        "unapproved automated outreach",
    ),
    "workflow_automation": (
        "unstable processes",
        "unlisted system interfaces",
        "removal of manual fallback",
    ),
    "data_insight": (
        "source-system repair",
        "historical data reconstruction",
        "unagreed predictive models",
    ),
    "industry_integration": (
        "unlisted connectors",
        "production infrastructure procurement",
        "guaranteed business outcomes",
    ),
}


def _complete_assessment(client, answers=None):
    client.application.config.update(PRIVACY_CONFIG)
    config = client.get("/api/v2/assessment/config/manufacturing")
    assert config.status_code == 200
    csrf_token = config.get_json()["csrf_token"]
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
                "answers": (
                    {code: "level_3" for code in QUESTION_CODES}
                    if answers is None
                    else answers
                ),
                "roi_choices": {
                    "headcount": "6_20",
                    "monthly_hours": "20_80",
                    "monthly_cost": "8000_15000",
                    "loss_factor": "normal",
                    "budget": "50000_200000",
                },
            },
            "contact": {
                "company_name": PRIVATE_VALUES[0],
                "contact_name": PRIVATE_VALUES[1],
                "phone": PRIVATE_VALUES[2],
                "email": PRIVATE_VALUES[3],
                "wechat": PRIVATE_VALUES[4],
            },
            "consent": {"accepted": True, "policy_version": "2026-08-19"},
            "attribution": {
                "source": "website_assessment",
                "utm_source": "organic",
                "utm_medium": "website",
                "utm_campaign": "task-10",
            },
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    return response.get_json()["assessment_id"]


@pytest.fixture()
def completed_assessment(client):
    return _complete_assessment(client)


def _snapshot(assessment_id):
    return json.loads(_raw_snapshot(assessment_id))


def _raw_snapshot(assessment_id):
    db = models.get_db()
    try:
        value = db.execute(
            "SELECT report_snapshot_json FROM assessments WHERE id=?",
            (assessment_id,),
        ).fetchone()[0]
    finally:
        db.close()
    return value


def _replace_snapshot(assessment_id, snapshot):
    db = models.get_db()
    try:
        db.execute(
            "UPDATE assessments SET report_snapshot_json=? WHERE id=?",
            (json.dumps(snapshot, ensure_ascii=False), assessment_id),
        )
        db.commit()
    finally:
        db.close()


def _clone_assessment(assessment_id, report_snapshot_json):
    db = models.get_db()
    try:
        clone_id = db.execute(
            "INSERT INTO assessments "
            "(submission_key,lead_id,rule_version_id,branch_code,subbranch_code,"
            "department_code,company_size_code,answers_json,dimension_scores_json,"
            "overall_score,maturity_code,report_snapshot_json,attribution_json,"
            "completed_at) "
            "SELECT ?,lead_id,rule_version_id,branch_code,subbranch_code,"
            "department_code,company_size_code,answers_json,dimension_scores_json,"
            "overall_score,maturity_code,?,attribution_json,completed_at "
            "FROM assessments WHERE id=?",
            (str(uuid.uuid4()), report_snapshot_json, assessment_id),
        ).lastrowid
        db.commit()
        return clone_id
    finally:
        db.close()


def _assert_private_cache_headers(response):
    directives = {
        item.strip().lower() for item in response.headers["Cache-Control"].split(",")
    }
    assert {"private", "no-store"} <= directives
    assert response.headers["Pragma"].lower() == "no-cache"
    assert response.headers["Expires"] == "0"


def _roi_basis_rows(page):
    return [
        [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        for row in page.select("#calculation-basis tbody tr")
    ]


EXPECTED_ROI_BASIS_ROWS = [
    ["参与人数", "6—20 人", "6 人", "13 人", "20 人"],
    ["每人每月耗时", "20—80 小时", "20 小时", "50 小时", "80 小时"],
    ["人均月综合成本", "8,000—15,000 元", "¥8,000", "¥11,500", "¥15,000"],
    ["返工或损耗程度", "一般", "5%", "10%", "15%"],
    ["可接受投入", "5—20 万元", "¥50,000", "¥125,000", "¥200,000"],
]


def test_pdf_adapter_loads_weasyprint_only_when_rendering(monkeypatch):
    real_import = builtins.__import__

    def reject_weasyprint(name, *args, **kwargs):
        if name == "weasyprint" or name.startswith("weasyprint."):
            raise ImportError("native PDF runtime unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_weasyprint)

    importlib.reload(report_pdf)
    with pytest.raises(ImportError, match="native PDF runtime unavailable"):
        report_pdf.render_pdf("<html></html>", "file:///trusted-app-root/")


def test_report_requires_the_current_session(completed_assessment, client):
    allowed = client.get(f"/assessment/report/{completed_assessment}")
    other_client = client.application.test_client()
    other = other_client.get(
        f"/assessment/report/{completed_assessment}"
    )
    other_pdf = other_client.get(f"/assessment/report/{completed_assessment}/pdf")
    with client.session_transaction() as session:
        session.clear()
    cleared = client.get(f"/assessment/report/{completed_assessment}")
    cleared_pdf = client.get(f"/assessment/report/{completed_assessment}/pdf")

    assert allowed.status_code == 200
    assert other.status_code == 404
    assert other_pdf.status_code == 404
    assert cleared.status_code == 404
    assert cleared_pdf.status_code == 404
    _assert_private_cache_headers(allowed)
    _assert_private_cache_headers(other)
    _assert_private_cache_headers(other_pdf)
    _assert_private_cache_headers(cleared)
    _assert_private_cache_headers(cleared_pdf)


def test_sixth_oldest_report_is_evicted_for_html_and_pdf(
    completed_assessment, client, monkeypatch
):
    assessment_ids = [completed_assessment]
    assessment_ids.extend(_complete_assessment(client) for _ in range(5))
    monkeypatch.setattr(report_pdf, "render_pdf", lambda *args, **kwargs: b"%PDF-test")

    oldest_html = client.get(f"/assessment/report/{assessment_ids[0]}")
    oldest_pdf = client.get(f"/assessment/report/{assessment_ids[0]}/pdf")
    newest_html = client.get(f"/assessment/report/{assessment_ids[-1]}")
    newest_pdf = client.get(f"/assessment/report/{assessment_ids[-1]}/pdf")

    assert oldest_html.status_code == 404
    assert oldest_pdf.status_code == 404
    assert newest_html.status_code == 200
    assert newest_pdf.status_code == 200
    for response in (oldest_html, oldest_pdf, newest_html, newest_pdf):
        _assert_private_cache_headers(response)


def test_canonical_weakest_tie_survives_persisted_sorted_json_html_and_pdf(
    client, monkeypatch
):
    answers = {
        "business_value_frequency": "level_3",
        "business_value_scope": "level_3",
        "process_documentation": "level_0",
        "process_stability": "level_0",
        "data_availability": "level_2",
        "data_quality": "level_2",
        "systems_foundation": "level_2",
        "systems_automation": "level_2",
        "organization_owner": "level_2",
        "organization_adoption": "level_2",
        "delivery_budget": "level_0",
        "delivery_timeline": "level_0",
    }
    assessment_id = _complete_assessment(client, answers=answers)
    persisted = json.loads(_raw_snapshot(assessment_id))
    captured = {}

    def render(html, base_url):
        captured["html"] = html
        return b"%PDF-test"

    monkeypatch.setattr(report_pdf, "render_pdf", render)
    html = client.get(f"/assessment/report/{assessment_id}")
    pdf = client.get(f"/assessment/report/{assessment_id}/pdf")

    assert list(persisted["scores"]["dimension_scores"]) == [
        "business_value",
        "data",
        "delivery",
        "organization",
        "process",
        "systems",
    ]
    assert persisted["scores"]["weakest"]["dimension"] == "process"
    assert html.status_code == 200
    assert pdf.status_code == 200
    browser_page = BeautifulSoup(html.data, "html.parser")
    pdf_page = BeautifulSoup(captured["html"], "html.parser")
    assert "流程维度仍需补齐" in browser_page.select_one("#weaknesses").get_text(
        " ", strip=True
    )
    assert pdf_page.select_one("#weaknesses").get_text(" ", strip=True) == (
        browser_page.select_one("#weaknesses").get_text(" ", strip=True)
    )
    _assert_private_cache_headers(html)
    _assert_private_cache_headers(pdf)


def test_all_paired_answer_score_extrema_survive_sorted_json_roundtrip(
    completed_assessment,
):
    catalog = assessment_repository.load_published_catalog("manufacturing")
    base = _snapshot(completed_assessment)
    questions_by_dimension = {
        dimension: tuple(
            question.code
            for question in catalog.questions
            if question.dimension == dimension
        )
        for dimension in DIMENSION_ORDER
    }
    rejected = []

    for selected_levels in product(
        ("level_0", "level_1", "level_2", "level_3"), repeat=6
    ):
        answers = {
            question_code: level
            for dimension, level in zip(DIMENSION_ORDER, selected_levels)
            for question_code in questions_by_dimension[dimension]
        }
        profile = AssessmentProfile(
            branch_code="manufacturing",
            subbranch_code="discrete_manufacturing",
            department_code="production",
            company_size_code="50_200",
            pain_codes=("production_reporting",),
            answers=answers,
            roi_choices=base["assessment"]["roi_choices"],
        )
        scores = score_assessment(catalog, profile)
        candidate = deepcopy(base)
        candidate["assessment"]["answers"] = answers
        candidate["scores"]["dimension_scores"] = dict(scores.dimension_scores)
        candidate["scores"]["overall_score"] = scores.overall_score
        candidate["scores"]["maturity_code"] = scores.maturity_code
        candidate["scores"]["strongest"] = {
            "dimension": scores.strongest_dimension,
            "explanation": DIMENSION_EXPLANATIONS[scores.strongest_dimension],
        }
        candidate["scores"]["weakest"] = {
            "dimension": scores.weakest_dimension,
            "explanation": DIMENSION_IMPROVEMENT_EXPLANATIONS[
                scores.weakest_dimension
            ],
        }
        candidate["roadmap_years_1_3"][0]["action"] = YEAR_1_BY_MATURITY[
            scores.maturity_code
        ]
        roundtripped = json.loads(
            json.dumps(candidate, ensure_ascii=False, sort_keys=True)
        )
        if not assessment_repository._valid_report_snapshot(roundtripped):
            rejected.append(selected_levels)

    assert not rejected, (
        f"{len(rejected)} paired-answer profiles were rejected; "
        f"first profiles: {rejected[:3]}"
    )


def test_legacy_incomplete_and_invalid_snapshots_return_404(
    completed_assessment, client, monkeypatch
):
    db = models.get_db()
    try:
        legacy_id = db.execute(
            "INSERT INTO assessments (company_name,contact_email,scores,result) "
            "VALUES (?,?,?,?)",
            ("旧企业", "legacy@example.invalid", '{"legacy":1}', "starter"),
        ).lastrowid
        db.commit()
    finally:
        db.close()
    incomplete = _snapshot(completed_assessment)
    incomplete.pop("disclaimer")
    forbidden_private_data = _snapshot(completed_assessment)
    forbidden_private_data["contact_name"] = "不应进入报告"
    missing_dimension = _snapshot(completed_assessment)
    missing_dimension["scores"]["dimension_scores"].pop("delivery")
    missing_calculation_basis = _snapshot(completed_assessment)
    missing_calculation_basis["calculation_basis"].pop("coefficients")
    missing_recommendation_score = _snapshot(completed_assessment)
    missing_recommendation_score["recommendations"][0].pop("match_score")
    invalid_ids = [
        legacy_id,
        _clone_assessment(completed_assessment, None),
        _clone_assessment(completed_assessment, "not-json"),
        _clone_assessment(completed_assessment, "[]"),
        _clone_assessment(completed_assessment, "{}"),
        _clone_assessment(
            completed_assessment, json.dumps(incomplete, ensure_ascii=False)
        ),
        _clone_assessment(
            completed_assessment,
            json.dumps(forbidden_private_data, ensure_ascii=False),
        ),
        _clone_assessment(
            completed_assessment, json.dumps(missing_dimension, ensure_ascii=False)
        ),
        _clone_assessment(
            completed_assessment,
            json.dumps(missing_calculation_basis, ensure_ascii=False),
        ),
        _clone_assessment(
            completed_assessment,
            json.dumps(missing_recommendation_score, ensure_ascii=False),
        ),
    ]
    with client.session_transaction() as session:
        session["assessment_report_ids"] = invalid_ids
    rendered = {"called": False}

    def unexpected_render(*args, **kwargs):
        rendered["called"] = True
        return b"%PDF-unexpected"

    monkeypatch.setattr(report_pdf, "render_pdf", unexpected_render)

    for assessment_id in invalid_ids:
        html = client.get(f"/assessment/report/{assessment_id}")
        pdf = client.get(f"/assessment/report/{assessment_id}/pdf")
        assert html.status_code == 404
        assert pdf.status_code == 404
        _assert_private_cache_headers(html)
        _assert_private_cache_headers(pdf)
    assert rendered["called"] is False


@pytest.mark.parametrize(
    "corruption",
    ("oversized_snapshot", "oversized_integer", "excessive_nesting"),
)
def test_resource_abusive_snapshot_json_returns_private_404_without_rendering(
    completed_assessment, client, monkeypatch, caplog, corruption
):
    snapshot = _snapshot(completed_assessment)
    raw = json.dumps(snapshot, ensure_ascii=False)
    if corruption == "oversized_snapshot":
        snapshot["scores"]["strongest"]["explanation"] = "x" * 200_000
        raw = json.dumps(snapshot, ensure_ascii=False)
    elif corruption == "oversized_integer":
        raw = raw.replace(
            '"overall_score": 100',
            f'"overall_score": {"9" * 5_000}',
            1,
        )
    else:
        raw = "[" * 1_200 + "0" + "]" * 1_200
    assessment_id = _clone_assessment(completed_assessment, raw)
    with client.session_transaction() as session:
        session["assessment_report_ids"] = [assessment_id]

    def unexpected_render(*args, **kwargs):
        pytest.fail("invalid snapshot reached the PDF renderer")

    monkeypatch.setattr(report_pdf, "render_pdf", unexpected_render)

    html = client.get(f"/assessment/report/{assessment_id}")
    pdf = client.get(f"/assessment/report/{assessment_id}/pdf")

    assert html.status_code == 404
    assert pdf.status_code == 404
    _assert_private_cache_headers(html)
    _assert_private_cache_headers(pdf)
    assert "5000" not in caplog.text
    assert "Unhandled application error" not in caplog.text


@pytest.mark.parametrize(
    "corruption",
    (
        "extra_top_level_section",
        "extra_nested_score_key",
        "missing_answer",
        "empty_answers",
        "missing_roi_choice",
        "empty_roi_choices",
        "extra_roi_choice",
        "invalid_answer_option",
        "invalid_roi_option",
        "empty_recommendations",
        "extra_recommendation_key",
        "missing_package_key",
        "empty_package_deliverables",
        "negative_roi_savings",
        "nonfinite_roi_savings",
        "component_over_domain_max",
        "boolean_dimension_score",
        "boolean_overall_score",
        "boolean_match_score",
        "boolean_component_score",
        "boolean_roi_money",
        "boolean_coefficient",
        "boolean_scenario_week",
        "boolean_package_support_days",
        "boolean_roadmap_year",
        "missing_selected_roi_band",
        "extra_selected_roi_band",
        "extra_roadmap_key",
    ),
)
def test_frozen_v2_snapshot_rejects_schema_cardinality_and_domain_corruption(
    completed_assessment, client, monkeypatch, corruption
):
    snapshot = _snapshot(completed_assessment)
    if corruption == "extra_top_level_section":
        snapshot["future_section"] = {}
    elif corruption == "extra_nested_score_key":
        snapshot["scores"]["future_score"] = 1
    elif corruption == "missing_answer":
        snapshot["assessment"]["answers"].pop(QUESTION_CODES[-1])
    elif corruption == "empty_answers":
        snapshot["assessment"]["answers"] = {}
    elif corruption == "missing_roi_choice":
        snapshot["assessment"]["roi_choices"].pop("budget")
    elif corruption == "empty_roi_choices":
        snapshot["assessment"]["roi_choices"] = {}
    elif corruption == "extra_roi_choice":
        snapshot["assessment"]["roi_choices"]["future_input"] = "future_band"
    elif corruption == "invalid_answer_option":
        snapshot["assessment"]["answers"][QUESTION_CODES[0]] = "level_9"
    elif corruption == "invalid_roi_option":
        snapshot["assessment"]["roi_choices"]["headcount"] = "not_a_band"
    elif corruption == "empty_recommendations":
        snapshot["recommendations"] = []
    elif corruption == "extra_recommendation_key":
        snapshot["recommendations"][0]["future_detail"] = "not frozen"
    elif corruption == "missing_package_key":
        snapshot["recommendations"][0]["package"].pop("acceptance")
    elif corruption == "empty_package_deliverables":
        snapshot["recommendations"][0]["package"]["deliverables"] = []
    elif corruption == "negative_roi_savings":
        snapshot["roi"]["midpoint"]["annual_savings"] = "-1"
    elif corruption == "nonfinite_roi_savings":
        snapshot["roi"]["midpoint"]["annual_savings"] = "NaN"
    elif corruption == "component_over_domain_max":
        snapshot["recommendations"][0]["components"]["pain"] = 36
    elif corruption == "boolean_dimension_score":
        snapshot["scores"]["dimension_scores"]["data"] = True
    elif corruption == "boolean_overall_score":
        snapshot["scores"]["overall_score"] = True
    elif corruption == "boolean_match_score":
        snapshot["recommendations"][0]["match_score"] = True
    elif corruption == "boolean_component_score":
        snapshot["recommendations"][0]["components"]["pain"] = True
    elif corruption == "boolean_roi_money":
        snapshot["roi"]["midpoint"]["annual_savings"] = True
    elif corruption == "boolean_coefficient":
        snapshot["calculation_basis"]["coefficients"]["efficiency"][0] = True
    elif corruption == "boolean_scenario_week":
        snapshot["recommendations"][0]["scenario"]["delivery_weeks"][
            "min"
        ] = True
    elif corruption == "boolean_package_support_days":
        snapshot["recommendations"][0]["package"]["support_days"] = True
    elif corruption == "boolean_roadmap_year":
        snapshot["roadmap_years_1_3"][0]["year"] = True
    elif corruption == "missing_selected_roi_band":
        snapshot["calculation_basis"]["selected_roi_bands"].pop("budget")
    elif corruption == "extra_selected_roi_band":
        snapshot["calculation_basis"]["selected_roi_bands"]["future_input"] = {
            "low": "1",
            "mid": "2",
            "high": "3",
        }
    else:
        snapshot["roadmap_90_days"][0]["future_detail"] = "not frozen"

    assessment_id = _clone_assessment(
        completed_assessment, json.dumps(snapshot, ensure_ascii=False)
    )
    with client.session_transaction() as session:
        session["assessment_report_ids"] = [assessment_id]

    def unexpected_render(*args, **kwargs):
        pytest.fail("corrupt snapshot reached the PDF renderer")

    monkeypatch.setattr(report_pdf, "render_pdf", unexpected_render)

    for suffix in ("", "/pdf"):
        response = client.get(f"/assessment/report/{assessment_id}{suffix}")
        assert response.status_code == 404
        _assert_private_cache_headers(response)


def test_html_report_renders_every_required_snapshot_section(
    completed_assessment, client
):
    response = client.get(f"/assessment/report/{completed_assessment}")
    page = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    assert page.select_one('meta[name="robots"]')["content"] == (
        "noindex,nofollow,noarchive"
    )
    assert page.select_one('link[href="/static/css/report.css"]')
    assert page.select_one("main.report-page[data-snapshot-sha256]")

    table = page.select_one("#readiness-scores table")
    assert table is not None
    assert table.select_one("caption")
    rows = table.select("tbody tr")
    assert len(rows) == 6
    assert all(row.select_one('th[scope="row"]') for row in rows)
    assert [
        [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        for row in rows
    ] == [
        ["业务价值", "100", "60"],
        ["流程基础", "100", "55"],
        ["数据基础", "100", "55"],
        ["系统基础", "100", "50"],
        ["组织准备", "100", "50"],
        ["落地条件", "100", "55"],
    ]

    radar = page.select_one('#readiness-radar[role="img"]')
    assert radar is not None
    assert radar.select_one("title")
    assert radar.select_one("desc")
    assert len(radar.select("line.radar-axis")) == 6
    assert radar.select_one("polygon.radar-score")
    assert radar.select_one("polygon.radar-reference")

    assert page.select_one("#strengths")
    assert page.select_one("#weaknesses")
    assert page.select_one("#recommendations .recommendation-card")
    assert len(page.select("#roi .roi-band")) == 3
    assert _roi_basis_rows(page) == EXPECTED_ROI_BASIS_ROWS
    assert len(page.select("#roadmap-90-days li")) == 4
    assert len(page.select("#roadmap-years li")) == 3
    assert page.select_one("#risks li")
    package = page.select_one("#service-packages .service-package")
    assert package is not None
    for selector in (
        ".package-budget",
        ".package-timeline",
        ".package-deliverables",
        ".package-cooperation",
        ".package-exclusions",
        ".package-acceptance",
        ".package-support",
    ):
        assert package.select_one(selector), selector
    assert "本报告由平台规则自动生成" in page.select_one(
        "#report-disclaimer"
    ).get_text(" ", strip=True)
    for private_value in PRIVATE_VALUES:
        assert private_value not in response.get_data(as_text=True)


def test_pdf_uses_the_same_snapshot_and_a_trusted_local_base_url(
    completed_assessment, client, monkeypatch
):
    html_response = client.get(f"/assessment/report/{completed_assessment}")
    browser_page = BeautifulSoup(html_response.data, "html.parser")
    captured = {}

    def render(html, base_url):
        captured.update(html=html, base_url=base_url)
        return b"%PDF-test"

    monkeypatch.setattr(report_pdf, "render_pdf", render)
    session_cookie = client.get_cookie("session")
    assert session_cookie is not None
    client.set_cookie(
        "session",
        session_cookie.value,
        domain="attacker.example",
        secure=True,
    )
    response = client.get(
        f"/assessment/report/{completed_assessment}/pdf",
        base_url="https://attacker.example:8443",
    )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data == b"%PDF-test"
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="ai-readiness-report-{completed_assessment}.pdf"'
    )
    _assert_private_cache_headers(response)
    assert captured["base_url"].startswith("file:///")
    assert "attacker.example" not in captured["base_url"]

    pdf_page = BeautifulSoup(captured["html"], "html.parser")
    assert not pdf_page.select("link,script,img")
    assert "attacker.example" not in captured["html"]
    assert pdf_page.select_one("main.report-page")["data-snapshot-sha256"] == (
        browser_page.select_one("main.report-page")["data-snapshot-sha256"]
    )
    assert pdf_page.select_one("#readiness-scores").get_text(
        " ", strip=True
    ) == browser_page.select_one("#readiness-scores").get_text(" ", strip=True)
    assert _roi_basis_rows(pdf_page) == EXPECTED_ROI_BASIS_ROWS
    assert _roi_basis_rows(pdf_page) == _roi_basis_rows(browser_page)


def test_reinit_reconciles_stale_catalog_and_preserves_legacy_snapshot_digest(
    completed_assessment, client, monkeypatch
):
    manifest = load_core_catalog_manifest()
    frozen_services = {service["code"]: service for service in manifest["services"]}
    legacy_snapshot = _snapshot(completed_assessment)
    for recommendation in legacy_snapshot["recommendations"]:
        code = recommendation["package"]["code"]
        recommendation["package"]["not_included"] = list(
            LEGACY_SERVICE_EXCLUSIONS[code]
        )
    _replace_snapshot(completed_assessment, legacy_snapshot)
    raw_legacy_snapshot = _raw_snapshot(completed_assessment)
    legacy_digest = hashlib.sha256(
        json.dumps(
            legacy_snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    db = models.get_db()
    try:
        db.executemany(
            "UPDATE services SET not_included_json=? "
            "WHERE code=? AND status='published'",
            [
                (
                    json.dumps(values, ensure_ascii=False, separators=(",", ":")),
                    code,
                )
                for code, values in LEGACY_SERVICE_EXCLUSIONS.items()
            ],
        )
        db.commit()
    finally:
        db.close()

    models.init_db()
    config = client.get("/api/v2/assessment/config/manufacturing")
    new_assessment = _complete_assessment(client)
    captured = {}

    def render(html, base_url):
        captured["html"] = html
        return b"%PDF-test"

    monkeypatch.setattr(report_pdf, "render_pdf", render)
    html = client.get(f"/assessment/report/{completed_assessment}")
    pdf = client.get(f"/assessment/report/{completed_assessment}/pdf")
    fresh_html = client.get(f"/assessment/report/{new_assessment}")

    assert config.status_code == 200
    assert html.status_code == 200
    assert pdf.status_code == 200
    assert fresh_html.status_code == 200
    pages = (
        BeautifulSoup(html.data, "html.parser"),
        BeautifulSoup(captured["html"], "html.parser"),
        BeautifulSoup(fresh_html.data, "html.parser"),
    )
    legacy_phrases = {
        phrase for values in LEGACY_SERVICE_EXCLUSIONS.values() for phrase in values
    }
    for page in pages:
        visible = page.get_text(" ", strip=True)
        assert all(phrase not in visible for phrase in legacy_phrases)
    for recommendation in legacy_snapshot["recommendations"]:
        code = recommendation["package"]["code"]
        for page in pages[:2]:
            visible = page.get_text(" ", strip=True)
            assert all(
                phrase in visible
                for phrase in frozen_services[code]["not_included"]
            )
    for page in pages[:2]:
        assert page.select_one("main.report-page")["data-snapshot-sha256"] == (
            legacy_digest
        )
    assert _raw_snapshot(completed_assessment) == raw_legacy_snapshot

    db = models.get_db()
    try:
        stored_exclusions = {
            row["code"]: json.loads(row["not_included_json"])
            for row in db.execute(
                "SELECT code,not_included_json FROM services "
                "WHERE code IN ({})".format(
                    ",".join("?" for _ in frozen_services)
                ),
                tuple(frozen_services),
            )
        }
    finally:
        db.close()
    assert stored_exclusions == {
        code: service["not_included"] for code, service in frozen_services.items()
    }


def test_unknown_custom_service_snapshot_remains_private_404(
    completed_assessment, client, monkeypatch
):
    snapshot = _snapshot(completed_assessment)
    snapshot["recommendations"][0]["package"]["not_included"] = [
        "客户自定义边界"
    ]
    _replace_snapshot(completed_assessment, snapshot)

    def unexpected_render(*args, **kwargs):
        pytest.fail("custom snapshot reached the PDF renderer")

    monkeypatch.setattr(report_pdf, "render_pdf", unexpected_render)

    for suffix in ("", "/pdf"):
        response = client.get(f"/assessment/report/{completed_assessment}{suffix}")
        assert response.status_code == 404
        _assert_private_cache_headers(response)


def test_shared_report_localizes_codes_formats_money_and_defines_safe_pdf_pages(
    completed_assessment, client, monkeypatch
):
    snapshot = _snapshot(completed_assessment)
    snapshot["roi"]["conservative"]["annual_savings"] = "1234567.8"
    snapshot["roi"]["conservative"]["three_year_net"] = "-89779.31"
    _replace_snapshot(completed_assessment, snapshot)
    captured = {}

    def render(html, base_url):
        captured["html"] = html
        return b"%PDF-test"

    monkeypatch.setattr(report_pdf, "render_pdf", render)
    html = client.get(f"/assessment/report/{completed_assessment}")
    pdf = client.get(f"/assessment/report/{completed_assessment}/pdf")

    assert html.status_code == 200
    assert pdf.status_code == 200
    browser_page = BeautifulSoup(html.data, "html.parser")
    pdf_page = BeautifulSoup(captured["html"], "html.parser")
    expected_integrations = {"low": "低", "medium": "中", "high": "高"}
    expected_categories = {
        "foundation": "基础准备",
        "pilot": "试点验证",
        "standard": "标准交付",
        "integration": "集成交付",
    }
    english_exclusions = (
        "software development",
        "system integration",
        "data cleansing execution",
        "source-document creation",
        "unrestricted internet answers",
        "custom core-system integration",
        "media spend",
        "guaranteed conversion results",
        "unapproved automated outreach",
        "unstable processes",
        "unlisted system interfaces",
        "removal of manual fallback",
        "source-system repair",
        "historical data reconstruction",
        "unagreed predictive models",
        "unlisted connectors",
        "production infrastructure procurement",
        "guaranteed business outcomes",
    )

    for page in (browser_page, pdf_page):
        visible = page.get_text(" ", strip=True)
        assert "¥1,234,567.80" in visible
        assert "-¥89,779.31" in visible
        assert "¥-89,779.31" not in visible
        budgets = [
            node.get_text(" ", strip=True)
            for node in page.select(".package-budget")
        ]
        assert any("¥100,000—¥250,000" in budget for budget in budgets)
        assert all(".0" not in budget for budget in budgets)
        for recommendation in snapshot["recommendations"]:
            scenario = recommendation["scenario"]
            package = recommendation["package"]
            assert (
                f"集成级别：{expected_integrations[scenario['integration_level']]}"
                in visible
            )
            assert expected_categories[package["category"]] in visible
            assert scenario["code"] not in visible
            assert scenario["integration_level"] not in visible
            assert package["category"] not in visible
            for risk in recommendation["risks"]:
                assert risk["code"] not in visible
        assert all(item not in visible for item in english_exclusions)
        risk_labels = [
            node.get_text(" ", strip=True) for node in page.select("#risks strong")
        ]
        assert risk_labels
        assert all(re.fullmatch(r"[\u4e00-\u9fff]+", label) for label in risk_labels)

    pdf_css = pdf_page.select_one("style").get_text(" ", strip=True)
    assert "@bottom-center" in pdf_css
    assert "counter(page)" in pdf_css
    assert "counter(pages)" in pdf_css
    section_rule = re.search(r"\.report-section\s*\{([^}]*)\}", pdf_css)
    assert section_rule is not None
    assert "break-inside" not in section_rule.group(1)
    assert re.search(
        r"\.report-section-heading\s*\{[^}]*break-after:\s*avoid", pdf_css
    )
    assert re.search(
        r"[^{}]*\.package-details\s*>\s*section[^{}]*"
        r"\{[^}]*break-inside:\s*avoid",
        pdf_css,
    )
    assert re.search(
        r"[^{}]*\.score-layout[^{}]*\{[^}]*break-inside:\s*avoid",
        pdf_css,
    )
    assert re.search(
        r"\.service-package\s+header\s*\{[^}]*break-after:\s*avoid",
        pdf_css,
    )
    service_rule = re.search(r"\.service-package\s*\{([^}]*)\}", pdf_css)
    assert service_rule is not None
    assert "break-inside: avoid" in service_rule.group(1)
    assert _snapshot(completed_assessment) == snapshot


def test_renderer_failure_is_safe_and_keeps_report_and_session(
    completed_assessment, client, monkeypatch, caplog
):
    before = _snapshot(completed_assessment)
    with client.session_transaction() as session:
        before_ids = list(session["assessment_report_ids"])

    def fail_render(html, base_url):
        raise RuntimeError("private@example.invalid renderer internals")

    monkeypatch.setattr(report_pdf, "render_pdf", fail_render)
    response = client.get(f"/assessment/report/{completed_assessment}/pdf")

    assert response.status_code == 503
    assert "PDF 暂时无法生成" in response.get_data(as_text=True)
    assert "renderer internals" not in response.get_data(as_text=True)
    assert PRIVATE_VALUES[3] not in response.get_data(as_text=True)
    assert "renderer internals" not in caplog.text
    assert PRIVATE_VALUES[3] not in caplog.text
    _assert_private_cache_headers(response)
    assert _snapshot(completed_assessment) == before
    with client.session_transaction() as session:
        assert session["assessment_report_ids"] == before_ids
    assert client.get(f"/assessment/report/{completed_assessment}").status_code == 200


def test_report_templates_autoescape_snapshot_text(
    completed_assessment, client, monkeypatch
):
    snapshot = _snapshot(completed_assessment)
    unsafe = '<script data-report-xss="1">alert(1)</script>'
    snapshot["scores"]["strongest"]["explanation"] = unsafe
    _replace_snapshot(completed_assessment, snapshot)
    captured = {}

    def render(html, base_url):
        captured["html"] = html
        return b"%PDF-test"

    monkeypatch.setattr(report_pdf, "render_pdf", render)

    html = client.get(f"/assessment/report/{completed_assessment}")
    pdf = client.get(f"/assessment/report/{completed_assessment}/pdf")

    assert html.status_code == 200
    assert pdf.status_code == 200
    browser_page = BeautifulSoup(html.data, "html.parser")
    pdf_page = BeautifulSoup(captured["html"], "html.parser")
    assert not browser_page.select('script[data-report-xss="1"]')
    assert not pdf_page.select('script[data-report-xss="1"]')
    assert unsafe in browser_page.get_text(" ", strip=True)
    assert unsafe in pdf_page.get_text(" ", strip=True)
