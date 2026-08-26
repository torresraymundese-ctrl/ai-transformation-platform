from bs4 import BeautifulSoup


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
