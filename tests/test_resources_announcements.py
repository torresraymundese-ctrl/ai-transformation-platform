from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import io
import json
import sqlite3

from bs4 import BeautifulSoup
from pypdf import PdfWriter
import pytest

import models
import blueprints.public_catalog as public_catalog_blueprint
from content_clock import SHANGHAI
from content_contracts import ContentBlock, ContentDraft, ContentRelation
from content_validation import ContentValidationError, validate_content_draft
from pagination import PageRequest
import publishing_repository
from publishing_service import (
    archive_content,
    copy_revision,
    create_content_draft,
    publish_content,
    publish_due_content,
    save_content_draft,
    schedule_content,
)
from source_url_checker import FetchResult


CSRF = "test-csrf-token"
NOW = datetime(2026, 8, 25, 10, 0, tzinfo=SHANGHAI)
RESOURCE_TYPES = {"article", "guide", "report", "template", "policy"}


def _resource_form(**overrides):
    form = {
        "csrf_token": CSRF,
        "action": "save",
        "slug": "reviewed-resource",
        "title": "经审核的企业 AI 指南",
        "summary": "只展示经人工审核的来源、版权和正文。",
        "seo_title": "企业 AI 指南",
        "seo_description": "查看经来源和版权审核的企业 AI 实施指南。",
        "share_image_media_id": "",
        "resource_type": "guide",
        "is_original": "1",
        "source_name": "",
        "source_url": "",
        "original_published_at": "2026-08-20T09:30",
        "copyright_notice": "本站原创，转载请保留版权说明。",
        "attachment_media_id": "",
        "review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "正文",
        "blocks-0-body": "<script>private-script</script><p>已审核资源正文</p>",
        "blocks-0-media_id": "",
    }
    form.update(overrides)
    return form


def _announcement_form(**overrides):
    form = {
        "csrf_token": CSRF,
        "action": "save",
        "slug": "current-announcement",
        "title": "当前公开公告",
        "summary": "只在固定有效期内公开。",
        "seo_title": "当前公开公告",
        "seo_description": "查看当前有效的企业 AI 平台公告。",
        "share_image_media_id": "",
        "valid_from": "2026-08-25T09:00",
        "valid_until": "2026-08-26T09:00",
        "cta_url": "https://example.com/notice?from=platform",
        "review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "公告正文",
        "blocks-0-body": "<script>private-announcement-script</script><p>已审核公告正文</p>",
        "blocks-0-media_id": "",
    }
    form.update(overrides)
    return form


def _latest_item(db, entry_type):
    row = db.execute(
        "SELECT * FROM content_items WHERE entry_type=? ORDER BY id DESC LIMIT 1",
        (entry_type,),
    ).fetchone()
    assert row is not None
    return row


def _create_resource(admin_client, db, **overrides):
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW
    admin_client.application.config["CONTENT_NOW_PROVIDER"] = lambda: NOW
    response = admin_client.post("/admin/resources/new", data=_resource_form(**overrides))
    assert response.status_code == 302
    return _latest_item(db, "resource")


def _create_announcement(admin_client, db, **overrides):
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW
    admin_client.application.config["CONTENT_NOW_PROVIDER"] = lambda: NOW
    response = admin_client.post(
        "/admin/announcements/new", data=_announcement_form(**overrides)
    )
    assert response.status_code == 302
    return _latest_item(db, "announcement")


def _edit_resource_form(db, content_id, **overrides):
    row = db.execute(
        "SELECT ci.*,rc.resource_type,rc.is_original,rc.source_name,rc.source_url,"
        "rc.original_published_at,rc.copyright_notice,rc.attachment_media_id "
        "FROM content_items ci JOIN resource_content rc ON rc.content_item_id=ci.id "
        "WHERE ci.id=?",
        (content_id,),
    ).fetchone()
    form = _resource_form(
        content_id=str(content_id),
        lock_version=str(row["lock_version"]),
        slug=row["slug"],
        title=row["title"],
        summary=row["summary"],
        seo_title=row["seo_title"],
        seo_description=row["seo_description"],
        share_image_media_id=str(row["share_image_media_id"] or ""),
        resource_type=row["resource_type"],
        is_original=str(row["is_original"]),
        source_name=row["source_name"] or "",
        source_url=row["source_url"] or "",
        original_published_at=(row["original_published_at"] or "").replace(" ", "T")[:-3],
        copyright_notice=row["copyright_notice"] or "",
        attachment_media_id=str(row["attachment_media_id"] or ""),
    )
    form.update(overrides)
    return form


def _edit_announcement_form(db, content_id, **overrides):
    row = db.execute(
        "SELECT ci.*,ac.valid_from,ac.valid_until,ac.cta_url "
        "FROM content_items ci JOIN announcement_content ac ON ac.content_item_id=ci.id "
        "WHERE ci.id=?",
        (content_id,),
    ).fetchone()
    form = _announcement_form(
        content_id=str(content_id),
        lock_version=str(row["lock_version"]),
        slug=row["slug"],
        title=row["title"],
        summary=row["summary"],
        seo_title=row["seo_title"],
        seo_description=row["seo_description"],
        share_image_media_id=str(row["share_image_media_id"] or ""),
        valid_from=(row["valid_from"] or "").replace(" ", "T")[:-3],
        valid_until=(row["valid_until"] or "").replace(" ", "T")[:-3],
        cta_url=row["cta_url"] or "",
    )
    form.update(overrides)
    return form


def _successful_transport():
    class SuccessfulTransport:
        def fetch(self, url, **kwargs):
            return FetchResult(True, "https_ok", url, 200, "text/html", b"ok")

    return SuccessfulTransport()


def _pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.metadata = None
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _upload_pdf(admin_client, db):
    response = admin_client.post(
        "/admin/media",
        data={
            "csrf_token": CSRF,
            "metadata_review_confirmed": "1",
            "file": (io.BytesIO(_pdf_bytes()), "reviewed-report.pdf", "application/pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    return db.execute(
        "SELECT * FROM media_assets WHERE detected_mime='application/pdf' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _insert_ready_asset(db, name, mime):
    digest = hashlib.sha256(name.encode()).hexdigest()
    asset_id = db.execute(
        "INSERT INTO media_assets (storage_name,display_name,detected_mime,byte_size,sha256,"
        "status,created_at,updated_at) VALUES (?,?,?,1,?,'pending',"
        "'2026-08-25 10:00:00','2026-08-25 10:00:00')",
        (name, name, mime, digest),
    ).lastrowid
    db.execute(
        "UPDATE media_assets SET status='ready',scan_result_code='safe',"
        "scan_checked_at='2026-08-25 10:00:00',ready_at='2026-08-25 10:00:00',"
        "updated_at='2026-08-25 10:00:00' WHERE id=?",
        (asset_id,),
    )
    db.commit()
    return asset_id


def _resource_draft(slug, *, copyright_notice="版权所有"):
    return ContentDraft(
        entry_type="resource",
        slug=slug,
        title=f"资源 {slug}",
        summary="经审核的资源摘要。",
        seo_title=f"资源 {slug}",
        seo_description="经审核的资源搜索摘要。",
        extension={
            "resource_type": "guide",
            "is_original": 1,
            "source_name": None,
            "source_url": None,
            "source_url_sha256": None,
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "original_published_at": "2026-08-20 09:30:00",
            "copyright_notice": copyright_notice,
            "attachment_media_id": None,
        },
        blocks=(ContentBlock("rich_text", "正文", "<p>公开资源</p>", {}, None, 0),),
    )


def _announcement_draft(slug):
    return ContentDraft(
        entry_type="announcement",
        slug=slug,
        title=f"公告 {slug}",
        summary="固定有效期公告。",
        seo_title=f"公告 {slug}",
        seo_description="固定有效期公开公告。",
        extension={
            "valid_from": "2026-08-25 09:00:00",
            "valid_until": "2026-08-27 09:00:00",
            "cta_url": "/assessment",
        },
        blocks=(ContentBlock("rich_text", "正文", "<p>公开公告</p>", {}, None, 0),),
    )


def _publish_related_resource(db, slug, *, title, sourced=False):
    if sourced:
        source_url = f"https://example.com/{slug}"
        source_hash = hashlib.sha256(source_url.encode()).hexdigest()
        draft = replace(
            _resource_draft(slug),
            title=title,
            seo_title=title,
            extension={
                **dict(_resource_draft(slug).extension),
                "is_original": 0,
                "source_name": "公开来源",
                "source_url": source_url,
                "source_url_sha256": source_hash,
                "original_published_at": "2026-08-18 09:00:00",
                "copyright_notice": "原文版权归公开来源所有。",
            },
        )
        published_at = datetime(2026, 8, 18, 10, 0, 0, tzinfo=SHANGHAI)
    else:
        draft = replace(_resource_draft(slug), title=title, seo_title=title)
        published_at = NOW
        source_hash = None
    content_id = create_content_draft(
        draft, actor="test-admin", now=published_at
    )
    if sourced:
        db.execute(
            "UPDATE resource_content SET source_check_code='https_ok',"
            "source_checked_at='2026-08-18 10:00:00',"
            "source_check_expires_at='2099-01-01 00:00:00',"
            "source_check_url_sha256=? WHERE content_item_id=?",
            (source_hash, content_id),
        )
        db.commit()
    publish_content(content_id, 1, actor="test-admin", now=published_at)
    return db.execute(
        "SELECT id,content_group_id,slug,title,lock_version FROM content_items WHERE id=?",
        (content_id,),
    ).fetchone()


def _content_owner_row(db, owner_kind):
    config = {
        "service": ("services", "service_id", "foundation_workshop"),
        "scenario": ("scenarios", "scenario_id", "mfg_knowledge_assistant"),
        "industry": ("industries", "industry_id", "manufacturing"),
    }
    table, identity, code = config[owner_kind]
    return db.execute(
        "SELECT ci.* FROM content_items ci JOIN content_groups g "
        f"ON g.id=ci.content_group_id JOIN {table} core ON core.id=g.{identity} "
        "WHERE ci.entry_type=? AND ci.status='draft' AND core.code=?",
        (owner_kind, code),
    ).fetchone()


def _publish_owner_with_resources(db, owner_kind, resources):
    if owner_kind == "industry":
        scenario = _content_owner_row(db, "scenario")
        publish_content(
            scenario["id"],
            scenario["lock_version"],
            actor="test-admin",
            now=NOW,
        )
    owner = _content_owner_row(db, owner_kind)
    draft = publishing_repository.load_content_draft(db, owner["id"])
    existing = tuple(
        relation
        for relation in draft.relations
        if relation.relation_type != f"{owner_kind}_resource"
    )
    relations = existing + tuple(
        ContentRelation(f"{owner_kind}_resource", resource["content_group_id"])
        for resource in resources
    )
    lock_version = save_content_draft(
        owner["id"],
        owner["lock_version"],
        replace(draft, relations=relations),
        actor="test-admin",
        now=NOW,
    )
    publish_content(
        owner["id"], lock_version, actor="test-admin", now=NOW
    )
    path = {
        "service": f"/service-packages/{owner['slug']}",
        "scenario": f"/scenarios/{owner['slug']}",
        "industry": f"/industries/{owner['slug']}",
    }[owner_kind]
    return path


def test_v2_routes_have_single_owners_and_remove_legacy_admin_writers(
    client, admin_client
):
    expected = {
        "/admin/resources": "admin.admin_resources_v2",
        "/admin/resources/new": "admin.admin_resource_new_v2",
        "/admin/resources/<int:content_id>": "admin.admin_resource_edit_v2",
        "/admin/resources/<int:content_id>/source-check": "admin.admin_resource_source_check_v2",
        "/admin/resources/<int:content_id>/copy": "admin.admin_resource_copy_v2",
        "/admin/announcements": "admin.admin_announcements_v2",
        "/admin/announcements/new": "admin.admin_announcement_new_v2",
        "/admin/announcements/<int:content_id>": "admin.admin_announcement_edit_v2",
        "/admin/announcements/<int:content_id>/copy": "admin.admin_announcement_copy_v2",
        "/resources": "public_catalog.resources_page",
        "/resources/<slug>": "public_catalog.resource_detail",
        "/announcements/<slug>": "public_catalog.announcement_detail",
    }
    rules = list(client.application.url_map.iter_rules())
    for path, endpoint in expected.items():
        matches = [rule for rule in rules if rule.rule == path]
        assert len(matches) == 1
        assert matches[0].endpoint == endpoint
        assert sum(rule.endpoint == endpoint for rule in rules) == 1
    assert not {
        "admin.admin_articles",
        "admin.admin_article_new",
        "admin.admin_article_edit",
        "admin.admin_announcement_new",
        "admin.admin_announcement_edit",
        "admin.admin_announcements",
    } & {rule.endpoint for rule in rules}

    anonymous = client.application.test_client().get("/admin/resources")
    assert anonymous.status_code == 302
    assert "/admin/login" in anonymous.headers["Location"]
    assert admin_client.get("/admin/resources").status_code == 200
    assert admin_client.get("/admin/announcements").status_code == 200
    assert admin_client.get("/admin/article/new").status_code == 404
    dashboard = admin_client.get("/admin").get_data(as_text=True)
    assert 'href="/admin/resources"' in dashboard
    assert 'href="/admin/articles"' not in dashboard


def test_resource_editor_is_choice_first_and_has_exact_schema(admin_client):
    response = admin_client.get("/admin/resources/new")
    assert response.status_code == 200
    document = BeautifulSoup(response.data, "html.parser")
    assert {
        option["value"]
        for option in document.select('select[name="resource_type"] option[value]')
    } == RESOURCE_TYPES
    assert {
        option["value"]
        for option in document.select('select[name="is_original"] option[value]')
    } == {"0", "1"}
    assert document.select_one("[data-original-fields]") is not None
    assert document.select_one("[data-sourced-fields]") is not None
    assert document.select_one('input[name="author"]') is None
    assert document.select_one('input[name="contact_email"]') is None


def test_resource_and_announcement_editors_preserve_exact_shanghai_seconds(
    admin_client
):
    resource = _resource_draft("second-precision-resource")
    resource = replace(
        resource,
        extension={
            **resource.extension,
            "original_published_at": "2026-08-20 09:30:17",
        },
    )
    resource_id = create_content_draft(resource, actor="test-admin", now=NOW)
    announcement = _announcement_draft("second-precision-announcement")
    announcement = replace(
        announcement,
        extension={
            **announcement.extension,
            "valid_from": "2026-08-25 09:00:17",
            "valid_until": "2026-08-27 09:00:29",
        },
    )
    announcement_id = create_content_draft(
        announcement, actor="test-admin", now=NOW
    )

    resource_document = BeautifulSoup(
        admin_client.get(f"/admin/resources/{resource_id}").data, "html.parser"
    )
    announcement_document = BeautifulSoup(
        admin_client.get(f"/admin/announcements/{announcement_id}").data,
        "html.parser",
    )
    original_time = resource_document.select_one(
        'input[name="original_published_at"]'
    )
    valid_from = announcement_document.select_one('input[name="valid_from"]')
    valid_until = announcement_document.select_one('input[name="valid_until"]')
    assert (original_time["value"], original_time["step"]) == (
        "2026-08-20T09:30:17", "1"
    )
    assert (valid_from["value"], valid_from["step"]) == (
        "2026-08-25T09:00:17", "1"
    )
    assert (valid_until["value"], valid_until["step"]) == (
        "2026-08-27T09:00:29", "1"
    )


@pytest.mark.parametrize("resource_type", sorted(RESOURCE_TYPES))
def test_each_exact_resource_type_can_publish_as_reviewed_original(
    admin_client, db, resource_type
):
    slug = f"reviewed-{resource_type}"
    response = admin_client.post(
        "/admin/resources/new",
        data=_resource_form(
            action="publish", resource_type=resource_type, slug=slug,
            title=f"审核资源 {resource_type}",
        ),
    )
    assert response.status_code == 302
    row = db.execute(
        "SELECT ci.status,rc.resource_type,rc.original_published_at "
        "FROM content_items ci JOIN resource_content rc ON rc.content_item_id=ci.id "
        "WHERE ci.slug=?",
        (slug,),
    ).fetchone()
    assert tuple(row) == ("published", resource_type, "2026-08-20 09:30:00")
    assert admin_client.get(f"/resources/{slug}").status_code == 200


def test_resource_rejects_invalid_type_authorship_source_and_copyright(
    admin_client, db
):
    attempts = (
        _resource_form(action="publish", resource_type="announcement"),
        _resource_form(action="publish", copyright_notice=" \t "),
        _resource_form(action="publish", copyright_notice="copyright\x00hidden"),
        _resource_form(
            action="publish", is_original="0", source_name="", source_url="",
        ),
        _resource_form(
            action="publish", is_original="0", source_name="source\x00hidden",
            source_url="https://example.com/a",
        ),
        _resource_form(
            action="publish", is_original="0", source_name="来源", source_url="http://example.com/a",
        ),
        _resource_form(
            action="publish", is_original="1", source_name="虚构作者", source_url="https://example.com/a",
        ),
        _resource_form(action="publish", original_published_at=""),
        _resource_form(action="publish", author="自然人姓名"),
    )
    before = db.execute(
        "SELECT COUNT(*) FROM content_items WHERE entry_type='resource'"
    ).fetchone()[0]
    for form in attempts:
        response = admin_client.post("/admin/resources/new", data=form)
        assert response.status_code == 400
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE entry_type='resource'"
    ).fetchone()[0] == before


@pytest.mark.parametrize(
    ("checked_at", "expires_at", "expected_status"),
    (
        ("2026-08-18 10:00:00", "2026-08-25 10:00:00", 302),
        ("2026-08-18 09:59:59", "2026-08-25 10:00:01", 400),
        ("2026-08-25 10:00:01", "2026-09-01 10:00:01", 400),
        ("2026-08-25 10:00:00", "2026-08-25 09:59:59", 400),
    ),
)
def test_sourced_resource_source_check_time_boundaries_are_exact(
    admin_client, db, checked_at, expires_at, expected_status
):
    slug = "source-boundary-" + hashlib.sha256(
        f"{checked_at}-{expires_at}".encode()
    ).hexdigest()[:10]
    source_url = f"https://example.com/{slug}"
    draft = _create_resource(
        admin_client,
        db,
        slug=slug,
        is_original="0",
        source_name="公开来源",
        source_url=source_url,
    )
    source_hash = hashlib.sha256(source_url.encode()).hexdigest()
    db.execute(
        "UPDATE resource_content SET source_check_code='https_ok',source_checked_at=?,"
        "source_check_expires_at=?,source_check_url_sha256=? WHERE content_item_id=?",
        (checked_at, expires_at, source_hash, draft["id"]),
    )
    db.commit()
    response = admin_client.post(
        f"/admin/resources/{draft['id']}",
        data=_edit_resource_form(db, draft["id"], action="publish"),
    )
    assert response.status_code == expected_status
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (draft["id"],)
    ).fetchone()[0] == ("published" if expected_status == 302 else "draft")


def test_sourced_resource_requires_fresh_exact_source_check_and_renders_safe_link(
    client, admin_client, db
):
    source_url = "https://Example.COM/research/../reviewed?b=2&a=1"
    draft = _create_resource(
        admin_client,
        db,
        slug="sourced-report",
        resource_type="report",
        is_original="0",
        source_name="公开研究机构",
        source_url=source_url,
        copyright_notice="原文版权归公开研究机构所有。",
    )
    extension = db.execute(
        "SELECT * FROM resource_content WHERE content_item_id=?", (draft["id"],)
    ).fetchone()
    assert extension["source_url"].startswith("https://example.com/")
    source_hash = hashlib.sha256(extension["source_url"].encode()).hexdigest()
    without_check = admin_client.post(
        f"/admin/resources/{draft['id']}",
        data=_edit_resource_form(db, draft["id"], action="publish"),
    )
    assert without_check.status_code == 400

    source_form = {
        "csrf_token": CSRF,
        "expected_lock_version": str(draft["lock_version"]),
        "expected_url_sha256": source_hash,
    }
    assert client.application.test_client().post(
        f"/admin/resources/{draft['id']}/source-check", data=source_form
    ).status_code == 302
    assert admin_client.post(
        f"/admin/resources/{draft['id']}/source-check",
        data={key: value for key, value in source_form.items() if key != "csrf_token"},
    ).status_code == 403
    admin_client.application.config["RESOURCE_SOURCE_TRANSPORT"] = _successful_transport()
    checked = admin_client.post(
        f"/admin/resources/{draft['id']}/source-check", data=source_form
    )
    assert checked.status_code == 302
    check = db.execute(
        "SELECT source_check_code,source_checked_at,source_check_expires_at,"
        "source_check_url_sha256 FROM resource_content WHERE content_item_id=?",
        (draft["id"],),
    ).fetchone()
    assert tuple(check) == (
        "https_ok", "2026-08-25 10:00:00", "2026-09-01 10:00:00", source_hash
    )
    published = admin_client.post(
        f"/admin/resources/{draft['id']}",
        data=_edit_resource_form(db, draft["id"], action="publish"),
    )
    assert published.status_code == 302
    listing = client.get("/resources")
    detail = client.get("/resources/sourced-report")
    assert listing.status_code == 200
    assert detail.status_code == 200
    assert BeautifulSoup(listing.data, "html.parser").select_one(
        'link[rel="canonical"]'
    )["href"] == "https://test.example/resources"
    document = BeautifulSoup(detail.data, "html.parser")
    source = document.select_one("a[data-resource-source]")
    canonical = document.select_one('link[rel="canonical"]')
    assert canonical["href"] == "https://test.example/resources/sourced-report"
    assert source["href"] == extension["source_url"]
    assert source["target"] == "_blank"
    assert source["rel"] == ["noopener", "noreferrer"]
    text = detail.get_data(as_text=True)
    assert "公开研究机构" in text
    assert "原文版权归公开研究机构所有" in text
    assert "private-script" not in text
    assert "source_url_sha256" not in text
    assert "source_check_code" not in text
    assert "contact_email" not in text


def test_failed_resource_source_check_is_generic_and_cannot_publish(
    admin_client, db
):
    source_url = "https://example.com/reviewed?token=must-not-leak"
    draft = _create_resource(
        admin_client,
        db,
        slug="failed-resource-source-check",
        is_original="0",
        source_name="公开来源",
        source_url=source_url,
    )
    extension = db.execute(
        "SELECT source_url,source_url_sha256 FROM resource_content "
        "WHERE content_item_id=?",
        (draft["id"],),
    ).fetchone()

    class FailedTransport:
        def fetch(self, url, **kwargs):
            return FetchResult(False, "network_error", url, None, None, b"")

    admin_client.application.config["RESOURCE_SOURCE_TRANSPORT"] = FailedTransport()
    response = admin_client.post(
        f"/admin/resources/{draft['id']}/source-check",
        data={
            "csrf_token": CSRF,
            "expected_lock_version": str(draft["lock_version"]),
            "expected_url_sha256": extension["source_url_sha256"],
        },
    )

    assert response.status_code == 302
    assert "must-not-leak" not in response.get_data(as_text=True)
    state = db.execute(
        "SELECT ci.status,ci.lock_version,rc.source_check_code "
        "FROM content_items ci JOIN resource_content rc ON rc.content_item_id=ci.id "
        "WHERE ci.id=?",
        (draft["id"],),
    ).fetchone()
    assert tuple(state) == ("draft", draft["lock_version"] + 1, "network_error")
    audit_text = " ".join(
        str(value)
        for row in db.execute(
            "SELECT action,status_code,ip_hash FROM admin_audit_logs"
        )
        for value in row
    )
    event_text = " ".join(
        str(value)
        for row in db.execute(
            "SELECT event_code,details_json FROM content_audit_events "
            "WHERE content_item_id=?",
            (draft["id"],),
        )
        for value in row
    )
    assert "must-not-leak" not in audit_text
    assert "must-not-leak" not in event_text
    assert "network_error" in event_text

    rejected = admin_client.post(
        f"/admin/resources/{draft['id']}",
        data=_edit_resource_form(db, draft["id"], action="publish"),
    )
    assert rejected.status_code == 400
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (draft["id"],)
    ).fetchone()[0] == "draft"


def test_resource_source_check_concurrent_edit_rolls_back_check_only(admin_client, db):
    old_url = "https://example.com/original-resource"
    new_url = "https://example.com/edited-resource"
    draft = _create_resource(
        admin_client,
        db,
        slug="resource-source-race",
        is_original="0",
        source_name="公开来源",
        source_url=old_url,
    )
    old_hash = hashlib.sha256(old_url.encode()).hexdigest()

    class ConcurrentEditTransport:
        def fetch(self, url, **kwargs):
            connection = models.get_db()
            try:
                current = publishing_repository.load_content_draft(connection, draft["id"])
                lock = connection.execute(
                    "SELECT lock_version FROM content_items WHERE id=?", (draft["id"],)
                ).fetchone()[0]
            finally:
                connection.close()
            extension = dict(current.extension)
            extension["source_url"] = new_url
            extension["source_url_sha256"] = hashlib.sha256(new_url.encode()).hexdigest()
            save_content_draft(
                draft["id"], lock, replace(current, extension=extension),
                actor="concurrent-admin", now=NOW,
            )
            return FetchResult(True, "https_ok", url, 200, "text/html", b"ok")

    admin_client.application.config["RESOURCE_SOURCE_TRANSPORT"] = ConcurrentEditTransport()
    response = admin_client.post(
        f"/admin/resources/{draft['id']}/source-check",
        data={
            "csrf_token": CSRF,
            "expected_lock_version": str(draft["lock_version"]),
            "expected_url_sha256": old_hash,
        },
    )
    assert response.status_code == 409
    row = db.execute(
        "SELECT ci.lock_version,rc.* FROM content_items ci JOIN resource_content rc "
        "ON rc.content_item_id=ci.id WHERE ci.id=?", (draft["id"],)
    ).fetchone()
    assert row["source_url"] == new_url
    assert row["lock_version"] == draft["lock_version"] + 1
    assert tuple(row[key] for key in (
        "source_check_code", "source_checked_at", "source_check_expires_at",
        "source_check_url_sha256",
    )) == (None, None, None, None)
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_source_checked'", (draft["id"],)
    ).fetchone()[0] == 0


def test_resource_attachment_must_be_ready_and_uses_published_download_route(
    admin_client, db
):
    asset = _upload_pdf(admin_client, db)
    response = admin_client.post(
        "/admin/resources/new",
        data=_resource_form(
            action="publish",
            slug="resource-with-attachment",
            resource_type="report",
            attachment_media_id=str(asset["id"]),
        ),
    )
    assert response.status_code == 302
    detail = admin_client.get("/resources/resource-with-attachment")
    assert detail.status_code == 200
    assert f'/media/{asset["id"]}/download' in detail.get_data(as_text=True)
    download = admin_client.get(f'/media/{asset["id"]}/download')
    assert download.status_code == 200
    assert download.headers["Content-Type"].startswith("application/pdf")
    assert download.headers["Content-Disposition"].startswith("attachment;")

    db.execute("PRAGMA foreign_keys=OFF")
    pending_id = db.execute(
        "INSERT INTO media_assets (storage_name,display_name,detected_mime,byte_size,sha256,"
        "status,created_at,updated_at) VALUES ('pending-task9.pdf','pending.pdf',"
        "'application/pdf',1,?,'pending','2026-08-25 10:00:00','2026-08-25 10:00:00')",
        ("f" * 64,),
    ).lastrowid
    db.commit()
    rejected = admin_client.post(
        "/admin/resources/new",
        data=_resource_form(
            action="publish", slug="pending-resource-attachment",
            attachment_media_id=str(pending_id),
        ),
    )
    assert rejected.status_code == 400
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE slug='pending-resource-attachment'"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("mime", "accepted"),
    (
        ("application/pdf", True),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            True,
        ),
        (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            True,
        ),
        ("image/png", False),
    ),
)
def test_resource_attachment_requires_ready_attachment_mime(
    admin_client, db, mime, accepted
):
    media_id = _insert_ready_asset(db, f"task9-{mime.rsplit('/', 1)[-1]}.bin", mime)
    slug = f"attachment-mime-{media_id}"
    response = admin_client.post(
        "/admin/resources/new",
        data=_resource_form(
            action="publish", slug=slug, attachment_media_id=str(media_id)
        ),
    )
    assert response.status_code == (302 if accepted else 400)
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE slug=? AND status='published'", (slug,)
    ).fetchone()[0] == (1 if accepted else 0)


def test_external_cta_is_safe_and_internal_cta_stays_same_window(admin_client, db):
    resource = _create_resource(
        admin_client,
        db,
        slug="external-resource-cta",
        **{
            "blocks-0-type": "cta",
            "blocks-0-title": "继续阅读",
            "blocks-0-body": "<p>说明</p>",
            "blocks-0-media_id": "",
            "blocks-0-cta_label": "访问公开材料",
            "blocks-0-cta_url": "https://example.com/material",
            "blocks-0-cta_style": "secondary",
        },
    )
    assert admin_client.post(
        f"/admin/resources/{resource['id']}",
        data=_edit_resource_form(
            db,
            resource["id"],
            action="publish",
            **{
                "blocks-0-type": "cta",
                "blocks-0-title": "继续阅读",
                "blocks-0-body": "<p>说明</p>",
                "blocks-0-media_id": "",
                "blocks-0-cta_label": "访问公开材料",
                "blocks-0-cta_url": "https://example.com/material",
                "blocks-0-cta_style": "secondary",
            },
        ),
    ).status_code == 302
    external = BeautifulSoup(
        admin_client.get("/resources/external-resource-cta").data, "html.parser"
    ).select_one('[data-content-block="cta"] a')
    assert external["target"] == "_blank"
    assert external["rel"] == ["noopener", "noreferrer"]

    announcement = _create_announcement(
        admin_client, db, action="publish", slug="internal-announcement-cta",
        cta_url="/assessment",
    )
    assert announcement["status"] == "published"
    internal = BeautifulSoup(
        admin_client.get("/announcements/internal-announcement-cta").data,
        "html.parser",
    ).select_one("a[data-announcement-cta]")
    assert internal["href"] == "/assessment"
    assert internal.get("target") is None
    assert internal.get("rel") is None


def test_announcement_fixed_interval_current_future_expired_and_archived_are_exact(
    admin_client, db
):
    current = _create_announcement(admin_client, db, action="publish")
    current_response = admin_client.get("/announcements/current-announcement")
    assert current_response.status_code == 200
    current_document = BeautifulSoup(current_response.data, "html.parser")
    assert current_document.select_one('link[rel="canonical"]')["href"] == (
        "https://test.example/announcements/current-announcement"
    )
    cta = current_document.select_one("a[data-announcement-cta]")
    assert cta["target"] == "_blank"
    assert cta["rel"] == ["noopener", "noreferrer"]
    current_text = current_response.get_data(as_text=True)
    assert "已审核公告正文" in current_text
    assert "private-announcement-script" not in current_text

    future = _create_announcement(
        admin_client,
        db,
        action="publish",
        slug="future-announcement",
        title="FUTURE-ANNOUNCEMENT-SECRET",
        valid_from="2026-08-25T11:00",
        valid_until="2026-08-26T11:00",
    )
    future_response = admin_client.get(f"/announcements/{future['slug']}")
    assert future_response.status_code == 404
    assert b"FUTURE-ANNOUNCEMENT-SECRET" not in future_response.data

    expiring = _create_announcement(
        admin_client,
        db,
        action="publish",
        slug="expired-announcement",
        title="EXPIRED-ANNOUNCEMENT-SECRET",
    )
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW + timedelta(days=2)
    admin_client.application.config["CONTENT_NOW_PROVIDER"] = lambda: NOW + timedelta(days=2)
    expired_response = admin_client.get(f"/announcements/{expiring['slug']}")
    assert expired_response.status_code == 404
    assert b"EXPIRED-ANNOUNCEMENT-SECRET" not in expired_response.data
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW

    archive_response = admin_client.post(
        f"/admin/announcements/{current['id']}",
        data={
            "csrf_token": CSRF,
            "action": "archive",
            "content_id": str(current["id"]),
            "lock_version": str(current["lock_version"]),
        },
    )
    assert archive_response.status_code == 302
    archived = admin_client.get("/announcements/current-announcement")
    assert archived.status_code == 404
    assert "当前公开公告" not in archived.get_data(as_text=True)


def test_original_resource_hides_source_and_nonpublic_states_never_leak(
    client, admin_client, db
):
    original = _create_resource(
        admin_client,
        db,
        action="publish",
        slug="original-resource-no-source",
        title="本站原创公开资源",
    )
    original_response = client.get("/resources/original-resource-no-source")
    original_document = BeautifulSoup(original_response.data, "html.parser")
    assert original_response.status_code == 200
    assert original_document.select_one("[data-resource-source]") is None
    assert "本站原创" in original_response.get_data(as_text=True)

    draft = _create_resource(
        admin_client,
        db,
        slug="private-draft-resource",
        title="PRIVATE-DRAFT-RESOURCE-SECRET",
    )
    future = _create_resource(
        admin_client,
        db,
        slug="future-resource",
        title="FUTURE-RESOURCE-SECRET",
    )
    schedule_content(
        future["id"], future["lock_version"], NOW + timedelta(hours=1),
        actor="test-admin", now=NOW,
    )
    archived = _create_resource(
        admin_client,
        db,
        action="publish",
        slug="archived-resource",
        title="ARCHIVED-RESOURCE-SECRET",
    )
    archived_response = admin_client.post(
        f"/admin/resources/{archived['id']}",
        data={
            "csrf_token": CSRF,
            "action": "archive",
            "content_id": str(archived["id"]),
            "lock_version": str(archived["lock_version"]),
        },
    )
    assert archived_response.status_code == 302

    listing = client.get("/resources")
    listing_text = listing.get_data(as_text=True)
    for row, secret in (
        (draft, "PRIVATE-DRAFT-RESOURCE-SECRET"),
        (future, "FUTURE-RESOURCE-SECRET"),
        (archived, "ARCHIVED-RESOURCE-SECRET"),
    ):
        response = client.get(f"/resources/{row['slug']}")
        assert response.status_code == 404
        assert secret not in response.get_data(as_text=True)
        assert secret not in listing_text


def test_resource_edit_uses_optimistic_lock_and_rolls_back_submitted_payload(
    admin_client, db
):
    draft = _create_resource(
        admin_client, db, slug="resource-lock-conflict"
    )
    stale_form = _edit_resource_form(
        db, draft["id"], title="冲突时保留的资源标题"
    )
    before_events = db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=?",
        (draft["id"],),
    ).fetchone()[0]
    db.execute(
        "UPDATE content_items SET title='并发资源标题',lock_version=lock_version+1 "
        "WHERE id=?",
        (draft["id"],),
    )
    db.commit()

    response = admin_client.post(
        f"/admin/resources/{draft['id']}", data=stale_form
    )

    assert response.status_code == 409
    assert "冲突时保留的资源标题" in response.get_data(as_text=True)
    current = db.execute(
        "SELECT title FROM content_items WHERE id=?", (draft["id"],)
    ).fetchone()[0]
    assert current == "并发资源标题"
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=?",
        (draft["id"],),
    ).fetchone()[0] == before_events


def test_published_resource_is_immutable_and_copy_post_is_exact(
    client, admin_client, db
):
    published = _create_resource(
        admin_client, db, action="publish", slug="immutable-resource"
    )
    before_items = db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
    before_events = db.execute(
        "SELECT COUNT(*) FROM content_audit_events"
    ).fetchone()[0]

    immutable = admin_client.get(f"/admin/resources/{published['id']}")
    assert immutable.status_code == 200
    document = BeautifulSoup(immutable.data, "html.parser")
    assert document.select_one("form[data-content-editor]") is None
    copy_form = document.select_one(
        f'form[action="/admin/resources/{published["id"]}/copy"]'
    )
    assert copy_form is not None
    assert db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == before_items
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events"
    ).fetchone()[0] == before_events

    path = f"/admin/resources/{published['id']}/copy"
    valid = {
        "csrf_token": CSRF,
        "content_id": str(published["id"]),
        "expected_lock_version": str(published["lock_version"]),
    }
    anonymous = client.application.test_client().post(path, data=valid)
    missing_csrf = admin_client.post(
        path, data={key: value for key, value in valid.items() if key != "csrf_token"}
    )
    wrong_identity = admin_client.post(
        path, data={**valid, "content_id": str(published["id"] + 1)}
    )
    stale = admin_client.post(
        path, data={**valid, "expected_lock_version": "999"}
    )
    assert anonymous.status_code == 302
    assert missing_csrf.status_code == 403
    assert wrong_identity.status_code == 400
    assert stale.status_code == 409
    assert db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == before_items

    copied = admin_client.post(path, data=valid)
    assert copied.status_code == 302
    copied_id = int(copied.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
    assert copied_id != published["id"]
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (copied_id,)
    ).fetchone()[0] == "draft"
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_revision_copied'",
        (copied_id,),
    ).fetchone()[0] == 1


def test_announcement_public_interval_boundaries_are_second_exact(admin_client, db):
    _create_announcement(
        admin_client,
        db,
        action="publish",
        slug="announcement-boundary",
        valid_from="2026-08-25T10:00",
        valid_until="2026-08-25T11:00",
    )
    path = "/announcements/announcement-boundary"
    for instant, expected in (
        (NOW - timedelta(seconds=1), 404),
        (NOW, 200),
        (NOW + timedelta(hours=1), 200),
        (NOW + timedelta(hours=1, seconds=1), 404),
    ):
        admin_client.application.config["CONTENT_NOW_PROVIDER"] = lambda instant=instant: instant
        assert admin_client.get(path).status_code == expected


def test_announcement_rejects_missing_or_invalid_interval_and_unsafe_cta(
    admin_client, db
):
    attempts = (
        _announcement_form(action="publish", valid_from=""),
        _announcement_form(action="publish", valid_until=""),
        _announcement_form(
            action="publish", valid_from="2026-08-26T10:00", valid_until="2026-08-25T10:00",
        ),
        _announcement_form(action="publish", cta_url="javascript:alert(1)"),
        _announcement_form(action="publish", cta_url="//evil.example/path"),
        _announcement_form(action="publish", author="invented"),
    )
    before = db.execute(
        "SELECT COUNT(*) FROM content_items WHERE entry_type='announcement'"
    ).fetchone()[0]
    for form in attempts:
        response = admin_client.post("/admin/announcements/new", data=form)
        assert response.status_code == 400
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE entry_type='announcement'"
    ).fetchone()[0] == before


def _exact_url(prefix, length):
    assert len(prefix) <= length
    return prefix + "a" * (length - len(prefix))


@pytest.mark.parametrize(
    ("kind", "length", "expected_status"),
    (
        ("source", 2048, 302),
        ("source", 2049, 400),
        ("announcement_cta", 2048, 302),
        ("announcement_cta", 2049, 400),
        ("block_cta", 1900, 302),
        ("block_cta", 2049, 400),
    ),
)
def test_admin_posts_enforce_2048_for_every_public_url(
    admin_client, db, kind, length, expected_status
):
    marker = f"{kind.replace('_', '-')}-{length}"
    if kind == "source":
        form = _resource_form(
            slug=f"admin-url-{marker}",
            is_original="0",
            source_name="公开来源",
            source_url=_exact_url("https://example.com/", length),
        )
        path = "/admin/resources/new"
    elif kind == "announcement_cta":
        form = _announcement_form(
            slug=f"admin-url-{marker}",
            cta_url=_exact_url("/", length),
        )
        path = "/admin/announcements/new"
    else:
        form = _resource_form(
            slug=f"admin-url-{marker}",
            **{
                "blocks-0-type": "cta",
                "blocks-0-title": "下一步",
                "blocks-0-body": "",
                "blocks-0-cta_label": "继续",
                "blocks-0-cta_url": _exact_url("https://example.com/", length),
                "blocks-0-cta_style": "primary",
            },
        )
        path = "/admin/resources/new"

    response = admin_client.post(path, data=form)

    assert response.status_code == expected_status
    row = db.execute(
        "SELECT status FROM content_items WHERE slug=?", (f"admin-url-{marker}",)
    ).fetchone()
    assert (row is not None) is (expected_status == 302)


@pytest.mark.parametrize(
    ("unicode_count", "expected_status", "expected_settings_bytes"),
    (
        (215, 302, 2000),
        (216, 400, None),
    ),
)
def test_admin_cta_revalidates_the_two_kibibyte_limit_after_url_normalization(
    admin_client, db, unicode_count, expected_status, expected_settings_bytes
):
    admin_client.application.config["PROPAGATE_EXCEPTIONS"] = False
    slug = f"normalized-cta-{unicode_count}"
    before_audit = db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE event_code='content_created'"
    ).fetchone()[0]

    response = admin_client.post(
        "/admin/resources/new",
        data=_resource_form(
            slug=slug,
            **{
                "blocks-0-type": "cta",
                "blocks-0-title": "下一步",
                "blocks-0-body": "",
                "blocks-0-cta_label": "继续",
                "blocks-0-cta_url": "https://example.com/" + "路" * unicode_count,
                "blocks-0-cta_style": "primary",
            },
        ),
    )

    row = db.execute(
        "SELECT ci.id,length(CAST(cb.settings_json AS BLOB)) AS settings_bytes "
        "FROM content_items ci LEFT JOIN content_blocks cb ON cb.content_item_id=ci.id "
        "WHERE ci.slug=?",
        (slug,),
    ).fetchone()
    created_audit = db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE event_code='content_created'"
    ).fetchone()[0]
    assert (response.status_code, None if row is None else row["settings_bytes"]) == (
        expected_status,
        expected_settings_bytes,
    )
    assert created_audit - before_audit == (1 if expected_status == 302 else 0)


@pytest.mark.parametrize("kind", ("source", "announcement_cta", "block_cta"))
def test_legacy_published_oversized_urls_fail_closed(client, admin_client, db, kind):
    oversized = _exact_url("https://example.com/", 2049)
    if kind == "announcement_cta":
        item = _create_announcement(
            admin_client,
            db,
            action="save",
            slug="legacy-oversized-announcement-cta",
            cta_url="/assessment",
        )
        db.execute(
            "UPDATE announcement_content SET cta_url=? WHERE content_item_id=?",
            (oversized, item["id"]),
        )
        path = "/announcements/legacy-oversized-announcement-cta"
    elif kind == "source":
        item = _create_resource(
            admin_client,
            db,
            action="save",
            slug="legacy-oversized-source-url",
            is_original="0",
            source_name="公开来源",
            source_url="https://example.com/short",
        )
        source_hash = hashlib.sha256(oversized.encode()).hexdigest()
        db.execute(
            "UPDATE resource_content SET source_url=?,source_url_sha256=?,"
            "source_check_code='https_ok',source_checked_at='2026-08-25 10:00:00',"
            "source_check_expires_at='2026-09-01 10:00:00',"
            "source_check_url_sha256=? WHERE content_item_id=?",
            (oversized, source_hash, source_hash, item["id"]),
        )
        path = "/resources/legacy-oversized-source-url"
    else:
        item = _create_resource(
            admin_client,
            db,
            action="save",
            slug="legacy-oversized-block-cta",
            **{
                "blocks-0-type": "cta",
                "blocks-0-title": "下一步",
                "blocks-0-body": "",
                "blocks-0-cta_label": "继续",
                "blocks-0-cta_url": "/assessment",
                "blocks-0-cta_style": "primary",
            },
        )
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute(
            "UPDATE content_blocks SET settings_json=? WHERE content_item_id=?",
            (
                json.dumps(
                    {"label": "继续", "url": oversized, "style": "primary"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                item["id"],
            ),
        )
        db.execute("PRAGMA ignore_check_constraints=OFF")
        path = "/resources/legacy-oversized-block-cta"
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-25 10:00:00' "
        "WHERE id=?",
        (item["id"],),
    )
    db.commit()

    response = client.get(path)

    assert response.status_code == 404


def test_public_read_models_are_snapshot_bounded_and_only_return_current_content(
    admin_client, db
):
    _create_resource(admin_client, db, action="publish", slug="read-model-resource")
    _create_announcement(admin_client, db, action="publish", slug="read-model-announcement")
    import resource_repository as resources

    page = resources.list_published_resources(
        resources.ResourceFilters(None), PageRequest(1, 20), now=NOW
    )
    announcements = resources.list_current_announcements(now=NOW)
    assert [item.slug for item in page.items] == ["read-model-resource"]
    assert [item.slug for item in announcements] == ["read-model-announcement"]
    assert resources.get_published_resource("read-model-resource", now=NOW).slug == "read-model-resource"
    assert resources.get_current_announcement("read-model-announcement", now=NOW).slug == "read-model-announcement"


class _InterleavingCursor:
    def __init__(self, cursor, after_first_fetch):
        self._cursor = cursor
        self._after_first_fetch = after_first_fetch

    def _fetched(self, value):
        callback, self._after_first_fetch = self._after_first_fetch, None
        if callback is not None:
            callback()
        return value

    def fetchone(self):
        return self._fetched(self._cursor.fetchone())

    def fetchall(self):
        return self._fetched(self._cursor.fetchall())

    def __iter__(self):
        return self

    def __next__(self):
        try:
            value = next(self._cursor)
        except StopIteration:
            self._fetched(None)
            raise
        return self._fetched(value)


class _InterleavingReadConnection:
    def __init__(self, connection, after_first_fetch):
        self._connection = connection
        self._after_first_fetch = after_first_fetch
        self._first_read_wrapped = False
        self._begin_seen = False
        self.begin_before_first_read = False

    def execute(self, sql, parameters=()):
        statement = sql.strip().upper()
        if statement == "BEGIN":
            self._begin_seen = True
        cursor = self._connection.execute(sql, parameters)
        if statement.startswith("SELECT") and not self._first_read_wrapped:
            self._first_read_wrapped = True
            self.begin_before_first_read = self._begin_seen
            return _InterleavingCursor(cursor, self._after_first_fetch)
        return cursor

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()


def _commit_replacement(get_db, old_id, replacement_id, entry_type):
    writer = get_db()
    try:
        writer.execute("BEGIN IMMEDIATE")
        old = writer.execute(
            "SELECT content_group_id,slug FROM content_items WHERE id=?", (old_id,)
        ).fetchone()
        replacement = writer.execute(
            "SELECT slug FROM content_items WHERE id=?", (replacement_id,)
        ).fetchone()
        writer.execute(
            "UPDATE content_items SET status='archived',archived_at='2026-08-25 10:00:01',"
            "lock_version=lock_version+1,updated_at='2026-08-25 10:00:01' "
            "WHERE id=? AND status='published'",
            (old_id,),
        )
        if old["slug"] != replacement["slug"]:
            writer.execute(
                "UPDATE content_groups SET canonical_slug=?,updated_at='2026-08-25 10:00:01' "
                "WHERE id=?",
                (replacement["slug"], old["content_group_id"]),
            )
            writer.execute(
                "INSERT INTO content_slug_aliases "
                "(entry_type,old_slug,content_group_id,created_at) VALUES (?,?,?,"
                "'2026-08-25 10:00:01')",
                (entry_type, old["slug"], old["content_group_id"]),
            )
        writer.execute(
            "UPDATE content_items SET status='published',published_at='2026-08-25 10:00:01',"
            "lock_version=lock_version+1,updated_at='2026-08-25 10:00:01' "
            "WHERE id=? AND status='draft'",
            (replacement_id,),
        )
        writer.commit()
    finally:
        writer.close()


@pytest.mark.parametrize("surface", ("list", "direct", "alias"))
def test_public_resource_reads_one_wal_snapshot_during_replacement(
    admin_client, db, monkeypatch, surface
):
    import resource_repository as resources

    db.execute("PRAGMA journal_mode=WAL")
    initial_slug = f"snapshot-resource-{surface}"
    current = _create_resource(
        admin_client, db, action="publish", slug=initial_slug,
        title="快照旧资源标题",
    )
    if surface == "alias":
        renamed_id = copy_revision(current["id"], actor="test-admin", now=NOW)
        renamed = replace(
            publishing_repository.load_content_draft(db, renamed_id),
            slug=f"{initial_slug}-current",
        )
        save_content_draft(renamed_id, 1, renamed, actor="test-admin", now=NOW)
        publish_content(renamed_id, 2, actor="test-admin", now=NOW)
        current = db.execute(
            "SELECT * FROM content_items WHERE id=?", (renamed_id,)
        ).fetchone()
    replacement_id = copy_revision(current["id"], actor="test-admin", now=NOW)
    replacement = replace(
        publishing_repository.load_content_draft(db, replacement_id),
        slug=(
            f"{initial_slug}-replacement" if surface == "alias" else current["slug"]
        ),
        title="并发替换后的资源标题",
    )
    save_content_draft(replacement_id, 1, replacement, actor="test-admin", now=NOW)
    db.commit()
    original_get_db = resources.models.get_db
    interleaved = _InterleavingReadConnection(
        original_get_db(),
        lambda: _commit_replacement(
            original_get_db, current["id"], replacement_id, "resource"
        ),
    )
    monkeypatch.setattr(resources.models, "get_db", lambda: interleaved)

    if surface == "list":
        projection = resources.list_published_resources(
            resources.ResourceFilters(None), PageRequest(1, 20), now=NOW
        ).items[0]
    else:
        projection = resources.get_published_resource(
            initial_slug if surface == "alias" else current["slug"], now=NOW
        )
    assert projection is not None
    assert projection.title == "快照旧资源标题"
    assert projection.redirect is (surface == "alias")
    assert interleaved.begin_before_first_read is True


@pytest.mark.parametrize("surface", ("list", "detail"))
def test_public_announcement_reads_one_wal_snapshot_during_replacement(
    admin_client, db, monkeypatch, surface
):
    import resource_repository as resources

    db.execute("PRAGMA journal_mode=WAL")
    current = _create_announcement(
        admin_client, db, action="publish", slug=f"snapshot-announcement-{surface}",
        title="快照旧公告标题",
    )
    replacement_id = copy_revision(current["id"], actor="test-admin", now=NOW)
    replacement = replace(
        publishing_repository.load_content_draft(db, replacement_id),
        title="并发替换后的公告标题",
    )
    save_content_draft(replacement_id, 1, replacement, actor="test-admin", now=NOW)
    db.commit()
    original_get_db = resources.models.get_db
    interleaved = _InterleavingReadConnection(
        original_get_db(),
        lambda: _commit_replacement(
            original_get_db, current["id"], replacement_id, "announcement"
        ),
    )
    monkeypatch.setattr(resources.models, "get_db", lambda: interleaved)

    if surface == "list":
        projection = resources.list_current_announcements(now=NOW)[0]
    else:
        projection = resources.get_current_announcement(current["slug"], now=NOW)
    assert projection is not None
    assert projection.title == "快照旧公告标题"
    assert interleaved.begin_before_first_read is True


def test_malformed_persisted_resource_and_announcement_fail_closed(admin_client, db):
    import resource_repository as resources

    resource = _create_resource(
        admin_client, db, action="save", slug="legacy-malformed-resource",
        title="MALFORMED-RESOURCE-SECRET",
    )
    announcement = _create_announcement(
        admin_client, db, action="save", slug="legacy-malformed-announcement",
        title="MALFORMED-ANNOUNCEMENT-SECRET",
    )
    db.execute(
        "UPDATE resource_content SET copyright_notice='   ' WHERE content_item_id=?",
        (resource["id"],),
    )
    db.execute(
        "UPDATE announcement_content SET valid_from=NULL WHERE content_item_id=?",
        (announcement["id"],),
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-25 10:00:00',"
        "updated_at='2026-08-25 10:00:00' WHERE id IN (?,?)",
        (resource["id"], announcement["id"]),
    )
    db.commit()

    resource_response = admin_client.get("/resources/legacy-malformed-resource")
    resource_listing = admin_client.get("/resources")
    announcement_response = admin_client.get(
        "/announcements/legacy-malformed-announcement"
    )
    assert resource_response.status_code == 404
    assert b"MALFORMED-RESOURCE-SECRET" not in resource_response.data
    assert b"MALFORMED-RESOURCE-SECRET" not in resource_listing.data
    assert announcement_response.status_code == 404
    assert b"MALFORMED-ANNOUNCEMENT-SECRET" not in announcement_response.data
    assert all(
        item.title != "MALFORMED-ANNOUNCEMENT-SECRET"
        for item in resources.list_current_announcements(now=NOW)
    )


def test_failed_resource_replacement_preserves_old_public_revision_and_audit(
    admin_client, db
):
    old = _create_resource(
        admin_client, db, action="publish", slug="atomic-resource",
        title="OLD-PUBLIC-RESOURCE",
    )
    copied_id = copy_revision(old["id"], actor="test-admin", now=NOW)
    db.execute(
        "UPDATE resource_content SET copyright_notice='   ' WHERE content_item_id=?",
        (copied_id,),
    )
    db.commit()
    before_success = db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE event_code='content_published'"
    ).fetchone()[0]

    with pytest.raises(ContentValidationError):
        publish_content(copied_id, 1, actor="test-admin", now=NOW)

    states = db.execute(
        "SELECT id,status FROM content_items WHERE content_group_id=? ORDER BY id",
        (old["content_group_id"],),
    ).fetchall()
    assert [(row["id"], row["status"]) for row in states] == [
        (old["id"], "published"), (copied_id, "draft")
    ]
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE event_code='content_published'"
    ).fetchone()[0] == before_success
    response = admin_client.get("/resources/atomic-resource")
    assert response.status_code == 200
    assert "OLD-PUBLIC-RESOURCE" in response.get_data(as_text=True)


def test_related_resource_target_must_be_public_complete_not_status_only(db):
    target_id = create_content_draft(
        _resource_draft("legacy-incomplete-related-resource"),
        actor="test-admin",
        now=NOW,
    )
    target = db.execute(
        "SELECT content_group_id FROM content_items WHERE id=?", (target_id,)
    ).fetchone()
    db.execute(
        "UPDATE resource_content SET copyright_notice='   ' WHERE content_item_id=?",
        (target_id,),
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-25 10:00:00',"
        "updated_at='2026-08-25 10:00:00' WHERE id=?",
        (target_id,),
    )
    db.commit()
    owner = db.execute(
        "SELECT ci.id,ci.lock_version FROM content_items ci JOIN content_groups g "
        "ON g.id=ci.content_group_id WHERE ci.entry_type='scenario' "
        "AND ci.status='draft' ORDER BY ci.id LIMIT 1"
    ).fetchone()
    owner_draft = publishing_repository.load_content_draft(db, owner["id"])
    owner_id = owner["id"]
    save_content_draft(
        owner_id,
        owner["lock_version"],
        replace(
            owner_draft,
            relations=(
                ContentRelation(
                    "scenario_resource", target["content_group_id"], 0
                ),
            ),
        ),
        actor="test-admin",
        now=NOW,
    )
    with pytest.raises(ContentValidationError) as error:
        publish_content(owner_id, owner["lock_version"] + 1, actor="test-admin", now=NOW)

    assert error.value.code == "relation_target_not_published"
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (owner_id,)
    ).fetchone()[0] == "draft"


@pytest.mark.parametrize("owner_kind", ("service", "scenario", "industry"))
def test_formally_published_owner_resources_render_ordered_navigable_links(
    client, db, owner_kind
):
    first = _publish_related_resource(
        db,
        f"{owner_kind}-ordered-resource-first",
        title=f"{owner_kind} 资源第一项",
    )
    second = _publish_related_resource(
        db,
        f"{owner_kind}-ordered-resource-second",
        title=f"{owner_kind} 资源第二项",
    )
    path = _publish_owner_with_resources(db, owner_kind, (second, first))

    response = client.get(path)

    assert response.status_code == 200
    document = BeautifulSoup(response.data, "html.parser")
    links = document.select('[data-related-kind="resource"] a')
    assert [link.get_text(strip=True) for link in links] == [
        second["title"], first["title"]
    ]
    assert [link["href"] for link in links] == [
        f"/resources/{second['slug']}", f"/resources/{first['slug']}"
    ]


@pytest.mark.parametrize("owner_kind", ("service", "scenario", "industry"))
@pytest.mark.parametrize("mutation", ("archived", "stale", "corrupt"))
def test_owner_resource_links_omit_targets_that_lose_public_completeness(
    client, db, monkeypatch, owner_kind, mutation
):
    target = _publish_related_resource(
        db,
        f"{owner_kind}-{mutation}-resource",
        title=f"MUST-HIDE-{owner_kind}-{mutation}",
        sourced=mutation == "stale",
    )
    path = _publish_owner_with_resources(db, owner_kind, (target,))
    exact = NOW
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: exact
    monkeypatch.setattr(public_catalog_blueprint, "shanghai_now", lambda: exact)
    before = client.get(path)
    resource_path = f"/resources/{target['slug']}"
    assert before.status_code == 200
    assert client.get(resource_path).status_code == 200
    assert BeautifulSoup(before.data, "html.parser").select_one(
        f'a[href="{resource_path}"]'
    ) is not None

    if mutation == "archived":
        archive_content(
            target["id"], target["lock_version"], actor="test-admin", now=NOW
        )
        current = exact
    elif mutation == "stale":
        current = exact + timedelta(seconds=1)
    else:
        replacement_id = copy_revision(target["id"], actor="test-admin", now=NOW)
        archive_content(
            target["id"], target["lock_version"], actor="test-admin", now=NOW
        )
        db.execute(
            "UPDATE resource_content SET copyright_notice=? WHERE content_item_id=?",
            (sqlite3.Binary(b"z" * 16), replacement_id),
        )
        db.execute(
            "UPDATE content_items SET status='published',published_at='2026-08-25 10:00:00' "
            "WHERE id=?",
            (replacement_id,),
        )
        db.commit()
        current = exact
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: current
    monkeypatch.setattr(public_catalog_blueprint, "shanghai_now", lambda: current)

    after = client.get(path)

    assert after.status_code == 200
    assert client.get(resource_path).status_code == 404
    document = BeautifulSoup(after.data, "html.parser")
    assert document.select('[data-related-kind="resource"]') == []
    assert target["title"] not in document.get_text(" ", strip=True)


def test_due_job_isolates_malformed_resource_from_valid_announcement(db):
    bad_id = create_content_draft(
        _resource_draft("due-malformed-resource"), actor="test-admin", now=NOW
    )
    good_id = create_content_draft(
        _announcement_draft("due-valid-announcement"), actor="test-admin", now=NOW
    )
    due = NOW + timedelta(hours=1)
    schedule_content(bad_id, 1, due, actor="test-admin", now=NOW)
    schedule_content(good_id, 1, due, actor="test-admin", now=NOW)
    db.execute(
        "UPDATE resource_content SET copyright_notice='   ' WHERE content_item_id=?",
        (bad_id,),
    )
    db.commit()

    result = publish_due_content(now=due, actor="task9-due")

    assert result.published_ids == (good_id,)
    assert result.failures == ((bad_id, "validation_failed"),)
    states = {
        row["id"]: (row["status"], row["publish_at"])
        for row in db.execute(
            "SELECT id,status,publish_at FROM content_items WHERE id IN (?,?)",
            (bad_id, good_id),
        )
    }
    assert states[bad_id] == ("draft", None)
    assert states[good_id][0] == "published"


def test_direct_resource_replacement_converts_persisted_blob_to_stable_validation(
    db,
):
    old_id = create_content_draft(
        _resource_draft("blob-direct-resource"), actor="test-admin", now=NOW
    )
    publish_content(old_id, 1, actor="test-admin", now=NOW)
    replacement_id = copy_revision(old_id, actor="test-admin", now=NOW)
    db.execute(
        "UPDATE resource_content SET copyright_notice=? WHERE content_item_id=?",
        (sqlite3.Binary(b"x" * 16), replacement_id),
    )
    db.commit()
    before_success = db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE event_code='content_published'"
    ).fetchone()[0]

    with pytest.raises(ContentValidationError) as error:
        publish_content(replacement_id, 1, actor="test-admin", now=NOW)

    assert error.value.code == "extension_invalid"
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (old_id,)
    ).fetchone()[0] == "published"
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (replacement_id,)
    ).fetchone()[0] == "draft"
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE event_code='content_published'"
    ).fetchone()[0] == before_success


def test_due_blob_resource_isolated_and_later_announcement_publishes(db):
    old_id = create_content_draft(
        _resource_draft("blob-due-resource"), actor="test-admin", now=NOW
    )
    publish_content(old_id, 1, actor="test-admin", now=NOW)
    replacement_id = copy_revision(old_id, actor="test-admin", now=NOW)
    announcement_id = create_content_draft(
        _announcement_draft("after-blob-due-resource"), actor="test-admin", now=NOW
    )
    due = NOW + timedelta(hours=1)
    schedule_content(replacement_id, 1, due, actor="test-admin", now=NOW)
    schedule_content(announcement_id, 1, due, actor="test-admin", now=NOW)
    db.execute(
        "UPDATE resource_content SET copyright_notice=? WHERE content_item_id=?",
        (sqlite3.Binary(b"y" * 16), replacement_id),
    )
    db.commit()

    result = publish_due_content(now=due, actor="task9-fix1-due")

    assert result.published_ids == (announcement_id,)
    assert result.failures == ((replacement_id, "validation_failed"),)
    states = {
        row["id"]: (row["status"], row["publish_at"], row["lock_version"])
        for row in db.execute(
            "SELECT id,status,publish_at,lock_version FROM content_items "
            "WHERE id IN (?,?,?)",
            (old_id, replacement_id, announcement_id),
        )
    }
    assert states[old_id][0] == "published"
    assert states[replacement_id] == ("draft", None, 3)
    assert states[announcement_id][0] == "published"
    details = db.execute(
        "SELECT details_json FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_due_failed'",
        (replacement_id,),
    ).fetchone()[0]
    assert details == '{"reason_code":"validation_failed"}'
    assert "blob" not in details


def _inject_nonfinite_block_settings(db, content_id):
    db.execute("PRAGMA ignore_check_constraints=ON")
    try:
        db.execute(
            "UPDATE content_blocks SET block_type='heading',settings_json=? "
            "WHERE content_item_id=?",
            ('{"level":NaN}', content_id),
        )
    finally:
        db.execute("PRAGMA ignore_check_constraints=OFF")
    db.commit()


def test_direct_replacement_converts_nonfinite_persisted_block_to_validation_error(db):
    old_id = create_content_draft(
        _resource_draft("nan-direct-resource"), actor="test-admin", now=NOW
    )
    publish_content(old_id, 1, actor="test-admin", now=NOW)
    replacement_id = copy_revision(old_id, actor="test-admin", now=NOW)
    _inject_nonfinite_block_settings(db, replacement_id)
    before_success = db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE event_code='content_published'"
    ).fetchone()[0]

    with pytest.raises(ContentValidationError) as error:
        publish_content(replacement_id, 1, actor="test-admin", now=NOW)

    assert error.value.code == "extension_invalid"
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (old_id,)
    ).fetchone()[0] == "published"
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (replacement_id,)
    ).fetchone()[0] == "draft"
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE event_code='content_published'"
    ).fetchone()[0] == before_success


def test_due_nonfinite_block_isolated_and_later_announcement_publishes(db):
    old_id = create_content_draft(
        _resource_draft("nan-due-resource"), actor="test-admin", now=NOW
    )
    publish_content(old_id, 1, actor="test-admin", now=NOW)
    replacement_id = copy_revision(old_id, actor="test-admin", now=NOW)
    announcement_id = create_content_draft(
        _announcement_draft("after-nan-due-resource"), actor="test-admin", now=NOW
    )
    due = NOW + timedelta(hours=1)
    schedule_content(replacement_id, 1, due, actor="test-admin", now=NOW)
    schedule_content(announcement_id, 1, due, actor="test-admin", now=NOW)
    _inject_nonfinite_block_settings(db, replacement_id)

    result = publish_due_content(now=due, actor="task9-fix2-due")

    assert result.published_ids == (announcement_id,)
    assert result.failures == ((replacement_id, "validation_failed"),)
    states = {
        row["id"]: (row["status"], row["publish_at"], row["lock_version"])
        for row in db.execute(
            "SELECT id,status,publish_at,lock_version FROM content_items "
            "WHERE id IN (?,?,?)",
            (old_id, replacement_id, announcement_id),
        )
    }
    assert states[old_id][0] == "published"
    assert states[replacement_id] == ("draft", None, 3)
    assert states[announcement_id][0] == "published"
    details = db.execute(
        "SELECT details_json FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_due_failed'",
        (replacement_id,),
    ).fetchone()[0]
    assert details == '{"reason_code":"validation_failed"}'
    assert "NaN" not in details


def test_domain_validation_rejects_whitespace_copyright_and_null_announcement_interval():
    with pytest.raises(ContentValidationError):
        validate_content_draft(_resource_draft("domain-bad-copyright", copyright_notice=" \t "))
    with pytest.raises(ContentValidationError):
        validate_content_draft(
            replace(
                _announcement_draft("domain-null-interval"),
                extension={"valid_from": None, "valid_until": None, "cta_url": None},
            )
        )
