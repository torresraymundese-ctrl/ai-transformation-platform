"""Operator-facing display regressions; fixtures never use the preview/user DB."""

import json

import pytest
from bs4 import BeautifulSoup

import content_repository
from tests.test_lead_export import _create_completed_lead, _historical_v20_snapshot
from tests.test_admin_ui import _admin_css, _css_declarations


def _main(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return BeautifulSoup(response.data, "html.parser").select_one("main")


def test_assessment_list_uses_linked_contact_and_saved_recommendation(admin_client, db):
    """Reading legacy columns or today's catalog loses the V2/historical display."""
    lead_id, assessment_id = _create_completed_lead(suffix="display")
    raw = db.execute("SELECT report_snapshot_json FROM assessments WHERE id=?", (assessment_id,)).fetchone()[0]
    snapshot = json.loads(raw)
    scenario = snapshot["recommendations"][0]["scenario"]["code"]
    snapshot["display_labels"]["scenarios"][scenario] = "评估当时的场景名称"
    snapshot["recommendations"][0]["package"]["public_name"] = "评估当时的服务名称"
    db.execute("UPDATE assessments SET report_snapshot_json=?,company_name='过时企业',contact_email='stale@example.invalid',result='过时方案' WHERE id=?", (json.dumps(snapshot), assessment_id))
    db.commit()
    before = tuple(db.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone())

    response = admin_client.get("/admin/assessments")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    page = BeautifulSoup(response.data, "html.parser")
    text = page.select_one("main").get_text(" ", strip=True)
    assert "display企业" in text
    assert "display@example.invalid" in text
    assert "评估当时的场景名称" in text
    assert "评估当时的服务名称" in text
    assert "过时企业" not in text and "过时方案" not in text
    assert "stale@example.invalid" not in text
    assert page.select_one(f'a[href="/admin/lead/{lead_id}"]') is not None
    assert not page.select('a[href*="/assessment/report/"]')
    assert before == tuple(db.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone())


def test_assessment_list_never_falls_back_to_pii_for_anonymized_lead(admin_client, db):
    """A legacy fallback must not resurrect PII after linked-lead anonymization."""
    lead_id, assessment_id = _create_completed_lead(suffix="erased")
    db.execute("UPDATE leads SET anonymized_at='2026-09-08 12:00:00' WHERE id=?", (lead_id,))
    db.execute("UPDATE assessments SET company_name='残留旧企业',contact_email='stale@example.invalid' WHERE id=?", (assessment_id,))
    db.commit()
    page = _main(admin_client, "/admin/assessments")
    text = page.get_text(" ", strip=True)
    assert "已匿名化" in text
    for private in ("erased企业", "erased@example.invalid", "残留旧企业", "stale@example.invalid"):
        assert private not in text
    assert page.select_one(f'a[href="/admin/lead/{lead_id}"]') is None


def test_assessment_list_orphaned_link_does_not_offer_broken_navigation(admin_client, db):
    _, assessment_id = _create_completed_lead(suffix="orphan")
    # Simulate an imported historical inconsistency in the disposable fixture.
    db.commit()
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("UPDATE assessments SET lead_id=999999,company_name='残留企业',contact_email='stale@example.invalid' WHERE id=?", (assessment_id,))
    db.commit()
    db.execute("PRAGMA foreign_keys=ON")

    page = _main(admin_client, "/admin/assessments")
    assert "线索已不存在" in page.get_text()
    assert "残留企业" not in page.get_text() and "stale@example.invalid" not in page.get_text()
    assert not page.select('a[href="/admin/lead/999999"]')


@pytest.mark.parametrize("raw", ["not-json", "{}", " " * (128 * 1024 + 1)], ids=["malformed", "empty", "oversized"])
def test_assessment_list_handles_invalid_snapshot_without_stale_result(admin_client, db, raw):
    """One unavailable V2 snapshot must not crash the list or reuse legacy results."""
    _, assessment_id = _create_completed_lead(suffix="invalid")
    db.execute("UPDATE assessments SET report_snapshot_json=?,result='不可使用的旧推荐' WHERE id=?", (raw, assessment_id))
    db.commit()
    text = _main(admin_client, "/admin/assessments").get_text(" ", strip=True)
    assert "invalid企业" in text
    assert "结果暂不可用" in text
    assert "不可使用的旧推荐" not in text


def test_assessment_list_keeps_legacy_rows_and_escapes_text(admin_client, db):
    """Unlinked pre-V2 records still render, without turning stored text into HTML."""
    db.execute("INSERT INTO assessments (company_name,contact_email,result) VALUES (?,?,?)", ("<script>legacy-company</script>", "legacy@example.invalid", "历史推荐"))
    db.commit()
    page = _main(admin_client, "/admin/assessments")
    assert "<script>legacy-company</script>" in page.get_text()
    assert "历史推荐" in page.get_text()
    assert page.select_one("script") is None


def test_assessment_list_supports_valid_v20_snapshot(admin_client, db):
    """Historical V2.0 snapshots have no display_labels but remain readable."""
    _, assessment_id = _create_completed_lead(suffix="historical")
    snapshot = _historical_v20_snapshot()
    db.execute("UPDATE assessments SET report_snapshot_json=? WHERE id=?", (json.dumps(snapshot), assessment_id))
    db.commit()
    text = _main(admin_client, "/admin/assessments").get_text(" ", strip=True)
    assert "historical企业" in text
    assert "生产经营数据洞察" in text
    assert "结果暂不可用" not in text


def test_assessment_list_localizes_code_only_saved_label(admin_client, db):
    """Older seeded labels may be codes; localize only that exact fallback."""
    from admin_display import LEGACY_SCENARIO_LABELS

    _, assessment_id = _create_completed_lead(suffix="code-label")
    raw = db.execute("SELECT report_snapshot_json FROM assessments WHERE id=?", (assessment_id,)).fetchone()[0]
    snapshot = json.loads(raw)
    code = snapshot["recommendations"][0]["scenario"]["code"]
    snapshot["display_labels"]["scenarios"][code] = code
    db.execute("UPDATE assessments SET report_snapshot_json=? WHERE id=?", (json.dumps(snapshot), assessment_id))
    db.commit()

    text = _main(admin_client, "/admin/assessments").get_text(" ", strip=True)
    assert LEGACY_SCENARIO_LABELS[code] in text
    assert code not in text


@pytest.mark.parametrize("path, selector, expected", [
    ("/admin/leads", 'select[name="status"] option[value="new"]', "新线索"),
    ("/admin/leads", 'select[name="branch"] option[value="manufacturing"]', "制造业"),
    ("/admin/appointments", 'select[name="status"] option[value="pending"]', "待确认"),
    ("/admin/catalog/industry", 'select[name="status"] option[value="published"]', "已发布"),
    ("/admin/catalog/scenario", 'select[name="status"] option[value="draft"]', "草稿"),
    ("/admin/catalog/service", 'select[name="status"] option[value="scheduled"]', "已排期"),
    ("/admin/resources", 'select[name="status"] option[value="archived"]', "已归档"),
    ("/admin/cases", 'select[name="status"] option[value="published"]', "已发布"),
    ("/admin/announcements", 'select[name="status"] option[value="draft"]', "草稿"),
    ("/admin/ingestion", 'select[name="state"] option[value="pending_review"]', "待审核"),
    ("/admin/legal", 'select[name="type"] option[value="privacy"]', "隐私政策"),
    ("/admin/rules", 'select[name="status"] option[value="published"]', "已发布"),
    ("/admin/data-requests", 'select[name="request_type"] option[value="access"]', "查阅与复制"),
    ("/admin/data-requests", 'select[name="status"] option[value="open"]', "未完成"),
    ("/admin/data-requests", 'select[name="channel"] option[value="email"]', "邮箱"),
    ("/admin/media", 'select[name="status"] option[value="ready"]', "可使用"),
])
def test_filter_labels_are_chinese_without_changing_submitted_values(admin_client, path, selector, expected):
    """Raw enums confuse operators; changing option values breaks server filters."""
    option = _main(admin_client, path).select_one(selector)
    assert option is not None
    assert option.get_text(strip=True) == expected


def test_populated_lead_cells_and_filter_selection_are_localized(admin_client, db):
    _create_completed_lead(suffix="visible")
    page = _main(admin_client, "/admin/leads?status=new&branch=manufacturing")
    cells = [cell.get_text(strip=True) for cell in page.select("tbody td")]
    assert "新线索" in cells and "制造业" in cells
    assert page.select_one('option[value="new"][selected]') is not None
    export = page.select_one('form[action="/admin/leads/export"]')
    assert export.select_one('input[name="status"]')["value"] == "new"
    assert export.select_one('input[name="csrf_token"]')["value"]


def test_catalog_is_title_first_without_losing_stable_identity(admin_client):
    page = _main(admin_client, "/admin/catalog/industry")
    assert page.select_one("h1").get_text(strip=True) == "行业文案"
    first_row = page.select_one("tr[data-catalog-row]")
    assert first_row.select_one("td").get_text(strip=True) in {"制造业", "零售电商", "知识型专业服务", "软件与创意服务"}
    assert first_row["data-catalog-row"] in first_row.get_text()


def test_assessment_list_limit_is_preserved(client, db):
    db.executemany("INSERT INTO assessments (company_name,created_at) VALUES (?,?)", [(f"企业{i}", f"2026-09-08 12:00:{i:02d}") for i in range(55)])
    db.commit()
    rows = content_repository.list_assessments()
    assert len(rows) == 50
    assert rows[0]["company_name"] == "企业54"


def test_data_tables_keep_native_layout_inside_keyboard_scroll_region(admin_client):
    """Block tables shrink columns; moving overflow must preserve keyboard access."""
    page = _main(admin_client, "/admin/catalog/industry")
    region = page.select_one('.admin-table-wrap[role="region"][tabindex="0"][aria-label]')
    assert region is not None and region.select_one('table.admin-data-table') is not None
    css = _admin_css(admin_client)
    assert _css_declarations(css, ".admin-main .admin-data-table").get("display") == "table"
    assert _css_declarations(css, ".admin-table-wrap")["overflow-x"] == "auto"


def test_dashboard_cards_align_actions_without_changing_queue_links(admin_client):
    """Natural heading height must not push same-row actions to different baselines."""
    css = _admin_css(admin_client)
    assert _css_declarations(css, "[data-operation-card]").get("display") == "flex"
    assert _css_declarations(css, "[data-operation-card] > .btn").get("margin-top") == "auto"


def test_unknown_admin_label_stays_visible_as_text_not_markup(client):
    from flask import render_template_string
    with client.application.app_context():
        html = render_template_string('{{ value | admin_label }}', value='<img src=x onerror=alert(1)>')
    assert "&lt;img" in html and "<img" not in html
