import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys

from flask import render_template_string
from PIL import Image
from pypdf import PdfWriter

import models


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def _publish_reference(db, *, asset_id, kind):
    slug = f"media-{kind}-{asset_id}"
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
    db.execute("INSERT INTO announcement_content (content_item_id) VALUES (?)", (content_id,))
    if kind in {"image_block", "download"}:
        db.execute(
            "INSERT INTO content_blocks "
            "(content_item_id,block_type,media_asset_id,sort_order) VALUES (?,?,?,0)",
            (content_id, "image_text" if kind == "image_block" else "download", asset_id),
        )
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-24 10:00:00',"
        "updated_at='2026-08-24 10:00:00' WHERE id=?",
        (content_id,),
    )
    db.commit()


def _publish_resource_attachment(db, asset_id):
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
        "(content_item_id,resource_type,is_original,attachment_media_id) "
        "VALUES (?,'report',1,?)",
        (content_id, asset_id),
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-24 10:00:00',"
        "updated_at='2026-08-24 10:00:00' WHERE id=?",
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
    assert published.headers["Cache-Control"] == "public, max-age=31536000, immutable"
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
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
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
        "/admin/announcement/new",
        data={
            "csrf_token": "test-csrf-token",
            "title": "oversized",
            "content_html": "x" * (1024 * 1024),
            "status": "draft",
        },
    )

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
