"""Published service packages preserve frozen V2 delivery authority."""

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import sqlite3
import uuid

from bs4 import BeautifulSoup
import pytest

import catalog_content_repository as catalog
from content_clock import SHANGHAI
from content_contracts import CaseMetric, ContentBlock, ContentDraft, ContentRelation
from content_validation import ContentValidationError, validate_content_draft
from pagination import PageRequest
from publishing_service import (
    archive_content,
    copy_revision,
    create_content_draft,
    publish_content,
    publish_due_content,
    schedule_content,
)


NOW = datetime(2026, 8, 24, 10, 0, 0, tzinfo=SHANGHAI)
NOW_TEXT = "2026-08-24 10:00:00"
SERVICE_REQUIRED_SECTIONS = {
    "industries", "departments", "maturity", "pains", "scope",
    "not-included", "deliverables", "implementation-steps",
    "prerequisites", "timeline", "budget", "acceptance", "support",
    "related-content", "pricing-disclaimer",
}
SERVICE_MATURITY = {
    "foundation_workshop": ("explore",),
    "knowledge_assistant_pilot": ("explore", "pilot", "scale"),
    "customer_growth_pilot": ("explore", "pilot", "scale"),
    "workflow_automation": ("explore", "pilot", "scale"),
    "data_insight": ("pilot", "scale", "collaborate"),
    "industry_integration": ("pilot", "scale", "collaborate"),
}
SERVICE_FACETS = {
    "foundation_workshop": {
        "industries": (
            ("manufacturing", "制造业"), ("retail", "零售电商"),
            ("professional_knowledge", "知识型专业服务"),
            ("software_creative", "软件与创意服务"),
        ),
        "departments": (
            ("production", "生产"), ("merchandising", "商品运营"),
            ("delivery", "项目交付"), ("product_delivery", "产品与交付"),
            ("quality", "质量"), ("store_operations", "门店运营"),
            ("knowledge_research", "知识研究"), ("design_content", "设计与内容"),
            ("equipment", "设备"), ("supply_chain", "供应链"),
            ("client_growth", "客户增长"), ("engineering", "工程研发"),
            ("marketing", "市场营销"), ("contracts_risk", "合同与风险"),
            ("marketing_sales", "市场与销售"), ("sales_service", "销售与服务"),
            ("customer_service", "客户服务"), ("operations", "运营管理"),
            ("customer_success", "客户成功"), ("finance_hr", "财务与人力"),
            ("people", "人才管理"),
        ),
        "pains": (),
    },
    "knowledge_assistant_pilot": {
        "industries": (
            ("manufacturing", "制造业"),
            ("professional_knowledge", "知识型专业服务"),
            ("software_creative", "软件与创意服务"),
        ),
        "departments": (
            ("production", "生产"), ("delivery", "项目交付"),
            ("knowledge_research", "知识研究"), ("equipment", "设备"),
            ("engineering", "工程研发"), ("customer_success", "客户成功"),
            ("finance_hr", "财务与人力"), ("people", "人才管理"),
        ),
        "pains": (
            ("knowledge_search", "知识与资料检索"), ("document_search", "文档检索"),
            ("equipment_maintenance", "设备维护"), ("client_service", "客户服务"),
            ("customer_support", "客户支持"), ("knowledge_docs", "知识文档"),
            ("office_documents", "办公文档处理"), ("talent_knowledge", "人才与知识管理"),
        ),
    },
    "customer_growth_pilot": {
        "industries": (("retail", "零售电商"), ("software_creative", "软件与创意服务")),
        "departments": (
            ("merchandising", "商品运营"), ("store_operations", "门店运营"),
            ("design_content", "设计与内容"), ("marketing", "市场营销"),
            ("marketing_sales", "市场与销售"), ("customer_service", "客户服务"),
        ),
        "pains": (
            ("customer_service", "客户服务"), ("marketing_content", "营销内容"),
            ("content_creation", "内容创作"), ("member_operations", "会员运营"),
            ("pricing_selection", "选品与定价"), ("marketing_sales", "市场与销售"),
        ),
    },
    "workflow_automation": {
        "industries": (("professional_knowledge", "知识型专业服务"),),
        "departments": (
            ("delivery", "项目交付"), ("contracts_risk", "合同与风险"),
            ("operations", "运营管理"),
        ),
        "pains": (
            ("proposal_drafting", "方案撰写"), ("project_delivery", "项目交付"),
            ("contract_review", "合同审查"), ("billing_reconciliation", "账单与对账"),
        ),
    },
    "data_insight": {
        "industries": (("manufacturing", "制造业"), ("retail", "零售电商")),
        "departments": (
            ("production", "生产"), ("merchandising", "商品运营"),
            ("store_operations", "门店运营"), ("supply_chain", "供应链"),
        ),
        "pains": (
            ("production_reporting", "生产报表"),
            ("inventory_replenishment", "库存补货"), ("scheduling", "生产排程"),
            ("sales_analysis", "销售分析"), ("inventory_supply", "库存与供应"),
            ("supply_reconciliation", "供应链对账"),
        ),
    },
    "industry_integration": {
        "industries": (
            ("manufacturing", "制造业"),
            ("professional_knowledge", "知识型专业服务"),
            ("software_creative", "软件与创意服务"),
        ),
        "departments": (
            ("production", "生产"), ("delivery", "项目交付"),
            ("product_delivery", "产品与交付"), ("quality", "质量"),
            ("engineering", "工程研发"), ("operations", "运营管理"),
        ),
        "pains": (
            ("requirements", "需求管理"), ("quality_inspection", "质量检测"),
            ("project_delivery", "项目交付"), ("quality_review", "质量审查"),
            ("operations_analysis", "运营分析"),
        ),
    },
}


def _service_draft(*, maturity_codes=("explore",)):
    return ContentDraft(
        entry_type="service", slug="schema-service", title="服务架构验证",
        summary="验证服务修订的成熟度关系在持久化前完整受控。",
        seo_title="服务架构验证", seo_description="验证服务包成熟度只允许四个固定阶段且不能为空。",
        extension={"service_id": 1},
        blocks=(ContentBlock("rich_text", body_html="<p>服务说明</p>"),),
        maturity_codes=maturity_codes,
    )


def _page(response):
    assert response.status_code == 200
    return BeautifulSoup(response.data, "html.parser")


def _publish_scenario_content(db):
    db.execute(
        "UPDATE content_items SET status='published',published_at=? "
        "WHERE entry_type='scenario' AND status='draft'",
        (NOW_TEXT,),
    )
    db.commit()


def _service_item(db, code, status):
    return db.execute(
        "SELECT ci.*,g.service_id FROM content_items ci "
        "JOIN content_groups g ON g.id=ci.content_group_id "
        "JOIN services s ON s.id=g.service_id "
        "WHERE ci.entry_type='service' AND s.code=? AND ci.status=?",
        (code, status),
    ).fetchone()


def _related_case(slug, *, public_source=False):
    source_url = "https://example.com/verified-case" if public_source else None
    source_hash = hashlib.sha256(source_url.encode()).hexdigest() if source_url else None
    return ContentDraft(
        entry_type="case",
        slug=slug,
        title=f"已验证案例 {slug}",
        summary="用于服务关联完整性验证的真实案例。",
        seo_title=f"已验证案例 {slug}",
        seo_description="验证服务页只能关联当前仍符合公开规则的案例。",
        extension={
            "verification_code": "public_verified" if public_source else "authorized_anonymous",
            "is_anonymized": 0 if public_source else 1,
            "basis_type": "public_source" if public_source else "internal_delivery_record",
            "private_basis_reference": None if public_source else "service-case-record-001",
            "source_url": source_url,
            "source_url_sha256": source_hash,
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "is_verified": 1,
            "review_confirmed": 1,
            "verified_at": "2026-08-24 09:00:00",
        },
        blocks=(ContentBlock("rich_text", body_html="<p>已脱敏的实施过程。</p>"),),
        metrics=(
            CaseMetric(
                "处理时间", "8", "2", "小时", "连续 30 天", "经脱敏交付记录核验。"
            ),
        ),
    )


def _publish_related_case(db, slug, *, public_source=False):
    content_id = create_content_draft(
        _related_case(slug, public_source=public_source), actor="test-admin", now=NOW
    )
    if public_source:
        source_hash = hashlib.sha256(b"https://example.com/verified-case").hexdigest()
        db.execute(
            "UPDATE case_content SET source_check_code='https_ok',source_checked_at=?,"
            "source_check_expires_at='2099-01-01 00:00:00',source_check_url_sha256=? "
            "WHERE content_item_id=?",
            (NOW_TEXT, source_hash, content_id),
        )
        db.commit()
    publish_content(content_id, 1, actor="test-admin", now=NOW)
    return db.execute(
        "SELECT * FROM content_items WHERE id=?", (content_id,)
    ).fetchone()


def _attach_service_case(db, service_content_id, case_group_id):
    db.execute(
        "INSERT INTO service_cases "
        "(service_content_item_id,case_content_group_id,sort_order) VALUES (?,?,0)",
        (service_content_id, case_group_id),
    )
    db.commit()


def _force_legacy_case_basis(db, content_id):
    trigger_sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='protect_case_content_update'"
    ).fetchone()[0]
    db.execute("DROP TRIGGER protect_case_content_update")
    db.execute(
        "UPDATE case_content SET basis_type='private_authorization' "
        "WHERE content_item_id=?",
        (content_id,),
    )
    db.execute(trigger_sql)
    db.commit()


def _publish_service(db, code):
    item = _service_item(db, code, "draft")
    assert item is not None
    publish_content(item["id"], item["lock_version"], actor="test-admin", now=NOW)
    return _service_item(db, code, "published")


class _InterleavingCursor:
    def __init__(self, cursor, after_fetch):
        self._cursor = cursor
        self._after_fetch = after_fetch

    def _fetched(self, value):
        callback, self._after_fetch = self._after_fetch, None
        if callback is not None:
            callback()
        return value

    def fetchone(self):
        return self._fetched(self._cursor.fetchone())

    def fetchall(self):
        return self._fetched(self._cursor.fetchall())


class _InterleavingReadConnection:
    """Wrap a real SQLite reader and replace content after its first read."""

    def __init__(self, connection, replace_after_first_fetch):
        self._connection = connection
        self._replace_after_first_fetch = replace_after_first_fetch
        self._first_read_wrapped = False
        self._begin_seen = False
        self.begin_before_first_read = False

    def execute(self, sql, parameters=()):
        statement = sql.strip().upper()
        if statement == "BEGIN":
            self._begin_seen = True
        cursor = self._connection.execute(sql, parameters)
        if statement.startswith("SELECT") and not self._first_read_wrapped:
            self._first_read_wrapped = True
            self.begin_before_first_read = self._begin_seen
            return _InterleavingCursor(cursor, self._replace_after_first_fetch)
        return cursor

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()


@pytest.fixture()
def published_services(client, db):
    _publish_scenario_content(db)
    for code in SERVICE_MATURITY:
        _publish_service(db, code)
    return client


def test_008_migration_allows_exact_service_owner_and_seed_is_explicit(db):
    versions = tuple(row[0] for row in db.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ))
    assert "008_service_content_maturity" in versions
    assert versions[-1] == "009_case_basis_types"

    actual = {}
    for code in SERVICE_MATURITY:
        item = _service_item(db, code, "draft")
        actual[code] = tuple(row[0] for row in db.execute(
            "SELECT maturity_code FROM content_maturity_levels "
            "WHERE content_item_id=? ORDER BY sort_order,maturity_code", (item["id"],)
        ))
    assert actual == SERVICE_MATURITY

    service = _service_item(db, "foundation_workshop", "draft")
    db.execute("DELETE FROM content_maturity_levels WHERE content_item_id=?", (service["id"],))
    db.execute(
        "INSERT INTO content_maturity_levels (content_item_id,maturity_code,sort_order) "
        "VALUES (?,?,?)", (service["id"], "explore", 0),
    )
    industry_id = db.execute(
        "SELECT ci.id FROM content_items ci WHERE ci.entry_type='industry' "
        "AND ci.status='draft' ORDER BY ci.id LIMIT 1"
    ).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="maturity level owner"):
        db.execute(
            "INSERT INTO content_maturity_levels (content_item_id,maturity_code,sort_order) "
            "VALUES (?,?,?)", (industry_id, "explore", 0),
        )


def test_validation_requires_nonempty_exact_service_maturity():
    validated = validate_content_draft(
        _service_draft(maturity_codes=("explore", "pilot", "scale", "collaborate"))
    )
    assert validated.maturity_codes == ("explore", "pilot", "scale", "collaborate")

    for maturity_codes in ((), ("explore", "explore"), ("optimize",)):
        with pytest.raises(ContentValidationError) as error:
            validate_content_draft(_service_draft(maturity_codes=maturity_codes))
        assert error.value.code == "maturity_invalid"


def test_service_list_uses_page_contract_shell_canonical_and_compatibility_redirect(
    published_services,
):
    response = published_services.get("/service-packages")
    document = _page(response)
    projection = catalog.public_services(PageRequest(1, 20), NOW)
    assert tuple(item.code for item in projection.items) == tuple(SERVICE_MATURITY)
    assert len(document.select("[data-service-card]")) == len(SERVICE_MATURITY)
    assert document.select("[data-service-code]") == []
    for code in SERVICE_MATURITY:
        assert code not in response.get_data(as_text=True)
    assert document.select_one('link[rel="canonical"]')["href"] == "https://test.example/service-packages"
    assert document.select_one('body[data-analytics-page="services"]') is not None
    assert response.headers["Cache-Control"] == "private, no-store"
    compatibility = published_services.get("/services")
    assert compatibility.status_code == 301
    assert compatibility.headers["Location"].endswith("/service-packages")


def test_every_public_service_detail_has_complete_delivery_structure_and_ctas(
    published_services,
):
    for code in SERVICE_MATURITY:
        slug = code.replace("_", "-")
        response = published_services.get(f"/service-packages/{slug}")
        document = _page(response)
        assert SERVICE_REQUIRED_SECTIONS <= {
            node["data-service-section"] for node in document.select("[data-service-section]")
        }
        assert document.select_one('link[rel="canonical"]')["href"] == (
            f"https://test.example/service-packages/{slug}"
        )
        assert document.select_one('[data-service-cta="primary"][href="/assessment"]') is not None
        assert document.select_one('[data-service-cta="secondary"][href="/cases"]') is not None
        assert response.headers["Cache-Control"] == "private, no-store"
        assert document.select_one('body[data-analytics-page="services"]') is not None


@pytest.mark.parametrize("surface", ("list", "detail"))
def test_public_service_reads_one_sqlite_snapshot_during_concurrent_replacement(
    published_services, db, monkeypatch, surface,
):
    current = _service_item(db, "foundation_workshop", "published")
    revision_id = copy_revision(current["id"], actor="test-admin", now=NOW)
    replacement_title = "并发替换后的 AI 就绪基础工作坊"
    db.execute(
        "UPDATE content_items SET title=? WHERE id=?",
        (replacement_title, revision_id),
    )
    service = db.execute(
        "SELECT min_budget,max_budget FROM services WHERE code='foundation_workshop'"
    ).fetchone()
    old_budget = (service["min_budget"], service["max_budget"])
    new_budget = (service["min_budget"] + 1000, service["max_budget"])
    db.commit()

    original_get_db = catalog.models.get_db

    def replace_revision_and_authority():
        writer = original_get_db()
        try:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute(
                "UPDATE services SET min_budget=? WHERE code='foundation_workshop'",
                (new_budget[0],),
            )
            writer.execute(
                "UPDATE content_items SET status='archived',archived_at=?,"
                "lock_version=lock_version+1,updated_at=? "
                "WHERE id=? AND status='published'",
                (NOW_TEXT, NOW_TEXT, current["id"]),
            )
            writer.execute(
                "UPDATE content_items SET status='published',published_at=?,"
                "lock_version=lock_version+1,updated_at=? "
                "WHERE id=? AND status='draft'",
                (NOW_TEXT, NOW_TEXT, revision_id),
            )
            writer.commit()
        finally:
            writer.close()

    interleaved = _InterleavingReadConnection(
        original_get_db(), replace_revision_and_authority
    )
    monkeypatch.setattr(catalog.models, "get_db", lambda: interleaved)
    if surface == "list":
        page = catalog.public_services(PageRequest(1, 20), NOW)
        first_projection = next(
            item for item in page.items if item.code == "foundation_workshop"
        )
        first_pair = (first_projection.title, first_projection.budget)
    else:
        first_projection = catalog.public_service("foundation-workshop", NOW)
        assert first_projection is not None
        first_pair = (first_projection["title"], first_projection["budget"])

    assert interleaved.begin_before_first_read is True
    assert first_pair == (current["title"], old_budget)

    monkeypatch.setattr(catalog.models, "get_db", original_get_db)
    if surface == "list":
        page = catalog.public_services(PageRequest(1, 20), NOW)
        later_projection = next(
            item for item in page.items if item.code == "foundation_workshop"
        )
        later_pair = (later_projection.title, later_projection.budget)
    else:
        later_projection = catalog.public_service("foundation-workshop", NOW)
        assert later_projection is not None
        later_pair = (later_projection["title"], later_projection["budget"])
    assert later_pair == (replacement_title, new_budget)


def test_service_projection_hides_a_persisted_legacy_case_relation(db):
    _publish_scenario_content(db)
    target = _publish_related_case(db, "service-legacy-target")
    service = _service_item(db, "foundation_workshop", "draft")
    _attach_service_case(db, service["id"], target["content_group_id"])
    publish_content(service["id"], service["lock_version"], actor="test-admin", now=NOW)
    _force_legacy_case_basis(db, target["id"])

    projection = catalog.public_service("foundation-workshop", NOW)

    assert projection is not None
    assert projection["cases"] == ()


@pytest.mark.parametrize(
    ("offset", "visible"),
    (
        (timedelta(days=7) - timedelta(seconds=1), True),
        (timedelta(days=7), True),
        (timedelta(days=7) + timedelta(seconds=1), False),
    ),
)
def test_service_related_public_source_uses_the_exact_seven_day_boundary(
    db, offset, visible
):
    _publish_scenario_content(db)
    target = _publish_related_case(
        db, "service-source-freshness-target", public_source=True
    )
    service = _service_item(db, "foundation_workshop", "draft")
    _attach_service_case(db, service["id"], target["content_group_id"])
    publish_content(service["id"], service["lock_version"], actor="test-admin", now=NOW)

    projection = catalog.public_service("foundation-workshop", NOW + offset)

    assert projection is not None
    assert tuple(case["slug"] for case in projection["cases"]) == (
        (target["slug"],) if visible else ()
    )


@pytest.mark.parametrize("invalid_target", ("stale_source", "legacy_basis"))
def test_service_immediate_relation_publish_rechecks_case_completeness_atomically(
    db, invalid_target
):
    _publish_scenario_content(db)
    target = _publish_related_case(
        db,
        f"service-immediate-{invalid_target.replace('_', '-')}-target",
        public_source=invalid_target == "stale_source",
    )
    if invalid_target == "legacy_basis":
        _force_legacy_case_basis(db, target["id"])
    old = _publish_service(db, "foundation_workshop")
    replacement_id = copy_revision(old["id"], actor="test-admin", now=NOW)
    _attach_service_case(db, replacement_id, target["content_group_id"])
    publish_at = (
        NOW + timedelta(days=7, seconds=1)
        if invalid_target == "stale_source"
        else NOW
    )

    with pytest.raises(ContentValidationError) as error:
        publish_content(
            replacement_id,
            1,
            actor="test-admin",
            now=publish_at,
        )

    assert error.value.code == "relation_target_not_published"
    assert _service_item(db, "foundation_workshop", "published")["id"] == old["id"]
    assert _service_item(db, "foundation_workshop", "draft")["id"] == replacement_id
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_published'",
        (replacement_id,),
    ).fetchone()[0] == 0


@pytest.mark.parametrize("invalid_target", ("stale_source", "legacy_basis"))
def test_service_due_relation_publish_rechecks_case_completeness_and_isolates(
    db, invalid_target
):
    _publish_scenario_content(db)
    target = _publish_related_case(
        db,
        f"service-due-{invalid_target.replace('_', '-')}-target",
        public_source=invalid_target == "stale_source",
    )
    old = _publish_service(db, "foundation_workshop")
    replacement_id = copy_revision(old["id"], actor="test-admin", now=NOW)
    _attach_service_case(db, replacement_id, target["content_group_id"])
    due = (
        NOW + timedelta(days=7, seconds=1)
        if invalid_target == "stale_source"
        else NOW + timedelta(hours=1)
    )
    schedule_content(replacement_id, 1, due, actor="test-admin", now=NOW)
    if invalid_target == "legacy_basis":
        _force_legacy_case_basis(db, target["id"])

    result = publish_due_content(now=due)

    assert result.published_ids == ()
    assert result.failures == ((replacement_id, "validation_failed"),)
    assert _service_item(db, "foundation_workshop", "published")["id"] == old["id"]
    assert _service_item(db, "foundation_workshop", "draft")["id"] == replacement_id
    assert db.execute(
        "SELECT details_json FROM content_audit_events WHERE content_item_id=? "
        "AND event_code='content_due_failed'",
        (replacement_id,),
    ).fetchone()[0] == '{"reason_code":"validation_failed"}'


def test_six_services_project_exact_codes_but_render_only_ordered_chinese_facets(
    published_services,
):
    maturity_labels = {
        "explore": "探索", "pilot": "试点", "scale": "规模化", "collaborate": "协同",
    }
    for code, expected in SERVICE_FACETS.items():
        response = published_services.get(f"/service-packages/{code.replace('_', '-')}")
        document = _page(response)
        projection = catalog.public_service(code.replace("_", "-"), NOW)
        assert projection is not None
        for facet in ("industries", "departments", "pains"):
            assert tuple(
                (item.code, item.label) for item in projection[facet]
            ) == expected[facet]
            nodes = document.select(
                f'[data-service-section="{facet}"] [data-service-facet]'
            )
            assert tuple(node.get_text(strip=True) for node in nodes) == tuple(
                label for _, label in expected[facet]
            )
        assert tuple(
            (item.code, item.label) for item in projection["maturity"]
        ) == tuple((value, maturity_labels[value]) for value in SERVICE_MATURITY[code])
        maturity = document.select(
            '[data-service-section="maturity"] [data-service-maturity]'
        )
        assert tuple(
            node.get_text(strip=True) for node in maturity
        ) == tuple(maturity_labels[value] for value in SERVICE_MATURITY[code])
        assert document.select(
            "[data-service-code],[data-facet-code],[data-maturity-code],"
            "[data-integration-code],[data-deliverable-code]"
        ) == []
        raw_codes = {
            projection["code"],
            *(item.code for item in projection["industries"]),
            *(item.code for item in projection["departments"]),
            *(item.code for item in projection["pains"]),
            *(item.code for item in projection["maturity"]),
            *(item.code for item in projection["integration"]),
            *(item.code for item in projection["deliverables"]),
            *(item.code for item in projection["scenarios"]),
        }
        html = response.get_data(as_text=True)
        for raw_code in raw_codes:
            if "_" in raw_code or ":" in raw_code:
                assert raw_code not in html
        assert "_json" not in html.lower()
        assert '["' not in html
        if not expected["pains"]:
            empty = document.select_one('[data-service-section="pains"] [data-empty-state]')
            assert empty is not None
            assert empty.get_text(strip=True) == "暂无特定痛点限制"


def test_service_detail_formats_budget_weeks_fixed_labels_and_no_raw_values(
    published_services,
):
    expected = {
        "foundation_workshop": ("20,000—50,000 元", "2—4 周", "基础准备", ("低",)),
        "knowledge_assistant_pilot": ("50,000—100,000 元", "4—8 周", "试点验证", ("低", "中")),
        "customer_growth_pilot": ("80,000—150,000 元", "4—10 周", "试点验证", ("低", "中")),
        "workflow_automation": ("100,000—200,000 元", "6—12 周", "标准交付", ("低", "中")),
        "data_insight": ("100,000—250,000 元", "8—16 周", "标准交付", ("中", "高")),
        "industry_integration": ("200,000—500,000 元", "12—24 周", "集成交付", ("高",)),
    }
    for code, (budget, weeks, category, integration) in expected.items():
        document = _page(published_services.get(f"/service-packages/{code.replace('_', '-')}"))
        assert document.select_one('[data-service-section="budget"]').get_text(" ", strip=True).endswith(budget)
        assert document.select_one('[data-service-section="timeline"]').get_text(" ", strip=True).endswith(weeks)
        assert document.select_one("[data-service-category]").get_text(strip=True) == category
        projection = catalog.public_service(code.replace("_", "-"), NOW)
        assert projection is not None
        assert tuple(item.code for item in projection["integration"]) == tuple(
            {"低": "low", "中": "medium", "高": "high"}[label]
            for label in integration
        )
        assert tuple(
            node.get_text(strip=True) for node in document.select("[data-service-integration]")
        ) == integration
        visible = document.get_text(" ", strip=True)
        assert code not in visible
        assert "_json" not in visible.lower()
        assert "[\"" not in visible


def test_delivery_authority_fields_and_optional_relations_render_without_placeholders(
    published_services,
):
    document = _page(published_services.get("/service-packages/foundation-workshop"))
    projection = catalog.public_service("foundation-workshop", NOW)
    assert projection is not None
    assert tuple(item.code for item in projection["deliverables"]) == tuple(
        f"foundation_workshop:{index}" for index in range(1, 6)
    )
    assert [node.get_text(strip=True) for node in document.select("[data-service-deliverable]")] == [
        "流程现状基线", "数据清单", "场景优先级矩阵", "90 天计划", "工作坊报告",
    ]
    assert "定制软件开发" in document.select_one('[data-service-section="not-included"]').get_text()
    assert "负责人书面确认" in document.select_one('[data-service-section="acceptance"]').get_text()
    assert "15 天" in document.select_one('[data-service-section="support"]').get_text()
    assert document.select('[data-related-kind="case"]') == []
    assert document.select('[data-related-kind="resource"]') == []
    assert document.select('[data-related-kind="scenario"]') == []
    related = document.select_one('[data-service-section="related-content"]')
    assert related.has_attr("hidden")
    assert related.get_text(" ", strip=True) == ""
    assert "关联内容" not in document.get_text(" ", strip=True)
    assert "最终范围和报价以需求确认结果为准" in document.select_one(
        '[data-service-section="pricing-disclaimer"]'
    ).get_text()


def test_service_hides_related_scenario_when_scenario_page_is_incomplete(
    client, db,
):
    current = _publish_service(db, "foundation_workshop")

    document = _page(client.get(f"/service-packages/{current['slug']}"))
    related = document.select('[data-related-kind="scenario"]')
    assert related == []
    assert "关联场景" not in document.get_text(" ", strip=True)
    assert "data_process_foundation" not in document.get_text(" ", strip=True)
    assert client.get("/scenarios/data-process-foundation").status_code == 404


def test_draft_future_archived_and_missing_service_details_are_private_404(client, db):
    draft = _service_item(db, "knowledge_assistant_pilot", "draft")
    assert client.get(f"/service-packages/{draft['slug']}").status_code == 404
    future = _service_item(db, "customer_growth_pilot", "draft")
    db.execute(
        "UPDATE content_items SET status='published',published_at=?,publish_at=? WHERE id=?",
        (NOW_TEXT, "2030-01-01 00:00:00", future["id"]),
    )
    db.commit()
    assert client.get(f"/service-packages/{future['slug']}").status_code == 404
    assert client.get("/service-packages/not-a-service").status_code == 404
    _publish_scenario_content(db)
    published = _publish_service(db, "foundation_workshop")
    assert client.get(f"/service-packages/{published['slug']}").status_code == 200
    archive_content(published["id"], published["lock_version"], actor="test-admin", now=NOW)
    assert client.get(f"/service-packages/{published['slug']}").status_code == 404


def test_service_authority_injection_never_falls_back_to_mutable_core_tables(db):
    _publish_scenario_content(db)
    current = _publish_service(db, "foundation_workshop")
    authority = catalog._service_authority(db, current["service_id"], NOW)
    injected = replace(
        authority,
        min_budget=12345,
        max_budget=67890,
        scenarios=(
            replace(
                authority.scenarios[0],
                title="快照权威场景",
                slug="snapshot-authority-scenario",
            ),
        ),
    )
    db.execute("DELETE FROM scenario_services WHERE service_id=?", (current["service_id"],))
    db.execute(
        "UPDATE services SET min_budget=1,max_budget=1 WHERE id=?", (current["service_id"],)
    )
    db.commit()

    projection = catalog.public_service(current["slug"], NOW, authority=injected)
    assert projection is not None
    assert projection["budget"] == (12345, 67890)
    assert projection["scenarios"] == injected.scenarios
    assert catalog.public_service(
        current["slug"], NOW, authority=replace(injected, industries=())
    ) is None


def test_malformed_injected_service_authority_fails_closed_without_type_leak(db):
    _publish_scenario_content(db)
    current = _publish_service(db, "foundation_workshop")
    authority = catalog._service_authority(db, current["service_id"], NOW)

    malformed_authorities = (
        replace(authority, deliverables=(object(),)),
        replace(authority, category_code=[]),
        replace(
            authority,
            deliverables=(replace(authority.deliverables[0], code=[]),),
        ),
        replace(
            authority,
            scenarios=(replace(authority.scenarios[0], integration_code=[]),),
        ),
    )
    for malformed in malformed_authorities:
        assert catalog.public_service(
            current["slug"], NOW, authority=malformed
        ) is None


def test_top_level_malformed_service_authority_injection_fails_closed(db):
    _publish_scenario_content(db)
    current = _publish_service(db, "foundation_workshop")
    authority = catalog._service_authority(db, current["service_id"], NOW)

    malformed_authorities = (
        object(),
        {},
        replace(authority, service_id=[]),
    )
    for malformed in malformed_authorities:
        assert catalog.public_service(
            current["slug"], NOW, authority=malformed
        ) is None


def test_service_list_omits_one_invalid_authority_without_hiding_healthy_services(
    published_services, db,
):
    invalid = _service_item(db, "foundation_workshop", "published")
    healthy = _service_item(db, "knowledge_assistant_pilot", "published")
    db.execute(
        "UPDATE service_deliverables SET description=' ' "
        "WHERE id=(SELECT MIN(id) FROM service_deliverables WHERE service_id=?)",
        (invalid["service_id"],),
    )
    db.commit()

    response = published_services.get("/service-packages")
    document = _page(response)
    titles = tuple(
        node.get_text(strip=True) for node in document.select("[data-service-card] h2")
    )

    assert response.status_code == 200
    assert healthy["title"] in titles
    assert invalid["title"] not in titles
    assert published_services.get(
        f"/service-packages/{invalid['slug']}"
    ).status_code == 404
    assert published_services.get(
        f"/service-packages/{healthy['slug']}"
    ).status_code == 200


def test_service_list_empty_and_archived_lifecycle_remains_available(client, db):
    empty = _page(client.get("/service-packages"))
    assert empty.select("[data-service-card]") == []
    assert "暂无已发布服务包" in empty.get_text(" ", strip=True)
    assert empty.select_one('[data-empty-state].ui-empty-state') is not None

    _publish_scenario_content(db)
    published = _publish_service(db, "foundation_workshop")
    available = _page(client.get("/service-packages"))
    assert tuple(
        node.get_text(strip=True)
        for node in available.select("[data-service-card] h2")
    ) == (published["title"],)

    archive_content(
        published["id"], published["lock_version"], actor="test-admin", now=NOW
    )
    archived = _page(client.get("/service-packages"))
    assert archived.select("[data-service-card]") == []
    assert "暂无已发布服务包" in archived.get_text(" ", strip=True)
    assert archived.select_one('[data-empty-state].ui-empty-state') is not None
    assert client.get(
        f"/service-packages/{published['slug']}"
    ).status_code == 404


def _corrupt_service_dependency(db, current, draft_id, source):
    service_id = current["service_id"]
    if source == "maturity":
        db.execute("DELETE FROM content_maturity_levels WHERE content_item_id=?", (draft_id,))
    elif source == "related_scenario":
        db.execute("DELETE FROM scenario_services WHERE service_id=?", (service_id,))
    elif source == "industry":
        db.execute(
            "UPDATE industry_branches SET status='archived' WHERE id IN ("
            "SELECT sb.industry_branch_id FROM scenario_services ss "
            "JOIN scenario_branches sb ON sb.scenario_id=ss.scenario_id WHERE ss.service_id=?)",
            (service_id,),
        )
    elif source == "department":
        db.execute(
            "UPDATE departments SET status='archived' WHERE id IN ("
            "SELECT sd.department_id FROM scenario_services ss "
            "JOIN scenario_departments sd ON sd.scenario_id=ss.scenario_id WHERE ss.service_id=?)",
            (service_id,),
        )
    elif source == "scenario_name":
        db.execute(
            "UPDATE scenarios SET public_name=' ' WHERE id IN ("
            "SELECT scenario_id FROM scenario_services WHERE service_id=?)",
            (service_id,),
        )
    elif source == "deliverables":
        db.execute("UPDATE service_deliverables SET status='archived' WHERE service_id=?", (service_id,))
    elif source == "deliverable_title":
        db.execute(
            "UPDATE service_deliverables SET title=' ' WHERE id=(SELECT MIN(id) FROM service_deliverables WHERE service_id=?)",
            (service_id,),
        )
    elif source == "deliverable_code":
        db.execute(
            "UPDATE service_deliverables SET code=' ' WHERE id=(SELECT MIN(id) FROM service_deliverables WHERE service_id=?)",
            (service_id,),
        )
    elif source == "deliverable_description":
        db.execute(
            "UPDATE service_deliverables SET description=' ' WHERE id=(SELECT MIN(id) FROM service_deliverables WHERE service_id=?)",
            (service_id,),
        )
    elif source == "scenario_code":
        db.execute(
            "UPDATE scenarios SET code=' ' WHERE id=("
            "SELECT MIN(scenario_id) FROM scenario_services WHERE service_id=?)",
            (service_id,),
        )
    elif source == "scenario_integration":
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute(
            "UPDATE scenarios SET integration_level='unknown' WHERE id=("
            "SELECT MIN(scenario_id) FROM scenario_services WHERE service_id=?)",
            (service_id,),
        )
    elif source in {
        "industry_code", "industry_name", "department_code", "department_name",
        "pain_code", "pain_name",
    }:
        kind, column = source.split("_", 1)
        table, link_table, target_column, scenario_link = {
            "industry": ("industries", "industry_branches", "industry_id", "scenario_branches"),
            "department": ("departments", "scenario_departments", "department_id", "scenario_departments"),
            "pain": ("pain_points", "scenario_pains", "pain_point_id", "scenario_pains"),
        }[kind]
        if kind == "industry":
            target_sql = (
                "SELECT branch.industry_id FROM scenario_services service_link "
                "JOIN scenario_branches scenario_link "
                "ON scenario_link.scenario_id=service_link.scenario_id "
                "JOIN industry_branches branch ON branch.id=scenario_link.industry_branch_id "
                "WHERE service_link.service_id=? ORDER BY branch.id LIMIT 1"
            )
        else:
            target_sql = (
                f"SELECT scenario_link.{target_column} FROM scenario_services service_link "
                f"JOIN {scenario_link} scenario_link "
                "ON scenario_link.scenario_id=service_link.scenario_id "
                "WHERE service_link.service_id=? ORDER BY scenario_link.rowid LIMIT 1"
            )
        db.execute(
            f"UPDATE {table} SET {column}=' ' WHERE id=({target_sql})",
            (service_id,),
        )
    else:
        column, value = {
            "service_code": ("code", " "), "name": ("public_name", " "),
            "category": ("category", "unknown"),
            "budget": ("max_budget", 1), "weeks": ("max_weeks", 1),
            "steps": ("implementation_steps_json", "[]"),
            "prerequisites": ("prerequisites_json", "[]"),
            "exclusions": ("not_included_json", "[]"),
            "acceptance": ("acceptance_json", "[]"),
            "support": ("support_days", 0), "support_text": ("support_description", " "),
            "disclaimer": ("public_disclaimer", " "),
        }[source]
        db.execute(f"UPDATE services SET {column}=? WHERE id=?", (value, service_id))
    db.commit()


@pytest.mark.parametrize("source", (
    "related_scenario", "industry", "department", "scenario_name", "deliverables",
    "deliverable_code", "deliverable_title", "deliverable_description",
    "service_code", "scenario_code", "scenario_integration",
    "industry_code", "industry_name", "department_code", "department_name",
    "pain_code", "pain_name", "name", "category", "budget", "weeks", "steps",
    "prerequisites", "exclusions", "acceptance", "support", "support_text", "disclaimer",
))
def test_formal_service_publish_rejects_invalid_shared_authority_without_replacing_revision(
    client, db, source,
):
    _publish_scenario_content(db)
    service_code = (
        "knowledge_assistant_pilot" if source.startswith("pain_")
        else "foundation_workshop"
    )
    current = _publish_service(db, service_code)
    revision_id = copy_revision(current["id"], actor="test-admin", now=NOW)
    _corrupt_service_dependency(db, current, revision_id, source)

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, 1, actor="test-admin", now=NOW + timedelta(minutes=1))
    assert error.value.code == "service_public_incomplete"
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "published"
    revision = db.execute(
        "SELECT status,lock_version,publish_at FROM content_items WHERE id=?", (revision_id,)
    ).fetchone()
    assert tuple(revision) == ("draft", 1, None)
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events WHERE content_item_id=? AND event_code='content_published'",
        (revision_id,),
    ).fetchone()[0] == 0
    assert client.get(f"/service-packages/{current['slug']}").status_code == 404


def test_revision_local_maturity_failure_keeps_old_public_service_online(client, db):
    _publish_scenario_content(db)
    current = _publish_service(db, "foundation_workshop")
    revision_id = copy_revision(current["id"], actor="test-admin", now=NOW)
    db.execute("DELETE FROM content_maturity_levels WHERE content_item_id=?", (revision_id,))
    db.commit()

    with pytest.raises(ContentValidationError) as error:
        publish_content(revision_id, 1, actor="test-admin", now=NOW + timedelta(minutes=1))

    assert error.value.code == "service_public_incomplete"
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (current["id"],)
    ).fetchone()[0] == "published"
    assert tuple(db.execute(
        "SELECT status,lock_version,publish_at FROM content_items WHERE id=?",
        (revision_id,),
    ).fetchone()) == ("draft", 1, None)
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events "
        "WHERE content_item_id=? AND event_code='content_published'",
        (revision_id,),
    ).fetchone()[0] == 0
    assert client.get(f"/service-packages/{current['slug']}").status_code == 200


def test_due_shared_authority_failure_does_not_replace_revision_or_write_success_audit(
    client, db,
):
    _publish_scenario_content(db)
    current = _publish_service(db, "foundation_workshop")
    revision_id = copy_revision(current["id"], actor="test-admin", now=NOW)
    due = NOW + timedelta(hours=1)
    schedule_content(revision_id, 1, due, actor="test-admin", now=NOW)
    _corrupt_service_dependency(db, current, revision_id, "deliverable_description")

    result = publish_due_content(actor="test-admin", now=due)

    assert result.published_ids == ()
    assert result.failures == ((revision_id, "validation_failed"),)
    assert db.execute(
        "SELECT status FROM content_items WHERE id=?", (current["id"],)
    ).fetchone()[0] == "published"
    assert tuple(db.execute(
        "SELECT status,publish_at FROM content_items WHERE id=?", (revision_id,)
    ).fetchone()) == ("draft", None)
    assert db.execute(
        "SELECT COUNT(*) FROM content_audit_events "
        "WHERE content_item_id=? AND event_code='content_published'",
        (revision_id,),
    ).fetchone()[0] == 0
    assert client.get(f"/service-packages/{current['slug']}").status_code == 404


def test_due_service_validation_failure_keeps_old_revision_and_has_no_success_audit(client, db):
    _publish_scenario_content(db)
    current = _publish_service(db, "foundation_workshop")
    revision_id = copy_revision(current["id"], actor="test-admin", now=NOW)
    due = NOW + timedelta(hours=1)
    schedule_content(revision_id, 1, due, actor="test-admin", now=NOW)
    db.execute("DELETE FROM content_maturity_levels WHERE content_item_id=?", (revision_id,))
    db.commit()

    result = publish_due_content(actor="test-admin", now=due)
    assert result.published_ids == ()
    assert result.failures == ((revision_id, "validation_failed"),)
    assert db.execute("SELECT status FROM content_items WHERE id=?", (current["id"],)).fetchone()[0] == "published"
    revision = db.execute(
        "SELECT status,publish_at FROM content_items WHERE id=?", (revision_id,)
    ).fetchone()
    assert tuple(revision) == ("draft", None)
    events = tuple(row[0] for row in db.execute(
        "SELECT event_code FROM content_audit_events WHERE content_item_id=? ORDER BY id", (revision_id,)
    ))
    assert "content_published" not in events
    assert events[-1] == "content_due_failed"
    assert client.get(f"/service-packages/{current['slug']}").status_code == 200


def _complete_assessment(client):
    client.application.config.update({
        "PRIVACY_PROCESSOR_NAME": "测试处理者",
        "PRIVACY_CONTACT": "privacy@example.invalid",
        "PRIVACY_POLICY_URL": "https://example.invalid/privacy",
    })
    config = client.get("/api/v2/assessment/config/manufacturing").get_json()
    response = client.post(
        "/api/v2/assessment/complete",
        json={
            "submission_key": str(uuid.uuid4()),
            "assessment": {
                "schema_version": "2.0",
                "profile": {
                    "branch_code": "manufacturing", "subbranch_code": "discrete_manufacturing",
                    "department_code": "production", "company_size_code": "50_200",
                    "pain_codes": ["production_reporting"],
                },
                "answers": {code: "level_3" for code in (
                    "business_value_frequency", "business_value_scope", "process_documentation",
                    "process_stability", "data_availability", "data_quality", "systems_foundation",
                    "systems_automation", "organization_owner", "organization_adoption",
                    "delivery_budget", "delivery_timeline",
                )},
                "roi_choices": {
                    "headcount": "6_20", "monthly_hours": "20_80",
                    "monthly_cost": "8000_15000", "loss_factor": "normal",
                    "budget": "50000_200000",
                },
            },
            "contact": {
                "company_name": "示例企业", "contact_name": "张先生", "phone": "13800138000",
                "email": "private@example.invalid", "wechat": "private-wechat",
            },
            "consent": {"accepted": True, "policy_version": "2026-08-19"},
            "attribution": {"source": "website_assessment"},
        },
        headers={"X-CSRF-Token": config["csrf_token"]},
    )
    assert response.status_code == 200
    return response.get_json()["assessment_id"]


def test_healthy_narrative_revision_replaces_public_service_without_changing_report_snapshot(
    published_services, db,
):
    assessment_id = _complete_assessment(published_services)
    raw_before = db.execute(
        "SELECT report_snapshot_json FROM assessments WHERE id=?", (assessment_id,)
    ).fetchone()[0]
    digest_before = hashlib.sha256(raw_before.encode("utf-8")).hexdigest()
    current = _service_item(db, "foundation_workshop", "published")
    revision_id = copy_revision(current["id"], actor="test-admin", now=NOW)
    db.execute(
        "UPDATE content_items SET title=?,summary=? WHERE id=?",
        ("更新后的 AI 就绪基础工作坊", "只更新叙事文案，不改动报告所需的服务权威字段。", revision_id),
    )
    db.commit()

    result = publish_content(revision_id, 1, actor="test-admin", now=NOW + timedelta(minutes=1))
    raw_after = db.execute(
        "SELECT report_snapshot_json FROM assessments WHERE id=?", (assessment_id,)
    ).fetchone()[0]
    assert result.archived_id == current["id"]
    assert hashlib.sha256(raw_after.encode("utf-8")).hexdigest() == digest_before
    document = _page(published_services.get("/service-packages/foundation-workshop"))
    assert document.h1.get_text(strip=True) == "更新后的 AI 就绪基础工作坊"
    assert "20,000—50,000 元" in document.get_text(" ", strip=True)
