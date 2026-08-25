from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import io

from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfWriter

import models
import publishing_repository
from content_clock import SHANGHAI
from publishing_service import save_content_draft, schedule_content
from source_url_checker import FetchResult


CSRF = "test-csrf-token"
NOW = datetime(2026, 8, 25, 10, 0, tzinfo=SHANGHAI)


def _case_form(**overrides):
    form = {
        "csrf_token": CSRF,
        "action": "save",
        "slug": "verified-automation-case",
        "title": "经授权匿名的报表自动化案例",
        "summary": "经人工审核的实施过程与量化结果。",
        "seo_title": "报表自动化案例",
        "seo_description": "查看经审核的企业报表自动化实施案例与统计指标。",
        "share_image_media_id": "",
        "verification_code": "authorized_anonymous",
        "is_verified": "1",
        "basis_type": "internal_delivery_record",
        "private_basis_reference": "合同内部编号-1",
        "source_url": "",
        "review_confirmed": "1",
        "privacy_review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "实施过程",
        "blocks-0-body": "<script>private-script</script><p>公开实施过程</p>",
        "blocks-0-media_id": "",
        "metrics-0-name": "报表处理时间",
        "metrics-0-before_value": "8",
        "metrics-0-after_value": "2",
        "metrics-0-unit": "小时",
        "metrics-0-statistical_period": "连续 30 天",
        "metrics-0-evidence_explanation": "依据交付记录中的人工与自动化时长对比。",
    }
    form.update(overrides)
    return form


def _create_case(admin_client, db, **overrides):
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: NOW
    response = admin_client.post("/admin/cases/new", data=_case_form(**overrides))
    assert response.status_code == 302
    row = db.execute(
        "SELECT * FROM content_items WHERE entry_type='case' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    return row


def _edit_form(db, content_id, **overrides):
    item = db.execute(
        "SELECT ci.*,cc.* FROM content_items ci JOIN case_content cc "
        "ON cc.content_item_id=ci.id WHERE ci.id=?",
        (content_id,),
    ).fetchone()
    form = _case_form(
        content_id=str(content_id),
        lock_version=str(item["lock_version"]),
        slug=item["slug"],
        title=item["title"],
        summary=item["summary"],
        seo_title=item["seo_title"],
        seo_description=item["seo_description"],
        share_image_media_id=str(item["share_image_media_id"] or ""),
        verification_code=item["verification_code"],
        is_verified=str(item["is_verified"]),
        basis_type=item["basis_type"],
        private_basis_reference=item["private_basis_reference"] or "",
        source_url=item["source_url"] or "",
    )
    form.update(overrides)
    return form


def _successful_transport():
    class SuccessfulTransport:
        def fetch(self, url, **kwargs):
            return FetchResult(True, "https_ok", url, 200, "text/html", b"ok")

    return SuccessfulTransport()


def _jpeg_with_exif():
    image = Image.new("RGB", (8, 6), (20, 80, 160))
    metadata = Image.Exif()
    metadata[315] = "private photographer"
    output = io.BytesIO()
    image.save(output, format="JPEG", exif=metadata)
    return output.getvalue()


def _pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.metadata = None
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_case_cutover_has_single_v2_owner_and_an_honest_empty_state(
    client, admin_client
):
    case_rules = [rule for rule in client.application.url_map.iter_rules() if rule.rule == "/cases"]
    admin_rules = [
        rule for rule in client.application.url_map.iter_rules() if rule.rule == "/admin/cases"
    ]
    assert len(case_rules) == 1
    assert len(admin_rules) == 1
    assert case_rules[0].endpoint.startswith("public_catalog.")
    assert admin_rules[0].endpoint == "admin.admin_cases_v2"

    response = client.get("/cases")
    assert response.status_code == 200
    assert "暂无已验证案例" in response.get_data(as_text=True)
    assert "某中型制造企业 RAG 知识库落地" not in response.get_data(as_text=True)
    assert "24 个真实" not in response.get_data(as_text=True)

    anonymous = client.application.test_client().get("/admin/cases")
    assert anonymous.status_code == 302
    assert "/admin/login" in anonymous.headers["Location"]
    admin_page = admin_client.get("/admin/cases")
    assert admin_page.status_code == 200
    assert admin_page.headers["Cache-Control"] == "private, no-store"
    assert "/admin/cases/new" in admin_page.get_data(as_text=True)


def test_case_form_is_choice_first_and_exposes_all_seven_safe_block_types(admin_client):
    page = admin_client.get("/admin/cases/new")
    assert page.status_code == 200
    document = BeautifulSoup(page.data, "html.parser")
    assert {
        option.get("value")
        for option in document.select('select[name="verification_code"] option[value]')
    } == {"public_verified", "authorized_anonymous"}
    assert {
        option.get("value")
        for option in document.select('select[name="basis_type"] option[value]')
    } == {"public_source", "client_authorization", "internal_delivery_record"}
    assert {
        option.get("value")
        for option in document.select("[data-new-block-type] option[value]")
    } == {"heading", "rich_text", "image_text", "metric", "steps", "download", "cta"}
    assert document.select_one('input[name="reviewer"]') is None
    assert document.select_one('input[name="contact_email"]') is None


def test_case_writes_require_auth_csrf_exact_fields_and_explicit_privacy_review(
    client, admin_client, db
):
    before = db.execute(
        "SELECT COUNT(*) FROM content_items WHERE entry_type='case'"
    ).fetchone()[0]
    anonymous = client.application.test_client().post(
        "/admin/cases/new", data=_case_form()
    )
    missing_csrf = admin_client.post(
        "/admin/cases/new", data={k: v for k, v in _case_form().items() if k != "csrf_token"}
    )
    obvious_pii = admin_client.post(
        "/admin/cases/new",
        data=_case_form(title="请联系 13800138000 或 customer@example.com 加微信"),
    )
    clean_but_unconfirmed = admin_client.post(
        "/admin/cases/new",
        data={
            k: v
            for k, v in _case_form(action="publish").items()
            if k != "privacy_review_confirmed"
        },
    )
    reviewer_injection = admin_client.post(
        "/admin/cases/new", data=_case_form(reviewer="自然人姓名")
    )

    assert anonymous.status_code == 302
    assert missing_csrf.status_code == 403
    assert obvious_pii.status_code == 400
    assert clean_but_unconfirmed.status_code == 400
    assert reviewer_injection.status_code == 400
    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE entry_type='case'"
    ).fetchone()[0] == before
    assert not {
        "contact_name", "contact_email", "phone", "wechat", "reviewer"
    } & {row[1] for row in db.execute("PRAGMA table_info(case_content)")}


def test_case_publish_requires_authenticity_review_time_and_complete_metric(
    admin_client, db
):
    attempts = (
        _case_form(action="publish", is_verified="0"),
        {k: v for k, v in _case_form(action="publish").items() if k != "review_confirmed"},
        _case_form(action="publish", **{"metrics-0-statistical_period": ""}),
        _case_form(action="publish", **{"metrics-0-evidence_explanation": ""}),
    )
    for form in attempts:
        response = admin_client.post("/admin/cases/new", data=form)
        assert response.status_code == 400

    assert db.execute(
        "SELECT COUNT(*) FROM content_items WHERE entry_type='case' AND status='published'"
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE event_code='content_published'"
    ).fetchone()[0] == 0


def test_authorized_case_publishes_metrics_and_never_leaks_private_evidence(
    admin_client, db
):
    draft = _create_case(admin_client, db)
    response = admin_client.post(
        f"/admin/cases/{draft['id']}",
        data=_edit_form(db, draft["id"], action="publish"),
    )
    assert response.status_code == 302
    extension = db.execute(
        "SELECT * FROM case_content WHERE content_item_id=?", (draft["id"],)
    ).fetchone()
    assert tuple(extension[key] for key in (
        "verification_code", "is_anonymized", "basis_type", "is_verified",
        "review_confirmed", "verified_at",
    )) == (
        "authorized_anonymous", 1, "internal_delivery_record", 1, 1,
        "2026-08-25 10:00:00",
    )

    listing = admin_client.get("/cases")
    detail = admin_client.get("/cases/verified-automation-case")
    assert listing.status_code == 200
    assert detail.status_code == 200
    listing_text = listing.get_data(as_text=True)
    detail_text = detail.get_data(as_text=True)
    assert "经授权匿名案例" in listing_text
    assert "经授权匿名案例" in detail_text
    assert "报表处理时间" in detail_text
    assert "连续 30 天" in detail_text
    assert "依据交付记录中的人工与自动化时长对比" in detail_text
    assert "公开实施过程" in detail_text
    assert "private-script" not in detail_text
    for private_value in (
        "authorized_anonymous", "internal_delivery_record", "合同内部编号-1",
        "private_basis_reference", "reviewer",
    ):
        assert private_value not in listing_text
        assert private_value not in detail_text
    assert '<link rel="canonical" href="https://test.example/cases/verified-automation-case"' in detail_text
    assert admin_client.get("/cases.csv").status_code == 404
    assert db.execute(
        "SELECT COUNT(*) FROM content_blocks WHERE content_item_id=? "
        "AND body_html LIKE '%合同内部编号-1%'",
        (draft["id"],),
    ).fetchone()[0] == 0
    audit_payload = " ".join(
        str(value)
        for row in db.execute(
            "SELECT actor,action,status_code,ip_hash FROM admin_audit_logs"
        )
        for value in row
    )
    assert "合同内部编号-1" not in audit_payload


def test_public_source_check_requires_auth_csrf_hash_lock_and_seven_day_freshness(
    client, admin_client, db
):
    source_url = "https://example.com/public-case"
    draft = _create_case(
        admin_client,
        db,
        slug="public-source-case",
        verification_code="public_verified",
        basis_type="public_source",
        private_basis_reference="",
        source_url=source_url,
    )
    source_hash = hashlib.sha256(source_url.encode()).hexdigest()
    source_form = {
        "csrf_token": CSRF,
        "expected_lock_version": str(draft["lock_version"]),
        "expected_url_sha256": source_hash,
    }
    anonymous = client.application.test_client().post(
        f"/admin/cases/{draft['id']}/source-check", data=source_form
    )
    missing_csrf = admin_client.post(
        f"/admin/cases/{draft['id']}/source-check",
        data={k: v for k, v in source_form.items() if k != "csrf_token"},
    )
    admin_client.application.config["CASE_SOURCE_TRANSPORT"] = _successful_transport()
    checked = admin_client.post(
        f"/admin/cases/{draft['id']}/source-check", data=source_form
    )
    assert anonymous.status_code == 302
    assert missing_csrf.status_code == 403
    assert checked.status_code == 302
    source = db.execute(
        "SELECT source_check_code,source_checked_at,source_check_expires_at,"
        "source_check_url_sha256 FROM case_content WHERE content_item_id=?",
        (draft["id"],),
    ).fetchone()
    assert tuple(source) == (
        "https_ok", "2026-08-25 10:00:00", "2026-09-01 10:00:00", source_hash
    )

    db.execute(
        "UPDATE case_content SET source_checked_at='2026-08-17 09:59:59',"
        "source_check_expires_at='2099-01-01 00:00:00' WHERE content_item_id=?",
        (draft["id"],),
    )
    db.commit()
    stale = admin_client.post(
        f"/admin/cases/{draft['id']}",
        data=_edit_form(db, draft["id"], action="publish"),
    )
    assert stale.status_code == 400
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (draft["id"],)
    ).fetchone()[0] == "draft"


def test_public_source_case_uses_the_exact_public_authenticity_label(
    admin_client, db
):
    source_url = "https://example.com/labeled-public-case"
    draft = _create_case(
        admin_client,
        db,
        slug="labeled-public-case",
        verification_code="public_verified",
        basis_type="public_source",
        private_basis_reference="",
        source_url=source_url,
    )
    admin_client.application.config["CASE_SOURCE_TRANSPORT"] = _successful_transport()
    checked = admin_client.post(
        f"/admin/cases/{draft['id']}/source-check",
        data={
            "csrf_token": CSRF,
            "expected_lock_version": str(draft["lock_version"]),
            "expected_url_sha256": hashlib.sha256(source_url.encode()).hexdigest(),
        },
    )
    assert checked.status_code == 302
    published = admin_client.post(
        f"/admin/cases/{draft['id']}",
        data=_edit_form(db, draft["id"], action="publish"),
    )
    assert published.status_code == 302
    public_text = admin_client.get("/cases/labeled-public-case").get_data(as_text=True)
    assert "真实公开案例" in public_text
    assert "public_verified" not in public_text
    assert "public_source" not in public_text


def test_source_check_concurrent_url_edit_returns_409_and_preserves_the_edit(
    admin_client, db
):
    old_url = "https://example.com/original-case"
    new_url = "https://example.com/edited-case"
    draft = _create_case(
        admin_client,
        db,
        slug="source-race-case",
        verification_code="public_verified",
        basis_type="public_source",
        private_basis_reference="",
        source_url=old_url,
    )
    old_hash = hashlib.sha256(old_url.encode()).hexdigest()

    class ConcurrentEditTransport:
        def fetch(self, url, **kwargs):
            connection = models.get_db()
            try:
                current = publishing_repository.load_content_draft(connection, draft["id"])
                lock_version = connection.execute(
                    "SELECT lock_version FROM content_items WHERE id=?", (draft["id"],)
                ).fetchone()[0]
            finally:
                connection.close()
            extension = dict(current.extension)
            extension["source_url"] = new_url
            extension["source_url_sha256"] = hashlib.sha256(new_url.encode()).hexdigest()
            save_content_draft(
                draft["id"], lock_version, replace(current, extension=extension),
                actor="concurrent-admin", now=NOW,
            )
            return FetchResult(True, "https_ok", url, 200, "text/html", b"ok")

    admin_client.application.config["CASE_SOURCE_TRANSPORT"] = ConcurrentEditTransport()
    response = admin_client.post(
        f"/admin/cases/{draft['id']}/source-check",
        data={
            "csrf_token": CSRF,
            "expected_lock_version": str(draft["lock_version"]),
            "expected_url_sha256": old_hash,
        },
    )
    assert response.status_code == 409
    state = db.execute(
        "SELECT ci.lock_version,cc.source_url,cc.source_check_code,cc.source_checked_at,"
        "cc.source_check_expires_at,cc.source_check_url_sha256 "
        "FROM content_items ci JOIN case_content cc ON cc.content_item_id=ci.id "
        "WHERE ci.id=?",
        (draft["id"],),
    ).fetchone()
    assert state["source_url"] == new_url
    assert state["lock_version"] == draft["lock_version"] + 1
    assert tuple(state[key] for key in (
        "source_check_code", "source_checked_at", "source_check_expires_at",
        "source_check_url_sha256",
    )) == (None, None, None, None)
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_source_checked'",
        (draft["id"],),
    ).fetchone()[0] == 0


def test_case_edit_uses_optimistic_lock_and_preserves_submitted_values_on_conflict(
    admin_client, db
):
    draft = _create_case(admin_client, db, slug="lock-case")
    stale_form = _edit_form(db, draft["id"], title="冲突时保留的标题")
    db.execute(
        "UPDATE content_items SET title='并发编辑标题',lock_version=lock_version+1 "
        "WHERE id=?",
        (draft["id"],),
    )
    db.commit()

    response = admin_client.post(f"/admin/cases/{draft['id']}", data=stale_form)
    assert response.status_code == 409
    assert "冲突时保留的标题" in response.get_data(as_text=True)
    assert db.execute(
        "SELECT title FROM content_items WHERE id=?", (draft["id"],)
    ).fetchone()[0] == "并发编辑标题"


def test_future_archived_and_legacy_cases_are_never_public(admin_client, db):
    future = _create_case(admin_client, db, slug="future-case")
    schedule_content(
        future["id"], future["lock_version"], NOW + timedelta(days=1),
        actor="test-admin", now=NOW,
    )
    assert admin_client.get("/cases/future-case").status_code == 404

    published = _create_case(admin_client, db, slug="archive-case")
    publish_response = admin_client.post(
        f"/admin/cases/{published['id']}",
        data=_edit_form(db, published["id"], action="publish"),
    )
    assert publish_response.status_code == 302
    assert admin_client.get("/cases/archive-case").status_code == 200
    published_lock = db.execute(
        "SELECT lock_version FROM content_items WHERE id=?", (published["id"],)
    ).fetchone()[0]
    wrong_identity = admin_client.post(
        f"/admin/cases/{published['id']}",
        data={
            "csrf_token": CSRF,
            "action": "archive",
            "content_id": str(future["id"]),
            "lock_version": str(published_lock),
        },
    )
    assert wrong_identity.status_code == 400
    assert admin_client.get("/cases/archive-case").status_code == 200
    archived = admin_client.post(
        f"/admin/cases/{published['id']}",
        data={
            "csrf_token": CSRF,
            "action": "archive",
            "content_id": str(published["id"]),
            "lock_version": str(published_lock),
        },
    )
    assert archived.status_code == 302
    assert admin_client.get("/cases/archive-case").status_code == 404

    legacy_group = db.execute(
        "INSERT INTO content_groups (entry_type,canonical_slug,created_at,updated_at) "
        "VALUES ('case','legacy-v2-row','2026-08-24 10:00:00','2026-08-24 10:00:00')"
    ).lastrowid
    legacy_item = db.execute(
        "INSERT INTO content_items "
        "(content_group_id,entry_type,revision_number,slug,title,summary,seo_title,"
        "seo_description,status,lock_version,created_at,updated_at) "
        "VALUES (?,'case',1,'legacy-v2-row','Legacy private case','Summary','SEO',"
        "'Description','draft',1,'2026-08-24 10:00:00','2026-08-24 10:00:00')",
        (legacy_group,),
    ).lastrowid
    db.execute(
        "INSERT INTO case_content "
        "(content_item_id,verification_code,is_anonymized,basis_type,"
        "private_basis_reference,is_verified,review_confirmed,verified_at) "
        "VALUES (?,'authorized_anonymous',1,'private_authorization','legacy-ref',1,1,"
        "'2026-08-24 10:00:00')",
        (legacy_item,),
    )
    trigger_sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='reject_legacy_case_basis_publication'"
    ).fetchone()[0]
    db.execute("DROP TRIGGER reject_legacy_case_basis_publication")
    db.execute(
        "UPDATE content_items SET status='published',published_at='2026-08-24 10:00:00' "
        "WHERE id=?",
        (legacy_item,),
    )
    db.execute(trigger_sql)
    db.commit()
    assert admin_client.get("/cases/legacy-v2-row").status_code == 404
    assert "Legacy private case" not in admin_client.get("/cases").get_data(as_text=True)


def test_case_media_requires_human_confirmation_and_uses_task4_safe_files(
    admin_client, db, media_root
):
    rejected_pdf = admin_client.post(
        "/admin/media",
        data={
            "csrf_token": CSRF,
            "file": (io.BytesIO(_pdf_bytes()), "evidence.pdf", "application/pdf"),
        },
        content_type="multipart/form-data",
    )
    assert rejected_pdf.status_code == 400
    accepted_pdf = admin_client.post(
        "/admin/media",
        data={
            "csrf_token": CSRF,
            "metadata_review_confirmed": "1",
            "file": (io.BytesIO(_pdf_bytes()), "evidence.pdf", "application/pdf"),
        },
        content_type="multipart/form-data",
    )
    assert accepted_pdf.status_code == 302
    pdf_asset = db.execute(
        "SELECT * FROM media_assets WHERE detected_mime='application/pdf' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()

    image_upload = admin_client.post(
        "/admin/media",
        data={
            "csrf_token": CSRF,
            "file": (io.BytesIO(_jpeg_with_exif()), "share.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    assert image_upload.status_code == 302
    image_asset = db.execute(
        "SELECT * FROM media_assets WHERE detected_mime='image/jpeg' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    with Image.open(media_root / image_asset["storage_name"]) as stored:
        assert not stored.getexif()

    draft = _create_case(
        admin_client,
        db,
        slug="case-with-media",
        share_image_media_id=str(image_asset["id"]),
        **{
            "blocks-0-type": "download",
            "blocks-0-title": "脱敏证据摘要",
            "blocks-0-body": "",
            "blocks-0-media_id": str(pdf_asset["id"]),
            "blocks-0-download_label": "下载公开附件",
        },
    )
    without_media_review = _edit_form(
        db,
        draft["id"],
        action="publish",
        share_image_media_id=str(image_asset["id"]),
        **{
            "blocks-0-type": "download",
            "blocks-0-title": "脱敏证据摘要",
            "blocks-0-body": "",
            "blocks-0-media_id": str(pdf_asset["id"]),
            "blocks-0-download_label": "下载公开附件",
        },
    )
    without_media_review.pop("media_review_confirmed")
    rejected = admin_client.post(
        f"/admin/cases/{draft['id']}", data=without_media_review
    )
    assert rejected.status_code == 400
    published_form = dict(without_media_review, media_review_confirmed="1")
    published_form["lock_version"] = str(db.execute(
        "SELECT lock_version FROM content_items WHERE id=?", (draft["id"],)
    ).fetchone()[0])
    published = admin_client.post(
        f"/admin/cases/{draft['id']}", data=published_form
    )
    assert published.status_code == 302
    detail = admin_client.get("/cases/case-with-media")
    assert detail.status_code == 200
    assert f'/media/{pdf_asset["id"]}/download' in detail.get_data(as_text=True)
