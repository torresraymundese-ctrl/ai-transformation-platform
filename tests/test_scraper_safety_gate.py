from unittest.mock import Mock

import pytest
import requests
from bs4 import BeautifulSoup


TOKEN = "test-csrf-token"


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


def test_legacy_scrape_control_is_disabled_with_queue_explanation(admin_client):
    """The dashboard must not offer an active control for retired publication."""
    response = admin_client.get("/admin")
    page = BeautifulSoup(response.data, "html.parser")
    control = page.select_one("button[data-ingestion-queue-state]")

    assert response.status_code == 200
    assert control is not None
    assert control.has_attr("disabled")
    assert control["data-ingestion-queue-state"] == "not-ready"
    assert "内容接入队列尚未就绪" in control.get_text()
    assert b"fetch('/admin/scrape'" not in response.data


def test_direct_legacy_scraper_fails_closed_without_calling_source_adapter(monkeypatch):
    """A direct script invocation must not bypass the queue gate."""
    import scraper

    source_adapter = Mock(side_effect=AssertionError("adapter must remain unused"))
    monkeypatch.setattr(scraper, "SOURCE_ADAPTERS", (source_adapter,))

    with pytest.raises(scraper.IngestionQueueNotReadyError) as error:
        scraper.run_scraper()

    assert str(error.value) == "ingestion_queue_not_ready"
    source_adapter.assert_not_called()
