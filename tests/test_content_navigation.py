"""Task 11 navigation, homepage, metadata, and compatibility contracts."""

from datetime import datetime
import hashlib
from urllib.parse import urlsplit
import uuid

from bs4 import BeautifulSoup
import pytest

import legacy_content_migration
import models
import content_repository
from content_clock import SHANGHAI
from publishing_service import archive_content, publish_content, schedule_content
from source_url_checker import FetchResult


NOW = datetime(2026, 8, 25, 10, 0, tzinfo=SHANGHAI)

REQUIRED_RENDERED_SURFACES = frozenset(
    {
        "public.home",
        "public.assessment",
        "public.about",
        "report.valid",
        "report.missing",
        "industries.list",
        "industries.detail",
        "scenarios.list",
        "scenarios.detail",
        "services.list",
        "services.detail",
        "cases.list",
        "cases.detail",
        "resources.list",
        "resources.detail",
        "announcements.home-list",
        "announcements.detail",
        "admin.login",
        "admin.dashboard",
        "admin.catalog.industries.list",
        "admin.catalog.industries.edit",
        "admin.catalog.scenarios.list",
        "admin.catalog.scenarios.edit",
        "admin.catalog.services.list",
        "admin.catalog.services.edit",
        "admin.cases.list",
        "admin.cases.edit",
        "admin.resources.list",
        "admin.resources.edit",
        "admin.announcements.list",
        "admin.announcements.edit",
        "admin.media",
        "admin.assessments",
        "admin.leads",
        "admin.leads.edit",
        "admin.appointments",
        "admin.data-requests",
    }
)
ASSESSMENT_QUESTION_CODES = (
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
TRUSTED_RENDERED_CONTACTS = frozenset({"tel:4001803358"})


def _page(response):
    return BeautifulSoup(response.data, "html.parser")


def _resource_form(**overrides):
    form = {
        "csrf_token": "test-csrf-token",
        "action": "publish",
        "slug": "legacy-article-target",
        "title": "经审核的迁移资源",
        "summary": "只允许通过当前 clean 映射访问的公开资源。",
        "seo_title": "经审核的迁移资源",
        "seo_description": "经审核的迁移资源摘要。",
        "share_image_media_id": "",
        "resource_type": "article",
        "is_original": "1",
        "source_name": "",
        "source_url": "",
        "original_published_at": "2026-08-20T09:30",
        "copyright_notice": "本站原创，转载请保留版权说明。",
        "attachment_media_id": "",
        "review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "正文",
        "blocks-0-body": "<p>已审核资源正文</p>",
        "blocks-0-media_id": "",
    }
    form.update(overrides)
    return form


def _case_form(**overrides):
    form = {
        "csrf_token": "test-csrf-token",
        "action": "publish",
        "slug": "matrix-verified-case",
        "title": "矩阵验证案例",
        "summary": "只用于验证已发布案例页面的链接上下文。",
        "seo_title": "矩阵验证案例",
        "seo_description": "验证案例列表与详情链接。",
        "share_image_media_id": "",
        "verification_code": "authorized_anonymous",
        "is_verified": "1",
        "basis_type": "internal_delivery_record",
        "private_basis_reference": "matrix-private-record",
        "source_url": "",
        "review_confirmed": "1",
        "privacy_review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "实施过程",
        "blocks-0-body": "<p>公开实施过程。</p>",
        "blocks-0-media_id": "",
        "metrics-0-name": "处理时间",
        "metrics-0-before_value": "8",
        "metrics-0-after_value": "2",
        "metrics-0-unit": "小时",
        "metrics-0-statistical_period": "连续 30 天",
        "metrics-0-evidence_explanation": "依据授权交付记录复核。",
    }
    form.update(overrides)
    return form


def _announcement_form(**overrides):
    form = {
        "csrf_token": "test-csrf-token",
        "action": "publish",
        "slug": "matrix-current-announcement",
        "title": "矩阵当前公告",
        "summary": "验证当前公告的内部 CTA。",
        "seo_title": "矩阵当前公告",
        "seo_description": "验证公告列表与详情链接。",
        "share_image_media_id": "",
        "valid_from": "2026-08-25T09:00",
        "valid_until": "2026-08-30T09:00",
        "cta_url": "/assessment",
        "review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "公告正文",
        "blocks-0-body": "<p>当前有效公告。</p>",
        "blocks-0-media_id": "",
    }
    form.update(overrides)
    return form


class _SuccessfulSourceTransport:
    def fetch(self, url, **kwargs):
        return FetchResult(True, "https_ok", url, 200, "text/html", b"ok")


def _ready_pdf_asset(db):
    digest = hashlib.sha256(b"matrix-reviewed-pdf").hexdigest()
    asset_id = db.execute(
        "INSERT INTO media_assets "
        "(storage_name,display_name,detected_mime,byte_size,sha256,status,"
        "created_at,updated_at) VALUES (?,?, 'application/pdf',1,?,'pending',?,?)",
        (
            "matrix-reviewed.pdf",
            "matrix-reviewed.pdf",
            digest,
            "2026-08-25 10:00:00",
            "2026-08-25 10:00:00",
        ),
    ).lastrowid
    db.execute(
        "UPDATE media_assets SET status='ready',scan_result_code='safe',"
        "scan_checked_at='2026-08-25 10:00:00',"
        "ready_at='2026-08-25 10:00:00',updated_at='2026-08-25 10:00:00' "
        "WHERE id=?",
        (asset_id,),
    )
    db.commit()
    return asset_id


def _complete_matrix_assessment(client):
    client.application.config.update(
        {
            "PRIVACY_PROCESSOR_NAME": "测试处理者",
            "PRIVACY_CONTACT": "privacy@example.invalid",
            "PRIVACY_POLICY_URL": "https://example.invalid/privacy",
        }
    )
    config = client.get("/api/v2/assessment/config/manufacturing")
    assert config.status_code == 200
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
                "answers": {
                    code: "level_3" for code in ASSESSMENT_QUESTION_CODES
                },
                "roi_choices": {
                    "headcount": "6_20",
                    "monthly_hours": "20_80",
                    "monthly_cost": "8000_15000",
                    "loss_factor": "normal",
                    "budget": "50000_200000",
                },
            },
            "contact": {
                "company_name": "矩阵示例企业",
                "contact_name": "张先生",
                "phone": "13800138000",
                "email": "matrix@example.invalid",
                "wechat": "matrix-wechat",
            },
            "consent": {"accepted": True, "policy_version": "2026-08-19"},
            "attribution": {
                "source": "website_assessment",
                "utm_source": "organic",
                "utm_medium": "website",
                "utm_campaign": "task-11-url-matrix",
            },
        },
        headers={"X-CSRF-Token": config.get_json()["csrf_token"]},
    )
    assert response.status_code == 200
    return response.get_json()["assessment_id"]


def _publish_url_matrix_content(client, admin_client, db):
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW
    admin_client.application.config["CONTENT_NOW_PROVIDER"] = lambda: NOW
    db.execute(
        "UPDATE content_items SET status='published',published_at=? "
        "WHERE entry_type IN ('industry','scenario') AND status='draft'",
        ("2026-08-25 10:00:00",),
    )
    db.commit()
    service = db.execute(
        "SELECT ci.* FROM content_items ci JOIN content_groups g "
        "ON g.id=ci.content_group_id JOIN services svc ON svc.id=g.service_id "
        "WHERE ci.entry_type='service' AND ci.status='draft' "
        "AND svc.code='foundation_workshop'"
    ).fetchone()
    publish_content(
        service["id"], service["lock_version"], actor="test-admin", now=NOW
    )

    case_response = admin_client.post("/admin/cases/new", data=_case_form())
    assert case_response.status_code == 302
    case = db.execute(
        "SELECT * FROM content_items WHERE entry_type='case' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()

    attachment_id = _ready_pdf_asset(db)
    source_url = "https://example.com/research/matrix-report"
    resource = _published_resource(
        admin_client,
        db,
        action="save",
        slug="matrix-sourced-resource",
        resource_type="report",
        is_original="0",
        source_name="公开研究机构",
        source_url=source_url,
        copyright_notice="原文版权归公开研究机构所有。",
        attachment_media_id=str(attachment_id),
        **{
            "blocks-0-type": "cta",
            "blocks-0-title": "继续阅读",
            "blocks-0-body": "",
            "blocks-0-media_id": "",
            "blocks-0-cta_label": "访问公开材料",
            "blocks-0-cta_url": "https://example.com/material",
            "blocks-0-cta_style": "secondary",
        },
    )
    normalized_source = db.execute(
        "SELECT source_url FROM resource_content WHERE content_item_id=?",
        (resource["id"],),
    ).fetchone()["source_url"]
    admin_client.application.config[
        "RESOURCE_SOURCE_TRANSPORT"
    ] = _SuccessfulSourceTransport()
    source_check = admin_client.post(
        f"/admin/resources/{resource['id']}/source-check",
        data={
            "csrf_token": "test-csrf-token",
            "expected_lock_version": str(resource["lock_version"]),
            "expected_url_sha256": hashlib.sha256(
                normalized_source.encode()
            ).hexdigest(),
        },
    )
    assert source_check.status_code == 302
    resource = db.execute(
        "SELECT * FROM content_items WHERE id=?", (resource["id"],)
    ).fetchone()
    publish_content(
        resource["id"], resource["lock_version"], actor="test-admin", now=NOW
    )

    announcement_response = admin_client.post(
        "/admin/announcements/new", data=_announcement_form()
    )
    assert announcement_response.status_code == 302
    announcement = db.execute(
        "SELECT * FROM content_items WHERE entry_type='announcement' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assessment_id = _complete_matrix_assessment(client)
    lead_id = db.execute(
        "SELECT lead_id FROM assessments WHERE id=?", (assessment_id,)
    ).fetchone()["lead_id"]

    identities = {}
    for kind, column, slug in (
        ("industry", "industry_id", "manufacturing"),
        ("scenario", "scenario_id", "mfg-knowledge-assistant"),
        ("service", "service_id", "foundation-workshop"),
    ):
        identities[kind] = db.execute(
            f"SELECT ci.slug,g.{column} AS core_id FROM content_items ci "
            "JOIN content_groups g ON g.id=ci.content_group_id "
            "WHERE ci.entry_type=? AND ci.status='published' AND ci.slug=?",
            (kind, slug),
        ).fetchone()
    return {
        "industry": identities["industry"],
        "scenario": identities["scenario"],
        "service": identities["service"],
        "case": case,
        "resource": resource,
        "resource_source": normalized_source,
        "resource_attachment_id": attachment_id,
        "announcement": announcement,
        "assessment_id": assessment_id,
        "lead_id": lead_id,
    }


def _published_resource(admin_client, db, **overrides):
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW
    admin_client.application.config["CONTENT_NOW_PROVIDER"] = lambda: NOW
    response = admin_client.post("/admin/resources/new", data=_resource_form(**overrides))
    assert response.status_code == 302
    return db.execute(
        "SELECT * FROM content_items WHERE entry_type='resource' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _mapped_legacy_article(admin_client, db, *, target_action="publish"):
    target = _published_resource(admin_client, db, action=target_action)
    cursor = db.execute(
        "INSERT INTO articles (title,source,source_url,summary,content_html,status) "
        "VALUES (?,?,?,?,?,?)",
        (
            "待迁移的 legacy 文章",
            "经审核来源",
            "https://example.com/legacy-article",
            "legacy 摘要",
            "<p>legacy 正文</p>",
            "published",
        ),
    )
    legacy_id = cursor.lastrowid
    db.commit()
    review_item = next(
        item
        for item in legacy_content_migration.inventory_legacy_content(db)
        if item.source_table == "articles" and item.source_id == legacy_id
    )
    timestamp = "2026-08-25 10:00:00"
    db.execute(
        "INSERT INTO legacy_content_reviews "
        "(source_table,source_id,title_summary,source_checksum,proposed_action,"
        "reason_code,decision_action,decision_at,decision_source_checksum,"
        "source_state,target_type,target_group,created_at,updated_at) "
        "VALUES ('articles',?,?,?,?,?,'clean',?,?, 'reachable','resource',NULL,?,?)",
        (
            legacy_id,
            review_item.title_summary,
            review_item.source_checksum,
            review_item.proposed_action,
            review_item.reason_code,
            timestamp,
            review_item.source_checksum,
            timestamp,
            timestamp,
        ),
    )
    db.execute(
        "INSERT INTO legacy_content_mappings "
        "(source_table,source_id,source_checksum,target_content_group_id,"
        "target_content_item_id,created_at,updated_at) "
        "VALUES ('articles',?,?,?,?,?,?)",
        (
            legacy_id,
            review_item.source_checksum,
            target["content_group_id"],
            target["id"],
            timestamp,
            timestamp,
        ),
    )
    db.commit()
    return legacy_id, target, review_item.source_checksum


def test_navigation_matches_confirmed_information_architecture(client):
    page = _page(client.get("/"))

    assert [
        link.get_text(" ", strip=True)
        for link in page.select("[data-primary-navigation] > a")
    ] == ["行业方案", "AI 场景", "服务与交付", "案例与资源", "关于我们"]
    assert page.select_one('[data-primary-cta][href="/assessment"]') is not None


def test_homepage_never_falls_back_to_unreviewed_legacy_content(client):
    response = client.get("/")
    page = _page(response)

    assert response.status_code == 200
    assert b"case_source_or_metric_unverified" not in response.data
    assert "某中型制造企业 RAG 知识库落地" not in response.get_data(as_text=True)
    assert "27+" not in page.get_text(" ", strip=True)
    assert "查看全部 27 个案例" not in page.get_text(" ", strip=True)
    assert page.select_one('[data-content-section="home-cases"]') is None
    assert page.select_one('[data-content-section="home-resources"]') is None
    assert page.select_one('[data-content-section="home-announcements"]') is None


def test_legacy_catalog_aliases_are_fixed_query_dropping_redirects(client):
    services = client.get("/services?source=legacy")
    insights = client.get("/insights?category=announcement&tag=RAG&next=https://evil.test")

    assert services.status_code == 301
    assert services.headers["Location"] == "/service-packages"
    assert insights.status_code == 301
    assert insights.headers["Location"] == "/resources"


def test_home_canonical_uses_only_the_validated_public_base_url(client):
    response = client.get(
        "/?next=https://evil.test",
        headers={"Host": "attacker.example", "X-Forwarded-Host": "forwarded.example"},
    )
    canonical = _page(response).select_one('link[rel="canonical"]')

    assert canonical is not None
    assert canonical["href"] == "https://test.example/"


@pytest.mark.parametrize("path", ("/assessment", "/about"))
def test_public_legacy_shell_pages_have_configured_canonical(client, path):
    response = client.get(
        f"{path}?ignored=1",
        headers={"Host": "attacker.example", "X-Forwarded-Host": "forwarded.example"},
    )
    canonical = _page(response).select_one('link[rel="canonical"]')

    assert canonical is not None
    assert canonical["href"] == f"https://test.example{path}"


def test_private_html_surfaces_have_template_and_header_noindex(client, admin_client):
    anonymous = client.application.test_client()
    surfaces = (
        (anonymous, "/admin/login"),
        (anonymous, "/assessment/report/999"),
        (admin_client, "/admin/data-requests"),
    )
    for surface_client, path in surfaces:
        response = surface_client.get(path)
        robots = _page(response).select_one('meta[name="robots"]')

        assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
        assert robots is not None, path
        directives = {
            directive.strip().lower()
            for directive in robots.get("content", "").split(",")
        }
        assert {"noindex", "nofollow"} <= directives
        assert response.headers["Cache-Control"] == "private, no-store"


def test_mobile_navigation_is_native_keyboard_operable(client):
    page = _page(client.get("/"))
    menu = page.select_one("details[data-mobile-navigation]")

    assert menu is not None
    assert menu.select_one("summary") is not None
    assert menu.select_one('a[href="/industries"]') is not None
    assert menu.select_one('a[href="/assessment"]') is not None

    stylesheet = client.get("/static/css/app.css")
    assert stylesheet.status_code == 200
    assert ":focus-visible" in stylesheet.get_data(as_text=True)


def _rendered_html(test_client, path, expected_status=200):
    response = test_client.get(path)
    assert response.status_code == expected_status, path
    assert response.mimetype == "text/html", path
    return _page(response)


def _is_verified_same_document_fragment(document, href, parsed):
    fragment = parsed.fragment
    return (
        href.startswith("#")
        and not parsed.scheme
        and not parsed.netloc
        and not parsed.path
        and not parsed.query
        and fragment
        and "%" not in fragment
        and not fragment.lower().startswith(("javascript:", "http:", "https:"))
        and document.find(id=fragment) is not None
    )


def _assert_rendered_link_matrix(surface, document):
    for link in document.select("a[href]"):
        href = link["href"]
        parsed = urlsplit(href)
        if href.startswith("/") and not href.startswith("//"):
            continue
        if _is_verified_same_document_fragment(document, href, parsed):
            continue
        if parsed.scheme in {"mailto", "tel"}:
            assert href in TRUSTED_RENDERED_CONTACTS, (surface, href)
            assert parsed.scheme == "tel", (surface, href)
            assert link.get("data-analytics-event") == "phone_clicked"
            assert link.get("data-analytics-source") == "footer"
            assert link.get("target") != "_blank"
            continue
        assert parsed.scheme == "https" and parsed.hostname, (surface, href)
        if link.get("target") == "_blank" and parsed.scheme in {"http", "https"}:
            rel = {value.lower() for value in link.get("rel", [])}
            assert {"noopener", "noreferrer"} <= rel, (surface, href)


def test_rendered_link_matrix_accepts_same_document_fragment(client):
    document = _rendered_html(client, "/")
    _assert_rendered_link_matrix("public.home", document)


def test_rendered_link_matrix_accepts_any_verified_same_document_id():
    document = BeautifulSoup(
        '<section id="chapter-42"></section><a href="#chapter-42">chapter</a>',
        "html.parser",
    )

    _assert_rendered_link_matrix("fragment-test", document)


@pytest.mark.parametrize(
    ("href", "target"),
    (
        ("#missing-chapter", ""),
        ("#javascript:alert(1)", '<section id="javascript:alert(1)"></section>'),
        ("#https://attacker.example", '<section id="https://attacker.example"></section>'),
        ("#%6aavascript:alert(1)", '<section id="%6aavascript:alert(1)"></section>'),
        ("#%68ttps:attacker.example", '<section id="%68ttps:attacker.example"></section>'),
        ("#chapter%2D42", '<section id="chapter%2D42"></section>'),
        ("#", ""),
    ),
)
def test_rendered_link_matrix_rejects_unapproved_fragments(href, target):
    document = BeautifulSoup(f'{target}<a href="{href}">unsafe</a>', "html.parser")
    with pytest.raises(AssertionError):
        _assert_rendered_link_matrix("fragment-test", document)


def test_rendered_server_links_follow_the_url_context_matrix(
    client, admin_client, db, monkeypatch
):
    monkeypatch.setattr(
        content_repository,
        "shanghai_now",
        lambda: datetime(2035, 1, 1, 10, 0, tzinfo=SHANGHAI),
    )
    content = _publish_url_matrix_content(client, admin_client, db)
    anonymous = client.application.test_client()
    documents = {
        "public.home": _rendered_html(client, "/"),
        "public.assessment": _rendered_html(client, "/assessment"),
        "public.about": _rendered_html(client, "/about"),
        "report.valid": _rendered_html(
            client, f"/assessment/report/{content['assessment_id']}"
        ),
        "report.missing": _rendered_html(
            client, "/assessment/report/999999", 404
        ),
        "industries.list": _rendered_html(client, "/industries"),
        "industries.detail": _rendered_html(
            client, f"/industries/{content['industry']['slug']}"
        ),
        "scenarios.list": _rendered_html(client, "/scenarios"),
        "scenarios.detail": _rendered_html(
            client, f"/scenarios/{content['scenario']['slug']}"
        ),
        "services.list": _rendered_html(client, "/service-packages"),
        "services.detail": _rendered_html(
            client, f"/service-packages/{content['service']['slug']}"
        ),
        "cases.list": _rendered_html(client, "/cases"),
        "cases.detail": _rendered_html(
            client, f"/cases/{content['case']['slug']}"
        ),
        "resources.list": _rendered_html(client, "/resources"),
        "resources.detail": _rendered_html(
            client, f"/resources/{content['resource']['slug']}"
        ),
        "announcements.home-list": _rendered_html(client, "/"),
        "announcements.detail": _rendered_html(
            client, f"/announcements/{content['announcement']['slug']}"
        ),
        "admin.login": _rendered_html(anonymous, "/admin/login"),
        "admin.dashboard": _rendered_html(admin_client, "/admin"),
        "admin.catalog.industries.list": _rendered_html(
            admin_client, "/admin/catalog/industry"
        ),
        "admin.catalog.industries.edit": _rendered_html(
            admin_client,
            f"/admin/catalog/industry/{content['industry']['core_id']}",
        ),
        "admin.catalog.scenarios.list": _rendered_html(
            admin_client, "/admin/catalog/scenario"
        ),
        "admin.catalog.scenarios.edit": _rendered_html(
            admin_client,
            f"/admin/catalog/scenario/{content['scenario']['core_id']}",
        ),
        "admin.catalog.services.list": _rendered_html(
            admin_client, "/admin/catalog/service"
        ),
        "admin.catalog.services.edit": _rendered_html(
            admin_client,
            f"/admin/catalog/service/{content['service']['core_id']}",
        ),
        "admin.cases.list": _rendered_html(admin_client, "/admin/cases"),
        "admin.cases.edit": _rendered_html(
            admin_client, f"/admin/cases/{content['case']['id']}"
        ),
        "admin.resources.list": _rendered_html(admin_client, "/admin/resources"),
        "admin.resources.edit": _rendered_html(
            admin_client, f"/admin/resources/{content['resource']['id']}"
        ),
        "admin.announcements.list": _rendered_html(
            admin_client, "/admin/announcements"
        ),
        "admin.announcements.edit": _rendered_html(
            admin_client, f"/admin/announcements/{content['announcement']['id']}"
        ),
        "admin.media": _rendered_html(admin_client, "/admin/media"),
        "admin.assessments": _rendered_html(admin_client, "/admin/assessments"),
        "admin.leads": _rendered_html(admin_client, "/admin/leads"),
        "admin.leads.edit": _rendered_html(
            admin_client, f"/admin/lead/{content['lead_id']}"
        ),
        "admin.appointments": _rendered_html(admin_client, "/admin/appointments"),
        "admin.data-requests": _rendered_html(
            admin_client, "/admin/data-requests"
        ),
    }

    assert frozenset(documents) == REQUIRED_RENDERED_SURFACES
    for surface, document in documents.items():
        _assert_rendered_link_matrix(surface, document)

    home = documents["public.home"]
    for chapter_id, href in (
        ("story-matching", f"/industries/{content['industry']['slug']}"),
        ("story-purpose", f"/scenarios/{content['scenario']['slug']}"),
        ("story-roadmap", f"/service-packages/{content['service']['slug']}"),
        ("story-evidence", f"/cases/{content['case']['slug']}"),
        ("story-evidence", f"/resources/{content['resource']['slug']}"),
        (
            "story-evidence",
            f"/announcements/{content['announcement']['slug']}",
        ),
    ):
        chapter = home.select_one(f'#{chapter_id}')
        assert chapter is not None
        assert chapter.select_one(f'a[href="{href}"]') is not None

    policy = documents["public.assessment"].select_one("#privacy-policy-link")
    assert policy is not None and not policy.has_attr("href")

    resource = documents["resources.detail"]
    assert resource.select_one("main#main-content.editorial-detail") is not None
    assert resource.select_one(".editorial-meta") is not None
    source = resource.select_one("a[data-resource-source]")
    assert source["href"] == content["resource_source"]
    assert source["href"].startswith("https://")
    assert source["target"] == "_blank"
    assert {"noopener", "noreferrer"} <= set(source["rel"])
    external_cta = resource.select_one('[data-content-block="cta"] a')
    assert external_cta["href"] == "https://example.com/material"
    assert external_cta["target"] == "_blank"
    assert {"noopener", "noreferrer"} <= set(external_cta["rel"])
    attachment = resource.select_one("a[data-resource-attachment]")
    assert attachment["href"] == (
        f"/media/{content['resource_attachment_id']}/download"
    )

    announcement = documents["announcements.detail"]
    assert announcement.select_one("main#main-content.editorial-detail") is not None
    assert announcement.select_one(".editorial-meta") is not None
    internal_cta = announcement.select_one("a[data-announcement-cta]")
    assert internal_cta["href"] == "/assessment"
    assert internal_cta.get("target") is None
    assert documents["announcements.home-list"].select_one(
        f'a[href="/announcements/{content["announcement"]["slug"]}"]'
    ) is not None


def test_privacy_policy_link_has_no_destination_before_validated_config(client):
    policy = _page(client.get("/assessment")).select_one("#privacy-policy-link")

    assert policy is not None
    assert not policy.has_attr("href")
    assert policy.get("target") == "_blank"
    assert {"noopener", "noreferrer"} <= {
        value.lower() for value in policy.get("rel", [])
    }


@pytest.mark.parametrize(
    ("policy_url", "expected_status"),
    (
        ("https://example.invalid/privacy", 200),
        ("http://example.invalid/privacy", 503),
        ("https://example.invalid/%ZZ", 503),
    ),
)
def test_assessment_config_exposes_only_validated_https_policy_url(
    client, policy_url, expected_status
):
    client.application.config.update(
        {
            "PRIVACY_PROCESSOR_NAME": "测试处理者",
            "PRIVACY_CONTACT": "privacy@example.invalid",
            "PRIVACY_POLICY_URL": policy_url,
        }
    )

    response = client.get("/api/v2/assessment/config/manufacturing")

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.get_json()["privacy_disclosure"]["policy_url"] == policy_url
        return
    assert response.get_json() == {
        "error": "assessment temporarily unavailable",
        "recoverable": True,
    }
    assert policy_url.encode() not in response.data
    policy_link = _page(client.get("/assessment")).select_one(
        "#privacy-policy-link"
    )
    assert policy_link is not None
    assert not policy_link.has_attr("href")


def test_legacy_article_redirect_requires_current_clean_published_mapping(
    client, admin_client, db
):
    unmapped = db.execute(
        "INSERT INTO articles (title,source,source_url,status) VALUES (?,?,?,?)",
        (
            "unmapped legacy article",
            "unmapped source",
            "https://example.com/unmapped",
            "published",
        ),
    ).lastrowid
    db.commit()
    legacy_id, target, _ = _mapped_legacy_article(admin_client, db)

    missing = client.get(f"/article/{unmapped}")
    redirect = client.get(f"/article/{legacy_id}")

    assert missing.status_code == 404
    assert redirect.status_code == 301
    assert redirect.headers["Location"] == f"/resources/{target['slug']}"


def test_legacy_article_adapter_uses_the_injected_content_clock(client, monkeypatch):
    calls = []
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: NOW

    def resolve(article_id, now=None):
        calls.append((article_id, now))
        return None

    monkeypatch.setattr(content_repository, "legacy_article_resource_slug", resolve)

    response = client.get("/article/17")

    assert response.status_code == 404
    assert calls == [(17, NOW)]


@pytest.mark.parametrize("article_id", (2**63 - 1, 2**63))
def test_legacy_article_ids_outside_existing_sqlite_rows_fail_closed(
    client, article_id
):
    response = client.get(f"/article/{article_id}")

    assert response.status_code == 404


def test_legacy_article_mapping_fails_closed_when_any_identity_is_polluted(
    client, admin_client, db
):
    legacy_id, _, checksum = _mapped_legacy_article(admin_client, db)
    db.execute(
        "UPDATE legacy_content_mappings SET source_checksum=? "
        "WHERE source_table='articles' AND source_id=?",
        (("f" if checksum[0] != "f" else "e") + checksum[1:], legacy_id),
    )
    db.commit()

    assert client.get(f"/article/{legacy_id}").status_code == 404


def test_legacy_article_mapping_rejects_polluted_review_target_group(
    client, admin_client, db
):
    legacy_id, _, _ = _mapped_legacy_article(admin_client, db)
    db.execute(
        "UPDATE legacy_content_reviews SET target_group='data_insight' "
        "WHERE source_table='articles' AND source_id=?",
        (legacy_id,),
    )
    db.commit()

    assert client.get(f"/article/{legacy_id}").status_code == 404


def test_legacy_article_mapping_rejects_explicitly_stale_review(
    client, admin_client, db
):
    legacy_id, _, _ = _mapped_legacy_article(admin_client, db)
    db.execute(
        "UPDATE legacy_content_reviews SET review_stale_at='2026-08-25 10:00:01' "
        "WHERE source_table='articles' AND source_id=?",
        (legacy_id,),
    )
    db.commit()

    assert client.get(f"/article/{legacy_id}").status_code == 404


@pytest.mark.parametrize("state", ("draft", "future", "archived"))
def test_legacy_article_mapping_fails_closed_for_nonpublic_target_states(
    client, admin_client, db, state
):
    target_action = "publish" if state == "archived" else "save"
    legacy_id, target, _ = _mapped_legacy_article(
        admin_client, db, target_action=target_action
    )
    if state == "future":
        schedule_content(
            target["id"],
            target["lock_version"],
            datetime(2030, 1, 1, tzinfo=SHANGHAI),
            actor="test-admin",
            now=NOW,
        )
    elif state == "archived":
        archive_content(
            target["id"], target["lock_version"], actor="test-admin", now=NOW
        )

    assert client.get(f"/article/{legacy_id}").status_code == 404
