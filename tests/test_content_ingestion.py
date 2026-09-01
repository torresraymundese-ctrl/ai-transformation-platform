from dataclasses import replace
from datetime import datetime
import hashlib
import json
import sqlite3

import pytest

import models
import manage
import ingestion_service
import ingestion_sources
import publishing_repository
from content_validation import ContentValidationError
from publishing_service import (
    publish_content,
    refresh_content_source_check,
    save_content_draft,
)
from ingestion_contracts import FetchedItem
from ingestion_repository import load_candidate, mark_candidate_pending, store_candidates
from ingestion_service import (
    AcceptDecision,
    IngestionDecisionError,
    accept_candidate,
    reject_candidate,
    run_enabled_sources,
)
from ingestion_sources import SourcePolicy
from source_url_checker import FetchResult


NOW = datetime.fromisoformat("2026-08-31T10:00:00+08:00")
TOKEN = "test-csrf-token"


def _reviewed_source(
    code="reviewed_news",
    name="经审核来源",
    url="https://example.com/reviewed",
    hosts=("example.com",),
    scheme="https",
    license_basis_reference="terms_2026_08",
):
    return {
        "code": code,
        "name": name,
        "url": url,
        "hosts": list(hosts),
        "adapter": "plain_text",
        "scheme": scheme,
        "license_basis_reference": license_basis_reference,
        "robots_policy": "allow",
        "retain_body": False,
        "enabled": False,
    }


@pytest.fixture(autouse=True)
def reviewed_registry(tmp_path, monkeypatch):
    path = tmp_path / "reviewed-ingestion-sources.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "sources": [
                    _reviewed_source(),
                    _reviewed_source(
                        code="reviewed_http",
                        name="经审核 HTTP 来源",
                        url="http://http-source.example.net/report",
                        hosts=("http-source.example.net",),
                        scheme="http",
                        license_basis_reference="http_terms_2026_08",
                    ),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ingestion_sources, "REGISTRY_PATH", path)
    monkeypatch.delenv("AI_PLATFORM_INGESTION_SOURCE_CODES", raising=False)
    return path


def _pending_candidate(
    db,
    *,
    url="https://example.com/reviewed",
    body="<p>正文</p>",
    source_code="reviewed_news",
    source_name="经审核来源",
):
    result = store_candidates(
        (
            FetchedItem(
                source_code=source_code,
                source_name=source_name,
                url=url,
                title="待审核的内容",
                summary="经过许可的固定摘要。",
                body_html=body,
                original_published_at=NOW,
            ),
        ),
        NOW,
    )
    candidate_id = result.created_ids[0]
    mark_candidate_pending(db, candidate_id, 1, NOW)
    db.commit()
    return candidate_id


def test_accept_creates_fixed_resource_draft_and_audit_in_one_transaction(db):
    candidate_id = _pending_candidate(db)

    content_id = accept_candidate(
        candidate_id,
        AcceptDecision(slug="reviewed-ingestion"),
        2,
        "test-admin",
        NOW,
    )

    candidate = load_candidate(candidate_id)
    content = db.execute(
        "SELECT ci.entry_type,ci.status,ci.publish_at,rc.resource_type,rc.is_original,"
        "rc.source_name,rc.source_url,rc.copyright_notice "
        "FROM content_items ci JOIN resource_content rc ON rc.content_item_id=ci.id "
        "WHERE ci.id=?",
        (content_id,),
    ).fetchone()
    governance = db.execute(
        "SELECT action,actor,metadata_json FROM governance_audit_events "
        "WHERE target_type='ingestion_candidate' AND target_id=?",
        (candidate_id,),
    ).fetchone()

    assert candidate.state == "accepted"
    assert candidate.target_content_id == content_id
    assert candidate.lock_version == 3
    assert tuple(content) == (
        "resource",
        "draft",
        None,
        "article",
        0,
        "经审核来源",
        "https://example.com/reviewed",
        "licensed_source_terms_2026_08",
    )
    assert dict(governance) == {
        "action": "ingestion_accepted",
        "actor": "test-admin",
        "metadata_json": '{"target_content_id":%d}' % content_id,
    }


def test_accept_rechecks_fixed_policy_and_does_not_restore_unlicensed_body(db):
    candidate_id = _pending_candidate(db, body="<p>不得进入草稿的远端正文</p>")

    content_id = accept_candidate(
        candidate_id,
        AcceptDecision(slug="summary-only-ingestion"),
        2,
        "test-admin",
        NOW,
    )

    body = db.execute(
        "SELECT body_html FROM content_blocks WHERE content_item_id=?",
        (content_id,),
    ).fetchone()[0]
    assert "经过许可的固定摘要" in body
    assert "远端正文" not in body

    attacker_id = _pending_candidate(db, url="https://attacker.invalid/content")
    with pytest.raises(IngestionDecisionError, match="candidate_source_invalid"):
        accept_candidate(
            attacker_id,
            AcceptDecision(slug="wrong-host-ingestion"),
            2,
            "test-admin",
            NOW,
        )
    assert load_candidate(attacker_id).state == "pending_review"


def test_accept_uses_current_reviewed_policy_name_not_candidate_snapshot(db):
    candidate_id = _pending_candidate(
        db,
        source_name="旧候选中被污染的来源名称",
    )

    content_id = accept_candidate(
        candidate_id,
        AcceptDecision(slug="policy-owned-source-name"),
        2,
        "test-admin",
        NOW,
    )

    source_name = db.execute(
        "SELECT source_name FROM resource_content WHERE content_item_id=?",
        (content_id,),
    ).fetchone()[0]
    assert source_name == "经审核来源"


def test_accept_fails_closed_when_current_policy_disallows_robots(
    db, reviewed_registry
):
    payload = json.loads(reviewed_registry.read_text(encoding="utf-8"))
    payload["sources"][0]["robots_policy"] = "disallow"
    reviewed_registry.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    candidate_id = _pending_candidate(
        db,
        source_name="旧候选中的污染名称",
    )

    with pytest.raises(IngestionDecisionError, match="candidate_source_invalid"):
        accept_candidate(
            candidate_id,
            AcceptDecision(slug="robots-disallowed-source"),
            2,
            "test-admin",
            NOW,
        )

    candidate = load_candidate(candidate_id)
    assert (candidate.state, candidate.lock_version, candidate.target_content_id) == (
        "pending_review",
        2,
        None,
    )
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE slug='robots-disallowed-source'"
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM governance_audit_events "
        "WHERE target_type='ingestion_candidate' AND target_id=?",
        (candidate_id,),
    ).fetchone()[0] == 0


def test_reviewed_http_accepts_only_to_private_draft_then_requires_real_https_check(db):
    candidate_id = _pending_candidate(
        db,
        url="http://http-source.example.net/report",
        source_code="reviewed_http",
        source_name="经审核 HTTP 来源",
    )

    content_id = accept_candidate(
        candidate_id,
        AcceptDecision(slug="private-http-ingestion"),
        2,
        "test-admin",
        NOW,
    )

    row = db.execute(
        "SELECT ci.status,ci.publish_at,rc.source_url FROM content_items ci "
        "JOIN resource_content rc ON rc.content_item_id=ci.id WHERE ci.id=?",
        (content_id,),
    ).fetchone()
    assert tuple(row) == (
        "draft",
        None,
        "http://http-source.example.net/report",
    )
    with pytest.raises(ContentValidationError, match="source_check_invalid"):
        publish_content(content_id, 1, actor="test-admin", now=NOW)

    draft = publishing_repository.load_content_draft(db, content_id)
    https_url = "https://http-source.example.net/report"
    https_draft = replace(
        draft,
        extension={
            **dict(draft.extension),
            "source_url": https_url,
            "source_url_sha256": hashlib.sha256(https_url.encode()).hexdigest(),
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
        },
    )
    assert save_content_draft(
        content_id, 1, https_draft, actor="test-admin", now=NOW
    ) == 2
    with pytest.raises(ContentValidationError, match="source_check_invalid"):
        publish_content(content_id, 2, actor="test-admin", now=NOW)

    class SuccessfulTransport:
        def fetch(self, url, **_kwargs):
            return FetchResult(True, "https_ok", url, 200, "text/html", b"ok")

    refresh_content_source_check(
        content_id,
        2,
        hashlib.sha256(https_url.encode()).hexdigest(),
        actor="test-admin",
        transport=SuccessfulTransport(),
        now=NOW,
    )
    publish_content(content_id, 3, actor="test-admin", now=NOW)
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (content_id,)
    ).fetchone()[0] == "published"


def test_draft_failure_rolls_back_candidate_and_governance_event(db, monkeypatch):
    candidate_id = _pending_candidate(db)

    def fail(*_args, **_kwargs):
        raise ContentValidationError("draft_invalid")

    monkeypatch.setattr(publishing_repository, "insert_content_draft", fail)

    with pytest.raises(ContentValidationError, match="draft_invalid"):
        accept_candidate(
            candidate_id,
            AcceptDecision(slug="rollback-ingestion"),
            2,
            "test-admin",
            NOW,
        )

    assert load_candidate(candidate_id).state == "pending_review"
    assert db.execute(
        "SELECT COUNT(*) FROM governance_audit_events WHERE target_id=?",
        (candidate_id,),
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE slug='rollback-ingestion'"
    ).fetchone()[0] == 0


def test_reject_uses_fixed_reason_bounded_note_and_optimistic_lock(db):
    candidate_id = _pending_candidate(db)

    reject_candidate(candidate_id, "irrelevant", "not_relevant", 2, "test-admin", NOW)

    candidate = load_candidate(candidate_id)
    assert (candidate.state, candidate.rejection_code, candidate.rejection_note) == (
        "rejected",
        "irrelevant",
        "not_relevant",
    )
    with pytest.raises(IngestionDecisionError, match="candidate_conflict"):
        reject_candidate(candidate_id, "duplicate", "duplicate", 2, "test-admin", NOW)


@pytest.mark.parametrize(
    "reason,note",
    [
        ("invented", "valid_code"),
        ("insufficient_evidence", "https://example.com/private"),
        ("insufficient_evidence", "person@example.com"),
        ("insufficient_evidence", "自由文本"),
        ("insufficient_evidence", "x" * 201),
    ],
)
def test_reject_rejects_unfixed_or_sensitive_decision_text(db, reason, note):
    candidate_id = _pending_candidate(db, url=f"https://example.com/{reason}-{len(note)}")

    with pytest.raises(IngestionDecisionError):
        reject_candidate(candidate_id, reason, note, 2, "test-admin", NOW)

    assert load_candidate(candidate_id).state == "pending_review"


def test_admin_choice_first_review_rejects_caller_url_and_never_publishes(
    admin_client, db
):
    candidate_id = _pending_candidate(db)

    page = admin_client.get(f"/admin/ingestion/{candidate_id}")
    assert page.status_code == 200
    assert page.headers["Cache-Control"] == "private, no-store"
    assert b'name="source_url"' not in page.data
    assert b'name="url"' not in page.data

    rejected = admin_client.post(
        f"/admin/ingestion/{candidate_id}/decision",
        data={
            "csrf_token": TOKEN,
            "action": "accept",
            "slug": "admin-reviewed",
            "expected_lock_version": "2",
            "url": "https://attacker.invalid/override",
        },
    )
    assert rejected.status_code == 400
    assert load_candidate(candidate_id).state == "pending_review"

    accepted = admin_client.post(
        f"/admin/ingestion/{candidate_id}/decision",
        data={
            "csrf_token": TOKEN,
            "action": "accept",
            "slug": "admin-reviewed",
            "expected_lock_version": "2",
        },
    )
    assert accepted.status_code == 302
    assert db.execute(
        "SELECT status FROM content_items WHERE slug='admin-reviewed'"
    ).fetchone()[0] == "draft"
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE slug='admin-reviewed' AND status='published'"
    ).fetchone()[0] == 0


def test_admin_routes_require_auth_csrf_single_owner_and_are_audited(client, admin_client, db):
    anonymous = client.application.test_client()
    assert anonymous.get("/admin/ingestion").status_code == 302
    assert admin_client.post("/admin/scrape").status_code == 403
    rules = [rule for rule in admin_client.application.url_map.iter_rules() if rule.rule == "/admin/scrape"]
    assert len(rules) == 1
    assert rules[0].endpoint == "admin.admin_scrape"

    response = admin_client.post("/admin/scrape", data={"csrf_token": TOKEN})
    assert response.status_code == 410
    assert response.get_json() == {"error": "ingestion_queue_not_ready"}
    audit = db.execute(
        "SELECT actor,action,status_code FROM admin_audit_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert tuple(audit) == ("test-admin", "admin_scrape", 410)
    assert response.headers["Cache-Control"] == "private, no-store"


def test_stale_accept_is_generic_and_discloses_no_candidate_source(admin_client, db):
    candidate_id = _pending_candidate(db, url="https://example.com/path?secret=hidden")

    response = admin_client.post(
        f"/admin/ingestion/{candidate_id}/decision",
        data={
            "csrf_token": TOKEN,
            "action": "accept",
            "slug": "stale-candidate",
            "expected_lock_version": "1",
        },
    )

    assert response.status_code == 409
    assert response.get_json() == {"error": "candidate_conflict"}
    assert b"secret" not in response.data
    assert b"example.com" not in response.data


def test_decision_transaction_uses_begin_immediate(db, monkeypatch):
    candidate_id = _pending_candidate(db)
    statements = []
    original_get_db = models.get_db

    def traced_db():
        connection = original_get_db()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(models, "get_db", traced_db)

    accept_candidate(
        candidate_id,
        AcceptDecision(slug="immediate-transaction"),
        2,
        "test-admin",
        NOW,
    )

    assert any(statement.upper() == "BEGIN IMMEDIATE" for statement in statements)


class _FixedTransport:
    def __init__(self):
        self.calls = 0

    def fetch(self, url, **_kwargs):
        self.calls += 1
        return FetchResult(True, "https_ok", url, 200, "text/plain", b"summary")


def _enabled_policy():
    return SourcePolicy(
        code="reviewed_news",
        name="经审核来源",
        url="https://example.com/reviewed",
        hosts=frozenset({"example.com"}),
        adapter="fixed",
        scheme="https",
        license_basis_reference="terms_2026_08",
        robots_policy="allow",
        retain_body=False,
        enabled=True,
    )


def _fixed_adapter(policy, result, now):
    return (
        FetchedItem(
            policy.code,
            policy.name,
            result.final_url,
            "重复抓取标题",
            "重复抓取摘要。",
            "<p>不得保留的正文</p>",
            now,
        ),
    )


def test_repeated_fixed_fetch_records_attempts_deduplicates_and_never_publishes(
    db, reviewed_registry, monkeypatch
):
    transport = _FixedTransport()
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news")
    options = {
        "registry_path": reviewed_registry,
        "transport": transport,
        "adapters": {"plain_text": _fixed_adapter},
        "now": NOW,
    }

    first = run_enabled_sources(**options)
    second = run_enabled_sources(**options)

    assert len(first.created_ids) == 1
    assert second.created_ids == ()
    assert second.deduplicated == 1
    assert transport.calls == 2
    candidate = load_candidate(first.created_ids[0])
    assert (candidate.state, candidate.lock_version, candidate.body_html) == (
        "pending_review",
        2,
        None,
    )
    assert db.execute("SELECT COUNT(*) FROM ingestion_fetch_attempts").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM content_items WHERE status='published'").fetchone()[0] == 0


def test_admin_queue_trigger_uses_validated_current_registry_without_caller_url(
    admin_client, db, monkeypatch
):
    transport = _FixedTransport()
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news")
    admin_client.application.config.update(
        INGESTION_TRANSPORT=transport,
        INGESTION_ADAPTERS={"plain_text": _fixed_adapter},
        ADMIN_NOW_PROVIDER=lambda: NOW,
    )
    published_before = db.execute(
        "SELECT COUNT(*) FROM content_items WHERE status='published'"
    ).fetchone()[0]

    response = admin_client.post("/admin/scrape", data={"csrf_token": TOKEN})

    assert response.status_code == 200
    assert response.get_json()["created_count"] == 1
    assert transport.calls == 1
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE status='published'"
    ).fetchone()[0] == published_before


def test_admin_queue_trigger_ignores_raw_source_policy_configuration(admin_client):
    transport = _FixedTransport()
    admin_client.application.config.update(
        INGESTION_SOURCE_REGISTRY=(_enabled_policy(),),
        INGESTION_TRANSPORT=transport,
        INGESTION_ADAPTERS={"plain_text": _fixed_adapter},
        ADMIN_NOW_PROVIDER=lambda: NOW,
    )

    response = admin_client.post("/admin/scrape", data={"csrf_token": TOKEN})

    assert response.status_code == 410
    assert response.get_json() == {"error": "ingestion_queue_not_ready"}
    assert transport.calls == 0


def test_admin_queue_trigger_ignores_legacy_registry_path_configuration(
    admin_client, tmp_path, monkeypatch
):
    untrusted_path = tmp_path / "untrusted-admin-registry.json"
    untrusted_path.write_text("{}", encoding="utf-8")
    transport = _FixedTransport()
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news")
    admin_client.application.config.update(
        INGESTION_SOURCE_REGISTRY_PATH=untrusted_path,
        INGESTION_TRANSPORT=transport,
        INGESTION_ADAPTERS={"plain_text": _fixed_adapter},
        ADMIN_NOW_PROVIDER=lambda: NOW,
    )

    response = admin_client.post("/admin/scrape", data={"csrf_token": TOKEN})

    assert response.status_code == 200
    assert response.get_json()["created_count"] == 1
    assert transport.calls == 1


def test_fetch_content_cli_runs_validated_registry_to_candidate_without_publishing(
    db, reviewed_registry, monkeypatch, capsys
):
    transport = _FixedTransport()
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news")
    monkeypatch.setattr(
        ingestion_service,
        "PinnedHttpTransport",
        lambda **_kwargs: transport,
    )
    published_before = db.execute(
        "SELECT COUNT(*) FROM content_items WHERE status='published'"
    ).fetchone()[0]

    assert manage.main(["fetch-content"]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    fields = dict(part.split("=", 1) for part in output.out.strip().split())
    assert fields["created_count"] == "1"
    assert fields["deduplicated"] == "0"
    assert fields["attempted_sources"] == "1"
    assert fields["failed_sources"] == "0"
    candidate_id = int(fields["created_ids"])
    candidate = load_candidate(candidate_id)
    assert (candidate.source_code, candidate.state, candidate.lock_version) == (
        "reviewed_news",
        "pending_review",
        2,
    )
    assert transport.calls == 1
    assert db.execute(
        "SELECT COUNT(*) FROM ingestion_fetch_attempts"
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE status='published'"
    ).fetchone()[0] == published_before
