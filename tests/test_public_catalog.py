"""Public, read-only catalog routes use only published catalog aggregates."""

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import sqlite3

import pytest
from bs4 import BeautifulSoup

import app as app_module
import blueprints.public_catalog as public_catalog_blueprint
import catalog_content_repository as catalog
from content_clock import SHANGHAI
from content_contracts import ContentBlock, ContentDraft
from content_json import ContentJsonError, decode_database_json
from content_validation import ContentValidationError
import media_service
import publishing_repository
from publishing_service import copy_revision, publish_content, publish_due_content, save_content_draft, schedule_content
from publishing_service import archive_content


INDUSTRY_REQUIRED_SECTIONS = {
    "overview", "business-pains", "departments", "sme-fit",
    "priority-scenarios", "service-packages", "assessment-cta",
}
SCENARIO_REQUIRED_SECTIONS = {
    "problem-boundary", "industries", "departments", "pains", "maturity",
    "prerequisites", "inputs", "outputs", "steps", "metrics", "risks",
    "timeline", "budget", "services", "assessment-cta",
}
NOW = "2026-08-24 10:00:00"
NOW_DATETIME = datetime(2026, 8, 24, 10, 0, 0, tzinfo=SHANGHAI)


def publish_catalog(db):
    """Promote the checked-in neutral catalog inside this disposable test DB."""
    db.execute(
        "UPDATE content_items SET status='published',published_at=? "
        "WHERE entry_type IN ('industry','scenario') AND status='draft'",
        (NOW,),
    )
    db.commit()


@pytest.fixture()
def published_catalog(client, db):
    publish_catalog(db)
    return client


def page(response):
    assert response.status_code == 200
    return BeautifulSoup(response.data, "html.parser")


def test_public_catalog_lists_use_the_shared_shell_and_private_analytics(published_catalog):
    industries = page(published_catalog.get("/industries"))
    scenarios = page(published_catalog.get("/scenarios"))

    assert {card["data-industry-code"] for card in industries.select("[data-industry-code]")} == {
        "manufacturing", "retail", "professional_knowledge", "software_creative"
    }
    assert len(scenarios.select("[data-scenario-code]")) == 12
    for document in (industries, scenarios):
        assert document.select_one('a[href="/assessment"]') is not None
        assert document.select_one('body[data-analytics-page]') is not None


def test_scenario_filters_are_intersection_not_union(published_catalog):
    response = published_catalog.get(
        "/scenarios?industry=manufacturing&department=production&maturity=explore"
    )
    document = page(response)
    codes = {card["data-scenario-code"] for card in document.select("[data-scenario-code]")}

    assert codes == {"mfg_knowledge_assistant"}


@pytest.mark.parametrize("query", (
    "?industry=invalid&department=invalid&maturity=starting&page=-1&per_page=999",
    "?industry=manufacturing&maturity=starting&page=zero&per_page=20.5",
))
def test_invalid_get_filters_fall_back_to_safe_defaults(published_catalog, query):
    document = page(published_catalog.get(f"/scenarios{query}"))
    expected_count = 12 if "industry=invalid" in query else 3
    assert len(document.select("[data-scenario-code]")) == expected_count
    assert document.select_one('select[name="maturity"] option[selected]')["value"] == ""


@pytest.mark.parametrize("maturity", ("explore", "pilot", "scale", "collaborate"))
def test_every_documented_maturity_filter_is_public(published_catalog, maturity):
    document = page(published_catalog.get(f"/scenarios?maturity={maturity}"))
    assert document.select("[data-scenario-code]")


def test_empty_filter_intersection_has_no_unrelated_fallback(published_catalog):
    document = page(published_catalog.get("/scenarios?industry=manufacturing&department=marketing&maturity=collaborate"))
    assert document.select("[data-scenario-code]") == []


@pytest.mark.parametrize("kind,slug,sections", (
    ("industries", "manufacturing", INDUSTRY_REQUIRED_SECTIONS),
    ("scenarios", "mfg-knowledge-assistant", SCENARIO_REQUIRED_SECTIONS),
))
def test_published_detail_has_sections_seo_canonical_and_no_internal_leaks(
    published_catalog, kind, slug, sections
):
    response = published_catalog.get(f"/{kind}/{slug}")
    document = page(response)

    assert sections <= {node["data-content-section"] for node in document.select("[data-content-section]")}
    assert document.select_one('link[rel="canonical"]')["href"] == f"https://test.example/{kind}/{slug}"
    assert document.title.get_text(strip=True)
    assert document.select_one('meta[name="description"]')["content"]
    for forbidden in ("minimum_business_value", "risk_codes_json", "test-admin", "@", "PRIVATE"):
        assert forbidden.encode() not in response.data


def test_draft_detail_is_private_404(client, db):
    row = db.execute(
        "SELECT slug FROM content_items WHERE entry_type='scenario' "
        "AND status='draft' ORDER BY id LIMIT 1"
    ).fetchone()
    response = client.get(f"/scenarios/{row['slug']}")
    assert response.status_code == 404
    assert row["slug"].encode() not in response.data


def test_archived_detail_is_private_404(published_catalog, db):
    row = db.execute(
        "SELECT id,lock_version,slug FROM content_items WHERE entry_type='scenario' "
        "AND status='published' ORDER BY id LIMIT 1"
    ).fetchone()
    archive_content(row["id"], row["lock_version"], actor="test-admin")

    response = published_catalog.get(f"/scenarios/{row['slug']}")
    assert response.status_code == 404
    assert row["slug"].encode() not in response.data


def test_future_published_detail_is_private_404(client, db):
    row = db.execute(
        "SELECT ci.id,ci.slug,ci.content_group_id FROM content_items ci "
        "WHERE ci.entry_type='industry' AND ci.status='draft' ORDER BY ci.id LIMIT 1"
    ).fetchone()
    db.execute(
        "UPDATE content_items SET publish_at=? WHERE id=?",
        ("2030-01-01 00:00:00", row["id"]),
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at=? WHERE id=?",
        (NOW, row["id"]),
    )
    db.commit()
    response = client.get(f"/industries/{row['slug']}")
    assert response.status_code == 404
    assert row["slug"].encode() not in response.data


def test_alias_redirects_to_the_canonical_published_slug(published_catalog, db):
    row = db.execute(
        "SELECT ci.slug,ci.content_group_id FROM content_items ci "
        "WHERE ci.entry_type='industry' AND ci.status='published' ORDER BY ci.id LIMIT 1"
    ).fetchone()

    db.execute(
        "INSERT INTO content_slug_aliases (entry_type,old_slug,content_group_id,created_at) "
        "VALUES ('industry','old-manufacturing',?,?)",
        (row["content_group_id"], NOW),
    )
    db.commit()
    alias = published_catalog.get("/industries/old-manufacturing")
    assert alias.status_code == 301
    assert alias.headers["Location"].endswith(f"/industries/{row['slug']}")


def test_every_public_complete_detail_has_its_required_sections(published_catalog):
    expected = (
        ("/industries", INDUSTRY_REQUIRED_SECTIONS, tuple(
            item["slug"] for item in catalog.public_industries(NOW_DATETIME)
        )),
        ("/scenarios", SCENARIO_REQUIRED_SECTIONS, tuple(
            item.slug for item in catalog.public_scenarios(
                catalog.ScenarioFilters(), catalog.PageRequest(1, 20), NOW_DATETIME
            ).items
        )),
    )
    for prefix, sections, slugs in expected:
        for slug in slugs:
            document = page(published_catalog.get(f"{prefix}/{slug}"))
            assert sections <= {node["data-content-section"] for node in document.select("[data-content-section]")}
    assert published_catalog.get("/scenarios/data-process-foundation").status_code == 404


def test_public_catalog_has_private_no_store_analytics_response(published_catalog):
    for path in ("/industries", "/industries/manufacturing", "/scenarios", "/scenarios/mfg-knowledge-assistant"):
        response = published_catalog.get(path)
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["Pragma"] == "no-cache"
        assert response.headers["Expires"] == "0"


def test_public_base_url_is_required_https_origin(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_PLATFORM_PUBLIC_BASE_URL", raising=False)
    for value in (None, "http://example.test", "https://user@example.test", "https://example.test/path", "https://example.test/?q=1", "https://example.test/#fragment"):
        config = {"TESTING": False, "SECRET_KEY": "test", "PUBLIC_BASE_URL": value,
                  "MEDIA_UPLOAD_ROOT": str(tmp_path / "media")}
        with pytest.raises(ValueError):
            app_module.create_app(config)


def _ready_media(db, name, mime):
    asset_id = db.execute(
        "INSERT INTO media_assets "
        "(storage_name,display_name,detected_mime,byte_size,sha256,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'pending',?,?)",
        (name, name, mime, 1, hashlib.sha256(name.encode()).hexdigest(), NOW, NOW),
    ).lastrowid
    db.execute(
        "UPDATE media_assets SET status='ready',scan_result_code='validated',"
        "scan_checked_at=?,ready_at=?,updated_at=? WHERE id=?",
        (NOW, NOW, NOW, asset_id),
    )
    db.commit()
    return asset_id


def _publish_all_governed_blocks(db):
    row = db.execute(
        "SELECT ci.id,ci.lock_version,ci.content_group_id,g.scenario_id,ci.slug "
        "FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "WHERE ci.entry_type='scenario' AND ci.status='draft' "
        "AND g.scenario_id=(SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant')"
    ).fetchone()
    image_id = _ready_media(db, "review-image.png", "image/png")
    download_id = _ready_media(db, "review-download.pdf", "application/pdf")
    draft = ContentDraft(
        entry_type="scenario", slug=row["slug"], title="受控区块公开测试",
        summary="通过受控发布流程验证每类内容区块的公开渲染。",
        seo_title="受控区块公开测试", seo_description="验证公开场景区块的安全渲染。",
        content_group_id=row["content_group_id"], extension={"scenario_id": row["scenario_id"]},
        maturity_codes=("explore",),
        blocks=(
            ContentBlock("heading", title="REVIEW-HEADING", settings={"level": 2}),
            ContentBlock("rich_text", title="REVIEW-RICH-TITLE", body_html="<p>REVIEW-RICH</p>", settings={}),
            ContentBlock("image_text", title="REVIEW-IMAGE", body_html="<p>REVIEW-IMAGE-BODY</p>", settings={"alignment": "left", "alt_text": "REVIEW-ALT"}, media_asset_id=image_id),
            ContentBlock("metric", title="REVIEW-METRIC-TITLE", settings={"value": "REVIEW-METRIC", "unit": "项"}),
            ContentBlock("steps", title="REVIEW-STEPS", settings={"items": ("REVIEW-STEP-ONE", "REVIEW-STEP-TWO")}),
            ContentBlock("download", title="REVIEW-DOWNLOAD-TITLE", settings={"label": "REVIEW-DOWNLOAD"}, media_asset_id=download_id),
            ContentBlock("cta", title="REVIEW-CTA-TITLE", settings={"label": "REVIEW-CTA", "url": "/assessment", "style": "primary"}),
        ),
    )
    lock_version = save_content_draft(row["id"], row["lock_version"], draft, actor="test-admin", now=NOW_DATETIME)
    publish_content(row["id"], lock_version, actor="test-admin", now=NOW_DATETIME)
    return row["slug"], image_id, download_id


def _publish_future_governed_blocks(db, *, due):
    """Build a future-dated published scenario solely inside the disposable DB."""
    row = db.execute(
        "SELECT ci.id,ci.lock_version,ci.content_group_id,g.scenario_id,ci.slug "
        "FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "WHERE ci.entry_type='scenario' AND ci.status='draft' "
        "AND g.scenario_id=(SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant')"
    ).fetchone()
    image_id = _ready_media(db, "future-review-image.png", "image/png")
    download_id = _ready_media(db, "future-review-download.pdf", "application/pdf")
    draft = ContentDraft(
        entry_type="scenario", slug=row["slug"], title="未来受控媒体测试",
        summary="验证未到期的内容不会提前释放公开媒体。",
        seo_title="未来受控媒体测试", seo_description="验证受控媒体严格遵从公开发布时间。",
        content_group_id=row["content_group_id"], extension={"scenario_id": row["scenario_id"]},
        maturity_codes=("explore",),
        blocks=(
            ContentBlock(
                "image_text", title="未来图片", body_html="<p>未来内容概述</p>",
                settings={"alignment": "left", "alt_text": "未来图片"}, media_asset_id=image_id,
            ),
            ContentBlock("download", title="未来下载", settings={"label": "未来下载"}, media_asset_id=download_id),
        ),
    )
    lock_version = save_content_draft(row["id"], row["lock_version"], draft, actor="test-admin", now=NOW_DATETIME)
    due_text = due.strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "UPDATE content_items SET status='published',published_at=?,publish_at=?,"
        "lock_version=lock_version+1,updated_at=? WHERE id=?",
        (NOW, due_text, NOW, row["id"]),
    )
    db.commit()
    return row["slug"], image_id, download_id, lock_version


def test_formally_published_governed_block_types_render_through_safe_public_http(client, db):
    slug, image_id, download_id = _publish_all_governed_blocks(db)

    response = client.get(f"/scenarios/{slug}")
    document = page(response)
    assert {node["data-content-block"] for node in document.select("[data-content-block]")} >= {
        "heading", "rich_text", "image_text", "metric", "steps", "download", "cta"
    }
    for marker in ("REVIEW-HEADING", "REVIEW-RICH", "REVIEW-IMAGE-BODY", "REVIEW-METRIC", "REVIEW-STEP-ONE", "REVIEW-DOWNLOAD", "REVIEW-CTA"):
        assert marker.encode() in response.data
    assert document.select_one(f'img[src="/media/{image_id}/image"]')["alt"] == "REVIEW-ALT"
    assert document.select_one(f'a[href="/media/{download_id}/download"]') is not None
    assert document.select_one('[data-content-block="cta"] a[href="/assessment"].btn-primary') is not None


@pytest.mark.parametrize(("block_type", "mime"), (("image_text", "application/pdf"), ("download", "image/png")))
def test_formal_publish_rejects_block_media_with_wrong_mime(db, block_type, mime):
    row = db.execute(
        "SELECT ci.id,ci.lock_version FROM content_items ci WHERE ci.entry_type='scenario' "
        "AND ci.status='draft' AND ci.content_group_id=(SELECT id FROM content_groups "
        "WHERE scenario_id=(SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'))"
    ).fetchone()
    media_id = _ready_media(db, f"wrong-{block_type}", mime)
    draft = publishing_repository.load_content_draft(db, row["id"])
    block = ContentBlock(
        block_type, title="媒体类型校验", body_html="<p>媒体类型校验正文</p>",
        settings={"alignment": "left", "alt_text": "示意图"} if block_type == "image_text" else {"label": "下载文件"},
        media_asset_id=media_id,
    )
    lock_version = save_content_draft(
        row["id"], row["lock_version"], replace(draft, blocks=(block,)),
        actor="test-admin", now=NOW_DATETIME,
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(row["id"], lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "block_media_mime_invalid"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (row["id"],)).fetchone()[0] == "draft"
    assert db.execute("SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'", (row["id"],)).fetchone()[0] == 0


def test_formally_published_block_media_urls_stream_real_matching_files(client, db, media_root):
    slug, image_id, download_id = _publish_all_governed_blocks(db)
    (media_root / "review-image.png").write_bytes(b"\x89PNG\r\n\x1a\npublic-image")
    (media_root / "review-download.pdf").write_bytes(b"%PDF-1.4\npublic-download\n%%EOF\n")

    response = client.get(f"/scenarios/{slug}")
    document = page(response)
    image_url = document.select_one(f'img[src="/media/{image_id}/image"]')["src"]
    download_url = document.select_one(f'a[href="/media/{download_id}/download"]')["href"]

    assert client.get(image_url).status_code == 200
    assert client.get(download_url).status_code == 200


def test_future_published_scenario_hides_detail_and_block_media_until_due(
    client, db, media_root, monkeypatch
):
    due = datetime(2030, 1, 1, 10, 0, 0, tzinfo=SHANGHAI)
    slug, image_id, download_id, _ = _publish_future_governed_blocks(db, due=due)
    (media_root / "future-review-image.png").write_bytes(b"\x89PNG\r\n\x1a\nfuture-image")
    (media_root / "future-review-download.pdf").write_bytes(b"%PDF-1.4\nfuture-download\n%%EOF\n")

    assert client.get(f"/scenarios/{slug}").status_code == 404
    assert client.get(f"/media/{image_id}/image").status_code == 404
    assert client.get(f"/media/{download_id}/download").status_code == 404

    monkeypatch.setattr(public_catalog_blueprint, "shanghai_now", lambda: due)
    monkeypatch.setattr(media_service, "shanghai_now", lambda: due)

    assert client.get(f"/scenarios/{slug}").status_code == 200
    assert client.get(f"/media/{image_id}/image").status_code == 200
    assert client.get(f"/media/{download_id}/download").status_code == 200


@pytest.mark.parametrize(("block_type", "settings", "media_asset_id"), (
    ("heading", {"level": 2.0}, None),
    ("download", {"label": {"not": "text"}}, None),
    ("cta", {"label": ["not text"], "url": "/assessment", "style": "primary"}, None),
    ("image_text", {"alignment": "left", "alt_text": "图"}, -1),
    ("image_text", {"alignment": ["left"], "alt_text": "图"}, None),
))
def test_public_block_projection_rejects_nonexact_settings_and_media_types(block_type, settings, media_asset_id):
    row = {
        "block_type": block_type, "title": "标题", "body_html": "<p>正文</p>",
        "settings_json": json.dumps(settings), "media_asset_id": media_asset_id,
    }

    assert catalog._public_block(row) is None


def test_scenario_required_sections_use_explicit_reviewed_inputs(published_catalog):
    document = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))
    inputs = {node.get_text(strip=True) for node in document.select('[data-content-section="inputs"] li')}
    prerequisites = {node.get_text(strip=True) for node in document.select('[data-content-section="prerequisites"] li')}
    metrics = document.select('[data-content-section="metrics"] li')
    risks = document.select('[data-content-section="risks"] li')

    assert inputs == {"设备与工艺知识文档的受控副本", "近三个月高频现场问题清单"}
    assert inputs.isdisjoint(prerequisites)
    assert all(not value.startswith(("部门：", "业务问题：")) for value in inputs)
    assert metrics and risks
    assert all("_" not in node.get_text() for node in risks)


def test_scenario_with_missing_required_structured_data_is_not_publicly_available(published_catalog, db):
    service = db.execute(
        "SELECT service_id FROM scenario_services link JOIN scenarios s ON s.id=link.scenario_id "
        "WHERE s.code='mfg_knowledge_assistant' LIMIT 1"
    ).fetchone()
    db.execute("UPDATE services SET prerequisites_json='[]' WHERE id=?", (service["service_id"],))
    db.commit()

    assert published_catalog.get("/scenarios/mfg-knowledge-assistant").status_code == 404


def _saved_scenario_revision(db):
    publish_catalog(db)
    current = db.execute(
        "SELECT ci.id,ci.lock_version,ci.content_group_id,g.scenario_id FROM content_items ci "
        "JOIN content_groups g ON g.id=ci.content_group_id WHERE ci.entry_type='scenario' "
        "AND ci.status='published' AND g.scenario_id=(SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant')"
    ).fetchone()
    revision_id = copy_revision(current["id"], actor="test-admin", now=NOW_DATETIME)
    draft = publishing_repository.load_content_draft(db, revision_id)
    lock_version = save_content_draft(revision_id, 1, draft, actor="test-admin", now=NOW_DATETIME)
    return current, revision_id, lock_version


def _saved_industry_revision(db):
    publish_catalog(db)
    current = db.execute(
        "SELECT ci.id,ci.lock_version,ci.content_group_id,g.industry_id FROM content_items ci "
        "JOIN content_groups g ON g.id=ci.content_group_id WHERE ci.entry_type='industry' "
        "AND ci.status='published' AND g.industry_id=(SELECT id FROM industries WHERE code='manufacturing')"
    ).fetchone()
    revision_id = copy_revision(current["id"], actor="test-admin", now=NOW_DATETIME)
    return current, revision_id


def _assert_unpublished_revision(db, current_id, revision_id, *, lock_version=None):
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current_id,)).fetchone()[0] == "published"
    revision = db.execute("SELECT status,lock_version FROM content_items WHERE id=?", (revision_id,)).fetchone()
    assert revision["status"] == "draft"
    if lock_version is not None:
        assert revision["lock_version"] == lock_version
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'",
        (revision_id,),
    ).fetchone()[0] == 0


def _corrupt_one_scenario_text_source(db, scenario_id, revision_id, source, value):
    """Keep a valid peer value and corrupt one required public text source."""
    if source == "industry":
        branch = db.execute(
            "SELECT ib.id AS branch_id,i.id AS industry_id FROM industry_branches ib "
            "JOIN industries i ON i.id=ib.industry_id WHERE i.code='retail' "
            "AND ib.status='published' ORDER BY ib.id LIMIT 1"
        ).fetchone()
        db.execute(
            "INSERT OR IGNORE INTO scenario_branches(scenario_id,industry_branch_id) VALUES (?,?)",
            (scenario_id, branch["branch_id"]),
        )
        db.execute("UPDATE industries SET name=? WHERE id=?", (value, branch["industry_id"]))
    elif source == "department":
        db.execute(
            "UPDATE departments SET name=? WHERE id=(SELECT department_id FROM "
            "scenario_departments WHERE scenario_id=? ORDER BY department_id LIMIT 1)",
            (value, scenario_id),
        )
    elif source == "pain":
        db.execute(
            "UPDATE pain_points SET name=? WHERE id=(SELECT pain_point_id FROM "
            "scenario_pains WHERE scenario_id=? ORDER BY pain_point_id LIMIT 1)",
            (value, scenario_id),
        )
    elif source == "input":
        if type(value) is not str:
            db.execute("PRAGMA ignore_check_constraints=ON")
        try:
            db.execute(
                "UPDATE scenario_public_inputs SET input_text=? WHERE id=(SELECT id FROM "
                "scenario_public_inputs WHERE content_item_id=? ORDER BY sort_order,id LIMIT 1)",
                (value, revision_id),
            )
        finally:
            if type(value) is not str:
                db.execute("PRAGMA ignore_check_constraints=OFF")
    elif source == "deliverable":
        db.execute(
            "UPDATE service_deliverables SET title=? WHERE id=(SELECT sd.id FROM "
            "service_deliverables sd JOIN scenario_services ss ON ss.service_id=sd.service_id "
            "WHERE ss.scenario_id=? AND sd.status='published' ORDER BY sd.id LIMIT 1)",
            (value, scenario_id),
        )
    else:
        raise AssertionError(source)
    db.commit()


def _corrupt_one_industry_text_source(db, industry_id, source, value):
    table = {
        "pain": ("pain_points", "industry_id=?"),
        "department": ("departments", "industry_id=?"),
        "company_size": ("company_sizes", "1=1"),
    }[source]
    table_name, predicate = table
    parameters = (industry_id,) if source != "company_size" else ()
    row = db.execute(
        f"SELECT id FROM {table_name} WHERE status='published' AND {predicate} ORDER BY id LIMIT 1",
        parameters,
    ).fetchone()
    db.execute(f"UPDATE {table_name} SET name=? WHERE id=?", (value, row["id"]))
    db.commit()


@pytest.mark.parametrize("source", ("industry", "department", "pain", "input", "deliverable"))
@pytest.mark.parametrize("value", (sqlite3.Binary(b"not-text"), " "), ids=("blob", "blank"))
def test_scenario_formal_publication_rejects_each_mixed_invalid_required_text_source(
    client, db, source, value
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    before = client.get("/scenarios/mfg-knowledge-assistant")
    assert before.status_code == 200
    if source == "input" and value == " ":
        with pytest.raises(sqlite3.IntegrityError):
            _corrupt_one_scenario_text_source(
                db, current["scenario_id"], revision_id, source, value
            )
        return
    _corrupt_one_scenario_text_source(
        db, current["scenario_id"], revision_id, source, value
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)
    if source == "input":
        assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


@pytest.mark.parametrize("source", ("pain", "department", "company_size"))
@pytest.mark.parametrize("value", (sqlite3.Binary(b"not-text"), " "), ids=("blob", "blank"))
def test_industry_formal_publication_rejects_each_mixed_invalid_required_text_source(
    db, source, value
):
    current, revision_id = _saved_industry_revision(db)
    _corrupt_one_industry_text_source(db, current["industry_id"], source, value)

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "industry_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=1)


def test_due_scenario_with_blob_input_keeps_old_public_revision_and_isolates_batch_failure(client, db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    due = NOW_DATETIME + timedelta(hours=1)
    schedule_content(revision_id, lock_version, due, actor="test-admin", now=NOW_DATETIME)
    _corrupt_one_scenario_text_source(
        db, current["scenario_id"], revision_id, "input", sqlite3.Binary(b"not-text")
    )
    healthy = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='retail_ai_service' "
        "AND ci.status='published'"
    ).fetchone()
    healthy_revision = copy_revision(healthy["id"], actor="test-admin", now=NOW_DATETIME)
    schedule_content(healthy_revision, 1, due, actor="test-admin", now=NOW_DATETIME)

    result = publish_due_content(actor="test-admin", now=due)

    assert healthy_revision in result.published_ids
    assert (revision_id, "validation_failed") in result.failures
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=4)
    assert db.execute("SELECT publish_at FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] is None
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_due_failed'",
        (revision_id,),
    ).fetchone()[0] == 1
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


@pytest.mark.parametrize("source", ("industry", "department", "pain", "input", "deliverable"))
def test_public_scenario_read_gate_rejects_a_mixed_blob_required_text_source(client, db, source):
    scenario = db.execute(
        "SELECT s.id,ci.id AS content_item_id FROM scenarios s JOIN content_groups g "
        "ON g.scenario_id=s.id JOIN content_items ci ON ci.content_group_id=g.id "
        "WHERE s.code='mfg_knowledge_assistant' AND ci.status='draft'"
    ).fetchone()
    _corrupt_one_scenario_text_source(
        db, scenario["id"], scenario["content_item_id"], source, sqlite3.Binary(b"not-text")
    )
    publish_catalog(db)

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404
    document = page(client.get("/scenarios"))
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in document.select("[data-scenario-code]")
    }


@pytest.mark.parametrize("source", ("pain", "department", "company_size"))
def test_public_industry_read_gate_rejects_a_mixed_blob_required_text_source(client, db, source):
    industry = db.execute("SELECT id FROM industries WHERE code='manufacturing'").fetchone()
    _corrupt_one_industry_text_source(
        db, industry["id"], source, sqlite3.Binary(b"not-text")
    )
    publish_catalog(db)

    document = page(client.get("/industries"))
    assert "manufacturing" not in {
        card["data-industry-code"] for card in document.select("[data-industry-code]")
    }
    assert client.get("/industries/manufacturing").status_code == 404


def test_archived_invalid_industry_text_row_does_not_block_a_complete_replacement(db):
    current, revision_id = _saved_industry_revision(db)
    row = db.execute(
        "SELECT id FROM pain_points WHERE industry_id=? AND status='published' ORDER BY id LIMIT 1",
        (current["industry_id"],),
    ).fetchone()
    db.execute(
        "UPDATE pain_points SET name=?,status='archived' WHERE id=?",
        (sqlite3.Binary(b"not-text"), row["id"]),
    )
    db.commit()

    publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "published"


@pytest.mark.parametrize("bad_settings", (
    sqlite3.Binary(b"{}"),
    '{"unreviewed":"extra"}',
), ids=("blob", "wrong_schema"))
def test_public_projection_fails_closed_when_any_persisted_block_cannot_be_projected(
    client, db, bad_settings
):
    revision = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='mfg_knowledge_assistant' "
        "AND ci.status='draft'"
    ).fetchone()
    db.execute(
        "INSERT INTO content_blocks(content_item_id,block_type,title,body_html,settings_json,media_asset_id,sort_order) "
        "VALUES (?,'rich_text','无效持久化块','<p>不会公开</p>',?,NULL,99)",
        (revision["id"], bad_settings),
    )
    db.commit()
    publish_catalog(db)

    detail = client.get("/scenarios/mfg-knowledge-assistant")
    listing = client.get("/scenarios")

    assert detail.status_code == 404
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in page(listing).select("[data-scenario-code]")
    }


@pytest.mark.parametrize("bad_settings", (
    sqlite3.Binary(b"{}"),
    '{"unreviewed":"extra"}',
), ids=("blob", "wrong_schema"))
def test_formal_publish_rejects_any_unprojectable_persisted_block_before_archiving_current(
    db, bad_settings
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    db.execute(
        "INSERT INTO content_blocks(content_item_id,block_type,title,body_html,settings_json,media_asset_id,sort_order) "
        "VALUES (?,'rich_text','无效持久化块','<p>不会公开</p>',?,NULL,99)",
        (revision_id, bad_settings),
    )
    db.commit()

    with pytest.raises(ContentValidationError):
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


@pytest.mark.parametrize("raw", (
    r'"\ud800"',
    r'{"\ud800":"ok"}',
    r'{"items":["\ud800"]}',
))
def test_bounded_database_json_rejects_lone_surrogates_in_every_text_position(raw):
    with pytest.raises(ContentJsonError):
        decode_database_json(raw)


def _write_surrogate_block_settings(db, revision_id):
    db.execute(
        "UPDATE content_blocks SET block_type='steps',settings_json=? WHERE content_item_id=?",
        (r'{"items":["\ud800"]}', revision_id),
    )
    db.commit()


def test_formal_publish_rejects_surrogate_block_settings_without_archiving_current_revision(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _write_surrogate_block_settings(db, revision_id)

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "content_json_invalid"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


def test_due_surrogate_block_failure_is_validation_failed_and_does_not_stop_a_healthy_item(client, db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    due = NOW_DATETIME + timedelta(hours=1)
    schedule_content(revision_id, lock_version, due, actor="test-admin", now=NOW_DATETIME)
    _write_surrogate_block_settings(db, revision_id)
    healthy = db.execute(
        "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='retail_ai_service' "
        "AND ci.status='published'"
    ).fetchone()
    healthy_revision = copy_revision(healthy["id"], actor="test-admin", now=NOW_DATETIME)
    schedule_content(healthy_revision, 1, due, actor="test-admin", now=NOW_DATETIME)

    result = publish_due_content(actor="test-admin", now=due)

    assert healthy_revision in result.published_ids
    assert (revision_id, "validation_failed") in result.failures
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=4)
    assert db.execute("SELECT publish_at FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] is None
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_due_failed'",
        (revision_id,),
    ).fetchone()[0] == 1
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200


@pytest.mark.parametrize("source", (
    "implementation_steps_json", "prerequisites_json", "acceptance_json",
))
def test_surrogate_service_json_is_private_and_rejected_by_formal_publication(client, db, source):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _replace_scenario_json_source(
        db, current["scenario_id"], revision_id, source, r'["\ud800"]'
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "content_json_invalid"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)
    db.execute(
        "UPDATE content_items SET status='archived',archived_at=?,updated_at=? WHERE id=?",
        (NOW, NOW, current["id"]),
    )
    db.execute(
        "UPDATE content_items SET status='published',published_at=? WHERE id=?",
        (NOW, revision_id),
    )
    db.commit()
    detail = client.get("/scenarios/mfg-knowledge-assistant")
    listing = client.get("/scenarios")
    assert detail.status_code == 404
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in page(listing).select("[data-scenario-code]")
    }


def test_bounded_database_json_keeps_normal_chinese_and_emoji_text():
    assert decode_database_json('{"items":["中文😀"]}') == {"items": ["中文😀"]}


def test_industry_with_blank_overview_cannot_replace_a_healthy_public_revision(db):
    current, revision_id = _saved_industry_revision(db)
    draft = publishing_repository.load_content_draft(db, revision_id)
    lock_version = save_content_draft(
        revision_id,
        1,
        replace(draft, blocks=(ContentBlock("rich_text", body_html="<p> </p>"),)),
        actor="test-admin",
        now=NOW_DATETIME,
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "industry_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


@pytest.mark.parametrize("missing", ("pain", "department", "company_size", "scenario", "service"))
def test_industry_publication_requires_each_live_public_dependency(db, missing):
    current, revision_id = _saved_industry_revision(db)
    industry_id = current["industry_id"]
    if missing == "pain":
        db.execute("UPDATE pain_points SET status='archived' WHERE industry_id=?", (industry_id,))
    elif missing == "department":
        db.execute("UPDATE departments SET status='archived' WHERE industry_id=?", (industry_id,))
    elif missing == "company_size":
        db.execute("UPDATE company_sizes SET status='archived'")
    elif missing == "scenario":
        db.execute(
            "UPDATE scenarios SET status='archived' WHERE id IN ("
            "SELECT sb.scenario_id FROM scenario_branches sb JOIN industry_branches ib "
            "ON ib.id=sb.industry_branch_id WHERE ib.industry_id=?)",
            (industry_id,),
        )
    else:
        db.execute(
            "UPDATE services SET status='archived' WHERE id IN ("
            "SELECT DISTINCT ss.service_id FROM scenario_services ss JOIN scenario_branches sb "
            "ON sb.scenario_id=ss.scenario_id JOIN industry_branches ib "
            "ON ib.id=sb.industry_branch_id WHERE ib.industry_id=?)",
            (industry_id,),
        )
    db.commit()

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "industry_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=1)


def test_public_complete_industry_revision_replaces_its_previous_revision(db):
    current, revision_id = _saved_industry_revision(db)

    result = publish_content(revision_id, 1, actor="test-admin", now=NOW_DATETIME)

    assert (result.published_id, result.archived_id) == (revision_id, current["id"])
    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "published"


def test_due_industry_with_later_missing_overview_fails_before_archiving_current_revision(db):
    current, revision_id = _saved_industry_revision(db)
    due = NOW_DATETIME + timedelta(hours=1)
    schedule_content(revision_id, 1, due, actor="test-admin", now=NOW_DATETIME)
    db.execute("UPDATE content_blocks SET body_html='<p> </p>' WHERE content_item_id=?", (revision_id,))
    db.commit()

    result = publish_due_content(actor="test-admin", now=due)

    assert result.published_ids == ()
    assert result.failures == ((revision_id, "validation_failed"),)
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=3)
    assert db.execute("SELECT publish_at FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] is None


def _break_scenario_public_source(db, scenario_id, revision_id, source):
    if source == "industry":
        db.execute("UPDATE industries SET status='archived' WHERE id=(SELECT i.id FROM industries i JOIN industry_branches ib ON ib.industry_id=i.id JOIN scenario_branches sb ON sb.industry_branch_id=ib.id WHERE sb.scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "branch":
        db.execute("UPDATE industry_branches SET status='archived' WHERE id=(SELECT industry_branch_id FROM scenario_branches WHERE scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "department":
        db.execute("UPDATE departments SET status='archived' WHERE id=(SELECT department_id FROM scenario_departments WHERE scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "pain":
        db.execute("UPDATE pain_points SET status='archived' WHERE id=(SELECT pain_point_id FROM scenario_pains WHERE scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "maturity":
        db.execute("DELETE FROM content_maturity_levels WHERE content_item_id=?", (revision_id,))
    elif source == "input":
        db.execute("DELETE FROM scenario_public_inputs WHERE content_item_id=?", (revision_id,))
    elif source == "service":
        db.execute("UPDATE services SET min_weeks=0 WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "prerequisite":
        db.execute("UPDATE services SET prerequisites_json='[\"\"]' WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario_id,))
    elif source == "output":
        db.execute(
            "UPDATE service_deliverables SET title=' ' WHERE service_id IN "
            "(SELECT service_id FROM scenario_services WHERE scenario_id=?) "
            "AND status='published'",
            (scenario_id,),
        )
    elif source == "risk":
        db.execute("UPDATE scenarios SET risk_codes_json='[\"unknown\"]' WHERE id=?", (scenario_id,))
    elif source == "narrative":
        db.execute("UPDATE content_blocks SET body_html='' WHERE content_item_id=?", (revision_id,))
    else:
        raise AssertionError(source)
    db.commit()


@pytest.mark.parametrize("source", (
    "industry", "branch", "department", "pain", "maturity", "input", "service",
    "prerequisite", "output", "risk", "narrative",
))
def test_incomplete_scenario_revision_is_rejected_before_replacing_public_revision(db, source):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _break_scenario_public_source(db, current["scenario_id"], revision_id, source)

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "published"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "draft"
    assert db.execute("SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'", (revision_id,)).fetchone()[0] == 0


def test_due_scenario_with_later_missing_input_fails_without_archiving_current_revision(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    scheduled = schedule_content(
        revision_id, lock_version, NOW_DATETIME + timedelta(hours=1), actor="test-admin", now=NOW_DATETIME
    )
    _break_scenario_public_source(db, current["scenario_id"], revision_id, "input")

    result = publish_due_content(actor="test-admin", now=NOW_DATETIME + timedelta(hours=1))

    assert result.published_ids == ()
    assert result.failures == ((revision_id, "validation_failed"),)
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "published"
    draft = db.execute("SELECT status,publish_at FROM content_items WHERE id=?", (revision_id,)).fetchone()
    assert tuple(draft) == ("draft", None)
    assert db.execute("SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'", (revision_id,)).fetchone()[0] == 0


def test_draft_input_damage_does_not_change_current_public_revision(published_catalog, db):
    current, revision_id, _ = _saved_scenario_revision(db)
    before = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))
    before_inputs = [item.get_text(strip=True) for item in before.select('[data-content-section="inputs"] li')]
    db.execute("DELETE FROM scenario_public_inputs WHERE content_item_id=?", (revision_id,))
    db.commit()

    after = page(published_catalog.get("/scenarios/mfg-knowledge-assistant"))

    assert [item.get_text(strip=True) for item in after.select('[data-content-section="inputs"] li')] == before_inputs
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "published"


def test_copied_inputs_are_revision_bound_and_published_rows_are_immutable(db):
    current, revision_id, _ = _saved_scenario_revision(db)
    previous = db.execute(
        "SELECT input_text,sort_order FROM scenario_public_inputs WHERE content_item_id=? ORDER BY sort_order,id",
        (current["id"],),
    ).fetchall()
    copied = db.execute(
        "SELECT input_text,sort_order FROM scenario_public_inputs WHERE content_item_id=? ORDER BY sort_order,id",
        (revision_id,),
    ).fetchall()

    assert copied == previous
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE scenario_public_inputs SET input_text='不可修改' WHERE content_item_id=?", (current["id"],))


def test_archived_historical_deliverable_does_not_block_valid_published_replacement(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    service_id = db.execute(
        "SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1", (current["scenario_id"],)
    ).fetchone()[0]
    db.execute(
        "INSERT INTO service_deliverables (code,service_id,title,status,sort_order) "
        "VALUES ('test:replacement-deliverable',?,'保留交付物','published',999)",
        (service_id,),
    )
    db.execute(
        "UPDATE service_deliverables SET status='archived' WHERE id=("
        "SELECT id FROM service_deliverables WHERE service_id=? AND status='published' ORDER BY id LIMIT 1)",
        (service_id,),
    )
    db.commit()

    publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "published"


def test_published_blank_deliverable_cannot_replace_a_healthy_scenario_revision(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    service_id = db.execute(
        "SELECT service_id FROM scenario_services WHERE scenario_id=? ORDER BY service_id LIMIT 1",
        (current["scenario_id"],),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO service_deliverables (code,service_id,title,status,sort_order) "
        "VALUES ('test:published-blank-deliverable',?,' ','published',999)",
        (service_id,),
    )
    db.commit()

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


def test_archived_blank_deliverable_does_not_block_a_valid_published_replacement(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    service_id = db.execute(
        "SELECT service_id FROM scenario_services WHERE scenario_id=? ORDER BY service_id LIMIT 1",
        (current["scenario_id"],),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO service_deliverables (code,service_id,title,status,sort_order) "
        "VALUES ('test:archived-blank-deliverable',?,' ','archived',999)",
        (service_id,),
    )
    db.commit()

    publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "published"


def _replace_scenario_json_source(db, scenario_id, revision_id, source, raw):
    if source == "settings_json":
        db.execute("UPDATE content_blocks SET settings_json=? WHERE content_item_id=?", (raw, revision_id))
    elif source == "risk_codes_json":
        db.execute("UPDATE scenarios SET risk_codes_json=? WHERE id=?", (raw, scenario_id))
    else:
        db.execute(
            f"UPDATE services SET {source}=? WHERE id=("
            "SELECT service_id FROM scenario_services WHERE scenario_id=? ORDER BY service_id LIMIT 1)",
            (raw, scenario_id),
        )
    db.commit()


@pytest.mark.parametrize(("source", "raw"), (
    ("settings_json", sqlite3.Binary(b"{}")),
    ("risk_codes_json", sqlite3.Binary(b'["process_variance"]')),
    ("risk_codes_json", sqlite3.Binary(b"\xff")),
    ("risk_codes_json", "[" * 1200 + '"process_variance"' + "]" * 1200),
    ("risk_codes_json", "[" + "9" * 20_000 + "]"),
    ("implementation_steps_json", sqlite3.Binary(b'["step"]')),
    ("prerequisites_json", sqlite3.Binary(b'["prerequisite"]')),
    ("acceptance_json", sqlite3.Binary(b'["acceptance"]')),
))
def test_formal_publish_rejects_non_text_json_without_archiving_current_scenario(
    db, source, raw
):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    _replace_scenario_json_source(db, current["scenario_id"], revision_id, source, raw)

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "content_json_invalid"
    _assert_unpublished_revision(db, current["id"], revision_id, lock_version=lock_version)


@pytest.mark.parametrize("source", ("steps", "acceptance", "budget", "core_name", "narrative", "malformed_json"))
def test_public_scenario_fails_closed_for_incomplete_or_malformed_required_data(client, db, source):
    scenario = db.execute("SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'").fetchone()
    if source == "steps":
        db.execute("UPDATE services SET implementation_steps_json='[null]' WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario["id"],))
    elif source == "acceptance":
        db.execute("UPDATE services SET acceptance_json='[\"\"]' WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario["id"],))
    elif source == "budget":
        db.execute("UPDATE services SET min_budget=0 WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario["id"],))
    elif source == "core_name":
        db.execute("UPDATE departments SET name=' ' WHERE id=(SELECT department_id FROM scenario_departments WHERE scenario_id=? LIMIT 1)", (scenario["id"],))
    elif source == "narrative":
        db.execute("UPDATE content_blocks SET body_html='<p> </p>' WHERE content_item_id=(SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id WHERE g.scenario_id=? LIMIT 1)", (scenario["id"],))
    else:
        db.execute("UPDATE services SET implementation_steps_json='{' WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)", (scenario["id"],))
    db.commit()
    publish_catalog(db)

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404


def test_all_public_complete_seeded_scenario_drafts_pass_the_formal_publish_gate(db):
    rows = db.execute("SELECT id,lock_version FROM content_items WHERE entry_type='scenario' AND status='draft' ORDER BY id").fetchall()

    results = []
    rejected = []
    for row in rows:
        try:
            results.append(publish_content(row["id"], row["lock_version"], actor="test-admin", now=NOW_DATETIME))
        except ContentValidationError:
            rejected.append(row["id"])

    assert len(results) == 12
    assert len(rejected) == 1
    rejected_code = db.execute(
        "SELECT s.code FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN scenarios s ON s.id=g.scenario_id WHERE ci.id=?", (rejected[0],)
    ).fetchone()[0]
    assert rejected_code == "data_process_foundation"
    assert db.execute("SELECT COUNT(*) FROM content_items WHERE entry_type='scenario' AND status='published'").fetchone()[0] == 12


@pytest.mark.parametrize("target", ("industry", "department", "pain"))
def test_archived_related_core_rows_are_omitted_from_public_cards_and_details(published_catalog, db, target):
    scenario = db.execute("SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'").fetchone()
    table = {"industry": "industries", "department": "departments", "pain": "pain_points"}[target]
    if target == "industry":
        row = db.execute(
            "SELECT i.id FROM industries i JOIN industry_branches ib ON ib.industry_id=i.id "
            "JOIN scenario_branches sb ON sb.industry_branch_id=ib.id WHERE sb.scenario_id=? LIMIT 1", (scenario["id"],)
        ).fetchone()
    else:
        link_table = "scenario_departments" if target == "department" else "scenario_pains"
        column = "department_id" if target == "department" else "pain_point_id"
        row = db.execute(f"SELECT {column} AS id FROM {link_table} WHERE scenario_id=? LIMIT 1", (scenario["id"],)).fetchone()
    marker = f"REVIEW-ARCHIVED-{target.upper()}"
    db.execute(f"UPDATE {table} SET name=?,status='archived' WHERE id=?", (marker, row["id"]))
    db.commit()

    card = page(published_catalog.get("/scenarios"))
    detail = published_catalog.get("/scenarios/mfg-knowledge-assistant")
    assert marker not in card.get_text()
    if target == "pain":
        assert detail.status_code == 200
        assert marker not in page(detail).get_text()
    else:
        remaining = db.execute(
            "SELECT COUNT(*) FROM scenario_branches sb JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
            "JOIN industries i ON i.id=ib.industry_id WHERE sb.scenario_id=? "
            "AND ib.status='published' AND i.status='published' AND trim(i.name)<>''"
            if target == "industry" else
            "SELECT COUNT(*) FROM scenario_departments sd JOIN departments d ON d.id=sd.department_id "
            "WHERE sd.scenario_id=? AND d.status='published' AND trim(d.name)<>''",
            (scenario["id"],),
        ).fetchone()[0]
        if remaining:
            assert detail.status_code == 200
            assert marker not in page(detail).get_text()
        else:
            assert detail.status_code == 404
            assert "mfg_knowledge_assistant" not in {
                node["data-scenario-code"] for node in card.select("[data-scenario-code]")
            }
            return
    cards = catalog.public_scenarios(catalog.ScenarioFilters(), catalog.PageRequest(1, 20), NOW_DATETIME)
    matched = next(item for item in cards.items if item.code == "mfg_knowledge_assistant")
    if target == "industry":
        assert marker not in matched.industries
    elif target == "department":
        assert marker not in matched.departments
    else:
        assert marker not in page(detail).get_text()


def test_archived_industry_branch_cannot_match_public_industry_filter(published_catalog, db):
    db.execute(
        "UPDATE industry_branches SET status='archived' WHERE id IN ("
        "SELECT ib.id FROM scenario_branches sb JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
        "JOIN scenarios s ON s.id=sb.scenario_id WHERE s.code='mfg_knowledge_assistant')"
    )
    db.commit()

    document = page(published_catalog.get("/scenarios?industry=manufacturing"))
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in document.select("[data-scenario-code]")
    }


@pytest.mark.parametrize("kind,table", (("industry", "industries"), ("department", "departments")))
def test_archived_core_codes_are_rejected_by_public_filter_parser(db, kind, table):
    row = db.execute(f"SELECT code FROM {table} WHERE status='published' ORDER BY id LIMIT 1").fetchone()
    db.execute(f"UPDATE {table} SET status='archived' WHERE code=?", (row["code"],))
    db.commit()

    filters = catalog.parse_public_scenario_filters({kind: row["code"]})

    assert getattr(filters, kind) == ""


@pytest.mark.parametrize("path", ("/industries", "/scenarios"))
def test_public_catalog_list_has_trusted_canonical_and_description(published_catalog, path):
    document = page(published_catalog.get(path, headers={"Host": "untrusted.example"}))
    assert document.select_one('link[rel="canonical"]')["href"] == f"https://test.example{path}"
    assert document.select_one('meta[name="description"]')["content"]


def test_scenario_without_published_pains_cannot_replace_current_revision(db):
    current, revision_id, lock_version = _saved_scenario_revision(db)
    db.execute("DELETE FROM scenario_pains WHERE scenario_id=?", (current["scenario_id"],))
    db.commit()

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, lock_version, actor="test-admin", now=NOW_DATETIME)

    assert error.value.code == "scenario_public_incomplete"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "published"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (revision_id,)).fetchone()[0] == "draft"
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'",
        (revision_id,),
    ).fetchone()[0] == 0


def test_scenario_without_published_pains_is_private_404(client, db):
    scenario_id = db.execute(
        "SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'"
    ).fetchone()[0]
    publish_catalog(db)
    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 200
    db.execute("DELETE FROM scenario_pains WHERE scenario_id=?", (scenario_id,))
    db.commit()

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404


@pytest.mark.parametrize(("column", "raw_json"), (
    ("implementation_steps_json", "true"),
    ("implementation_steps_json", "1"),
    ("implementation_steps_json", '"步骤"'),
    ("implementation_steps_json", '{"步骤":"一"}'),
    ("prerequisites_json", "true"),
    ("prerequisites_json", "1"),
    ("prerequisites_json", '"前置条件"'),
    ("prerequisites_json", '{"前置":"条件"}'),
    ("acceptance_json", "true"),
    ("acceptance_json", "1"),
    ("acceptance_json", '"验收"'),
    ("acceptance_json", '{"验收":"条件"}'),
    ("risk_codes_json", "true"),
    ("risk_codes_json", "1"),
    ("risk_codes_json", '"process_variance"'),
    ("risk_codes_json", '{"process_variance":"风险"}'),
))
def test_wrong_json_containers_are_private_404_not_iterated_as_values(client, db, column, raw_json):
    scenario = db.execute(
        "SELECT id FROM scenarios WHERE code='mfg_knowledge_assistant'"
    ).fetchone()
    if column == "risk_codes_json":
        db.execute("UPDATE scenarios SET risk_codes_json=? WHERE id=?", (raw_json, scenario["id"]))
    else:
        db.execute(
            f"UPDATE services SET {column}=? WHERE id=(SELECT service_id FROM scenario_services WHERE scenario_id=? LIMIT 1)",
            (raw_json, scenario["id"]),
        )
    db.commit()
    publish_catalog(db)
    client.application.config["PROPAGATE_EXCEPTIONS"] = False

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404


@pytest.mark.parametrize(("source", "raw"), (
    ("settings_json", sqlite3.Binary(b"{}")),
    ("risk_codes_json", sqlite3.Binary(b'["process_variance"]')),
    ("risk_codes_json", sqlite3.Binary(b"\xff")),
    ("risk_codes_json", "[" * 1200 + '"process_variance"' + "]" * 1200),
    ("risk_codes_json", "[" + "9" * 20_000 + "]"),
    ("implementation_steps_json", sqlite3.Binary(b'["step"]')),
    ("prerequisites_json", sqlite3.Binary(b'["prerequisite"]')),
    ("acceptance_json", sqlite3.Binary(b'["acceptance"]')),
))
def test_public_catalog_fails_closed_for_non_text_or_unbounded_json(
    client, db, source, raw
):
    scenario = db.execute(
        "SELECT s.id,ci.id AS content_item_id FROM scenarios s JOIN content_groups g "
        "ON g.scenario_id=s.id JOIN content_items ci ON ci.content_group_id=g.id "
        "WHERE s.code='mfg_knowledge_assistant' AND ci.status='draft'"
    ).fetchone()
    _replace_scenario_json_source(db, scenario["id"], scenario["content_item_id"], source, raw)
    publish_catalog(db)
    client.application.config["PROPAGATE_EXCEPTIONS"] = False

    detail = client.get("/scenarios/mfg-knowledge-assistant")
    listing = client.get("/scenarios")

    assert detail.status_code == 404
    assert listing.status_code == 200
    assert "mfg_knowledge_assistant" not in {
        card["data-scenario-code"] for card in page(listing).select("[data-scenario-code]")
    }


@pytest.mark.parametrize(("missing", "expected_total"), (("inputs", 11), ("services", 9)))
def test_public_scenario_list_and_filtered_list_omit_detail_incomplete_cards(client, db, missing, expected_total):
    if missing == "inputs":
        row = db.execute(
            "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
            "JOIN scenarios s ON s.id=g.scenario_id WHERE s.code='mfg_knowledge_assistant' "
            "AND ci.status='draft'"
        ).fetchone()
        db.execute("DELETE FROM scenario_public_inputs WHERE content_item_id=?", (row["id"],))
    else:
        db.execute(
            "UPDATE services SET status='archived' WHERE id IN ("
            "SELECT ss.service_id FROM scenario_services ss JOIN scenarios s ON s.id=ss.scenario_id "
            "WHERE s.code='mfg_knowledge_assistant')"
        )
    publish_catalog(db)

    assert client.get("/scenarios/mfg-knowledge-assistant").status_code == 404
    for path in ("/scenarios", "/scenarios?industry=manufacturing"):
        document = page(client.get(path))
        assert "mfg_knowledge_assistant" not in {
            card["data-scenario-code"] for card in document.select("[data-scenario-code]")
        }
    projection = catalog.public_scenarios(catalog.ScenarioFilters(), catalog.PageRequest(1, 20), NOW_DATETIME)
    assert projection.total == expected_total
    assert "mfg_knowledge_assistant" not in {card.code for card in projection.items}
    assert "retail_ai_service" in {card.code for card in projection.items}


@pytest.mark.parametrize("missing", ("overview", "pains", "departments", "company_sizes", "scenarios", "services"))
def test_industry_list_and_detail_require_real_published_sections(client, db, missing):
    industry = db.execute("SELECT id FROM industries WHERE code='manufacturing'").fetchone()
    if missing == "overview":
        db.execute(
            "UPDATE content_blocks SET body_html='<p> </p>' WHERE content_item_id=("
            "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
            "WHERE g.industry_id=? AND ci.status='draft')",
            (industry["id"],),
        )
    elif missing == "pains":
        db.execute("UPDATE pain_points SET status='archived' WHERE industry_id=?", (industry["id"],))
    elif missing == "departments":
        db.execute("UPDATE departments SET status='archived' WHERE industry_id=?", (industry["id"],))
    elif missing == "company_sizes":
        db.execute("UPDATE company_sizes SET status='archived'")
    elif missing == "scenarios":
        db.execute(
            "DELETE FROM scenario_public_inputs WHERE content_item_id IN ("
            "SELECT ci.id FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
            "JOIN scenario_branches sb ON sb.scenario_id=g.scenario_id "
            "JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
            "WHERE ci.status='draft' AND ib.industry_id=?)",
            (industry["id"],),
        )
    else:
        db.execute(
            "UPDATE services SET status='archived' WHERE id IN ("
            "SELECT DISTINCT ss.service_id FROM scenario_services ss JOIN scenario_branches sb ON sb.scenario_id=ss.scenario_id "
            "JOIN industry_branches ib ON ib.id=sb.industry_branch_id WHERE ib.industry_id=?)",
            (industry["id"],),
        )
    publish_catalog(db)

    document = page(client.get("/industries"))
    assert "manufacturing" not in {card["data-industry-code"] for card in document.select("[data-industry-code]")}
    assert client.get("/industries/manufacturing").status_code == 404
