from datetime import datetime
import hashlib

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader
from pathlib import Path
from PIL import Image
import pytest
import re

from content_clock import SHANGHAI
from content_contracts import CaseMetric, ContentBlock, ContentDraft
from publishing_service import create_content_draft, publish_content


def _page(response):
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


@pytest.fixture()
def editorial_public_routes(client, db):
    """Publish only the truthful fixture values needed by the public documents."""
    now = datetime(2026, 8, 25, 10, 0, tzinfo=SHANGHAI)
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: now

    attachment_id = db.execute(
        "INSERT INTO media_assets (storage_name,display_name,detected_mime,byte_size,sha256,"
        "status,created_at,updated_at) VALUES (?,?,?,?,?,'pending',?,?)",
        (
            "editorial-review.pdf",
            "审核材料.pdf",
            "application/pdf",
            1,
            hashlib.sha256(b"editorial-review").hexdigest(),
            "2026-08-25 10:00:00",
            "2026-08-25 10:00:00",
        ),
    ).lastrowid
    db.execute(
        "UPDATE media_assets SET status='ready',scan_result_code='safe',"
        "scan_checked_at='2026-08-25 10:00:00',ready_at='2026-08-25 10:00:00',"
        "updated_at='2026-08-25 10:00:00' WHERE id=?",
        (attachment_id,),
    )
    db.commit()

    case = ContentDraft(
        entry_type="case",
        slug="editorial-evidence-case",
        title="经授权匿名的证据案例",
        summary="经人工审核的实施过程与量化结果。",
        seo_title="经授权匿名的证据案例",
        seo_description="查看经审核的企业实施案例与统计指标。",
        extension={
            "verification_code": "authorized_anonymous",
            "is_anonymized": 1,
            "basis_type": "internal_delivery_record",
            "private_basis_reference": "internal-editorial-reference",
            "source_url": None,
            "source_url_sha256": None,
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "is_verified": 1,
            "review_confirmed": 1,
            "verified_at": "2026-08-25 10:00:00",
        },
        blocks=(ContentBlock("rich_text", "实施过程", "<p>已验证实施过程。</p>"),),
        metrics=(
            CaseMetric(
                "报表处理时间",
                "8",
                "2",
                "小时",
                "连续 30 天",
                "依据交付记录中的人工与自动化时长对比。",
            ),
        ),
    )
    resource_url = "https://example.com/editorial-review"
    resource = ContentDraft(
        entry_type="resource",
        slug="editorial-review-dossier",
        title="经审核的资源档案",
        summary="只展示经来源、版权与附件审核的真实资源。",
        seo_title="经审核的资源档案",
        seo_description="查看经审核的公开资源档案。",
        extension={
            "resource_type": "report",
            "is_original": 0,
            "source_name": "公开研究机构",
            "source_url": resource_url,
            "source_url_sha256": hashlib.sha256(resource_url.encode()).hexdigest(),
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "original_published_at": "2026-08-20 09:30:00",
            "copyright_notice": "原文版权归公开研究机构所有。",
            "attachment_media_id": attachment_id,
        },
        blocks=(ContentBlock("rich_text", "正文", "<p>已审核资源正文。</p>"),),
    )
    announcement = ContentDraft(
        entry_type="announcement",
        slug="editorial-dynamic-announcement",
        title="当前有效的公开公告",
        summary="仅在已验证有效期内公开。",
        seo_title="当前有效的公开公告",
        seo_description="查看当前有效的平台公告。",
        extension={
            "valid_from": "2026-08-25 09:00:00",
            "valid_until": "2026-08-26 09:00:00",
            "cta_url": "https://example.com/editorial-notice",
        },
        blocks=(ContentBlock("rich_text", "公告正文", "<p>已审核公告正文。</p>"),),
    )
    for draft in (case, announcement):
        content_id = create_content_draft(draft, actor="test-admin", now=now)
        publish_content(content_id, 1, actor="test-admin", now=now)
    resource_id = create_content_draft(resource, actor="test-admin", now=now)
    db.execute(
        "UPDATE resource_content SET source_check_code='https_ok',"
        "source_checked_at='2026-08-25 10:00:00',"
        "source_check_expires_at='2099-01-01 00:00:00',"
        "source_check_url_sha256=? WHERE content_item_id=?",
        (hashlib.sha256(resource_url.encode()).hexdigest(), resource_id),
    )
    db.commit()
    publish_content(resource_id, 1, actor="test-admin", now=now)

    return {
        "case": "/cases/editorial-evidence-case",
        "resource": "/resources/editorial-review-dossier",
        "announcement": "/announcements/editorial-dynamic-announcement",
        "about": "/about",
        "assessment": "/assessment",
        "error": "/missing-editorial-page",
    }


def _css_custom_color(css, name):
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9a-f]{{6}})", css.lower())
    assert match is not None, name
    return match.group(1)


def _css_rule(css, selector):
    match = re.search(
        rf"(?m)^{re.escape(selector)}\s*\{{(?P<declarations>[^}}]*)\}}",
        css,
        re.DOTALL,
    )
    assert match is not None, selector
    return match.group("declarations")


def _css_member_rule(css, selector):
    """Read one selector from a top-level grouped CSS rule without matching text blindly."""
    for match in re.finditer(
        r"(?ms)^(?P<selectors>[^{}]+)\{(?P<declarations>[^{}]*)\}", css
    ):
        selectors = [item.strip() for item in match.group("selectors").split(",")]
        if selector in selectors:
            return match.group("declarations")
    raise AssertionError(selector)


def _css_token_color(tokens, declaration_value):
    match = re.fullmatch(r"var\((--ui-[a-z0-9-]+)\)", declaration_value)
    assert match is not None, declaration_value
    return _css_custom_color(tokens, match.group(1))


def _css_blocks(css, opener):
    """Return balanced CSS blocks for an at-rule without treating nested rules as text."""
    blocks = []
    search_from = 0
    while True:
        start = css.find(opener, search_from)
        if start == -1:
            return blocks
        brace_start = css.find("{", start)
        assert brace_start != -1, opener
        depth = 0
        for index in range(brace_start, len(css)):
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(css[brace_start + 1 : index])
                    search_from = index + 1
                    break
        else:
            raise AssertionError(f"unterminated CSS block: {opener}")


def _css_rule_in_blocks(blocks, selector):
    """Find one direct selector rule inside the parsed at-rule blocks."""
    for block in blocks:
        match = re.search(
            rf"(?m)^\s*{re.escape(selector)}\s*\{{(?P<declarations>[^}}]*)\}}",
            block,
            re.DOTALL,
        )
        if match is not None:
            return match.group("declarations")
    raise AssertionError(selector)


def _css_declarations(declarations):
    return {
        name.strip(): value.strip()
        for declaration in declarations.split(";")
        if ":" in declaration
        for name, value in (declaration.split(":", 1),)
    }


def _css_specificity(selector):
    """Return the CSS specificity tuple needed by the public layout contracts."""
    without_not = selector.replace(":not(", "(")
    ids = len(re.findall(r"#[a-zA-Z0-9_-]+", without_not))
    class_like = len(re.findall(r"\.[a-zA-Z0-9_-]+|\[[^\]]+\]", without_not))
    class_like += len(re.findall(r":(?!:)[a-zA-Z0-9_-]+", without_not))
    elements = len(
        re.findall(r"(?:^|[\s>+~(])([a-zA-Z][a-zA-Z0-9_-]*)", without_not)
    )
    return ids, class_like, elements


def _contrast_ratio(foreground, background):
    def luminance(color):
        channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        channels = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize(
    "path",
    ("/", "/industries", "/scenarios", "/service-packages", "/cases", "/resources", "/about", "/assessment"),
)
def test_public_shell_uses_one_silver_evidence_navigation_layer(client, path):
    page = _page(client.get(path))
    hrefs = [link["href"] for link in page.select('link[rel="stylesheet"]')]
    public_pages_index = hrefs.index("/static/css/public-pages.css")

    assert hrefs[public_pages_index + 1] == "/static/css/silver-evidence-public.css"
    assert len(page.select("header > nav[data-public-navigation='silver-evidence']")) == 1
    assert not page.select(".site-signal")
    assert page.select_one("nav[data-public-navigation='silver-evidence']").get(
        "data-navigation-tone"
    ) == "dark"
    assert len(page.select("main#main-content[aria-label='主要内容']")) == 1

    footer = page.select_one("footer.footer")
    assert footer is not None
    assert not footer.select("[style]")
    assert [heading.get_text(" ", strip=True) for heading in footer.select("h2")] == [
        "企业AI转型平台",
        "服务方案",
        "资源中心",
        "关于",
    ]


def test_scale_inspired_tokens_and_story_layer_are_local(client):
    """The selected local story layer keeps the industrial tokens and safety regimes."""
    tokens = client.get("/static/css/design-tokens.css").get_data(as_text=True).lower()
    story_css = client.get("/static/css/dark-evidence-home.css").get_data(as_text=True)
    page = _page(client.get("/"))

    for token in (
        "--ui-graphite-1000: #06080b",
        "--ui-graphite-950: #0b1016",
        "--ui-graphite-850: #18202a",
        "--ui-paper-050: #f3f1eb",
        "--ui-paper-000: #fbfaf7",
        "--ui-ink-950: #111827",
        "--ui-ink-650: #556070",
        "--ui-silver-200: #d8dee6",
        "--ui-signal-blue: #0f6fef",
        '--ui-font-sans: "noto sans sc", "source han sans sc", "microsoft yahei ui", "microsoft yahei", sans-serif',
        "--ui-font-label: inter, arial, sans-serif",
        "--ui-container-wide: 85rem",
    ):
        assert token in tokens

    assert page.select_one('link[href="/static/css/dark-evidence-home.css"]') is not None
    assert "@media (min-width: 1100px)" in story_css
    assert "@media (min-width: 768px) and (max-width: 1099px)" in story_css
    assert "@media (max-width: 767px)" in story_css
    assert "@media (prefers-reduced-motion: reduce)" in story_css
    mobile_story_css = story_css.split("@media (max-width: 767px)", 1)[1]
    assert ".home-dark-evidence .story-product--overview" in mobile_story_css
    assert "position: static" in mobile_story_css


def test_hero_secondary_action_keeps_a_visible_outline_label(client):
    """The hero's secondary path must override the public paper-fill button."""
    css = client.get("/static/css/guided-story.css").get_data(as_text=True)
    hero_outline = _css_rule(css, ".story-chapter--hero .btn-outline")

    assert "background: transparent" in hero_outline
    assert "color: var(--ui-paper-050)" in hero_outline


def test_home_has_skip_link_and_single_named_main(client):
    page = _page(client.get("/"))
    assert page.select_one('a.skip-link[href="#main-content"]') is not None
    mains = page.select("main#main-content")
    assert len(mains) == 1


@pytest.mark.parametrize("path", ("/", "/about", "/industries"))
def test_skip_link_targets_a_unique_focusable_main_on_public_pages(client, path):
    page = _page(client.get(path))
    target = page.select("main#main-content")
    assert len(target) == 1
    assert target[0].get("tabindex") == "-1"


def test_shared_focus_rules_make_the_skip_link_and_focus_visible(client):
    response = client.get("/static/css/ui-components.css")
    css = response.get_data(as_text=True)

    assert response.status_code == 200
    assert ".skip-link:focus" in css
    assert "transform: translateY(0)" in css
    assert ":focus-visible" in css
    assert "outline: 3px solid var(--ui-focus)" in css
    assert "outline-offset: 3px" in css
    assert "box-shadow: none" in css

    tokens = client.get("/static/css/design-tokens.css").get_data(as_text=True)
    focus = _css_custom_color(tokens, "--ui-focus")
    graphite = _css_custom_color(tokens, "--ui-graphite-1000")
    assert _contrast_ratio(focus, "#ffffff") >= 3
    assert _contrast_ratio(focus, graphite) >= 3


def test_design_tokens_are_served_with_approved_values(client):
    response = client.get("/static/css/design-tokens.css")
    css = response.get_data(as_text=True)
    assert response.status_code == 200
    for token in (
        "--ui-ink-950: #111827",
        "--ui-ink-650: #556070",
        "--ui-line-200: #dde4ee",
        "--ui-graphite-1000: #06080b",
        "--ui-graphite-950: #0b1016",
        "--ui-graphite-850: #18202a",
        "--ui-paper-050: #f3f1eb",
        "--ui-paper-000: #fbfaf7",
        "--ui-silver-200: #d8dee6",
        "--ui-signal-blue: #0f6fef",
        '--ui-font-sans: "noto sans sc", "source han sans sc", "microsoft yahei ui", "microsoft yahei", sans-serif',
        "--ui-font-label: inter, arial, sans-serif",
        "--ui-container-wide: 85rem",
    ):
        assert token in css.lower()
    assert "prefers-reduced-motion: reduce" in css


def test_legacy_brand_tokens_converge_on_single_signal_blue(client):
    """Compatibility aliases must not preserve a second public accent palette."""
    css = client.get("/static/css/design-tokens.css").get_data(as_text=True).lower()

    for deprecated_color in (
        "#5bd9e8",
        "#061b46",
        "#0f5fef",
        "#0b49bf",
        "#007c91",
        "#9a5b00",
    ):
        assert deprecated_color not in css

    for alias in (
        "--ui-signal-cyan",
        "--ui-blue-600",
        "--ui-blue-700",
        "--ui-teal-700",
        "--ui-amber-700",
    ):
        assert f"{alias}: var(--ui-signal-blue)" in css

    assert "--ui-navy-950: var(--ui-graphite-1000)" in css
    assert "--ui-focus: #0f6fef" in css


def test_shared_shell_keeps_truthful_assessment_copy_without_a_signal_bar(client):
    """The former second header row must not return as a standalone signal bar."""
    page = _page(client.get("/about"))
    navigation = page.select_one("nav[data-public-navigation='silver-evidence']")

    assert navigation is not None
    assert not page.select("[data-site-signal]")
    assert navigation.select_one('[href="/assessment"]') is not None


def test_story_product_heading_gets_panel_row_treatment(client):
    """The assessment heading must not bypass the product panel's padded, ruled rows."""
    css = client.get("/static/css/guided-story.css").get_data(as_text=True)
    heading = _css_rule(css, ".story-product > h3")

    assert "margin: 0;" in heading
    assert "padding: clamp(1rem, 2.5vw, 2rem);" in heading
    assert "border-bottom: 1px solid var(--ui-line-light);" in heading


def test_public_buttons_and_story_tokens_use_industrial_contract(client):
    """Public actions must use signal states while story motion and radii stay in scope."""
    public_css = client.get("/static/css/public-pages.css").get_data(as_text=True)
    token_css = client.get("/static/css/design-tokens.css").get_data(as_text=True)
    primary = _css_rule(public_css, ".public-page .btn-primary")
    primary_hover = _css_rule(public_css, ".public-page .btn-primary:hover")
    primary_focus = _css_rule(public_css, ".public-page .btn-primary:focus-visible")
    outline = _css_rule(public_css, ".public-page .btn-outline")
    outline_hover = _css_rule(public_css, ".public-page .btn-outline:hover")
    outline_focus = _css_rule(public_css, ".public-page .btn-outline:focus-visible")

    assert "background: var(--ui-signal-blue);" in primary
    assert "color: var(--ui-surface-000);" in primary
    assert "border-color: var(--ui-signal-blue);" in outline
    assert "color: var(--ui-graphite-950);" in outline
    assert "background: var(--ui-paper-050);" in outline
    for state in (primary_hover, primary_focus, outline_hover, outline_focus):
        assert re.search(
            r"background:\s*var\(--ui-signal-(?:blue|cyan)\);",
            state,
        )
    assert "--ui-motion-story: 680ms;" in token_css

    for token in ("--ui-radius-control", "--ui-radius-panel"):
        radius = re.search(rf"{re.escape(token)}:\s*([0-9.]+)rem", token_css)
        assert radius is not None, token
        assert 0 <= float(radius.group(1)) * 16 <= 8


def test_shared_shell_uses_real_brand_and_truthful_conversion_copy(client):
    page = _page(client.get("/"))
    logo = page.select_one('.nav-logo img[src="/static/logo.png"]')
    assert logo is not None
    assert logo.get("alt") == ""
    assert page.select_one('.nav-logo[aria-label="企业 AI 转型平台首页"]') is not None
    assert page.select_one(".nav-brand-text").get_text(" ", strip=True) == "企业 AI转型 平台"
    assert page.select_one('[data-primary-cta][href="/assessment"]') is not None
    sticky = page.select_one("#stickyCta")
    assert sticky is not None
    text = sticky.get_text(" ", strip=True)
    assert "完成 AI 就绪度评估" in text
    assert "5 分钟" not in text
    assert "🚀" not in text


def test_footer_has_no_inline_layout_styles(client):
    page = _page(client.get("/"))
    footer = page.select_one("footer.footer")
    assert footer is not None
    assert not footer.select("[style]")


@pytest.mark.parametrize(
    "path",
    ("/industries/manufacturing", "/scenarios/mfg-knowledge-assistant"),
)
def test_decision_cta_accessible_name_matches_its_visible_label(client, db, path):
    """The terminal assessment action keeps its visible accessible name."""
    db.execute(
        "UPDATE content_items SET status='published', published_at='2026-08-24 10:00:00' "
        "WHERE entry_type IN ('industry', 'scenario') AND status='draft'"
    )
    db.commit()
    page = _page(client.get(path))
    cta = page.select_one('[data-decision-primary-action][href="/assessment"]')

    assert cta is not None
    assert cta.get_text(" ", strip=True) == "获取适配建议"
    assert cta.get("aria-label") in (None, "获取适配建议")


def test_decision_chapter_link_color_rules_do_not_override_primary_ctas(client, db):
    """A later chapter-link rule must not turn a signal-blue CTA's text blue."""
    db.execute(
        "UPDATE content_items SET status='published', published_at='2026-08-24 10:00:00' "
        "WHERE entry_type IN ('industry', 'scenario') AND status='draft'"
    )
    db.commit()
    page = _page(client.get("/industries/manufacturing"))
    cta = page.select_one(
        '.decision-detail [data-decision-chapter] a.btn-primary[data-decision-primary-action]'
    )
    public_css = client.get("/static/css/public-pages.css").get_data(as_text=True)
    silver_css = client.get("/static/css/silver-evidence-public.css").get_data(
        as_text=True
    )
    ordinary_selector = ".decision-detail [data-decision-chapter] a:not(.btn)"
    inverse_selector = (
        ".decision-detail [data-decision-chapter]:nth-child(even) a:not(.btn)"
    )

    assert cta is not None
    assert cta not in page.select(ordinary_selector)
    assert cta not in page.select(inverse_selector)
    assert _css_declarations(_css_rule(silver_css, ordinary_selector))["color"] == (
        "var(--ui-signal-blue)"
    )
    assert _css_declarations(_css_rule(silver_css, inverse_selector))["color"] == (
        "var(--ui-paper-000)"
    )
    for selector, expected_color in (
        (".public-page .btn-primary", "var(--ui-surface-000)"),
        (".public-page .btn-primary:hover", "var(--ui-graphite-950)"),
        (".public-page .btn-primary:focus-visible", "var(--ui-graphite-950)"),
    ):
        declarations = _css_declarations(_css_rule(public_css, selector))
        assert declarations["color"] == expected_color


def test_shared_navigation_and_footer_use_readable_text_colors(client):
    """The shared shell keeps readable text on its paper and graphite surfaces."""
    tokens = client.get("/static/css/design-tokens.css").get_data(as_text=True)
    css = client.get("/static/css/ui-components.css").get_data(as_text=True)
    ink = _css_custom_color(tokens, "--ui-ink-650")
    paper = _css_custom_color(tokens, "--ui-paper-050")
    graphite = _css_custom_color(tokens, "--ui-graphite-950")

    assert _contrast_ratio(ink, "#ffffff") >= 4.5
    assert _contrast_ratio(ink, "#f5f5f7") >= 4.5
    assert _contrast_ratio(paper, graphite) >= 4.5
    assert ".nav-links a { color: var(--ui-ink-650);" in css
    assert ".footer { color: var(--ui-paper-050); background: var(--ui-graphite-950); }" in css
    assert ".footer a,\n.footer-bottom { color: var(--ui-paper-050); }" in css


def test_task5_small_editorial_and_assessment_text_meets_aa_contrast(client):
    """Signal blue is an accent; small document text must keep a 4.5:1 foreground."""
    tokens = client.get("/static/css/design-tokens.css").get_data(as_text=True)
    editorial_css = client.get("/static/css/silver-evidence-public.css").get_data(
        as_text=True
    )
    assessment_css = client.get("/static/css/assessment.css").get_data(as_text=True)
    paper = _css_custom_color(tokens, "--ui-paper-050")
    graphite = _css_custom_color(tokens, "--ui-graphite-1000")

    examples = (
        (editorial_css, ".public-shell .review-dossier__meta a", paper),
        (editorial_css, ".public-shell .editorial-content-flow a", paper),
        (editorial_css, ".public-shell .review-dossier .public-eyebrow", paper),
        (editorial_css, ".public-shell .editorial-cover .public-eyebrow", graphite),
        (assessment_css, ".privacy-card a", paper),
        (assessment_css, ".assessment-eyebrow", graphite),
    )
    for css, selector, background in examples:
        declarations = _css_declarations(_css_member_rule(css, selector))
        foreground = _css_token_color(tokens, declarations["color"])
        assert _contrast_ratio(foreground, background) >= 4.5, selector


def test_shared_navigation_and_footer_links_keep_touch_targets_and_mobile_columns(client):
    """Shrinking shell links or keeping four mobile footer columns must fail this contract."""
    css = client.get("/static/css/ui-components.css").get_data(as_text=True)

    assert ".nav-links a," in css
    assert ".mobile-navigation-panel a," in css
    assert ".footer-inner a {" in css
    assert "min-height: 2.75rem;" in css
    assert ".nav-links a { min-inline-size: 2.75rem; }" in css
    assert ".footer-bottom a { min-height: 2.75rem; display: inline-flex; align-items: center; }" in css
    assert ".footer-inner { grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert ".footer-inner > :first-child { grid-column: 1 / -1; }" in css


def test_navigation_brand_text_overrides_the_legacy_span_color(client):
    response = client.get("/static/css/ui-components.css")
    css = response.get_data(as_text=True)

    assert response.status_code == 200
    assert ".nav-logo .nav-brand-text" in css
    assert "color: var(--ui-ink-950)" in css
    assert ".nav-brand-text strong { color: var(--ui-blue-600); }" in css


def test_decision_detail_css_stacks_the_split_cover_and_fact_strip_on_narrow_screens(client):
    """The 767px rules must beat the three-class desktop decision-detail selectors."""
    response = client.get("/static/css/silver-evidence-public.css")
    css = response.get_data(as_text=True)
    mobile_blocks = _css_blocks(css, "@media (max-width: 767px)")
    hero = _css_declarations(_css_rule_in_blocks(
        mobile_blocks, ".public-shell .decision-detail .detail-hero__grid"
    ))
    facts = _css_declarations(_css_rule_in_blocks(
        mobile_blocks, ".public-shell .decision-detail .detail-facts"
    ))
    fact_item = _css_declarations(_css_rule_in_blocks(
        mobile_blocks, ".public-shell .decision-detail .detail-facts > div"
    ))
    desktop_fact_item = _css_declarations(_css_rule(
        css, ".public-shell .decision-detail .detail-facts > div"
    ))
    desktop_fact_value = _css_declarations(_css_rule(
        css, ".public-shell .decision-detail .detail-facts dd"
    ))

    assert response.status_code == 200
    assert hero["grid-template-columns"] == "1fr"
    assert facts["grid-template-columns"] == "1fr"
    assert "!important" not in _css_rule_in_blocks(
        mobile_blocks, ".public-shell .decision-detail .detail-hero__grid"
    )
    assert "!important" not in _css_rule_in_blocks(
        mobile_blocks, ".public-shell .decision-detail .detail-facts"
    )
    assert fact_item["border-left"] == "0"
    assert desktop_fact_item["min-width"] == "0"
    assert desktop_fact_value["overflow-wrap"] == "anywhere"


@pytest.mark.parametrize("viewport_width", (390, 320))
def test_scenario_mobile_metadata_stays_in_the_body_column(client, db, viewport_width):
    """At supported phone widths, scenario metadata cannot occupy the 2.75rem index rail."""
    db.execute(
        "UPDATE content_items SET status='published', published_at='2026-08-24 10:00:00' "
        "WHERE entry_type='scenario' AND status='draft'"
    )
    db.commit()
    page = _page(client.get("/scenarios"))
    metadata = page.select_one(
        ".public-scenarios .scenario-signal-row .editorial-result-row__meta"
    )
    legacy_css = client.get("/static/css/public-pages.css").get_data(as_text=True)
    silver_css = client.get("/static/css/silver-evidence-public.css").get_data(
        as_text=True
    )
    legacy_selector = (
        ".public-scenarios .scenario-signal-row .catalog-card-meta"
    )
    corrected_selector = (
        ".public-shell .public-scenarios .scenario-signal-row "
        ".editorial-result-row__meta"
    )
    legacy_mobile = _css_declarations(
        _css_rule_in_blocks(
            _css_blocks(legacy_css, "@media (max-width: 767px)"), legacy_selector
        )
    )
    corrected_mobile = _css_declarations(
        _css_rule_in_blocks(
            _css_blocks(silver_css, "@media (max-width: 767px)"),
            corrected_selector,
        )
    )

    assert viewport_width <= 767
    assert metadata is not None
    assert metadata.name == "dl"
    assert metadata.select("div > dt + dd")
    assert legacy_mobile["grid-column"] == "auto"
    assert _css_specificity(corrected_selector) > _css_specificity(legacy_selector)
    assert corrected_mobile["grid-column"] == "2"
    assert corrected_mobile["min-width"] == "0"
    assert corrected_mobile["width"] == "auto"


def test_public_display_titles_balance_lines_and_widen_split_covers_at_large_viewports(client):
    """Catch single-character title lines and squeezed 1440px split-cover copy."""
    response = client.get("/static/css/silver-evidence-public.css")
    css = response.get_data(as_text=True)
    assessment_css = client.get("/static/css/assessment.css").get_data(as_text=True)

    assert response.status_code == 200
    for selector in (
        ".public-shell .public-page-header h1",
        ".public-shell .decision-detail .detail-hero h1",
        ".public-shell .editorial-cover h1,\n.public-shell .manifesto-cover h1",
    ):
        assert _css_declarations(_css_rule(css, selector))["text-wrap"] == "balance"
    assert _css_declarations(_css_rule(assessment_css, ".assessment-hero h1"))[
        "text-wrap"
    ] == "balance"

    large_blocks = _css_blocks(css, "@media (min-width: 1280px)")
    assert _css_declarations(_css_rule_in_blocks(
        large_blocks, ".public-shell .public-page-header--with-art"
    ))["grid-template-columns"] == "minmax(0, 1.1fr) minmax(18rem, 0.72fr)"
    for selector in (
        ".public-shell .decision-detail .detail-hero__grid",
        ".public-shell .editorial-cover__grid,\n  .public-shell .manifesto-cover__grid",
    ):
        assert _css_declarations(_css_rule_in_blocks(large_blocks, selector))[
            "grid-template-columns"
        ] == "minmax(0, 1.12fr) minmax(22rem, 0.88fr)"

    metric = _css_declarations(_css_rule_in_blocks(
        large_blocks,
        ".public-shell .evidence-metric-row .evidence-metric-row__values",
    ))
    assert metric["white-space"] == "nowrap"


def test_decision_detail_css_numbers_primary_chapters(client):
    """Dropping the chapter counter would remove the report-like decision hierarchy."""
    response = client.get("/static/css/silver-evidence-public.css")
    css = response.get_data(as_text=True)

    assert response.status_code == 200
    assert ".decision-document { counter-reset: decision-chapter; }" in css
    assert ".decision-detail [data-decision-chapter]" in css
    assert ".decision-chapter__sequence" in css
    assert "font-variant-numeric: tabular-nums;" in css


def test_mobile_sticky_cta_css_reserves_its_compact_fixed_row(client):
    """Catch a wrapping fixed CTA that can cover the mobile detail content below it."""
    response = client.get("/static/css/ui-components.css")
    css = response.get_data(as_text=True)

    assert response.status_code == 200
    assert ".sticky-cta { flex-wrap: nowrap; align-items: center; }" in css
    assert ".sticky-cta .cta-text { min-width: 0; flex: 1 1 auto; overflow-wrap: anywhere; }" in css
    assert ".sticky-cta .btn { flex: 0 0 auto; min-height: 2.75rem; }" in css
    assert "body.has-sticky-cta { padding-bottom: calc(4.5rem + env(safe-area-inset-bottom)); }" in css


@pytest.mark.parametrize(
    "path, page_class",
    (
        ("/industries", "public-industries"),
        ("/scenarios", "public-scenarios"),
        ("/service-packages", "public-services"),
        ("/cases", "public-cases"),
        ("/resources", "public-resources"),
    ),
)
def test_catalog_lists_share_semantic_page_structure(client, path, page_class):
    """Missing the shared list structure would make this catalog contract fail."""
    page = _page(client.get(path))
    main = page.select_one(f"main#main-content.{page_class}")

    assert main is not None
    assert len(main.select(":scope > .public-page-header h1")) == 1
    assert main.select_one(".catalog-grid") is not None


@pytest.mark.parametrize(
    "path, page_class",
    (
        ("/industries", "public-industries"),
        ("/scenarios", "public-scenarios"),
        ("/service-packages", "public-services"),
        ("/cases", "public-cases"),
        ("/resources", "public-resources"),
    ),
)
def test_silver_evidence_catalog_families_use_editorial_rows(client, path, page_class):
    """Every catalog keeps the shared editorial shell even when no items are public."""
    page = _page(client.get(path))
    main = page.select_one(f"main#main-content.{page_class}")

    assert main is not None
    assert main["data-page-family"] == "catalog"
    assert main.select_one('[data-catalog-layout="editorial"]') is not None
    assert main.select_one(".public-page-header__copy h1") is not None
    assert main.select_one('img[src^="/static/images/ui/"]') is not None
    assert not main.select("[style]")


def test_scenario_filters_keep_accessible_labels_and_selected_values(client):
    """Dropping a label, selected filter, or reset action would make filtering opaque."""
    page = _page(client.get("/scenarios?industry=manufacturing&maturity=pilot"))
    form = page.select_one('form.public-filter[aria-label="筛选场景"]')

    assert form is not None
    assert form.select_one('label[for="industry"]') is not None
    assert form.select_one('#industry[value="manufacturing"]') is not None
    assert form.select_one('#maturity option[selected][value="pilot"]') is not None
    assert form.select_one('a[href="/scenarios"]') is not None


@pytest.mark.parametrize("path", ("/", "/about"))
def test_static_public_pages_use_named_main_and_no_inline_layout(client, path):
    """Inline layout inside the shared main would bypass the responsive UI contract."""
    page = _page(client.get(path))

    assert page.select_one("main#main-content") is not None
    assert not page.select("main [style]")


@pytest.mark.parametrize(
    ("route_key", "family", "required_selector"),
    (
        ("case", "evidence-article", "[data-case-verification]"),
        (
            "resource",
            "review-dossier",
            "[data-resource-authorship]",
        ),
        ("announcement", "dynamic-article", "[data-announcement-validity]"),
        ("about", "manifesto", "[data-manifesto-chapter]"),
        ("assessment", "assessment-conversion", "#assessment-wizard"),
        ("error", "status-page", "[data-status-recovery]"),
    ),
)
def test_silver_evidence_editorial_and_conversion_families_keep_live_contracts(
    client, editorial_public_routes, route_key, family, required_selector
):
    """Editorial presentation may change hierarchy, never published data or wizard behavior."""
    response = client.get(editorial_public_routes[route_key])
    page = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    main = page.select_one("main#main-content")

    assert response.status_code == (404 if route_key == "error" else 200)
    assert main is not None
    assert main["data-page-family"] == family
    assert main.select_one(required_selector) is not None
    assert len(main.select("h1")) == 1
    assert not main.select("[style]")
    assert not any(
        asset.get("src", "").startswith(("http://", "https://"))
        for asset in page.select("img[src], script[src]")
    )
    assert not any(
        asset.get("href", "").startswith(("http://", "https://"))
        for asset in page.select('link[rel="stylesheet"][href]')
    )
    assert not any(symbol in page.get_text(" ", strip=True) for symbol in ("⚠", "🚀", "✨"))

    if route_key == "case":
        assert main.select_one("[data-verified-at]") is not None
        assert main.select_one("[data-case-metric]") is not None
        assert "internal-editorial-reference" not in main.get_text(" ", strip=True)
    elif route_key == "resource":
        source = main.select_one("[data-resource-source]")
        attachment = main.select_one("[data-resource-attachment]")
        assert source["href"] == "https://example.com/editorial-review"
        assert source["target"] == "_blank"
        assert source["rel"] == ["noopener", "noreferrer"]
        assert attachment["href"].startswith("/media/")
    elif route_key == "announcement":
        cta = main.select_one("[data-announcement-cta]")
        assert "2026-08-25 09:00:00 至 2026-08-26 09:00:00" in main.get_text(
            " ", strip=True
        )
        assert cta["target"] == "_blank"
        assert cta["rel"] == ["noopener", "noreferrer"]
    elif route_key == "about":
        assert len(main.select("[data-manifesto-chapter]")) == 4
    elif route_key == "assessment":
        wizard = main.select_one("#assessment-wizard")
        assert wizard["data-config-base"] == "/api/v2/assessment/config"
        assert wizard["data-preview-url"] == "/api/v2/assessment/preview"
        assert wizard["data-complete-url"] == "/api/v2/assessment/complete"
        assert {field.get("name") for field in main.select("form input[name]")} == {
            "company_name",
            "contact_name",
            "phone",
            "email",
            "wechat",
            "privacy_consent",
        }
        assert main.select_one("#assessment-progress") is not None
        assert main.select_one("#assessment-error[role='alert']") is not None
        assert main.select_one("#assessment-live-status[aria-live='polite']") is not None
    else:
        assert main.select_one("[data-status-recovery][href='/']") is not None


def test_home_preserves_real_content_sections_and_single_primary_action(client):
    """The home page must keep published collections without inventing a metric claim."""
    page = _page(client.get("/"))

    story = page.select_one("[data-guided-story]")
    assert story is not None
    assert len(story.select("h1")) == 1
    hero = story.select_one("#story-purpose")
    assert [link.get("href") for link in hero.select(".home-hero-actions a")] == [
        "/assessment"
    ]
    assert hero.select_one(
        ".home-hero-copy > p:not(.public-eyebrow):not(.home-audit-note)"
    ).get_text(" ", strip=True) == (
        "评估准备度，匹配高价值场景，形成可执行的实施路径。"
    )
    assert page.select_one('[data-home-section="applications"]') is not None
    assert page.select_one('[data-home-section="proof"]') is not None
    assert page.select_one('[data-home-section="news"]') is not None
    final_cta = page.select_one('[data-home-section="final-cta"]')
    assert final_cta.select_one("h2").get_text(" ", strip=True) == (
        "确认你的 AI 转型起点"
    )
    assert [
        (link.get_text(" ", strip=True), link.get("href"))
        for link in final_cta.select("a")
    ] == [("开始评估", "/assessment")]
    assert [chapter["id"] for chapter in story.select("[data-story-chapter]")] == [
        "story-purpose",
        "story-assessment",
        "story-matching",
        "story-roadmap",
        "story-evidence",
    ]
    assert not page.select("main [style]")
    assert not page.select("main video")
    assert not page.select(
        "main [data-customer-logo-wall], main .customer-logo-wall, main .logo-wall"
    )
    assert "27+" not in page.get_text(" ", strip=True)


def test_home_dark_evidence_css_keeps_one_signal_color(client):
    """The dark homepage keeps one signal color across its composition."""
    css = client.get("/static/css/dark-evidence-home.css").get_data(as_text=True)

    for secondary_blue in ("#5ca0ff", "#075fce", "#4d9cff", "#62a8ff"):
        assert secondary_blue not in css.lower()
    assert "color: var(--home-signal)" in _css_rule(
        css, ".home-dark-evidence .home-text-link"
    )
    assert "color: var(--home-signal)" in _css_rule(
        css,
        ".home-dark-evidence .home-application-links a:hover,\n"
        ".home-dark-evidence .home-application-links a:focus-visible",
    )
    focus_rule = _css_rule(
        css,
        ".home-dark-evidence a:focus-visible,\n"
        ".home-dark-evidence summary:focus-visible,\n"
        ".home-dark-evidence button:focus-visible,\n"
        ".home-dark-evidence input:focus-visible,\n"
        ".home-dark-evidence select:focus-visible,\n"
        ".home-dark-evidence textarea:focus-visible",
    )
    assert "outline: 3px solid var(--home-signal)" in focus_rule
    assert "outline-offset: 3px" in focus_rule


def test_home_navigation_and_conversion_surfaces_follow_dark_evidence_contract(client):
    """Only the homepage gets the dark shell and its duplicate fixed CTA is suppressed."""
    home = _page(client.get("/"))
    navigation = home.select_one("nav.nav.nav--home-dark[data-home-navigation]")

    assert navigation is not None
    assert navigation["data-home-navigation"] == "dark-evidence"
    assert [link.get("href") for link in navigation.select("a[href]")] == [
        "/",
        "/industries",
        "/scenarios",
        "/service-packages",
        "/cases",
        "/about",
        "/assessment",
        "/industries",
        "/scenarios",
        "/service-packages",
        "/cases",
        "/about",
        "/assessment",
    ]
    home_nav_cta = navigation.select_one('[data-primary-cta][href="/assessment"]')
    assert home_nav_cta is not None
    assert home_nav_cta.has_attr("hidden")
    assert not home.select("[data-site-signal]")
    assert [link.get("href") for link in home.select(".home-hero-actions a")] == [
        "/assessment"
    ]
    primary_actions = home.select('main a.btn-primary[href="/assessment"]')
    assert len(primary_actions) == 2
    assert primary_actions[0].find_parent(id="story-purpose") is not None
    assert primary_actions[1].find_parent(
        attrs={"data-home-section": "final-cta"}
    ) is not None

    about = _page(client.get("/about"))
    assert about.select_one("nav.nav.nav--home-dark") is None
    assert about.select_one("nav.nav[data-home-navigation]") is None
    assert not about.select("[data-site-signal]")
    about_nav_cta = about.select_one('nav [data-primary-cta][href="/assessment"]')
    assert about_nav_cta is not None
    assert not about_nav_cta.has_attr("hidden")


def test_home_responsive_shell_declares_three_safe_layout_regimes(client):
    """Static CSS must cover desktop, compact desktop, mobile, and reduced motion."""
    css = client.get("/static/css/dark-evidence-home.css").get_data(as_text=True)

    root_rule = _css_rule(css, ".home-dark-evidence")
    assert "min-width: 0" in root_rule
    assert "min-width: 20rem" not in root_rule

    hidden_conversion = _css_rule(
        css,
        ".home-dark-evidence .site-signal,\n.home-dark-evidence .sticky-cta",
    )
    assert "display: none" in hidden_conversion
    assert "@media (min-width: 1100px)" in css
    assert "@media (min-width: 768px) and (max-width: 1099px)" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    compact_css = css.split(
        "@media (min-width: 768px) and (max-width: 1099px)", 1
    )[1].split("@media (max-width: 767px)", 1)[0]
    compact_css = re.sub(r"(?m)^  ", "", compact_css)
    compact_story = _css_rule(
        compact_css, ".home-dark-evidence .guided-story"
    )
    assert "padding-inline-end: 2.75rem" in compact_story
    compact_hero_title = _css_rule(
        compact_css, ".home-dark-evidence .home-hero-copy h1"
    )
    assert "font-size: clamp(3.25rem, 6vw, 4rem)" in compact_hero_title
    mobile_css = css.split("@media (max-width: 767px)", 1)[1].split(
        "@media (prefers-reduced-motion: reduce)", 1
    )[0]
    mobile_css = re.sub(r"(?m)^  ", "", mobile_css)
    mobile_progress = _css_rule(
        mobile_css, ".home-dark-evidence .guided-story-progress"
    )
    mobile_step = _css_rule(
        mobile_css, ".home-dark-evidence .guided-story-progress a"
    )
    assert "overflow-x: auto" in mobile_progress
    assert "scrollbar-width: none" in mobile_progress
    assert "flex: 0 0 auto" in mobile_step
    assert "min-width: 2.75rem" in mobile_step
    assert "min-height: 2.75rem" in mobile_step
    mobile_scrollbar = _css_rule(
        mobile_css,
        ".home-dark-evidence .guided-story-progress::-webkit-scrollbar",
    )
    assert "display: none" in mobile_scrollbar
    assert "transform: scale(1.02)" in css
    assert "[data-story-mode=\"enhanced\"]" in css


def test_home_dark_evidence_assets_are_local_decodable_and_bounded(client):
    """The selected homepage art must stay local, lightweight, and correctly prioritized."""
    page = _page(client.get("/"))

    assert page.body.get("class") and "home-dark-evidence" in page.body["class"]
    assert page.select_one('link[href="/static/css/dark-evidence-home.css"]') is not None
    expected = {
        "/static/images/ui/home-ai-core-silver.webp": (1920, 1080, 350_000),
        "/static/images/ui/home-knowledge-system.webp": (1600, 900, 300_000),
        "/static/images/ui/home-path-system.webp": (1600, 900, 300_000),
    }
    root = Path(__file__).resolve().parents[1]

    assert len(page.select("img[data-home-art]")) == len(expected)
    for url, (width, height, byte_limit) in expected.items():
        matches = page.select(f'img[data-home-art][src="{url}"]')
        assert len(matches) == 1
        image = matches[0]
        assert image.get("alt") == ""
        assert (image.get("width"), image.get("height")) == (str(width), str(height))

        asset = root / "static" / url.removeprefix("/static/")
        assert asset.exists()
        assert 0 < asset.stat().st_size <= byte_limit
        with Image.open(asset) as bitmap:
            assert bitmap.format == "WEBP"
            assert bitmap.size == (width, height)
            assert not getattr(bitmap, "is_animated", False)
            assert getattr(bitmap, "n_frames", 1) == 1
            bitmap.verify()
        with Image.open(asset) as bitmap:
            bitmap.load()

    hero = page.select_one(
        'img[data-home-art][src="/static/images/ui/home-ai-core-silver.webp"]'
    )
    assert hero.get("fetchpriority") == "high"
    assert hero.get("loading") != "lazy"

    for url in (
        "/static/images/ui/home-knowledge-system.webp",
        "/static/images/ui/home-path-system.webp",
    ):
        supporting = page.select_one(f'img[data-home-art][src="{url}"]')
        assert supporting.get("loading") == "lazy"
        assert supporting.get("decoding") == "async"


def test_silver_evidence_assets_are_local_decodable_and_bound_to_public_surfaces(client):
    """Silver-evidence art stays local, truthful, decodable, and visibly lit."""
    page = _page(client.get("/"))
    hero = page.select_one(
        'img[data-home-art][src="/static/images/ui/home-ai-core-silver.webp"]'
    )

    assert hero is not None
    assert hero.get("alt") == ""
    assert (hero.get("width"), hero.get("height")) == ("1920", "1080")
    assert hero.get("fetchpriority") == "high"

    expected = {
        "home-ai-core-silver.webp": (1920, 1080, 350_000),
        "public-industry-operations.webp": (1920, 1080, 400_000),
        "public-delivery-system.webp": (1600, 900, 340_000),
        "public-trust-evidence.webp": (1600, 900, 340_000),
    }
    root = Path(__file__).resolve().parents[1] / "static" / "images" / "ui"

    for filename, (width, height, byte_limit) in expected.items():
        asset = root / filename
        assert asset.exists(), filename
        assert 0 < asset.stat().st_size <= byte_limit
        with Image.open(asset) as bitmap:
            assert bitmap.format == "WEBP"
            assert bitmap.mode == "RGB"
            assert bitmap.size == (width, height)
            assert not getattr(bitmap, "is_animated", False)
            assert getattr(bitmap, "n_frames", 1) == 1
            bitmap.verify()
        with Image.open(asset) as bitmap:
            bitmap.load()

    css = client.get("/static/css/dark-evidence-home.css").get_data(as_text=True)
    assert "invert(" not in css.lower()
    assert "hue-rotate(" not in css.lower()
    hero_rule = _css_rule(css, ".home-dark-evidence .home-art--hero img")
    brightness = re.search(r"brightness\(\s*([0-9]*\.?[0-9]+)\s*\)", hero_rule)
    assert brightness is not None
    assert float(brightness.group(1)) >= 0.9


def _assert_home_technology_assets_contract(page):
    images = page.select("img[data-technology-art]")

    assert [image["src"] for image in images] == [
        "/static/images/ui/industrial-data-infrastructure.webp",
        "/static/images/ui/enterprise-compute-space.webp",
    ]
    root = Path(__file__).resolve().parents[1]
    expected_assets = (
        (
            '#story-roadmap [data-product-surface="roadmap"]',
            "/static/images/ui/industrial-data-infrastructure.webp",
            (1600, 1000),
        ),
        (
            '#story-roadmap [data-product-surface="evidence"]',
            "/static/images/ui/enterprise-compute-space.webp",
            (1600, 900),
        ),
    )
    for surface_selector, expected_src, expected_size in expected_assets:
        wrappers = page.select(f"{surface_selector} .story-technology-art")
        assert len(wrappers) == 1
        wrapper = wrappers[0]
        assert wrapper.get("aria-hidden") == "true"
        image = wrapper.select_one("img[data-technology-art]")
        assert image is not None
        assert image.get("src") == expected_src
        assert image.get("alt") == ""
        assert image.get("loading") == "lazy", "missing loading=lazy"
        assert image.get("decoding") == "async", "missing decoding=async"
        assert (image.get("width"), image.get("height")) == tuple(
            str(dimension) for dimension in expected_size
        )
        asset = root / "static" / image["src"].removeprefix("/static/")
        assert asset.exists()
        assert 0 < asset.stat().st_size <= 350_000
        with Image.open(asset) as bitmap:
            assert bitmap.format == "WEBP"
            assert bitmap.size == expected_size
            assert not getattr(bitmap, "is_animated", False)
            assert getattr(bitmap, "n_frames", 1) == 1
            bitmap.verify()
        with Image.open(asset) as bitmap:
            bitmap.load()


def test_home_technology_assets_are_local_decorative_and_bounded(client):
    """Decorative technology art must remain local, correctly placed, and fully decodable."""
    _assert_home_technology_assets_contract(_page(client.get("/")))


def test_home_technology_asset_contract_rejects_in_memory_jinja_mutation(client, monkeypatch):
    """A missing lazy-load attribute in a temporary template must fail the real asset contract."""
    app = client.application
    loader = app.jinja_env.loader
    source, _, _ = loader.get_source(app.jinja_env, "index.html")
    technology_image = (
        'src="/static/images/ui/industrial-data-infrastructure.webp" alt="" '
        'width="1600" height="1000" loading="lazy" decoding="async"'
    )
    mutated_source = source.replace(
        technology_image,
        technology_image.replace(' loading="lazy"', ""),
        1,
    )

    assert mutated_source != source
    monkeypatch.setattr(
        app.jinja_env,
        "loader",
        ChoiceLoader((DictLoader({"index.html": mutated_source}), loader)),
    )
    app.jinja_env.cache.clear()
    try:
        with pytest.raises(AssertionError, match="missing loading=lazy"):
            _assert_home_technology_assets_contract(_page(client.get("/")))
    finally:
        app.jinja_env.cache.clear()


def test_guided_story_runtime_is_local_and_does_not_intercept_native_scrolling(client):
    """Story guidance may observe chapters, but must not take over browser scrolling."""
    page = _page(client.get("/"))
    response = client.get("/static/js/guided_story.js")
    source = response.get_data(as_text=True)

    assert page.select_one('script[src="/static/js/guided_story.js"][defer]') is not None
    assert response.status_code == 200
    assert "IntersectionObserver" in source
    assert re.search(r"addEventListener\(['\"]wheel", source) is None
    assert re.search(r"wheel[\s\S]{0,200}preventDefault", source) is None
