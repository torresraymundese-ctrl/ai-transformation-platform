import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
import hashlib
import sqlite3
import subprocess
import sys

import pytest

import legacy_content_migration as migration
import manage


NOW = "2026-08-24 15:16:17"
KNOWN_SERVICE_CODES = (
    "foundation_workshop",
    "knowledge_assistant_pilot",
    "customer_growth_pilot",
    "workflow_automation",
    "data_insight",
    "industry_integration",
)


def _item(items, source_table, source_id):
    return next(
        item
        for item in items
        if item.source_table == source_table and item.source_id == source_id
    )


def _legacy_counts(db):
    return {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("services", "cases", "articles", "announcements")
    }


def _review_row(db, source_table, source_id):
    return db.execute(
        "SELECT * FROM legacy_content_reviews "
        "WHERE source_table=? AND source_id=?",
        (source_table, source_id),
    ).fetchone()


def test_review_item_is_frozen_and_six_v2_services_have_literal_keep_targets(db):
    items = migration.inventory_legacy_content(db)
    service_items = {
        item.target_group: item
        for item in items
        if item.source_table == "services" and item.target_group is not None
    }

    assert tuple(sorted(service_items)) == tuple(sorted(KNOWN_SERVICE_CODES))
    for code in KNOWN_SERVICE_CODES:
        item = service_items[code]
        assert (item.action, item.reason_code, item.target_type) == (
            "keep",
            "service_code_matches_v2",
            "service",
        )
        assert item.source_state == "unchecked"
        assert item.required_confirmations == (
            "service_scope_review",
            "deliverables_review",
        )
        assert item.target_preview == {
            "entry_type": "service",
            "service_code": code,
            "title": item.title_summary,
            "status": "draft",
            "publishable": False,
        }

    with pytest.raises(FrozenInstanceError):
        service_items[KNOWN_SERVICE_CODES[0]].reason_code = "changed"


def test_unmappable_service_is_archived_with_stable_reason_and_no_target(db):
    source_id = db.execute(
        "INSERT INTO services (name,tier,code) VALUES (?,?,?)",
        ("无法映射的服务", "legacy", "not_a_v2_service"),
    ).lastrowid
    db.commit()

    item = _item(migration.inventory_legacy_content(db), "services", source_id)

    assert (item.action, item.reason_code) == ("archive", "service_unmappable")
    assert (item.target_type, item.target_group, item.target_preview) == (
        None,
        None,
        None,
    )
    assert item.required_confirmations == ()


def test_unverified_case_is_never_publishable_or_deleted(db):
    case_id = db.execute(
        "INSERT INTO cases (title,industry,result) VALUES (?,?,?)",
        ("某企业提升 99%", "制造业", "人员成本下降 99%"),
    ).lastrowid
    db.commit()

    item = _item(migration.inventory_legacy_content(db), "cases", case_id)

    assert (item.action, item.reason_code) == (
        "delete_later",
        "case_source_or_metric_unverified",
    )
    assert item.required_confirmations == (
        "source_or_authorization",
        "metric_basis",
        "privacy_review",
    )
    assert item.target_preview == {
        "entry_type": "case",
        "title": "某企业提升 99%",
        "status": "draft",
        "publishable": False,
    }
    assert db.execute("SELECT title FROM cases WHERE id=?", (case_id,)).fetchone()


def test_article_classification_fails_closed_and_redacts_url_secrets(db):
    valid_id = db.execute(
        "INSERT INTO articles (title,source,source_url,status) VALUES (?,?,?,?)",
        (
            "公开来源文章",
            "公开来源",
            "https://Example.COM/path/to/page?token=QUERY-SECRET#fragment",
            "published",
        ),
    ).lastrowid
    invalid_id = db.execute(
        "INSERT INTO articles (title,source,source_url,status) VALUES (?,?,?,?)",
        ("无效来源文章", "本地", "file:///opt/platform/.env", "published"),
    ).lastrowid
    missing_id = db.execute(
        "INSERT INTO articles (title,source,source_url,status) VALUES (?,?,?,?)",
        ("缺少来源文章", "本地", None, "published"),
    ).lastrowid
    db.commit()

    items = migration.inventory_legacy_content(db)
    valid = _item(items, "articles", valid_id)
    invalid = _item(items, "articles", invalid_id)
    missing = _item(items, "articles", missing_id)

    assert (valid.action, valid.reason_code, valid.source_state) == (
        "clean",
        "article_source_requires_check",
        "unchecked",
    )
    assert valid.required_confirmations == (
        "source_reachable",
        "content_valid",
        "summary_suitable",
        "copyright_review",
    )
    assert valid.target_preview == {
        "entry_type": "resource",
        "resource_type": "article",
        "title": "公开来源文章",
        "status": "draft",
        "source_url_display": "https://example.com/path/to/page",
        "publishable": False,
    }
    assert (invalid.action, invalid.reason_code, invalid.target_preview) == (
        "archive",
        "article_source_url_invalid",
        None,
    )
    assert (missing.action, missing.reason_code, missing.target_preview) == (
        "archive",
        "article_source_url_missing",
        None,
    )
    serialized = migration.items_to_jsonl((valid, invalid, missing))
    assert "QUERY-SECRET" not in serialized
    assert "fragment" not in serialized
    assert "file:///opt/platform/.env" not in serialized


def test_announcement_never_infers_validity_from_age(db):
    announcement_id = db.execute(
        "INSERT INTO announcements (title,content_html,status,created_at) "
        "VALUES (?,?,?,?)",
        ("十年前仍标记发布的公告", "<p>正文</p>", "published", "2016-01-01 00:00:00"),
    ).lastrowid
    db.commit()

    item = _item(
        migration.inventory_legacy_content(db), "announcements", announcement_id
    )

    assert (item.action, item.reason_code, item.target_type) == (
        "archive",
        "announcement_validity_unconfirmed",
        "announcement",
    )
    assert item.required_confirmations == ("valid_from", "valid_until")
    assert item.target_preview == {
        "entry_type": "announcement",
        "title": "十年前仍标记发布的公告",
        "status": "draft",
        "valid_from": None,
        "valid_until": None,
        "publishable": False,
    }


def test_inventory_is_deterministic_ordered_and_checksum_changes_with_source(db):
    article_id = db.execute(
        "INSERT INTO articles (title,source,source_url) VALUES (?,?,?)",
        ("校验和文章", "来源", "https://example.com/a"),
    ).lastrowid
    db.commit()

    first = migration.inventory_legacy_content(db)
    second = migration.inventory_legacy_content(db)

    assert first == second
    assert [(item.source_table, item.source_id) for item in first] == sorted(
        (item.source_table, item.source_id) for item in first
    )
    old_checksum = _item(first, "articles", article_id).source_checksum
    assert len(old_checksum) == 64
    assert set(old_checksum) <= set("0123456789abcdef")

    db.execute("UPDATE articles SET summary=? WHERE id=?", ("新摘要", article_id))
    db.commit()
    new_checksum = _item(
        migration.inventory_legacy_content(db), "articles", article_id
    ).source_checksum
    assert new_checksum != old_checksum


def test_record_only_writes_review_rows_in_one_transaction(db, monkeypatch):
    monkeypatch.setattr(migration, "current_shanghai_datetime", lambda: datetime(2026, 8, 24, 15, 16, 17))
    before = _legacy_counts(db)
    before_target = db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
    items = migration.inventory_legacy_content(db)

    count = migration.record_legacy_inventory(db, items)

    assert count == len(items)
    assert _legacy_counts(db) == before
    assert db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == before_target
    assert db.execute("SELECT COUNT(*) FROM legacy_content_reviews").fetchone()[0] == len(items)
    assert {row[0] for row in db.execute("SELECT created_at FROM legacy_content_reviews")} == {NOW}

    invalid = replace(items[0], source_table="site_config")
    with pytest.raises(ValueError, match="source_table"):
        migration.record_legacy_inventory(db, (items[0], invalid))
    assert db.execute("SELECT COUNT(*) FROM legacy_content_reviews").fetchone()[0] == len(items)


def test_same_checksum_refreshes_preview_without_overwriting_decision_or_check(db, monkeypatch):
    monkeypatch.setattr(migration, "current_shanghai_datetime", lambda: datetime(2026, 8, 24, 15, 16, 17))
    article_id = db.execute(
        "INSERT INTO articles (title,source,source_url) VALUES (?,?,?)",
        ("待复核文章", "来源", "https://example.com/review"),
    ).lastrowid
    db.commit()
    original = _item(migration.inventory_legacy_content(db), "articles", article_id)
    migration.record_legacy_inventory(db, (original,))
    db.execute(
        "UPDATE legacy_content_reviews SET "
        "decision_action='clean', decision_at='2026-08-24 10:00:00', "
        "decision_source_checksum=source_checksum, source_state='reachable', "
        "source_check_code='https_ok', source_checked_at='2026-08-24 10:01:00', "
        "source_check_expires_at='2026-08-31 10:01:00', "
        "check_source_checksum=source_checksum "
        "WHERE source_table='articles' AND source_id=?",
        (article_id,),
    )
    db.commit()
    refreshed = replace(
        original,
        title_summary="刷新后的派生摘要",
        target_preview={"entry_type": "resource", "publishable": False},
    )

    migration.record_legacy_inventory(db, (refreshed,))
    row = _review_row(db, "articles", article_id)

    assert row["title_summary"] == "刷新后的派生摘要"
    assert json.loads(row["target_preview_json"]) == {
        "entry_type": "resource",
        "publishable": False,
    }
    assert (
        row["decision_action"],
        row["decision_at"],
        row["decision_source_checksum"],
    ) == ("clean", "2026-08-24 10:00:00", original.source_checksum)
    assert (
        row["source_state"],
        row["source_check_code"],
        row["source_checked_at"],
        row["source_check_expires_at"],
        row["check_source_checksum"],
    ) == (
        "reachable",
        "https_ok",
        "2026-08-24 10:01:00",
        "2026-08-31 10:01:00",
        original.source_checksum,
    )
    assert row["review_stale_at"] is None


def test_changed_checksum_stales_prior_decision_and_check_without_inheriting_them(db, monkeypatch):
    monkeypatch.setattr(migration, "current_shanghai_datetime", lambda: datetime(2026, 8, 24, 15, 16, 17))
    article_id = db.execute(
        "INSERT INTO articles (title,source,source_url) VALUES (?,?,?)",
        ("版本一", "来源", "https://example.com/versioned"),
    ).lastrowid
    db.commit()
    original = _item(migration.inventory_legacy_content(db), "articles", article_id)
    migration.record_legacy_inventory(db, (original,))
    db.execute(
        "UPDATE legacy_content_reviews SET "
        "decision_action='clean', decision_at='2026-08-24 10:00:00', "
        "decision_source_checksum=source_checksum, source_state='reachable', "
        "source_check_code='https_ok', source_checked_at='2026-08-24 10:01:00', "
        "source_check_expires_at='2026-08-31 10:01:00', "
        "check_source_checksum=source_checksum "
        "WHERE source_table='articles' AND source_id=?",
        (article_id,),
    )
    db.execute("UPDATE articles SET title=? WHERE id=?", ("版本二", article_id))
    db.commit()
    changed = _item(migration.inventory_legacy_content(db), "articles", article_id)

    migration.record_legacy_inventory(db, (changed,))
    row = _review_row(db, "articles", article_id)

    assert row["source_checksum"] == changed.source_checksum
    assert row["source_checksum"] != original.source_checksum
    assert row["review_stale_at"] == NOW
    assert row["decision_action"] == "clean"
    assert row["decision_source_checksum"] == original.source_checksum
    assert row["decision_source_checksum"] != row["source_checksum"]
    assert row["source_check_code"] == "https_ok"
    assert row["check_source_checksum"] == original.source_checksum
    assert row["check_source_checksum"] != row["source_checksum"]


def test_cli_defaults_to_zero_write_jsonl_and_never_outputs_contacts_config_or_secrets(
    db, capsys
):
    secret_markers = (
        "CONTACT-SECRET-13800000000",
        "CONFIG-SECRET-VALUE",
        "URL-QUERY-SECRET",
    )
    db.execute(
        "INSERT INTO leads (company_name,contact_name,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?)",
        (secret_markers[0], "联系人", "new", NOW, NOW),
    )
    db.execute(
        "INSERT OR REPLACE INTO site_config (key,value) VALUES (?,?)",
        ("private_key", secret_markers[1]),
    )
    db.execute(
        "INSERT INTO articles (title,source,source_url) VALUES (?,?,?)",
        ("安全输出文章", "来源", f"https://example.com/safe?token={secret_markers[2]}"),
    )
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = _legacy_counts(db)

    assert manage.main(["inventory-content"]) == 0
    output = capsys.readouterr().out
    lines = output.splitlines()

    assert lines
    assert all(json.loads(line)["source_table"] in {
        "services", "cases", "articles", "announcements"
    } for line in lines)
    assert all(marker not in output for marker in secret_markers)
    assert "private_key" not in output
    assert _legacy_counts(db) == before
    assert db.execute("SELECT COUNT(*) FROM legacy_content_reviews").fetchone()[0] == 0


def test_cli_record_populates_reviews_but_preserves_all_sources(db, capsys, monkeypatch):
    monkeypatch.setattr(migration, "current_shanghai_datetime", lambda: datetime(2026, 8, 24, 15, 16, 17))
    before = _legacy_counts(db)

    assert manage.main(["inventory-content", "--format", "jsonl", "--record"]) == 0
    output = capsys.readouterr().out

    assert output.splitlines()
    assert _legacy_counts(db) == before
    assert db.execute("SELECT COUNT(*) FROM legacy_content_reviews").fetchone()[0] == sum(before.values())


def test_mapping_rules_reject_unknown_sources_targets_and_executable_rules(
    db, tmp_path, monkeypatch
):
    bad_rules = {
        "version": 1,
        "allowed_source_tables": [
            "services", "cases", "articles", "announcements", "site_config"
        ],
        "allowed_target_types": [
            "service", "case", "resource", "announcement", "admin_session"
        ],
        "allowed_target_groups": list(KNOWN_SERVICE_CODES) + ["unknown_group"],
        "service_code_targets": {
            "foundation_workshop": {"target_type": "service", "target_group": "foundation_workshop"}
        },
        "expression": "__import__('os').environ",
    }
    path = tmp_path / "bad-rules.json"
    path.write_text(json.dumps(bad_rules), encoding="utf-8")
    monkeypatch.setattr(migration, "MAPPING_RULES_PATH", path)

    with pytest.raises(ValueError, match="mapping rules"):
        migration.inventory_legacy_content(db)


def test_cli_dry_run_uses_a_true_read_only_connection_and_preserves_delete_journal(
    db, capsys, monkeypatch
):
    assert db.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() == "delete"

    def writable_connection_must_not_be_used():
        raise AssertionError("dry-run opened the writable database helper")

    monkeypatch.setattr(manage.models, "get_db", writable_connection_must_not_be_used)

    assert manage.main(["inventory-content"]) == 0
    assert capsys.readouterr().err == ""
    assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"


def test_cli_dry_run_missing_database_fails_generically_without_creating_paths(
    tmp_path, capsys, monkeypatch
):
    missing_parent = tmp_path / "must-not-be-created"
    missing_db = missing_parent / "platform.db"
    monkeypatch.setattr(manage.models, "DB_PATH", str(missing_db))

    assert manage.main(["inventory-content"]) == 1
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == "error=inventory_unavailable\n"
    assert not missing_parent.exists()
    assert str(missing_db) not in captured.err


def _file_fingerprints(directory):
    return {
        path.name: (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in directory.iterdir()
        if path.is_file()
    }


def test_cli_dry_run_fails_closed_on_uncheckpointed_wal_without_creating_shm(
    tmp_path, capsys, monkeypatch
):
    database_path = tmp_path / "wal-platform.db"
    with sqlite3.connect(database_path) as setup:
        assert setup.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        setup.execute("CREATE TABLE snapshot_probe (value TEXT NOT NULL)")
        setup.execute("INSERT INTO snapshot_probe VALUES ('main-only')")
        setup.commit()
        setup.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    setup.close()
    crash_writer = (
        "import os, sqlite3, sys\n"
        "db=sqlite3.connect(sys.argv[1])\n"
        "db.execute('PRAGMA wal_autocheckpoint=0')\n"
        "db.execute(\"INSERT INTO snapshot_probe VALUES ('wal-only')\")\n"
        "db.commit()\n"
        "os._exit(0)\n"
    )
    subprocess.run(
        [sys.executable, "-c", crash_writer, str(database_path)],
        check=True,
    )
    wal_path = database_path.with_name(f"{database_path.name}-wal")
    shm_path = database_path.with_name(f"{database_path.name}-shm")
    assert wal_path.exists() and wal_path.stat().st_size > 0
    shm_path.unlink(missing_ok=True)
    immutable = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        assert immutable.execute("SELECT value FROM snapshot_probe").fetchall() == [
            ("main-only",)
        ]
    finally:
        immutable.close()
    before = _file_fingerprints(tmp_path)
    monkeypatch.setattr(manage.models, "DB_PATH", str(database_path))

    assert manage.main(["inventory-content"]) == 1
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == "error=inventory_unavailable\n"
    assert _file_fingerprints(tmp_path) == before
    assert not shm_path.exists()


@pytest.mark.parametrize("rules_payload", (None, "{damaged-json"))
def test_cli_dry_run_maps_invalid_mapping_rules_to_the_only_generic_error(
    db, tmp_path, capsys, monkeypatch, rules_payload
):
    assert db.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() == "delete"
    missing_rules = tmp_path / "private-missing-rules-marker.json"
    if rules_payload is not None:
        missing_rules.write_text(rules_payload, encoding="utf-8")
    monkeypatch.setattr(migration, "MAPPING_RULES_PATH", missing_rules)

    assert manage.main(["inventory-content"]) == 1
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == "error=inventory_unavailable\n"
    assert "private-missing-rules-marker" not in captured.err


def test_cli_record_uses_the_existing_writable_connection_seam(
    db, capsys, monkeypatch
):
    calls = []
    real_get_db = manage.models.get_db

    def tracked_get_db():
        calls.append("write")
        return real_get_db()

    monkeypatch.setattr(manage.models, "get_db", tracked_get_db)

    assert manage.main(["inventory-content", "--record"]) == 0
    capsys.readouterr()

    assert calls == ["write"]
    assert db.execute("SELECT COUNT(*) FROM legacy_content_reviews").fetchone()[0] > 0


@pytest.mark.parametrize(
    "unsafe_url",
    (
        "https://example.com/has space",
        "https://-bad.example/path",
        "https://bad_.example/path",
        "https://example.com/%zz",
        "https://example.com/@user",
        " https://example.com/leading-space",
        "https://example.com/delete\x7fcontrol",
        "https://example.com/c1\x80control",
        "https://[v1.fe80]/path",
        "https://999.999.999.999/path",
    ),
)
def test_article_url_that_cannot_safely_persist_fails_closed(db, unsafe_url):
    article_id = db.execute(
        "INSERT INTO articles (title,source,source_url) VALUES (?,?,?)",
        ("非法 URL", "来源", unsafe_url),
    ).lastrowid
    db.commit()

    item = _item(migration.inventory_legacy_content(db), "articles", article_id)

    assert (item.action, item.reason_code, item.target_type, item.target_preview) == (
        "archive",
        "article_source_url_invalid",
        None,
        None,
    )


@pytest.mark.parametrize(
    ("source_url", "expected_display"),
    (
        ("https://8.8.8.8/path", "https://8.8.8.8/path"),
        (
            "https://[2001:4860:4860::8888]/path",
            "https://[2001:4860:4860::8888]/path",
        ),
        ("https://例子.测试/路径", "https://xn--fsqu00a.xn--0zwm56d/路径"),
    ),
)
def test_real_ip_literals_and_idna_domains_remain_clean(
    db, source_url, expected_display
):
    article_id = db.execute(
        "INSERT INTO articles (title,source,source_url) VALUES (?,?,?)",
        ("合法公共 URL", "来源", source_url),
    ).lastrowid
    db.commit()

    item = _item(migration.inventory_legacy_content(db), "articles", article_id)

    assert (item.action, item.reason_code) == (
        "clean",
        "article_source_requires_check",
    )
    assert item.target_preview["source_url_display"] == expected_display


def test_cli_record_handles_mixed_valid_and_invalid_urls_atomically(
    db, capsys, monkeypatch
):
    monkeypatch.setattr(
        migration,
        "current_shanghai_datetime",
        lambda: datetime(2026, 8, 24, 15, 16, 17),
    )
    invalid_urls = (
        "https://example.com/has space",
        "https://-bad.example/path",
        "https://bad_.example/path",
        "https://example.com/%zz",
        "https://example.com/@user",
        "https://[v1.fe80]/path",
        "https://999.999.999.999/path",
    )
    invalid_ids = [
        db.execute(
            "INSERT INTO articles (title,source,source_url) VALUES (?,?,?)",
            (f"非法 URL {index}", "来源", url),
        ).lastrowid
        for index, url in enumerate(invalid_urls, 1)
    ]
    valid_id = db.execute(
        "INSERT INTO articles (title,source,source_url) VALUES (?,?,?)",
        (
            "合法 URL",
            "来源",
            "https://Example.com/valid/path?token=still-hashed#not-stored",
        ),
    ).lastrowid
    db.commit()

    assert manage.main(["inventory-content", "--record"]) == 0
    capsys.readouterr()

    rows = db.execute(
        "SELECT source_id,proposed_action,reason_code,source_url_display,"
        "source_url_sha256 FROM legacy_content_reviews "
        "WHERE source_table='articles' AND source_id IN ({})".format(
            ",".join("?" for _ in (*invalid_ids, valid_id))
        ),
        (*invalid_ids, valid_id),
    ).fetchall()
    by_id = {row["source_id"]: row for row in rows}
    assert set(by_id) == {*invalid_ids, valid_id}
    for source_id in invalid_ids:
        assert (
            by_id[source_id]["proposed_action"],
            by_id[source_id]["reason_code"],
            by_id[source_id]["source_url_display"],
            by_id[source_id]["source_url_sha256"],
        ) == ("archive", "article_source_url_invalid", None, None)
    assert by_id[valid_id]["source_url_display"] == "https://example.com/valid/path"
    assert len(by_id[valid_id]["source_url_sha256"]) == 64
