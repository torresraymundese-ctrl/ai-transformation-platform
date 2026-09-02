from datetime import datetime
import hashlib
import json
import sqlite3

import pytest

from content_clock import SHANGHAI
from pagination import PageRequest


NOW = datetime(2026, 8, 31, 10, 0, 0, tzinfo=SHANGHAI)
TOMORROW = datetime(2026, 9, 1, 10, 0, 0, tzinfo=SHANGHAI)
FAR_FUTURE = datetime(2099, 1, 1, 10, 0, 0, tzinfo=SHANGHAI)


def _raw_digest(
    document_type,
    version_code,
    *,
    title,
    body_summary,
    body_html,
):
    payload = {
        "body_html": body_html,
        "body_summary": body_summary,
        "external_url": None,
        "mode": "internal",
        "title": title,
        "type": document_type,
        "version": version_code,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _draft(document_type="privacy", version_code="2026-08-31"):
    from legal_repository import create_legal_draft

    return create_legal_draft(
        document_type=document_type,
        version_code=version_code,
        title=f"{document_type} title",
        body_summary=f"{document_type} summary",
        body_html="<p>Reviewed body</p>",
        effective_at=NOW,
        actor="test-admin",
        now=NOW,
    )


def _reviewed(document_type="privacy", version_code="2026-08-31"):
    from legal_repository import confirm_legal_review

    version_id = _draft(document_type, version_code)
    lock_version = confirm_legal_review(
        version_id, expected_lock_version=1, actor="test-admin", now=NOW
    )
    return version_id, lock_version


def _published(document_type="privacy", version_code="2026-08-31"):
    from legal_repository import publish_legal_version

    version_id, lock_version = _reviewed(document_type, version_code)
    publish_legal_version(
        version_id, lock_version, actor="test-admin", now=NOW
    )
    return version_id


def test_canonical_digest_is_deterministic_and_sensitive_to_exact_content():
    from legal_repository import canonical_legal_digest

    content = {
        "document_type": "privacy",
        "version_code": "2026-08-31",
        "mode": "internal",
        "title": "Privacy",
        "body_summary": "Summary",
        "body_html": "<p>Body</p>",
        "external_url": None,
    }

    first = canonical_legal_digest(**content)
    second = canonical_legal_digest(**dict(reversed(tuple(content.items()))))

    assert first == second
    assert len(first) == 64
    assert canonical_legal_digest(**{**content, "title": "Changed"}) != first


@pytest.mark.parametrize(
    "version_code",
    ["", "-starts-with-symbol", "contains/slash", "contains space", "a" * 65],
)
def test_canonical_digest_rejects_invalid_version_codes(version_code):
    from legal_repository import LegalContractError, canonical_legal_digest

    with pytest.raises(LegalContractError):
        canonical_legal_digest(
            document_type="privacy",
            version_code=version_code,
            mode="internal",
            title="Privacy",
            body_summary="Summary",
            body_html="<p>Body</p>",
            external_url=None,
        )


def test_migration_creates_four_type_immutable_schema_and_binding_tables(db):
    columns = {row["name"] for row in db.execute("PRAGMA table_info(legal_documents)")}
    assert {
        "id",
        "document_type",
        "version_code",
        "mode",
        "content_sha256",
        "reviewed_content_sha256",
        "status",
        "lock_version",
        "effective_at",
    } <= columns
    assert {row["name"] for row in db.execute("PRAGMA table_info(lead_consents)")} >= {
        "legal_version_id"
    }
    snapshot_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(assessment_legal_versions)")
    }
    assert snapshot_columns == {
        "assessment_id",
        "document_type",
        "legal_version_id",
        "version_code",
        "digest",
    }

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO legal_documents "
            "(document_type,version_code,mode,title,body_summary,body_html,"
            "content_sha256,status,lock_version,effective_at,created_at,updated_at) "
            "VALUES ('other','v1','internal','t','s','<p>b</p>',?,'draft',1,?,?,?)",
            ("a" * 64, "2026-08-31 10:00:00", "2026-08-31 10:00:00", "2026-08-31 10:00:00"),
        )


def test_internal_draft_review_edit_requires_re_review_before_publication(db):
    from legal_repository import (
        LegalContractError,
        confirm_legal_review,
        publish_legal_version,
        update_legal_draft,
    )

    version_id, reviewed_lock = _reviewed()
    edited_lock = update_legal_draft(
        version_id,
        expected_lock_version=reviewed_lock,
        title="Changed title",
        body_summary="privacy summary",
        body_html="<p>Changed body</p><script>alert(1)</script>",
        effective_at=NOW,
        actor="test-admin",
        now=NOW,
    )
    row = db.execute("SELECT * FROM legal_documents WHERE id=?", (version_id,)).fetchone()
    assert row["lock_version"] == edited_lock
    assert row["reviewed_content_sha256"] is None
    assert row["legal_review_confirmed_at"] is None
    assert "script" not in row["body_html"]
    with pytest.raises(LegalContractError, match="review_required"):
        publish_legal_version(version_id, edited_lock, "test-admin", NOW)

    final_lock = confirm_legal_review(version_id, edited_lock, "test-admin", NOW)
    publish_legal_version(version_id, final_lock, "test-admin", NOW)
    assert db.execute(
        "SELECT status FROM legal_documents WHERE id=?", (version_id,)
    ).fetchone()[0] == "published"


@pytest.mark.parametrize("forbidden", ["\u202e", "\u200b", "\u0085", "\x00"])
def test_internal_body_rejects_unicode_control_and_format_characters(db, forbidden):
    from legal_repository import LegalContractError, create_legal_draft

    with pytest.raises(LegalContractError, match="body_html_invalid"):
        create_legal_draft(
            document_type="terms",
            version_code="unicode-v1",
            title="title",
            body_summary="summary",
            body_html=f"<p>safe{forbidden}text</p>",
            effective_at=NOW,
            actor="test-admin",
            now=NOW,
        )


@pytest.mark.parametrize(
    ("encoded_control", "version_code"),
    [
        ("&#x202E;", "entity-rlo-v1"),
        ("&#8203;", "entity-zwsp-v1"),
        ("&rlm;", "entity-rlm-v1"),
    ],
)
def test_internal_body_rejects_single_decoded_html_control_entities(
    db, encoded_control, version_code
):
    from legal_repository import LegalContractError, create_legal_draft

    with pytest.raises(LegalContractError, match="body_html_invalid"):
        create_legal_draft(
            document_type="terms",
            version_code=version_code,
            title="title",
            body_summary="summary",
            body_html=f"<p>safe{encoded_control}exe.txt</p>",
            effective_at=NOW,
            actor="test-admin",
            now=NOW,
        )


def test_internal_body_accepts_html5_numeric_reference_mapped_to_punctuation(db):
    import html
    import unicodedata

    from legal_repository import create_legal_draft

    body = "<p>safe&#x85;exe.txt</p>"
    version_id = create_legal_draft(
        document_type="terms",
        version_code="entity-html5-remap-v1",
        title="title",
        body_summary="summary",
        body_html=body,
        effective_at=NOW,
        actor="test-admin",
        now=NOW,
    )
    stored = db.execute(
        "SELECT body_html FROM legal_documents WHERE id=?", (version_id,)
    ).fetchone()[0]
    browser_equivalent = html.unescape(stored)
    assert "\u2026" in browser_equivalent
    assert not any(
        char not in {"\n", "\t"}
        and unicodedata.category(char).startswith("C")
        for char in browser_equivalent
    )


def test_internal_body_does_not_recursively_decode_escaped_control_entity(db):
    from legal_repository import create_legal_draft

    body = "<p>safe&amp;#x202E;exe.txt</p>"
    version_id = create_legal_draft(
        document_type="terms",
        version_code="escaped-entity-v1",
        title="title",
        body_summary="summary",
        body_html=body,
        effective_at=NOW,
        actor="test-admin",
        now=NOW,
    )
    assert db.execute(
        "SELECT body_html FROM legal_documents WHERE id=?", (version_id,)
    ).fetchone()[0] == body


def test_internal_body_nfkc_normalizes_crlf_allows_tab_and_rejects_lone_cr(db):
    from legal_repository import LegalContractError, create_legal_draft

    version_id = create_legal_draft(
        document_type="terms",
        version_code="normalized-v1",
        title="title",
        body_summary="summary",
        body_html="<pre>Ａ\r\nB\tC</pre>",
        effective_at=NOW,
        actor="test-admin",
        now=NOW,
    )
    assert db.execute(
        "SELECT body_html FROM legal_documents WHERE id=?", (version_id,)
    ).fetchone()[0] == "<pre>A\nB\tC</pre>"

    with pytest.raises(LegalContractError, match="body_html_invalid"):
        create_legal_draft(
            document_type="terms",
            version_code="lone-cr-v1",
            title="title",
            body_summary="summary",
            body_html="<p>A\rB</p>",
            effective_at=NOW,
            actor="test-admin",
            now=NOW,
        )


def test_review_rejects_direct_sql_malicious_body_even_with_matching_digest(db):
    from legal_repository import LegalContractError, confirm_legal_review

    version_id = _draft("terms", "sql-malicious-review-v1")
    body = "<p>safe</p><script>alert(1)</script>"
    digest = _raw_digest(
        "terms",
        "sql-malicious-review-v1",
        title="terms title",
        body_summary="terms summary",
        body_html=body,
    )
    db.execute(
        "UPDATE legal_documents SET body_html=?,content_sha256=?,"
        "reviewed_content_sha256=NULL,legal_review_confirmed_at=NULL,"
        "lock_version=lock_version+1 WHERE id=?",
        (body, digest, version_id),
    )
    db.commit()

    with pytest.raises(LegalContractError, match="stored_content_invalid"):
        confirm_legal_review(version_id, 2, "test-admin", NOW)


def test_public_read_rejects_direct_sql_malicious_reviewed_content(client, db):
    version_id = _draft("ai_content_notice", "sql-malicious-public-v1")
    body = "<p>safe</p><script>alert(1)</script>"
    digest = _raw_digest(
        "ai_content_notice",
        "sql-malicious-public-v1",
        title="ai_content_notice title",
        body_summary="ai_content_notice summary",
        body_html=body,
    )
    db.execute(
        "UPDATE legal_documents SET body_html=?,content_sha256=?,lock_version=lock_version+1 "
        "WHERE id=?",
        (body, digest, version_id),
    )
    db.execute(
        "UPDATE legal_documents SET reviewed_content_sha256=content_sha256,"
        "legal_review_confirmed_at=?,updated_at=?,lock_version=lock_version+1 WHERE id=?",
        ("2026-08-31 10:00:00", "2026-08-31 10:00:00", version_id),
    )
    db.execute(
        "UPDATE legal_documents SET status='published',published_at=?,updated_at=?,"
        "lock_version=lock_version+1 WHERE id=?",
        ("2026-08-31 10:00:00", "2026-08-31 10:00:00", version_id),
    )
    db.execute(
        "INSERT INTO active_legal_documents(document_type,legal_document_id) VALUES (?,?)",
        ("ai_content_notice", version_id),
    )
    db.commit()

    assert client.get("/legal/ai_content_notice").status_code == 404
    assert client.get(
        "/legal/ai_content_notice/sql-malicious-public-v1"
    ).status_code == 404


def test_sql_prevents_stale_review_and_published_content_mutation(db):
    version_id, _ = _reviewed()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE legal_documents SET title='tampered',content_sha256=?,lock_version=lock_version+1 "
            "WHERE id=?",
            ("b" * 64, version_id),
        )
    db.rollback()

    version_id = _published("terms", "terms-v1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE legal_documents SET title='tampered' WHERE id=?", (version_id,))
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM legal_documents WHERE id=?", (version_id,))


def test_sql_rejects_unreviewed_publication_and_draft_edits_without_lock_bump(db):
    draft_id = _draft("ai_content_notice", "ai-v1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE legal_documents SET status='published',published_at=?,updated_at=?,"
            "lock_version=lock_version+1 WHERE id=?",
            ("2026-08-31 10:00:00", "2026-08-31 10:00:00", draft_id),
        )
    db.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE legal_documents SET title='changed',content_sha256=? WHERE id=?",
            ("b" * 64, draft_id),
        )


def test_future_version_cannot_publish_and_pointer_is_sole_current_authority(db):
    from legal_repository import LegalContractError, confirm_legal_review, publish_legal_version

    version_id = _draft("terms", "future-v1")
    db.execute(
        "UPDATE legal_documents SET effective_at=?,lock_version=lock_version+1 WHERE id=?",
        ("2026-09-01 10:00:00", version_id),
    )
    db.commit()
    lock = confirm_legal_review(version_id, 2, "test-admin", NOW)
    with pytest.raises(LegalContractError, match="effective_at_future"):
        publish_legal_version(version_id, lock, "test-admin", NOW)
    assert db.execute(
        "SELECT COUNT(*) FROM active_legal_documents WHERE document_type='terms'"
    ).fetchone()[0] == 0


def test_publication_moves_pointer_archives_old_and_writes_governance_audit(db):
    from legal_repository import confirm_legal_review, publish_legal_version

    old_id = _published("privacy", "privacy-v1")
    new_id = _draft("privacy", "privacy-v2")
    lock = confirm_legal_review(new_id, 1, "test-admin", NOW)
    publish_legal_version(new_id, lock, "test-admin", NOW)

    states = {
        row["id"]: row["status"]
        for row in db.execute(
            "SELECT id,status FROM legal_documents WHERE id IN (?,?)", (old_id, new_id)
        )
    }
    assert states == {old_id: "archived", new_id: "published"}
    assert db.execute(
        "SELECT legal_document_id FROM active_legal_documents WHERE document_type='privacy'"
    ).fetchone()[0] == new_id
    assert db.execute(
        "SELECT COUNT(*) FROM governance_audit_events "
        "WHERE action IN ('legal_review_confirmed','legal_version_published')"
    ).fetchone()[0] >= 4


def test_active_pointer_rejects_draft_stale_review_and_still_pointed_archive(db):
    draft_id = _draft("roi_disclaimer", "roi-v1")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO active_legal_documents(document_type,legal_document_id) VALUES (?,?)",
            ("roi_disclaimer", draft_id),
        )
    db.rollback()

    published_id = _published("roi_disclaimer", "roi-v2")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE legal_documents SET status='archived',archived_at=?,updated_at=?,"
            "lock_version=lock_version+1 WHERE id=?",
            ("2026-08-31 10:00:00", "2026-08-31 10:00:00", published_id),
        )


def test_sql_rejects_direct_internal_public_insert_and_future_pointer(db):
    from legal_repository import canonical_legal_digest, confirm_legal_review

    digest = canonical_legal_digest(
        document_type="terms",
        version_code="direct-v1",
        mode="internal",
        title="title",
        body_summary="summary",
        body_html="<p>body</p>",
        external_url=None,
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO legal_documents "
            "(document_type,version_code,mode,title,body_summary,body_html,content_sha256,"
            "reviewed_content_sha256,status,lock_version,legal_review_confirmed_at,"
            "effective_at,published_at,created_at,updated_at) "
            "VALUES ('terms','direct-v1','internal','title','summary','<p>body</p>',?,?,'published',"
            "2,?,'2026-08-31 10:00:00','2026-08-31 10:00:00',?,?)",
            (digest, digest, "2026-08-31 10:00:00", "2026-08-31 10:00:00", "2026-08-31 10:00:00"),
        )
    db.rollback()

    version_id = _draft("terms", "future-direct-v1")
    db.execute(
        "UPDATE legal_documents SET effective_at='2099-01-01 00:00:00',"
        "lock_version=lock_version+1 WHERE id=?",
        (version_id,),
    )
    db.commit()
    lock = confirm_legal_review(version_id, 2, "test-admin", NOW)
    db.execute(
        "UPDATE legal_documents SET status='published',published_at=?,updated_at=?,"
        "lock_version=lock_version+1 WHERE id=? AND lock_version=?",
        ("2026-08-31 10:00:00", "2026-08-31 10:00:00", version_id, lock),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO active_legal_documents(document_type,legal_document_id) VALUES ('terms',?)",
            (version_id,),
        )


def test_assessment_legal_snapshot_is_immutable_but_consent_deletion_remains_allowed(db):
    version_id = _published("privacy", "privacy-snapshot")
    assessment_id = db.execute(
        "INSERT INTO assessments(company_name,created_at) VALUES ('x',?)",
        ("2026-08-31 10:00:00",),
    ).lastrowid
    db.execute(
        "INSERT INTO assessment_legal_versions "
        "(assessment_id,document_type,legal_version_id,version_code,digest) "
        "SELECT ?,document_type,id,version_code,content_sha256 FROM legal_documents WHERE id=?",
        (assessment_id, version_id),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE assessment_legal_versions SET version_code='changed' "
            "WHERE assessment_id=?",
            (assessment_id,),
        )
    db.rollback()

    lead_id = db.execute(
        "INSERT INTO leads(company_name,contact_name,created_at,updated_at) VALUES ('c','n',?,?)",
        ("2026-08-31 10:00:00", "2026-08-31 10:00:00"),
    ).lastrowid
    consent_id = db.execute(
        "INSERT INTO lead_consents(lead_id,policy_version,consented_at,source,identity_hash,legal_version_id) "
        "VALUES (?,?,?,?,?,?)",
        (lead_id, "privacy-snapshot", "2026-08-31 10:00:00", "assessment", "hash", version_id),
    ).lastrowid
    db.execute("DELETE FROM lead_consents WHERE id=?", (consent_id,))
    assert db.execute("SELECT COUNT(*) FROM lead_consents WHERE id=?", (consent_id,)).fetchone()[0] == 0


def test_assessment_snapshot_must_match_referenced_type_version_and_digest(db):
    version_id = _published("privacy", "privacy-exact")
    assessment_id = db.execute(
        "INSERT INTO assessments(company_name,created_at) VALUES ('x',?)",
        ("2026-08-31 10:00:00",),
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO assessment_legal_versions "
            "(assessment_id,document_type,legal_version_id,version_code,digest) "
            "VALUES (?,?,?,?,?)",
            (assessment_id, "terms", version_id, "wrong", "a" * 64),
        )


def test_external_privacy_reconciliation_links_matching_history_and_exact_repeat_is_noop(db):
    from legal_repository import reconcile_external_privacy_reference

    lead_id = db.execute(
        "INSERT INTO leads(company_name,contact_name,created_at,updated_at) VALUES ('c','n',?,?)",
        ("2026-08-31 10:00:00", "2026-08-31 10:00:00"),
    ).lastrowid
    matching = db.execute(
        "INSERT INTO lead_consents(lead_id,policy_version,consented_at,source,identity_hash) "
        "VALUES (?,?,?,?,?)",
        (lead_id, "2026-08-19", "2026-08-31 10:00:00", "assessment", "hash1"),
    ).lastrowid
    other = db.execute(
        "INSERT INTO lead_consents(lead_id,policy_version,consented_at,source,identity_hash) "
        "VALUES (?,?,?,?,?)",
        (lead_id, "old", "2026-08-31 10:00:00", "assessment", "hash2"),
    ).lastrowid
    db.commit()

    version_id = reconcile_external_privacy_reference(
        db, "2026-08-19", "https://legal.example/privacy", NOW
    )
    audit_count = db.execute("SELECT COUNT(*) FROM governance_audit_events").fetchone()[0]
    repeated_id = reconcile_external_privacy_reference(
        db, "2026-08-19", "https://legal.example/privacy", NOW
    )

    assert repeated_id == version_id
    row = db.execute("SELECT * FROM legal_documents WHERE id=?", (version_id,)).fetchone()
    assert row["mode"] == "external_legacy"
    assert row["reviewed_content_sha256"] is None
    assert row["body_html"] is None
    assert db.execute(
        "SELECT legal_version_id FROM lead_consents WHERE id=?", (matching,)
    ).fetchone()[0] == version_id
    assert db.execute(
        "SELECT legal_version_id FROM lead_consents WHERE id=?", (other,)
    ).fetchone()[0] is None
    assert db.execute("SELECT COUNT(*) FROM governance_audit_events").fetchone()[0] == audit_count


def test_external_reconcile_uses_injected_future_clock_not_host_localtime(db):
    from legal_repository import reconcile_external_privacy_reference

    version_id = reconcile_external_privacy_reference(
        db,
        "future-policy-v1",
        "https://legal.example/future-privacy",
        FAR_FUTURE,
    )
    row = db.execute(
        "SELECT d.id,d.effective_at,d.published_at "
        "FROM active_legal_documents a JOIN legal_documents d ON d.id=a.legal_document_id "
        "WHERE a.document_type='privacy'"
    ).fetchone()
    assert tuple(row) == (
        version_id,
        "2099-01-01 10:00:00",
        "2099-01-01 10:00:00",
    )


def test_internal_privacy_switch_archives_external_and_preserves_consent_fk(db):
    from legal_repository import reconcile_external_privacy_reference

    lead_id = db.execute(
        "INSERT INTO leads(company_name,contact_name,created_at,updated_at) "
        "VALUES ('c','n',?,?)",
        ("2026-08-31 10:00:00", "2026-08-31 10:00:00"),
    ).lastrowid
    consent_id = db.execute(
        "INSERT INTO lead_consents(lead_id,policy_version,consented_at,source,identity_hash) "
        "VALUES (?,?,?,?,?)",
        (
            lead_id,
            "legacy-policy-v1",
            "2026-08-31 10:00:00",
            "assessment",
            "identity-hash",
        ),
    ).lastrowid
    db.commit()
    external_id = reconcile_external_privacy_reference(
        db,
        "legacy-policy-v1",
        "https://legal.example/legacy-privacy",
        NOW,
    )
    assert db.execute(
        "SELECT legal_version_id FROM lead_consents WHERE id=?", (consent_id,)
    ).fetchone()[0] == external_id

    internal_id = _published("privacy", "internal-privacy-v1")

    assert db.execute(
        "SELECT legal_document_id FROM active_legal_documents WHERE document_type='privacy'"
    ).fetchone()[0] == internal_id
    assert db.execute(
        "SELECT status FROM legal_documents WHERE id=?", (external_id,)
    ).fetchone()[0] == "archived"
    assert db.execute(
        "SELECT legal_version_id FROM lead_consents WHERE id=?", (consent_id,)
    ).fetchone()[0] == external_id


def test_external_reconcile_version_conflict_fails_closed_without_writes(db):
    from legal_repository import LegalContractError, reconcile_external_privacy_reference

    reconcile_external_privacy_reference(
        db, "2026-08-19", "https://legal.example/privacy", NOW
    )
    before = tuple(
        db.execute(
            "SELECT id,external_url,content_sha256,status FROM legal_documents ORDER BY id"
        ).fetchall()
    )
    audit_before = db.execute("SELECT COUNT(*) FROM governance_audit_events").fetchone()[0]
    with pytest.raises(LegalContractError, match="external_version_conflict"):
        reconcile_external_privacy_reference(
            db, "2026-08-19", "https://legal.example/changed", NOW
        )
    after = tuple(
        db.execute(
            "SELECT id,external_url,content_sha256,status FROM legal_documents ORDER BY id"
        ).fetchall()
    )
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    assert db.execute("SELECT COUNT(*) FROM governance_audit_events").fetchone()[0] == audit_before


def test_external_pointer_does_not_satisfy_internal_active_bundle(db):
    from legal_repository import LegalContractError, load_active_legal_bundle, reconcile_external_privacy_reference

    reconcile_external_privacy_reference(
        db, "2026-08-19", "https://legal.example/privacy", NOW
    )
    with pytest.raises(LegalContractError, match="legal_bundle_not_ready"):
        load_active_legal_bundle(db, NOW)


def test_four_reviewed_internal_pointers_load_without_committing_caller_connection(db):
    from legal_repository import LegalVersionIds, load_active_legal_bundle, load_legal_bundle

    ids = {
        document_type: _published(document_type, f"{document_type}-v1")
        for document_type in ("privacy", "terms", "roi_disclaimer", "ai_content_notice")
    }
    db.execute("INSERT INTO site_config(key,value) VALUES ('caller-pending','keep-local')")

    active = load_active_legal_bundle(db, NOW)
    historical = load_legal_bundle(db, LegalVersionIds(**ids))

    assert active.version_ids == LegalVersionIds(**ids)
    assert historical.version_ids == LegalVersionIds(**ids)
    assert db.in_transaction is True
    db.rollback()
    assert db.execute(
        "SELECT COUNT(*) FROM site_config WHERE key='caller-pending'"
    ).fetchone()[0] == 0


def test_query_filters_exactly_orders_and_clamps_page(db):
    from legal_repository import LegalFilters, query_legal_versions

    _draft("terms", "terms-older")
    _draft("terms", "terms-newer")
    db.execute(
        "UPDATE legal_documents SET updated_at='2026-08-30 10:00:00',"
        "lock_version=lock_version+1 WHERE version_code='terms-older'"
    )
    db.commit()

    page = query_legal_versions(
        LegalFilters(document_type="terms", status="draft"), PageRequest(999, 20)
    )
    assert [row.version_code for row in page.items] == ["terms-newer", "terms-older"]
    assert page.page == 1
    assert page.per_page == 20


def test_public_current_and_version_routes_hide_drafts_and_preserve_history(client, db):
    old_id = _published("terms", "terms-v1")
    _published("terms", "terms-v2")
    _draft("terms", "terms-draft")

    current = client.get("/legal/terms")
    historical = client.get("/legal/terms/terms-v1")
    draft = client.get("/legal/terms/terms-draft")
    unknown = client.get("/legal/terms/missing")

    assert current.status_code == 200
    assert b"terms title" in current.data
    assert historical.status_code == 200
    assert draft.status_code == 404
    assert unknown.status_code == 404
    assert db.execute("SELECT status FROM legal_documents WHERE id=?", (old_id,)).fetchone()[0] == "archived"


def test_external_version_route_redirects_only_to_frozen_url(client, db):
    from legal_repository import reconcile_external_privacy_reference

    reconcile_external_privacy_reference(
        db, "2026-08-19", "https://legal.example/privacy", NOW
    )
    response = client.get("/legal/privacy/2026-08-19")
    assert response.status_code == 302
    assert response.headers["Location"] == "https://legal.example/privacy"


@pytest.mark.parametrize(
    "path",
    [
        "/legal/privacy/bad%20code",
        "/legal/privacy/%2F",
        "/legal/privacy/" + "a" * 65,
        "/legal/unknown/v1",
    ],
)
def test_public_legal_path_rejects_noncanonical_codes(client, path):
    assert client.get(path).status_code == 404


def test_admin_legal_routes_require_auth_csrf_and_emit_no_store(client, admin_client):
    anonymous = client.application.test_client().get("/admin/legal")
    listing = admin_client.get("/admin/legal?type=invalid&status=invalid&per_page=50")
    forbidden = admin_client.post(
        "/admin/legal/new",
        data={
            "document_type": "privacy",
            "version_code": "route-v1",
            "title": "title",
            "body_summary": "summary",
            "body_html": "<p>body</p>",
            "effective_at": "2026-08-31 10:00:00",
        },
    )

    assert anonymous.status_code in {302, 403}
    assert listing.status_code == 200
    assert "no-store" in listing.headers["Cache-Control"]
    assert forbidden.status_code == 403


def test_admin_future_effective_version_is_rejected_at_publish(admin_client):
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW
    created = admin_client.post(
        "/admin/legal/new",
        data={
            "csrf_token": "test-csrf-token",
            "document_type": "privacy",
            "version_code": "future-route-v1",
            "title": "title",
            "body_summary": "summary",
            "body_html": "<p>body</p>",
            "effective_at": "2026-09-01 10:00:00",
        },
    )
    assert created.status_code == 302
    location = created.headers["Location"]
    reviewed = admin_client.post(
        location,
        data={
            "csrf_token": "test-csrf-token",
            "action": "review",
            "expected_lock_version": "1",
        },
    )
    assert reviewed.status_code == 302
    rejected = admin_client.post(
        location,
        data={
            "csrf_token": "test-csrf-token",
            "action": "publish",
            "expected_lock_version": "2",
        },
    )
    assert rejected.status_code == 400
    assert rejected.get_json() == {"error": "effective_at_future"}
