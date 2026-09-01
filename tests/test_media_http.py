from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta

from flask import render_template_string
from PIL import Image
from pypdf import PdfWriter
import pytest
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Response

import models
import blueprints.public_catalog as public_catalog_blueprint
import media_service
import publishing_repository
from content_clock import SHANGHAI
from content_contracts import CaseMetric, ContentBlock, ContentDraft
from publishing_service import (
    create_content_draft,
    publish_content,
    save_content_draft,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _ShortReadInput:
    def __init__(self, data, chunk_size=64 * 1024):
        self._stream = io.BytesIO(data)
        self._chunk_size = chunk_size

    def read(self, size=-1):
        if size < 0:
            size = self._chunk_size
        return self._stream.read(min(size, self._chunk_size))


def _image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (8, 6), (32, 96, 160)).save(output, format="PNG")
    return output.getvalue()


def _pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.metadata = None
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _ooxml_bytes(kind):
    if kind == "docx":
        main_path = "word/document.xml"
        main_type = (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document.main+xml"
        )
        main_xml = (
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
            b'wordprocessingml/2006/main"/>'
        )
    else:
        main_path = "xl/workbook.xml"
        main_type = (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet.main+xml"
        )
        main_xml = (
            b'<workbook xmlns="http://schemas.openxmlformats.org/'
            b'spreadsheetml/2006/main"/>'
        )
    content_types = (
        '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
        'package/2006/content-types">'
        f'<Override PartName="/{main_path}" ContentType="{main_type}"/>'
        "</Types>"
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr(main_path, main_xml)
    return output.getvalue()


def _upload(client, name, mime, data, *, csrf="test-csrf-token", confirmed=True):
    form = {
        "csrf_token": csrf,
        "file": (io.BytesIO(data), name, mime),
    }
    if confirmed:
        form["metadata_review_confirmed"] = "1"
    return client.post("/admin/media", data=form, content_type="multipart/form-data")


def _latest_asset():
    db = models.get_db()
    try:
        return db.execute("SELECT * FROM media_assets ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        db.close()


def _publish_reference(db, *, asset_id, kind, publish_at=None):
    slug = f"media-{kind.replace('_', '-')}-{asset_id}"
    group_id = db.execute(
        "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
        "VALUES ('announcement',?,'2026-08-24 10:00:00','2026-08-24 10:00:00')",
        (slug,),
    ).lastrowid
    content_id = db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,seo_description,"
        "share_image_media_id,status,lock_version,created_at,updated_at) "
        "VALUES (?,'announcement',1,?,'Title','Summary','SEO','Description',?,'draft',1,"
        "'2026-08-24 10:00:00','2026-08-24 10:00:00')",
        (group_id, slug, asset_id if kind == "share" else None),
    ).lastrowid
    db.execute(
        "INSERT INTO announcement_content (content_item_id,valid_from,valid_until) "
        "VALUES (?,'2000-01-01 00:00:00','2099-01-01 00:00:00')",
        (content_id,),
    )
    if kind in {"image_block", "download"}:
        settings = (
            {"alignment": "left", "alt_text": "公开图片"}
            if kind == "image_block"
            else {"label": "下载附件"}
        )
        db.execute(
            "INSERT INTO content_blocks "
            "(content_item_id,block_type,title,body_html,settings_json,media_asset_id,sort_order) "
            "VALUES (?,?,?,?,?,?,0)",
            (
                content_id,
                "image_text" if kind == "image_block" else "download",
                "公开媒体",
                "<p>公开媒体说明</p>" if kind == "image_block" else None,
                json.dumps(settings, ensure_ascii=False, separators=(",", ":")),
                asset_id,
            ),
        )
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-24 10:00:00',"
        "publish_at=?,updated_at='2026-08-24 10:00:00' WHERE id=?",
        (publish_at, content_id),
    )
    db.commit()
    publishing_repository.validate_announcement_public_completeness(
        db,
        content_id,
        datetime(2026, 8, 24, 10, 0, 0, tzinfo=SHANGHAI),
    )


def _publish_resource_attachment(db, asset_id, *, publish_at=None):
    slug = f"resource-attachment-{asset_id}"
    group_id = db.execute(
        "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
        "VALUES ('resource',?,'2026-08-24 10:00:00','2026-08-24 10:00:00')",
        (slug,),
    ).lastrowid
    content_id = db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,seo_description,"
        "status,lock_version,created_at,updated_at) "
        "VALUES (?,'resource',1,?,'Report','Summary','SEO','Description','draft',1,"
        "'2026-08-24 10:00:00','2026-08-24 10:00:00')",
        (group_id, slug),
    ).lastrowid
    db.execute(
        "INSERT INTO resource_content "
        "(content_item_id,resource_type,is_original,original_published_at,"
        "copyright_notice,attachment_media_id) "
        "VALUES (?,'report',1,'2026-08-20 09:00:00','本站原创',?)",
        (content_id, asset_id),
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-24 10:00:00',"
        "publish_at=?,updated_at='2026-08-24 10:00:00' WHERE id=?",
        (publish_at, content_id),
    )
    db.commit()


def _publish_announcement_download(db, asset_id, *, slug, valid_from, valid_until):
    content_id = create_content_draft(
        ContentDraft(
            entry_type="announcement",
            slug=slug,
            title=f"公告 {slug}",
            summary="公开媒体有效期边界公告。",
            seo_title=f"公告 {slug}",
            seo_description="验证公告媒体只在当前有效期内公开。",
            extension={
                "valid_from": valid_from,
                "valid_until": valid_until,
                "cta_url": None,
            },
            blocks=(
                ContentBlock(
                    "download",
                    title="公告附件",
                    settings={"label": "下载公告附件"},
                    media_asset_id=asset_id,
                ),
            ),
        ),
        actor="media-test",
        now=datetime(2026, 8, 24, 10, 0, 0, tzinfo=SHANGHAI),
    )
    publish_content(
        content_id,
        1,
        actor="media-test",
        now=datetime(2026, 8, 24, 10, 0, 0, tzinfo=SHANGHAI),
    )
    return content_id


def _publish_sourced_resource_attachment(db, asset_id, *, slug):
    source_url = f"https://example.com/{slug}"
    source_hash = hashlib.sha256(source_url.encode()).hexdigest()
    published_at = datetime(2026, 8, 18, 10, 0, 0, tzinfo=SHANGHAI)
    content_id = create_content_draft(
        ContentDraft(
            entry_type="resource",
            slug=slug,
            title=f"来源资源 {slug}",
            summary="公开媒体来源新鲜度边界资源。",
            seo_title=f"来源资源 {slug}",
            seo_description="验证资源媒体随来源检查新鲜度撤销公开资格。",
            extension={
                "resource_type": "report",
                "is_original": 0,
                "source_name": "公开来源",
                "source_url": source_url,
                "source_url_sha256": source_hash,
                "source_check_code": None,
                "source_checked_at": None,
                "source_check_expires_at": None,
                "source_check_url_sha256": None,
                "original_published_at": "2026-08-18 09:00:00",
                "copyright_notice": "原文版权归公开来源所有。",
                "attachment_media_id": asset_id,
            },
        ),
        actor="media-test",
        now=published_at,
    )
    db.execute(
        "UPDATE resource_content SET source_check_code='https_ok',source_checked_at=?,"
        "source_check_expires_at='2099-01-01 00:00:00',source_check_url_sha256=? "
        "WHERE content_item_id=?",
        ("2026-08-18 10:00:00", source_hash, content_id),
    )
    db.commit()
    publish_content(content_id, 1, actor="media-test", now=published_at)
    return content_id


def _publish_case_image_reference(asset_id):
    now = datetime(2026, 8, 25, 10, 0, 0, tzinfo=SHANGHAI)
    content_id = create_content_draft(
        ContentDraft(
            entry_type="case",
            slug="media-public-case",
            title="媒体公开案例",
            summary="通过完整案例公开门禁后引用分享图。",
            seo_title="媒体公开案例",
            seo_description="验证案例详情与媒体授权使用同一公开完整性。",
            share_image_media_id=asset_id,
            extension={
                "verification_code": "authorized_anonymous",
                "is_anonymized": 1,
                "basis_type": "internal_delivery_record",
                "private_basis_reference": "media-case-record-001",
                "source_url": None,
                "source_url_sha256": None,
                "source_check_code": None,
                "source_checked_at": None,
                "source_check_expires_at": None,
                "source_check_url_sha256": None,
                "is_verified": 1,
                "review_confirmed": 1,
                "verified_at": "2026-08-25 09:00:00",
            },
            blocks=(ContentBlock("rich_text", body_html="<p>公开案例正文。</p>"),),
            metrics=(
                CaseMetric(
                    "处理时间", "8", "2", "小时", "连续 30 天", "经脱敏交付记录核验。"
                ),
            ),
        ),
        actor="media-test",
        now=now,
    )
    publish_content(content_id, 1, actor="media-test", now=now)
    return content_id, "/cases/media-public-case"


def _publish_catalog_image_reference(db, asset_id, entry_type):
    now = datetime(2026, 8, 25, 10, 0, 0, tzinfo=SHANGHAI)
    if entry_type in {"industry", "service"}:
        db.execute(
            "UPDATE content_items SET status='published',published_at='2026-08-25 10:00:00' "
            "WHERE entry_type='scenario' AND status='draft'"
        )
        db.commit()
    code = {
        "industry": "manufacturing",
        "scenario": "mfg_knowledge_assistant",
        "service": "foundation_workshop",
    }[entry_type]
    table, identity = {
        "industry": ("industries", "industry_id"),
        "scenario": ("scenarios", "scenario_id"),
        "service": ("services", "service_id"),
    }[entry_type]
    item = db.execute(
        "SELECT ci.* FROM content_items ci JOIN content_groups g "
        f"ON g.id=ci.content_group_id JOIN {table} core ON core.id=g.{identity} "
        "WHERE ci.entry_type=? AND ci.status='draft' AND core.code=?",
        (entry_type, code),
    ).fetchone()
    draft = publishing_repository.load_content_draft(db, item["id"])
    lock_version = save_content_draft(
        item["id"],
        item["lock_version"],
        replace(draft, share_image_media_id=asset_id),
        actor="media-test",
        now=now,
    )
    publish_content(item["id"], lock_version, actor="media-test", now=now)
    path = {
        "industry": "/industries/manufacturing",
        "scenario": "/scenarios/mfg-knowledge-assistant",
        "service": "/service-packages/foundation-workshop",
    }[entry_type]
    return item["id"], path


def _break_public_reference(db, content_id, entry_type):
    if entry_type == "case":
        trigger_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='protect_case_metrics_delete'"
        ).fetchone()[0]
        db.execute("DROP TRIGGER protect_case_metrics_delete")
        db.execute(
            "DELETE FROM case_metrics WHERE case_content_item_id=?", (content_id,)
        )
        db.execute(trigger_sql)
    else:
        table, identity = {
            "industry": ("industries", "industry_id"),
            "scenario": ("scenarios", "scenario_id"),
            "service": ("services", "service_id"),
        }[entry_type]
        db.execute(
            f"UPDATE {table} SET status='archived' WHERE id=("
            f"SELECT {identity} FROM content_groups g JOIN content_items ci "
            "ON ci.content_group_id=g.id WHERE ci.id=?)",
            (content_id,),
        )
    db.commit()


def test_media_upload_requires_authentication_and_csrf(client, media_root):
    anonymous = _upload(client, "image.png", "image/png", _image_bytes())
    assert anonymous.status_code == 302
    assert "/admin/login" in anonymous.headers["Location"]

    with client.session_transaction() as session:
        session["admin_username"] = "test-admin"
        session["csrf_token"] = "expected"
    rejected = _upload(
        client,
        "image.png",
        "image/png",
        _image_bytes(),
        csrf="wrong",
    )
    assert rejected.status_code == 403
    assert list(media_root.iterdir()) == []


def test_successful_and_rejected_media_posts_are_audited_without_payload(
    admin_client, media_root
):
    success = _upload(admin_client, "safe-image.png", "image/png", _image_bytes())
    rejected = _upload(
        admin_client,
        "secret-hostile-name.html",
        "text/html",
        b"private-content-marker<script>",
    )

    assert success.status_code == 302
    assert rejected.status_code == 400
    db = models.get_db()
    try:
        records = db.execute(
            "SELECT actor,action,status_code FROM admin_audit_logs "
            "WHERE action='admin_media' ORDER BY id"
        ).fetchall()
        serialized = " ".join(
            str(tuple(row))
            for row in db.execute("SELECT * FROM admin_audit_logs ORDER BY id")
        )
    finally:
        db.close()
    assert [dict(row) for row in records] == [
        {"actor": "test-admin", "action": "admin_media", "status_code": 302},
        {"actor": "test-admin", "action": "admin_media", "status_code": 400},
    ]
    assert "secret-hostile-name" not in serialized
    assert "private-content-marker" not in serialized
    assert len([path for path in media_root.iterdir() if not path.name.startswith(".upload-")]) == 1


def test_admin_document_upload_requires_privacy_review_checkbox(admin_client, media_root):
    response = _upload(
        admin_client,
        "report.pdf",
        "application/pdf",
        _pdf_bytes(),
        confirmed=False,
    )

    assert response.status_code == 400
    assert list(media_root.iterdir()) == []


def test_admin_media_list_preview_and_archive_are_controlled(admin_client, media_root):
    assert _upload(admin_client, "preview.png", "image/png", _image_bytes()).status_code == 302
    asset = _latest_asset()

    listing = admin_client.get("/admin/media")
    preview = admin_client.get(f"/admin/media/{asset['id']}/preview")
    archived = admin_client.post(
        f"/admin/media/{asset['id']}/archive",
        data={"csrf_token": "test-csrf-token"},
    )
    missing_preview = admin_client.get(f"/admin/media/{asset['id']}/preview")

    assert listing.status_code == 200
    assert b"preview.png" in listing.data
    assert preview.status_code == 200
    assert preview.mimetype == "image/png"
    assert preview.headers["Cache-Control"] == "private, no-store"
    assert preview.headers["X-Content-Type-Options"] == "nosniff"
    assert archived.status_code == 302
    assert missing_preview.status_code == 404
    assert (media_root / asset["storage_name"]).is_file()


def test_admin_image_preview_is_inline_with_exact_content_disposition(admin_client):
    assert _upload(admin_client, "preview.png", "image/png", _image_bytes()).status_code == 302
    asset = _latest_asset()

    response = admin_client.get(f"/admin/media/{asset['id']}/preview")

    assert response.status_code == 200
    assert response.headers["Content-Disposition"] == "inline; filename=preview.png"


def test_admin_document_previews_are_attachments_with_exact_content_disposition(
    admin_client,
):
    documents = (
        ("report.pdf", "application/pdf", _pdf_bytes()),
        (
            "guide.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _ooxml_bytes("docx"),
        ),
        (
            "sheet.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            _ooxml_bytes("xlsx"),
        ),
    )
    for name, mime, data in documents:
        assert _upload(admin_client, name, mime, data).status_code == 302
        asset = _latest_asset()

        response = admin_client.get(f"/admin/media/{asset['id']}/preview")

        assert response.status_code == 200
        assert response.headers["Content-Disposition"] == f"attachment; filename={name}"


def test_public_inline_image_requires_current_published_reference_and_safe_headers(
    admin_client, db
):
    assert _upload(admin_client, "public.png", "image/png", _image_bytes()).status_code == 302
    asset = _latest_asset()

    unreferenced = admin_client.get(f"/media/{asset['id']}/image")
    _publish_reference(db, asset_id=asset["id"], kind="share")
    published = admin_client.get(f"/media/{asset['id']}/image")

    assert unreferenced.status_code == 404
    assert published.status_code == 200
    assert published.mimetype == "image/png"
    assert published.headers["Content-Disposition"].startswith("inline")
    assert published.headers["ETag"] == f'"{asset["sha256"]}"'
    assert published.headers["Cache-Control"] == "public, max-age=0, must-revalidate"
    assert published.headers["X-Content-Type-Options"] == "nosniff"


def test_public_image_block_uses_inline_route_but_download_block_cannot(client, admin_client, db):
    assert _upload(admin_client, "block.png", "image/png", _image_bytes()).status_code == 302
    asset = _latest_asset()
    _publish_reference(db, asset_id=asset["id"], kind="image_block")

    assert client.get(f"/media/{asset['id']}/image").status_code == 200
    assert client.get(f"/media/{asset['id']}/download").status_code == 404


def test_public_attachment_requires_published_download_reference_and_attachment_headers(
    client, admin_client, db
):
    data = _pdf_bytes()
    assert _upload(admin_client, "reviewed-report.pdf", "application/pdf", data).status_code == 302
    asset = _latest_asset()

    assert client.get(f"/media/{asset['id']}/download").status_code == 404
    _publish_reference(db, asset_id=asset["id"], kind="download")
    response = client.get(f"/media/{asset['id']}/download")

    assert response.status_code == 200
    assert response.data == data
    assert response.mimetype == "application/pdf"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert "reviewed-report.pdf" in response.headers["Content-Disposition"]
    assert response.headers["ETag"] == f'"{asset["sha256"]}"'
    assert response.headers["Cache-Control"] == "public, max-age=0, must-revalidate"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get(f"/media/{asset['id']}/image").status_code == 404


def test_published_resource_attachment_uses_only_the_download_route(
    client, admin_client, db
):
    data = _pdf_bytes()
    assert _upload(admin_client, "resource-report.pdf", "application/pdf", data).status_code == 302
    asset = _latest_asset()
    _publish_resource_attachment(db, asset["id"])

    download = client.get(f"/media/{asset['id']}/download")

    assert download.status_code == 200
    assert download.data == data
    assert download.headers["Content-Disposition"].startswith("attachment;")
    assert client.get(f"/media/{asset['id']}/image").status_code == 404


@pytest.mark.parametrize(("path", "kind"), (("image", "image"), ("download", "download")))
def test_public_media_routes_pass_injected_content_now(client, monkeypatch, path, kind):
    instant = datetime(2026, 8, 25, 10, 0, 0, tzinfo=SHANGHAI)
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: instant
    captured = {}

    def lookup(asset_id, *, kind, now):
        captured.update(asset_id=asset_id, kind=kind, now=now)
        return None

    monkeypatch.setattr("blueprints.media.get_published_media_asset", lookup)
    assert client.get(f"/media/7/{path}").status_code == 404
    assert captured == {"asset_id": 7, "kind": kind, "now": instant}


@pytest.mark.parametrize(
    ("instant", "expected_status"),
    (
        (datetime(2026, 8, 25, 9, 59, 59, tzinfo=SHANGHAI), 404),
        (datetime(2026, 8, 25, 10, 0, 0, tzinfo=SHANGHAI), 200),
        (datetime(2026, 8, 25, 11, 0, 0, tzinfo=SHANGHAI), 200),
        (datetime(2026, 8, 25, 11, 0, 1, tzinfo=SHANGHAI), 404),
    ),
)
def test_public_announcement_media_follows_exact_current_interval(
    client, admin_client, db, monkeypatch, instant, expected_status
):
    assert _upload(
        admin_client,
        f"announcement-{instant:%H%M%S}.pdf",
        "application/pdf",
        _pdf_bytes(),
    ).status_code == 302
    asset = _latest_asset()
    _publish_announcement_download(
        db,
        asset["id"],
        slug=f"announcement-media-{instant:%H%M%S}",
        valid_from="2026-08-25 10:00:00",
        valid_until="2026-08-25 11:00:00",
    )
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: instant

    response = client.get(f"/media/{asset['id']}/download")

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("instant", "expected_status"),
    (
        (datetime(2026, 8, 25, 10, 0, 0, tzinfo=SHANGHAI), 200),
        (datetime(2026, 8, 25, 10, 0, 1, tzinfo=SHANGHAI), 404),
    ),
)
def test_public_resource_media_follows_exact_seven_day_source_freshness(
    client, admin_client, db, monkeypatch, instant, expected_status
):
    assert _upload(
        admin_client,
        f"source-{instant:%H%M%S}.pdf",
        "application/pdf",
        _pdf_bytes(),
    ).status_code == 302
    asset = _latest_asset()
    _publish_sourced_resource_attachment(
        db, asset["id"], slug=f"source-media-{instant:%H%M%S}"
    )
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: instant

    response = client.get(f"/media/{asset['id']}/download")

    assert response.status_code == expected_status


def test_public_media_rejects_malformed_legacy_reference(
    client, admin_client, db, monkeypatch
):
    assert _upload(
        admin_client, "malformed-reference.pdf", "application/pdf", _pdf_bytes()
    ).status_code == 302
    asset = _latest_asset()
    content_id = create_content_draft(
        ContentDraft(
            entry_type="resource",
            slug="malformed-media-resource",
            title="不得授权的损坏资源",
            summary="持久化损坏的资源不得授权附件。",
            seo_title="不得授权的损坏资源",
            seo_description="验证旧数据损坏时媒体端点关闭。",
            extension={
                "resource_type": "report",
                "is_original": 1,
                "source_name": None,
                "source_url": None,
                "source_url_sha256": None,
                "source_check_code": None,
                "source_checked_at": None,
                "source_check_expires_at": None,
                "source_check_url_sha256": None,
                "original_published_at": "2026-08-20 09:00:00",
                "copyright_notice": "本站原创",
                "attachment_media_id": asset["id"],
            },
        ),
        actor="media-test",
        now=datetime(2026, 8, 24, 10, 0, 0, tzinfo=SHANGHAI),
    )
    db.execute(
        "UPDATE resource_content SET copyright_notice=? WHERE content_item_id=?",
        (sqlite3.Binary(b"x" * 16), content_id),
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-24 10:00:00' "
        "WHERE id=?",
        (content_id,),
    )
    db.commit()
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: datetime(2026, 8, 25, 10, 0, 0, tzinfo=SHANGHAI)

    response = client.get(f"/media/{asset['id']}/download")

    assert response.status_code == 404


def test_public_media_allows_a_healthy_shared_reference_when_another_is_expired(
    client, admin_client, db, monkeypatch
):
    assert _upload(
        admin_client, "shared-reference.pdf", "application/pdf", _pdf_bytes()
    ).status_code == 302
    asset = _latest_asset()
    _publish_announcement_download(
        db,
        asset["id"],
        slug="expired-shared-media-reference",
        valid_from="2026-08-24 08:00:00",
        valid_until="2026-08-24 09:00:00",
    )
    _publish_announcement_download(
        db,
        asset["id"],
        slug="healthy-shared-media-reference",
        valid_from="2026-08-25 09:00:00",
        valid_until="2026-08-25 11:00:00",
    )
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: datetime(2026, 8, 25, 10, 0, 0, tzinfo=SHANGHAI)

    response = client.get(f"/media/{asset['id']}/download")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=0, must-revalidate"


@pytest.mark.parametrize("entry_type", ("case", "industry", "scenario", "service"))
def test_public_media_requires_the_same_complete_projection_as_every_public_detail(
    client, admin_client, db, monkeypatch, entry_type
):
    now = datetime(2026, 8, 25, 10, 0, 0, tzinfo=SHANGHAI)
    assert _upload(
        admin_client,
        f"{entry_type}-projection.png",
        "image/png",
        _image_bytes(),
    ).status_code == 302
    asset = _latest_asset()
    if entry_type == "case":
        content_id, detail_path = _publish_case_image_reference(asset["id"])
    else:
        content_id, detail_path = _publish_catalog_image_reference(
            db, asset["id"], entry_type
        )
    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: now
    assert client.get(detail_path).status_code == 200
    assert client.get(f"/media/{asset['id']}/image").status_code == 200

    _break_public_reference(db, content_id, entry_type)

    assert client.get(detail_path).status_code == 404
    assert client.get(f"/media/{asset['id']}/image").status_code == 404

    _publish_reference(db, asset_id=asset["id"], kind="share")

    shared = client.get(f"/media/{asset['id']}/image")
    assert shared.status_code == 200
    assert shared.headers["Cache-Control"] == "public, max-age=0, must-revalidate"


@pytest.mark.parametrize("reference_kind", ("share", "image_block"))
def test_future_published_image_references_are_private_until_due(
    client, admin_client, db, monkeypatch, reference_kind
):
    assert _upload(admin_client, f"future-{reference_kind}.png", "image/png", _image_bytes()).status_code == 302
    asset = _latest_asset()
    due = datetime(2030, 1, 1, 10, 0, 0, tzinfo=SHANGHAI)
    _publish_reference(
        db,
        asset_id=asset["id"],
        kind=reference_kind,
        publish_at="2030-01-01 10:00:00",
    )

    assert client.get(f"/media/{asset['id']}/image").status_code == 404

    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: due

    assert client.get(f"/media/{asset['id']}/image").status_code == 200


@pytest.mark.parametrize("reference_kind", ("download", "resource"))
def test_future_published_download_references_are_private_until_due(
    client, admin_client, db, monkeypatch, reference_kind
):
    assert _upload(admin_client, f"future-{reference_kind}.pdf", "application/pdf", _pdf_bytes()).status_code == 302
    asset = _latest_asset()
    due = datetime(2030, 1, 1, 10, 0, 0, tzinfo=SHANGHAI)
    if reference_kind == "resource":
        _publish_resource_attachment(db, asset["id"], publish_at="2030-01-01 10:00:00")
    else:
        _publish_reference(
            db,
            asset_id=asset["id"],
            kind=reference_kind,
            publish_at="2030-01-01 10:00:00",
        )

    assert client.get(f"/media/{asset['id']}/download").status_code == 404

    client.application.config["CONTENT_NOW_PROVIDER"] = lambda: due

    assert client.get(f"/media/{asset['id']}/download").status_code == 200


def test_missing_archived_and_unreferenced_public_assets_share_generic_404(
    client, admin_client
):
    assert _upload(admin_client, "unused.png", "image/png", _image_bytes()).status_code == 302
    asset = _latest_asset()
    first = client.get(f"/media/{asset['id']}/image")
    admin_client.post(
        f"/admin/media/{asset['id']}/archive",
        data={"csrf_token": "test-csrf-token"},
    )
    second = client.get(f"/media/{asset['id']}/image")
    third = client.get("/media/999999/image")

    for response in (first, second, third):
        assert response.status_code == 404
        assert b"unused.png" not in response.data
        assert b"Traceback" not in response.data


def test_media_url_helpers_keep_images_and_og_images_separate_from_downloads(client):
    with client.application.test_request_context():
        html = render_template_string(
            '<img src="{{ media_image_url(7) }}">'
            '<meta property="og:image" content="{{ media_image_url(7) }}">'
            '<a class="download" href="{{ media_download_url(8) }}">download</a>'
        )

    assert html.count('/media/7/image') == 2
    assert 'href="/media/8/download"' in html
    assert '/media/7/download' not in html
    assert '/media/8/image' not in html


def test_non_media_requests_keep_one_mebibyte_boundary(admin_client):
    response = admin_client.post(
        "/admin/announcements/new",
        data={
            "csrf_token": "test-csrf-token",
            "title": "oversized",
            "content_html": "x" * (1024 * 1024),
            "status": "draft",
        },
    )

    assert response.status_code == 413


def test_non_media_stream_without_content_length_is_bounded_while_reading(client):
    body = b'{"padding":"' + (b"x" * (1024 * 1024)) + b'"}'
    builder = EnvironBuilder(
        path="/api/assessment",
        method="POST",
        input_stream=io.BytesIO(body),
        content_type="application/json",
    )
    environ = builder.get_environ()
    environ.pop("CONTENT_LENGTH", None)
    environ["wsgi.input"] = _ShortReadInput(body)
    environ["wsgi.input_terminated"] = True

    response = Response.from_app(client.application, environ)

    assert response.status_code == 413


def test_authenticated_media_route_can_reach_validator_above_one_mebibyte(
    admin_client, media_root
):
    response = _upload(
        admin_client,
        "invalid-large.jpg",
        "image/jpeg",
        b"x" * (1024 * 1024 + 1),
    )

    assert response.status_code == 400
    assert list(media_root.iterdir()) == []


def test_unauthenticated_large_media_is_rejected_before_multipart_auth_parsing(
    client, media_root
):
    response = _upload(
        client,
        "anonymous-large.jpg",
        "image/jpeg",
        b"x" * (1024 * 1024 + 1),
    )

    assert response.status_code == 413
    assert list(media_root.iterdir()) == []


def test_early_admin_size_rejections_are_always_private_for_anonymous_and_authenticated(
    client, admin_client
):
    anonymous_client = client.application.test_client()
    anonymous = _upload(
        anonymous_client,
        "anonymous-large.jpg",
        "image/jpeg",
        b"x" * (1024 * 1024 + 1),
    )
    authenticated = admin_client.post(
        "/admin/announcements/new",
        data={
            "csrf_token": "test-csrf-token",
            "title": "oversized",
            "content_html": "x" * (1024 * 1024),
            "status": "draft",
        },
    )

    assert anonymous.status_code == 413
    assert authenticated.status_code == 413
    for response in (anonymous, authenticated):
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["Pragma"] == "no-cache"
        assert response.headers["Expires"] == "0"


def test_media_transport_ceiling_allows_validation_to_enforce_twenty_mebibytes(
    admin_client, media_root
):
    response = _upload(
        admin_client,
        "too-large.pdf",
        "application/pdf",
        b"%PDF-" + b"x" * (20 * 1024 * 1024),
    )

    assert response.status_code == 400
    assert list(media_root.iterdir()) == []


def test_global_transport_ceiling_rejects_media_above_multipart_allowance(
    admin_client, media_root
):
    response = _upload(
        admin_client,
        "transport-too-large.pdf",
        "application/pdf",
        b"%PDF-" + b"x" * (22 * 1024 * 1024),
    )

    assert response.status_code == 413
    assert list(media_root.iterdir()) == []


def test_module_and_test_factories_allow_injection_but_wsgi_requires_safe_production_root():
    environment = os.environ.copy()
    environment.pop("AI_PLATFORM_MEDIA_ROOT", None)
    development = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app; print(app.app.config['MEDIA_UPLOAD_ROOT'])",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    missing = subprocess.run(
        [sys.executable, "-c", "import wsgi"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    outside_environment = {**environment, "AI_PLATFORM_MEDIA_ROOT": str(PROJECT_ROOT)}
    outside = subprocess.run(
        [sys.executable, "-c", "import wsgi"],
        cwd=PROJECT_ROOT,
        env=outside_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    safe_environment = {
        **environment,
        "AI_PLATFORM_MEDIA_ROOT": "/opt/ai-platform/data/media/content",
    }
    production = subprocess.run(
        [
            sys.executable,
            "-c",
            "import wsgi; print(wsgi.app.config['MEDIA_UPLOAD_ROOT'])",
        ],
        cwd=PROJECT_ROOT,
        env=safe_environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert development.returncode == 0
    assert development.stdout.strip().replace("\\", "/").endswith("/data/media")
    assert missing.returncode != 0
    assert outside.returncode != 0
    assert production.returncode == 0
