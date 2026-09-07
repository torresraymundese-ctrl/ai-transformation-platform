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


def _admin_css(client):
    response = client.get("/static/css/admin.css")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _css_blocks(css):
    """Yield top-level selector/at-rule blocks without depending on CSS tooling."""
    cursor = 0
    while cursor < len(css):
        opening = css.find("{", cursor)
        if opening < 0:
            return
        depth = 1
        closing = opening + 1
        while closing < len(css) and depth:
            if css[closing] == "{":
                depth += 1
            elif css[closing] == "}":
                depth -= 1
            closing += 1
        assert depth == 0
        yield css[cursor:opening].strip(), css[opening + 1 : closing - 1]
        cursor = closing


def _css_declarations(css, selector, *, media=None):
    """Return declarations attached to one exact selector in one media context."""
    rules = list(_css_blocks(css))
    if media is not None:
        matching_media = [body for prelude, body in rules if prelude == f"@media {media}"]
        assert len(matching_media) == 1
        rules = list(_css_blocks(matching_media[0]))

    declarations = {}
    for prelude, body in rules:
        if prelude.startswith("@"):
            continue
        selectors = {item.strip() for item in prelude.split(",")}
        if selector not in selectors:
            continue
        for item in body.split(";"):
            name, separator, value = item.partition(":")
            if separator:
                declarations[name.strip().lower()] = value.strip().removesuffix(
                    "!important"
                ).strip()
    return declarations


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


def test_standalone_login_links_use_a_reusable_44px_target_rule(client):
    """Removing target sizing from either standalone login link must fail."""
    page = _page(client.get("/admin/login"))
    links = page.select("a.admin-control-link")

    assert {tuple(link.get("class", ())) for link in links} == {
        ("login-brand", "admin-control-link"),
        ("login-return", "admin-control-link"),
    }
    declarations = _css_declarations(_admin_css(client), ".admin-control-link")
    assert declarations["display"] == "inline-flex"
    assert declarations["min-height"] == "44px"
    assert declarations["align-items"] == "center"


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
    css = _admin_css(client)
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
        assert _css_declarations(css, selector)
    assert _css_declarations(css, ".admin-layout")["grid-template-columns"] == (
        "15rem minmax(0, 1fr)"
    )
    assert _css_declarations(
        css, ".admin-layout", media="(max-width: 1023px)"
    )["grid-template-columns"] == "minmax(0, 1fr)"
    assert _css_declarations(css, ".admin-login .admin-layout")[
        "grid-template-columns"
    ] == "minmax(0, 1fr)"
    for selector in (".admin-nav a", ".admin-nav button", ".btn"):
        assert _css_declarations(css, selector)["min-height"] == "44px"
    assert _css_declarations(css, ":focus-visible")["outline"] == (
        "3px solid var(--ui-focus)"
    )
    text_input = (
        'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])'
    )
    assert _css_declarations(css, text_input)["min-height"] == "44px"
    assert _css_declarations(css, 'input[type="checkbox"]')["width"] == "auto"
    assert _css_declarations(css, 'input[type="radio"]')["width"] == "auto"
    assert _css_declarations(css, ".admin-table-wrap")["overflow-x"] == "auto"
    assert _css_declarations(css, ".admin-main table")["overflow-x"] == "auto"
    assert _css_declarations(
        css, ".skip-link", media="(prefers-reduced-motion: reduce)"
    )["transition"] == "none"
    assert "var(--ui-" in _css_declarations(css, "body")["font-family"]


def test_populated_content_editor_controls_share_44px_touch_targets(
    admin_client, db
):
    """Unclassed editor actions and wrapped choices must remain usable touch targets."""
    scenario = db.execute(
        "SELECT scenario_id FROM content_groups "
        "WHERE entry_type='scenario' ORDER BY scenario_id LIMIT 1"
    ).fetchone()
    assert scenario is not None
    page = _page(admin_client.get(f"/admin/catalog/scenario/{scenario['scenario_id']}"))
    editor = page.select_one('form[data-content-editor]')
    assert editor is not None

    assert {
        button["data-block-action"]
        for button in editor.select(
            '[data-content-block] button[data-block-action]'
        )
    } == {"up", "down", "remove"}
    assert editor.select_one("button[data-add-block]") is not None
    maturity_labels = editor.select(
        'label:has(> input[type="checkbox"][name="maturity_codes"])'
    )
    assert len(maturity_labels) == 4

    css = _admin_css(admin_client)
    button_target = _css_declarations(
        css, 'form[data-content-editor] button[type="button"]'
    )
    assert button_target["min-width"] == "44px"
    assert button_target["min-height"] == "44px"
    for input_type in ("checkbox", "radio"):
        choice_target = _css_declarations(
            css, f'.admin-main label:has(> input[type="{input_type}"])'
        )
        assert choice_target["display"] == "inline-flex"
        assert choice_target["min-height"] == "44px"
        assert choice_target["align-items"] == "center"


def test_unauthenticated_admin_error_uses_single_column_shell(client):
    """A navigation-free admin error must not retain the desktop sidebar track."""
    client.application.config["ADMIN_PASSWORD_HASH"] = None

    response = client.get("/admin/login")
    assert response.status_code == 503
    page = BeautifulSoup(response.data, "html.parser")
    assert page.select_one("body.admin-navigation-free") is not None
    assert page.select_one("nav.admin-nav") is None
    assert len(page.select("main#admin-main")) == 1
    assert _css_declarations(
        _admin_css(client), ".admin-navigation-free .admin-layout"
    )["grid-template-columns"] == "minmax(0, 1fr)"


def test_oversized_admin_rich_content_images_are_intrinsically_contained(client):
    """A wide rich-content image must shrink without distorting its aspect ratio."""
    document = BeautifulSoup(
        '<main class="admin-main"><div data-rich-content>'
        '<img src="oversized.png" width="2400" height="1600" alt=""></div></main>',
        "html.parser",
    )
    assert document.select_one('.admin-main img[width="2400"]') is not None

    declarations = _css_declarations(_admin_css(client), ".admin-main img")
    assert declarations["max-width"] == "100%"
    assert declarations["height"] == "auto"


def test_print_admin_shell_removes_sidebar_track_and_expands_main(client):
    """Print media must not retain a hidden 240px navigation grid column."""
    css = _admin_css(client)

    layout = _css_declarations(css, ".admin-layout", media="print")
    navigation = _css_declarations(css, ".admin-nav", media="print")
    main = _css_declarations(css, ".admin-main", media="print")
    assert layout["grid-template-columns"] == "minmax(0, 1fr)"
    assert navigation["display"] == "none"
    assert main["grid-column"] == "1 / -1"
    assert main["width"] == "100%"
