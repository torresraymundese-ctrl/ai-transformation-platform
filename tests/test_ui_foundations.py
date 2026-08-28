from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader
from pathlib import Path
from PIL import Image
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
        "/static/css/dark-evidence-home.css",
    ]


def test_scale_inspired_tokens_and_story_layer_are_local(client):
    """The selected local story layer keeps the industrial tokens and safety regimes."""
    tokens = client.get("/static/css/design-tokens.css").get_data(as_text=True).lower()
    story_css = client.get("/static/css/dark-evidence-home.css").get_data(as_text=True)
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
    """Non-home routes remain visibly connected to the shared assessment shell."""
    page = _page(client.get("/about"))
    signal = page.select_one("[data-site-signal]")

    assert signal is not None
    assert signal.get("hidden") is None
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
    assert home.select_one("[data-site-signal]").has_attr("hidden")
    assert [link.get("href") for link in home.select(".home-hero-actions a")] == [
        "/assessment"
    ]
    assert len(home.select('main a.btn-primary[href="/assessment"]')) == 2
    assert home.select_one('[data-home-section="final-cta"] a[href="/assessment"]')

    about = _page(client.get("/about"))
    assert about.select_one("nav.nav.nav--home-dark") is None
    assert about.select_one("nav.nav[data-home-navigation]") is None
    assert not about.select_one("[data-site-signal]").has_attr("hidden")


def test_home_responsive_shell_declares_three_safe_layout_regimes(client):
    """Static CSS must cover desktop, compact desktop, mobile, and reduced motion."""
    css = client.get("/static/css/dark-evidence-home.css").get_data(as_text=True)

    hidden_conversion = _css_rule(
        css,
        ".home-dark-evidence .site-signal,\n.home-dark-evidence .sticky-cta",
    )
    assert "display: none" in hidden_conversion
    assert "@media (min-width: 1100px)" in css
    assert "@media (min-width: 768px) and (max-width: 1099px)" in css
    assert "@media (max-width: 767px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
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
    assert "min-width: 2.75rem" in mobile_step
    assert "min-height: 2.75rem" in mobile_step
    assert "transform: scale(1.02)" in css
    assert "[data-story-mode=\"enhanced\"]" in css


def test_home_dark_evidence_assets_are_local_decodable_and_bounded(client):
    """The selected homepage art must stay local, lightweight, and correctly prioritized."""
    page = _page(client.get("/"))

    assert page.body.get("class") and "home-dark-evidence" in page.body["class"]
    assert page.select_one('link[href="/static/css/dark-evidence-home.css"]') is not None
    expected = {
        "/static/images/ui/home-ai-core.webp": (1920, 1080, 350_000),
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

    hero = page.select_one('img[data-home-art][src="/static/images/ui/home-ai-core.webp"]')
    assert hero.get("fetchpriority") == "high"
    assert hero.get("loading") != "lazy"

    for url in (
        "/static/images/ui/home-knowledge-system.webp",
        "/static/images/ui/home-path-system.webp",
    ):
        supporting = page.select_one(f'img[data-home-art][src="{url}"]')
        assert supporting.get("loading") == "lazy"
        assert supporting.get("decoding") == "async"


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
            '#story-evidence [data-product-surface="evidence"]',
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
