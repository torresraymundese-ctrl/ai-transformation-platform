"""Shared administrator shell and operations-dashboard UI contracts."""

from bs4 import BeautifulSoup


ADMIN_DESTINATIONS = (
    "/admin",
    "/admin/catalog/industry",
    "/admin/catalog/scenario",
    "/admin/catalog/service",
    "/admin/resources",
    "/admin/ingestion",
    "/admin/legal",
    "/admin/cases",
    "/admin/announcements",
    "/admin/assessments",
    "/admin/rules",
    "/admin/leads",
    "/admin/appointments",
    "/admin/data-requests",
    "/admin/assets",
    "/admin/media",
)


def _page(response):
    assert response.status_code == 200
    return BeautifulSoup(response.data, "html.parser")


def test_admin_shell_has_one_focusable_named_main_and_local_styles(admin_client):
    """Removing the shared landmark, skip target, or isolated CSS must fail."""
    page = _page(admin_client.get("/admin"))

    assert len(page.select("main")) == 1
    assert page.select_one('a.skip-link[href="#admin-main"]') is not None
    assert page.select_one(
        'main.admin-main#admin-main[tabindex="-1"][aria-label="后台主要内容"]'
    ) is not None
    assert page.select_one(".admin-layout") is not None
    assert page.select_one('link[href="/static/css/design-tokens.css"]') is not None
    assert page.select_one('link[href="/static/css/admin.css"]') is not None
    assert page.select_one("head > style") is None


def test_admin_stylesheet_is_not_loaded_by_the_public_shell(client):
    """Admin presentation must remain isolated from public routes."""
    page = _page(client.get("/"))

    assert page.select_one('link[href="/static/css/admin.css"]') is None


def test_login_uses_the_shared_main_without_management_navigation(client):
    """The public login must not expose a second main or admin destinations."""
    page = _page(client.get("/admin/login"))

    assert len(page.select("main#admin-main")) == 1
    assert page.select_one("main main") is None
    assert page.select_one("body.admin-login") is not None
    assert page.select_one("nav.admin-nav") is None
    assert page.select_one('a.login-brand[href="/"]') is not None
    assert page.select_one('a.login-return[href="/"]') is not None
    form = page.select_one('form[method="POST"][action="/admin/login"]')
    assert form is not None
    assert form.select_one('input[name="csrf_token"][type="hidden"]') is not None
    assert form.select_one('input[name="username"][autocomplete="username"]') is not None
    assert (
        form.select_one('input[name="password"][autocomplete="current-password"]')
        is not None
    )


def test_admin_navigation_preserves_groups_destinations_and_secure_logout(
    admin_client,
):
    """Dropping a destination, group label, or POST/CSRF logout must fail."""
    page = _page(admin_client.get("/admin"))
    navigation = page.select_one('nav.admin-nav[aria-label="后台主导航"]')

    assert navigation is not None
    assert [
        heading.get_text(" ", strip=True)
        for heading in navigation.select(".admin-nav__group > h2")
    ] == ["运营", "内容", "治理", "资产"]
    destinations = {link.get("href") for link in navigation.select("a[href]")}
    assert set(ADMIN_DESTINATIONS) <= destinations
    assert "/" in destinations
    current = navigation.select('a[aria-current="page"]')
    assert len(current) == 1
    assert current[0]["href"] == "/admin"

    logout = navigation.select_one('form[method="POST"][action="/admin/logout"]')
    assert logout is not None
    csrf = logout.select_one('input[name="csrf_token"][type="hidden"]')
    assert csrf is not None
    assert csrf.get("value")


def test_dashboard_cards_keep_real_counts_and_links_without_visible_queue_codes(
    admin_client,
):
    """Cards must retain data contracts while hiding implementation codes."""
    page = _page(admin_client.get("/admin"))
    cards = page.select("[data-operation-card]")

    assert cards
    for card in cards:
        queue = card["data-queue"]
        count = int(card["data-count"])
        assert queue not in card.get_text(" ", strip=True)
        assert int(card.select_one("[data-operation-count]").get_text(strip=True)) == count
        detail = _page(admin_client.get(f"/admin?queue={queue}"))
        assert int(detail.select_one("[data-total]")["data-total"]) == count
        assert card.select_one(f'a[href="/admin?queue={queue}"]') is not None


def test_operations_pagination_exposes_current_choice_without_losing_query_state(
    admin_client,
):
    """Pagination styling must not replace its server-owned query contract."""
    page = _page(admin_client.get("/admin?queue=new_leads&per_page=20"))
    navigation = page.select_one(
        'nav.operations-pagination.admin-actions[aria-label="运营队列分页"]'
    )

    assert navigation is not None
    current = navigation.select_one('a[aria-current="true"]')
    assert current is not None
    assert current.get_text(" ", strip=True) == "20 条"
    assert "queue=new_leads" in current["href"]


def test_admin_css_keeps_shared_responsive_and_accessibility_contracts(client):
    """Regressions in the required shell, aliases, input sizing, and focus fail."""
    response = client.get("/static/css/admin.css")

    assert response.status_code == 200
    css = response.get_data(as_text=True)
    for selector in (
        ".admin-layout",
        ".admin-main",
        ".admin-nav",
        ".admin-actions",
        ".admin-editor-section",
        ".admin-table-wrap",
        ".admin-error-summary",
        ".card",
        ".btn",
        ".form-group",
        ".admin-grid",
        ".inline-form",
        ".tag",
        ".flash",
    ):
        assert selector in css
    assert "grid-template-columns: 15rem minmax(0, 1fr)" in css
    assert "@media (max-width: 1023px)" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
    assert ".admin-login .admin-layout" in css
    assert "min-height: 44px" in css
    assert "outline: 3px solid var(--ui-focus)" in css
    assert ':not([type="checkbox"]):not([type="radio"])' in css
    assert "overflow-x: auto" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "var(--ui-" in css
