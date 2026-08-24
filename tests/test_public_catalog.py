"""Public, read-only catalog routes use only published catalog aggregates."""

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import sqlite3

import pytest
from bs4 import BeautifulSoup

import app as app_module
import catalog_content_repository as catalog
from content_clock import SHANGHAI
from content_contracts import ContentBlock, ContentDraft
from content_validation import ContentValidationError
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
    assert len(scenarios.select("[data-scenario-code]")) == 13
    for document in (industries, scenarios):
        assert document.select_one('a[href="/assessment"]') is not None
        assert document.select_one('body[data-analytics-page]') is not None


def test_scenario_filters_are_intersection_not_union(published_catalog):
    response = published_catalog.get(
        "/scenarios?industry=manufacturing&department=production&maturity=explore"
    )
    document = page(response)
    codes = {card["data-scenario-code"] for card in document.select("[data-scenario-code]")}

    assert codes == {"mfg_knowledge_assistant", "data_process_foundation"}


@pytest.mark.parametrize("query", (
    "?industry=invalid&department=invalid&maturity=starting&page=-1&per_page=999",
    "?industry=manufacturing&maturity=starting&page=zero&per_page=20.5",
))
def test_invalid_get_filters_fall_back_to_safe_defaults(published_catalog, query):
    document = page(published_catalog.get(f"/scenarios{query}"))
    expected_count = 13 if "industry=invalid" in query else 4
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


def test_every_published_detail_has_its_required_sections(published_catalog, db):
    expected = (("industry", "/industries", INDUSTRY_REQUIRED_SECTIONS),
                ("scenario", "/scenarios", SCENARIO_REQUIRED_SECTIONS))
    for entry_type, prefix, sections in expected:
        slugs = [row[0] for row in db.execute(
            "SELECT slug FROM content_items WHERE entry_type=? AND status='published' ORDER BY id",
            (entry_type,),
        )]
        for slug in slugs:
            document = page(published_catalog.get(f"{prefix}/{slug}"))
            assert sections <= {node["data-content-section"] for node in document.select("[data-content-section]")}


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


def test_all_seeded_scenario_drafts_pass_the_formal_publish_gate(db):
    rows = db.execute("SELECT id,lock_version FROM content_items WHERE entry_type='scenario' AND status='draft' ORDER BY id").fetchall()

    results = [publish_content(row["id"], row["lock_version"], actor="test-admin", now=NOW_DATETIME) for row in rows]

    assert len(results) == 13
    assert db.execute("SELECT COUNT(*) FROM content_items WHERE entry_type='scenario' AND status='published'").fetchone()[0] == 13


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
