"""Public SEO and asset-loading contracts for shipped public pages."""

from datetime import datetime
import re
from urllib.parse import urljoin, urlsplit

import pytest
from bs4 import BeautifulSoup

from content_clock import SHANGHAI


NOW = datetime(2026, 9, 7, 10, 0, 0, tzinfo=SHANGHAI)
CSS_URL_PATTERN = re.compile(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)", re.IGNORECASE)
CSS_QUOTED_IMPORT_PATTERN = re.compile(
    r"@import\s+(['\"])([^'\"]+)\1",
    re.IGNORECASE,
)


def _page(response):
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    return BeautifulSoup(response.data, "html.parser")


def _publish_catalog(db):
    """Promote the checked-in neutral catalog in this test's disposable DB."""
    db.execute(
        "UPDATE content_items SET status='published',published_at=? "
        "WHERE entry_type IN ('industry','scenario','service') AND status='draft'",
        ("2026-08-24 10:00:00",),
    )
    db.commit()


def _publish_legal(document_type, version_code, *, summary):
    from legal_repository import (
        confirm_legal_review,
        create_legal_draft,
        publish_legal_version,
    )

    version_id = create_legal_draft(
        document_type=document_type,
        version_code=version_code,
        title=f"{document_type} {version_code}",
        body_summary=summary,
        body_html="<p>Reviewed legal body</p>",
        effective_at=NOW,
        actor="test-admin",
        now=NOW,
    )
    lock_version = confirm_legal_review(
        version_id,
        expected_lock_version=1,
        actor="test-admin",
        now=NOW,
    )
    publish_legal_version(
        version_id,
        lock_version,
        actor="test-admin",
        now=NOW,
    )
    return version_id


def _assert_local_rendered_dependencies(document, *, path):
    for script in document.select("script[src]"):
        assert script["src"].startswith("/static/"), (
            path,
            "remote script dependency",
            script["src"],
        )
        assert script.has_attr("defer"), path

    for image in document.select("img[src]"):
        assert image["src"].startswith(("/static/", "/media/")), (
            path,
            "remote image dependency",
            image["src"],
        )

    for stylesheet in document.select('link[rel~="stylesheet"][href]'):
        assert stylesheet["href"].startswith("/static/"), (
            path,
            "remote stylesheet dependency",
            stylesheet["href"],
        )


def _css_asset_references(css):
    references = [match.group(2).strip() for match in CSS_URL_PATTERN.finditer(css)]
    references.extend(
        match.group(2).strip()
        for match in CSS_QUOTED_IMPORT_PATTERN.finditer(css)
    )
    return references


def _assert_local_stylesheet_dependencies(css, *, stylesheet_href):
    base = f"https://local-assets.invalid{stylesheet_href}"
    for reference in _css_asset_references(css):
        if reference.startswith("data:"):
            continue
        resolved = urlsplit(urljoin(base, reference))
        assert (
            resolved.scheme == "https"
            and resolved.netloc == "local-assets.invalid"
            and resolved.path.startswith("/static/")
        ), (stylesheet_href, "remote CSS dependency", reference)


def _assert_local_page_dependencies(client, document, *, path):
    _assert_local_rendered_dependencies(document, path=path)

    stylesheets = document.select('link[rel~="stylesheet"][href]')
    assert stylesheets, path
    for stylesheet in stylesheets:
        href = stylesheet["href"]
        response = client.get(href)
        assert response.status_code == 200, (path, href)
        assert response.mimetype == "text/css", (path, href)
        _assert_local_stylesheet_dependencies(
            response.get_data(as_text=True),
            stylesheet_href=href,
        )


@pytest.mark.parametrize(
    "path",
    (
        "/",
        "/industries",
        "/scenarios",
        "/service-packages",
        "/cases",
        "/resources",
        "/about",
        "/assessment",
    ),
)
def test_public_pages_use_only_local_deferred_asset_dependencies(client, path):
    document = _page(client.get(path))

    _assert_local_page_dependencies(client, document, path=path)


@pytest.mark.parametrize(
    "unsafe_markup",
    (
        '<img src="https://assets.example/remote.webp" alt="">',
        '<link rel="stylesheet" href="//assets.example/remote.css">',
    ),
)
def test_local_dependency_guard_rejects_remote_rendered_assets(unsafe_markup):
    document = BeautifulSoup(
        f"<html><head></head><body>{unsafe_markup}</body></html>",
        "html.parser",
    )

    with pytest.raises(AssertionError, match="remote (image|stylesheet) dependency"):
        _assert_local_rendered_dependencies(document, path="mutated fixture")


@pytest.mark.parametrize(
    "unsafe_css",
    (
        '@import "https://assets.example/remote-fonts.css";',
        "@font-face { src: url(//assets.example/remote.woff2) format('woff2'); }",
    ),
)
def test_local_dependency_guard_rejects_remote_css_imports_and_fonts(unsafe_css):
    with pytest.raises(AssertionError, match="remote CSS dependency"):
        _assert_local_stylesheet_dependencies(
            unsafe_css,
            stylesheet_href="/static/css/mutated.css",
        )


def test_approved_detail_dependency_guard_rejects_remote_mutation(client, db):
    _publish_catalog(db)
    path = "/industries/manufacturing"
    document = _page(client.get(path))
    document.select_one('link[rel~="stylesheet"]')["href"] = (
        "https://assets.example/detail.css"
    )

    with pytest.raises(AssertionError, match="remote stylesheet dependency"):
        _assert_local_page_dependencies(client, document, path=path)


def test_public_route_matrix_has_unique_titles_and_trusted_canonicals(client):
    paths = (
        "/",
        "/industries",
        "/scenarios",
        "/service-packages",
        "/cases",
        "/resources",
        "/about",
        "/assessment",
    )
    documents = {
        path: _page(
            client.get(
                f"{path}?campaign=https://attacker.example",
                headers={
                    "Host": "attacker.example",
                    "X-Forwarded-Host": "forwarded.example",
                },
            )
        )
        for path in paths
    }

    titles = [document.title.get_text(strip=True) for document in documents.values()]
    assert all(titles)
    assert len(titles) == len(set(titles))
    for path, document in documents.items():
        canonicals = document.select('link[rel="canonical"]')
        assert len(canonicals) == 1, path
        assert canonicals[0]["href"] == f"https://test.example{path}"


def test_private_html_surfaces_remain_noindex(client):
    for path in ("/admin/login", "/assessment/report/999"):
        response = client.get(path)
        document = BeautifulSoup(response.data, "html.parser")
        robots = document.select_one('meta[name="robots"]')

        assert robots is not None, path
        assert "noindex" in robots.get("content", "").lower(), path
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_shipped_logo_and_decorative_images_have_intrinsic_dimensions(client, db):
    _publish_catalog(db)
    paths = (
        "/",
        "/industries",
        "/industries/manufacturing",
        "/scenarios/mfg-knowledge-assistant",
        "/service-packages/foundation-workshop",
        "/about",
    )

    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        document = _page(response)
        _assert_local_page_dependencies(client, document, path=path)
        images = document.select("img[src]")
        assert images, path
        for image in images:
            assert image["src"].startswith("/static/"), (path, image["src"])
            assert image.get("width"), (path, image.get("src"))
            assert image.get("height"), (path, image.get("src"))

    logo = _page(client.get("/")).select_one('.nav-logo img[src="/static/logo.png"]')
    assert logo.get("width") == "859"
    assert logo.get("height") == "1066"
    assert logo.get("decoding") == "async"


def test_above_fold_decorative_images_are_eager_and_high_priority(client, db):
    _publish_catalog(db)
    roles = (
        ("/", "img[data-home-art]"),
        ("/industries", ".public-page-header__art img"),
        ("/industries/manufacturing", ".detail-hero__media img"),
        ("/about", ".manifesto-cover__media img"),
    )

    for path, selector in roles:
        image = _page(client.get(path)).select_one(selector)
        assert image is not None, path
        assert image.get("loading") == "eager", path
        assert image.get("fetchpriority") == "high", path


def test_approved_editorial_detail_heroes_are_eager_and_high_priority(
    admin_client,
    db,
):
    from tests.test_resources_announcements import (
        _create_announcement,
        _create_resource,
    )
    from tests.test_verified_cases import _create_case, _edit_form

    case = _create_case(admin_client, db, slug="performance-case")
    assert admin_client.post(
        f"/admin/cases/{case['id']}",
        data=_edit_form(db, case["id"], action="publish"),
    ).status_code == 302
    _create_resource(
        admin_client,
        db,
        slug="performance-resource",
        action="publish",
    )
    _create_announcement(
        admin_client,
        db,
        slug="performance-announcement",
        action="publish",
    )

    for path in (
        "/cases/performance-case",
        "/resources/performance-resource",
        "/announcements/performance-announcement",
    ):
        document = _page(admin_client.get(path))
        _assert_local_page_dependencies(admin_client, document, path=path)
        image = document.select_one(".editorial-cover__media img")
        assert image is not None, path
        assert image.get("loading") == "eager", path
        assert image.get("fetchpriority") == "high", path


def test_home_below_fold_images_are_lazy_and_async(client):
    document = _page(client.get("/"))
    images = document.select("img[data-home-art], img[data-technology-art]")

    assert len(images) >= 5
    for image in images[1:]:
        assert image.get("loading") == "lazy"
        assert image.get("decoding") == "async"


def test_internal_legal_current_and_history_have_escaped_metadata_from_trusted_origin(
    client,
):
    summary = '"><script data-summary-xss="1">alert(1)</script> reviewed summary'
    _publish_legal("terms", "terms-v1", summary=summary)
    _publish_legal("terms", "terms-v2", summary="Current reviewed summary")

    responses = {
        "/legal/terms": client.get(
            "/legal/terms?next=https://attacker.example",
            headers={
                "Host": "attacker.example",
                "X-Forwarded-Host": "forwarded.example",
            },
        ),
        "/legal/terms/terms-v1": client.get(
            "/legal/terms/terms-v1?next=https://attacker.example",
            headers={
                "Host": "attacker.example",
                "X-Forwarded-Host": "forwarded.example",
            },
        ),
    }

    for path, response in responses.items():
        document = _page(response)
        _assert_local_page_dependencies(client, document, path=path)
        canonicals = document.select('link[rel="canonical"]')
        descriptions = document.select('meta[name="description"]')

        assert len(canonicals) == 1
        assert canonicals[0]["href"] == f"https://test.example{path}"
        assert len(descriptions) == 1
        assert descriptions[0]["content"]
        assert urlsplit(canonicals[0]["href"]).netloc == "test.example"
        assert document.select_one("script[data-summary-xss]") is None
        assert response.get_data(as_text=True).count('rel="canonical"') == 1

    historical = BeautifulSoup(
        responses["/legal/terms/terms-v1"].data,
        "html.parser",
    )
    assert historical.select_one('meta[name="description"]')["content"] == summary


def test_legal_metadata_does_not_change_redirect_or_private_version_behavior(client, db):
    from legal_repository import reconcile_external_privacy_reference

    _publish_legal("terms", "published-v1", summary="Published summary")
    from legal_repository import create_legal_draft

    create_legal_draft(
        document_type="terms",
        version_code="draft-v1",
        title="Draft",
        body_summary="Draft summary",
        body_html="<p>Draft</p>",
        effective_at=NOW,
        actor="test-admin",
        now=NOW,
    )
    reconcile_external_privacy_reference(
        db,
        "legacy-v1",
        "https://legal.example/privacy",
        NOW,
    )

    redirect_response = client.get("/legal/privacy/legacy-v1")
    assert redirect_response.status_code == 302
    assert redirect_response.headers["Location"] == "https://legal.example/privacy"
    assert client.get("/legal/terms/draft-v1").status_code == 404
    assert client.get("/legal/terms/missing-v1").status_code == 404
