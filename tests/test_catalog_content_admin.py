import hashlib
from pathlib import Path

from bs4 import BeautifulSoup

from content_contracts import CaseMetric, ContentDraft
from publishing_service import create_content_draft, publish_content

CSRF = "test-csrf-token"


def _first(db, kind="scenario"):
    return db.execute(
        "SELECT ci.*,g.canonical_slug,g.scenario_id,g.industry_id,g.service_id "
        "FROM content_items ci JOIN content_groups g ON g.id=ci.content_group_id "
        "WHERE g.entry_type=? ORDER BY ci.id LIMIT 1",
        (kind,),
    ).fetchone()


def _valid_form(item, **changes):
    values = {
        "csrf_token": CSRF,
        "content_id": str(item["id"]),
        "lock_version": str(item["lock_version"]),
        "action": "save",
        "title": "场景文案更新",
        "summary": "用于说明适用范围、准备条件和实施边界的中性摘要。",
        "seo_title": "场景文案更新",
        "seo_description": "查看场景的适用范围、准备条件与实施边界。",
        "share_image_media_id": "",
        "maturity_codes": ["explore", "pilot"],
        "blocks-0-type": "rich_text",
        "blocks-0-title": "适用说明",
        "blocks-0-body": "<p>由团队结合现状确认适用范围。</p>",
        "blocks-0-media_id": "",
    }
    values.update(changes)
    return values


def _publish_case_target(db, slug, title):
    draft = ContentDraft(
        entry_type="case",
        slug=slug,
        title=title,
        summary="经授权并由内部交付记录验证的匿名案例说明。",
        seo_title=title,
        seo_description="查看经授权并已完成内部核验的匿名案例。",
        extension={
            "verification_code": f"verification-{slug}",
            "is_anonymized": 1,
            "basis_type": "private_authorization",
            "private_basis_reference": f"internal-{slug}",
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
                "处理周期",
                "8",
                "6",
                "小时",
                "连续 30 天",
                "由已授权内部交付记录中的处理时长对比得出。",
            ),
        ),
    )
    content_id = create_content_draft(draft, actor="test-admin")
    publish_content(content_id, 1, actor="test-admin")
    return db.execute(
        "SELECT content_group_id FROM content_items WHERE id=?",
        (content_id,),
    ).fetchone()[0]


def test_catalog_lists_all_core_rows_once_with_private_cache(admin_client):
    for kind, count in (("industry", 4), ("scenario", 13), ("service", 6)):
        response = admin_client.get(f"/admin/catalog/{kind}")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.data.count(b'data-catalog-row="') == count


def test_catalog_routes_require_authentication_and_csrf(client, admin_client, db):
    item = _first(db)
    with client.session_transaction() as session:
        session.clear()
    anonymous = client.get("/admin/catalog/scenario")
    with admin_client.session_transaction() as session:
        session["admin_username"] = "test-admin"
        session["csrf_token"] = CSRF
    rejected = admin_client.post(
        f"/admin/catalog/scenario/{item['scenario_id']}",
        data={key: value for key, value in _valid_form(item).items() if key != "csrf_token"},
    )
    assert anonymous.status_code == 302
    assert "/admin/login" in anonymous.headers["Location"]
    assert rejected.status_code == 403


def test_unknown_or_assessment_critical_fields_are_rejected_without_residue(admin_client, db):
    item = _first(db)
    route = f"/admin/catalog/scenario/{item['scenario_id']}"
    before_item = tuple(db.execute("SELECT title,lock_version FROM content_items WHERE id=?", (item["id"],)).fetchone())
    before_rule = tuple(
        db.execute(
            "SELECT minimum_data,min_weeks,max_weeks FROM scenarios WHERE id=?",
            (item["scenario_id"],),
        ).fetchone()
    )

    for field in ("minimum_data", "min_budget", "deliverables", "unexpected"):
        response = admin_client.post(route, data=_valid_form(item, **{field: "0"}))
        assert response.status_code == 400
        assert response.get_json() == {"error": "unknown_field", "field": field}

    assert tuple(db.execute("SELECT title,lock_version FROM content_items WHERE id=?", (item["id"],)).fetchone()) == before_item
    assert tuple(db.execute("SELECT minimum_data,min_weeks,max_weeks FROM scenarios WHERE id=?", (item["scenario_id"],)).fetchone()) == before_rule


def test_save_review_publish_copy_on_edit_and_archive_use_revision_state_machine(admin_client, db):
    item = _first(db)
    route = f"/admin/catalog/scenario/{item['scenario_id']}"

    saved = admin_client.post(route, data=_valid_form(item))
    assert saved.status_code == 302
    current = _first(db)
    assert (current["title"], current["lock_version"], current["status"]) == (
        "场景文案更新",
        2,
        "draft",
    )

    reviewed = admin_client.post(
        route,
        data=_valid_form(current, action="review"),
    )
    assert reviewed.status_code == 302
    current = _first(db)
    assert db.execute(
        "SELECT event_code FROM content_audit_events WHERE content_item_id=? ORDER BY id DESC LIMIT 1",
        (current["id"],),
    ).fetchone()[0] == "content_reviewed"

    published = admin_client.post(
        route,
        data=_valid_form(current, action="publish"),
    )
    assert published.status_code == 302
    published_item = db.execute("SELECT * FROM content_items WHERE id=?", (current["id"],)).fetchone()
    assert published_item["status"] == "published"

    edit = admin_client.get(route)
    assert edit.status_code == 200
    revisions = db.execute(
        "SELECT id,status FROM content_items WHERE content_group_id=? ORDER BY revision_number",
        (current["content_group_id"],),
    ).fetchall()
    assert [row["status"] for row in revisions] == ["published", "draft"]

    archived = admin_client.post(
        route,
        data={
            "csrf_token": CSRF,
            "action": "archive",
            "content_id": str(published_item["id"]),
            "lock_version": str(published_item["lock_version"]),
        },
    )
    assert archived.status_code == 302
    assert db.execute("SELECT status FROM content_items WHERE id=?", (published_item["id"],)).fetchone()[0] == "archived"


def test_optimistic_conflict_returns_409_and_preserves_submitted_values(admin_client, db):
    item = _first(db)
    route = f"/admin/catalog/scenario/{item['scenario_id']}"
    db.execute("UPDATE content_items SET lock_version=lock_version+1 WHERE id=?", (item["id"],))
    db.commit()

    response = admin_client.post(route, data=_valid_form(item, title="冲突时保留的标题"))

    assert response.status_code == 409
    assert "冲突时保留的标题".encode("utf-8") in response.data
    assert db.execute("SELECT title FROM content_items WHERE id=?", (item["id"],)).fetchone()[0] != "冲突时保留的标题"


def test_block_maturity_and_relation_inputs_use_exact_choice_schema(admin_client, db):
    item = _first(db)
    route = f"/admin/catalog/scenario/{item['scenario_id']}"
    invalid_maturity = admin_client.post(route, data=_valid_form(item, maturity_codes=["invented"]))
    invalid_block = admin_client.post(route, data=_valid_form(item, **{"blocks-0-type": "script"}))

    assert invalid_maturity.status_code == 400
    assert invalid_block.status_code == 400
    assert db.execute("SELECT lock_version FROM content_items WHERE id=?", (item["id"],)).fetchone()[0] == item["lock_version"]


def test_post_persists_the_selected_second_relation_target(admin_client, db):
    item = _first(db)
    first_group = _publish_case_target(db, "first-relation-case", "第一个关系案例")
    second_group = _publish_case_target(db, "second-relation-case", "第二个关系案例")

    response = admin_client.post(
        f"/admin/catalog/scenario/{item['scenario_id']}",
        data=_valid_form(
            item,
            **{
                "relations-0-type": "scenario_case",
                "relations-0-target_group_id": str(second_group),
            },
        ),
    )

    assert response.status_code == 302
    targets = db.execute(
        "SELECT case_content_group_id FROM scenario_cases "
        "WHERE scenario_content_item_id=? ORDER BY sort_order",
        (item["id"],),
    ).fetchall()
    assert [row[0] for row in targets] == [second_group]
    assert first_group != second_group


def test_existing_relation_type_is_rendered_as_an_immutable_field(admin_client, db):
    item = _first(db)
    target_group = _publish_case_target(db, "immutable-relation-case", "不可变关系案例")
    saved = admin_client.post(
        f"/admin/catalog/scenario/{item['scenario_id']}",
        data=_valid_form(
            item,
            **{
                "relations-0-type": "scenario_case",
                "relations-0-target_group_id": str(target_group),
            },
        ),
    )
    assert saved.status_code == 302

    rendered = admin_client.get(f"/admin/catalog/scenario/{item['scenario_id']}")

    assert rendered.status_code == 200
    assert b'type="hidden" name="relations-0-type"' in rendered.data
    assert b'<select name="relations-0-type"' not in rendered.data
    assert b'scenario_case' in rendered.data


def test_block_rejects_settings_for_another_type_and_non_contiguous_order(admin_client, db):
    item = _first(db)
    route = f"/admin/catalog/scenario/{item['scenario_id']}"
    wrong_settings = admin_client.post(
        route,
        data=_valid_form(item, **{"blocks-0-cta_url": "/assessment"}),
    )
    gap_form = _valid_form(item)
    for suffix in ("type", "title", "body", "media_id"):
        gap_form[f"blocks-2-{suffix}"] = gap_form.pop(f"blocks-0-{suffix}")
    gap = admin_client.post(route, data=gap_form)

    assert wrong_settings.status_code == 400
    assert gap.status_code == 400
    assert db.execute("SELECT lock_version FROM content_items WHERE id=?", (item["id"],)).fetchone()[0] == item["lock_version"]


def _pending_media(db):
    timestamp = "2026-08-24 09:00:00"
    media_id = db.execute(
        "INSERT INTO media_assets "
        "(storage_name,display_name,detected_mime,byte_size,sha256,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'pending',?,?)",
        (
            "task5-pending.png",
            "task5-pending.png",
            "image/png",
            10,
            hashlib.sha256(b"task5-pending").hexdigest(),
            timestamp,
            timestamp,
        ),
    ).lastrowid
    db.commit()
    return media_id


def _ready_media(db, name, mime):
    timestamp = "2026-08-24 09:00:00"
    media_id = db.execute(
        "INSERT INTO media_assets "
        "(storage_name,display_name,detected_mime,byte_size,sha256,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'pending',?,?)",
        (
            name,
            name,
            mime,
            10,
            hashlib.sha256(name.encode("utf-8")).hexdigest(),
            timestamp,
            timestamp,
        ),
    ).lastrowid
    db.execute(
        "UPDATE media_assets SET status='ready',scan_result_code='validated',"
        "scan_checked_at=?,ready_at=?,updated_at=? WHERE id=?",
        (timestamp, timestamp, timestamp, media_id),
    )
    db.commit()
    return media_id


def test_editor_share_choices_exclude_ready_pdf_but_block_choices_keep_it(admin_client, db):
    """Catch a share selector that exposes an asset its public image route cannot serve."""
    item = _first(db)
    pdf_id = _ready_media(db, "share-choice.pdf", "application/pdf")
    image_id = _ready_media(db, "share-choice.png", "image/png")

    response = admin_client.get(f"/admin/catalog/scenario/{item['scenario_id']}")
    document = BeautifulSoup(response.data, "html.parser")
    share_choices = {
        option.get("value")
        for option in document.select('select[name="share_image_media_id"] option')
    }
    block_choices = {
        option.get("value")
        for option in document.select('select[name="blocks-0-media_id"] option')
    }

    assert response.status_code == 200
    assert str(pdf_id) not in share_choices
    assert str(image_id) in share_choices
    assert str(pdf_id) in block_choices


def test_admin_publish_rejects_ready_pdf_share_image_without_mutation(admin_client, db):
    """Catch an admin publish that accepts a ready non-image sharing asset."""
    item = _first(db)
    pdf_id = _ready_media(db, "share-publish.pdf", "application/pdf")
    before = tuple(db.execute(
        "SELECT title,status,lock_version,share_image_media_id FROM content_items WHERE id=?",
        (item["id"],),
    ).fetchone())

    response = admin_client.post(
        f"/admin/catalog/scenario/{item['scenario_id']}",
        data=_valid_form(item, action="publish", share_image_media_id=str(pdf_id)),
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "share_image_mime_invalid"}
    assert tuple(db.execute(
        "SELECT title,status,lock_version,share_image_media_id FROM content_items WHERE id=?",
        (item["id"],),
    ).fetchone()) == before
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_published'", (item["id"],),
    ).fetchone()[0] == 0


def test_admin_publish_heading_without_title_renders_its_safe_body_without_none(admin_client, db):
    """Catch the literal None heading emitted for the legal optional heading title."""
    item = _first(db)
    response = admin_client.post(
        f"/admin/catalog/scenario/{item['scenario_id']}",
        data=_valid_form(
            item,
            action="publish",
            **{
                "blocks-0-type": "heading",
                "blocks-0-title": "",
                "blocks-0-body": "<p>HEADING-BODY-VISIBLE</p>",
                "blocks-0-heading_level": "2",
            },
        ),
    )

    assert response.status_code == 302
    public = admin_client.get(f"/scenarios/{item['slug']}")
    document = BeautifulSoup(public.data, "html.parser")
    assert public.status_code == 200
    assert b"HEADING-BODY-VISIBLE" in public.data
    assert b">None<" not in public.data
    assert document.select('[data-content-block="heading"]') == []


def test_save_rejects_media_outside_ready_choices_without_mutation(admin_client, db):
    item = _first(db)
    pending_id = _pending_media(db)
    response = admin_client.post(
        f"/admin/catalog/scenario/{item['scenario_id']}",
        data=_valid_form(item, share_image_media_id=str(pending_id)),
    )

    assert response.status_code == 400
    assert tuple(db.execute("SELECT title,lock_version FROM content_items WHERE id=?", (item["id"],)).fetchone()) == (
        item["title"],
        item["lock_version"],
    )


def test_publish_validation_failure_rolls_back_submitted_aggregate(admin_client, db):
    item = _first(db)
    pending_id = _pending_media(db)
    response = admin_client.post(
        f"/admin/catalog/scenario/{item['scenario_id']}",
        data=_valid_form(
            item,
            action="publish",
            title="不应留下的发布标题",
            share_image_media_id=str(pending_id),
        ),
    )

    assert response.status_code == 400
    after = db.execute(
        "SELECT title,status,lock_version,share_image_media_id FROM content_items WHERE id=?",
        (item["id"],),
    ).fetchone()
    assert tuple(after) == (item["title"], "draft", item["lock_version"], None)


def test_legacy_case_editor_is_a_migration_notice(admin_client):
    assert admin_client.get("/admin/case/new").status_code == 410
    assert admin_client.post("/admin/case/1", data={"csrf_token": CSRF}).status_code == 410


def test_admin_catalog_blueprint_contains_no_direct_sql():
    path = Path(__file__).resolve().parents[1] / "blueprints" / "admin" / "catalog.py"
    text = path.read_text(encoding="utf-8").lower()
    assert ".execute(" not in text
    assert not any(token in text for token in ("select ", "insert ", "update ", "delete "))
