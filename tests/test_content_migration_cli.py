import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

from content_contracts import ContentDraft
import legacy_content_migration as migration
import manage
import models
import publishing_repository
import publishing_service
from source_url_checker import FetchResult


SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 26, 10, 0, 0, tzinfo=SHANGHAI)


class SuccessfulTransport:
    def __init__(self, db, on_fetch=None):
        self.db = db
        self.on_fetch = on_fetch
        self.calls = []

    def fetch(self, url, **kwargs):
        assert self.db.in_transaction is False
        self.calls.append((url, kwargs))
        if self.on_fetch is not None:
            self.on_fetch()
        return FetchResult(True, "https_ok", url, 200, "text/html", b"reviewed")


class FailingTransport(SuccessfulTransport):
    def fetch(self, url, **kwargs):
        assert self.db.in_transaction is False
        self.calls.append((url, kwargs))
        if urlsplit(url).scheme not in kwargs["allowed_schemes"]:
            return FetchResult(False, "scheme_not_allowed", url, None, None, b"")
        return FetchResult(False, "network_error", url, None, None, b"")


def _insert_article(db, *, suffix="one", url=None):
    source_url = url or f"https://example.com/{suffix}?private=redacted"
    cursor = db.execute(
        "INSERT INTO articles "
        "(title_hash,title,source,source_url,summary,content_html,publish_date,status) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            f"hash-{suffix}",
            f"旧文章 {suffix}",
            "可信来源",
            source_url,
            "仍有参考价值的摘要",
            "<p>经过人工审阅的旧文章正文。</p>",
            "2026-08-01 09:00:00",
            "published",
        ),
    )
    db.commit()
    return cursor.lastrowid


def _insert_announcement(db, *, suffix="one"):
    cursor = db.execute(
        "INSERT INTO announcements (title,content_html,status,created_at) VALUES (?,?,?,?)",
        (
            f"旧公告 {suffix}",
            "<p>经过人工审阅的公告正文。</p>",
            "published",
            "2026-08-01 09:00:00",
        ),
    )
    db.commit()
    return cursor.lastrowid


def _record_inventory(db):
    items = migration.inventory_legacy_content(db)
    migration.record_legacy_inventory(db, items)
    return items


def _review(db, table, source_id):
    return db.execute(
        "SELECT * FROM legacy_content_reviews WHERE source_table=? AND source_id=?",
        (table, source_id),
    ).fetchone()


def _decision_payload(review, *, action=None, confirmations=None, target=None):
    return {
        "version": 1,
        "source_table": review["source_table"],
        "source_id": review["source_id"],
        "source_checksum": review["source_checksum"],
        "action": action or review["proposed_action"],
        "confirmations": list(confirmations or json.loads(review["required_confirmations_json"] or "[]")),
        "target": target or {},
    }


def _insert_case(db, *, suffix="one"):
    cursor = db.execute(
        "INSERT INTO cases (title,industry,pain_point,solution,result) VALUES (?,?,?,?,?)",
        (f"案例 {suffix}", "制造业", "问题", "方案", "结果"),
    )
    db.commit()
    return cursor.lastrowid


def _case_target():
    return {
        "verification_code": "authorized_anonymous",
        "is_anonymized": 1,
        "basis_type": "client_authorization",
        "private_basis_reference": "授权记录",
        "metrics": [
            {
                "name": "周期",
                "before_value": "10",
                "after_value": "5",
                "unit": "天",
                "statistical_period": "四周",
                "evidence_explanation": "授权复盘记录",
            }
        ],
    }


def _load_decisions(tmp_path, *payloads):
    path = tmp_path / "decisions.jsonl"
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in payloads),
        encoding="utf-8",
    )
    return migration.load_legacy_decisions(path)


def _legacy_counts(db):
    return tuple(
        db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in migration.SOURCE_TABLES
    )


def test_source_preflight_runs_outside_transactions_and_persists_exact_binding(db):
    article_id = _insert_article(db)
    _record_inventory(db)
    transport = SuccessfulTransport(db)

    result = migration.check_legacy_sources(
        db, transport=transport, actor="legacy_source_check", now=NOW
    )

    row = _review(db, "articles", article_id)
    assert result.errors == ()
    assert row["source_state"] == "reachable"
    assert row["source_check_code"] == "https_ok"
    assert row["source_checked_at"] == "2026-08-26 10:00:00"
    assert row["source_check_expires_at"] == "2026-09-02 10:00:00"
    assert row["check_source_checksum"] == row["source_checksum"]
    assert transport.calls
    assert all(call[1]["allowed_hosts"] == frozenset({"example.com"}) for call in transport.calls)


def test_source_preflight_records_all_exact_states_and_refuses_checksum_toctou(db):
    unreachable_id = _insert_article(db, suffix="offline")
    invalid_id = _insert_article(db, suffix="http", url="http://example.com/legacy")
    announcement_id = _insert_announcement(db)
    _record_inventory(db)

    result = migration.check_legacy_sources(
        db, transport=FailingTransport(db), actor="legacy_source_check", now=NOW
    )
    assert _review(db, "articles", unreachable_id)["source_state"] == "unreachable"
    assert _review(db, "articles", invalid_id)["source_state"] == "invalid"
    missing = _review(db, "announcements", announcement_id)
    assert missing["source_state"] == "missing"
    assert missing["source_check_code"] == "source_missing"
    assert result.errors == ()

    changed_id = _insert_article(db, suffix="changed")
    _record_inventory(db)

    def mutate_after_network():
        db.execute(
            "UPDATE articles SET summary='并发变更' WHERE id=?", (changed_id,)
        )
        db.commit()

    toctou = migration.check_legacy_sources(
        db,
        transport=SuccessfulTransport(db, on_fetch=mutate_after_network),
        actor="legacy_source_check",
        now=NOW,
        identities=(("articles", changed_id),),
    )
    assert toctou.errors == ("source_changed",)
    row = _review(db, "articles", changed_id)
    assert row["source_state"] == "unchecked"
    assert row["source_check_code"] is None


@pytest.mark.parametrize(
    "mutator",
    (
        lambda value: {**value, "extra": True},
        lambda value: {**value, "source_id": True},
        lambda value: {**value, "source_id": 1.0},
        lambda value: {**value, "source_table": []},
        lambda value: {**value, "action": {}},
        lambda value: {**value, "source_checksum": "0" * 63},
        lambda value: {**value, "confirmations": ["x", "x"]},
        lambda value: {**value, "confirmations": [{}]},
    ),
)
def test_decision_jsonl_rejects_non_exact_shapes_and_types(db, tmp_path, mutator):
    article_id = _insert_article(db, suffix="schema")
    _record_inventory(db)
    payload = _decision_payload(
        _review(db, "articles", article_id),
        target={
            "copyright_notice": "已获摘要展示许可",
            "original_published_at": "2026-08-01 09:00:00",
        },
    )
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps(mutator(payload), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(migration.LegacyDecisionError):
        migration.load_legacy_decisions(path)


@pytest.mark.parametrize(
    "raw",
    (
        '{"version":1,"version":1}',
        '{"version":NaN}',
    ),
)
def test_decision_jsonl_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path, raw):
    path = tmp_path / "invalid.jsonl"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(migration.LegacyDecisionError):
        migration.load_legacy_decisions(path)


def test_decision_jsonl_wraps_decoder_value_errors_for_oversized_integer(tmp_path):
    path = tmp_path / "oversized-integer.jsonl"
    path.write_text('{"version":' + "9" * 5_000 + "}", encoding="utf-8")

    with pytest.raises(migration.LegacyDecisionError, match="invalid decision JSON"):
        migration.load_legacy_decisions(path)


@pytest.mark.parametrize(
    "forbidden",
    ("\u0001", "\u202e", "\ud800", "\ue000", "\ufdd0"),
)
def test_decision_plain_text_rejects_every_unicode_other_category(
    db, tmp_path, forbidden
):
    article_id = _insert_article(db, suffix="unicode-category")
    _record_inventory(db)
    payload = _decision_payload(
        _review(db, "articles", article_id),
        target={
            "copyright_notice": f"许可说明{forbidden}",
            "original_published_at": "2026-08-01 09:00:00",
        },
    )
    path = tmp_path / "unicode-category.jsonl"
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")

    with pytest.raises(migration.LegacyDecisionError):
        migration.load_legacy_decisions(path)


@pytest.mark.parametrize(
    ("slot", "forbidden"),
    (("private_basis_reference", "\u202e"), ("metric_evidence", "\ud800")),
)
def test_case_private_and_metric_text_reject_format_or_surrogate_characters(
    db, tmp_path, slot, forbidden
):
    case_id = _insert_case(db, suffix=slot)
    _record_inventory(db)
    target = _case_target()
    if slot == "private_basis_reference":
        target["private_basis_reference"] = f"授权{forbidden}记录"
    else:
        target["metrics"][0]["evidence_explanation"] = f"复盘{forbidden}记录"
    payload = _decision_payload(
        _review(db, "cases", case_id), action="clean", target=target
    )
    path = tmp_path / f"case-{slot}.jsonl"
    path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")

    with pytest.raises(migration.LegacyDecisionError):
        migration.load_legacy_decisions(path)


def test_decision_plain_text_allows_normal_chinese_and_emoji(db, tmp_path):
    article_id = _insert_article(db, suffix="normal-unicode")
    _record_inventory(db)
    payload = _decision_payload(
        _review(db, "articles", article_id),
        target={
            "copyright_notice": "客户确认：可公开摘要 ✅",
            "original_published_at": "2026-08-01 09:00:00",
        },
    )

    assert len(_load_decisions(tmp_path, payload)) == 1


def test_decision_jsonl_rejects_duplicate_source_identity(db, tmp_path):
    article_id = _insert_article(db, suffix="duplicate")
    _record_inventory(db)
    payload = _decision_payload(
        _review(db, "articles", article_id),
        target={
            "copyright_notice": "已获摘要展示许可",
            "original_published_at": "2026-08-01 09:00:00",
        },
    )
    with pytest.raises(migration.LegacyDecisionError):
        _load_decisions(tmp_path, payload, payload)


def test_decision_jsonl_rejects_out_of_range_sqlite_ids(db, tmp_path):
    article_id = _insert_article(db, suffix="id-bound")
    _record_inventory(db)
    article = _decision_payload(
        _review(db, "articles", article_id),
        target={
            "copyright_notice": "已获摘要展示许可",
            "original_published_at": "2026-08-01 09:00:00",
        },
    )
    article["source_id"] = 9_223_372_036_854_775_808
    with pytest.raises(migration.LegacyDecisionError):
        _load_decisions(tmp_path, article)


@pytest.mark.parametrize(
    ("verification_code", "is_anonymized"),
    (("public_verified", 1), ("authorized_anonymous", 0)),
)
def test_case_decision_requires_exact_verification_anonymization_pair(
    db, tmp_path, verification_code, is_anonymized
):
    case_id = db.execute(
        "INSERT INTO cases (title,industry,pain_point,solution,result) VALUES (?,?,?,?,?)",
        ("案例", "制造业", "问题", "方案", "结果"),
    ).lastrowid
    db.commit()
    _record_inventory(db)
    case = _decision_payload(
        _review(db, "cases", case_id),
        action="clean",
        target={
            "verification_code": verification_code,
            "is_anonymized": is_anonymized,
            "basis_type": "client_authorization",
            "private_basis_reference": "授权记录",
            "metrics": [
                {
                    "name": "周期",
                    "before_value": "10",
                    "after_value": "5",
                    "unit": "天",
                    "statistical_period": "四周",
                    "evidence_explanation": "授权复盘记录",
                }
            ],
        },
    )
    with pytest.raises(migration.LegacyDecisionError):
        _load_decisions(tmp_path, case)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (("verification_code", []), ("basis_type", {})),
)
def test_case_decision_enum_types_are_stable_validation_errors(
    db, tmp_path, field, invalid_value
):
    case_id = db.execute(
        "INSERT INTO cases (title,industry,pain_point,solution,result) VALUES (?,?,?,?,?)",
        ("枚举案例", "制造业", "问题", "方案", "结果"),
    ).lastrowid
    db.commit()
    _record_inventory(db)
    target = {
        "verification_code": "authorized_anonymous",
        "is_anonymized": 1,
        "basis_type": "client_authorization",
        "private_basis_reference": "授权记录",
        "metrics": [
            {
                "name": "周期",
                "before_value": "10",
                "after_value": "5",
                "unit": "天",
                "statistical_period": "四周",
                "evidence_explanation": "授权复盘记录",
            }
        ],
    }
    target[field] = invalid_value
    case = _decision_payload(
        _review(db, "cases", case_id), action="clean", target=target
    )

    with pytest.raises(migration.LegacyDecisionError):
        _load_decisions(tmp_path, case)


def test_service_decision_rejects_out_of_range_target_and_lock_ids(db, tmp_path):
    source = db.execute(
        "SELECT * FROM services WHERE code='foundation_workshop'"
    ).fetchone()
    _record_inventory(db)
    review = _review(db, "services", source["id"])
    for field in ("target_content_id", "expected_lock_version"):
        target = {
            "target_group": "foundation_workshop",
            "target_content_id": 1,
            "expected_lock_version": 1,
            "merge_approved": True,
        }
        target[field] = 9_223_372_036_854_775_808
        with pytest.raises(migration.LegacyDecisionError):
            _load_decisions(
                tmp_path,
                _decision_payload(review, target=target),
            )
    with pytest.raises(migration.LegacyDecisionError):
        _load_decisions(
            tmp_path,
            _decision_payload(review, target={"target_group": []}),
        )


def test_decision_jsonl_converts_deep_json_and_read_races_to_stable_error(
    db, tmp_path, monkeypatch
):
    nested = tmp_path / "nested.jsonl"
    nested.write_text("[" * 1_200 + "0" + "]" * 1_200, encoding="utf-8")
    with pytest.raises(migration.LegacyDecisionError):
        migration.load_legacy_decisions(nested)

    article_id = _insert_article(db, suffix="decision-race")
    _record_inventory(db)
    payload = _decision_payload(
        _review(db, "articles", article_id),
        target={
            "copyright_notice": "已获摘要展示许可",
            "original_published_at": "2026-08-01 09:00:00",
        },
    )
    racing = tmp_path / "racing.jsonl"
    racing.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    original_open = Path.open

    class RacingReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, size=-1):
            data = self.handle.read(size)
            with original_open(racing, "ab") as writer:
                writer.write(b" ")
            return data

    def racing_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return RacingReader(handle) if path == racing else handle

    monkeypatch.setattr(Path, "open", racing_open)
    with pytest.raises(migration.LegacyDecisionError):
        migration.load_legacy_decisions(racing)


def test_decision_jsonl_bounds_the_read_when_file_grows_after_open(
    db, tmp_path, monkeypatch
):
    article_id = _insert_article(db, suffix="decision-growth")
    _record_inventory(db)
    payload = _decision_payload(
        _review(db, "articles", article_id),
        target={
            "copyright_notice": "已获摘要展示许可",
            "original_published_at": "2026-08-01 09:00:00",
        },
    )
    growing = tmp_path / "growing.jsonl"
    growing.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    original_open = Path.open
    requested_sizes = []

    class GrowingReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, size=-1):
            requested_sizes.append(size)
            with original_open(growing, "ab") as writer:
                writer.write(b"x" * (migration.MAX_DECISION_BYTES + 1))
            return self.handle.read(size)

    def tracked_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return GrowingReader(handle) if path == growing else handle

    monkeypatch.setattr(Path, "open", tracked_open)

    with pytest.raises(migration.LegacyDecisionError):
        migration.load_legacy_decisions(growing)
    assert requested_sizes == [migration.MAX_DECISION_BYTES + 1]


def test_article_preview_is_zero_write_then_apply_is_draft_only_idempotent(db, tmp_path):
    article_id = _insert_article(db, suffix="apply")
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "articles", article_id)
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    before_sources = _legacy_counts(db)
    before_targets = db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]

    preview = migration.preview_legacy_decisions(db, decisions, now=NOW)
    assert preview.items[0].status == "ready"
    assert db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == before_targets
    assert db.execute("SELECT COUNT(*) FROM legacy_content_mappings").fetchone()[0] == 0

    first = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )
    db.execute(
        "UPDATE legacy_content_reviews SET source_check_expires_at='2026-08-25 10:00:00' "
        "WHERE source_table='articles' AND source_id=?",
        (article_id,),
    )
    db.commit()
    second = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )
    assert second.target_ids == first.target_ids
    assert first.errors == second.errors == ()
    content_id = first.target_ids[0]
    item = db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
    extension = db.execute(
        "SELECT * FROM resource_content WHERE content_item_id=?", (content_id,)
    ).fetchone()
    mapping = db.execute(
        "SELECT * FROM legacy_content_mappings WHERE source_table='articles' AND source_id=?",
        (article_id,),
    ).fetchone()
    assert item["entry_type"] == "resource" and item["status"] == "draft"
    assert extension["source_url"] == "https://example.com/apply"
    assert mapping["target_content_item_id"] == content_id
    assert mapping["target_content_group_id"] == item["content_group_id"]
    assert tuple(extension[key] for key in (
        "source_check_code", "source_checked_at", "source_check_expires_at",
        "source_check_url_sha256",
    )) == (None, None, None, None)
    assert _legacy_counts(db) == before_sources
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events "
        "WHERE content_item_id=? AND event_code='legacy_content_migrated'",
        (content_id,),
    ).fetchone()[0] == 1

    db.execute("UPDATE articles SET summary='源已变化' WHERE id=?", (article_id,))
    db.commit()
    drift = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )
    assert drift.errors == ("source_changed",)
    assert drift.target_ids == ()


@pytest.mark.parametrize("later_status", ("published", "archived"))
def test_existing_mapping_remains_idempotent_after_target_lifecycle(
    db, tmp_path, later_status
):
    article_id = _insert_article(db, suffix=f"mapped-{later_status}")
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            _review(db, "articles", article_id),
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    first = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at=? WHERE id=?",
        ("2026-08-26 10:01:00", first.target_ids[0]),
    )
    if later_status == "archived":
        db.execute(
            "UPDATE content_items SET status='archived',archived_at=? WHERE id=?",
            ("2026-08-26 10:02:00", first.target_ids[0]),
        )
    db.commit()

    repeated = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )

    assert repeated.target_ids == first.target_ids
    assert repeated.errors == ()
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events "
        "WHERE content_item_id=? AND event_code='legacy_content_migrated'",
        (first.target_ids[0],),
    ).fetchone()[0] == 1


def test_stale_or_unchecked_source_and_stale_decision_fail_closed(db, tmp_path):
    article_id = _insert_article(db, suffix="stale")
    _record_inventory(db)
    review = _review(db, "articles", article_id)
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    assert migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    ).errors == ("source_unchecked",)

    migration.check_legacy_sources(
        db,
        transport=SuccessfulTransport(db),
        actor="legacy_source_check",
        now=NOW - timedelta(days=8),
    )
    assert migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    ).errors == ("source_check_stale",)

    stale_payload = _decision_payload(
        review,
        target={
            "copyright_notice": "已获摘要展示许可",
            "original_published_at": "2026-08-01 09:00:00",
        },
    )
    stale_payload["source_checksum"] = "f" * 64
    stale_decisions = _load_decisions(tmp_path, stale_payload)
    assert migration.apply_legacy_decisions(
        db, stale_decisions, actor="legacy_migration", now=NOW
    ).errors == ("decision_stale",)


@pytest.mark.parametrize(
    ("state", "code", "checked_at", "expires_at", "expected"),
    (
        (
            "reachable",
            "network_error",
            "2026-08-26 10:00:00",
            "2026-09-02 10:00:00",
            "source_not_allowed",
        ),
        (
            "reachable",
            "https_ok",
            None,
            "2026-09-02 10:00:00",
            "source_check_stale",
        ),
        (
            "reachable",
            "https_ok",
            "2026-08-27 10:00:00",
            "2026-09-03 10:00:00",
            "source_check_stale",
        ),
        (
            "reachable",
            "https_ok",
            "2026-08-26 10:00:00",
            "2099-09-02 10:00:00",
            "source_check_stale",
        ),
    ),
)
def test_apply_rejects_polluted_article_source_check_tuple(
    db, tmp_path, state, code, checked_at, expires_at, expected
):
    article_id = _insert_article(db, suffix=f"polluted-{expected}-{code}")
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "articles", article_id)
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    before = db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
    if checked_at is None:
        db.execute("PRAGMA ignore_check_constraints=ON")
    db.execute(
        "UPDATE legacy_content_reviews SET source_state=?,source_check_code=?,"
        "source_checked_at=?,source_check_expires_at=? "
        "WHERE source_table='articles' AND source_id=?",
        (state, code, checked_at, expires_at, article_id),
    )
    db.commit()
    if checked_at is None:
        db.execute("PRAGMA ignore_check_constraints=OFF")

    result = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )

    assert result.errors == (expected,)
    assert result.target_ids == ()
    assert db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == before
    assert db.execute(
        "SELECT COUNT(*) FROM legacy_content_mappings "
        "WHERE source_table='articles' AND source_id=?",
        (article_id,),
    ).fetchone()[0] == 0


def test_apply_rejects_impossible_missing_source_state_pair(db, tmp_path):
    announcement_id = _insert_announcement(db, suffix="state-pair")
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "announcements", announcement_id)
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            action="clean",
            target={
                "valid_from": "2026-08-26 00:00:00",
                "valid_until": "2026-09-26 00:00:00",
                "cta_url": None,
            },
        ),
    )
    db.execute(
        "UPDATE legacy_content_reviews SET source_state='reachable',"
        "source_check_code='https_ok' WHERE source_table='announcements' AND source_id=?",
        (announcement_id,),
    )
    db.commit()

    result = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )

    assert result.errors == ("source_not_allowed",)
    assert result.target_ids == ()


def test_source_check_never_blesses_old_decision_but_current_file_can_replace_it(
    db, tmp_path
):
    article_id = _insert_article(db, suffix="renewed-decision")
    _record_inventory(db)
    db.execute(
        "UPDATE legacy_content_reviews SET decision_action='clean',"
        "decision_at='2026-08-20 10:00:00',decision_source_checksum=? "
        "WHERE source_table='articles' AND source_id=?",
        ("f" * 64, article_id),
    )
    db.commit()
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    checked = _review(db, "articles", article_id)
    assert checked["decision_source_checksum"] == "f" * 64
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            checked,
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    result = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )
    assert result.errors == ()
    renewed = _review(db, "articles", article_id)
    assert renewed["decision_source_checksum"] == renewed["source_checksum"]


def test_case_requires_exact_private_evidence_and_complete_metrics(db, tmp_path):
    case_id = db.execute(
        "INSERT INTO cases (title,industry,pain_point,solution,result) VALUES (?,?,?,?,?)",
        ("经授权匿名案例", "制造业", "知识检索慢", "权限化知识库", "完成试点"),
    ).lastrowid
    db.commit()
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "cases", case_id)
    base_target = {
        "verification_code": "authorized_anonymous",
        "is_anonymized": 1,
        "basis_type": "client_authorization",
        "private_basis_reference": "授权记录-2026-01",
        "metrics": [],
    }
    incomplete = _load_decisions(
        tmp_path,
        _decision_payload(review, action="clean", target=base_target),
    )
    assert migration.apply_legacy_decisions(
        db, incomplete, actor="legacy_migration", now=NOW
    ).errors == ("case_evidence_incomplete",)

    target = dict(base_target)
    target["metrics"] = [
        {
            "name": "检索用时",
            "before_value": "30",
            "after_value": "8",
            "unit": "分钟",
            "statistical_period": "试点后四周",
            "evidence_explanation": "由授权项目复盘记录核验",
        }
    ]
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(review, action="clean", target=target),
    )
    result = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )
    assert result.errors == ()
    content_id = result.target_ids[0]
    case_extension = db.execute(
        "SELECT * FROM case_content WHERE content_item_id=?", (content_id,)
    ).fetchone()
    assert case_extension["basis_type"] == "client_authorization"
    assert case_extension["source_check_code"] is None
    assert db.execute(
        "SELECT COUNT(*) FROM case_metrics WHERE case_content_item_id=?", (content_id,)
    ).fetchone()[0] == 1


def test_explicit_announcement_dates_create_announcement_draft(db, tmp_path):
    announcement_id = _insert_announcement(db, suffix="dated")
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "announcements", announcement_id)
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            action="clean",
            target={
                "valid_from": "2026-08-26 00:00:00",
                "valid_until": "2026-09-26 00:00:00",
                "cta_url": "/assessment",
            },
        ),
    )
    result = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )
    item = db.execute(
        "SELECT * FROM content_items WHERE id=?", (result.target_ids[0],)
    ).fetchone()
    extension = db.execute(
        "SELECT * FROM announcement_content WHERE content_item_id=?", (item["id"],)
    ).fetchone()
    assert item["entry_type"] == "announcement" and item["status"] == "draft"
    assert (extension["valid_from"], extension["valid_until"]) == (
        "2026-08-26 00:00:00",
        "2026-09-26 00:00:00",
    )


def test_expired_or_not_yet_current_announcement_is_not_converted(
    db, tmp_path
):
    announcement_id = _insert_announcement(db, suffix="expired")
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "announcements", announcement_id)
    for suffix, valid_from, valid_until in (
        ("expired", "2020-01-01 00:00:00", "2020-02-01 00:00:00"),
        ("future", "2026-08-27 00:00:00", "2026-09-27 00:00:00"),
    ):
        decisions = _load_decisions(
            tmp_path,
            _decision_payload(
                review,
                action="clean",
                target={
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                    "cta_url": None,
                },
            ),
        )
        result = migration.apply_legacy_decisions(
            db, decisions, actor="legacy_migration", now=NOW
        )
        assert result.errors == ("announcement_not_current",), suffix
        assert result.target_ids == ()


def test_seeded_service_requires_lock_versioned_merge_and_preserves_aggregate(db, tmp_path):
    source = db.execute(
        "SELECT * FROM services WHERE code='foundation_workshop'"
    ).fetchone()
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "services", source["id"])
    initial = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            target={"target_group": "foundation_workshop"},
        ),
    )
    before_mapping = db.execute("SELECT COUNT(*) FROM legacy_content_mappings").fetchone()[0]
    preview = migration.preview_legacy_decisions(db, initial, now=NOW)
    item = preview.items[0]
    assert item.status == "target_draft_exists"
    assert item.target_content_id is not None and item.target_lock_version is not None
    assert db.execute("SELECT COUNT(*) FROM legacy_content_mappings").fetchone()[0] == before_mapping

    before = publishing_repository.load_content_draft(db, item.target_content_id)
    approved_payload = _decision_payload(
        review,
        target={
            "target_group": "foundation_workshop",
            "target_content_id": item.target_content_id,
            "expected_lock_version": item.target_lock_version,
            "merge_approved": True,
        },
    )
    approved = _load_decisions(tmp_path, approved_payload)
    result = migration.apply_legacy_decisions(
        db, approved, actor="legacy_migration", now=NOW
    )
    assert result.target_ids == (item.target_content_id,)
    after = publishing_repository.load_content_draft(db, item.target_content_id)
    assert after.content_group_id == before.content_group_id
    assert after.extension == before.extension
    assert after.maturity_codes == before.maturity_codes
    assert after.relations == before.relations
    assert after.metrics == before.metrics
    assert after.share_image_media_id == before.share_image_media_id
    assert after.publish_at == before.publish_at
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE content_group_id=? AND status='draft'",
        (before.content_group_id,),
    ).fetchone()[0] == 1


def test_scheduled_service_target_is_not_merged_before_due_publication(db, tmp_path):
    source = db.execute(
        "SELECT * FROM services WHERE code='foundation_workshop'"
    ).fetchone()
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "services", source["id"])
    initial = _load_decisions(
        tmp_path,
        _decision_payload(review, target={"target_group": "foundation_workshop"}),
    )
    target = migration.preview_legacy_decisions(db, initial, now=NOW).items[0]
    assert target.status == "target_draft_exists"
    assert target.target_content_id is not None
    assert target.target_lock_version is not None
    due_at = NOW + timedelta(hours=1)
    scheduled = publishing_service.schedule_content(
        target.target_content_id,
        target.target_lock_version,
        due_at,
        actor="content_scheduler",
        now=NOW,
    )
    approved = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            target={
                "target_group": "foundation_workshop",
                "target_content_id": target.target_content_id,
                "expected_lock_version": scheduled.lock_version,
                "merge_approved": True,
            },
        ),
    )
    before = publishing_repository.load_content_draft(db, target.target_content_id)
    before_item = tuple(
        db.execute(
            "SELECT status,lock_version,publish_at,updated_at FROM content_items WHERE id=?",
            (target.target_content_id,),
        ).fetchone()
    )
    before_review = tuple(
        _review(db, "services", source["id"])[column]
        for column in ("decision_action", "decision_at", "decision_source_checksum")
    )
    before_mapping = db.execute(
        "SELECT COUNT(*) FROM legacy_content_mappings"
    ).fetchone()[0]
    before_audit = db.execute(
        "SELECT COUNT(*) FROM content_audit_events"
    ).fetchone()[0]

    result = migration.apply_legacy_decisions(
        db, approved, actor="legacy_migration", now=NOW
    )

    assert result.errors == ("target_scheduled",)
    assert publishing_repository.load_content_draft(db, target.target_content_id) == before
    assert tuple(
        db.execute(
            "SELECT status,lock_version,publish_at,updated_at FROM content_items WHERE id=?",
            (target.target_content_id,),
        ).fetchone()
    ) == before_item
    assert tuple(
        _review(db, "services", source["id"])[column]
        for column in ("decision_action", "decision_at", "decision_source_checksum")
    ) == before_review
    assert db.execute(
        "SELECT COUNT(*) FROM legacy_content_mappings"
    ).fetchone()[0] == before_mapping
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events"
    ).fetchone()[0] == before_audit

    due = publishing_service.publish_due_content(actor="due_worker", now=due_at)
    assert due.published_ids == (target.target_content_id,)
    published = publishing_repository.load_content_draft(db, target.target_content_id)
    assert published.blocks == before.blocks
    assert all(block.title != "旧版服务内容审阅合并" for block in published.blocks)
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events "
        "WHERE content_item_id=? AND event_code='legacy_content_migrated'",
        (target.target_content_id,),
    ).fetchone()[0] == 0


def test_existing_service_mapping_reports_source_changed_before_target_validation(
    db, tmp_path
):
    source = db.execute(
        "SELECT * FROM services WHERE code='foundation_workshop'"
    ).fetchone()
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "services", source["id"])
    initial = _load_decisions(
        tmp_path,
        _decision_payload(review, target={"target_group": "foundation_workshop"}),
    )
    target = migration.preview_legacy_decisions(db, initial, now=NOW).items[0]
    approved = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            target={
                "target_group": "foundation_workshop",
                "target_content_id": target.target_content_id,
                "expected_lock_version": target.target_lock_version,
                "merge_approved": True,
            },
        ),
    )
    migrated = migration.apply_legacy_decisions(
        db, approved, actor="legacy_migration", now=NOW
    )
    assert migrated.errors == ()
    db.execute(
        "UPDATE services SET code='foundation_workshop_changed' WHERE id=?",
        (source["id"],),
    )
    db.commit()

    repeated = migration.apply_legacy_decisions(
        db, approved, actor="legacy_migration", now=NOW
    )

    assert repeated.errors == ("source_changed",)
    assert repeated.target_ids == ()


@pytest.mark.parametrize("failure_seam", ("_insert_mapping", "_write_migration_audit"))
def test_service_merge_mapping_or_audit_failure_restores_the_complete_seeded_draft(
    db, tmp_path, monkeypatch, failure_seam
):
    source = db.execute(
        "SELECT * FROM services WHERE code='foundation_workshop'"
    ).fetchone()
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "services", source["id"])
    initial = _load_decisions(
        tmp_path,
        _decision_payload(review, target={"target_group": "foundation_workshop"}),
    )
    target = migration.preview_legacy_decisions(db, initial, now=NOW).items[0]
    approved = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            target={
                "target_group": "foundation_workshop",
                "target_content_id": target.target_content_id,
                "expected_lock_version": target.target_lock_version,
                "merge_approved": True,
            },
        ),
    )
    before = publishing_repository.load_content_draft(db, target.target_content_id)
    before_item = tuple(
        db.execute(
            "SELECT lock_version,updated_at FROM content_items WHERE id=?",
            (target.target_content_id,),
        ).fetchone()
    )
    before_audit = db.execute("SELECT COUNT(*) FROM content_audit_events").fetchone()[0]

    def fail(*args, **kwargs):
        if failure_seam == "_write_migration_audit":
            raise RuntimeError("injected service audit failure")
        raise sqlite3.IntegrityError("injected service mapping failure")

    monkeypatch.setattr(migration, failure_seam, fail)
    result = migration.apply_legacy_decisions(
        db, approved, actor="legacy_migration", now=NOW
    )
    assert result.errors == ("migration_failed",)
    assert publishing_repository.load_content_draft(db, target.target_content_id) == before
    assert tuple(
        db.execute(
            "SELECT lock_version,updated_at FROM content_items WHERE id=?",
            (target.target_content_id,),
        ).fetchone()
    ) == before_item
    assert db.execute("SELECT COUNT(*) FROM content_audit_events").fetchone()[0] == before_audit
    assert db.execute("SELECT COUNT(*) FROM legacy_content_mappings").fetchone()[0] == 0


@pytest.mark.parametrize("failure_seam", ("_insert_mapping", "_write_migration_audit"))
def test_new_target_mapping_or_audit_failure_rolls_back_entire_aggregate(
    db, tmp_path, monkeypatch, failure_seam
):
    article_id = _insert_article(db, suffix=failure_seam)
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            _review(db, "articles", article_id),
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    before_items = db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
    before_groups = db.execute("SELECT COUNT(*) FROM content_groups").fetchone()[0]
    before_audit = db.execute("SELECT COUNT(*) FROM content_audit_events").fetchone()[0]

    def fail(*args, **kwargs):
        if failure_seam == "_write_migration_audit":
            raise RuntimeError("injected audit failure")
        raise sqlite3.IntegrityError("injected mapping failure")

    monkeypatch.setattr(migration, failure_seam, fail)
    result = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )
    assert result.errors == ("migration_failed",)
    assert db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == before_items
    assert db.execute("SELECT COUNT(*) FROM content_groups").fetchone()[0] == before_groups
    assert db.execute("SELECT COUNT(*) FROM content_audit_events").fetchone()[0] == before_audit
    assert db.execute("SELECT COUNT(*) FROM legacy_content_mappings").fetchone()[0] == 0


def test_resource_alias_collision_is_the_same_stable_conflict_in_preview_and_apply(
    db, tmp_path
):
    first_id = _insert_article(db, suffix="alias-owner")
    colliding_id = _insert_article(db, suffix="alias-collision")
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    first_review = _review(db, "articles", first_id)
    first = _load_decisions(
        tmp_path,
        _decision_payload(
            first_review,
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    first_result = migration.apply_legacy_decisions(
        db, first, actor="legacy_migration", now=NOW
    )
    assert first_result.errors == ()
    assert len(first_result.target_ids) == 1
    owner = db.execute(
        "SELECT content_group_id FROM content_items WHERE id=?",
        (first_result.target_ids[0],),
    ).fetchone()
    db.execute(
        "INSERT INTO content_slug_aliases "
        "(entry_type,old_slug,content_group_id,created_at) VALUES (?,?,?,?)",
        (
            "resource",
            f"legacy-article-{colliding_id}",
            owner["content_group_id"],
            "2026-08-26 10:00:00",
        ),
    )
    db.commit()
    alias_owner = db.execute(
        "SELECT cg.entry_type FROM content_slug_aliases alias "
        "JOIN content_groups cg ON cg.id=alias.content_group_id "
        "WHERE alias.entry_type='resource' AND alias.old_slug=?",
        (f"legacy-article-{colliding_id}",),
    ).fetchone()
    assert alias_owner is not None and alias_owner["entry_type"] == "resource"
    colliding_review = _review(db, "articles", colliding_id)
    colliding = _load_decisions(
        tmp_path,
        _decision_payload(
            colliding_review,
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    before = (
        db.execute("SELECT COUNT(*) FROM content_groups").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM legacy_content_mappings").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM content_audit_events").fetchone()[0],
        tuple(
            colliding_review[column]
            for column in ("decision_action", "decision_at", "decision_source_checksum")
        ),
    )

    preview = migration.preview_legacy_decisions(db, colliding, now=NOW)
    applied = migration.apply_legacy_decisions(
        db, colliding, actor="legacy_migration", now=NOW
    )

    assert preview.errors == ("target_conflict",)
    assert applied.errors == ("target_conflict",)
    assert (
        db.execute("SELECT COUNT(*) FROM content_groups").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM legacy_content_mappings").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM content_audit_events").fetchone()[0],
        tuple(
            _review(db, "articles", colliding_id)[column]
            for column in ("decision_action", "decision_at", "decision_source_checksum")
        ),
    ) == before


def test_mapping_identity_must_point_to_item_in_the_recorded_group(db, tmp_path):
    article_id = _insert_article(db, suffix="mapping")
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            _review(db, "articles", article_id),
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    wrong = db.execute(
        "SELECT ci.id,cg.id AS group_id FROM content_items ci "
        "JOIN content_groups cg ON cg.id=ci.content_group_id "
        "WHERE ci.entry_type='service' LIMIT 2"
    ).fetchall()
    db.execute(
        "INSERT INTO legacy_content_mappings "
        "(source_table,source_id,source_checksum,target_content_group_id,"
        "target_content_item_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
        (
            "articles",
            article_id,
            _review(db, "articles", article_id)["source_checksum"],
            wrong[0]["group_id"],
            wrong[1]["id"],
            "2026-08-26 10:00:00",
            "2026-08-26 10:00:00",
        ),
    )
    db.commit()
    result = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )
    assert result.errors == ("mapping_invalid",)
    assert result.target_ids == ()


def test_mapping_postcondition_binds_new_target_to_the_local_aggregate(
    db, tmp_path, monkeypatch
):
    wrong_target_id = _insert_article(db, suffix="mapping-postcondition-owner")
    local_source_id = _insert_article(db, suffix="mapping-postcondition-local")
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    wrong_review = _review(db, "articles", wrong_target_id)
    wrong_decision = _load_decisions(
        tmp_path,
        _decision_payload(
            wrong_review,
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    wrong_result = migration.apply_legacy_decisions(
        db, wrong_decision, actor="legacy_migration", now=NOW
    )
    assert wrong_result.errors == ()
    assert len(wrong_result.target_ids) == 1
    wrong_item = db.execute(
        "SELECT id,content_group_id FROM content_items WHERE id=?",
        (wrong_result.target_ids[0],),
    ).fetchone()
    local_review = _review(db, "articles", local_source_id)
    local_decision = _load_decisions(
        tmp_path,
        _decision_payload(
            local_review,
            target={
                "copyright_notice": "已获摘要展示许可",
                "original_published_at": "2026-08-01 09:00:00",
            },
        ),
    )
    before = (
        db.execute("SELECT COUNT(*) FROM content_groups").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM content_audit_events").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM legacy_content_mappings").fetchone()[0],
        tuple(
            local_review[column]
            for column in ("decision_action", "decision_at", "decision_source_checksum")
        ),
    )
    real_insert_mapping = migration._insert_mapping

    def insert_wrong_same_type_mapping(db_arg, decision, _group_id, _content_id, now_text):
        return real_insert_mapping(
            db_arg,
            decision,
            wrong_item["content_group_id"],
            wrong_item["id"],
            now_text,
        )

    monkeypatch.setattr(migration, "_insert_mapping", insert_wrong_same_type_mapping)
    result = migration.apply_legacy_decisions(
        db, local_decision, actor="legacy_migration", now=NOW
    )

    assert result.errors == ("mapping_invalid",)
    assert result.target_ids == ()
    assert db.execute(
        "SELECT COUNT(*) FROM legacy_content_mappings "
        "WHERE source_table='articles' AND source_id=?",
        (local_source_id,),
    ).fetchone()[0] == 0
    assert (
        db.execute("SELECT COUNT(*) FROM content_groups").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM content_audit_events").fetchone()[0],
        db.execute("SELECT COUNT(*) FROM legacy_content_mappings").fetchone()[0],
        tuple(
            _review(db, "articles", local_source_id)[column]
            for column in ("decision_action", "decision_at", "decision_source_checksum")
        ),
    ) == before


def test_existing_service_mapping_must_match_the_reviewed_service_code(db, tmp_path):
    source = db.execute(
        "SELECT * FROM services WHERE code='foundation_workshop'"
    ).fetchone()
    wrong_target = db.execute(
        "SELECT ci.id,cg.id AS group_id FROM content_items ci "
        "JOIN content_groups cg ON cg.id=ci.content_group_id "
        "JOIN services s ON s.id=cg.service_id "
        "WHERE ci.status='draft' AND ci.entry_type='service' AND s.code='data_insight'"
    ).fetchone()
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "services", source["id"])
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            target={"target_group": "foundation_workshop"},
        ),
    )
    db.execute(
        "INSERT INTO legacy_content_mappings "
        "(source_table,source_id,source_checksum,target_content_group_id,"
        "target_content_item_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
        (
            "services",
            source["id"],
            review["source_checksum"],
            wrong_target["group_id"],
            wrong_target["id"],
            "2026-08-26 10:00:00",
            "2026-08-26 10:00:00",
        ),
    )
    db.commit()

    result = migration.apply_legacy_decisions(
        db, decisions, actor="legacy_migration", now=NOW
    )

    assert result.errors == ("service_mapping_invalid",)
    assert result.target_ids == ()


def test_first_service_merge_requires_source_review_decision_and_target_to_match(
    db, tmp_path, monkeypatch, capsys
):
    source = db.execute(
        "SELECT * FROM services WHERE code='foundation_workshop'"
    ).fetchone()
    wrong_target = db.execute(
        "SELECT ci.id,ci.content_group_id,ci.lock_version FROM content_items ci "
        "JOIN content_groups cg ON cg.id=ci.content_group_id "
        "JOIN services s ON s.id=cg.service_id "
        "WHERE ci.status='draft' AND ci.entry_type='service' "
        "AND s.code='data_insight'"
    ).fetchone()
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    db.execute(
        "UPDATE legacy_content_reviews SET target_group='data_insight' "
        "WHERE source_table='services' AND source_id=?",
        (source["id"],),
    )
    db.commit()
    review = _review(db, "services", source["id"])
    initial_payload = _decision_payload(
        review, target={"target_group": "data_insight"}
    )
    initial = _load_decisions(tmp_path, initial_payload)
    approved_payload = _decision_payload(
        review,
        target={
            "target_group": "data_insight",
            "target_content_id": wrong_target["id"],
            "expected_lock_version": wrong_target["lock_version"],
            "merge_approved": True,
        },
    )
    approved = _load_decisions(tmp_path, approved_payload)
    decision_path = tmp_path / "service-four-way.jsonl"
    decision_path.write_text(
        json.dumps(initial_payload, ensure_ascii=False), encoding="utf-8"
    )
    service_rows = db.execute(
        "SELECT ci.id,ci.lock_version,ci.updated_at FROM content_items ci "
        "WHERE ci.id IN (?,?) ORDER BY ci.id",
        (
            db.execute(
                "SELECT ci.id FROM content_items ci "
                "JOIN content_groups cg ON cg.id=ci.content_group_id "
                "JOIN services s ON s.id=cg.service_id "
                "WHERE ci.status='draft' AND s.code='foundation_workshop'"
            ).fetchone()["id"],
            wrong_target["id"],
        ),
    ).fetchall()
    before_drafts = tuple(
        publishing_repository.load_content_draft(db, row["id"])
        for row in service_rows
    )
    before_rows = tuple(tuple(row) for row in service_rows)
    before_audit = db.execute(
        "SELECT COUNT(*) FROM content_audit_events"
    ).fetchone()[0]
    before_review = tuple(
        review[column]
        for column in ("decision_action", "decision_at", "decision_source_checksum")
    )

    preview = migration.preview_legacy_decisions(db, initial, now=NOW)
    applied = migration.apply_legacy_decisions(
        db, approved, actor="legacy_migration", now=NOW
    )

    assert preview.errors == ("service_mapping_invalid",)
    assert applied.errors == ("service_mapping_invalid",)
    assert tuple(
        publishing_repository.load_content_draft(db, row["id"])
        for row in service_rows
    ) == before_drafts
    assert tuple(
        tuple(
            db.execute(
                "SELECT id,lock_version,updated_at FROM content_items WHERE id=?",
                (row["id"],),
            ).fetchone()
        )
        for row in service_rows
    ) == before_rows
    assert db.execute(
        "SELECT COUNT(*) FROM legacy_content_mappings "
        "WHERE source_table='services' AND source_id=?",
        (source["id"],),
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events"
    ).fetchone()[0] == before_audit
    assert tuple(
        _review(db, "services", source["id"])[column]
        for column in ("decision_action", "decision_at", "decision_source_checksum")
    ) == before_review
    db.close()
    monkeypatch.setattr(manage, "shanghai_now", lambda: NOW)
    cli_code = manage.main(
        ["migrate-legacy-content", "--decisions", str(decision_path)]
    )
    captured = capsys.readouterr()
    assert cli_code == 1
    assert captured.err == ""
    assert '"status":"service_mapping_invalid"' in captured.out


def test_migration_result_jsonl_is_generic_and_omits_sensitive_decision_values(db, tmp_path):
    case_id = db.execute(
        "INSERT INTO cases (title,industry,pain_point,solution,result) VALUES (?,?,?,?,?)",
        ("匿名案例", "制造业", "问题", "方案", "结果"),
    ).lastrowid
    db.commit()
    _record_inventory(db)
    migration.check_legacy_sources(
        db, transport=SuccessfulTransport(db), actor="legacy_source_check", now=NOW
    )
    review = _review(db, "cases", case_id)
    secret = "合同私密编号-DO-NOT-OUTPUT"
    decisions = _load_decisions(
        tmp_path,
        _decision_payload(
            review,
            action="clean",
            target={
                "verification_code": "authorized_anonymous",
                "is_anonymized": 1,
                "basis_type": "client_authorization",
                "private_basis_reference": secret,
                "metrics": [],
            },
        ),
    )
    result = migration.preview_legacy_decisions(db, decisions, now=NOW)
    output = migration.migration_result_to_jsonl(result)
    assert secret not in output
    assert "private_basis_reference" not in output
    assert "?private=" not in output
    for line in output.splitlines():
        assert set(json.loads(line)) <= {
            "source_table", "source_id", "status", "target_content_id",
            "target_content_group_id", "target_lock_version", "preview",
        }


def _prepare_cli_article(tmp_path, monkeypatch):
    database_path = tmp_path / "cli-platform.db"
    monkeypatch.setattr(models, "DB_PATH", str(database_path))
    monkeypatch.setattr(manage, "shanghai_now", lambda: NOW)
    models.init_db()
    connection = models.get_db()
    article_id = _insert_article(connection, suffix="cli")
    _record_inventory(connection)
    migration.check_legacy_sources(
        connection,
        transport=SuccessfulTransport(connection),
        actor="legacy_source_check",
        now=NOW,
    )
    review = dict(_review(connection, "articles", article_id))
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    decision_path = tmp_path / "cli-decisions.jsonl"
    decision_path.write_text(
        json.dumps(
            _decision_payload(
                review,
                target={
                    "copyright_notice": "已获摘要展示许可",
                    "original_published_at": "2026-08-01 09:00:00",
                },
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return database_path, decision_path, article_id


def _fingerprints(directory):
    return {
        path.name: (path.stat().st_size, path.read_bytes())
        for path in directory.iterdir()
        if path.is_file()
    }


def test_migrate_cli_defaults_to_strong_readonly_preview_then_apply_uses_writable_db(
    tmp_path, monkeypatch, capsys
):
    database_path, decision_path, article_id = _prepare_cli_article(tmp_path, monkeypatch)
    before = _fingerprints(tmp_path)
    original_get_db = models.get_db

    def forbidden_write_open():
        raise AssertionError("dry-run must not open the writable connection")

    monkeypatch.setattr(models, "get_db", forbidden_write_open)
    assert manage.main(["migrate-legacy-content", "--decisions", str(decision_path)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert '"status":"ready"' in captured.out
    assert "?private=" not in captured.out
    assert _fingerprints(tmp_path) == before
    assert not Path(f"{database_path}-wal").exists()
    assert not Path(f"{database_path}-shm").exists()

    monkeypatch.setattr(models, "get_db", original_get_db)
    assert manage.main(
        ["migrate-legacy-content", "--decisions", str(decision_path), "--apply"]
    ) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert '"status":"migrated"' in captured.out
    verification = original_get_db()
    try:
        assert verification.execute(
            "SELECT COUNT(*) FROM legacy_content_mappings "
            "WHERE source_table='articles' AND source_id=?",
            (article_id,),
        ).fetchone()[0] == 1
    finally:
        verification.close()


def test_cli_errors_are_fixed_and_never_echo_decision_path_or_secret(
    tmp_path, monkeypatch, capsys
):
    database_path = tmp_path / "platform.db"
    database_path.write_bytes(b"not-a-database")
    monkeypatch.setattr(models, "DB_PATH", str(database_path))
    secret_path = tmp_path / "private-basis-DO-NOT-ECHO.jsonl"
    secret_path.write_text('{"private_basis_reference":"DO-NOT-ECHO"}', encoding="utf-8")

    assert manage.main(
        ["migrate-legacy-content", "--decisions", str(secret_path)]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error=legacy_migration_unavailable\n"
    assert "DO-NOT-ECHO" not in captured.err
    assert str(secret_path) not in captured.err


def test_cli_huge_source_id_returns_fixed_generic_error_without_traceback(
    tmp_path, monkeypatch, capsys
):
    _, decision_path, _ = _prepare_cli_article(tmp_path, monkeypatch)
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    payload["source_id"] = 9_223_372_036_854_775_808
    decision_path.write_text(json.dumps(payload), encoding="utf-8")

    assert manage.main(
        ["migrate-legacy-content", "--decisions", str(decision_path)]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error=legacy_migration_unavailable\n"
    assert "Traceback" not in captured.err


def test_cli_invalid_case_enum_returns_fixed_generic_error_without_writes(
    tmp_path, monkeypatch, capsys
):
    _, decision_path, _ = _prepare_cli_article(tmp_path, monkeypatch)
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    payload.update(
        {
            "source_table": "cases",
            "action": "clean",
            "target": {
                "verification_code": [],
                "is_anonymized": 1,
                "basis_type": "client_authorization",
                "private_basis_reference": "PRIVATE_ENUM_DO_NOT_ECHO",
                "metrics": [],
            },
        }
    )
    decision_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    before = _fingerprints(tmp_path)

    assert manage.main(
        ["migrate-legacy-content", "--decisions", str(decision_path)]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error=legacy_migration_unavailable\n"
    assert "Traceback" not in captured.err
    assert "PRIVATE_ENUM_DO_NOT_ECHO" not in captured.err
    assert _fingerprints(tmp_path) == before


@pytest.mark.parametrize("apply_args", ((), ("--apply",)))
@pytest.mark.parametrize("forbidden", ("\ud800", "\u202e", "\u0001"))
def test_cli_forbidden_unicode_is_generic_and_zero_write_in_preview_or_apply(
    tmp_path, monkeypatch, capsys, apply_args, forbidden
):
    _, decision_path, _ = _prepare_cli_article(tmp_path, monkeypatch)
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    payload["target"]["copyright_notice"] = f"PRIVATE_UNICODE{forbidden}VALUE"
    decision_path.write_text(
        json.dumps(payload, ensure_ascii=True), encoding="utf-8"
    )
    before = _fingerprints(tmp_path)

    assert manage.main(
        [
            "migrate-legacy-content",
            "--decisions",
            str(decision_path),
            *apply_args,
        ]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error=legacy_migration_unavailable\n"
    assert "Traceback" not in captured.err
    assert "PRIVATE_UNICODE" not in captured.err
    assert _fingerprints(tmp_path) == before


def test_cli_oversized_json_integer_is_a_fixed_generic_error(
    tmp_path, monkeypatch, capsys
):
    _, decision_path, _ = _prepare_cli_article(tmp_path, monkeypatch)
    decision_path.write_text(
        '{"version":' + "9" * 5_000 + "}", encoding="utf-8"
    )
    before = _fingerprints(tmp_path)

    assert manage.main(
        ["migrate-legacy-content", "--decisions", str(decision_path)]
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error=legacy_migration_unavailable\n"
    assert "Traceback" not in captured.err
    assert _fingerprints(tmp_path) == before


def test_check_sources_cli_registers_explicit_write_preflight_without_real_network(
    db, monkeypatch, capsys
):
    article_id = _insert_article(db, suffix="cli-check")
    _record_inventory(db)
    opened = []

    class BorrowedConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def close(self):
            pass

    def connection_factory():
        borrowed = BorrowedConnection(db)
        opened.append(borrowed)
        return borrowed

    class CliTransport(SuccessfulTransport):
        def __init__(self):
            super().__init__(db)

    monkeypatch.setattr(manage.models, "get_db", connection_factory)
    monkeypatch.setattr(manage, "PinnedHttpTransport", CliTransport)
    monkeypatch.setattr(manage.legacy_content_migration, "current_shanghai_datetime", lambda: NOW)

    assert manage.main(["check-content-sources"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "state=reachable" in captured.out
    assert "?private=" not in captured.out
    assert _review(db, "articles", article_id)["source_state"] == "reachable"
    assert opened


def test_check_sources_cli_rejects_unknown_transport_code_without_writes(
    db, monkeypatch, capsys
):
    article_id = _insert_article(db, suffix="cli-invalid-check-code")
    _record_inventory(db)

    class BorrowedConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def close(self):
            pass

    class InvalidCodeTransport:
        def fetch(self, url, **kwargs):
            assert db.in_transaction is False
            return FetchResult(
                False, "PRIVATE_UNKNOWN_CODE", url, None, None, b""
            )

    monkeypatch.setattr(manage.models, "get_db", lambda: BorrowedConnection(db))
    monkeypatch.setattr(manage, "PinnedHttpTransport", InvalidCodeTransport)
    monkeypatch.setattr(
        manage.legacy_content_migration, "current_shanghai_datetime", lambda: NOW
    )

    assert manage.main(["check-content-sources"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error=content_source_check_unavailable\n"
    assert "PRIVATE_UNKNOWN_CODE" not in captured.err
    review = _review(db, "articles", article_id)
    assert review["source_state"] == "unchecked"
    assert review["source_check_code"] is None
    assert review["check_source_checksum"] is None
