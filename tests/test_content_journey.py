"""Task 12 end-to-end content journeys through HTTP/admin/CLI surfaces only."""

import ast
from datetime import datetime
import io
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfWriter
import requests
from werkzeug.datastructures import MultiDict

import manage
from source_url_checker import FetchResult


CSRF = "test-csrf-token"
SHANGHAI = ZoneInfo("Asia/Shanghai")
JOURNEY_NOW = datetime(2026, 8, 25, 10, 0, tzinfo=SHANGHAI)


SERVICE_REQUIRED_SECTIONS = {
    "industries",
    "departments",
    "maturity",
    "pains",
    "scope",
    "not-included",
    "deliverables",
    "implementation-steps",
    "prerequisites",
    "timeline",
    "budget",
    "acceptance",
    "support",
    "related-content",
    "pricing-disclaimer",
}


def _catalog_rows(admin_client, kind):
    response = admin_client.get(f"/admin/catalog/{kind}")
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    rows = []
    for row in page.select("[data-catalog-row]"):
        codes = row.select("code")
        edit = row.select_one(f'a[href^="/admin/catalog/{kind}/"]')
        assert len(codes) == 2 and edit is not None
        rows.append((edit["href"], codes[1].get_text(strip=True)))
    return tuple(rows)


def _form_payload(form):
    """Serialize successful controls like a browser, excluding submit buttons."""
    payload = MultiDict()
    for control in form.select("input[name], textarea[name], select[name]"):
        if control.has_attr("disabled"):
            continue
        name = control["name"]
        if control.name == "textarea":
            payload.add(name, control.get_text())
            continue
        if control.name == "select":
            options = [option for option in control.select("option") if not option.has_attr("disabled")]
            selected = [option for option in options if option.has_attr("selected")]
            if not selected and options:
                selected = options[:1]
            for option in selected:
                payload.add(name, option.get("value", option.get_text()))
            continue
        input_type = control.get("type", "text").lower()
        if input_type in {"checkbox", "radio"} and not control.has_attr("checked"):
            continue
        payload.add(name, control.get("value", ""))
    return payload


def _publish_catalog_editor(admin_client, edit_path):
    editor = admin_client.get(edit_path)
    assert editor.status_code == 200
    page = BeautifulSoup(editor.data, "html.parser")
    form = page.select_one("form[data-content-editor]")
    assert form is not None
    payload = _form_payload(form)
    payload.setlist("action", ["publish"])
    return admin_client.post(edit_path, data=payload)


def _catalog_row(admin_client, kind, slug):
    return next(row for row in _catalog_rows(admin_client, kind) if row[1] == slug)


def _public_title(client, path):
    response = client.get(path)
    assert response.status_code == 200
    heading = BeautifulSoup(response.data, "html.parser").select_one("main h1")
    assert heading is not None
    return heading.get_text(" ", strip=True)


def _publish_available_scenarios(admin_client):
    published = 0
    gaps = []
    rows = _catalog_rows(admin_client, "scenario")
    assert len(rows) == 13
    for edit_path, slug in rows:
        response = _publish_catalog_editor(admin_client, edit_path)
        if response.status_code == 302:
            published += 1
        else:
            assert response.status_code == 400
            gaps.append((slug, response.get_json()["error"]))
    assert published == 12
    assert gaps == [("data-process-foundation", "scenario_public_incomplete")]


def _image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (12, 8), (32, 96, 160)).save(output, format="PNG")
    return output.getvalue()


def _pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.metadata = None
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _upload_media(admin_client, *, name, mime, data):
    response = admin_client.post(
        "/admin/media",
        data={
            "csrf_token": CSRF,
            "metadata_review_confirmed": "1",
            "file": (io.BytesIO(data), name, mime),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    page = BeautifulSoup(admin_client.get("/admin/media").data, "html.parser")
    for row in page.select("tbody tr"):
        cells = row.select("td")
        if len(cells) >= 2 and cells[1].get_text(strip=True) == name:
            return int(cells[0].get_text(strip=True))
    raise AssertionError(f"uploaded media is not listed: {name}")


def _case_form(image_id):
    return {
        "csrf_token": CSRF,
        "action": "publish",
        "slug": "journey-verified-case",
        "title": "经授权匿名的知识助手案例",
        "summary": "经真实性、隐私和指标依据复核的匿名案例。",
        "seo_title": "经授权匿名知识助手案例",
        "seo_description": "查看经人工复核的匿名知识助手案例与量化依据。",
        "share_image_media_id": str(image_id),
        "verification_code": "authorized_anonymous",
        "is_verified": "1",
        "basis_type": "internal_delivery_record",
        "private_basis_reference": "PRIVATE-BASIS-JOURNEY-001",
        "source_url": "",
        "review_confirmed": "1",
        "privacy_review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "image_text",
        "blocks-0-title": "实施过程",
        "blocks-0-body": "<p>仅展示经审核的实施过程。</p>",
        "blocks-0-media_id": str(image_id),
        "blocks-0-image_alignment": "left",
        "blocks-0-image_alt_text": "知识助手实施过程示意图",
        "metrics-0-name": "资料检索时间",
        "metrics-0-before_value": "30",
        "metrics-0-after_value": "8",
        "metrics-0-unit": "分钟",
        "metrics-0-statistical_period": "连续 30 天",
        "metrics-0-evidence_explanation": "依据匿名交付记录中的抽样时长对比。",
    }


def _sourced_resource_form(attachment_id):
    return {
        "csrf_token": CSRF,
        "action": "save",
        "slug": "journey-reviewed-resource",
        "title": "经来源检查的企业 AI 指南",
        "summary": "来源、版权和附件均经过人工审核。",
        "seo_title": "经来源检查的企业 AI 指南",
        "seo_description": "查看经来源、版权和附件审核的企业 AI 指南。",
        "share_image_media_id": "",
        "resource_type": "guide",
        "is_original": "0",
        "source_name": "公开资料中心",
        "source_url": "https://source.example/guides/ai-readiness",
        "original_published_at": "2026-08-20T09:30:00",
        "copyright_notice": "经许可进行摘要展示，原文版权归来源方。",
        "attachment_media_id": str(attachment_id),
        "review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "指南摘要",
        "blocks-0-body": "<p>仅展示经人工审核的资源摘要。</p>",
        "blocks-0-media_id": "",
    }


def _announcement_form():
    return {
        "csrf_token": CSRF,
        "action": "publish",
        "slug": "journey-active-announcement",
        "title": "旅程中的当前公告",
        "summary": "仅在固定上海时间区间内展示。",
        "seo_title": "旅程中的当前公告",
        "seo_description": "验证公告只在固定有效期内公开。",
        "share_image_media_id": "",
        "valid_from": "2026-08-25T09:00:00",
        "valid_until": "2026-08-26T09:00:00",
        "cta_url": "/assessment",
        "review_confirmed": "1",
        "media_review_confirmed": "1",
        "blocks-0-type": "rich_text",
        "blocks-0-title": "公告正文",
        "blocks-0-body": "<p>当前有效的公告内容。</p>",
        "blocks-0-media_id": "",
    }


def test_journey_source_stays_on_http_admin_and_cli_surfaces():
    """Prevent later journey helpers from bypassing the accepted system surfaces."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported_modules = []
    direct_database_calls = []
    string_literals = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"execute", "executemany", "executescript"}
        ):
            direct_database_calls.append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_literals.append(node.value.lstrip().lower())

    sql_prefixes = tuple(
        left + right
        for left, right in (
            ("sel", "ect "),
            ("ins", "ert "),
            ("upd", "ate "),
            ("del", "ete "),
            ("pra", "gma "),
        )
    )
    assert not any(
        module.endswith("_" + "repository") for module in imported_modules
    )
    assert direct_database_calls == []
    assert not any(
        literal.startswith(sql_prefixes) for literal in string_literals
    )


def test_admin_http_can_publish_a_complete_service_with_seeded_maturity(admin_client):
    """Catch a service admin form that erases its seeded revision maturity relation."""
    _publish_available_scenarios(admin_client)

    mobile = admin_client.get(
        "/scenarios?industry=manufacturing&department=production"
        "&maturity=explore&per_page=50",
        headers={"User-Agent": "Mozilla/5.0 Mobile 390x844"},
    )
    assert mobile.status_code == 200
    mobile_page = BeautifulSoup(mobile.data, "html.parser")
    assert [
        card["data-scenario-code"]
        for card in mobile_page.select("[data-scenario-code]")
    ] == ["mfg_knowledge_assistant"]
    assert mobile_page.select_one('form[aria-label="筛选场景"]') is not None
    assert mobile_page.select_one('meta[name="viewport"]')["content"] == (
        "width=device-width, initial-scale=1.0"
    )

    service_rows = _catalog_rows(admin_client, "service")
    assert len(service_rows) == 6
    edit_path, slug = service_rows[0]
    published = _publish_catalog_editor(admin_client, edit_path)
    assert published.status_code == 302, published.get_data(as_text=True)

    detail = admin_client.get(f"/service-packages/{slug}")
    assert detail.status_code == 200
    page = BeautifulSoup(detail.data, "html.parser")
    sections = {
        node["data-service-section"]
        for node in page.select("[data-service-section]")
    }
    assert sections >= SERVICE_REQUIRED_SECTIONS


def test_admin_can_publish_schedule_revise_and_archive_through_http_and_cli(
    client, admin_client, monkeypatch, capsys
):
    """Catch a missing admin scheduling surface or a due job that hides the old revision."""
    edit_path, slug = _catalog_row(
        admin_client, "scenario", "mfg-knowledge-assistant"
    )
    public_path = f"/scenarios/{slug}"
    admin_now = datetime(2020, 1, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    due_now = datetime(2021, 1, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: admin_now

    assert client.get(public_path).status_code == 404
    published = _publish_catalog_editor(admin_client, edit_path)
    assert published.status_code == 302
    original_title = _public_title(client, public_path)

    copied_editor = admin_client.get(edit_path)
    assert copied_editor.status_code == 200
    copied_page = BeautifulSoup(copied_editor.data, "html.parser")
    copied_form = copied_page.select_one("form[data-content-editor]")
    assert copied_form is not None
    revision_payload = _form_payload(copied_form)
    revision_payload.setlist("title", ["知识助手场景 · 定时修订"])
    revision_payload.setlist("seo_title", ["知识助手场景定时修订"])
    revision_payload.setlist("action", ["save"])
    saved = admin_client.post(edit_path, data=revision_payload)
    assert saved.status_code == 302

    schedule_editor = admin_client.get(edit_path)
    schedule_page = BeautifulSoup(schedule_editor.data, "html.parser")
    schedule_form = schedule_page.select_one("form[data-schedule-content]")
    assert schedule_form is not None
    schedule_payload = _form_payload(schedule_form)
    schedule_payload.setlist("publish_at", ["2021-01-01T09:00:00"])
    schedule_payload.setlist("action", ["schedule"])
    scheduled = admin_client.post(edit_path, data=schedule_payload)
    assert scheduled.status_code == 302
    assert _public_title(client, public_path) == original_title

    monkeypatch.setattr(manage.publishing_service, "shanghai_now", lambda: due_now)
    assert manage.main(["publish-due-content"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert "published_count=1" in output.out
    assert _public_title(client, public_path) == "知识助手场景 · 定时修订"

    archive_editor = admin_client.get(edit_path)
    archive_page = BeautifulSoup(archive_editor.data, "html.parser")
    archive_button = archive_page.select_one(
        'button[name="action"][value="archive"]'
    )
    assert archive_button is not None
    archive_form = archive_button.find_parent("form")
    archive_payload = _form_payload(archive_form)
    archive_payload.setlist("action", ["archive"])
    archived = admin_client.post(edit_path, data=archive_payload)
    assert archived.status_code == 302
    assert client.get(public_path).status_code == 404


def test_stale_schedule_returns_a_recoverable_admin_conflict(admin_client):
    """Catch a stale scheduling payload being mistaken for a narrative draft."""
    edit_path, _slug = _catalog_row(
        admin_client, "scenario", "mfg-knowledge-assistant"
    )
    admin_now = datetime(2020, 1, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    admin_client.application.config["ADMIN_NOW_PROVIDER"] = lambda: admin_now

    initial = admin_client.get(edit_path)
    page = BeautifulSoup(initial.data, "html.parser")
    schedule_form = page.select_one("form[data-schedule-content]")
    editor_form = page.select_one("form[data-content-editor]")
    assert schedule_form is not None and editor_form is not None
    stale_schedule = _form_payload(schedule_form)
    stale_schedule.setlist("publish_at", ["2021-01-01T09:00:00"])
    stale_schedule.setlist("action", ["schedule"])

    concurrent_edit = _form_payload(editor_form)
    concurrent_edit.setlist("title", ["并发保存后的标题"])
    concurrent_edit.setlist("action", ["save"])
    assert admin_client.post(edit_path, data=concurrent_edit).status_code == 302

    conflict = admin_client.post(edit_path, data=stale_schedule)
    assert conflict.status_code == 409
    conflict_page = BeautifulSoup(conflict.data, "html.parser")
    assert "内容已被其他操作更新" in conflict_page.get_text(" ", strip=True)
    publish_at = conflict_page.select_one(
        'form[data-schedule-content] input[name="publish_at"]'
    )
    assert publish_at is not None
    assert publish_at.get("value") == "2021-01-01T09:00:00"


def test_verified_case_resource_media_and_service_relations_are_public_only_after_review(
    client, admin_client
):
    """Exercise reviewed case/resource/media creation and relation publication over HTTP."""

    class SuccessfulSourceTransport:
        def fetch(self, url, **_kwargs):
            return FetchResult(
                True, "https_ok", url, 200, "text/html", b"reviewed"
            )

    admin_client.application.config.update(
        ADMIN_NOW_PROVIDER=lambda: JOURNEY_NOW,
        CONTENT_NOW_PROVIDER=lambda: JOURNEY_NOW,
        RESOURCE_SOURCE_TRANSPORT=SuccessfulSourceTransport(),
    )
    image_id = _upload_media(
        admin_client,
        name="journey-case.png",
        mime="image/png",
        data=_image_bytes(),
    )
    attachment_id = _upload_media(
        admin_client,
        name="journey-guide.pdf",
        mime="application/pdf",
        data=_pdf_bytes(),
    )

    created_case = admin_client.post("/admin/cases/new", data=_case_form(image_id))
    assert created_case.status_code == 302
    case_public = client.get("/cases/journey-verified-case")
    assert case_public.status_code == 200
    case_page = BeautifulSoup(case_public.data, "html.parser")
    assert "经授权匿名案例" in case_page.get_text(" ", strip=True)
    metric = case_page.select_one("[data-case-metric]")
    assert metric is not None
    assert "统计周期" in metric.get_text(" ", strip=True)
    assert "连续 30 天" in metric.get_text(" ", strip=True)
    assert "PRIVATE-BASIS-JOURNEY-001" not in case_page.get_text()
    assert case_page.select_one('main a[href^="mailto:"]') is None
    assert case_page.select_one('main a[href^="tel:"]') is None
    case_image = case_page.select_one(
        f'img[src="/media/{image_id}/image"]'
    )
    assert case_image is not None
    assert client.get(case_image["src"]).status_code == 200

    saved_resource = admin_client.post(
        "/admin/resources/new", data=_sourced_resource_form(attachment_id)
    )
    assert saved_resource.status_code == 302
    resource_edit_path = saved_resource.headers["Location"]
    resource_id = int(resource_edit_path.rsplit("/", 1)[-1])
    assert client.get("/resources/journey-reviewed-resource").status_code == 404

    source_page = BeautifulSoup(
        admin_client.get(resource_edit_path).data, "html.parser"
    )
    source_form = source_page.select_one(
        f'form[action="/admin/resources/{resource_id}/source-check"]'
    )
    assert source_form is not None
    source_checked = admin_client.post(
        source_form["action"], data=_form_payload(source_form)
    )
    assert source_checked.status_code == 302

    reviewed_page = BeautifulSoup(
        admin_client.get(resource_edit_path).data, "html.parser"
    )
    reviewed_form = reviewed_page.select_one("form[data-content-editor]")
    assert reviewed_form is not None
    publish_resource = _form_payload(reviewed_form)
    publish_resource.setlist("review_confirmed", ["1"])
    publish_resource.setlist("media_review_confirmed", ["1"])
    publish_resource.setlist("action", ["publish"])
    published_resource = admin_client.post(
        resource_edit_path, data=publish_resource
    )
    assert published_resource.status_code == 302

    resource_public = client.get("/resources/journey-reviewed-resource")
    assert resource_public.status_code == 200
    resource_page = BeautifulSoup(resource_public.data, "html.parser")
    source_link = resource_page.select_one("a[data-resource-source]")
    assert source_link is not None
    assert source_link["href"] == "https://source.example/guides/ai-readiness"
    assert source_link.get("rel") == ["noopener", "noreferrer"]
    attachment = resource_page.select_one("a[data-resource-attachment]")
    assert attachment is not None
    assert attachment["href"] == f"/media/{attachment_id}/download"
    download = client.get(attachment["href"])
    assert download.status_code == 200
    assert download.headers["Content-Disposition"].startswith("attachment;")

    _publish_available_scenarios(admin_client)
    service_edit_path, service_slug = _catalog_rows(admin_client, "service")[0]
    service_editor = admin_client.get(service_edit_path)
    service_page = BeautifulSoup(service_editor.data, "html.parser")
    service_form = service_page.select_one("form[data-content-editor]")
    assert service_form is not None
    relation_choices = {
        option["data-entry-type"]: option["value"]
        for option in service_page.select(
            "[data-new-relation-target] option[data-entry-type]"
        )
    }
    assert set(relation_choices) == {"case", "resource"}
    publish_service = _form_payload(service_form)
    publish_service.update(
        {
            "relations-0-type": "service_case",
            "relations-0-target_group_id": relation_choices["case"],
            "relations-1-type": "service_resource",
            "relations-1-target_group_id": relation_choices["resource"],
        }
    )
    publish_service.setlist("action", ["publish"])
    assert admin_client.post(service_edit_path, data=publish_service).status_code == 302

    service_public = client.get(f"/service-packages/{service_slug}")
    assert service_public.status_code == 200
    service_detail = BeautifulSoup(service_public.data, "html.parser")
    related_text = service_detail.select_one(
        '[data-service-section="related-content"]'
    ).get_text(" ", strip=True)
    assert "经授权匿名的知识助手案例" in related_text
    assert "经来源检查的企业 AI 指南" in related_text
    assert service_detail.select_one(
        'a[href="/resources/journey-reviewed-resource"]'
    ) is not None


def test_active_announcement_disappears_at_the_exact_expiry_boundary(
    client, admin_client
):
    """Catch an announcement that remains public or on the homepage after expiry."""
    clock = {"now": JOURNEY_NOW}
    admin_client.application.config.update(
        ADMIN_NOW_PROVIDER=lambda: clock["now"],
        CONTENT_NOW_PROVIDER=lambda: clock["now"],
    )
    created = admin_client.post(
        "/admin/announcements/new", data=_announcement_form()
    )
    assert created.status_code == 302

    public_path = "/announcements/journey-active-announcement"
    assert client.get(public_path).status_code == 200
    assert "旅程中的当前公告" in client.get("/").get_data(as_text=True)

    clock["now"] = datetime(2026, 8, 26, 9, 0, 1, tzinfo=SHANGHAI)
    expired = client.get(public_path)
    assert expired.status_code == 404
    assert "旅程中的当前公告" not in client.get("/").get_data(as_text=True)


def test_cli_source_review_preview_and_idempotent_seeded_service_conversion(
    client,
    admin_client,
    monkeypatch,
    capsys,
    tmp_path,
):
    """Discover and merge a seeded legacy service using only CLI/admin/public APIs."""

    class NoNetworkTransport:
        calls = []

        def fetch(self, url, **_kwargs):
            self.calls.append(url)
            raise AssertionError("seeded service source review must not use the network")

    admin_client.application.config.update(
        ADMIN_NOW_PROVIDER=lambda: JOURNEY_NOW,
        CONTENT_NOW_PROVIDER=lambda: JOURNEY_NOW,
    )
    monkeypatch.setattr(manage, "shanghai_now", lambda: JOURNEY_NOW)
    monkeypatch.setattr(
        manage.legacy_content_migration,
        "current_shanghai_datetime",
        lambda: JOURNEY_NOW.replace(tzinfo=None),
    )

    assert manage.main(["inventory-content"]) == 0
    inventory_capture = capsys.readouterr()
    assert inventory_capture.err == ""
    assert "private=never-output" not in inventory_capture.out
    inventory = tuple(
        json.loads(line) for line in inventory_capture.out.splitlines()
    )
    service = next(
        row
        for row in inventory
        if row["source_table"] == "services"
        and row["target_group"] == "foundation_workshop"
    )
    assert service["proposed_action"] == "keep"
    assert service["source_state"] == "unchecked"

    assert manage.main(["inventory-content"]) == 0
    repeated_dry_run = capsys.readouterr()
    assert repeated_dry_run.err == ""
    assert repeated_dry_run.out == inventory_capture.out

    assert manage.main(["inventory-content", "--record"]) == 0
    recorded_capture = capsys.readouterr()
    assert recorded_capture.err == ""
    assert "private=never-output" not in recorded_capture.out

    monkeypatch.setattr(manage, "PinnedHttpTransport", NoNetworkTransport)
    assert manage.main(["check-content-sources"]) == 0
    checked_capture = capsys.readouterr()
    assert checked_capture.err == ""
    assert (
        f"source_table=services source_id={service['source_id']} "
        "state=missing code=source_missing"
    ) in checked_capture.out
    assert NoNetworkTransport.calls == []

    decision_path = Path(tmp_path) / "journey-decisions.jsonl"
    decision = {
        "version": 1,
        "source_table": "services",
        "source_id": service["source_id"],
        "source_checksum": service["source_checksum"],
        "action": "keep",
        "confirmations": service["required_confirmations"],
        "target": {"target_group": "foundation_workshop"},
    }
    decision_path.write_text(
        json.dumps(decision, ensure_ascii=False), encoding="utf-8"
    )

    command = ["migrate-legacy-content", "--decisions", str(decision_path)]
    assert manage.main(command) == 0
    preview_capture = capsys.readouterr()
    assert preview_capture.err == ""
    preview = json.loads(preview_capture.out)
    assert preview["status"] == "target_draft_exists"
    assert preview["preview"] == {
        "kind": "service_narrative_merge",
        "changes": ["summary", "review_block"],
    }
    target_id = preview["target_content_id"]
    target_lock_version = preview["target_lock_version"]
    assert isinstance(target_id, int)
    assert isinstance(target_lock_version, int)

    decision["target"] = {
        "target_group": "foundation_workshop",
        "target_content_id": target_id,
        "expected_lock_version": target_lock_version,
        "merge_approved": True,
    }
    decision_path.write_text(
        json.dumps(decision, ensure_ascii=False), encoding="utf-8"
    )
    assert manage.main(command) == 0
    approved_capture = capsys.readouterr()
    assert approved_capture.err == ""
    approved = json.loads(approved_capture.out)
    assert approved["status"] == "ready"
    assert approved["target_content_id"] == target_id

    public_path = "/service-packages/foundation-workshop"
    assert client.get(public_path).status_code == 404

    assert manage.main([*command, "--apply"]) == 0
    first_capture = capsys.readouterr()
    assert first_capture.err == ""
    first = json.loads(first_capture.out)
    assert first["status"] == "migrated"
    assert first["target_content_id"] == target_id
    assert client.get(public_path).status_code == 404

    assert manage.main([*command, "--apply"]) == 0
    second_capture = capsys.readouterr()
    assert second_capture.err == ""
    second = json.loads(second_capture.out)
    assert second["status"] == "already_mapped"
    assert second["target_content_id"] == target_id

    _publish_available_scenarios(admin_client)
    service_edit_path, slug = _catalog_row(
        admin_client, "service", "foundation-workshop"
    )
    assert slug == "foundation-workshop"
    service_editor = admin_client.get(service_edit_path)
    assert service_editor.status_code == 200
    service_form = BeautifulSoup(
        service_editor.data, "html.parser"
    ).select_one("form[data-content-editor]")
    assert service_form is not None
    assert _form_payload(service_form)["content_id"] == str(target_id)
    assert _publish_catalog_editor(admin_client, service_edit_path).status_code == 302
    assert client.get(public_path).status_code == 200


def test_disabled_legacy_scraper_and_unmapped_compatibility_routes_fail_closed(
    client, admin_client, monkeypatch
):
    """Catch network use, direct scrape publication, or unsafe legacy fallbacks."""
    calls = []

    def forbidden_network(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("legacy scraper must not use the network")

    monkeypatch.setattr(requests, "get", forbidden_network)
    disabled = admin_client.post(
        "/admin/scrape", data={"csrf_token": CSRF}
    )
    assert disabled.status_code == 410
    assert disabled.get_json() == {"error": "ingestion_queue_not_ready"}
    assert calls == []

    services = client.get(
        "/services?next=https://attacker.example", follow_redirects=False
    )
    insights = client.get(
        "/insights?next=https://attacker.example", follow_redirects=False
    )
    assert (services.status_code, services.headers["Location"]) == (
        301,
        "/service-packages",
    )
    assert (insights.status_code, insights.headers["Location"]) == (
        301,
        "/resources",
    )
    assert client.get("/article/2147483647").status_code == 404
