import builtins
import importlib
import json
import uuid

from bs4 import BeautifulSoup

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


@pytest.fixture()
def completed_assessment(client):
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


def _snapshot(assessment_id):
    db = models.get_db()
    try:
        value = db.execute(
            "SELECT report_snapshot_json FROM assessments WHERE id=?",
            (assessment_id,),
        ).fetchone()[0]
    finally:
        db.close()
    return json.loads(value)


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
    other = client.application.test_client().get(
        f"/assessment/report/{completed_assessment}"
    )
    with client.session_transaction() as session:
        session.clear()
    cleared = client.get(f"/assessment/report/{completed_assessment}")

    assert allowed.status_code == 200
    assert other.status_code == 404
    assert cleared.status_code == 404
    _assert_private_cache_headers(allowed)
    _assert_private_cache_headers(other)
    _assert_private_cache_headers(cleared)


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
