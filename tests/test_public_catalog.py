"""Public, read-only catalog routes use only published catalog aggregates."""

from datetime import datetime, timedelta

import pytest
from bs4 import BeautifulSoup

import app as app_module
from content_clock import SHANGHAI
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


def test_public_catalog_lists_use_the_shared_shell_and_private_analytics(published_catalog):
    industries = page(published_catalog.get("/industries"))
    scenarios = page(published_catalog.get("/scenarios"))

    assert {card["data-industry-code"] for card in industries.select("[data-industry-code]")} == {
        "manufacturing", "retail", "professional_knowledge", "software_creative"
    }
    assert len(scenarios.select("[data-scenario-code]")) == 13
    for document in (industries, scenarios):
        assert document.select_one('a[href="/assessment"]') is not None
        assert document.select_one('body[data-analytics-page]') is not None


def test_scenario_filters_are_intersection_not_union(published_catalog):
    response = published_catalog.get(
        "/scenarios?industry=manufacturing&department=production&maturity=explore"
    )
    document = page(response)
    codes = {card["data-scenario-code"] for card in document.select("[data-scenario-code]")}

    assert codes == {"mfg_knowledge_assistant", "data_process_foundation"}


@pytest.mark.parametrize("query", (
    "?industry=invalid&department=invalid&maturity=starting&page=-1&per_page=999",
    "?industry=manufacturing&maturity=starting&page=zero&per_page=20.5",
))
def test_invalid_get_filters_fall_back_to_safe_defaults(published_catalog, query):
    document = page(published_catalog.get(f"/scenarios{query}"))
    expected_count = 13 if "industry=invalid" in query else 4
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


def test_every_published_detail_has_its_required_sections(published_catalog, db):
    expected = (("industry", "/industries", INDUSTRY_REQUIRED_SECTIONS),
                ("scenario", "/scenarios", SCENARIO_REQUIRED_SECTIONS))
    for entry_type, prefix, sections in expected:
        slugs = [row[0] for row in db.execute(
            "SELECT slug FROM content_items WHERE entry_type=? AND status='published' ORDER BY id",
            (entry_type,),
        )]
        for slug in slugs:
            document = page(published_catalog.get(f"{prefix}/{slug}"))
            assert sections <= {node["data-content-section"] for node in document.select("[data-content-section]")}


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
