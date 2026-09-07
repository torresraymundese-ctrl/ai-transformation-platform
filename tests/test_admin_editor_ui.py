"""Rendered accessibility and preservation contracts for admin editors."""

from bs4 import BeautifulSoup

from content_clock import shanghai_now
from rule_release_repository import copy_active_release


CSRF = "test-csrf-token"


def _page(response, expected_status=200):
    assert response.status_code == expected_status
    return BeautifulSoup(response.data, "html.parser")


def _resource_form(**overrides):
    form = {
        "csrf_token": CSRF,
        "action": "save",
        "slug": "admin-ui-resource",
        "title": "资源编辑器验证",
        "summary": "用于验证管理端编辑器的真实渲染结构。",
        "seo_title": "资源编辑器验证",
        "seo_description": "验证资源编辑器的分区、标签和发布操作。",
        "share_image_media_id": "",
        "resource_type": "guide",
        "is_original": "1",
        "source_name": "",
        "source_url": "",
        "original_published_at": "2026-09-07T09:00",
        "copyright_notice": "本站原创。",
        "attachment_media_id": "",
        "review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "正文",
        "blocks-0-body": "<p>经审核正文。</p>",
        "blocks-0-media_id": "",
    }
    form.update(overrides)
    return form


def _announcement_form(**overrides):
    form = {
        "csrf_token": CSRF,
        "action": "save",
        "slug": "admin-ui-announcement",
        "title": "公告编辑器验证",
        "summary": "用于验证公告编辑器的真实渲染结构。",
        "seo_title": "公告编辑器验证",
        "seo_description": "验证公告编辑器的分区、标签和发布操作。",
        "share_image_media_id": "",
        "valid_from": "2026-09-07T09:00",
        "valid_until": "2026-09-08T09:00",
        "cta_url": "/contact",
        "review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "正文",
        "blocks-0-body": "<p>经审核正文。</p>",
        "blocks-0-media_id": "",
    }
    form.update(overrides)
    return form


def _case_form(**overrides):
    form = {
        "csrf_token": CSRF,
        "action": "save",
        "slug": "admin-ui-case",
        "title": "案例编辑器验证",
        "summary": "经人工审核的实施过程与量化结果。",
        "seo_title": "案例编辑器验证",
        "seo_description": "验证案例编辑器的分区、标签和发布操作。",
        "share_image_media_id": "",
        "verification_code": "authorized_anonymous",
        "is_verified": "1",
        "basis_type": "internal_delivery_record",
        "private_basis_reference": "internal-admin-ui-case",
        "source_url": "",
        "review_confirmed": "1",
        "privacy_review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "实施过程",
        "blocks-0-body": "<p>公开实施过程。</p>",
        "blocks-0-media_id": "",
        "metrics-0-name": "处理时间",
        "metrics-0-before_value": "8",
        "metrics-0-after_value": "2",
        "metrics-0-unit": "小时",
        "metrics-0-statistical_period": "连续 30 天",
        "metrics-0-evidence_explanation": "依据授权交付记录复核。",
    }
    form.update(overrides)
    return form


def _created_location(client, path, data):
    response = client.post(path, data=data)
    assert response.status_code == 302
    return response.headers["Location"]


def _assert_named_controls(form):
    """Every visible form control must keep an explicit associated label."""
    for control in form.select("input:not([type=hidden]), select, textarea"):
        if control.find_parent("label") is not None:
            continue
        control_id = control.get("id")
        assert control_id, f"unlabelled control: {control}"
        assert form.select_one(f'label[for="{control_id}"]') is not None


def _assert_editor_structure(page, required_sections):
    assert len(page.select("main#admin-main")) == 1
    assert len(page.select("h1")) == 1
    assert len(page.select('script[src="/static/js/admin_ui.js"][defer]')) == 1
    ids = [element["id"] for element in page.select("[id]")]
    assert len(ids) == len(set(ids))
    editor = page.select_one("form[data-admin-editor]")
    assert editor is not None
    assert editor.get("method", "").lower() == "post"
    assert editor.select_one('input[type="hidden"][name="csrf_token"]') is not None
    for section_id in required_sections:
        section = editor.select_one(
            f'section.admin-editor-section#{section_id}[aria-labelledby]'
        )
        assert section is not None
        labelled_by = section["aria-labelledby"]
        assert section.select_one(f'h2#{labelled_by}') is not None
    assert any(
        "admin-actions" in child.get("class", ())
        for child in editor.find_all(recursive=False)
        if getattr(child, "attrs", None) is not None
    )
    _assert_named_controls(editor)


def test_content_editors_render_new_and_edit_forms_without_losing_post_contracts(
    admin_client, db
):
    resource_edit = _created_location(
        admin_client, "/admin/resources/new", _resource_form()
    )
    announcement_edit = _created_location(
        admin_client, "/admin/announcements/new", _announcement_form()
    )
    case_edit = _created_location(admin_client, "/admin/cases/new", _case_form())
    catalog = db.execute(
        "SELECT g.scenario_id FROM content_groups g "
        "WHERE g.entry_type='scenario' ORDER BY g.scenario_id LIMIT 1"
    ).fetchone()
    assert catalog is not None

    expected = {
        "/admin/resources/new": {"editor-basic", "editor-content", "editor-media", "editor-seo", "editor-publishing"},
        resource_edit: {"editor-basic", "editor-content", "editor-media", "editor-seo", "editor-publishing"},
        "/admin/announcements/new": {"editor-basic", "editor-content", "editor-media", "editor-seo", "editor-publishing"},
        announcement_edit: {"editor-basic", "editor-content", "editor-media", "editor-seo", "editor-publishing"},
        "/admin/cases/new": {"editor-basic", "editor-content", "editor-media", "editor-seo", "editor-publishing"},
        case_edit: {"editor-basic", "editor-content", "editor-media", "editor-seo", "editor-publishing"},
        f"/admin/catalog/scenario/{catalog['scenario_id']}": {"editor-basic", "editor-content", "editor-media", "editor-seo", "editor-publishing"},
    }

    for path, sections in expected.items():
        page = _page(admin_client.get(path))
        _assert_editor_structure(page, sections)
        editor = page.select_one("form[data-admin-editor]")
        assert editor.has_attr("data-content-editor")
        assert {
            button["value"]
            for button in editor.select('button[name="action"][value]')
        } == {"save", "review", "publish"}
        assert editor.select_one(".admin-actions") is not None
        if path.endswith("/new"):
            assert editor.select_one('input[name="lock_version"]') is None
        else:
            assert editor.select_one('input[name="lock_version"][type="hidden"]')


def test_legal_and_rule_editors_preserve_lock_fields_actions_and_section_anchors(
    admin_client,
):
    legal_edit = _created_location(
        admin_client,
        "/admin/legal/new",
        {
            "csrf_token": CSRF,
            "document_type": "privacy",
            "version_code": "admin-ui-v1",
            "title": "隐私政策",
            "body_summary": "法律文档编辑器测试。",
            "body_html": "<p>法律文档正文。</p>",
            "effective_at": "2026-09-07T09:00:00",
        },
    )
    release_id = copy_active_release(
        "v2.1-admin-ui", "管理端编辑器", "test-admin", shanghai_now()
    )

    legal_new = _page(admin_client.get("/admin/legal/new"))
    _assert_editor_structure(
        legal_new, {"editor-basic", "editor-content", "editor-publishing"}
    )
    legal_page = _page(admin_client.get(legal_edit))
    _assert_editor_structure(
        legal_page, {"editor-basic", "editor-content", "editor-publishing"}
    )
    assert legal_page.select_one(
        'form[data-admin-editor] input[name="expected_lock_version"][type="hidden"]'
    )
    assert {
        button["value"]
        for button in legal_page.select('button[name="action"][value]')
    } == {"save", "review", "publish"}

    rule_page = _page(admin_client.get(f"/admin/rules/{release_id}"))
    _assert_editor_structure(
        rule_page,
        {
            "editor-basic",
            "editor-taxonomy",
            "editor-public-content",
            "editor-scoring",
            "editor-benchmarks",
            "editor-roi",
            "editor-scenarios",
            "editor-services",
        },
    )
    rule_form = rule_page.select_one('form[data-admin-editor][data-rule-edit]')
    assert rule_form.select_one(
        'input[name="expected_lock_version"][type="hidden"]'
    )
    assert rule_form.select_one('.admin-actions button[type="submit"]') is not None

    generic_error = _page(
        admin_client.post(
            f"/admin/rules/{release_id}",
            data={"csrf_token": CSRF, "unknown": "not-accepted"},
        ),
        400,
    )
    assert generic_error.select_one(
        '.admin-error-summary[data-admin-error-summary][role="alert"][tabindex="-1"]'
    ) is not None


def test_rendered_server_error_summary_is_alert_focus_target(admin_client, db):
    item = db.execute(
        "SELECT ci.*, g.scenario_id FROM content_items ci "
        "JOIN content_groups g ON g.id=ci.content_group_id "
        "WHERE g.entry_type='scenario' ORDER BY ci.id LIMIT 1"
    ).fetchone()
    assert item is not None
    path = f"/admin/catalog/scenario/{item['scenario_id']}"
    valid = {
        "csrf_token": CSRF,
        "content_id": str(item["id"]),
        "lock_version": str(item["lock_version"]),
        "action": "save",
        "title": "编辑器冲突验证",
        "summary": "保留真实的内容修订和锁冲突语义。",
        "seo_title": "编辑器冲突验证",
        "seo_description": "验证锁冲突后服务端错误摘要可以获得焦点。",
        "share_image_media_id": "",
        "maturity_codes": ["explore"],
        "blocks-0-type": "rich_text",
        "blocks-0-title": "适用说明",
        "blocks-0-body": "<p>适用说明。</p>",
        "blocks-0-media_id": "",
    }
    assert admin_client.post(path, data=valid).status_code == 302
    conflict = admin_client.post(path, data=valid)
    page = _page(conflict, 409)

    summary = page.select_one(
        '.admin-error-summary[data-admin-error-summary][role="alert"][tabindex="-1"]'
    )
    assert summary is not None
    assert "内容已被其他操作更新" in summary.get_text()


def test_active_admin_lists_have_one_page_heading_and_unique_filter_labels(admin_client):
    paths = (
        "/admin/assets",
        "/admin/assessments",
        "/admin/catalog/industry",
        "/admin/catalog/scenario",
        "/admin/catalog/service",
        "/admin/resources",
        "/admin/cases",
        "/admin/announcements",
        "/admin/ingestion",
        "/admin/data-requests",
        "/admin/assets/codes",
        "/admin/assets/departments",
        "/admin/assets/unit-a",
        "/admin/assets/unit-b",
        "/admin/assets/labels?unit=A",
    )
    for path in paths:
        page = _page(admin_client.get(path))
        assert len(page.select("main#admin-main > h1, main#admin-main .admin-heading h1")) == 1
        ids = [element["id"] for element in page.select("[id]")]
        assert len(ids) == len(set(ids)), path
        for form in page.select("form[data-operations-filters]"):
            _assert_named_controls(form)


def test_asset_label_screen_controls_and_populated_sheet_are_locally_contained(
    admin_client, db
):
    assert admin_client.post(
        "/admin/assets/code/new",
        data={
            "csrf_token": CSRF,
            "code": "ADMIN_UI_LABEL",
            "name": "管理端标签测试",
            "category": "table",
            "sort_order": "0",
        },
    ).status_code == 302
    code_id = db.execute(
        "SELECT id FROM asset_codes WHERE code='ADMIN_UI_LABEL'"
    ).fetchone()[0]
    assert admin_client.post(
        "/admin/assets/unit-b/new",
        data={
            "csrf_token": CSRF,
            "asset_code_id": str(code_id),
            "quantity": "1",
            "remark": "",
        },
    ).status_code == 302

    page = _page(admin_client.get("/admin/assets/labels?unit=B"))
    toolbar = page.select_one(".label-toolbar")

    assert toolbar is not None
    for control in toolbar.select("a, button"):
        assert "btn" in control.get("class", ()), control
    scroll_region = page.select_one(
        '[data-label-sheet-scroll] > .label-sheet > .label-card'
    )
    assert scroll_region is not None

    empty_page = _page(admin_client.get("/admin/assets/labels?unit=A"))
    empty_state_link = empty_page.select_one('.card a[href="/admin/assets/unit-a"]')
    assert empty_state_link is not None
    assert "admin-control-link" in empty_state_link.get("class", ())


def test_asset_auxiliary_new_and_edit_forms_have_page_headings_and_labels(
    admin_client, db
):
    assert admin_client.post(
        "/admin/assets/code/new",
        data={
            "csrf_token": CSRF,
            "code": "ADMIN_UI_FORM",
            "name": "管理端表单测试",
            "category": "chair",
            "sort_order": "0",
        },
    ).status_code == 302
    code_id = db.execute(
        "SELECT id FROM asset_codes WHERE code='ADMIN_UI_FORM'"
    ).fetchone()[0]
    assert admin_client.post(
        "/admin/assets/departments/new",
        data={"csrf_token": CSRF, "name": "测试科室", "sort_order": "0"},
    ).status_code == 302
    department_id = db.execute(
        "SELECT id FROM asset_departments WHERE name='测试科室'"
    ).fetchone()[0]
    assert admin_client.post(
        "/admin/assets/unit-a/new",
        data={
            "csrf_token": CSRF,
            "department": "测试科室",
            "asset_code_id": str(code_id),
            "quantity": "1",
            "remark": "",
        },
    ).status_code == 302
    unit_a_id = db.execute(
        "SELECT id FROM unit_a_assets WHERE asset_code_id=?", (code_id,)
    ).fetchone()[0]
    assert admin_client.post(
        "/admin/assets/unit-b/new",
        data={
            "csrf_token": CSRF,
            "asset_code_id": str(code_id),
            "quantity": "1",
            "remark": "",
        },
    ).status_code == 302
    unit_b_id = db.execute(
        "SELECT id FROM unit_b_assets WHERE asset_code_id=?", (code_id,)
    ).fetchone()[0]

    paths = (
        "/admin/assets/code/new",
        f"/admin/assets/code/{code_id}",
        "/admin/assets/departments/new",
        f"/admin/assets/departments/{department_id}",
        "/admin/assets/unit-a/new",
        f"/admin/assets/unit-a/{unit_a_id}",
        "/admin/assets/unit-b/new",
        f"/admin/assets/unit-b/{unit_b_id}",
    )
    for path in paths:
        page = _page(admin_client.get(path))
        assert len(page.select("main#admin-main h1")) == 1, path
        form = page.select_one('form[method="POST"]')
        assert form is not None
        _assert_named_controls(form)
