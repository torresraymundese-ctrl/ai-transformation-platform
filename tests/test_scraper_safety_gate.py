from unittest.mock import Mock
from pathlib import Path

import pytest
import requests
from bs4 import BeautifulSoup


TOKEN = "test-csrf-token"
ROOT = Path(__file__).resolve().parents[1]


def legacy_article_rows(db):
    return db.execute(
        "SELECT title, source, source_url, summary, content_html, tags, category "
        "FROM articles ORDER BY id"
    ).fetchall()


def test_legacy_scrape_is_disabled_without_network_or_legacy_article_writes(
    admin_client, monkeypatch, db
):
    """Enabling the old route must fail before it can fetch or publish content."""
    network = Mock(side_effect=AssertionError("network must remain unused"))
    monkeypatch.setattr(requests, "get", network)
    before = legacy_article_rows(db)

    response = admin_client.post("/admin/scrape", data={"csrf_token": TOKEN})

    assert response.status_code == 410
    assert response.get_json() == {"error": "ingestion_queue_not_ready"}
    assert legacy_article_rows(db) == before
    network.assert_not_called()


def test_legacy_scrape_response_is_private_and_audited_without_disclosure(
    admin_client, db
):
    """The unavailable response must retain admin boundaries without source details."""
    response = admin_client.post("/admin/scrape", data={"csrf_token": TOKEN})
    audit = db.execute(
        "SELECT actor, action, status_code FROM admin_audit_logs "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()

    assert response.status_code == 410
    assert response.get_json() == {"error": "ingestion_queue_not_ready"}
    assert b"http" not in response.data
    assert response.headers["Cache-Control"] == "private, no-store"
    assert dict(audit) == {
        "actor": "test-admin",
        "action": "admin_scrape",
        "status_code": 410,
    }


def test_legacy_scrape_keeps_anonymous_callers_at_the_login_boundary(client):
    """Unauthenticated callers must not learn the ingestion-gate response."""
    response = client.post("/admin/scrape")

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_legacy_scrape_rejects_missing_csrf_before_running(admin_client, monkeypatch):
    """An authenticated session alone must not activate the retired action."""
    network = Mock(side_effect=AssertionError("network must remain unused"))
    monkeypatch.setattr(requests, "get", network)

    response = admin_client.post("/admin/scrape")

    assert response.status_code == 403
    network.assert_not_called()


def test_dashboard_replaces_legacy_scrape_control_with_review_queue_link(admin_client):
    """The dashboard must route operators to review instead of retired publication."""
    response = admin_client.get("/admin")
    page = BeautifulSoup(response.data, "html.parser")
    queue_link = page.select_one('a[href="/admin/ingestion"]')

    assert response.status_code == 200
    assert queue_link is not None
    assert "接入候选" in queue_link.get_text()
    assert page.select_one('button[data-ingestion-queue-state]') is None
    assert page.select_one('form[action="/admin/scrape"]') is None
    assert b"fetch('/admin/scrape'" not in response.data

    queue_response = admin_client.get(queue_link["href"])
    queue_page = BeautifulSoup(queue_response.data, "html.parser")
    current_action = queue_page.select_one('form[action="/admin/scrape"][method="post"]')
    assert queue_response.status_code == 200
    assert current_action is not None
    assert current_action.select_one(
        'input[name="csrf_token"][value="test-csrf-token"]'
    ) is not None
    assert "抓取已启用来源" in current_action.get_text()


def test_direct_legacy_scraper_fails_closed_without_calling_source_adapter(monkeypatch):
    """A direct script invocation must not bypass the queue gate."""
    import scraper

    source_adapter = Mock(side_effect=AssertionError("adapter must remain unused"))
    monkeypatch.setattr(scraper, "SOURCE_ADAPTERS", (source_adapter,))

    with pytest.raises(scraper.IngestionQueueNotReadyError) as error:
        scraper.run_scraper()

    assert str(error.value) == "ingestion_queue_not_ready"
    source_adapter.assert_not_called()


def test_deployment_and_script_entrypoints_do_not_invoke_legacy_publication_helpers():
    """Deployment and direct scripts must not bypass the reviewed ingestion queue."""
    legacy_helpers = ("add_curated_articles", "save_article")
    entrypoints = (ROOT / "deploy.sh", ROOT / "scraper.py", ROOT / "manage.py")

    for entrypoint in entrypoints:
        source = entrypoint.read_text(encoding="utf-8")
        assert not any(helper in source for helper in legacy_helpers), entrypoint
