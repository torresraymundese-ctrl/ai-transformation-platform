from bs4 import BeautifulSoup
import pytest


def _page(response):
    assert response.status_code == 200
    return BeautifulSoup(response.get_data(as_text=True), "html.parser")


def test_public_shell_loads_design_layers_after_legacy_css(client):
    page = _page(client.get("/"))
    hrefs = [link["href"] for link in page.select('link[rel="stylesheet"]')]
    assert hrefs[-4:] == [
        "/static/css/app.css",
        "/static/css/design-tokens.css",
        "/static/css/ui-components.css",
        "/static/css/public-pages.css",
    ]


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
    assert "box-shadow: var(--ui-focus)" in css


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
    ):
        assert token in css.lower()
    assert "prefers-reduced-motion: reduce" in css


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

    assert page.select_one(".home-hero h1") is not None
    assert page.select_one('.home-hero a[href="/assessment"]') is not None
    assert "27+" not in page.get_text(" ", strip=True)
