from bs4 import BeautifulSoup
import pytest
import re


def _page(response):
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


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


def test_public_shell_loads_design_layers_after_legacy_css(client):
    page = _page(client.get("/"))
    hrefs = [link["href"] for link in page.select('link[rel="stylesheet"]')]
    assert hrefs[-5:] == [
        "/static/css/app.css",
        "/static/css/design-tokens.css",
        "/static/css/ui-components.css",
        "/static/css/public-pages.css",
        "/static/css/guided-story.css",
    ]


def test_scale_inspired_tokens_and_story_layer_are_local(client):
    """The local public shell needs the industrial story layer and its responsive safety rules."""
    tokens = client.get("/static/css/design-tokens.css").get_data(as_text=True).lower()
    story_css = client.get("/static/css/guided-story.css").get_data(as_text=True)
    page = _page(client.get("/"))

    for token in (
        "--ui-graphite-1000: #07090d",
        "--ui-graphite-950: #0d1117",
        "--ui-paper-050: #f3f1eb",
        "--ui-signal-blue: #0f6fef",
        "--ui-signal-cyan: #5bd9e8",
        "--ui-container-wide: 85rem",
    ):
        assert token in tokens

    assert page.select_one('link[href="/static/css/guided-story.css"]') is not None
    assert "position: sticky" in story_css
    assert "min-height: 100svh" in story_css
    assert "@media (max-width: 767px)" in story_css
    assert "@media (prefers-reduced-motion: reduce)" in story_css
    mobile_story_css = story_css.split("@media (max-width: 767px)", 1)[1]
    assert ".story-product { position: static; top: auto; }" in mobile_story_css


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
    assert _contrast_ratio(focus, "#ffffff") >= 3
    assert _contrast_ratio(focus, "#061b46") >= 3


def test_design_tokens_are_served_with_approved_values(client):
    response = client.get("/static/css/design-tokens.css")
    css = response.get_data(as_text=True)
    assert response.status_code == 200
    for token in (
        "--ui-navy-950: #061b46",
        "--ui-blue-600: #0f5fef",
        "--ui-blue-700: #0b49bf",
        "--ui-teal-700: #007c91",
        "--ui-amber-700: #9a5b00",
        "--ui-ink-950: #15213a",
        "--ui-ink-650: #536176",
        "--ui-line-200: #dde4ee",
        "--ui-graphite-1000: #07090d",
        "--ui-graphite-950: #0d1117",
        "--ui-paper-050: #f3f1eb",
        "--ui-signal-blue: #0f6fef",
        "--ui-signal-cyan: #5bd9e8",
        "--ui-container-wide: 85rem",
    ):
        assert token in css.lower()
    assert "prefers-reduced-motion: reduce" in css


def test_shared_shell_has_truthful_signal_bar(client):
    """The assessment route is visibly connected to the shared public shell."""
    page = _page(client.get("/"))
    signal = page.select_one("[data-site-signal]")

    assert signal is not None
    assert signal.get_text(" ", strip=True) == "从评估到实施，建立可验证的 AI 转型路径"
    assert signal.select_one('a[href="/assessment"]') is not None


def test_signal_bar_anchor_keeps_a_full_touch_target(client):
    """A line-height-only signal link would leave most of its 44px bar unclickable."""
    css = client.get("/static/css/ui-components.css").get_data(as_text=True)
    signal_anchor = _css_rule(css, ".site-signal a")

    assert "display: inline-flex;" in signal_anchor
    assert "min-height: 2.75rem;" in signal_anchor
    assert "align-items: center;" in signal_anchor


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
    assert "background: var(--ui-signal-cyan);" in primary_hover
    assert "background: var(--ui-signal-cyan);" in primary_focus
    assert "border-color: var(--ui-signal-blue);" in outline
    assert "color: var(--ui-graphite-950);" in outline
    assert "background: var(--ui-paper-050);" in outline
    assert "background: var(--ui-signal-cyan);" in outline_hover
    assert "background: var(--ui-signal-cyan);" in outline_focus
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
    """A replacement aria-label must not make the CTA name differ from its visible text."""
    db.execute(
        "UPDATE content_items SET status='published', published_at='2026-08-24 10:00:00' "
        "WHERE entry_type IN ('industry', 'scenario') AND status='draft'"
    )
    db.commit()
    page = _page(client.get(path))
    cta = page.select_one('.decision-summary a[href="/assessment"]')

    assert cta is not None
    assert cta.get_text(" ", strip=True) == "获取适配建议"
    assert cta.get("aria-label") in (None, "获取适配建议")


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


def test_decision_detail_css_keeps_the_summary_before_content_on_narrow_screens(client):
    """Catch a narrow decision layout that leaves the summary after the main content."""
    response = client.get("/static/css/public-pages.css")
    css = response.get_data(as_text=True)

    assert response.status_code == 200
    assert ".decision-layout { grid-template-columns: 1fr; }" in css
    assert ".decision-summary { position: static; grid-row: 1; }" in css
    assert ".decision-main { grid-row: 2; }" in css


def test_decision_detail_css_numbers_primary_chapters(client):
    """Dropping the chapter counter would remove the report-like decision hierarchy."""
    response = client.get("/static/css/public-pages.css")
    css = response.get_data(as_text=True)

    assert response.status_code == 200
    assert ".decision-main { counter-reset: decision-section; }" in css
    assert ".decision-section > h2::before" in css
    assert "counter-increment: decision-section;" in css
    assert "counter(decision-section, decimal-leading-zero)" in css


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


def test_home_preserves_real_content_sections_and_single_primary_action(client):
    """The home page must keep published collections without inventing a metric claim."""
    page = _page(client.get("/"))

    story = page.select_one("[data-guided-story]")
    assert story is not None
    assert len(story.select("h1")) == 1
    assert story.select_one('a[href="/assessment"]') is not None
    assert [chapter["id"] for chapter in story.select("[data-story-chapter]")] == [
        "story-purpose",
        "story-assessment",
        "story-matching",
        "story-roadmap",
        "story-evidence",
    ]
    assert "27+" not in page.get_text(" ", strip=True)
