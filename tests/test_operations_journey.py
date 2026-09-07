"""Task 22 Stage 5 journeys through authenticated HTTP surfaces only."""

import ast
import csv
from datetime import datetime, timedelta
from io import StringIO
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import pytest
from werkzeug.datastructures import MultiDict
from werkzeug.security import generate_password_hash

os.environ.setdefault("AI_PLATFORM_PUBLIC_BASE_URL", "https://test.example")

import app as app_module
import ingestion_sources
import models
from source_url_checker import FetchResult


CSRF = "task22-csrf-token"
ADMIN_USERNAME = "task22-admin"
ADMIN_PASSWORD = "task22-only-password"
SHANGHAI = ZoneInfo("Asia/Shanghai")
JOURNEY_NOW = datetime(2026, 9, 3, 10, 0, tzinfo=SHANGHAI)
SOURCE_CODE = "task22_reviewed_source"
SOURCE_URL = "https://task22.test.example/reviewed"
SOURCE_HOST = "task22.test.example"
SOURCE_LICENSE = "task22_review_2026_09"
BRANCHES = (
    "manufacturing",
    "retail",
    "professional_knowledge",
    "software_creative",
)
LEGAL_TYPES = ("privacy", "terms", "roi_disclaimer", "ai_content_notice")


class _FakePinnedTransport:
    def __init__(self):
        self.calls = []

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert url == SOURCE_URL
        assert kwargs["allowed_hosts"] == frozenset({SOURCE_HOST})
        assert kwargs["allowed_schemes"] == frozenset({"https"})
        return FetchResult(
            True,
            "https_ok",
            SOURCE_URL,
            200,
            "text/plain",
            "Task 22 固定候选\n仅使用经审核来源的摘要。".encode("utf-8"),
        )


@pytest.fixture
def journey(tmp_path, monkeypatch):
    registry = tmp_path / "task22-reviewed-sources.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "sources": [
                    {
                        "code": SOURCE_CODE,
                        "name": "Task 22 TEST ONLY 已审来源",
                        "url": SOURCE_URL,
                        "hosts": [SOURCE_HOST],
                        "adapter": "plain_text",
                        "scheme": "https",
                        "license_basis_reference": SOURCE_LICENSE,
                        "robots_policy": "allow",
                        "retain_body": False,
                        "enabled": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    transport = _FakePinnedTransport()
    monkeypatch.setattr(ingestion_sources, "REGISTRY_PATH", registry)
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", SOURCE_CODE)
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "task22-operations.db"))
    models.init_db()
    application = app_module.create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "task22-session-secret",
            "ADMIN_USERNAME": ADMIN_USERNAME,
            "ADMIN_PASSWORD_HASH": generate_password_hash(ADMIN_PASSWORD),
            "SESSION_COOKIE_SECURE": True,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "MEDIA_UPLOAD_ROOT": str(tmp_path / "media"),
            "PUBLIC_BASE_URL": "https://test.example",
            "INGESTION_TRANSPORT": transport,
            "RESOURCE_SOURCE_TRANSPORT": transport,
            "ADMIN_NOW_PROVIDER": lambda: JOURNEY_NOW,
            "CONTENT_NOW_PROVIDER": lambda: JOURNEY_NOW,
            "ASSESSMENT_FLOW_NOW_PROVIDER": lambda: JOURNEY_NOW,
            "PRIVACY_PROCESSOR_NAME": "Task 22 TEST ONLY processor",
            "PRIVACY_CONTACT": "privacy@test.example",
            "PRIVACY_POLICY_URL": None,
        }
    )
    public = application.test_client()
    admin = application.test_client()
    anonymous = application.test_client()
    with admin.session_transaction() as session:
        session["admin_username"] = ADMIN_USERNAME
        session["csrf_token"] = CSRF
    return {
        "app": application,
        "public": public,
        "admin": admin,
        "anonymous": anonymous,
        "transport": transport,
    }


def _form_payload(form):
    payload = MultiDict()
    for control in form.select("input[name], textarea[name], select[name]"):
        if control.has_attr("disabled"):
            continue
        name = control["name"]
        if control.name == "textarea":
            payload.add(name, control.get_text())
            continue
        if control.name == "select":
            options = [
                option
                for option in control.select("option")
                if not option.has_attr("disabled")
            ]
            selected = [option for option in options if option.has_attr("selected")]
            if not selected and options:
                selected = options[:1]
            for option in selected:
                payload.add(name, option.get("value", option.get_text()))
            continue
        input_type = control.get("type", "text").lower()
        if input_type in {"checkbox", "radio"} and not control.has_attr("checked"):
            continue
        if input_type in {"button", "submit", "reset"}:
            continue
        payload.add(name, control.get("value", ""))
    return payload


def _catalog_rows(admin, kind):
    response = admin.get(
        "/admin/resources" if kind == "resource" else f"/admin/catalog/{kind}"
    )
    assert response.status_code == 200
    rows = []
    selector = "tbody tr" if kind == "resource" else "[data-catalog-row]"
    for row in BeautifulSoup(response.data, "html.parser").select(selector):
        codes = row.select("code")
        edit_prefix = (
            "/admin/resources/" if kind == "resource" else f"/admin/catalog/{kind}/"
        )
        edit = row.select_one(f'a[href^="{edit_prefix}"]')
        if kind == "resource":
            if len(codes) != 1 or edit is None:
                continue
            slug = codes[0].get_text(strip=True).removeprefix("/resources/")
            group = "resource"
        else:
            assert len(codes) == 2 and edit is not None
            group = codes[0].get_text(strip=True).removeprefix(f"{kind}:")
            slug = codes[1].get_text(strip=True)
        rows.append(
            {
                "path": edit["href"],
                "group": group,
                "slug": slug,
            }
        )
    return tuple(rows)


def _publish_catalog_editor(admin, edit_path):
    editor = admin.get(edit_path)
    assert editor.status_code == 200
    form = BeautifulSoup(editor.data, "html.parser").select_one(
        "form[data-content-editor]"
    )
    assert form is not None
    payload = _form_payload(form)
    for confirmation in ("review_confirmed", "media_review_confirmed"):
        if form.select_one(f'[name="{confirmation}"]') is not None:
            payload.setlist(confirmation, ["1"])
    payload.setlist("action", ["publish"])
    return admin.post(edit_path, data=payload)


def _visible_candidate_state(admin, candidate_id):
    response = admin.get(f"/admin/ingestion/{candidate_id}")
    assert response.status_code == 200
    page = BeautifulSoup(response.data, "html.parser")
    text = page.get_text(" ", strip=True)
    lock = page.select_one('input[name="expected_lock_version"]')
    return text, None if lock is None else lock["value"]


def _publish_legal(admin, document_type, suffix, now):
    admin.application.config["ADMIN_NOW_PROVIDER"] = lambda: now
    version_code = f"task22-{document_type}-{suffix}"
    created = admin.post(
        "/admin/legal/new",
        data={
            "csrf_token": CSRF,
            "document_type": document_type,
            "version_code": version_code,
            "title": f"Task 22 TEST ONLY {document_type} {suffix}",
            "body_summary": f"Task 22 TEST ONLY {document_type} {suffix} summary",
            "body_html": f"<p>Task 22 TEST ONLY {document_type} {suffix} body</p>",
            "effective_at": now.replace(tzinfo=None).isoformat(timespec="seconds"),
        },
    )
    assert created.status_code == 302
    location = created.headers["Location"]
    draft = BeautifulSoup(admin.get(location).data, "html.parser")
    review_form = draft.select_one('form button[value="review"]')
    assert review_form is not None
    review_payload = _form_payload(review_form.find_parent("form"))
    review_payload.setlist("action", ["review"])
    reviewed = admin.post(location, data=review_payload)
    assert reviewed.status_code == 302
    reviewed_page = BeautifulSoup(admin.get(location).data, "html.parser")
    publish_button = reviewed_page.select_one('form button[value="publish"]')
    assert publish_button is not None
    publish_payload = _form_payload(publish_button.find_parent("form"))
    publish_payload.setlist("action", ["publish"])
    published = admin.post(location, data=publish_payload)
    assert published.status_code == 302
    return version_code


def _publish_legal_bundle(journey, suffix="v1", now=JOURNEY_NOW):
    return {
        document_type: _publish_legal(
            journey["admin"], document_type, suffix, now
        )
        for document_type in LEGAL_TYPES
    }


def _issue_config(journey, branch="manufacturing", now=JOURNEY_NOW):
    journey["app"].config["ASSESSMENT_FLOW_NOW_PROVIDER"] = lambda: now
    response = journey["public"].get(f"/api/v2/assessment/config/{branch}")
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["branch"]["code"] == branch
    assert isinstance(payload["flow_id"], str) and len(payload["flow_id"]) == 32
    return payload


def _bound_preview_payload(config):
    return {
        "flow_id": config["flow_id"],
        "rule_version": config["rule_version"],
        "schema_version": "2.0",
        "profile": {
            "branch_code": config["branch"]["code"],
            "subbranch_code": config["subbranches"][0]["code"],
            "department_code": config["departments"][0]["code"],
            "company_size_code": config["company_sizes"][0]["code"],
            "pain_codes": [config["pain_points"][0]["code"]],
        },
        "answers": {
            question["code"]: question["options"][-1]["code"]
            for question in config["questions"]
        },
        "roi_choices": {
            group: options[0]
            for group, options in config["roi_options"].items()
        },
    }


def _bound_completion_payload(config, submission_key, company_name="Task 22 企业"):
    assessment = _bound_preview_payload(config)
    assessment.pop("flow_id")
    return {
        "flow_id": config["flow_id"],
        "submission_key": submission_key,
        "assessment": assessment,
        "contact": {
            "company_name": company_name,
            "contact_name": "Task 22 TEST ONLY contact",
            "phone": "13800138000",
            "email": "task22@example.invalid",
            "wechat": "",
        },
        "consent": {
            "accepted": True,
            "policy_version": config["consent_policy_version"],
        },
        "attribution": {"source": "task22_journey"},
    }


def _complete(journey, config, submission_key, company_name="Task 22 企业"):
    response = journey["public"].post(
        "/api/v2/assessment/complete",
        json=_bound_completion_payload(config, submission_key, company_name),
        headers={"X-CSRF-Token": config["csrf_token"]},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _decode_csv(payload):
    assert payload.startswith(b"\xef\xbb\xbf")
    return tuple(csv.reader(StringIO(payload.decode("utf-8-sig"))))


def _publish_available_scenarios(admin):
    outcomes = []
    rows = _catalog_rows(admin, "scenario")
    assert len(rows) == 13
    for row in rows:
        response = _publish_catalog_editor(admin, row["path"])
        outcomes.append(
            (row["group"], response.status_code, response.get_json(silent=True))
        )
    assert sum(status == 302 for _code, status, _body in outcomes) == 12, outcomes
    assert [
        (code, status, body)
        for code, status, body in outcomes
        if status != 302
    ] == [
        (
            "data_process_foundation",
            400,
            {"error": "scenario_public_incomplete"},
        )
    ]


def _rule_preview_payload(editor, config):
    form = editor.select_one("form[data-rule-preview]")
    assert form is not None
    payload = _form_payload(form)
    payload.setlist("branch_code", [config["branch"]["code"]])
    payload.setlist("subbranch_code", [config["subbranches"][0]["code"]])
    payload.setlist("department_code", [config["departments"][0]["code"]])
    payload.setlist("company_size_code", [config["company_sizes"][0]["code"]])
    payload.setlist("pain_codes", [config["pain_points"][0]["code"]])
    for question in config["questions"]:
        payload.setlist(
            f'answer__{question["code"]}', [question["options"][-1]["code"]]
        )
    for group, options in config["roi_options"].items():
        payload.setlist(f"roi__{group}", [options[0]])
    return form["action"], payload


def _wait_for_next_database_second():
    """Keep the HTTP journey outside the rule editor's one-second timestamp edge."""
    observed = datetime.now(SHANGHAI).replace(microsecond=0)
    deadline = time.monotonic() + 1.2
    while datetime.now(SHANGHAI).replace(microsecond=0) == observed:
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_operations_journey_source_is_http_only():
    """Catch a future journey shortcut through repository imports or direct SQL."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported_modules = []
    database_calls = []
    sql_literals = []
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
            database_calls.append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            normalized = node.value.lstrip().lower()
            if normalized.startswith(sql_prefixes):
                sql_literals.append(node.lineno)

    assert not any(
        module.rsplit(".", 1)[-1] == "repository" or module.endswith("_repository")
        for module in imported_modules
    )
    assert database_calls == []
    assert sql_literals == []


def test_admin_shell_contains_mobile_navigation_tables_and_lead_controls(journey):
    """Keep every admin action reachable without document-level horizontal overflow."""
    rules = BeautifulSoup(journey["admin"].get("/admin/rules").data, "html.parser")
    leads = BeautifulSoup(journey["admin"].get("/admin/leads").data, "html.parser")
    navigation = rules.select("nav.admin-nav")
    assert len(navigation) == 1
    admin_navigation = navigation[0]
    assert admin_navigation.select_one('a.brand[href="/admin"]') is not None
    expected_groups = (
        (
            "运营",
            (
                ("运营工作台", "/admin"),
                ("线索管理", "/admin/leads"),
                ("诊断预约", "/admin/appointments"),
            ),
        ),
        (
            "内容",
            (
                ("行业文案", "/admin/catalog/industry"),
                ("场景文案", "/admin/catalog/scenario"),
                ("服务文案", "/admin/catalog/service"),
                ("审核资源", "/admin/resources"),
                ("接入候选", "/admin/ingestion"),
                ("已验证案例", "/admin/cases"),
                ("有效期公告", "/admin/announcements"),
            ),
        ),
        (
            "治理",
            (
                ("法律文档", "/admin/legal"),
                ("评估记录", "/admin/assessments"),
                ("规则版本", "/admin/rules"),
                ("隐私请求", "/admin/data-requests"),
            ),
        ),
        (
            "资产",
            (
                ("资产管理", "/admin/assets"),
                ("媒体管理", "/admin/media"),
            ),
        ),
    )
    groups = admin_navigation.select(".admin-nav__group")
    assert len(groups) == len(expected_groups)
    for group, (heading, expected_links) in zip(groups, expected_groups):
        assert group.select_one("h2").get_text(" ", strip=True) == heading
        assert tuple(
            (link.get_text(" ", strip=True), link["href"])
            for link in group.select("a[href]")
        ) == expected_links
        assert not group.has_attr("hidden")

    website = admin_navigation.select_one(
        '.admin-nav__footer a[href="/"][target="_blank"]'
    )
    assert website is not None
    assert {item.lower() for item in website.get("rel", ())} == {
        "noopener",
        "noreferrer",
    }
    assert admin_navigation.select_one(
        'a[href="/admin/rules"][aria-current="page"]'
    ) is not None

    logout = admin_navigation.select_one(
        'form[method="POST"][action="/admin/logout"]'
    )
    assert logout is not None
    assert logout.select_one('button[type="submit"]') is not None
    csrf = logout.select_one('input[type="hidden"][name="csrf_token"]')
    assert csrf is not None and csrf.get("value")

    stylesheet_link = rules.select_one('link[href="/static/css/admin.css"]')
    assert stylesheet_link is not None
    stylesheet_response = journey["admin"].get(stylesheet_link["href"])
    assert stylesheet_response.status_code == 200
    stylesheet = stylesheet_response.get_data(as_text=True)

    def css_blocks(source):
        cursor = 0
        while cursor < len(source):
            opening = source.find("{", cursor)
            if opening < 0:
                return
            depth = 1
            closing = opening + 1
            while closing < len(source) and depth:
                depth += source[closing] == "{"
                depth -= source[closing] == "}"
                closing += 1
            assert depth == 0
            yield source[cursor:opening].strip(), source[opening + 1 : closing - 1]
            cursor = closing

    def declarations(selector, media=None):
        blocks = list(css_blocks(stylesheet))
        if media is not None:
            media_blocks = [
                body for prelude, body in blocks if prelude == f"@media {media}"
            ]
            assert len(media_blocks) == 1
            blocks = list(css_blocks(media_blocks[0]))
        result = {}
        for prelude, body in blocks:
            if selector not in {part.strip() for part in prelude.split(",")}:
                continue
            for item in body.split(";"):
                name, separator, value = item.partition(":")
                if separator:
                    result[name.strip()] = value.strip()
        return result

    assert declarations(".admin-layout")["grid-template-columns"] == (
        "15rem minmax(0, 1fr)"
    )
    assert declarations(".admin-main")["min-width"] == "0"
    assert declarations(".admin-main table")["overflow-x"] == "auto"
    assert declarations(".admin-layout", "(max-width: 1023px)")[
        "grid-template-columns"
    ] == "minmax(0, 1fr)"
    assert "auto-fit" in declarations(
        ".admin-nav__groups", "(max-width: 1023px)"
    )["grid-template-columns"]

    assert rules.select("table th")
    assert all(not heading.has_attr("hidden") for heading in rules.select("table th"))
    assert leads.select_one('form[data-operations-filters="true"]') is not None
    export = leads.select_one('form[action="/admin/leads/export"] button')
    assert export is not None and export.get_text(strip=True) == "导出 CSV"


def test_fixed_candidate_is_reviewed_into_a_draft_then_published_publicly(journey):
    """Catch ingestion that bypasses review or cannot complete its public journey."""
    admin = journey["admin"]
    public = journey["public"]

    fetched = admin.post("/admin/scrape", data={"csrf_token": CSRF})
    assert fetched.status_code == 200
    assert fetched.get_json() == {
        "created_count": 1,
        "created_ids": [1],
        "deduplicated": 0,
        "failed_sources": 0,
    }
    assert len(journey["transport"].calls) == 1
    candidate_id = fetched.get_json()["created_ids"][0]
    candidate_text, lock = _visible_candidate_state(admin, candidate_id)
    assert "pending_review" in candidate_text
    assert "Task 22 固定候选" in candidate_text
    assert lock == "2"

    public_path = "/resources/task22-reviewed-resource"
    assert public.get(public_path).status_code == 404
    accepted = admin.post(
        f"/admin/ingestion/{candidate_id}/decision",
        data={
            "csrf_token": CSRF,
            "action": "accept",
            "expected_lock_version": lock,
            "slug": "task22-reviewed-resource",
        },
    )
    assert accepted.status_code == 302
    accepted_text, accepted_lock = _visible_candidate_state(admin, candidate_id)
    assert "accepted" in accepted_text
    assert accepted_lock is None
    assert public.get(public_path).status_code == 404

    resource = next(
        row
        for row in _catalog_rows(admin, "resource")
        if row["slug"] == "task22-reviewed-resource"
    )
    resource_editor = admin.get(resource["path"])
    source_check = BeautifulSoup(resource_editor.data, "html.parser").select_one(
        'form[action$="/source-check"]'
    )
    assert source_check is not None
    checked = admin.post(source_check["action"], data=_form_payload(source_check))
    assert checked.status_code == 302
    published = _publish_catalog_editor(admin, resource["path"])
    assert published.status_code == 302, published.get_data(as_text=True)
    page = public.get(public_path)
    assert page.status_code == 200
    assert "Task 22 固定候选" in BeautifulSoup(
        page.data, "html.parser"
    ).get_text(" ", strip=True)


def test_dashboard_queue_and_filtered_leads_export_the_same_formula_safe_row(journey):
    """Catch queue/list predicate drift or a CSV response returned before audit succeeds."""
    _publish_legal_bundle(journey)
    config = _issue_config(journey)
    _complete(
        journey,
        config,
        "550e8400-e29b-41d4-a716-446655442201",
        company_name="=2+5 Task 22 公司",
    )

    dashboard_response = journey["admin"].get("/admin")
    assert dashboard_response.status_code == 200
    dashboard = BeautifulSoup(dashboard_response.data, "html.parser")
    card = dashboard.select_one('[data-operation-card][data-queue="new_leads"]')
    assert card is not None and card["data-count"] == "1"
    queue_link = card.select_one('a[href="/admin?queue=new_leads"]')
    assert queue_link is not None
    queue_response = journey["admin"].get(queue_link["href"])
    queue = BeautifulSoup(queue_response.data, "html.parser")
    queue_section = queue.select_one('[data-operations-queue="new_leads"]')
    assert queue_section is not None
    assert queue_section["data-total"] == card["data-count"]
    queue_ids = {
        row["data-id"] for row in queue.select("[data-operation-row][data-id]")
    }

    filtered_response = journey["admin"].get(
        "/admin/leads?status=new&branch=manufacturing&queue=ordinary"
    )
    assert filtered_response.status_code == 200
    filtered = BeautifulSoup(filtered_response.data, "html.parser")
    lead_ids = {
        link["href"].rsplit("/", 1)[-1]
        for link in filtered.select('tbody a[href^="/admin/lead/"]')
    }
    assert lead_ids == queue_ids
    export_form = filtered.select_one('form[action="/admin/leads/export"]')
    assert export_form is not None
    exported = journey["admin"].post(
        export_form["action"], data=_form_payload(export_form)
    )
    assert exported.status_code == 200
    assert exported.headers["Cache-Control"] == "private, no-store"
    assert exported.headers["Content-Type"].startswith("text/csv")
    rows = _decode_csv(exported.data)
    assert len(rows) == 2
    assert rows[1][0] == "'=2+5 Task 22 公司"
    assert rows[1][2] == "'13800138000"
    assert "manufacturing" in rows[1]

    lead_id = next(iter(queue_ids))
    detail_path = f"/admin/lead/{lead_id}"
    detail_response = journey["admin"].get(detail_path)
    detail = BeautifulSoup(detail_response.data, "html.parser")
    followup_form = detail.select_one('form:has(input[name="action"][value="followup"])')
    assert followup_form is not None
    followup_payload = _form_payload(followup_form)
    followup_payload.setlist("followup_note", ["Task 22 TEST ONLY 逾期队列验收"])
    followup_payload.setlist("next_followup_at", ["2026-09-02T23:00"])
    followed_up = journey["admin"].post(detail_path, data=followup_payload)
    assert followed_up.status_code == 302

    overdue_dashboard_response = journey["admin"].get("/admin")
    overdue_dashboard = BeautifulSoup(overdue_dashboard_response.data, "html.parser")
    overdue_card = overdue_dashboard.select_one(
        '[data-operation-card][data-queue="followup_overdue"]'
    )
    assert overdue_card is not None and overdue_card["data-count"] == "1"
    overdue_link = overdue_card.select_one('a[href="/admin?queue=followup_overdue"]')
    assert overdue_link is not None
    overdue_response = journey["admin"].get(overdue_link["href"])
    overdue_queue = BeautifulSoup(overdue_response.data, "html.parser")
    overdue_section = overdue_queue.select_one(
        '[data-operations-queue="followup_overdue"]'
    )
    assert overdue_section is not None
    assert overdue_section["data-total"] == overdue_card["data-count"]
    overdue_ids = {
        row["data-id"]
        for row in overdue_queue.select("[data-operation-row][data-id]")
    }
    assert overdue_ids == {lead_id}


def test_same_session_old_and_new_privacy_flows_finish_exact_versions(journey):
    """Catch a later legal publication rebinding an already issued assessment flow."""
    versions_v1 = _publish_legal_bundle(journey)
    old_config = _issue_config(journey)
    next_now = JOURNEY_NOW + timedelta(minutes=1)
    privacy_v2 = _publish_legal(journey["admin"], "privacy", "v2", next_now)
    new_config = _issue_config(journey, now=next_now)

    assert old_config["flow_id"] != new_config["flow_id"]
    assert old_config["consent_policy_version"] == versions_v1["privacy"]
    assert new_config["consent_policy_version"] == privacy_v2
    old_result = _complete(
        journey,
        old_config,
        "550e8400-e29b-41d4-a716-446655442202",
        "Task 22 旧法律版本企业",
    )
    new_result = _complete(
        journey,
        new_config,
        "550e8400-e29b-41d4-a716-446655442203",
        "Task 22 新法律版本企业",
    )

    old_report = journey["public"].get(old_result["report_url"])
    new_report = journey["public"].get(new_result["report_url"])
    assert old_report.status_code == new_report.status_code == 200
    old_text = BeautifulSoup(old_report.data, "html.parser").get_text(" ", strip=True)
    new_text = BeautifulSoup(new_report.data, "html.parser").get_text(" ", strip=True)
    assert versions_v1["privacy"] in old_text
    assert privacy_v2 not in old_text
    assert privacy_v2 in new_text
    assert journey["public"].get(
        f'/legal/privacy/{versions_v1["privacy"]}'
    ).status_code == 200
    assert journey["public"].get(f"/legal/privacy/{privacy_v2}").status_code == 200


def test_rule_copy_preview_publish_switches_new_flow_and_keeps_old_report(journey):
    """Catch rule publication that leaks into an old flow or misses public services."""
    _publish_legal_bundle(journey)
    admin = journey["admin"]
    public = journey["public"]
    _publish_available_scenarios(admin)
    target_service = _catalog_rows(admin, "service")[0]
    assert _publish_catalog_editor(admin, target_service["path"]).status_code == 302
    public_path = f'/service-packages/{target_service["slug"]}'
    original_service = public.get(public_path)
    assert original_service.status_code == 200
    old_config = _issue_config(journey)

    rules = BeautifulSoup(admin.get("/admin/rules").data, "html.parser")
    copy_form = rules.select_one("form[data-rule-copy]")
    assert copy_form is not None
    copy_payload = _form_payload(copy_form)
    copy_payload.setlist("code", ["task22-rule-v2"])
    copy_payload.setlist("name", ["Task 22 TEST ONLY rule v2"])
    copied = admin.post(copy_form["action"], data=copy_payload)
    assert copied.status_code == 303
    edit_path = copied.headers["Location"]
    editor_response = admin.get(edit_path)
    assert editor_response.status_code == 200
    editor = BeautifulSoup(editor_response.data, "html.parser")
    edit_form = editor.select_one("form[data-rule-edit]")
    assert edit_form is not None
    edit_payload = _form_payload(edit_form)
    changed_names = {}
    changed_support = {}
    for fieldset in editor.select("[data-service-code]"):
        code = fieldset["data-service-code"]
        name = f"Task22 发布服务 {code}"
        support = f"Task22 发布支持 {code}"
        public_name = fieldset.select_one(
            f'input[name="service__{code}__public_name"]'
        )
        support_description = fieldset.select_one(
            f'textarea[name="service__{code}__support_description"]'
        )
        assert public_name is not None and support_description is not None
        edit_payload.setlist(public_name["name"], [name])
        edit_payload.setlist(support_description["name"], [support])
        changed_names[code] = name
        changed_support[code] = support
    saved = admin.post(edit_path, data=edit_payload)
    assert saved.status_code == 303, saved.get_data(as_text=True)
    _wait_for_next_database_second()

    saved_editor = BeautifulSoup(admin.get(edit_path).data, "html.parser")
    for branch in BRANCHES:
        preview_config = _issue_config(journey, branch)
        preview_action, preview_payload = _rule_preview_payload(
            saved_editor, preview_config
        )
        previewed = admin.post(preview_action, data=preview_payload)
        assert previewed.status_code == 200, previewed.get_data(as_text=True)
        preview_page = BeautifulSoup(previewed.data, "html.parser")
        assert {
            node["data-preview-section"]
            for node in preview_page.select("[data-preview-section]")
        } == {"scores", "scenarios", "roi", "roadmap", "services"}

    confirmation = BeautifulSoup(
        admin.get(f"{edit_path}/publish").data, "html.parser"
    )
    publish_form = confirmation.select_one("form[data-rule-publish]")
    assert publish_form is not None
    published = admin.post(
        publish_form["action"], data=_form_payload(publish_form)
    )
    assert published.status_code == 303, published.get_data(as_text=True)
    new_config = _issue_config(journey)
    assert old_config["rule_version"] != new_config["rule_version"]
    assert new_config["rule_version"] == "task22-rule-v2"

    switched_service = public.get(public_path)
    assert switched_service.status_code == 200
    assert changed_support[target_service["group"]] in BeautifulSoup(
        switched_service.data, "html.parser"
    ).get_text(" ", strip=True)
    assert switched_service.data != original_service.data

    old_result = _complete(
        journey,
        old_config,
        "550e8400-e29b-41d4-a716-446655442204",
        "Task 22 旧规则企业",
    )
    old_report_first = public.get(old_result["report_url"])
    assert old_report_first.status_code == 200
    assert b"Task22" not in old_report_first.data
    new_result = _complete(
        journey,
        new_config,
        "550e8400-e29b-41d4-a716-446655442205",
        "Task 22 新规则企业",
    )
    new_report = public.get(new_result["report_url"])
    assert new_report.status_code == 200
    assert b"Task22" in new_report.data
    old_report_second = public.get(old_result["report_url"])
    assert old_report_second.status_code == 200
    old_first_page = BeautifulSoup(old_report_first.data, "html.parser")
    old_second_page = BeautifulSoup(old_report_second.data, "html.parser")
    assert (
        old_first_page.select_one("main[data-snapshot-sha256]")[
            "data-snapshot-sha256"
        ]
        == old_second_page.select_one("main[data-snapshot-sha256]")[
            "data-snapshot-sha256"
        ]
    )
    assert str(old_first_page.select_one(".report-content")) == str(
        old_second_page.select_one(".report-content")
    )


def test_unauthorized_csrf_and_invalid_actions_keep_visible_domains_unchanged(journey):
    """Catch rejected admin actions that still create visible domain records."""
    admin = journey["admin"]
    anonymous = journey["anonymous"]
    public = journey["public"]

    empty_queue = admin.get("/admin/ingestion").data
    unauthorized = anonymous.post("/admin/scrape", data={"csrf_token": CSRF})
    assert unauthorized.status_code in {302, 403}
    assert admin.get("/admin/ingestion").data == empty_queue

    created = admin.post("/admin/scrape", data={"csrf_token": CSRF}).get_json()
    candidate_id = created["created_ids"][0]
    visible_before = _visible_candidate_state(admin, candidate_id)
    missing_csrf = admin.post(
        f"/admin/ingestion/{candidate_id}/decision",
        data={
            "action": "accept",
            "expected_lock_version": visible_before[1],
            "slug": "task22-must-not-exist",
        },
    )
    invalid = admin.post(
        f"/admin/ingestion/{candidate_id}/decision",
        data={
            "csrf_token": CSRF,
            "action": "purge",
            "expected_lock_version": visible_before[1],
        },
    )
    assert missing_csrf.status_code == 403
    assert invalid.status_code == 400
    assert _visible_candidate_state(admin, candidate_id) == visible_before
    assert public.get("/resources/task22-must-not-exist").status_code == 404

    legal_marker = "task22-forbidden-privacy"
    assert legal_marker not in admin.get("/admin/legal").get_data(as_text=True)
    legal_payload = {
        "csrf_token": CSRF,
        "document_type": "privacy",
        "version_code": legal_marker,
        "title": "Task 22 forbidden",
        "body_summary": "Task 22 forbidden summary",
        "body_html": "<p>Task 22 forbidden body</p>",
        "effective_at": JOURNEY_NOW.replace(tzinfo=None).isoformat(
            timespec="seconds"
        ),
    }
    assert anonymous.post("/admin/legal/new", data=legal_payload).status_code in {
        302,
        403,
    }
    legal_payload.pop("csrf_token")
    assert admin.post("/admin/legal/new", data=legal_payload).status_code == 403
    assert legal_marker not in admin.get("/admin/legal").get_data(as_text=True)

    rule_marker = "task22-forbidden-rule"
    assert rule_marker not in admin.get("/admin/rules").get_data(as_text=True)
    assert admin.post(
        "/admin/rules/copy", data={"code": rule_marker, "name": "forbidden"}
    ).status_code == 403
    assert admin.post(
        "/admin/rules/copy",
        data={
            "csrf_token": CSRF,
            "code": rule_marker,
            "name": "forbidden",
            "unexpected": "x",
        },
    ).status_code == 400
    assert rule_marker not in admin.get("/admin/rules").get_data(as_text=True)

    leads_before = admin.get("/admin/leads").data
    assert admin.post(
        "/admin/leads/export",
        data={
            "status": "",
            "branch": "",
            "date_from": "",
            "date_to": "",
            "queue": "ordinary",
            "q": "",
        },
    ).status_code == 403
    assert admin.get("/admin/leads").data == leads_before
