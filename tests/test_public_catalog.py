"""Public, read-only catalog routes use only published catalog aggregates."""

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import re
import sqlite3

import pytest
from bs4 import BeautifulSoup

import app as app_module
import blueprints.public_catalog as public_catalog_blueprint
import catalog_content_repository as catalog
import content_repository
from content_clock import SHANGHAI
from content_contracts import CaseMetric, ContentBlock, ContentDraft, ContentRelation
from content_json import ContentJsonError, decode_database_json
from content_validation import ContentValidationError, is_exact_nonblank_text
import media_service
import publishing_repository
from publishing_service import copy_revision, create_content_draft, publish_content, publish_due_content, save_content_draft, schedule_content
from publishing_service import archive_content


INDUSTRY_REQUIRED_SECTIONS = {
    "overview", "business-pains", "departments", "sme-fit",
    "priority-scenarios", "service-packages", "assessment-cta",
}
SCENARIO_REQUIRED_SECTIONS = {
    "problem-boundary", "industries", "departments", "pains", "maturity",
    "prerequisites", "inputs", "outputs", "steps", "metrics", "risks",
    "timeline", "budget", "services", "assessment-cta",
}
NOW = "2026-08-24 10:00:00"
NOW_DATETIME = datetime(2026, 8, 24, 10, 0, 0, tzinfo=SHANGHAI)


def publish_catalog(db):
    """Promote the checked-in neutral catalog inside this disposable test DB."""
    db.execute(
        "UPDATE content_items SET status='published',published_at=? "
        "WHERE entry_type IN ('industry','scenario') AND status='draft'",
        (NOW,),
    )
    db.commit()


@pytest.fixture()
def published_catalog(client, db):
    publish_catalog(db)
    return client


def page(response):
    assert response.status_code == 200
    return BeautifulSoup(response.data, "html.parser")


def _publish_home_news_items():
    """Publish one truthful resource and one current announcement for home HTTP tests."""
    resource_id = create_content_draft(
        ContentDraft(
            entry_type="resource",
            slug="home-audited-resource",
            title="首页审核资源",
            summary="用于验证首页审核资源行的真实发布内容。",
            seo_title="首页审核资源",
            seo_description="验证首页按公开投影展示审核资源。",
            extension={
                "resource_type": "guide",
                "is_original": 1,
                "source_name": None,
                "source_url": None,
                "source_url_sha256": None,
                "source_check_code": None,
                "source_checked_at": None,
                "source_check_expires_at": None,
                "source_check_url_sha256": None,
                "original_published_at": "2026-08-20 09:30:00",
                "copyright_notice": "本站原创，转载请保留版权说明。",
                "attachment_media_id": None,
            },
            blocks=(
                ContentBlock(
                    "rich_text", "正文", "<p>首页审核资源正文。</p>", {}, None, 0
                ),
            ),
        ),
        actor="test-admin",
        now=NOW_DATETIME,
    )
    publish_content(resource_id, 1, actor="test-admin", now=NOW_DATETIME)

    announcement_id = create_content_draft(
        ContentDraft(
            entry_type="announcement",
            slug="home-current-announcement",
            title="首页当前公告",
            summary="用于验证首页当前公告行的真实发布内容。",
            seo_title="首页当前公告",
            seo_description="验证首页按公开投影展示当前公告。",
            extension={
                "valid_from": "2026-08-24 09:00:00",
                "valid_until": "2026-08-25 09:00:00",
                "cta_url": "/assessment",
            },
            blocks=(
                ContentBlock(
                    "rich_text", "正文", "<p>首页当前公告正文。</p>", {}, None, 0
                ),
            ),
        ),
        actor="test-admin",
        now=NOW_DATETIME,
    )
    publish_content(announcement_id, 1, actor="test-admin", now=NOW_DATETIME)


def _css_declarations(css, selector):
    """Read one public CSS rule as its browser-facing declaration mapping."""
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", css)
    assert match is not None, selector
    return {
        name.strip(): value.strip()
        for declaration in match.group(1).split(";")
        if ":" in declaration
        for name, value in (declaration.split(":", 1),)
    }


def _assert_decision_shell(document):
    """Catch detail pages that drop the shared decision layout or assessment action."""
    assert document.select_one("main#main-content.decision-detail") is not None
    assert len(document.select("main#main-content")) == 1
    assert document.select_one(".detail-hero h1") is not None
    assert document.select_one(".decision-main") is not None
    assert document.select_one(
        'aside.decision-summary[aria-labelledby="decision-summary-title"]'
    ) is not None
    assert document.select_one('.decision-summary a[href="/assessment"]') is not None


@pytest.mark.parametrize(
    "path, context_labels",
    (
        ("/industries/manufacturing", ("适用部门", "企业规模", "优先场景")),
        ("/scenarios/mfg-knowledge-assistant", ("适用行业", "相关部门", "适用痛点")),
    ),
)
def test_catalog_details_keep_verified_theme_context_and_numbered_sections(
    published_catalog, path, context_labels,
):
    """Catch detail pages that separate verified context from the themed hero."""
    document = page(published_catalog.get(path))

    themes = document.select(".detail-theme")
    assert len(themes) == 1
    theme = themes[0]
    assert theme.select_one('.detail-breadcrumb[aria-label="面包屑"]') is not None
    assert theme.select_one(".detail-hero h1") is not None
    context = theme.select_one("dl.detail-context")
    assert context is not None
    assert tuple(node.get_text(" ", strip=True) for node in context.select("dt")) == context_labels

    main_sections = document.select(".decision-main > section:has(h2)")
    assert main_sections
    assert all("decision-section" in node.get("class", ()) for node in main_sections)
    assert len(document.select("main#main-content")) == 1

    if path.startswith("/scenarios/"):
        context_text = context.get_text(" ", strip=True)
        for selector in (
            '[data-content-section="industries"] li',
            '[data-content-section="departments"] li',
            '[data-content-section="pains"] li',
        ):
            assert document.select_one(selector).get_text(" ", strip=True) in context_text
        assert "mfg_knowledge_assistant" not in context_text


def test_industry_detail_uses_real_decision_summary_and_return_link(published_catalog):
    """Catch an industry detail that loses its published decision context or list return."""
    document = page(published_catalog.get("/industries/manufacturing"))

    _assert_decision_shell(document)
    summary = document.select_one(".decision-summary").get_text(" ", strip=True)
    assert "适用部门" in summary
    assert "优先场景" in summary
    assert "周期" in summary
    assert "预算" in summary
    assert "评估后确认" in summary
    assert document.select_one('.decision-summary a[href="/industries"]') is not None


def test_scenario_detail_uses_real_decision_summary(published_catalog):
    """Catch a scenario detail that substitutes unsupported decision claims for published fields."""
    document = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))

    _assert_decision_shell(document)
    summary = document.select_one(".decision-summary").get_text(" ", strip=True)
    assert "适用行业" in summary
    assert "相关部门" in summary
    assert "周期" in summary
    assert "预算" in summary
    assert "评估后确认" in summary or "周" in summary
    assert "已评估" not in summary
    assert "已覆盖" not in summary
    assert document.select_one('.decision-summary a[href="/scenarios"]') is not None


def test_scenario_detail_composes_exactly_three_business_chapters(published_catalog):
    """A storage-field section added back to the main column must break this contract."""
    document = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))
    chapters = document.select(".decision-main > .decision-section")

    assert [chapter.select_one(":scope > h2").get_text(" ", strip=True) for chapter in chapters] == [
        "适用场景",
        "实施路径",
        "关键输入、输出与风险",
    ]
    for marker in SCENARIO_REQUIRED_SECTIONS:
        assert len(document.select(f'[data-content-section="{marker}"]')) == 1, marker
    assert document.select_one('.detail-theme [data-content-section="industries"]') is not None
    assert document.select_one('.detail-theme [data-content-section="departments"]') is not None
    assert document.select_one('.detail-theme [data-content-section="pains"]') is not None
    assert document.select_one('.decision-summary [data-content-section="timeline"]') is not None
    assert document.select_one('.decision-summary [data-content-section="budget"]') is not None
    assert document.select('.decision-main [data-content-section="timeline"]') == []
    assert document.select('.decision-main [data-content-section="budget"]') == []


def test_scenario_summary_is_static_with_one_full_width_action_pair(published_catalog):
    """Sticky, pill-shaped, duplicated, or raw-decimal summary actions must fail."""
    document = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))
    summaries = document.select("aside.decision-summary")
    actions = summaries[0].select_one(":scope > .decision-summary-actions")
    css = published_catalog.get("/static/css/public-pages.css").get_data(as_text=True)

    assert len(summaries) == 1
    assert actions is not None
    assert [link.get_text(" ", strip=True) for link in actions.select("a")] == [
        "获取适配建议",
        "返回场景列表",
    ]
    assert [link.get("href") for link in actions.select("a")] == [
        "/assessment",
        "/scenarios",
    ]
    summary_rules = _css_declarations(css, ".public-scenario-detail .decision-summary")
    action_rules = _css_declarations(css, ".decision-summary-actions .btn")
    assert summary_rules["position"] == "static"
    assert action_rules["width"] == "100%"
    assert action_rules["border-radius"] == "var(--ui-radius-control)"
    summary_text = summaries[0].get_text(" ", strip=True)
    assert "50000.0" not in summary_text
    assert "100000.0" not in summary_text
    assert "¥5万" in summary_text


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected"),
    (
        (10001, 12345, "¥10,001—¥12,345"),
        (50000.5, 100000.25, "¥50,000.5—¥100,000.25"),
        (50000, 100000, "¥5万—¥10万"),
        (0.00001, 0.00002, "¥0.00001—¥0.00002"),
        (
            1e25,
            1.0000000000000003e25,
            "¥10,000,000,000,000,000,000,000,000—"
            "¥10,000,000,000,000,003,000,000,000",
        ),
        (
            10**100,
            10**100 + 1,
            "¥1,000,000,000,000,000,000,000,000,000,000,000,000,000,000,000,000,000,"
            "000,000,000,000,000,000,000,000,000,000,000,000,000,000,000万—¥10,000,000,"
            "000,000,000,000,000,000,000,000,000,000,000,000,000,000,000,000,000,000,"
            "000,000,000,000,000,000,000,000,000,000,000,000,001",
        ),
        pytest.param(
            10**5000 + 1,
            10**5000 + 2,
            "¥100," + "000," * 1665 + "001—¥100," + "000," * 1665 + "002",
            id="beyond-python-integer-string-limit",
        ),
    ),
)
def test_scenario_summary_preserves_exact_published_budget_values(
    published_catalog, db, monkeypatch, minimum, maximum, expected,
):
    """Rounding a legal published budget to a shorter 万 value must fail."""
    if type(minimum) is int and minimum > 2**63 - 1:
        scenario = dict(catalog.public_scenario(
            "mfg-knowledge-assistant", NOW_DATETIME
        ))
        scenario["budget"] = ((minimum, maximum),)
        monkeypatch.setattr(
            public_catalog_blueprint.catalog,
            "public_scenario",
            lambda slug, now: scenario,
        )
    else:
        service = db.execute(
            "SELECT service_id FROM scenario_services link "
            "JOIN scenarios scenario ON scenario.id=link.scenario_id "
            "WHERE scenario.code='mfg_knowledge_assistant' LIMIT 1"
        ).fetchone()
        db.execute(
            "UPDATE services SET min_budget=?,max_budget=? WHERE id=?",
            (minimum, maximum, service["service_id"]),
        )
        db.commit()

    document = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))
    budget = document.select_one(
        '.decision-summary [data-content-section="budget"] dd'
    )

    assert budget.get_text(" ", strip=True) == expected


def test_scenario_filter_groups_controls_and_cards_show_real_metadata(published_catalog):
    """Ungrouped controls or a title-only scenario card must break the catalog design."""
    document = page(published_catalog.get(
        "/scenarios?industry=manufacturing&department=production&maturity=explore"
    ))
    form = document.select_one("form.public-filter.public-filter-panel")

    assert form is not None
    fields = form.select(":scope > .public-filter-fields > .public-filter-field")
    assert [field.select_one("label").get("for") for field in fields] == [
        "industry",
        "department",
        "maturity",
        "per_page",
    ]
    assert [field.select_one("input, select").get("id") for field in fields] == [
        "industry",
        "department",
        "maturity",
        "per_page",
    ]
    assert form.select_one(':scope > .public-filter-actions button[type="submit"]') is not None
    assert document.select_one('#industry[value="manufacturing"]') is not None
    assert document.select_one('#department[value="production"]') is not None
    assert document.select_one('#maturity option[selected][value="explore"]') is not None

    cards = document.select('[data-scenario-code="mfg_knowledge_assistant"] > article.catalog-card')
    assert len(cards) == 1
    metadata = cards[0].select_one("dl.catalog-card-meta")
    assert metadata is not None
    assert [term.get_text(" ", strip=True) for term in metadata.select("dt")] == [
        "行业",
        "部门",
        "成熟度",
    ]
    metadata_text = metadata.get_text(" ", strip=True)
    for published_label in ("制造业", "生产", "探索", "试点"):
        assert published_label in metadata_text
    assert "mfg_knowledge_assistant" not in cards[0].get_text(" ", strip=True)


def test_home_uses_guided_story_with_published_scenario_and_service(published_catalog, db):
    """The homepage keeps every available published collection linked in its story."""
    db.execute(
        "UPDATE content_items SET status='published',published_at=? "
        "WHERE entry_type='service' AND status='draft'",
        (NOW,),
    )
    db.commit()
    document = page(published_catalog.get("/"))
    home_data = content_repository.home_page_data()
    story = document.select_one("[data-guided-story]")

    assert story is not None
    assert document.select_one(".home-hero--navy") is None
    matching = story.select_one("#story-matching")
    roadmap = story.select_one("#story-roadmap")
    assert matching is not None
    assert roadmap is not None
    first_scenario = home_data["scenarios"][0]
    first_service = home_data["services"][0]
    assert matching.select_one(
        f'a[href="/scenarios/{first_scenario.slug}"]'
    ) is not None
    roadmap_product = roadmap.select_one('[data-product-surface="roadmap"]')
    assert roadmap_product is not None
    assert roadmap_product.select_one(
        f'a[href="/service-packages/{first_service.slug}"]'
    ) is not None
    if home_data["cases"]:
        first_case = home_data["cases"][0]
        assert story.select_one(f'a[href="/cases/{first_case.slug}"]') is not None
    if home_data["resources"]:
        first_resource = home_data["resources"][0]
        assert story.select_one(
            f'a[href="/resources/{first_resource.slug}"]'
        ) is not None
    if home_data["announcements"]:
        first_announcement = home_data["announcements"][0]
        assert story.select_one(
            f'a[href="/announcements/{first_announcement.slug}"]'
        ) is not None


def test_home_news_orders_current_announcements_before_resources_and_has_honest_empty_state(
    client,
):
    """The home route must group real current announcements before audited resources."""
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: NOW_DATETIME
    empty_news = page(client.get("/")).select_one('[data-home-section="news"]')

    assert empty_news.select(".home-news-row") == []
    assert empty_news.select_one(".home-news-empty").get_text(" ", strip=True) == (
        "暂无已发布的公告或审核资源。"
    )

    _publish_home_news_items()
    news = page(client.get("/")).select_one('[data-home-section="news"]')
    rows = news.select(".home-news-row")

    assert [row["href"] for row in rows] == [
        "/announcements/home-current-announcement",
        "/resources/home-audited-resource",
    ]
    assert [row.select_one("time")["datetime"] for row in rows] == [
        "2026-08-24 09:00:00",
        "2026-08-20 09:30:00",
    ]
    assert news.select_one(".home-news-empty") is None


def test_home_exposes_five_truthful_guided_story_chapters(published_catalog):
    document = page(published_catalog.get("/"))
    story = document.select_one("[data-guided-story]")
    assert story is not None
    assert [section["id"] for section in story.select("[data-story-chapter]")] == [
        "story-purpose",
        "story-assessment",
        "story-matching",
        "story-roadmap",
        "story-evidence",
    ]
    hero = story.select_one("#story-purpose")
    assert hero.select_one("h1").get_text(" ", strip=True) == (
        "让 AI 转型，从可验证的业务价值开始"
    )
    assert hero.select_one(
        ".home-hero-copy > p:not(.public-eyebrow):not(.home-audit-note)"
    ).get_text(" ", strip=True) == (
        "评估准备度，匹配高价值场景，形成可执行的实施路径。"
    )
    assert [
        link.get_text(" ", strip=True)
        for link in hero.select(".home-hero-actions a")
    ] == ["开始 AI 就绪度评估"]
    assert hero.select_one('a[href="/assessment"]') is not None
    assert story.select_one('[data-capability="assessment"]') is not None
    assert story.select_one('[data-capability="matching"]') is not None
    assert story.select_one('[data-capability="delivery"]') is not None
    assert story.select_one('[data-home-section="applications"]') is not None
    assert story.select_one('[data-home-section="proof"]') is not None
    assert story.select_one('[data-home-section="news"]') is not None
    assert story.select_one('[data-home-section="final-cta"]') is not None
    final_cta = story.select_one('[data-home-section="final-cta"]')
    assert final_cta.select_one("h2").get_text(" ", strip=True) == (
        "确认你的 AI 转型起点"
    )
    assert [
        (link.get_text(" ", strip=True), link.get("href"))
        for link in final_cta.select("a")
    ] == [("开始评估", "/assessment")]
    assert [link["href"] for link in story.select("[data-story-step]")] == [
        "#story-purpose",
        "#story-assessment",
        "#story-matching",
        "#story-roadmap",
        "#story-evidence",
    ]
    assert story.select("video") == []
    assert story.select(
        "[data-customer-logo-wall], .customer-logo-wall, .logo-wall"
    ) == []
    assert story.select("[style]") == []
    assert all(
        image.get("src", "").startswith("/static/")
        for image in story.select("img")
    )


def test_home_guided_story_sections_follow_the_bound_chapter_ownership(
    published_catalog,
):
    """Each visual section belongs to the chapter named by the homepage spec."""
    document = page(published_catalog.get("/"))
    story = document.select_one("[data-guided-story]")
    purpose = story.select_one("#story-purpose")
    assessment = story.select_one("#story-assessment")
    roadmap = story.select_one("#story-roadmap")
    evidence = story.select_one("#story-evidence")

    assert purpose.select_one(":scope > .home-positioning") is not None
    assert assessment.select_one(".home-positioning") is None
    assert assessment["data-capability"] == "assessment"
    assert assessment.select_one(".home-capability-number").get_text(
        " ", strip=True
    ) == "01"
    assert roadmap.select_one(
        ':scope > [data-home-section="applications"]'
    ) is not None
    assert evidence.select_one('[data-home-section="applications"]') is None
    assert evidence.select_one(':scope > [data-home-section]')[
        "data-home-section"
    ] == "proof"

    chapters = story.select("[data-story-chapter]")
    steps = story.select("[data-story-step]")
    expected_ids = [
        "story-purpose",
        "story-assessment",
        "story-matching",
        "story-roadmap",
        "story-evidence",
    ]
    assert [chapter["id"] for chapter in chapters] == expected_ids
    assert len({chapter["id"] for chapter in chapters}) == 5
    assert [step["data-story-step"] for step in steps] == expected_ids
    assert [step["href"] for step in steps] == [
        f"#{chapter_id}" for chapter_id in expected_ids
    ]
    assert len({step["data-story-step"] for step in steps}) == 5


def test_home_labels_every_simulated_result_as_demo_data(published_catalog):
    document = page(published_catalog.get("/"))
    values = document.select("[data-demo-value]")

    assert values
    for value in values:
        label = value.select_one("[data-demo-label]")
        if label is None:
            sibling = value.find_next_sibling()
            if sibling is not None and sibling.has_attr("data-demo-label"):
                label = sibling
        assert label is not None, value.get_text(" ", strip=True)
        assert label.get_text(" ", strip=True) == "演示数据"
    assert "行业平均" not in document.get_text(" ", strip=True)


def test_public_catalog_lists_use_the_shared_shell_and_private_analytics(published_catalog):
    industries = page(published_catalog.get("/industries"))
    scenarios = page(published_catalog.get("/scenarios"))

    assert {card["data-industry-code"] for card in industries.select("[data-industry-code]")} == {
        "manufacturing", "retail", "professional_knowledge", "software_creative"
    }
    assert len(scenarios.select("[data-scenario-code]")) == 12
    for document in (industries, scenarios):
        assert document.select_one('a[href="/assessment"]') is not None
        assert document.select_one('body[data-analytics-page]') is not None


def test_scenario_filters_are_intersection_not_union(published_catalog):
    response = published_catalog.get(
        "/scenarios?industry=manufacturing&department=production&maturity=explore"
    )
    document = page(response)
    codes = {card["data-scenario-code"] for card in document.select("[data-scenario-code]")}

    assert codes == {"mfg_knowledge_assistant"}


def test_scenario_catalog_uses_signal_panel_and_editorial_rows(published_catalog, monkeypatch):
    """Keep the published scenario filters paired with their editorial result rows."""
    filters = catalog.ScenarioFilters(industry="manufacturing", maturity="pilot")
    source_page = catalog.public_scenarios(filters, catalog.PageRequest(1, 20), NOW_DATETIME)
    synthetic_total = source_page.total + source_page.per_page
    synthetic_page = replace(
        source_page,
        total=synthetic_total,
        total_pages=(synthetic_total + source_page.per_page - 1) // source_page.per_page,
    )
    assert synthetic_page.total != len(synthetic_page.items)

    def public_scenarios_for_catalog(request_filters, request_page, now):
        assert request_filters == filters
        assert request_page == catalog.PageRequest(1, 20)
        return synthetic_page

    monkeypatch.setattr(
        public_catalog_blueprint.catalog,
        "public_scenarios",
        public_scenarios_for_catalog,
    )
    document = page(published_catalog.get("/scenarios?industry=manufacturing&maturity=pilot"))

    panel = document.select_one('form.scenario-signal-panel[aria-label="筛选场景"]')
    assert panel is not None
    rows = document.select("[data-scenario-code].scenario-signal-row > article.catalog-card")
    assert rows
    assert len(rows) == len(synthetic_page.items)
    assert synthetic_page.total != len(rows)
    assert panel.select_one("[data-result-count]").get_text(" ", strip=True) == f"共 {synthetic_page.total} 个已发布场景"
    assert rows[0].select_one("dl.catalog-card-meta") is not None
    assert document.select_one('#industry[value="manufacturing"]') is not None
    assert document.select_one('#maturity option[selected][value="pilot"]') is not None


def test_scenario_detail_uses_decision_cover_and_exact_three_chapters(published_catalog):
    """Keep the decision cover while preserving the three published detail chapters."""
    document = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))

    assert document.select_one(".scenario-decision-cover h1") is not None
    assert [h.get_text(" ", strip=True) for h in document.select(".decision-main > .decision-section > h2")] == [
        "适用场景", "实施路径", "关键输入、输出与风险"
    ]
    assert len(document.select('[data-content-section="timeline"]')) == 1
    assert len(document.select('[data-content-section="budget"]')) == 1


@pytest.mark.parametrize("query", (
    "?industry=invalid&department=invalid&maturity=starting&page=-1&per_page=999",
    "?industry=manufacturing&maturity=starting&page=zero&per_page=20.5",
))
def test_invalid_get_filters_fall_back_to_safe_defaults(published_catalog, query):
    document = page(published_catalog.get(f"/scenarios{query}"))
    expected_count = 12 if "industry=invalid" in query else 3
    assert len(document.select("[data-scenario-code]")) == expected_count
    assert document.select_one('select[name="maturity"] option[selected]')["value"] == ""


@pytest.mark.parametrize("maturity", ("explore", "pilot", "scale", "collaborate"))
def test_every_documented_maturity_filter_is_public(published_catalog, maturity):
    document = page(published_catalog.get(f"/scenarios?maturity={maturity}"))
    assert document.select("[data-scenario-code]")


def test_empty_filter_intersection_has_no_unrelated_fallback(published_catalog):
    document = page(published_catalog.get("/scenarios?industry=manufacturing&department=marketing&maturity=collaborate"))
    assert document.select("[data-scenario-code]") == []


@pytest.mark.parametrize("kind,slug,sections", (
    ("industries", "manufacturing", INDUSTRY_REQUIRED_SECTIONS),
    ("scenarios", "mfg-knowledge-assistant", SCENARIO_REQUIRED_SECTIONS),
))
def test_published_detail_has_sections_seo_canonical_and_no_internal_leaks(
    published_catalog, kind, slug, sections
):
    response = published_catalog.get(f"/{kind}/{slug}")
    document = page(response)

    assert sections <= {node["data-content-section"] for node in document.select("[data-content-section]")}
    assert document.select_one('link[rel="canonical"]')["href"] == f"https://test.example/{kind}/{slug}"
    assert document.title.get_text(strip=True)
    assert document.select_one('meta[name="description"]')["content"]
    for forbidden in ("minimum_business_value", "risk_codes_json", "test-admin", "@", "PRIVATE"):
        assert forbidden.encode() not in response.data


def test_draft_detail_is_private_404(client, db):
    row = db.execute(
        "SELECT slug FROM content_items WHERE entry_type='scenario' "
        "AND status='draft' ORDER BY id LIMIT 1"
    ).fetchone()
    response = client.get(f"/scenarios/{row['slug']}")
    assert response.status_code == 404
    assert row["slug"].encode() not in response.data


def test_archived_detail_is_private_404(published_catalog, db):
    row = db.execute(
        "SELECT id,lock_version,slug FROM content_items WHERE entry_type='scenario' "
        "AND status='published' ORDER BY id LIMIT 1"
    ).fetchone()
    archive_content(row["id"], row["lock_version"], actor="test-admin")

    response = published_catalog.get(f"/scenarios/{row['slug']}")
    assert response.status_code == 404
    assert row["slug"].encode() not in response.data


def test_future_published_detail_is_private_404(client, db):
    row = db.execute(
        "SELECT ci.id,ci.slug,ci.content_group_id FROM content_items ci "
        "WHERE ci.entry_type='industry' AND ci.status='draft' ORDER BY ci.id LIMIT 1"
    ).fetchone()
    db.execute(
        "UPDATE content_items SET publish_at=? WHERE id=?",
        ("2030-01-01 00:00:00", row["id"]),
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at=? WHERE id=?",
        (NOW, row["id"]),
    )
    db.commit()
    response = client.get(f"/industries/{row['slug']}")
    assert response.status_code == 404
    assert row["slug"].encode() not in response.data


def test_alias_redirects_to_the_canonical_published_slug(published_catalog, db):
    row = db.execute(
        "SELECT ci.slug,ci.content_group_id FROM content_items ci "
        "WHERE ci.entry_type='industry' AND ci.status='published' ORDER BY ci.id LIMIT 1"
    ).fetchone()

    db.execute(
        "INSERT INTO content_slug_aliases (entry_type,old_slug,content_group_id,created_at) "
        "VALUES ('industry','old-manufacturing',?,?)",
        (row["content_group_id"], NOW),
    )
    db.commit()
    alias = published_catalog.get("/industries/old-manufacturing")
    assert alias.status_code == 301
    assert alias.headers["Location"].endswith(f"/industries/{row['slug']}")


def test_every_public_complete_detail_has_its_required_sections(published_catalog):
    expected = (
        ("/industries", INDUSTRY_REQUIRED_SECTIONS, tuple(
            item["slug"] for item in catalog.public_industries(NOW_DATETIME)
        )),
        ("/scenarios", SCENARIO_REQUIRED_SECTIONS, tuple(
            item.slug for item in catalog.public_scenarios(
                catalog.ScenarioFilters(), catalog.PageRequest(1, 20), NOW_DATETIME
            ).items
        )),
    )
    for prefix, sections, slugs in expected:
        for slug in slugs:
            document = page(published_catalog.get(f"{prefix}/{slug}"))
            assert sections <= {node["data-content-section"] for node in document.select("[data-content-section]")}
    assert published_catalog.get("/scenarios/data-process-foundation").status_code == 404


def test_public_catalog_has_private_no_store_analytics_response(published_catalog):
    for path in ("/industries", "/industries/manufacturing", "/scenarios", "/scenarios/mfg-knowledge-assistant"):
        response = published_catalog.get(path)
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["Pragma"] == "no-cache"
        assert response.headers["Expires"] == "0"


def test_public_base_url_is_required_https_origin(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_PLATFORM_PUBLIC_BASE_URL", raising=False)
    for value in (None, "http://example.test", "https://user@example.test", "https://example.test/path", "https://example.test/?q=1", "https://example.test/#fragment"):
        config = {"TESTING": False, "SECRET_KEY": "test", "PUBLIC_BASE_URL": value,
                  "MEDIA_UPLOAD_ROOT": str(tmp_path / "media")}
        with pytest.raises(ValueError):
            app_module.create_app(config)


@pytest.mark.parametrize("value", (
    "https://example.test?",
    "https://example.test#",
    "https://example.test:bad",
    "https://:443",
    "https://example.test:0",
    "https://example.test:",
    "https://[2001:db8::1]:",
    "https://example.test\n",
), ids=("empty-query", "empty-fragment", "bad-port", "empty-host", "zero-port", "empty-dns-port", "empty-ipv6-port", "control"))
def test_public_base_url_rejects_noncanonical_https_origins(tmp_path, monkeypatch, value):
    """Catch parser normalization that accepts an input other than a strict origin."""
    monkeypatch.delenv("AI_PLATFORM_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(ValueError):
        app_module.create_app({
            "TESTING": False,
            "SECRET_KEY": "test",
            "PUBLIC_BASE_URL": value,
            "MEDIA_UPLOAD_ROOT": str(tmp_path / "media"),
        })


@pytest.mark.parametrize("value", (
    "https://exa mple.test",
    "https://example_test",
    "https://example%.test",
    "https://exam\u200bple.test",
), ids=("space", "underscore", "bad-percent", "zero-width"))
def test_public_base_url_rejects_invalid_hostname_shape(tmp_path, monkeypatch, value):
    """Catch a syntactically parsed hostname that is not a legal local origin host."""
    monkeypatch.delenv("AI_PLATFORM_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(ValueError):
        app_module.create_app({
            "TESTING": False,
            "SECRET_KEY": "test",
            "PUBLIC_BASE_URL": value,
            "MEDIA_UPLOAD_ROOT": str(tmp_path / "media"),
        })


@pytest.mark.parametrize("value", (
    "https://exam\u034fple.test",
    "https://[v1.example]",
    "https://xn--a.test",
    "https://[fe80::1%25en0]",
    "https://example.test:0443",
), ids=("idna-maps-nothing", "ipvfuture", "invalid-a-label", "ipv6-zone", "leading-zero-port"))
def test_public_base_url_rejects_ambiguous_authority_forms(tmp_path, monkeypatch, value):
    """Catch loose urlsplit authority parsing that cannot form a strict HTTPS origin."""
    monkeypatch.delenv("AI_PLATFORM_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(ValueError):
        app_module.create_app({
            "TESTING": False,
            "SECRET_KEY": "test",
            "PUBLIC_BASE_URL": value,
            "MEDIA_UPLOAD_ROOT": str(tmp_path / "media"),
        })


@pytest.mark.parametrize("value", (
    "https://0x7f000001",
    "https://0x7f.0.0.1",
    "https://127.0x0.0.1",
    "https://0x",
    "https://test.123",
    "https://test.09",
), ids=("single-hex", "split-hex", "mixed-hex", "empty-hex", "numeric-last-label", "zero-prefixed-last-label"))
def test_public_base_url_rejects_dns_forms_that_whatwg_can_treat_as_ipv4(tmp_path, monkeypatch, value):
    """Prevent an alternate IPv4 spelling from being accepted through the DNS fallback."""
    monkeypatch.delenv("AI_PLATFORM_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(ValueError):
        app_module.create_app({
            "TESTING": False,
            "SECRET_KEY": "test",
            "PUBLIC_BASE_URL": value,
            "MEDIA_UPLOAD_ROOT": str(tmp_path / "media"),
        })


def test_public_base_url_keeps_a_non_numeric_final_label_as_dns(tmp_path, monkeypatch):
    """Keep an ordinary valid DNS label that only starts with an alternate-IP prefix."""
    monkeypatch.delenv("AI_PLATFORM_PUBLIC_BASE_URL", raising=False)
    application = app_module.create_app({
        "TESTING": False,
        "SECRET_KEY": "test",
        "PUBLIC_BASE_URL": "https://0x7f000001.test",
        "MEDIA_UPLOAD_ROOT": str(tmp_path / "media"),
    })

    assert application.config["PUBLIC_BASE_URL"] == "https://0x7f000001.test"


@pytest.mark.parametrize("value", (
    "https://faß.de",
    "https://xn--fa-hia.de",
), ids=("unicode-idna2008", "punycode-idna2008"))
def test_public_base_url_accepts_lossless_idna2008_origins(tmp_path, monkeypatch, value):
    """Accept the valid ß U-label and its verified IDNA2008 A-label counterpart."""
    monkeypatch.delenv("AI_PLATFORM_PUBLIC_BASE_URL", raising=False)
    application = app_module.create_app({
        "TESTING": False,
        "SECRET_KEY": "test",
        "PUBLIC_BASE_URL": value,
        "MEDIA_UPLOAD_ROOT": str(tmp_path / "media"),
    })

    assert application.config["PUBLIC_BASE_URL"] == value


@pytest.mark.parametrize("value", (
    "https://example.test",
    "https://example.test:1",
    "https://example.test:443",
    "https://example.test:8443",
    "https://example.test:65535",
    "https://[2001:db8::1]:8443",
    "https://192.0.2.1:8443",
    "https://例子.测试",
    "https://xn--fsqu00a.xn--0zwm56d",
))
def test_public_base_url_accepts_exact_https_origins(tmp_path, monkeypatch, value):
    monkeypatch.delenv("AI_PLATFORM_PUBLIC_BASE_URL", raising=False)
    application = app_module.create_app({
        "TESTING": False,
        "SECRET_KEY": "test",
        "PUBLIC_BASE_URL": value,
        "MEDIA_UPLOAD_ROOT": str(tmp_path / "media"),
    })

    assert application.config["PUBLIC_BASE_URL"] == value


def _ready_media(db, name, mime):
    asset_id = db.execute(
        "INSERT INTO media_assets "
        "(storage_name,display_name,detected_mime,byte_size,sha256,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'pending',?,?)",
        (name, name, mime, 1, hashlib.sha256(name.encode()).hexdigest(), NOW, NOW),
    ).lastrowid
    db.execute(
        "UPDATE media_assets SET status='ready',scan_result_code='validated',"
        "scan_checked_at=?,ready_at=?,updated_at=? WHERE id=?",
        (NOW, NOW, NOW, asset_id),
    )
    db.commit()
    return asset_id


def _publish_all_governed_blocks(db):
    row = db.execute(
        "SELECT ci.id,ci.lock_version,ci.content_group_id,g.scenario_id,ci.slug "
        "FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "WHERE ci.entry_type='scenario' AND ci.status='draft' "
        "AND g.scenario_id=(SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant')"
    ).fetchone()
    image_id = _ready_media(db, "review-image.png", "image/png")
    download_id = _ready_media(db, "review-download.pdf", "application/pdf")
    draft = ContentDraft(
        entry_type="scenario", slug=row["slug"], title="受控区块公开测试",
        summary="通过受控发布流程验证每类内容区块的公开渲染。",
        seo_title="受控区块公开测试", seo_description="验证公开场景区块的安全渲染。",
        content_group_id=row["content_group_id"], extension={"scenario_id": row["scenario_id"]},
        maturity_codes=("explore",),
        blocks=(
            ContentBlock("heading", title="REVIEW-HEADING", body_html="<p>REVIEW-HEADING-BODY</p>", settings={"level": 2}),
            ContentBlock("rich_text", title="REVIEW-RICH-TITLE", body_html="<p>REVIEW-RICH</p>", settings={}),
            ContentBlock("image_text", title="REVIEW-IMAGE", body_html="<p>REVIEW-IMAGE-BODY</p>", settings={"alignment": "left", "alt_text": "REVIEW-ALT"}, media_asset_id=image_id),
            ContentBlock("metric", title="REVIEW-METRIC-TITLE", body_html="<p>REVIEW-METRIC-BODY</p>", settings={"value": "REVIEW-METRIC", "unit": "项"}),
            ContentBlock("steps", title="REVIEW-STEPS", body_html="<p>REVIEW-STEPS-BODY</p>", settings={"items": ("REVIEW-STEP-ONE", "REVIEW-STEP-TWO")}),
            ContentBlock("download", title="REVIEW-DOWNLOAD-TITLE", body_html="<p>REVIEW-DOWNLOAD-BODY</p>", settings={"label": "REVIEW-DOWNLOAD"}, media_asset_id=download_id),
            ContentBlock("cta", title="REVIEW-CTA-TITLE", body_html="<p>REVIEW-CTA-BODY</p>", settings={"label": "REVIEW-CTA", "url": "/assessment", "style": "primary"}),
        ),
    )
    lock_version = save_content_draft(row["id"], row["lock_version"], draft, actor="test-admin", now=NOW_DATETIME)
    publish_content(row["id"], lock_version, actor="test-admin", now=NOW_DATETIME)
    return row["slug"], image_id, download_id


def _publish_future_governed_blocks(db, *, due):
    """Build a future-dated published scenario solely inside the disposable DB."""
    row = db.execute(
        "SELECT ci.id,ci.lock_version,ci.content_group_id,g.scenario_id,ci.slug "
        "FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "WHERE ci.entry_type='scenario' AND ci.status='draft' "
        "AND g.scenario_id=(SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant')"
    ).fetchone()
    image_id = _ready_media(db, "future-review-image.png", "image/png")
    download_id = _ready_media(db, "future-review-download.pdf", "application/pdf")
    draft = ContentDraft(
        entry_type="scenario", slug=row["slug"], title="未来受控媒体测试",
        summary="验证未到期的内容不会提前释放公开媒体。",
        seo_title="未来受控媒体测试", seo_description="验证受控媒体严格遵从公开发布时间。",
        content_group_id=row["content_group_id"], extension={"scenario_id": row["scenario_id"]},
        maturity_codes=("explore",),
        blocks=(
            ContentBlock(
                "image_text", title="未来图片", body_html="<p>未来内容概述</p>",
                settings={"alignment": "left", "alt_text": "未来图片"}, media_asset_id=image_id,
            ),
            ContentBlock("download", title="未来下载", settings={"label": "未来下载"}, media_asset_id=download_id),
        ),
    )
    lock_version = save_content_draft(row["id"], row["lock_version"], draft, actor="test-admin", now=NOW_DATETIME)
    due_text = due.strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "UPDATE content_items SET status='published',published_at=?,publish_at=?,"
        "lock_version=lock_version+1,updated_at=? WHERE id=?",
        (NOW, due_text, NOW, row["id"]),
    )
    db.commit()
    return row["slug"], image_id, download_id, lock_version


def test_formally_published_governed_block_types_render_through_safe_public_http(client, db):
    slug, image_id, download_id = _publish_all_governed_blocks(db)

    response = client.get(f"/scenarios/{slug}")
    document = page(response)
    assert {node["data-content-block"] for node in document.select("[data-content-block]")} >= {
        "heading", "rich_text", "image_text", "metric", "steps", "download", "cta"
    }
    expected = {
        "heading": ".content-block-heading",
        "rich_text": ".content-block-rich-text",
        "image_text": ".content-block-image-text",
        "metric": ".content-block-metric",
        "steps": ".content-block-steps",
        "download": ".content-block-download",
        "cta": ".content-block-cta",
    }
    for block_type, selector in expected.items():
        assert document.select_one(
            f'[data-content-block="{block_type}"]{selector}'
        ) is not None
    for marker in (
        "REVIEW-HEADING", "REVIEW-HEADING-BODY", "REVIEW-RICH-TITLE", "REVIEW-RICH",
        "REVIEW-IMAGE", "REVIEW-IMAGE-BODY", "REVIEW-METRIC-TITLE", "REVIEW-METRIC",
        "REVIEW-METRIC-BODY", "REVIEW-STEPS", "REVIEW-STEPS-BODY", "REVIEW-STEP-ONE",
        "REVIEW-DOWNLOAD-TITLE", "REVIEW-DOWNLOAD-BODY", "REVIEW-DOWNLOAD",
        "REVIEW-CTA-TITLE", "REVIEW-CTA-BODY", "REVIEW-CTA",
    ):
        assert marker.encode() in response.data
    assert document.select_one(f'img[src="/media/{image_id}/image"]')["alt"] == "REVIEW-ALT"
    assert document.select_one(f'a[href="/media/{download_id}/download"]') is not None
    assert document.select_one('[data-content-block="cta"] a[href="/assessment"].btn-primary') is not None


@pytest.mark.parametrize(("block_type", "mime"), (("image_text", "application/pdf"), ("download", "image/png")))
def test_formal_publish_rejects_block_media_with_wrong_mime(db, block_type, mime):
    row = db.execute(
        "SELECT ci.id,ci.lock_version FROM content_items ci WHERE ci.entry_type='scenario' "
        "AND ci.status='draft' AND ci.content_group_id=(SELECT id FROM content_groups "
        "WHERE scenario_id=(SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'))"
    ).fetchone()
    media_id = _ready_media(db, f"wrong-{block_type}", mime)
    draft = publishing_repository.load_content_draft(db, row["id"])
    block = ContentBlock(
        block_type, title="媒体类型校验", body_html="<p>媒体类型校验正文</p>",
        settings={"alignment": "left", "alt_text": "示意图"} if block_type == "image_text" else {"label": "下载文件"},
        media_asset_id=media_id,
    )
    lock_version = save_content_draft(
        row["id"], row["lock_version"], replace(draft, blocks=(block,)),
        actor="test-admin", now=NOW_DATETIME,
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(row["id"], lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "block_media_mime_invalid"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (row["id"],)).fetchone()[0] == "draft"
    assert db.execute("SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'", (row["id"],)).fetchone()[0] == 0


def test_formally_published_block_media_urls_stream_real_matching_files(client, db, media_root):
    slug, image_id, download_id = _publish_all_governed_blocks(db)
    (media_root / "review-image.png").write_bytes(b"\x89PNG\r\n\x1a\npublic-image")
    (media_root / "review-download.pdf").write_bytes(b"%PDF-1.4\npublic-download\n%%EOF\n")

    response = client.get(f"/scenarios/{slug}")
    document = page(response)
    image_url = document.select_one(f'img[src="/media/{image_id}/image"]')["src"]
    download_url = document.select_one(f'a[href="/media/{download_id}/download"]')["href"]

    assert client.get(image_url).status_code == 200
    assert client.get(download_url).status_code == 200


def test_future_published_scenario_hides_detail_and_block_media_until_due(
    client, db, media_root, monkeypatch
):
    due = datetime(2030, 1, 1, 10, 0, 0, tzinfo=SHANGHAI)
    slug, image_id, download_id, _ = _publish_future_governed_blocks(db, due=due)
    (media_root / "future-review-image.png").write_bytes(b"\x89PNG\r\n\x1a\nfuture-image")
    (media_root / "future-review-download.pdf").write_bytes(b"%PDF-1.4\nfuture-download\n%%EOF\n")

    assert client.get(f"/scenarios/{slug}").status_code == 404
    assert client.get(f"/media/{image_id}/image").status_code == 404
    assert client.get(f"/media/{download_id}/download").status_code == 404

    monkeypatch.setattr(public_catalog_blueprint, "shanghai_now", lambda: due)
    monkeypatch.setattr(media_service, "shanghai_now", lambda: due)

    assert client.get(f"/scenarios/{slug}").status_code == 200
    assert client.get(f"/media/{image_id}/image").status_code == 200
    assert client.get(f"/media/{download_id}/download").status_code == 200


@pytest.mark.parametrize(("block_type", "settings", "media_asset_id"), (
    ("heading", {"level": 2.0}, None),
    ("download", {"label": {"not": "text"}}, None),
    ("cta", {"label": ["not text"], "url": "/assessment", "style": "primary"}, None),
    ("image_text", {"alignment": "left", "alt_text": "图"}, -1),
    ("image_text", {"alignment": ["left"], "alt_text": "图"}, None),
))
def test_public_block_projection_rejects_nonexact_settings_and_media_types(block_type, settings, media_asset_id):
    row = {
        "block_type": block_type, "title": "标题", "body_html": "<p>正文</p>",
        "settings_json": json.dumps(settings), "media_asset_id": media_asset_id,
        "sort_order": 0,
    }

    assert catalog._public_block(row) is None


def test_scenario_required_sections_use_explicit_reviewed_inputs(published_catalog):
    document = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))
    inputs = {node.get_text(strip=True) for node in document.select('[data-content-section="inputs"] li')}
    prerequisites = {node.get_text(strip=True) for node in document.select('[data-content-section="prerequisites"] li')}
    metrics = document.select('[data-content-section="metrics"] li')
    risks = document.select('[data-content-section="risks"] li')

    assert inputs == {"设备与工艺知识文档的受控副本", "近三个月高频现场问题清单"}
    assert inputs.isdisjoint(prerequisites)
    assert all(not value.startswith(("部门：", "业务问题：")) for value in inputs)
    assert metrics and risks
    assert all("_" not in node.get_text() for node in risks)


def test_scenario_with_missing_required_structured_data_is_not_publicly_available(published_catalog, db):
    service = db.execute(
        "SELECT service_id FROM scenario_services link JOIN scenarios s ON s.id=link.scenario_id "
        "WHERE s.code='mfg_knowledge_assistant' LIMIT 1"
    ).fetchone()
    db.execute("UPDATE services SET prerequisites_json='[]' WHERE id=?", (service["service_id"],))
    db.commit()

    assert published_catalog.get("/scenarios/mfg-knowledge-assistant").status_code == 404


def _saved_scenario_revision(db):
    publish_catalog(db)
    current = db.execute(
        "SELECT ci.id,ci.lock_version,ci.content_group_id,g.scenario_id FROM content_items ci "
        "JOIN content_groups g ON g.id=ci.content_group_id WHERE ci.entry_type='scenario' "
        "AND ci.status='published' AND g.scenario_id=(SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant')"
    ).fetchone()
    revision_id = copy_revision(current["id"], actor="test-admin", now=NOW_DATETIME)
    draft = publishing_repository.load_content_draft(db, revision_id)
    lock_version = save_content_draft(revision_id, 1, draft, actor="test-admin", now=NOW_DATETIME)
    return current, revision_id, lock_version


def _saved_industry_revision(db):
    publish_catalog(db)
    current = db.execute(
        "SELECT ci.id,ci.lock_version,ci.content_group_id,g.industry_id FROM content_items ci "
        "JOIN content_groups g ON g.id=ci.content_group_id WHERE ci.entry_type='industry' "
        "AND ci.status='published' AND g.industry_id=(SELECT id FROM industries WHERE code='manufacturing')"
    ).fetchone()
    revision_id = copy_revision(current["id"], actor="test-admin", now=NOW_DATETIME)
    return current, revision_id


def _assert_unpublished_revision(db, current_id, revision_id, *, lock_version=None):
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current_id,)).fetchone()[0] == "published"
    revision = db.execute("SELECT status,lock_version FROM content_items WHERE id=?", (revision_id,)).fetchone()
    assert revision["status"] == "draft"
    if lock_version is not None:
        assert revision["lock_version"] == lock_version
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'",
        (revision_id,),
    ).fetchone()[0] == 0


def _inject_blank_block_title(db, revision_id):
    cursor = db.execute(
        "UPDATE content_blocks SET title='   ' WHERE id=(SELECT id FROM content_blocks "
        "WHERE content_item_id=? ORDER BY sort_order,id LIMIT 1)",
        (revision_id,),
    )
    assert cursor.rowcount == 1
    db.commit()


def _published_scenario_candidates(db, industry_id):
    rows = db.execute(
        "SELECT DISTINCT ci.id,s.code FROM content_items ci "
        "JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id "
        "JOIN scenario_branches sb ON sb.scenario_id=g.scenario_id "
        "JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
        "WHERE ci.entry_type='scenario' AND ci.status='published' "
        "AND (ci.publish_at IS NULL OR ci.publish_at<=?) AND ib.industry_id=? "
        "AND ib.status='published' "
        "ORDER BY ci.id",
        (NOW, industry_id),
    ).fetchall()
    return tuple((row["id"], row["code"]) for row in rows)


def _replace_first_block_titles(db, content_ids, title):
    trigger = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='protect_content_blocks_update'"
    ).fetchone()
    assert trigger is not None
    originals = []
    db.execute("DROP TRIGGER protect_content_blocks_update")
    try:
        for content_id in content_ids:
            block = db.execute(
                "SELECT id,title FROM content_blocks WHERE content_item_id=? "
                "ORDER BY sort_order,id LIMIT 1",
                (content_id,),
            ).fetchone()
            assert block is not None
            originals.append((block["title"], block["id"]))
            db.execute(
                "UPDATE content_blocks SET title=? WHERE id=?", (title, block["id"])
            )
    finally:
        db.execute(trigger["sql"])
    db.commit()
    return tuple(originals)


def _restore_block_titles(db, originals):
    trigger = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='protect_content_blocks_update'"
    ).fetchone()
    assert trigger is not None
    db.execute("DROP TRIGGER protect_content_blocks_update")
    try:
        db.executemany("UPDATE content_blocks SET title=? WHERE id=?", originals)
    finally:
        db.execute(trigger["sql"])
    db.commit()


def _publication_state_snapshot(db, content_ids):
    placeholders = ",".join("?" for _ in content_ids)
    items = tuple(
        tuple(row) for row in db.execute(
            "SELECT id,status,lock_version,published_at,archived_at FROM content_items "
            f"WHERE id IN ({placeholders}) ORDER BY id",
            content_ids,
        )
    )
    audits = tuple(
        tuple(row) for row in db.execute(
            "SELECT content_item_id,event_code,actor_text,details_json,created_at "
            f"FROM content_audit_events WHERE content_item_id IN ({placeholders}) "
            "ORDER BY id",
            content_ids,
        )
    )
    return items, audits


def _scenario_service_state_snapshot(db, scenario_id):
    return tuple(
        tuple(row) for row in db.execute(
            "SELECT link.scenario_id,link.service_id,svc.code,svc.status "
            "FROM scenario_services link JOIN services svc ON svc.id=link.service_id "
            "WHERE link.scenario_id=? ORDER BY link.service_id",
            (scenario_id,),
        )
    )


def _assert_public_service_section(client, slug):
    section = page(client.get(f"/scenarios/{slug}")).select_one(
        '[data-content-section="services"]'
    )
    assert section is not None
    assert section.get_text(" ", strip=True) == "服务 AI 就绪基础工作坊"
    assert "企业知识助手试点" not in section.get_text(" ", strip=True)


def _archive_equipment_department_for_knowledge_scenario(db):
    scenario = db.execute(
        "SELECT ci.id,ci.lock_version,ci.slug,g.scenario_id FROM content_items ci "
        "JOIN content_groups g ON g.id=ci.content_group_id JOIN scenarios s ON s.id=g.scenario_id "
        "WHERE ci.entry_type='scenario' AND ci.status='published' "
        "AND s.code='mfg_knowledge_assistant'"
    ).fetchone()
    assert scenario is not None
    before = db.execute(
        "SELECT d.id,d.code,d.name,d.status FROM scenario_departments link "
        "JOIN departments d ON d.id=link.department_id WHERE link.scenario_id=? "
        "ORDER BY d.sort_order,d.id",
        (scenario["scenario_id"],),
    ).fetchall()
    assert len(before) >= 3
    assert {row["code"] for row in before} == {
        "equipment", "production", "finance_hr",
    }
    assert all(
        row["status"] == "published" and is_exact_nonblank_text(row["name"])
        for row in before
    )
    equipment = next(row for row in before if row["code"] == "equipment")
    cursor = db.execute(
        "UPDATE departments SET name='   ',status='archived' "
        "WHERE id=? AND status='published'",
        (equipment["id"],),
    )
    assert cursor.rowcount == 1
    db.commit()

    remaining = db.execute(
        "SELECT d.code,d.name,d.status FROM scenario_departments link "
        "JOIN departments d ON d.id=link.department_id WHERE link.scenario_id=? "
        "AND d.status='published' ORDER BY d.sort_order,d.id",
        (scenario["scenario_id"],),
    ).fetchall()
    assert {row["code"] for row in remaining} == {"production", "finance_hr"}
    assert remaining and all(
        row["status"] == "published" and is_exact_nonblank_text(row["name"])
        for row in remaining
    )
    assert db.execute(
        "SELECT status FROM departments WHERE id=?", (equipment["id"],)
    ).fetchone()[0] == "archived"
    return scenario


def _archive_knowledge_service_with_published_replacement(db):
    scenario = db.execute(
        "SELECT ci.id,ci.lock_version,ci.slug,g.scenario_id FROM content_items ci "
        "JOIN content_groups g ON g.id=ci.content_group_id JOIN scenarios s ON s.id=g.scenario_id "
        "WHERE ci.entry_type='scenario' AND ci.status='published' "
        "AND s.code='mfg_knowledge_assistant'"
    ).fetchone()
    assert scenario is not None
    original = db.execute(
        "SELECT svc.id,svc.code,svc.status FROM scenario_services link "
        "JOIN services svc ON svc.id=link.service_id WHERE link.scenario_id=? "
        "AND svc.code='knowledge_assistant_pilot'",
        (scenario["scenario_id"],),
    ).fetchone()
    replacement = db.execute(
        "SELECT id,code,status,public_name,min_budget,max_budget,min_weeks,max_weeks,"
        "implementation_steps_json,prerequisites_json,acceptance_json FROM services "
        "WHERE code='foundation_workshop'"
    ).fetchone()
    assert original is not None
    assert original["status"] == "published"
    assert replacement is not None
    assert replacement["status"] == "published"
    assert is_exact_nonblank_text(replacement["public_name"])
    assert db.execute(
        "SELECT COUNT(*) FROM service_deliverables "
        "WHERE service_id=? AND status='published'",
        (replacement["id"],),
    ).fetchone()[0] >= 1

    db.execute(
        "INSERT INTO scenario_services(scenario_id,service_id) VALUES (?,?)",
        (scenario["scenario_id"], replacement["id"]),
    )
    archived = db.execute(
        "UPDATE services SET status='archived' "
        "WHERE id=? AND status='published'",
        (original["id"],),
    )
    assert archived.rowcount == 1
    db.commit()

    services = db.execute(
        "SELECT svc.code,svc.status FROM scenario_services link "
        "JOIN services svc ON svc.id=link.service_id WHERE link.scenario_id=? "
        "ORDER BY svc.id",
        (scenario["scenario_id"],),
    ).fetchall()
    assert {(row["code"], row["status"]) for row in services} == {
        ("knowledge_assistant_pilot", "archived"),
        ("foundation_workshop", "published"),
    }
    public_services = catalog._services_for_scenario(db, scenario["scenario_id"])
    assert tuple(service["code"] for service in public_services) == (
        "foundation_workshop",
    )
    assert catalog._valid_services(public_services) is True
    return scenario


def test_industry_nested_scenario_ignores_archived_service_with_published_replacement(
    client, db
):
    current, industry_revision = _saved_industry_revision(db)
    scenario = _archive_knowledge_service_with_published_replacement(db)
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    _assert_public_service_section(client, scenario["slug"])
    assert client.get("/industries/manufacturing").status_code == 200

    candidates = _published_scenario_candidates(db, current["industry_id"])
    other_candidates = tuple(
        candidate_id for candidate_id, _ in candidates if candidate_id != scenario["id"]
    )
    assert other_candidates
    for candidate_id in other_candidates:
        lock_version = db.execute(
            "SELECT lock_version FROM content_items WHERE id=?", (candidate_id,)
        ).fetchone()[0]
        archive_content(
            candidate_id,
            lock_version,
            actor="test-admin",
            now=NOW_DATETIME + timedelta(minutes=1),
        )
    assert _published_scenario_candidates(db, current["industry_id"]) == (
        (scenario["id"], "mfg_knowledge_assistant"),
    )
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    assert client.get("/industries/manufacturing").status_code == 200
    industry_before = _publication_state_snapshot(
        db, (current["id"], industry_revision)
    )
    scenario_before = _publication_state_snapshot(db, (scenario["id"],))
    services_before = _scenario_service_state_snapshot(db, scenario["scenario_id"])

    result = publish_content(
        industry_revision,
        1,
        actor="test-admin",
        now=NOW_DATETIME + timedelta(minutes=2),
    )

    assert (result.published_id, result.archived_id) == (
        industry_revision,
        current["id"],
    )
    assert _publication_state_snapshot(db, (scenario["id"],)) == scenario_before
    assert _scenario_service_state_snapshot(
        db, scenario["scenario_id"]
    ) == services_before
    old = db.execute(
        "SELECT status,lock_version,archived_at FROM content_items WHERE id=?",
        (current["id"],),
    ).fetchone()
    new = db.execute(
        "SELECT status,lock_version,published_at FROM content_items WHERE id=?",
        (industry_revision,),
    ).fetchone()
    assert (old["status"], old["lock_version"], old["archived_at"]) == (
        "archived", 2, "2026-08-24 10:02:00",
    )
    assert (new["status"], new["lock_version"], new["published_at"]) == (
        "published", 2, "2026-08-24 10:02:00",
    )
    assert industry_before != _publication_state_snapshot(
        db, (current["id"], industry_revision)
    )
    published_audits = db.execute(
        "SELECT details_json FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_published' ORDER BY id",
        (industry_revision,),
    ).fetchall()
    assert len(published_audits) == 1
    assert json.loads(published_audits[0]["details_json"]) == {
        "archived_id": current["id"],
    }
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    _assert_public_service_section(client, scenario["slug"])
    assert client.get("/industries/manufacturing").status_code == 200


def test_direct_scenario_publish_remains_strict_with_archived_service_and_published_replacement(
    client, db
):
    publish_catalog(db)
    scenario = _archive_knowledge_service_with_published_replacement(db)
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    _assert_public_service_section(client, scenario["slug"])
    assert client.get("/industries/manufacturing").status_code == 200
    revision_id = copy_revision(
        scenario["id"], actor="test-admin", now=NOW_DATETIME
    )
    before = _publication_state_snapshot(db, (scenario["id"], revision_id))
    services_before = _scenario_service_state_snapshot(db, scenario["scenario_id"])

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    assert _publication_state_snapshot(db, (scenario["id"], revision_id)) == before
    assert _scenario_service_state_snapshot(
        db, scenario["scenario_id"]
    ) == services_before
    _assert_unpublished_revision(
        db, scenario["id"], revision_id, lock_version=1
    )
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    _assert_public_service_section(client, scenario["slug"])
    assert client.get("/industries/manufacturing").status_code == 200


def test_industry_nested_scenario_ignores_archived_core_department_with_published_remainders(
    client, db
):
    current, industry_revision = _saved_industry_revision(db)
    scenario = _archive_equipment_department_for_knowledge_scenario(db)
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    assert client.get("/industries/manufacturing").status_code == 200

    candidates = _published_scenario_candidates(db, current["industry_id"])
    assert sum(candidate_id == scenario["id"] for candidate_id, _ in candidates) == 1
    other_candidates = tuple(
        candidate_id for candidate_id, _ in candidates if candidate_id != scenario["id"]
    )
    assert other_candidates
    for candidate_id in other_candidates:
        lock_version = db.execute(
            "SELECT lock_version FROM content_items WHERE id=?", (candidate_id,)
        ).fetchone()[0]
        archive_content(
            candidate_id,
            lock_version,
            actor="test-admin",
            now=NOW_DATETIME + timedelta(minutes=1),
        )
    assert _published_scenario_candidates(db, current["industry_id"]) == (
        (scenario["id"], "mfg_knowledge_assistant"),
    )
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    assert client.get("/industries/manufacturing").status_code == 200
    scenario_before = _publication_state_snapshot(db, (scenario["id"],))

    result = publish_content(
        industry_revision,
        1,
        actor="test-admin",
        now=NOW_DATETIME + timedelta(minutes=2),
    )

    assert (result.published_id, result.archived_id) == (
        industry_revision,
        current["id"],
    )
    old = db.execute(
        "SELECT status,lock_version,archived_at FROM content_items WHERE id=?",
        (current["id"],),
    ).fetchone()
    new = db.execute(
        "SELECT status,lock_version,published_at FROM content_items WHERE id=?",
        (industry_revision,),
    ).fetchone()
    assert (old["status"], old["lock_version"]) == ("archived", 2)
    assert old["archived_at"] == "2026-08-24 10:02:00"
    assert (new["status"], new["lock_version"]) == ("published", 2)
    assert new["published_at"] == "2026-08-24 10:02:00"
    published_audits = db.execute(
        "SELECT details_json FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_published' ORDER BY id",
        (industry_revision,),
    ).fetchall()
    assert len(published_audits) == 1
    assert json.loads(published_audits[0]["details_json"]) == {
        "archived_id": current["id"],
    }
    assert _publication_state_snapshot(db, (scenario["id"],)) == scenario_before
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    assert client.get("/industries/manufacturing").status_code == 200


def test_direct_scenario_publish_remains_strict_with_archived_core_department(
    client, db
):
    publish_catalog(db)
    scenario = _archive_equipment_department_for_knowledge_scenario(db)
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    assert client.get("/industries/manufacturing").status_code == 200
    revision_id = copy_revision(
        scenario["id"], actor="test-admin", now=NOW_DATETIME
    )
    before = _publication_state_snapshot(db, (scenario["id"], revision_id))

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    assert _publication_state_snapshot(db, (scenario["id"], revision_id)) == before
    assert tuple(db.execute(
        "SELECT status,lock_version FROM content_items WHERE id=?", (scenario["id"],)
    ).fetchone()) == ("published", scenario["lock_version"])
    assert tuple(db.execute(
        "SELECT status,lock_version FROM content_items WHERE id=?", (revision_id,)
    ).fetchone()) == ("draft", 1)
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_published'",
        (revision_id,),
    ).fetchone()[0] == 0
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    assert client.get("/industries/manufacturing").status_code == 200


def test_industry_candidate_requires_a_published_branch_in_that_industry(client, db):
    current, industry_revision = _saved_industry_revision(db)
    scenario = db.execute(
        "SELECT ci.id,ci.slug,g.scenario_id FROM content_items ci "
        "JOIN content_groups g ON g.id=ci.content_group_id JOIN scenarios s ON s.id=g.scenario_id "
        "WHERE ci.entry_type='scenario' AND ci.status='published' "
        "AND s.code='mfg_knowledge_assistant'"
    ).fetchone()
    assert scenario is not None
    candidates = _published_scenario_candidates(db, current["industry_id"])
    other_candidates = tuple(
        candidate_id for candidate_id, _ in candidates if candidate_id != scenario["id"]
    )
    assert other_candidates
    for candidate_id in other_candidates:
        lock_version = db.execute(
            "SELECT lock_version FROM content_items WHERE id=?", (candidate_id,)
        ).fetchone()[0]
        archive_content(
            candidate_id,
            lock_version,
            actor="test-admin",
            now=NOW_DATETIME + timedelta(minutes=1),
        )
    retail_branch = db.execute(
        "SELECT ib.id FROM industry_branches ib JOIN industries i ON i.id=ib.industry_id "
        "WHERE i.code='retail' AND i.status='published' AND ib.status='published' "
        "ORDER BY ib.sort_order,ib.id LIMIT 1"
    ).fetchone()
    assert retail_branch is not None
    db.execute(
        "INSERT INTO scenario_branches(scenario_id,industry_branch_id) VALUES (?,?)",
        (scenario["scenario_id"], retail_branch["id"]),
    )
    archived = db.execute(
        "UPDATE industry_branches SET status='archived' "
        "WHERE industry_id=? AND status='published'",
        (current["industry_id"],),
    )
    assert archived.rowcount >= 1
    db.commit()

    assert _published_scenario_candidates(db, current["industry_id"]) == ()
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    filtered = page(client.get("/scenarios?industry=manufacturing"))
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in filtered.select("[data-scenario-code]")
    }
    assert client.get("/industries/manufacturing").status_code == 404
    industry_before = _publication_state_snapshot(
        db, (current["id"], industry_revision)
    )
    scenario_before = _publication_state_snapshot(db, (scenario["id"],))

    with pytest.raises(ContentValidationError) as error:
        publish_content(
            industry_revision,
            1,
            actor="test-admin",
            now=NOW_DATETIME + timedelta(minutes=2),
        )

    assert error.value.code == "industry_public_incomplete"
    assert _publication_state_snapshot(
        db, (current["id"], industry_revision)
    ) == industry_before
    assert _publication_state_snapshot(db, (scenario["id"],)) == scenario_before
    _assert_unpublished_revision(
        db, current["id"], industry_revision, lock_version=1
    )
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    assert client.get("/industries/manufacturing").status_code == 404


def test_industry_publish_keeps_public_scenario_healthy_after_relation_target_archive(
    client, db
):
    publish_catalog(db)
    target_id = create_content_draft(
        ContentDraft(
            entry_type="case",
            slug="archived-scenario-relation-target",
            title="后续归档的场景关联案例",
            summary="验证可选关联目标归档后不会破坏场景公开健康性。",
            seo_title="场景关联案例归档验证",
            seo_description="验证可选案例归档后的公开目录发布边界。",
            extension={
                "verification_code": "authorized_anonymous",
                "is_anonymized": 1,
                "basis_type": "internal_delivery_record",
                "private_basis_reference": "archived-relation-target-001",
                "source_url": None,
                "source_url_sha256": None,
                "source_check_code": None,
                "source_checked_at": None,
                "source_check_expires_at": None,
                "source_check_url_sha256": None,
                "is_verified": 1,
                "review_confirmed": 1,
                "verified_at": NOW,
            },
            metrics=(
                CaseMetric(
                    "场景关联验证指标",
                    "8",
                    "2",
                    "小时",
                    "连续 30 天",
                    "由已确认的内部交付记录对比得出。",
                ),
            ),
        ),
        actor="test-admin",
        now=NOW_DATETIME,
    )
    publish_content(target_id, 1, actor="test-admin", now=NOW_DATETIME)
    target = db.execute(
        "SELECT content_group_id,lock_version,status FROM content_items WHERE id=?",
        (target_id,),
    ).fetchone()
    assert target["status"] == "published"

    scenario = db.execute(
        "SELECT ci.id,ci.slug FROM content_items ci JOIN content_groups g "
        "ON g.id=ci.content_group_id JOIN scenarios s ON s.id=g.scenario_id "
        "WHERE ci.entry_type='scenario' AND ci.status='published' "
        "AND s.code='mfg_knowledge_assistant'"
    ).fetchone()
    scenario_revision = copy_revision(
        scenario["id"], actor="test-admin", now=NOW_DATETIME
    )
    scenario_draft = publishing_repository.load_content_draft(db, scenario_revision)
    scenario_lock = save_content_draft(
        scenario_revision,
        1,
        replace(
            scenario_draft,
            relations=(
                ContentRelation("scenario_case", target["content_group_id"]),
            ),
        ),
        actor="test-admin",
        now=NOW_DATETIME,
    )
    scenario_result = publish_content(
        scenario_revision,
        scenario_lock,
        actor="test-admin",
        now=NOW_DATETIME,
    )
    assert (scenario_result.published_id, scenario_result.archived_id) == (
        scenario_revision,
        scenario["id"],
    )
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200

    archive_content(
        target_id,
        target["lock_version"],
        actor="test-admin",
        now=NOW_DATETIME + timedelta(minutes=1),
    )
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (target_id,)
    ).fetchone()[0] == "archived"
    assert db.execute(
        "SELECT case_content_group_id FROM scenario_cases "
        "WHERE scenario_content_item_id=?",
        (scenario_revision,),
    ).fetchone()[0] == target["content_group_id"]
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200

    current, industry_revision = _saved_industry_revision(db)
    candidates = _published_scenario_candidates(db, current["industry_id"])
    assert sum(candidate_id == scenario_revision for candidate_id, _ in candidates) == 1
    other_candidates = tuple(
        candidate_id for candidate_id, _ in candidates if candidate_id != scenario_revision
    )
    assert other_candidates
    for candidate_id in other_candidates:
        lock_version = db.execute(
            "SELECT lock_version FROM content_items WHERE id=?", (candidate_id,)
        ).fetchone()[0]
        archive_content(
            candidate_id,
            lock_version,
            actor="test-admin",
            now=NOW_DATETIME + timedelta(minutes=2),
        )
    assert _published_scenario_candidates(db, current["industry_id"]) == (
        (scenario_revision, "mfg_knowledge_assistant"),
    )
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    assert client.get("/industries/manufacturing").status_code == 200

    result = publish_content(
        industry_revision,
        1,
        actor="test-admin",
        now=NOW_DATETIME + timedelta(minutes=3),
    )

    assert (result.published_id, result.archived_id) == (
        industry_revision,
        current["id"],
    )
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (current["id"],)
    ).fetchone()[0] == "archived"
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (industry_revision,)
    ).fetchone()[0] == "published"
    assert client.get(f"/scenarios/{scenario['slug']}").status_code == 200
    assert client.get("/industries/manufacturing").status_code == 200


def test_industry_publish_rejects_when_all_published_scenario_candidates_have_blank_titles(
    client, db
):
    current, revision_id = _saved_industry_revision(db)
    assert client.get("/industries/manufacturing").status_code == 200
    candidates = _published_scenario_candidates(db, current["industry_id"])
    candidate_ids = tuple(candidate_id for candidate_id, _ in candidates)
    originals = _replace_first_block_titles(db, candidate_ids, "   ")
    damaged_before = client.get("/industries/manufacturing")
    assert damaged_before.status_code == 404
    state_before = _publication_state_snapshot(db, (current["id"], revision_id))

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "industry_public_incomplete"
    assert _publication_state_snapshot(db, (current["id"], revision_id)) == state_before
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=1)
    damaged_after = client.get("/industries/manufacturing")
    assert (damaged_after.status_code, damaged_after.data) == (
        damaged_before.status_code, damaged_before.data
    )

    _restore_block_titles(db, originals)
    assert client.get("/industries/manufacturing").status_code == 200


def test_industry_publish_continues_from_blank_candidates_to_a_healthy_scenario(
    client, db
):
    current, revision_id = _saved_industry_revision(db)
    candidates = _published_scenario_candidates(db, current["industry_id"])
    # The fallback data_process_foundation candidate is intentionally excluded.
    known_healthy = tuple(
        (candidate_id, code) for candidate_id, code in candidates
        if code in {
            "mfg_knowledge_assistant",
            "mfg_operations_reporting",
            "mfg_quality_inspection",
        }
    )
    assert len(known_healthy) == 3
    healthy_id, _ = max(known_healthy)
    earlier_ids = tuple(
        candidate_id for candidate_id, _ in candidates if candidate_id < healthy_id
    )
    assert earlier_ids
    _replace_first_block_titles(db, earlier_ids, "   ")
    candidate_ids = tuple(candidate_id for candidate_id, _ in candidates)
    candidates_before = _publication_state_snapshot(db, candidate_ids)

    result = publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert (result.published_id, result.archived_id) == (revision_id, current["id"])
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (revision_id,)
    ).fetchone()[0] == "published"
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (current["id"],)
    ).fetchone()[0] == "archived"
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_published'",
        (revision_id,),
    ).fetchone()[0] == 1
    assert _publication_state_snapshot(db, candidate_ids) == candidates_before
    assert client.get("/industries/manufacturing").status_code == 200


def test_immediate_publish_rejects_persisted_blank_block_title_and_keeps_current_public(
    client, db
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _inject_blank_block_title(db, revision_id)

    with pytest.raises(ContentValidationError) as error:
        publish_content(
            revision_id, lock_version, actor="test-admin", now=NOW_DATETIME
        )

    assert error.value.code == "block_title_invalid"
    _assert_unpublished_revision(
        db, current["id"], revision_id, lock_version=lock_version
    )
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


def test_schedule_rejects_persisted_blank_block_title_without_state_or_audit(
    client, db
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _inject_blank_block_title(db, revision_id)

    with pytest.raises(ContentValidationError) as error:
        schedule_content(
            revision_id,
            lock_version,
            NOW_DATETIME + timedelta(hours=1),
            actor="test-admin",
            now=NOW_DATETIME,
        )

    assert error.value.code == "block_title_invalid"
    _assert_unpublished_revision(
        db, current["id"], revision_id, lock_version=lock_version
    )
    assert db.execute(
        "SELECT publish_at FROM content_items WHERE id=?", (revision_id,)
    ).fetchone()[0] is None
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_scheduled'", (revision_id,)
    ).fetchone()[0] == 0
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


def test_due_blank_block_title_failure_keeps_current_public_and_isolates_healthy_peer(
    client, db
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    due = NOW_DATETIME + timedelta(hours=1)
    schedule_content(
        revision_id, lock_version, due, actor="test-admin", now=NOW_DATETIME
    )
    _inject_blank_block_title(db, revision_id)
    healthy = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='retail_ai_service' "
        "AND ci.status='published'"
    ).fetchone()
    healthy_revision = copy_revision(
        healthy["id"], actor="test-admin", now=NOW_DATETIME
    )
    schedule_content(
        healthy_revision, 1, due, actor="test-admin", now=NOW_DATETIME
    )

    result = publish_due_content(actor="test-admin", now=due)

    assert result.published_ids == (healthy_revision,)
    assert result.failures == ((revision_id, "validation_failed"),)
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=4)
    assert db.execute(
        "SELECT publish_at FROM content_items WHERE id=?", (revision_id,)
    ).fetchone()[0] is None
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_due_failed'", (revision_id,)
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (healthy_revision,)
    ).fetchone()[0] == "published"
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


def _corrupt_one_scenario_text_source(db, scenario_id, revision_id, source, value):
    """Keep a valid peer value and corrupt one required public text source."""
    if source == "industry":
        branch = db.execute(
            "SELECT ib.id AS branch_id,i.id AS industry_id FROM industry_branches ib "
            "JOIN industries i ON i.id=ib.industry_id WHERE i.code='retail' "
            "AND ib.status='published' ORDER BY ib.id LIMIT 1"
        ).fetchone()
        db.execute(
            "INSERT OR IGNORE INTO scenario_branches(scenario_id,industry_branch_id) VALUES (?,?)",
            (scenario_id, branch["branch_id"]),
        )
        db.execute("UPDATE industries SET name=? WHERE id=?", (value, branch["industry_id"]))
    elif source == "department":
        db.execute(
            "UPDATE departments SET name=? WHERE id=(SELECT department_id FROM "
            "scenario_departments WHERE scenario_id=? ORDER BY department_id LIMIT 1)",
            (value, scenario_id),
        )
    elif source == "pain":
        db.execute(
            "UPDATE pain_points SET name=? WHERE id=(SELECT pain_point_id FROM "
            "scenario_pains WHERE scenario_id=? ORDER BY pain_point_id LIMIT 1)",
            (value, scenario_id),
        )
    elif source == "input":
        legacy_value = (
            type(value) is not str
            or not value.strip()
            or len(value) > 300
            or "\x00" in value
        )
        if legacy_value:
            db.execute("PRAGMA ignore_check_constraints=ON")
        try:
            db.execute(
                "UPDATE scenario_public_inputs SET input_text=? WHERE id=(SELECT id FROM "
                "scenario_public_inputs WHERE content_item_id=? ORDER BY sort_order,id LIMIT 1)",
                (value, revision_id),
            )
        finally:
            if legacy_value:
                db.execute("PRAGMA ignore_check_constraints=OFF")
    elif source == "input_sort_order":
        db.execute("PRAGMA ignore_check_constraints=ON")
        try:
            db.execute(
                "UPDATE scenario_public_inputs SET sort_order=? WHERE id=(SELECT id FROM "
                "scenario_public_inputs WHERE content_item_id=? ORDER BY sort_order,id LIMIT 1)",
                (value, revision_id),
            )
        finally:
            db.execute("PRAGMA ignore_check_constraints=OFF")
    elif source == "deliverable":
        db.execute(
            "UPDATE service_deliverables SET title=? WHERE id=(SELECT sd.id FROM "
            "service_deliverables sd JOIN scenario_services ss ON ss.service_id=sd.service_id "
            "WHERE ss.scenario_id=? AND sd.status='published' ORDER BY sd.id LIMIT 1)",
            (value, scenario_id),
        )
    else:
        raise AssertionError(source)
    db.commit()


def _corrupt_one_industry_text_source(db, industry_id, source, value):
    table = {
        "pain": ("pain_points", "industry_id=?"),
        "department": ("departments", "industry_id=?"),
        "company_size": ("company_sizes", "1=1"),
    }[source]
    table_name, predicate = table
    parameters = (industry_id,) if source != "company_size" else ()
    row = db.execute(
        f"SELECT id FROM {table_name} WHERE status='published' AND {predicate} ORDER BY id LIMIT 1",
        parameters,
    ).fetchone()
    db.execute(f"UPDATE {table_name} SET name=? WHERE id=?", (value, row["id"]))
    db.commit()


@pytest.mark.parametrize("source", ("industry", "department", "pain", "input", "deliverable"))
@pytest.mark.parametrize("value", (sqlite3.Binary(b"not-text"), " "), ids=("blob", "blank"))
def test_scenario_formal_publication_rejects_each_mixed_invalid_required_text_source(
    client, db, source, value
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    before = client.get("/scenarios/mfg-knowledge-assistant")
    assert before.status_code == 200
    _corrupt_one_scenario_text_source(
        db, current["scenario_id"], revision_id, source, value
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)
    if source == "input":
        assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


@pytest.mark.parametrize("source", ("pain", "department", "company_size"))
@pytest.mark.parametrize("value", (sqlite3.Binary(b"not-text"), " "), ids=("blob", "blank"))
def test_industry_formal_publication_rejects_each_mixed_invalid_required_text_source(
    db, source, value
):
    current, revision_id = _saved_industry_revision(db)
    _corrupt_one_industry_text_source(db, current["industry_id"], source, value)

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "industry_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=1)


def test_due_scenario_with_blob_input_keeps_old_public_revision_and_isolates_batch_failure(client, db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    due = NOW_DATETIME + timedelta(hours=1)
    schedule_content(revision_id, lock_version, due, actor="test-admin", now=NOW_DATETIME)
    _corrupt_one_scenario_text_source(
        db, current["scenario_id"], revision_id, "input", sqlite3.Binary(b"not-text")
    )
    healthy = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='retail_ai_service' "
        "AND ci.status='published'"
    ).fetchone()
    healthy_revision = copy_revision(healthy["id"], actor="test-admin", now=NOW_DATETIME)
    schedule_content(healthy_revision, 1, due, actor="test-admin", now=NOW_DATETIME)

    result = publish_due_content(actor="test-admin", now=due)

    assert healthy_revision in result.published_ids
    assert (revision_id, "validation_failed") in result.failures
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=4)
    assert db.execute("SELECT publish_at FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] is None
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_due_failed'",
        (revision_id,),
    ).fetchone()[0] == 1
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


@pytest.mark.parametrize("source", ("industry", "department", "pain", "input", "deliverable"))
def test_public_scenario_read_gate_rejects_a_mixed_blob_required_text_source(client, db, source):
    scenario = db.execute(
        "SELECT s.id,ci.id AS content_item_id FROM scenarios s JOIN content_groups g "
        "ON g.scenario_id=s.id JOIN content_items ci ON ci.content_group_id=g.id "
        "WHERE s.code='mfg_knowledge_assistant' AND ci.status='draft'"
    ).fetchone()
    _corrupt_one_scenario_text_source(
        db, scenario["id"], scenario["content_item_id"], source, sqlite3.Binary(b"not-text")
    )
    publish_catalog(db)

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404
    document = page(client.get("/scenarios"))
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in document.select("[data-scenario-code]")
    }


@pytest.mark.parametrize("source", ("pain", "department", "company_size"))
def test_public_industry_read_gate_rejects_a_mixed_blob_required_text_source(client, db, source):
    industry = db.execute("SELECT id FROM industries WHERE code='manufacturing'").fetchone()
    _corrupt_one_industry_text_source(
        db, industry["id"], source, sqlite3.Binary(b"not-text")
    )
    publish_catalog(db)

    document = page(client.get("/industries"))
    assert "manufacturing" not in {
        card["data-industry-code"] for card in document.select("[data-industry-code]")
    }
    assert client.get("/industries/manufacturing").status_code == 404


def test_archived_invalid_industry_text_row_does_not_block_a_complete_replacement(db):
    current, revision_id = _saved_industry_revision(db)
    row = db.execute(
        "SELECT id FROM pain_points WHERE industry_id=? AND status='published' ORDER BY id LIMIT 1",
        (current["industry_id"],),
    ).fetchone()
    db.execute(
        "UPDATE pain_points SET name=?,status='archived' WHERE id=?",
        (sqlite3.Binary(b"not-text"), row["id"]),
    )
    db.commit()

    publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "published"


@pytest.mark.parametrize("bad_settings", (
    sqlite3.Binary(b"{}"),
    '{"unreviewed":"extra"}',
), ids=("blob", "wrong_schema"))
def test_public_projection_fails_closed_when_any_persisted_block_cannot_be_projected(
    client, db, bad_settings
):
    revision = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='mfg_knowledge_assistant' "
        "AND ci.status='draft'"
    ).fetchone()
    db.execute(
        "INSERT INTO content_blocks(content_item_id,block_type,title,body_html,settings_json,media_asset_id,sort_order) "
        "VALUES (?,'rich_text','无效持久化块','<p>不会公开</p>',?,NULL,99)",
        (revision["id"], bad_settings),
    )
    db.commit()
    publish_catalog(db)

    detail = client.get("/scenarios/mfg-knowledge-assistant")
    listing = client.get("/scenarios")

    assert detail.status_code == 404
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in page(listing).select("[data-scenario-code]")
    }


@pytest.mark.parametrize(("entry_type", "slug", "detail_path", "list_path", "card_selector", "code"), (
    ("scenario", "mfg-knowledge-assistant", "/scenarios/mfg-knowledge-assistant", "/scenarios", "[data-scenario-code]", "mfg_knowledge_assistant"),
    ("industry", "manufacturing", "/industries/manufacturing", "/industries", "[data-industry-code]", "manufacturing"),
))
@pytest.mark.parametrize("bad_order", (1.5, "not-an-integer"), ids=("real", "text"))
def test_public_projection_fails_closed_for_nonexact_persisted_block_sort_order(
    client, db, entry_type, slug, detail_path, list_path, card_selector, code, bad_order
):
    revision = db.execute(
        "SELECT id FROM content_items WHERE entry_type=? AND status='draft' AND slug=?",
        (entry_type, slug),
    ).fetchone()
    db.execute(
        "UPDATE content_blocks SET sort_order=? WHERE id=(SELECT id FROM content_blocks "
        "WHERE content_item_id=? ORDER BY sort_order,id LIMIT 1)",
        (bad_order, revision["id"]),
    )
    db.commit()
    publish_catalog(db)

    assert client.get(detail_path).status_code == 404
    assert code not in {
        card.get(f"data-{entry_type}-code")
        for card in page(client.get(list_path)).select(card_selector)
    }


def test_service_save_rejects_nonexact_block_sort_order(db):
    row = db.execute(
        "SELECT id,lock_version FROM content_items WHERE entry_type='scenario' "
        "AND status='draft' ORDER BY id LIMIT 1"
    ).fetchone()
    draft = publishing_repository.load_content_draft(db, row["id"])
    invalid_block = replace(draft.blocks[0], sort_order=1.5)

    with pytest.raises(ContentValidationError) as error:
        save_content_draft(
            row["id"], row["lock_version"], replace(draft, blocks=(invalid_block,)),
            actor="test-admin", now=NOW_DATETIME,
        )

    assert error.value.code == "block_order_invalid"


_UNICODE_PUBLIC_WHITESPACE = ("\u00a0", "\t", "\n", "\u3000")
_INVALID_PUBLIC_INPUTS = _UNICODE_PUBLIC_WHITESPACE + ("x" * 300 + " ",)


@pytest.mark.parametrize("value", _INVALID_PUBLIC_INPUTS, ids=("nbsp", "tab", "newline", "fullwidth", "raw-overlong"))
def test_immediate_publish_rejects_unicode_whitespace_scenario_input_and_keeps_current_public(
    client, db, value
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200
    _corrupt_one_scenario_text_source(
        db, current["scenario_id"], revision_id, "input", value
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


@pytest.mark.parametrize("value", _UNICODE_PUBLIC_WHITESPACE, ids=("nbsp", "tab", "newline", "fullwidth"))
def test_due_publish_rejects_unicode_whitespace_input_keeps_old_page_and_isolates_healthy_item(
    client, db, value
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    due = NOW_DATETIME + timedelta(hours=1)
    schedule_content(revision_id, lock_version, due, actor="test-admin", now=NOW_DATETIME)
    _corrupt_one_scenario_text_source(
        db, current["scenario_id"], revision_id, "input", value
    )
    healthy = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='retail_ai_service' "
        "AND ci.status='published'"
    ).fetchone()
    healthy_revision = copy_revision(healthy["id"], actor="test-admin", now=NOW_DATETIME)
    schedule_content(healthy_revision, 1, due, actor="test-admin", now=NOW_DATETIME)

    result = publish_due_content(actor="test-admin", now=due)

    assert healthy_revision in result.published_ids
    assert (revision_id, "validation_failed") in result.failures
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=4)
    assert db.execute("SELECT publish_at FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] is None
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_due_failed'",
        (revision_id,),
    ).fetchone()[0] == 1
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


@pytest.mark.parametrize(("source", "value"), (
    ("industry", "\u00a0"), ("department", "\t"),
    ("pain", "\n"), ("deliverable", "\u3000"),
))
def test_formal_scenario_publish_rejects_unicode_whitespace_in_every_other_live_text_source(
    db, source, value
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _corrupt_one_scenario_text_source(
        db, current["scenario_id"], revision_id, source, value
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


@pytest.mark.parametrize(("source", "value"), (
    ("pain", "\u00a0"), ("department", "\t"), ("company_size", "\n"),
))
def test_formal_industry_publish_rejects_unicode_whitespace_in_every_live_text_source(
    db, source, value
):
    current, revision_id = _saved_industry_revision(db)
    _corrupt_one_industry_text_source(db, current["industry_id"], source, value)

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "industry_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=1)


@pytest.mark.parametrize("bad_order", (1.5, "not-an-integer"), ids=("real", "text"))
def test_public_scenario_projection_requires_exact_persisted_input_sort_order(client, db, bad_order):
    revision = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='mfg_knowledge_assistant' "
        "AND ci.status='draft'"
    ).fetchone()
    db.execute("PRAGMA ignore_check_constraints=ON")
    try:
        db.execute(
            "UPDATE scenario_public_inputs SET sort_order=? WHERE id=(SELECT id FROM "
            "scenario_public_inputs WHERE content_item_id=? ORDER BY sort_order,id LIMIT 1)",
            (bad_order, revision["id"]),
        )
    finally:
        db.execute("PRAGMA ignore_check_constraints=OFF")
    db.commit()
    publish_catalog(db)

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"]
        for card in page(client.get("/scenarios")).select("[data-scenario-code]")
    }


@pytest.mark.parametrize("bad_order", (1.5, "not-an-integer"), ids=("real", "text"))
def test_formal_publish_rejects_legacy_nonexact_input_sort_order_and_keeps_current_public(
    client, db, bad_order
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200
    _corrupt_one_scenario_text_source(
        db, current["scenario_id"], revision_id, "input_sort_order", bad_order
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


def test_formal_publish_rejects_nul_input_without_archiving_current_public(client, db):
    """Catch formal publication accepting a NUL that later makes public input unsafe."""
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _corrupt_one_scenario_text_source(
        db, current["scenario_id"], revision_id, "input", "有效\x00输入"
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


def test_public_scenario_projection_fails_closed_for_legacy_nul_input(client, db):
    """Catch a public projection that renders a persisted NUL-containing input."""
    revision = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='mfg_knowledge_assistant' "
        "AND ci.status='draft'"
    ).fetchone()
    db.execute("PRAGMA ignore_check_constraints=ON")
    try:
        db.execute(
            "UPDATE scenario_public_inputs SET input_text=? WHERE id=(SELECT id FROM "
            "scenario_public_inputs WHERE content_item_id=? ORDER BY sort_order,id LIMIT 1)",
            ("有效\x00输入", revision["id"]),
        )
    finally:
        db.execute("PRAGMA ignore_check_constraints=OFF")
    db.commit()
    publish_catalog(db)

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"]
        for card in page(client.get("/scenarios")).select("[data-scenario-code]")
    }


def test_formal_publish_rejects_ready_pdf_share_image_without_archiving_current_public(client, db):
    """Catch a formal publish that promotes a PDF share image the image endpoint rejects."""
    current, revision_id, lock_version = _saved_scenario_revision(db)
    pdf_id = _ready_media(db, "formal-share.pdf", "application/pdf")
    draft = publishing_repository.load_content_draft(db, revision_id)
    lock_version = save_content_draft(
        revision_id,
        lock_version,
        replace(draft, share_image_media_id=pdf_id),
        actor="test-admin",
        now=NOW_DATETIME,
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "share_image_mime_invalid"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


def test_formal_publish_accepts_ready_image_share_image(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    image_id = _ready_media(db, "formal-share.png", "image/png")
    draft = publishing_repository.load_content_draft(db, revision_id)
    lock_version = save_content_draft(
        revision_id,
        lock_version,
        replace(draft, share_image_media_id=image_id),
        actor="test-admin",
        now=NOW_DATETIME,
    )

    result = publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert (result.published_id, result.archived_id) == (revision_id, current["id"])
    assert tuple(db.execute(
        "SELECT status,share_image_media_id FROM content_items WHERE id=?", (revision_id,)
    ).fetchone()) == ("published", image_id)
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "archived"


@pytest.mark.parametrize("bad_settings", (
    sqlite3.Binary(b"{}"),
    '{"unreviewed":"extra"}',
), ids=("blob", "wrong_schema"))
def test_formal_publish_rejects_any_unprojectable_persisted_block_before_archiving_current(
    db, bad_settings
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    db.execute(
        "INSERT INTO content_blocks(content_item_id,block_type,title,body_html,settings_json,media_asset_id,sort_order) "
        "VALUES (?,'rich_text','无效持久化块','<p>不会公开</p>',?,NULL,99)",
        (revision_id, bad_settings),
    )
    db.commit()

    with pytest.raises(ContentValidationError):
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


@pytest.mark.parametrize("raw", (
    r'"\ud800"',
    r'{"\ud800":"ok"}',
    r'{"items":["\ud800"]}',
))
def test_bounded_database_json_rejects_lone_surrogates_in_every_text_position(raw):
    with pytest.raises(ContentJsonError):
        decode_database_json(raw)


def _write_surrogate_block_settings(db, revision_id):
    db.execute(
        "UPDATE content_blocks SET block_type='steps',settings_json=? WHERE content_item_id=?",
        (r'{"items":["\ud800"]}', revision_id),
    )
    db.commit()


def test_formal_publish_rejects_surrogate_block_settings_without_archiving_current_revision(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _write_surrogate_block_settings(db, revision_id)

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "content_json_invalid"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


def test_due_surrogate_block_failure_is_validation_failed_and_does_not_stop_a_healthy_item(client, db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    due = NOW_DATETIME + timedelta(hours=1)
    schedule_content(revision_id, lock_version, due, actor="test-admin", now=NOW_DATETIME)
    _write_surrogate_block_settings(db, revision_id)
    healthy = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='retail_ai_service' "
        "AND ci.status='published'"
    ).fetchone()
    healthy_revision = copy_revision(healthy["id"], actor="test-admin", now=NOW_DATETIME)
    schedule_content(healthy_revision, 1, due, actor="test-admin", now=NOW_DATETIME)

    result = publish_due_content(actor="test-admin", now=due)

    assert healthy_revision in result.published_ids
    assert (revision_id, "validation_failed") in result.failures
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=4)
    assert db.execute("SELECT publish_at FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] is None
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_due_failed'",
        (revision_id,),
    ).fetchone()[0] == 1
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


@pytest.mark.parametrize("source", (
    "implementation_steps_json", "prerequisites_json", "acceptance_json",
))
def test_surrogate_service_json_is_private_and_rejected_by_formal_publication(client, db, source):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _replace_scenario_json_source(
        db, current["scenario_id"], revision_id, source, r'["\ud800"]'
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "content_json_invalid"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)
    db.execute(
        "UPDATE content_items SET status='archived',archived_at=?,updated_at=? WHERE id=?",
        (NOW, NOW, current["id"]),
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at=? WHERE id=?",
        (NOW, revision_id),
    )
    db.commit()
    detail = client.get("/scenarios/mfg-knowledge-assistant")
    listing = client.get("/scenarios")
    assert detail.status_code == 404
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in page(listing).select("[data-scenario-code]")
    }


def test_bounded_database_json_keeps_normal_chinese_and_emoji_text():
    assert decode_database_json('{"items":["中文😀"]}') == {"items": ["中文😀"]}


def test_industry_with_blank_overview_cannot_replace_a_healthy_public_revision(db):
    current, revision_id = _saved_industry_revision(db)
    draft = publishing_repository.load_content_draft(db, revision_id)
    lock_version = save_content_draft(
        revision_id,
        1,
        replace(draft, blocks=(ContentBlock("rich_text", body_html="<p> </p>"),)),
        actor="test-admin",
        now=NOW_DATETIME,
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "industry_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


@pytest.mark.parametrize("missing", ("pain", "department", "company_size", "scenario", "service"))
def test_industry_publication_requires_each_live_public_dependency(db, missing):
    current, revision_id = _saved_industry_revision(db)
    industry_id = current["industry_id"]
    if missing == "pain":
        db.execute("UPDATE pain_points SET status='archived' WHERE industry_id=?", (industry_id,))
    elif missing == "department":
        db.execute("UPDATE departments SET status='archived' WHERE industry_id=?", (industry_id,))
    elif missing == "company_size":
        db.execute("UPDATE company_sizes SET status='archived'")
    elif missing == "scenario":
        db.execute(
            "UPDATE scenarios SET status='archived' WHERE id IN ("
            "SELECT sb.scenario_id FROM scenario_branches sb JOIN industry_branches ib "
            "ON ib.id=sb.industry_branch_id WHERE ib.industry_id=?)",
            (industry_id,),
        )
    else:
        db.execute(
            "UPDATE services SET status='archived' WHERE id IN ("
            "SELECT DISTINCT ss.service_id FROM scenario_services ss JOIN scenario_branches sb "
            "ON sb.scenario_id=ss.scenario_id JOIN industry_branches ib "
            "ON ib.id=sb.industry_branch_id WHERE ib.industry_id=?)",
            (industry_id,),
        )
    db.commit()

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "industry_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=1)


def test_public_complete_industry_revision_replaces_its_previous_revision(db):
    current, revision_id = _saved_industry_revision(db)

    result = publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert (result.published_id, result.archived_id) == (revision_id, current["id"])
    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "published"


def test_due_industry_with_later_missing_overview_fails_before_archiving_current_revision(db):
    current, revision_id = _saved_industry_revision(db)
    due = NOW_DATETIME + timedelta(hours=1)
    schedule_content(revision_id, 1, due, actor="test-admin", now=NOW_DATETIME)
    db.execute("UPDATE content_blocks SET body_html='<p> </p>' WHERE content_item_id=?", (revision_id,))
    db.commit()

    result = publish_due_content(actor="test-admin", now=due)

    assert result.published_ids == ()
    assert result.failures == ((revision_id, "validation_failed"),)
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=3)
    assert db.execute("SELECT publish_at FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] is None


def _break_scenario_public_source(db, scenario_id, revision_id, source):
    if source == "industry":
        db.execute("UPDATE industries SET status='archived' WHERE id=(SELECT i.id FROM industries i JOIN industry_branches ib ON ib.industry_id=i.id JOIN scenario_branches sb ON sb.industry_branch_id=ib.id WHERE sb.scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "branch":
        db.execute("UPDATE industry_branches SET status='archived' WHERE id=(SELECT industry_branch_id FROM scenario_branches WHERE scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "department":
        db.execute("UPDATE departments SET status='archived' WHERE id=(SELECT department_id FROM scenario_departments WHERE scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "pain":
        db.execute("UPDATE pain_points SET status='archived' WHERE id=(SELECT pain_point_id FROM scenario_pains WHERE scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "maturity":
        db.execute("DELETE FROM content_maturity_levels WHERE content_item_id=?", (revision_id,))
    elif source == "input":
        db.execute("DELETE FROM scenario_public_inputs WHERE content_item_id=?", (revision_id,))
    elif source == "service":
        db.execute("UPDATE services SET min_weeks=0 WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "prerequisite":
        db.execute("UPDATE services SET prerequisites_json='[\"\"]' WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "output":
        db.execute(
            "UPDATE service_deliverables SET title=' ' WHERE service_id IN "
            "(SELECT service_id FROM scenario_services WHERE scenario_id=?) "
            "AND status='published'",
            (scenario_id,),
        )
    elif source == "risk":
        db.execute("UPDATE scenarios SET risk_codes_json='[\"unknown\"]' WHERE id=?", (scenario_id,))
    elif source == "narrative":
        db.execute("UPDATE content_blocks SET body_html='' WHERE content_item_id=?", (revision_id,))
    else:
        raise AssertionError(source)
    db.commit()


@pytest.mark.parametrize("source", (
    "industry", "branch", "department", "pain", "maturity", "input", "service",
    "prerequisite", "output", "risk", "narrative",
))
def test_incomplete_scenario_revision_is_rejected_before_replacing_public_revision(db, source):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _break_scenario_public_source(db, current["scenario_id"], revision_id, source)

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "published"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "draft"
    assert db.execute("SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'", (revision_id,)).fetchone()[0] == 0


def test_due_scenario_with_later_missing_input_fails_without_archiving_current_revision(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    scheduled = schedule_content(
        revision_id, lock_version, NOW_DATETIME + timedelta(hours=1), actor="test-admin", now=NOW_DATETIME
    )
    _break_scenario_public_source(db, current["scenario_id"], revision_id, "input")

    result = publish_due_content(actor="test-admin", now=NOW_DATETIME + timedelta(hours=1))

    assert result.published_ids == ()
    assert result.failures == ((revision_id, "validation_failed"),)
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "published"
    draft = db.execute("SELECT status,publish_at FROM content_items WHERE id=?", (revision_id,)).fetchone()
    assert tuple(draft) == ("draft", None)
    assert db.execute("SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'", (revision_id,)).fetchone()[0] == 0


def test_draft_input_damage_does_not_change_current_public_revision(published_catalog, db):
    current, revision_id, _ = _saved_scenario_revision(db)
    before = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))
    before_inputs = [item.get_text(strip=True) for item in before.select('[data-content-section="inputs"] li')]
    db.execute("DELETE FROM scenario_public_inputs WHERE content_item_id=?", (revision_id,))
    db.commit()

    after = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))

    assert [item.get_text(strip=True) for item in after.select('[data-content-section="inputs"] li')] == before_inputs
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "published"


def test_copied_inputs_are_revision_bound_and_published_rows_are_immutable(db):
    current, revision_id, _ = _saved_scenario_revision(db)
    previous = db.execute(
        "SELECT input_text,sort_order FROM scenario_public_inputs WHERE content_item_id=? ORDER BY sort_order,id",
        (current["id"],),
    ).fetchall()
    copied = db.execute(
        "SELECT input_text,sort_order FROM scenario_public_inputs WHERE content_item_id=? ORDER BY sort_order,id",
        (revision_id,),
    ).fetchall()

    assert copied == previous
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE scenario_public_inputs SET input_text='不可修改' WHERE content_item_id=?", (current["id"],))


def test_archived_historical_deliverable_does_not_block_valid_published_replacement(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    service_id = db.execute(
        "SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1", (current["scenario_id"],)
    ).fetchone()[0]
    db.execute(
        "INSERT INTO service_deliverables (code,service_id,title,status,sort_order) "
        "VALUES ('test:replacement-deliverable',?,'保留交付物','published',999)",
        (service_id,),
    )
    db.execute(
        "UPDATE service_deliverables SET status='archived' WHERE id=("
        "SELECT id FROM service_deliverables WHERE service_id=? AND status='published' ORDER BY id LIMIT 1)",
        (service_id,),
    )
    db.commit()

    publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "published"


def test_published_blank_deliverable_cannot_replace_a_healthy_scenario_revision(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    service_id = db.execute(
        "SELECT service_id FROM scenario_services WHERE scenario_id=? ORDER BY service_id LIMIT 1",
        (current["scenario_id"],),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO service_deliverables (code,service_id,title,status,sort_order) "
        "VALUES ('test:published-blank-deliverable',?,' ','published',999)",
        (service_id,),
    )
    db.commit()

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


def test_archived_blank_deliverable_does_not_block_a_valid_published_replacement(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    service_id = db.execute(
        "SELECT service_id FROM scenario_services WHERE scenario_id=? ORDER BY service_id LIMIT 1",
        (current["scenario_id"],),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO service_deliverables (code,service_id,title,status,sort_order) "
        "VALUES ('test:archived-blank-deliverable',?,' ','archived',999)",
        (service_id,),
    )
    db.commit()

    publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "published"


def _replace_scenario_json_source(db, scenario_id, revision_id, source, raw):
    if source == "settings_json":
        db.execute("UPDATE content_blocks SET settings_json=? WHERE content_item_id=?", (raw, revision_id))
    elif source == "risk_codes_json":
        db.execute("UPDATE scenarios SET risk_codes_json=? WHERE id=?", (raw, scenario_id))
    else:
        db.execute(
            f"UPDATE services SET {source}=? WHERE id=("
            "SELECT service_id FROM scenario_services WHERE scenario_id=? ORDER BY service_id LIMIT 1)",
            (raw, scenario_id),
        )
    db.commit()


@pytest.mark.parametrize(("source", "raw"), (
    ("settings_json", sqlite3.Binary(b"{}")),
    ("risk_codes_json", sqlite3.Binary(b'["process_variance"]')),
    ("risk_codes_json", sqlite3.Binary(b"\xff")),
    ("risk_codes_json", "[" * 1200 + '"process_variance"' + "]" * 1200),
    ("risk_codes_json", "[" + "9" * 20_000 + "]"),
    ("implementation_steps_json", sqlite3.Binary(b'["step"]')),
    ("prerequisites_json", sqlite3.Binary(b'["prerequisite"]')),
    ("acceptance_json", sqlite3.Binary(b'["acceptance"]')),
))
def test_formal_publish_rejects_non_text_json_without_archiving_current_scenario(
    db, source, raw
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _replace_scenario_json_source(db, current["scenario_id"], revision_id, source, raw)

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "content_json_invalid"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


@pytest.mark.parametrize("source", ("steps", "acceptance", "budget", "core_name", "narrative", "malformed_json"))
def test_public_scenario_fails_closed_for_incomplete_or_malformed_required_data(client, db, source):
    scenario = db.execute("SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'").fetchone()
    if source == "steps":
        db.execute("UPDATE services SET implementation_steps_json='[null]' WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario["id"],))
    elif source == "acceptance":
        db.execute("UPDATE services SET acceptance_json='[\"\"]' WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario["id"],))
    elif source == "budget":
        db.execute("UPDATE services SET min_budget=0 WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario["id"],))
    elif source == "core_name":
        db.execute("UPDATE departments SET name=' ' WHERE id=(SELECT department_id FROM scenario_departments WHERE scenario_id=? LIMIT 1)", (scenario["id"],))
    elif source == "narrative":
        db.execute("UPDATE content_blocks SET body_html='<p> </p>' WHERE content_item_id=(SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id WHERE g.scenario_id=? LIMIT 1)", (scenario["id"],))
    else:
        db.execute("UPDATE services SET implementation_steps_json='{' WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario["id"],))
    db.commit()
    publish_catalog(db)

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404


def test_all_public_complete_seeded_scenario_drafts_pass_the_formal_publish_gate(db):
    rows = db.execute("SELECT id,lock_version FROM content_items WHERE entry_type='scenario' AND status='draft' ORDER BY id").fetchall()

    results = []
    rejected = []
    for row in rows:
        try:
            results.append(publish_content(row["id"], row["lock_version"], actor="test-admin", now=NOW_DATETIME))
        except ContentValidationError:
            rejected.append(row["id"])

    assert len(results) == 12
    assert len(rejected) == 1
    rejected_code = db.execute(
        "SELECT s.code FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE ci.id=?", (rejected[0],)
    ).fetchone()[0]
    assert rejected_code == "data_process_foundation"
    assert db.execute("SELECT COUNT(*) FROM content_items WHERE entry_type='scenario' AND status='published'").fetchone()[0] == 12


@pytest.mark.parametrize("target", ("industry", "department", "pain"))
def test_archived_related_core_rows_are_omitted_from_public_cards_and_details(published_catalog, db, target):
    scenario = db.execute("SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'").fetchone()
    table = {"industry": "industries", "department": "departments", "pain": "pain_points"}[target]
    if target == "industry":
        row = db.execute(
            "SELECT i.id FROM industries i JOIN industry_branches ib ON ib.industry_id=i.id "
            "JOIN scenario_branches sb ON sb.industry_branch_id=ib.id WHERE sb.scenario_id=? LIMIT 1", (scenario["id"],)
        ).fetchone()
    else:
        link_table = "scenario_departments" if target == "department" else "scenario_pains"
        column = "department_id" if target == "department" else "pain_point_id"
        row = db.execute(f"SELECT {column} AS id FROM {link_table} WHERE scenario_id=? LIMIT 1", (scenario["id"],)).fetchone()
    marker = f"REVIEW-ARCHIVED-{target.upper()}"
    db.execute(f"UPDATE {table} SET name=?,status='archived' WHERE id=?", (marker, row["id"]))
    db.commit()

    card = page(published_catalog.get("/scenarios"))
    detail = published_catalog.get("/scenarios/mfg-knowledge-assistant")
    assert marker not in card.get_text()
    if target == "pain":
        assert detail.status_code == 200
        assert marker not in page(detail).get_text()
    else:
        remaining = db.execute(
            "SELECT COUNT(*) FROM scenario_branches sb JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
            "JOIN industries i ON i.id=ib.industry_id WHERE sb.scenario_id=? "
            "AND ib.status='published' AND i.status='published' AND trim(i.name)<>''"
            if target == "industry" else
            "SELECT COUNT(*) FROM scenario_departments sd JOIN departments d ON d.id=sd.department_id "
            "WHERE sd.scenario_id=? AND d.status='published' AND trim(d.name)<>''",
            (scenario["id"],),
        ).fetchone()[0]
        if remaining:
            assert detail.status_code == 200
            assert marker not in page(detail).get_text()
        else:
            assert detail.status_code == 404
            assert "mfg_knowledge_assistant" not in {
                node["data-scenario-code"] for node in card.select("[data-scenario-code]")
            }
            return
    cards = catalog.public_scenarios(catalog.ScenarioFilters(), catalog.PageRequest(1, 20), NOW_DATETIME)
    matched = next(item for item in cards.items if item.code == "mfg_knowledge_assistant")
    if target == "industry":
        assert marker not in matched.industries
    elif target == "department":
        assert marker not in matched.departments
    else:
        assert marker not in page(detail).get_text()


def test_archived_industry_branch_cannot_match_public_industry_filter(published_catalog, db):
    db.execute(
        "UPDATE industry_branches SET status='archived' WHERE id IN ("
        "SELECT ib.id FROM scenario_branches sb JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
        "JOIN scenarios s ON s.id=sb.scenario_id WHERE s.code='mfg_knowledge_assistant')"
    )
    db.commit()

    document = page(published_catalog.get("/scenarios?industry=manufacturing"))
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in document.select("[data-scenario-code]")
    }


@pytest.mark.parametrize("kind,table", (("industry", "industries"), ("department", "departments")))
def test_archived_core_codes_are_rejected_by_public_filter_parser(db, kind, table):
    row = db.execute(f"SELECT code FROM {table} WHERE status='published' ORDER BY id LIMIT 1").fetchone()
    db.execute(f"UPDATE {table} SET status='archived' WHERE code=?", (row["code"],))
    db.commit()

    filters = catalog.parse_public_scenario_filters({kind: row["code"]})

    assert getattr(filters, kind) == ""


@pytest.mark.parametrize("path", ("/industries", "/scenarios"))
def test_public_catalog_list_has_trusted_canonical_and_description(published_catalog, path):
    document = page(published_catalog.get(path, headers={"Host": "untrusted.example"}))
    assert document.select_one('link[rel="canonical"]')["href"] == f"https://test.example{path}"
    assert document.select_one('meta[name="description"]')["content"]


def test_scenario_without_published_pains_cannot_replace_current_revision(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    db.execute("DELETE FROM scenario_pains WHERE scenario_id=?", (current["scenario_id"],))
    db.commit()

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "published"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "draft"
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'",
        (revision_id,),
    ).fetchone()[0] == 0


def test_scenario_without_published_pains_is_private_404(client, db):
    scenario_id = db.execute(
        "SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'"
    ).fetchone()[0]
    publish_catalog(db)
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200
    db.execute("DELETE FROM scenario_pains WHERE scenario_id=?", (scenario_id,))
    db.commit()

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404


@pytest.mark.parametrize(("column", "raw_json"), (
    ("implementation_steps_json", "true"),
    ("implementation_steps_json", "1"),
    ("implementation_steps_json", '"步骤"'),
    ("implementation_steps_json", '{"步骤":"一"}'),
    ("prerequisites_json", "true"),
    ("prerequisites_json", "1"),
    ("prerequisites_json", '"前置条件"'),
    ("prerequisites_json", '{"前置":"条件"}'),
    ("acceptance_json", "true"),
    ("acceptance_json", "1"),
    ("acceptance_json", '"验收"'),
    ("acceptance_json", '{"验收":"条件"}'),
    ("risk_codes_json", "true"),
    ("risk_codes_json", "1"),
    ("risk_codes_json", '"process_variance"'),
    ("risk_codes_json", '{"process_variance":"风险"}'),
))
def test_wrong_json_containers_are_private_404_not_iterated_as_values(client, db, column, raw_json):
    scenario = db.execute(
        "SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'"
    ).fetchone()
    if column == "risk_codes_json":
        db.execute("UPDATE scenarios SET risk_codes_json=? WHERE id=?", (raw_json, scenario["id"]))
    else:
        db.execute(
            f"UPDATE services SET {column}=? WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)",
            (raw_json, scenario["id"]),
        )
    db.commit()
    publish_catalog(db)
    client.application.config["PROPAGATE_EXCEPTIONS"] = False

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404


@pytest.mark.parametrize(("source", "raw"), (
    ("settings_json", sqlite3.Binary(b"{}")),
    ("risk_codes_json", sqlite3.Binary(b'["process_variance"]')),
    ("risk_codes_json", sqlite3.Binary(b"\xff")),
    ("risk_codes_json", "[" * 1200 + '"process_variance"' + "]" * 1200),
    ("risk_codes_json", "[" + "9" * 20_000 + "]"),
    ("implementation_steps_json", sqlite3.Binary(b'["step"]')),
    ("prerequisites_json", sqlite3.Binary(b'["prerequisite"]')),
    ("acceptance_json", sqlite3.Binary(b'["acceptance"]')),
))
def test_public_catalog_fails_closed_for_non_text_or_unbounded_json(
    client, db, source, raw
):
    scenario = db.execute(
        "SELECT s.id,ci.id AS content_item_id FROM scenarios s JOIN content_groups g "
        "ON g.scenario_id=s.id JOIN content_items ci ON ci.content_group_id=g.id "
        "WHERE s.code='mfg_knowledge_assistant' AND ci.status='draft'"
    ).fetchone()
    _replace_scenario_json_source(db, scenario["id"], scenario["content_item_id"], source, raw)
    publish_catalog(db)
    client.application.config["PROPAGATE_EXCEPTIONS"] = False

    detail = client.get("/scenarios/mfg-knowledge-assistant")
    listing = client.get("/scenarios")

    assert detail.status_code == 404
    assert listing.status_code == 200
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in page(listing).select("[data-scenario-code]")
    }


@pytest.mark.parametrize(("missing", "expected_total"), (("inputs", 11), ("services", 9)))
def test_public_scenario_list_and_filtered_list_omit_detail_incomplete_cards(client, db, missing, expected_total):
    if missing == "inputs":
        row = db.execute(
            "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
            "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='mfg_knowledge_assistant' "
            "AND ci.status='draft'"
        ).fetchone()
        db.execute("DELETE FROM scenario_public_inputs WHERE content_item_id=?", (row["id"],))
    else:
        db.execute(
            "UPDATE services SET status='archived' WHERE id IN ("
            "SELECT ss.service_id FROM scenario_services ss JOIN scenarios s ON s.id=ss.scenario_id "
            "WHERE s.code='mfg_knowledge_assistant')"
        )
    publish_catalog(db)

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404
    for path in ("/scenarios", "/scenarios?industry=manufacturing"):
        document = page(client.get(path))
        assert "mfg_knowledge_assistant" not in {
            card["data-scenario-code"] for card in document.select("[data-scenario-code]")
        }
    projection = catalog.public_scenarios(catalog.ScenarioFilters(), catalog.PageRequest(1, 20), NOW_DATETIME)
    assert projection.total == expected_total
    assert "mfg_knowledge_assistant" not in {card.code for card in projection.items}
    assert "retail_ai_service" in {card.code for card in projection.items}


@pytest.mark.parametrize("missing", ("overview", "pains", "departments", "company_sizes", "scenarios", "services"))
def test_industry_list_and_detail_require_real_published_sections(client, db, missing):
    industry = db.execute("SELECT id FROM industries WHERE code='manufacturing'").fetchone()
    if missing == "overview":
        db.execute(
            "UPDATE content_blocks SET body_html='<p> </p>' WHERE content_item_id=("
            "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
            "WHERE g.industry_id=? AND ci.status='draft')",
            (industry["id"],),
        )
    elif missing == "pains":
        db.execute("UPDATE pain_points SET status='archived' WHERE industry_id=?", (industry["id"],))
    elif missing == "departments":
        db.execute("UPDATE departments SET status='archived' WHERE industry_id=?", (industry["id"],))
    elif missing == "company_sizes":
        db.execute("UPDATE company_sizes SET status='archived'")
    elif missing == "scenarios":
        db.execute(
            "DELETE FROM scenario_public_inputs WHERE content_item_id IN ("
            "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
            "JOIN scenario_branches sb ON sb.scenario_id=g.scenario_id "
            "JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
            "WHERE ci.status='draft' AND ib.industry_id=?)",
            (industry["id"],),
        )
    else:
        db.execute(
            "UPDATE services SET status='archived' WHERE id IN ("
            "SELECT DISTINCT ss.service_id FROM scenario_services ss JOIN scenario_branches sb ON sb.scenario_id=ss.scenario_id "
            "JOIN industry_branches ib ON ib.id=sb.industry_branch_id WHERE ib.industry_id=?)",
            (industry["id"],),
        )
    publish_catalog(db)

    document = page(client.get("/industries"))
    assert "manufacturing" not in {card["data-industry-code"] for card in document.select("[data-industry-code]")}
    assert client.get("/industries/manufacturing").status_code == 404


def _corrupt_scenario_range(db, scenario_id, source, minimum, maximum):
    columns = {
        "core_weeks": ("scenarios", "min_weeks", "max_weeks"),
        "service_weeks": ("services", "min_weeks", "max_weeks"),
        "service_budget": ("services", "min_budget", "max_budget"),
    }[source]
    table, minimum_column, maximum_column = columns
    if table == "scenarios":
        db.execute(
            f"UPDATE {table} SET {minimum_column}=?,{maximum_column}=? WHERE id=?",
            (minimum, maximum, scenario_id),
        )
    else:
        db.execute(
            f"UPDATE {table} SET {minimum_column}=?,{maximum_column}=? WHERE id IN ("
            "SELECT service_id FROM scenario_services WHERE scenario_id=?)",
            (minimum, maximum, scenario_id),
        )
    db.commit()


@pytest.mark.parametrize(
    ("source", "minimum", "maximum"),
    (
        ("service_budget", float("inf"), float("inf")),
        ("service_budget", float("-inf"), float("-inf")),
        ("core_weeks", 1.5, 2.5),
        ("service_weeks", 1.5, 2.5),
    ),
    ids=("positive-infinity-budget", "negative-infinity-budget", "fractional-core-weeks", "fractional-service-weeks"),
)
def test_formal_publish_rejects_nonfinite_budget_and_nonintegral_weeks_without_replacing_current(
    db, source, minimum, maximum
):
    """Keep a saved candidate draft when core range values cannot form public ranges."""
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _corrupt_scenario_range(
        db, current["scenario_id"], source, minimum, maximum,
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


@pytest.mark.parametrize(
    ("source", "minimum", "maximum"),
    (
        ("service_budget", float("inf"), float("inf")),
        ("service_budget", float("-inf"), float("-inf")),
        ("core_weeks", 1.5, 2.5),
        ("service_weeks", 1.5, 2.5),
    ),
    ids=("positive-infinity-budget", "negative-infinity-budget", "fractional-core-weeks", "fractional-service-weeks"),
)
def test_public_scenario_fails_closed_for_legacy_nonfinite_budget_and_nonintegral_weeks(
    client, db, source, minimum, maximum
):
    """Never keep a legacy range on a public card when its detail is unsafe."""
    scenario_id = db.execute(
        "SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'"
    ).fetchone()[0]
    _corrupt_scenario_range(db, scenario_id, source, minimum, maximum)
    publish_catalog(db)

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"]
        for card in page(client.get("/scenarios")).select("[data-scenario-code]")
    }


def test_due_nonintegral_core_weeks_failure_is_isolated_from_a_healthy_scenario(client, db):
    """Ensure one due candidate with fractional core weeks cannot stop its healthy peer."""
    current, revision_id, lock_version = _saved_scenario_revision(db)
    due = NOW_DATETIME + timedelta(hours=1)
    schedule_content(revision_id, lock_version, due, actor="test-admin", now=NOW_DATETIME)
    _corrupt_scenario_range(
        db, current["scenario_id"], "core_weeks", 1.5, 2.5,
    )
    healthy = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='retail_ai_service' "
        "AND ci.status='published'"
    ).fetchone()
    healthy_revision = copy_revision(healthy["id"], actor="test-admin", now=NOW_DATETIME)
    schedule_content(healthy_revision, 1, due, actor="test-admin", now=NOW_DATETIME)

    result = publish_due_content(actor="test-admin", now=due)

    assert healthy_revision in result.published_ids
    assert (revision_id, "validation_failed") in result.failures
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=4)
    assert db.execute(
        "SELECT publish_at FROM content_items WHERE id=?", (revision_id,)
    ).fetchone()[0] is None
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_due_failed'", (revision_id,)
    ).fetchone()[0] == 1


def test_formal_publish_rejects_corrupted_draft_top_level_nul_without_archiving_current(client, db):
    """Catch publication of an unreadable top-level title injected after save."""
    current, revision_id, lock_version = _saved_scenario_revision(db)
    db.execute(
        "UPDATE content_items SET title=? WHERE id=?", ("有效\x00标题", revision_id)
    )
    db.commit()

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "title_invalid"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


@pytest.mark.parametrize(
    ("entry_type", "slug", "detail_path", "list_path", "selector", "code"),
    (
        ("scenario", "mfg-knowledge-assistant", "/scenarios/mfg-knowledge-assistant", "/scenarios", "[data-scenario-code]", "mfg_knowledge_assistant"),
        ("industry", "manufacturing", "/industries/manufacturing", "/industries", "[data-industry-code]", "manufacturing"),
    ),
)
@pytest.mark.parametrize("field", ("title", "summary", "seo_title", "seo_description"))
def test_public_catalog_fails_closed_for_legacy_top_level_nul(
    client, db, entry_type, slug, detail_path, list_path, selector, code, field
):
    """Keep both public lists and details private for a malformed persisted item field."""
    revision = db.execute(
        "SELECT id FROM content_items WHERE entry_type=? AND status='draft' AND slug=?",
        (entry_type, slug),
    ).fetchone()
    db.execute(
        f"UPDATE content_items SET {field}=? WHERE id=?", (f"有效\x00{field}", revision["id"])
    )
    db.commit()
    publish_catalog(db)

    assert client.get(detail_path).status_code == 404
    assert code not in {
        card.get(f"data-{entry_type}-code")
        for card in page(client.get(list_path)).select(selector)
    }


def _write_legacy_invalid_plain_block(db, revision_id, source, value):
    if source == "title":
        db.execute(
            "UPDATE content_blocks SET title=? WHERE id=(SELECT id FROM content_blocks "
            "WHERE content_item_id=? ORDER BY sort_order,id LIMIT 1)",
            (value, revision_id),
        )
    else:
        block_type, settings = {
            "image_alt": ("image_text", {"alignment": "left", "alt_text": value}),
            "metric_value": ("metric", {"value": value, "unit": "项"}),
            "metric_unit": ("metric", {"value": "10", "unit": value}),
            "step_item": ("steps", {"items": [value]}),
            "download_label": ("download", {"label": value}),
            "cta_label": ("cta", {"label": value, "url": "/assessment", "style": "primary"}),
        }[source]
        db.execute(
            "INSERT INTO content_blocks(content_item_id,block_type,title,body_html,settings_json,media_asset_id,sort_order) "
            "VALUES (?,?,?,'<p>合法正文</p>',?,NULL,99)",
            (revision_id, block_type, "合法块标题", json.dumps(settings, ensure_ascii=False)),
        )
    db.commit()


@pytest.mark.parametrize(
    "source", ("title", "image_alt", "metric_value", "metric_unit", "step_item", "download_label", "cta_label"),
)
@pytest.mark.parametrize("value", ("有效\x00文本", " "), ids=("nul", "blank"))
def test_public_scenario_fails_closed_for_legacy_invalid_block_plain_text(client, db, source, value):
    """Reject each persisted title/renderer setting that save-time exact text protects."""
    revision = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='mfg_knowledge_assistant' "
        "AND ci.status='draft'"
    ).fetchone()
    _write_legacy_invalid_plain_block(db, revision["id"], source, value)
    publish_catalog(db)

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"]
        for card in page(client.get("/scenarios")).select("[data-scenario-code]")
    }
