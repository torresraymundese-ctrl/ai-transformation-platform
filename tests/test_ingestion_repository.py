from datetime import datetime
import importlib
import json
from pathlib import Path
import shutil
import sqlite3
from threading import Barrier, Thread

import pytest

from content_clock import SHANGHAI
import migrations
import models


NOW = datetime(2026, 8, 24, 12, 34, 56, tzinfo=SHANGHAI)


def _ingestion_modules():
    contracts = importlib.import_module("ingestion_contracts")
    repository = importlib.import_module("ingestion_repository")
    return contracts, repository


def _item(contracts, *, url, body_html="<p>同一正文</p>"):
    return contracts.FetchedItem(
        source_code="reviewed-source",
        source_name="Reviewed Source",
        url=url,
        title="候选标题",
        summary="经授权摘要",
        body_html=body_html,
        original_published_at=datetime(2026, 8, 23, 9, 0, tzinfo=SHANGHAI),
    )


def test_ingestion_schema_is_appended_after_009_without_publishing_content(db):
    public_before = db.execute(
        "SELECT COUNT(*) FROM content_items WHERE status='published'"
    ).fetchone()[0]
    tables = {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    versions = [
        row[0]
        for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")
    ]

    assert {
        "ingestion_fetch_attempts",
        "ingestion_candidates",
        "governance_audit_events",
    } <= tables
    candidate_columns = {
        row[1] for row in db.execute("PRAGMA table_info(ingestion_candidates)")
    }
    assert candidate_columns == {
        "id",
        "source_code",
        "source_name",
        "canonical_url",
        "content_sha256",
        "title",
        "licensed_summary",
        "body_html",
        "original_published_at",
        "state",
        "rejection_code",
        "rejection_note",
        "lock_version",
        "target_content_id",
        "created_at",
        "updated_at",
    }
    unique_indexes = {
        row[1]
        for row in db.execute("PRAGMA index_list(ingestion_candidates)")
        if row[2]
    }
    assert {
        "unique_ingestion_candidate_canonical_url",
        "unique_ingestion_candidate_content_sha256",
    } <= unique_indexes
    assert versions[-2:] == ["009_case_basis_types", "010_ingestion_operations"]
    assert db.execute("SELECT COUNT(*) FROM ingestion_candidates").fetchone()[0] == 0
    assert (
        db.execute(
            "SELECT COUNT(*) FROM content_items WHERE status='published'"
        ).fetchone()[0]
        == public_before
    )


def test_canonical_url_normalizes_scheme_idna_path_and_tracking_query():
    _, repository = _ingestion_modules()

    assert repository.canonicalize_url(
        "HTTPS://B\u00dcCHER.Example:443/a/../b//c/?utm_source=campaign&z=2&a=1#fragment"
    ) == "https://xn--bcher-kva.example/b/c/?a=1&z=2"


def test_canonical_url_normalizes_percent_triplets_without_decoding_reserved_path_bytes():
    _, repository = _ingestion_modules()

    percent = repository.canonicalize_url("https://example.com/a%25b")
    encoded_slash = repository.canonicalize_url("https://example.com/a%2fb/%7euser")
    literal_slash = repository.canonicalize_url("https://example.com/a/b/~user")

    assert percent == "https://example.com/a%25b"
    assert encoded_slash == "https://example.com/a%2Fb/~user"
    assert encoded_slash != literal_slash
    assert repository.canonicalize_url(percent) == percent
    assert repository.canonicalize_url(encoded_slash) == encoded_slash


def test_encoded_slash_and_literal_separator_have_distinct_url_dedupe_keys(db):
    contracts, repository = _ingestion_modules()
    encoded = _item(
        contracts, url="https://example.com/a%2fb", body_html="encoded-content"
    )
    literal = _item(
        contracts, url="https://example.com/a/b", body_html="literal-content"
    )
    encoded_hex_variant = _item(
        contracts,
        url="https://example.com/a%2Fb#fragment",
        body_html="third-content",
    )

    first = repository.store_candidates((encoded, literal), NOW)
    repeated = repository.store_candidates((encoded_hex_variant,), NOW)

    assert len(first.created_ids) == 2
    assert first.deduplicated == 0
    assert repeated.created_ids == ()
    assert repeated.deduplicated == 1


def test_store_candidates_deduplicates_canonical_url_and_content_hash(db):
    contracts, repository = _ingestion_modules()
    fetched = _item(
        contracts,
        url="https://Example.com/articles/one?a=1&utm_medium=email",
    )
    tracking_variant = _item(
        contracts,
        url="https://example.com/articles/one?utm_source=other&a=1#section",
        body_html="<p>不同正文</p>",
    )
    same_body_other_url = _item(
        contracts,
        url="https://example.com/articles/two",
    )

    first = repository.store_candidates((fetched,), now=NOW)
    second = repository.store_candidates((tracking_variant, same_body_other_url), now=NOW)

    assert first.created_ids
    assert second.created_ids == ()
    assert second.deduplicated == 2


def test_content_hash_deduplicates_nfkc_and_whitespace_equivalent_content(db):
    contracts, repository = _ingestion_modules()
    first = contracts.FetchedItem(
        source_code="reviewed-source",
        source_name="Reviewed Source",
        url="https://example.com/normalized-one",
        title="ABC",
        summary="Licensed summary",
        body_html="<p>Body text</p>",
        original_published_at=None,
    )
    equivalent = contracts.FetchedItem(
        source_code="reviewed-source",
        source_name="Reviewed\u3000Source",
        url="https://example.com/normalized-two",
        title="\uff21\uff22\uff23",
        summary="\uff2c\uff49\uff43\uff45\uff4e\uff53\uff45\uff44\u3000\uff53\uff55\uff4d\uff4d\uff41\uff52\uff59",
        body_html="<p>\n  \uff22\uff4f\uff44\uff59   \uff54\uff45\uff58\uff54\t</p>",
        original_published_at=None,
    )

    assert repository.normalized_content_sha256(first) == (
        repository.normalized_content_sha256(equivalent)
    )
    assert repository.store_candidates((first,), NOW).created_ids
    result = repository.store_candidates((equivalent,), NOW)
    assert result.created_ids == ()
    assert result.deduplicated == 1


@pytest.mark.parametrize(
    "source_code",
    ("Uppercase", "has space", "-leading", "a" * 65, ""),
)
def test_fetched_item_rejects_unbounded_or_non_lowercase_source_codes(source_code):
    contracts, _ = _ingestion_modules()

    with pytest.raises(contracts.IngestionContractError, match="source_code_invalid"):
        contracts.FetchedItem(
            source_code=source_code,
            source_name="Reviewed Source",
            url="https://example.com/item",
            title="Title",
            summary="Licensed summary",
            body_html="<p>Body</p>",
            original_published_at=None,
        )


@pytest.mark.parametrize(
    "url",
    (
        "ftp://example.com/item",
        "https://user:secret@example.com/item",
        "https://example.com:444/item",
        "https://example.com/%zz",
        " https://example.com/item",
    ),
)
def test_canonical_url_rejects_unsafe_authority_or_syntax(url):
    contracts, repository = _ingestion_modules()

    with pytest.raises(contracts.IngestionContractError):
        repository.canonicalize_url(url)


def test_canonical_url_rejects_values_over_storage_bound_before_sqlite(db):
    contracts, repository = _ingestion_modules()
    overlong_url = "https://example.com/" + ("a" * 2048)

    with pytest.raises(contracts.IngestionContractError, match="url_invalid"):
        repository.store_candidates(
            (_item(contracts, url=overlong_url, body_html="overlong"),), NOW
        )

    assert db.execute("SELECT COUNT(*) FROM ingestion_candidates").fetchone()[0] == 0


def test_store_candidate_sanitizes_body_uses_shanghai_time_and_commits_owned_connection(db):
    contracts, repository = _ingestion_modules()
    item = _item(
        contracts,
        url="https://example.com/time",
        body_html="<script>secret()</script><p onclick='bad()'>允许正文</p>",
    )

    result = repository.store_candidates((item,), now=NOW)

    assert db.in_transaction is False
    candidate = repository.load_candidate(result.created_ids[0])
    assert candidate.body_html == "<p>允许正文</p>"
    assert candidate.created_at == NOW
    assert candidate.updated_at == NOW
    assert candidate.original_published_at == datetime(
        2026, 8, 23, 9, 0, tzinfo=SHANGHAI
    )
    assert candidate.state == "fetched"
    assert candidate.lock_version == 1
    assert len(candidate.content_sha256) == 64
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE id=?", (candidate.target_content_id,)
    ).fetchone()[0] == 0
    assert repository.load_candidate(result.created_ids[0]) == candidate
    assert repository.load_candidate(999999) is None


def test_approved_repository_interfaces_accept_positional_now(db):
    contracts, repository = _ingestion_modules()

    candidate_id = repository.store_candidates(
        (_item(contracts, url="https://example.com/positional-now"),), NOW
    ).created_ids[0]
    repository.mark_candidate_pending(db, candidate_id, 1, NOW)

    assert db.execute(
        "SELECT state FROM ingestion_candidates WHERE id=?", (candidate_id,)
    ).fetchone()[0] == "pending_review"


def test_store_candidates_rejects_naive_business_time_without_writes(db):
    contracts, repository = _ingestion_modules()
    item = _item(contracts, url="https://example.com/naive")

    with pytest.raises(ValueError, match="timezone-aware"):
        repository.store_candidates(
            (item,), now=datetime(2026, 8, 24, 12, 34, 56)
        )

    assert db.execute("SELECT COUNT(*) FROM ingestion_candidates").fetchone()[0] == 0


def test_store_candidates_prevalidates_the_whole_batch_before_any_write(db):
    contracts, repository = _ingestion_modules()
    valid = _item(contracts, url="https://example.com/valid-first", body_html="one")
    invalid = _item(contracts, url="https://example.com/%zz", body_html="two")

    with pytest.raises(contracts.IngestionContractError, match="url_invalid"):
        repository.store_candidates((valid, invalid), now=NOW)

    assert db.execute("SELECT COUNT(*) FROM ingestion_candidates").fetchone()[0] == 0


def test_failed_fetch_attempt_is_separate_and_contains_no_remote_payload(db):
    _, repository = _ingestion_modules()

    attempt_id = repository.record_fetch_attempt(
        db,
        source_code="reviewed-source",
        source_name="Reviewed Source",
        outcome_code="failed",
        error_code="network_failure",
        fetched_count=0,
        started_at=NOW,
        completed_at=NOW,
    )

    row = db.execute(
        "SELECT * FROM ingestion_fetch_attempts WHERE id=?", (attempt_id,)
    ).fetchone()
    assert tuple(row[key] for key in (
        "source_code", "source_name", "outcome_code", "error_code",
        "fetched_count", "started_at", "completed_at", "created_at",
    )) == (
        "reviewed-source", "Reviewed Source", "failed", "network_failure", 0,
        "2026-08-24 12:34:56", "2026-08-24 12:34:56",
        "2026-08-24 12:34:56",
    )
    assert not {"url", "body_html", "response_body"}.intersection(row.keys())
    assert db.execute("SELECT COUNT(*) FROM ingestion_candidates").fetchone()[0] == 0
    assert db.in_transaction is True


def test_successful_fetch_attempt_records_only_count_and_fixed_metadata(db):
    _, repository = _ingestion_modules()

    attempt_id = repository.record_fetch_attempt(
        db,
        source_code="reviewed-source",
        source_name="Reviewed Source",
        outcome_code="succeeded",
        error_code=None,
        fetched_count=2,
        started_at=NOW,
        completed_at=NOW,
    )

    row = db.execute(
        "SELECT outcome_code,error_code,fetched_count FROM ingestion_fetch_attempts "
        "WHERE id=?",
        (attempt_id,),
    ).fetchone()
    assert tuple(row) == ("succeeded", None, 2)
    assert db.execute("SELECT COUNT(*) FROM ingestion_candidates").fetchone()[0] == 0
    assert db.in_transaction is True


def test_mark_pending_enforces_exact_state_and_optimistic_lock(db):
    contracts, repository = _ingestion_modules()
    candidate_id = repository.store_candidates(
        (_item(contracts, url="https://example.com/pending"),), now=NOW
    ).created_ids[0]

    repository.mark_candidate_pending(db, candidate_id, 1, now=NOW)
    candidate = db.execute(
        "SELECT state,lock_version FROM ingestion_candidates WHERE id=?",
        (candidate_id,),
    ).fetchone()
    assert tuple(candidate) == ("pending_review", 2)

    with pytest.raises(repository.IngestionConflictError) as stale:
        repository.mark_candidate_pending(db, candidate_id, 1, now=NOW)
    assert stale.value.code == "candidate_conflict"
    assert db.execute(
        "SELECT lock_version FROM ingestion_candidates WHERE id=?", (candidate_id,)
    ).fetchone()[0] == 2


def test_database_enforces_candidate_transition_graph_and_fixed_rejection_codes(db):
    contracts, repository = _ingestion_modules()
    accepted_id, rejected_id = repository.store_candidates(
        (
            _item(contracts, url="https://example.com/accepted", body_html="accepted"),
            _item(contracts, url="https://example.com/rejected", body_html="rejected"),
        ),
        now=NOW,
    ).created_ids
    group_id = db.execute(
        "INSERT INTO content_groups "
        "(entry_type,canonical_slug,created_at,updated_at) VALUES (?,?,?,?)",
        ("resource", "accepted-target", "2026-08-24 12:34:56", "2026-08-24 12:34:56"),
    ).lastrowid
    target_id = db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
        "seo_description,status,lock_version,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            group_id, "resource", 1, "accepted-target", "Target", "Summary",
            "Target SEO", "Target description", "draft", 1,
            "2026-08-24 12:34:56", "2026-08-24 12:34:56",
        ),
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError, match="invalid ingestion candidate transition"):
        db.execute(
            "UPDATE ingestion_candidates SET state='accepted',target_content_id=? "
            "WHERE id=?",
            (target_id, accepted_id),
        )

    repository.mark_candidate_pending(db, accepted_id, 1, now=NOW)
    db.execute(
        "UPDATE ingestion_candidates SET state='accepted',target_content_id=?,"
        "lock_version=lock_version+1,updated_at=? WHERE id=?",
        (target_id, "2026-08-24 12:34:56", accepted_id),
    )
    with pytest.raises(sqlite3.IntegrityError, match="invalid ingestion candidate transition"):
        db.execute(
            "UPDATE ingestion_candidates SET state='rejected',target_content_id=NULL,"
            "rejection_code='irrelevant' WHERE id=?",
            (accepted_id,),
        )

    repository.mark_candidate_pending(db, rejected_id, 1, now=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE ingestion_candidates SET state='rejected',"
            "rejection_code='free_form_reason' WHERE id=?",
            (rejected_id,),
        )
    db.execute(
        "UPDATE ingestion_candidates SET state='rejected',rejection_code='irrelevant',"
        "lock_version=lock_version+1,updated_at=? WHERE id=?",
        ("2026-08-24 12:34:56", rejected_id),
    )
    assert db.execute(
        "SELECT state,rejection_code FROM ingestion_candidates WHERE id=?",
        (rejected_id,),
    ).fetchone()[:] == ("rejected", "irrelevant")


@pytest.mark.parametrize(
    ("state", "lock_version", "rejection_code", "needs_target"),
    (
        ("pending_review", 1, None, False),
        ("fetched", 2, None, False),
        ("accepted", 1, None, True),
        ("rejected", 1, "irrelevant", False),
    ),
)
def test_database_requires_every_candidate_insert_to_start_fetched(
    db, state, lock_version, rejection_code, needs_target
):
    group_id = db.execute(
        "INSERT INTO content_groups "
        "(entry_type,canonical_slug,created_at,updated_at) VALUES (?,?,?,?)",
        (
            "resource",
            f"initial-{state}-{lock_version}",
            "2026-08-24 12:34:56",
            "2026-08-24 12:34:56",
        ),
    ).lastrowid
    target_id = db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
        "seo_description,status,lock_version,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            group_id,
            "resource",
            1,
            f"initial-{state}-{lock_version}",
            "Target",
            "Summary",
            "Target SEO",
            "Target description",
            "draft",
            1,
            "2026-08-24 12:34:56",
            "2026-08-24 12:34:56",
        ),
    ).lastrowid

    with pytest.raises(
        sqlite3.IntegrityError, match="invalid ingestion candidate initial state"
    ):
        db.execute(
            "INSERT INTO ingestion_candidates "
            "(source_code,source_name,canonical_url,content_sha256,title,"
            "licensed_summary,body_html,original_published_at,state,rejection_code,"
            "lock_version,target_content_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "reviewed-source",
                "Reviewed Source",
                f"https://example.com/initial-{state}-{lock_version}",
                (f"{state}-{lock_version}".encode("utf-8").hex() + ("0" * 64))[:64],
                "Candidate",
                "Summary",
                None,
                None,
                state,
                rejection_code,
                lock_version,
                target_id if needs_target else None,
                "2026-08-24 12:34:56",
                "2026-08-24 12:34:56",
            ),
        )


def _concurrent_store(barrier, item, results, errors):
    _, repository = _ingestion_modules()
    try:
        barrier.wait()
        result = repository.store_candidates((item,), now=NOW)
        results.append(result)
    except Exception as error:  # pragma: no cover - asserted through the shared list
        errors.append(error)


@pytest.mark.parametrize("dedupe_axis", ("url", "content"))
def test_concurrent_candidate_insert_has_one_winner(tmp_path, monkeypatch, dedupe_axis):
    database_path = tmp_path / f"concurrent-{dedupe_axis}.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        migrations.apply_migrations(connection)
    finally:
        connection.close()
    monkeypatch.setattr(models, "DB_PATH", str(database_path))
    contracts, _ = _ingestion_modules()
    first = _item(contracts, url="https://example.com/concurrent/one", body_html="one")
    second = _item(
        contracts,
        url=(
            "https://example.com/concurrent/one?utm_source=retry"
            if dedupe_axis == "url"
            else "https://example.com/concurrent/two"
        ),
        body_html="two" if dedupe_axis == "url" else "one",
    )
    barrier = Barrier(2)
    results = []
    errors = []
    threads = [
        Thread(
            target=_concurrent_store,
            args=(barrier, item, results, errors),
        )
        for item in (first, second)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert sum(len(result.created_ids) for result in results) == 1
    assert sum(result.deduplicated for result in results) == 1


@pytest.mark.parametrize(
    "forbidden_key",
    ("body_html", "source_url", "filename", "contact_email", "search_text", "BoDy_HtMl"),
)
def test_governance_audit_rejects_sensitive_or_free_form_metadata(db, forbidden_key):
    contracts, repository = _ingestion_modules()

    with pytest.raises(contracts.IngestionContractError, match="audit_metadata_invalid"):
        repository.write_governance_audit_event(
            db,
            action="ingestion_rejected",
            target_type="ingestion_candidate",
            target_id=1,
            actor="test-admin",
            metadata={forbidden_key: "must-not-be-stored"},
            now=NOW,
        )

    with pytest.raises(sqlite3.IntegrityError, match="audit metadata contains forbidden fields"):
        db.execute(
            "INSERT INTO governance_audit_events "
            "(action,target_type,target_id,actor,metadata_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "ingestion_rejected", "ingestion_candidate", 1, "test-admin",
                '{"' + forbidden_key + '":"must-not-be-stored"}',
                "2026-08-24 12:34:56",
            ),
        )

    assert db.execute("SELECT COUNT(*) FROM governance_audit_events").fetchone()[0] == 0


@pytest.mark.parametrize(
    "sensitive_value",
    (
        "person@example.com",
        "report.pdf",
        "13800000000",
        "example.com/private",
        "任意自由文本",
    ),
)
def test_governance_audit_rejects_sensitive_values_under_innocuous_keys(
    db, sensitive_value
):
    contracts, repository = _ingestion_modules()

    with pytest.raises(contracts.IngestionContractError, match="audit_metadata_invalid"):
        repository.write_governance_audit_event(
            db,
            action="ingestion_rejected",
            target_type="ingestion_candidate",
            target_id=1,
            actor="test-admin",
            metadata={"detail": sensitive_value},
            now=NOW,
        )
    with pytest.raises(sqlite3.IntegrityError, match="audit metadata contains forbidden fields"):
        db.execute(
            "INSERT INTO governance_audit_events "
            "(action,target_type,target_id,actor,metadata_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "ingestion_rejected",
                "ingestion_candidate",
                1,
                "test-admin",
                '{"detail":' + json.dumps(sensitive_value, ensure_ascii=False) + '}',
                "2026-08-24 12:34:56",
            ),
        )


def test_governance_audit_rejects_nested_forbidden_keys(db):
    contracts, repository = _ingestion_modules()

    with pytest.raises(contracts.IngestionContractError, match="audit_metadata_invalid"):
        repository.write_governance_audit_event(
            db,
            action="ingestion_rejected",
            target_type="ingestion_candidate",
            target_id=1,
            actor="test-admin",
            metadata={"safe": {"BoDy_HtMl": "hidden"}},
            now=NOW,
        )
    with pytest.raises(sqlite3.IntegrityError, match="audit metadata contains forbidden fields"):
        db.execute(
            "INSERT INTO governance_audit_events "
            "(action,target_type,target_id,actor,metadata_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "ingestion_rejected",
                "ingestion_candidate",
                1,
                "test-admin",
                '{"safe":{"BoDy_HtMl":"hidden"}}',
                "2026-08-24 12:34:56",
            ),
        )


def test_governance_audit_metadata_privacy_cannot_be_bypassed_by_direct_update(db):
    audit_id = db.execute(
        "INSERT INTO governance_audit_events "
        "(action,target_type,target_id,actor,metadata_json,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            "ingestion_rejected",
            "ingestion_candidate",
            1,
            "test-admin",
            '{"reason_code":"irrelevant"}',
            "2026-08-24 12:34:56",
        ),
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError, match="audit metadata contains forbidden fields"):
        db.execute(
            "UPDATE governance_audit_events SET metadata_json=? WHERE id=?",
            ('{"detail":"person@example.com"}', audit_id),
        )


@pytest.mark.parametrize(
    "invalid_actor",
    (
        "https://admin.example",
        "admin@example.com",
        "13800000000",
        "report.pdf",
        "admin user",
        "任意管理员",
        "a" * 65,
    ),
)
def test_governance_audit_rejects_sensitive_or_non_code_actor_on_insert_and_update(
    db, invalid_actor
):
    contracts, repository = _ingestion_modules()

    with pytest.raises(contracts.IngestionContractError, match="audit_actor_invalid"):
        repository.write_governance_audit_event(
            db,
            action="ingestion_rejected",
            target_type="ingestion_candidate",
            target_id=1,
            actor=invalid_actor,
            metadata={"reason_code": "irrelevant"},
            now=NOW,
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO governance_audit_events "
            "(action,target_type,target_id,actor,metadata_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "ingestion_rejected",
                "ingestion_candidate",
                1,
                invalid_actor,
                '{"reason_code":"irrelevant"}',
                "2026-08-24 12:34:56",
            ),
        )
    audit_id = db.execute(
        "INSERT INTO governance_audit_events "
        "(action,target_type,target_id,actor,metadata_json,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            "ingestion_rejected",
            "ingestion_candidate",
            1,
            "test-admin",
            '{"reason_code":"irrelevant"}',
            "2026-08-24 12:34:56",
        ),
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE governance_audit_events SET actor=? WHERE id=?",
            (invalid_actor, audit_id),
        )


@pytest.mark.parametrize("valid_actor", ("Admin", "ops.admin"))
def test_governance_audit_accepts_shared_admin_actor_via_python_api(db, valid_actor):
    _, repository = _ingestion_modules()

    audit_id = repository.write_governance_audit_event(
        db,
        action="ingestion_rejected",
        target_type="ingestion_candidate",
        target_id=1,
        actor=valid_actor,
        metadata={"reason_code": "irrelevant"},
        now=NOW,
    )

    assert db.execute(
        "SELECT actor FROM governance_audit_events WHERE id=?", (audit_id,)
    ).fetchone()[0] == valid_actor


@pytest.mark.parametrize("valid_actor", ("Admin", "ops.admin"))
def test_governance_audit_accepts_shared_admin_actor_via_direct_insert(
    db, valid_actor
):
    audit_id = db.execute(
        "INSERT INTO governance_audit_events "
        "(action,target_type,target_id,actor,metadata_json,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            "ingestion_rejected",
            "ingestion_candidate",
            1,
            valid_actor,
            '{"reason_code":"irrelevant"}',
            "2026-08-24 12:34:56",
        ),
    ).lastrowid

    assert db.execute(
        "SELECT actor FROM governance_audit_events WHERE id=?", (audit_id,)
    ).fetchone()[0] == valid_actor


@pytest.mark.parametrize("valid_actor", ("Admin", "ops.admin"))
def test_governance_audit_accepts_shared_admin_actor_via_direct_update(
    db, valid_actor
):
    audit_id = db.execute(
        "INSERT INTO governance_audit_events "
        "(action,target_type,target_id,actor,metadata_json,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            "ingestion_rejected",
            "ingestion_candidate",
            1,
            "test-admin",
            '{"reason_code":"irrelevant"}',
            "2026-08-24 12:34:56",
        ),
    ).lastrowid

    db.execute(
        "UPDATE governance_audit_events SET actor=? WHERE id=?",
        (valid_actor, audit_id),
    )
    assert db.execute(
        "SELECT actor FROM governance_audit_events WHERE id=?", (audit_id,)
    ).fetchone()[0] == valid_actor


def test_governance_audit_python_api_rejects_embedded_nul_actor(db):
    contracts, repository = _ingestion_modules()

    with pytest.raises(contracts.IngestionContractError, match="audit_actor_invalid"):
        repository.write_governance_audit_event(
            db,
            action="ingestion_rejected",
            target_type="ingestion_candidate",
            target_id=1,
            actor="Admin\x00evil",
            metadata={"reason_code": "irrelevant"},
            now=NOW,
        )


@pytest.mark.parametrize(
    "invalid_actor",
    ("Admin\x00evil", sqlite3.Binary(b"Admin\x00evil")),
    ids=("nul-text", "nul-blob"),
)
def test_governance_audit_direct_insert_rejects_nul_or_blob_actor(
    db, invalid_actor
):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO governance_audit_events "
            "(action,target_type,target_id,actor,metadata_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "ingestion_rejected",
                "ingestion_candidate",
                1,
                invalid_actor,
                '{"reason_code":"irrelevant"}',
                "2026-08-24 12:34:56",
            ),
        )


@pytest.mark.parametrize(
    "invalid_actor",
    ("Admin\x00evil", sqlite3.Binary(b"Admin\x00evil")),
    ids=("nul-text", "nul-blob"),
)
def test_governance_audit_direct_update_rejects_nul_or_blob_actor(
    db, invalid_actor
):
    audit_id = db.execute(
        "INSERT INTO governance_audit_events "
        "(action,target_type,target_id,actor,metadata_json,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            "ingestion_rejected",
            "ingestion_candidate",
            1,
            "test-admin",
            '{"reason_code":"irrelevant"}',
            "2026-08-24 12:34:56",
        ),
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE governance_audit_events SET actor=? WHERE id=?",
            (invalid_actor, audit_id),
        )


def test_governance_audit_writes_only_bounded_structured_metadata_without_commit(db):
    _, repository = _ingestion_modules()

    audit_id = repository.write_governance_audit_event(
        db,
        action="ingestion_rejected",
        target_type="ingestion_candidate",
        target_id=7,
        actor="test-admin",
        metadata={"reason_code": "irrelevant", "target_content_id": 11},
        now=NOW,
    )

    row = db.execute(
        "SELECT action,target_type,target_id,actor,metadata_json,created_at "
        "FROM governance_audit_events WHERE id=?",
        (audit_id,),
    ).fetchone()
    assert tuple(row) == (
        "ingestion_rejected",
        "ingestion_candidate",
        7,
        "test-admin",
        '{"reason_code":"irrelevant","target_content_id":11}',
        "2026-08-24 12:34:56",
    )
    assert db.in_transaction is True


def test_migration_upgrades_exact_001_through_009_and_preserves_sentinel(
    tmp_path, monkeypatch
):
    prior_dir = tmp_path / "migrations-through-009"
    prior_dir.mkdir()
    project_root = Path(__file__).resolve().parents[1]
    for migration_path in sorted((project_root / "migrations").glob("00[1-9]_*.sql")):
        shutil.copy2(migration_path, prior_dir / migration_path.name)
    database_path = tmp_path / "through-009.db"
    connection = sqlite3.connect(database_path)
    try:
        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", prior_dir)
        migrations.apply_migrations(connection)
        connection.execute(
            "INSERT INTO site_config (key,value) VALUES (?,?)",
            ("task13-sentinel", "keep-me"),
        )
        connection.commit()

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", project_root / "migrations")
        migrations.apply_migrations(connection)
        migrations.apply_migrations(connection)
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        sentinel = connection.execute(
            "SELECT value FROM site_config WHERE key='task13-sentinel'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert versions == [
        "001_initial",
        "002_security",
        "003_v2_catalog",
        "004_v2_assessment_leads",
        "005_v2_appointments_analytics",
        "006_content_catalog",
        "007_scenario_public_inputs",
        "008_service_content_maturity",
        "009_case_basis_types",
        "010_ingestion_operations",
    ]
    assert len({version[:3] for version in versions}) == len(versions)
    assert sentinel == "keep-me"
