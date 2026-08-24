from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import sqlite3
from threading import Barrier, Thread

import pytest

import manage
import models
import publishing_repository
from content_clock import SHANGHAI
from content_contracts import CaseMetric, ContentBlock, ContentDraft, ContentRelation
from content_validation import ContentValidationError
from publishing_service import (
    ContentConflictError,
    ContentStateError,
    archive_content,
    copy_revision,
    create_content_draft,
    get_public_revision,
    publish_content,
    publish_due_content,
    refresh_content_source_check,
    resolve_public_revision,
    save_content_draft,
    schedule_content,
)


NOW = datetime(2026, 8, 24, 10, 0, 0, tzinfo=SHANGHAI)


def _announcement(slug="platform-news", **changes):
    values = {
        "entry_type": "announcement",
        "slug": slug,
        "title": "平台公告",
        "summary": "一条通过结构化校验的企业 AI 平台公告。",
        "seo_title": "平台公告",
        "seo_description": "查看企业 AI 转型平台的最新公告。",
        "extension": {
            "valid_from": "2026-08-24 00:00:00",
            "valid_until": "2026-09-24 00:00:00",
            "cta_url": "/assessment",
        },
        "blocks": (ContentBlock("rich_text", body_html="<p>公告正文</p>"),),
    }
    values.update(changes)
    return ContentDraft(**values)


def _resource(slug="source-report", *, source_url="https://example.com/report", check=None):
    source_hash = hashlib.sha256(source_url.encode()).hexdigest()
    check_values = check or {
        "source_check_code": "https_ok",
        "source_checked_at": "2026-08-24 09:00:00",
        "source_check_expires_at": "2026-08-31 09:00:00",
        "source_check_url_sha256": source_hash,
    }
    return ContentDraft(
        entry_type="resource",
        slug=slug,
        title="AI 转型报告",
        summary="已校验来源的中小企业 AI 转型报告。",
        seo_title="AI 转型报告",
        seo_description="阅读已审核的中小企业 AI 转型报告。",
        extension={
            "resource_type": "report",
            "is_original": 0,
            "source_name": "Example",
            "source_url": source_url,
            "source_url_sha256": source_hash,
            **check_values,
            "original_published_at": "2026-08-20 09:00:00",
            "copyright_notice": "转载请注明来源",
            "attachment_media_id": None,
        },
    )


def _row(db, content_id):
    return db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()


def test_caller_owned_insert_and_update_never_commit(db):
    db.execute("BEGIN IMMEDIATE")
    content_id = publishing_repository.insert_content_draft(
        db, _announcement(), actor="admin", now=NOW
    )
    updated = replace(_announcement(), title="未提交的更新")
    publishing_repository.update_content_draft(
        db, content_id, 1, updated, actor="admin", now=NOW
    )
    db.rollback()

    assert db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM content_audit_events").fetchone()[0] == 0


def test_publish_replaces_old_revision_atomically_and_copies_full_aggregate(db):
    first_id = create_content_draft(_announcement(), actor="admin", now=NOW)
    publish_content(first_id, 1, actor="admin", now=NOW)
    second_id = copy_revision(first_id, actor="admin", now=NOW + timedelta(seconds=1))

    copied = publishing_repository.load_content_draft(db, second_id)
    assert copied.blocks == (ContentBlock("rich_text", body_html="<p>公告正文</p>"),)
    assert dict(copied.extension) == dict(_announcement().extension)

    result = publish_content(second_id, 1, actor="admin", now=NOW + timedelta(seconds=2))

    assert result.published_id == second_id
    assert result.archived_id == first_id
    assert (_row(db, first_id)["status"], _row(db, second_id)["status"]) == (
        "archived",
        "published",
    )


def test_copy_preserves_media_maturity_and_relations(db):
    timestamp = "2026-08-24 09:00:00"
    media_id = db.execute(
        "INSERT INTO media_assets "
        "(storage_name,display_name,detected_mime,byte_size,sha256,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'pending',?,?)",
        ("copy-image.png", "copy-image.png", "image/png", 10, "a" * 64, timestamp, timestamp),
    ).lastrowid
    db.execute(
        "UPDATE media_assets SET status='ready',scan_result_code='clean',scan_checked_at=?,"
        "ready_at=?,updated_at=? WHERE id=?",
        (timestamp, timestamp, timestamp, media_id),
    )
    db.commit()
    target = create_content_draft(_resource("copy-target"), actor="admin", now=NOW)
    publish_content(target, 1, actor="admin", now=NOW)
    target_group = _row(db, target)["content_group_id"]
    scenario_id = db.execute(
        "SELECT id FROM scenarios WHERE status='published' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    aggregate = ContentDraft(
        entry_type="scenario",
        slug="copy-scenario",
        title="场景完整复制",
        summary="验证媒体、成熟度和关联关系在修订复制时保持不变。",
        seo_title="场景完整复制",
        seo_description="验证场景修订深复制的完整结构化内容。",
        share_image_media_id=media_id,
        extension={"scenario_id": scenario_id},
        blocks=(
            ContentBlock(
                "image_text",
                body_html="<p>图文内容</p>",
                settings={"alignment": "left", "alt_text": "场景示意图"},
                media_asset_id=media_id,
            ),
        ),
        relations=(ContentRelation("scenario_resource", target_group),),
        maturity_codes=("explore", "pilot"),
    )
    original = create_content_draft(aggregate, actor="admin", now=NOW)
    publish_content(original, 1, actor="admin", now=NOW)

    copied_id = copy_revision(original, actor="admin", now=NOW)
    copied = publishing_repository.load_content_draft(db, copied_id)

    assert copied.share_image_media_id == media_id
    assert copied.blocks == aggregate.blocks
    assert copied.relations == aggregate.relations
    assert copied.maturity_codes == ("explore", "pilot")


def test_archived_case_copy_preserves_extension_and_metrics(db):
    case = ContentDraft(
        entry_type="case",
        slug="verified-case-copy",
        title="经授权匿名案例",
        summary="一个通过内部交付记录验证的匿名客户案例。",
        seo_title="经授权匿名案例",
        seo_description="查看经授权且具备指标依据的匿名客户案例。",
        extension={
            "verification_code": "verified-internal-record",
            "is_anonymized": 1,
            "basis_type": "private_authorization",
            "private_basis_reference": "internal-delivery-record-001",
            "source_url": None,
            "source_url_sha256": None,
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "is_verified": 1,
            "review_confirmed": 1,
            "verified_at": "2026-08-24 09:00:00",
        },
        metrics=(
            CaseMetric(
                "报表处理时间", "8", "2", "小时", "连续 30 天",
                "由项目交付记录中的人工与自动化时长对比得出。",
            ),
        ),
    )
    original = create_content_draft(case, actor="admin", now=NOW)
    publish_content(original, 1, actor="admin", now=NOW)
    archive_content(original, 2, actor="admin", now=NOW)

    copied_id = copy_revision(original, actor="admin", now=NOW)
    copied = publishing_repository.load_content_draft(db, copied_id)

    assert dict(copied.extension) == dict(case.extension)
    assert copied.metrics == case.metrics
    assert _row(db, copied_id)["status"] == "draft"


def test_draft_copy_is_rejected_and_stale_lock_writes_nothing(db):
    content_id = create_content_draft(_announcement(), actor="admin", now=NOW)

    with pytest.raises(ContentStateError) as state_error:
        copy_revision(content_id, actor="admin", now=NOW)
    with pytest.raises(ContentConflictError):
        save_content_draft(content_id, 99, _announcement(), actor="admin", now=NOW)

    assert state_error.value.code == "copy_source_not_immutable"
    assert _row(db, content_id)["lock_version"] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE event_code='content_updated'"
    ).fetchone()[0] == 0


def test_publish_failure_rolls_back_old_revision_slug_and_audit(db, monkeypatch):
    first_id = create_content_draft(_announcement("old-slug"), actor="admin", now=NOW)
    publish_content(first_id, 1, actor="admin", now=NOW)
    second_id = copy_revision(first_id, actor="admin", now=NOW)
    draft = replace(publishing_repository.load_content_draft(db, second_id), slug="new-slug")
    save_content_draft(second_id, 1, draft, actor="admin", now=NOW)

    original = publishing_repository.write_audit_event

    def fail_publish_audit(connection, content_id, event_code, actor, now, details=None):
        if event_code == "content_published":
            raise sqlite3.OperationalError("simulated audit failure")
        return original(connection, content_id, event_code, actor, now, details)

    monkeypatch.setattr(publishing_repository, "write_audit_event", fail_publish_audit)
    with pytest.raises(sqlite3.OperationalError, match="simulated audit failure"):
        publish_content(second_id, 2, actor="admin", now=NOW)

    assert (_row(db, first_id)["status"], _row(db, second_id)["status"]) == (
        "published",
        "draft",
    )
    group = db.execute("SELECT canonical_slug FROM content_groups").fetchone()[0]
    assert group == "old-slug"
    assert db.execute("SELECT COUNT(*) FROM content_slug_aliases").fetchone()[0] == 0


def test_invalid_relation_keeps_old_revision_public(db):
    first_id = create_content_draft(_announcement("stable"), actor="admin", now=NOW)
    publish_content(first_id, 1, actor="admin", now=NOW)
    target_id = create_content_draft(_resource("draft-target"), actor="admin", now=NOW)
    target_group = _row(db, target_id)["content_group_id"]

    scenario_id = db.execute(
        "SELECT id FROM scenarios WHERE status='published' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    scenario = ContentDraft(
        entry_type="scenario",
        slug="scenario-editorial",
        title="场景编辑内容",
        summary="用于验证关联目标发布状态的场景内容。",
        seo_title="场景编辑内容",
        seo_description="用于验证内容发布关联的场景页面。",
        extension={"scenario_id": scenario_id},
        relations=(ContentRelation("scenario_resource", target_group, 0),),
        maturity_codes=("explore",),
    )
    invalid_id = create_content_draft(scenario, actor="admin", now=NOW)

    with pytest.raises(ContentValidationError) as error:
        publish_content(invalid_id, 1, actor="admin", now=NOW)

    assert error.value.code == "relation_target_not_published"
    assert _row(db, first_id)["status"] == "published"
    assert _row(db, invalid_id)["status"] == "draft"


def test_future_schedule_preserves_old_public_until_exact_due_second(db):
    first_id = create_content_draft(_announcement(), actor="admin", now=NOW)
    publish_content(first_id, 1, actor="admin", now=NOW)
    second_id = copy_revision(first_id, actor="admin", now=NOW)
    due = NOW + timedelta(hours=1)

    scheduled = schedule_content(second_id, 1, due, actor="admin", now=NOW)

    assert scheduled.publish_at == "2026-08-24 11:00:00"
    assert get_public_revision("announcement", "platform-news", due - timedelta(seconds=1))["id"] == first_id
    early = publish_due_content(now=due - timedelta(seconds=1))
    exact = publish_due_content(now=due)
    repeated = publish_due_content(now=due)
    assert early.published_ids == ()
    assert exact.published_ids == (second_id,)
    assert repeated.published_ids == ()
    assert get_public_revision("announcement", "platform-news", due)["id"] == second_id


def test_due_uses_injected_instant_even_when_host_clock_is_utc(db):
    content_id = create_content_draft(_announcement("utc-boundary"), actor="admin", now=NOW)
    due = datetime(2026, 8, 25, 0, 0, 0, tzinfo=SHANGHAI)
    schedule_content(content_id, 1, due, actor="admin", now=NOW)

    result = publish_due_content(now=datetime(2026, 8, 24, 16, 0, 0, tzinfo=timezone.utc))

    assert result.published_ids == (content_id,)


def test_schedule_rejects_source_check_that_expires_before_publish_time(db):
    content_id = create_content_draft(_resource(), actor="admin", now=NOW)

    with pytest.raises(ContentValidationError) as error:
        schedule_content(
            content_id,
            1,
            datetime(2026, 9, 1, 9, 0, 0, tzinfo=SHANGHAI),
            actor="admin",
            now=NOW,
        )

    assert error.value.code == "source_check_expires_before_publish"
    assert _row(db, content_id)["publish_at"] is None


def test_due_failure_is_isolated_and_records_only_safe_reason(db):
    target = create_content_draft(_resource("due-target"), actor="admin", now=NOW)
    publish_content(target, 1, actor="admin", now=NOW)
    target_group = _row(db, target)["content_group_id"]
    scenario_id = db.execute(
        "SELECT id FROM scenarios WHERE status='published' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    owner = ContentDraft(
        entry_type="scenario",
        slug="due-owner",
        title="定时场景内容",
        summary="发布前关联有效，到期时关联已归档的失败样本。",
        seo_title="定时场景内容",
        seo_description="测试定时发布的单条失败隔离能力。",
        extension={"scenario_id": scenario_id},
        relations=(ContentRelation("scenario_resource", target_group, 0),),
        maturity_codes=("pilot",),
    )
    invalid = create_content_draft(owner, actor="admin", now=NOW)
    valid = create_content_draft(_announcement("due-valid"), actor="admin", now=NOW)
    due = NOW + timedelta(hours=1)
    schedule_content(invalid, 1, due, actor="admin", now=NOW)
    schedule_content(valid, 1, due, actor="admin", now=NOW)
    archive_content(target, 2, actor="admin", now=NOW + timedelta(minutes=1))

    result = publish_due_content(now=due)

    assert result.published_ids == (valid,)
    assert result.failures == ((invalid, "validation_failed"),)
    assert _row(db, invalid)["status"] == "draft"
    assert _row(db, invalid)["publish_at"] is None
    details = db.execute(
        "SELECT details_json FROM content_audit_events "
        "WHERE content_item_id=? AND event_code='content_due_failed'",
        (invalid,),
    ).fetchone()[0]
    assert details == '{"reason_code":"validation_failed"}'


def test_due_failure_rolls_back_partial_archive_before_recording_safe_failure(db):
    old = create_content_draft(_announcement("due-old-name"), actor="admin", now=NOW)
    publish_content(old, 1, actor="admin", now=NOW)
    replacement = copy_revision(old, actor="admin", now=NOW)
    renamed = replace(
        publishing_repository.load_content_draft(db, replacement),
        slug="occupied-name",
    )
    save_content_draft(replacement, 1, renamed, actor="admin", now=NOW)
    occupied = create_content_draft(_announcement("occupied-name"), actor="admin", now=NOW)
    publish_content(occupied, 1, actor="admin", now=NOW)
    due = NOW + timedelta(hours=1)
    schedule_content(replacement, 2, due, actor="admin", now=NOW)

    result = publish_due_content(now=due)

    assert result.failures == ((replacement, "validation_failed"),)
    assert _row(db, old)["status"] == "published"
    assert _row(db, replacement)["status"] == "draft"
    assert _row(db, replacement)["publish_at"] is None
    group_slug = db.execute(
        "SELECT canonical_slug FROM content_groups WHERE id=?",
        (_row(db, old)["content_group_id"],),
    ).fetchone()[0]
    assert group_slug == "due-old-name"


def test_slug_rename_creates_alias_and_public_resolution_redirect(db):
    first = create_content_draft(_announcement("old-name"), actor="admin", now=NOW)
    publish_content(first, 1, actor="admin", now=NOW)
    second = copy_revision(first, actor="admin", now=NOW)
    save_content_draft(
        second,
        1,
        replace(publishing_repository.load_content_draft(db, second), slug="new-name"),
        actor="admin",
        now=NOW,
    )
    publish_content(second, 2, actor="admin", now=NOW)

    resolution = resolve_public_revision("announcement", "old-name", NOW)
    assert resolution.revision["id"] == second
    assert resolution.canonical_slug == "new-name"
    assert resolution.redirect is True
    with pytest.raises(ContentValidationError) as error:
        create_content_draft(_announcement("old-name"), actor="admin", now=NOW)
    assert error.value.code == "slug_conflict"


def test_public_lookup_excludes_draft_future_and_archived(db):
    draft = create_content_draft(_announcement("private-draft"), actor="admin", now=NOW)
    assert get_public_revision("announcement", "private-draft", NOW) is None
    publish_content(draft, 1, actor="admin", now=NOW)
    archive_content(draft, 2, actor="admin", now=NOW)
    assert get_public_revision("announcement", "private-draft", NOW) is None


def test_source_url_change_clears_prior_check_tuple(db):
    content_id = create_content_draft(_resource(), actor="admin", now=NOW)
    current = publishing_repository.load_content_draft(db, content_id)
    changed = _resource(source_url="https://example.com/new-report")

    save_content_draft(content_id, 1, changed, actor="admin", now=NOW)

    row = db.execute(
        "SELECT source_url_sha256,source_check_code,source_checked_at,"
        "source_check_expires_at,source_check_url_sha256 FROM resource_content "
        "WHERE content_item_id=?",
        (content_id,),
    ).fetchone()
    assert row["source_url_sha256"] != current.extension["source_url_sha256"]
    assert tuple(row)[1:] == (None, None, None, None)


def test_publish_requires_matching_current_unexpired_source_check(db):
    stale = _resource(
        check={
            "source_check_code": "https_ok",
            "source_checked_at": "2026-08-10 09:00:00",
            "source_check_expires_at": "2026-08-17 09:00:00",
            "source_check_url_sha256": "0" * 64,
        }
    )
    content_id = create_content_draft(stale, actor="admin", now=NOW)

    with pytest.raises(ContentValidationError) as error:
        publish_content(content_id, 1, actor="admin", now=NOW)

    assert error.value.code == "source_check_invalid"
    assert _row(db, content_id)["status"] == "draft"


def test_refresh_finishes_network_before_transaction_and_consumes_lock_once(db):
    unchecked = _resource(check={})
    content_id = create_content_draft(unchecked, actor="admin", now=NOW)
    source_hash = hashlib.sha256(b"https://example.com/report").hexdigest()

    class Transport:
        def fetch(self, url, **kwargs):
            probe = models.get_db()
            try:
                probe.execute("BEGIN IMMEDIATE")
                probe.rollback()
            finally:
                probe.close()
            from source_url_checker import FetchResult

            return FetchResult(True, "https_ok", url, 200, "text/html", b"ok")

    result = refresh_content_source_check(
        content_id,
        1,
        source_hash,
        actor="admin",
        transport=Transport(),
        now=NOW,
    )

    assert result.ok is True
    assert _row(db, content_id)["lock_version"] == 2
    with pytest.raises(ContentConflictError):
        refresh_content_source_check(
            content_id,
            1,
            source_hash,
            actor="admin",
            transport=Transport(),
            now=NOW,
        )
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events "
        "WHERE content_item_id=? AND event_code='content_source_checked'",
        (content_id,),
    ).fetchone()[0] == 1


def test_concurrent_copy_allocates_only_one_next_revision(db):
    first = create_content_draft(_announcement("concurrent-copy"), actor="admin", now=NOW)
    publish_content(first, 1, actor="admin", now=NOW)
    barrier = Barrier(2)
    outcomes = []

    def worker():
        barrier.wait()
        try:
            outcomes.append(copy_revision(first, actor="admin", now=NOW))
        except ContentConflictError as error:
            outcomes.append(error.code)

    threads = [Thread(target=worker), Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len([value for value in outcomes if isinstance(value, int)]) == 1
    assert outcomes.count("draft_already_exists") == 1
    group_id = _row(db, first)["content_group_id"]
    assert db.execute(
        "SELECT revision_number FROM content_items WHERE content_group_id=? AND status='draft'",
        (group_id,),
    ).fetchone()[0] == 2


def test_manage_publish_due_content_prints_only_counts_ids_and_safe_codes(
    db, capsys, monkeypatch
):
    content_id = create_content_draft(_announcement("cli-due"), actor="admin", now=NOW)
    schedule_content(content_id, 1, NOW + timedelta(hours=1), actor="admin", now=NOW)
    monkeypatch.setattr(
        "publishing_service.shanghai_now", lambda: NOW + timedelta(hours=1)
    )

    assert manage.main(["publish-due-content"]) == 0
    output = capsys.readouterr().out.strip()

    assert output == f"published_count=1 published_ids={content_id} failed_count=0 failures=none"
    assert "cli-due" not in output


def test_manage_publish_due_content_does_not_accept_an_operator_clock_override():
    with pytest.raises(SystemExit) as error:
        manage.main(
            ["publish-due-content", "--now", "2026-08-24T11:00:00+08:00"]
        )

    assert error.value.code == 2
