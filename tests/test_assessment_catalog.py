import importlib
import json
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

import models


VERSION_CODE = "v2.0-2026-08-19"
DIMENSIONS = (
    "business_value",
    "process",
    "data",
    "systems",
    "organization",
    "delivery",
)

LEGACY_SERVICE_EXCLUSIONS = {
    "foundation_workshop": (
        "software development",
        "system integration",
        "data cleansing execution",
    ),
    "knowledge_assistant_pilot": (
        "source-document creation",
        "unrestricted internet answers",
        "custom core-system integration",
    ),
    "customer_growth_pilot": (
        "media spend",
        "guaranteed conversion results",
        "unapproved automated outreach",
    ),
    "workflow_automation": (
        "unstable processes",
        "unlisted system interfaces",
        "removal of manual fallback",
    ),
    "data_insight": (
        "source-system repair",
        "historical data reconstruction",
        "unagreed predictive models",
    ),
    "industry_integration": (
        "unlisted connectors",
        "production infrastructure procurement",
        "guaranteed business outcomes",
    ),
}

CHINESE_SERVICE_EXCLUSIONS = {
    "foundation_workshop": (
        "定制软件开发",
        "业务系统集成",
        "数据清洗实施",
    ),
    "knowledge_assistant_pilot": (
        "源文档编写与补录",
        "不受限制的互联网问答",
        "核心业务系统定制集成",
    ),
    "customer_growth_pilot": (
        "媒体投放费用",
        "转化效果承诺",
        "未经审批的自动外呼或触达",
    ),
    "workflow_automation": (
        "尚未稳定的业务流程改造",
        "未列明的系统接口",
        "取消人工兜底机制",
    ),
    "data_insight": (
        "源系统修复",
        "历史数据补建",
        "未约定的预测模型",
    ),
    "industry_integration": (
        "未列明的系统连接器",
        "生产环境基础设施采购",
        "业务结果承诺",
    ),
}


@pytest.fixture()
def catalog_db(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    return models.get_db()


def repository():
    return importlib.import_module("assessment_repository")


def insert_later_version_and_unrelated_service(db):
    db.execute(
        "INSERT INTO assessment_versions "
        "(code,name,status,published_at) VALUES (?,?,?,?)",
        ("v99.0-future", "Future", "published", "2099-01-01 00:00:00"),
    )
    db.execute(
        "INSERT INTO services "
        "(code,name,tier,category,public_name,min_budget,max_budget,min_weeks,"
        "max_weeks,implementation_steps_json,prerequisites_json,"
        "not_included_json,acceptance_json,support_days,status,sort_order) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "unrelated_published_service",
            "Unrelated",
            "assessment",
            "test",
            "Unrelated",
            1,
            2,
            1,
            2,
            '["step"]',
            '["prerequisite"]',
            '["excluded"]',
            '["acceptance"]',
            1,
            "published",
            999,
        ),
    )
    db.commit()


def test_v2_catalog_schema_preserves_queryable_relationships(catalog_db):
    tables = {
        row[0]
        for row in catalog_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {
        "company_sizes",
        "pain_points",
        "scenario_pains",
        "scenario_budget_options",
        "assessment_branch_weights",
    } <= tables

    department_columns = {
        row[1] for row in catalog_db.execute("PRAGMA table_info(departments)")
    }
    scenario_columns = {
        row[1] for row in catalog_db.execute("PRAGMA table_info(scenarios)")
    }
    service_columns = {
        row[1] for row in catalog_db.execute("PRAGMA table_info(services)")
    }
    scenario_service_targets = {
        row[2]
        for row in catalog_db.execute("PRAGMA foreign_key_list(scenario_services)")
    }

    assert "industry_id" in department_columns
    assert {
        "minimum_business_value",
        "minimum_process",
        "minimum_data",
        "minimum_systems",
        "minimum_organization",
        "minimum_delivery",
        "integration_level",
        "min_weeks",
        "max_weeks",
        "risk_codes_json",
        "fallback_only",
    } <= scenario_columns
    assert {
        "code",
        "public_name",
        "min_budget",
        "max_budget",
        "min_weeks",
        "max_weeks",
        "implementation_steps_json",
        "prerequisites_json",
        "not_included_json",
        "acceptance_json",
        "support_days",
        "support_description",
        "public_disclaimer",
        "status",
    } <= service_columns
    assert "services" in scenario_service_targets
    assert "service_deliverables" not in scenario_service_targets


def test_published_catalog_has_exact_questions_weights_reference_and_branch_choices(
    catalog_db,
):
    catalog_db.close()
    catalog = repository().load_published_catalog("manufacturing")

    assert catalog.version_code == VERSION_CODE
    assert catalog.subbranch_codes == (
        "discrete_manufacturing",
        "process_manufacturing",
        "equipment_manufacturing",
        "consumer_goods_manufacturing",
    )
    assert catalog.department_codes == (
        "production",
        "quality",
        "equipment",
        "supply_chain",
        "sales_service",
        "finance_hr",
    )
    assert catalog.pain_codes == (
        "knowledge_search",
        "quality_inspection",
        "equipment_maintenance",
        "production_reporting",
        "scheduling",
        "inventory_supply",
        "quotation_service",
        "office_documents",
    )
    assert [question.code for question in catalog.questions] == [
        "business_value_frequency",
        "business_value_scope",
        "process_documentation",
        "process_stability",
        "data_availability",
        "data_quality",
        "systems_foundation",
        "systems_automation",
        "organization_owner",
        "organization_adoption",
        "delivery_budget",
        "delivery_timeline",
    ]
    assert catalog.questions[0].prompt == "这个问题出现得有多频繁？"
    assert [option.code for option in catalog.questions[0].options] == [
        "level_0",
        "level_1",
        "level_2",
        "level_3",
    ]
    assert [option.score for option in catalog.questions[0].options] == [0, 1, 2, 3]
    assert catalog.branch_weights == {
        "manufacturing": dict(zip(DIMENSIONS, (20, 20, 20, 15, 10, 15))),
        "retail": dict(zip(DIMENSIONS, (25, 15, 20, 15, 10, 15))),
        "professional_knowledge": dict(
            zip(DIMENSIONS, (25, 20, 15, 10, 15, 15))
        ),
        "software_creative": dict(zip(DIMENSIONS, (25, 15, 15, 15, 15, 15))),
    }
    assert catalog.reference_lines["manufacturing"] == dict(
        zip(DIMENSIONS, (60, 55, 55, 50, 50, 55))
    )
    with pytest.raises(FrozenInstanceError):
        catalog.questions[0].prompt = "changed"


def test_published_choice_codes_have_exact_chinese_labels(catalog_db):
    expected = {
        "manufacturing": {
            "subbranches": {
                "discrete_manufacturing": "离散制造",
                "process_manufacturing": "流程制造",
                "equipment_manufacturing": "装备制造",
                "consumer_goods_manufacturing": "消费品制造",
            },
            "departments": {
                "production": "生产",
                "quality": "质量",
                "equipment": "设备",
                "supply_chain": "供应链",
                "sales_service": "销售与服务",
                "finance_hr": "财务与人力",
            },
            "pains": {
                "knowledge_search": "知识与资料检索",
                "quality_inspection": "质量检测",
                "equipment_maintenance": "设备维护",
                "production_reporting": "生产报表",
                "scheduling": "生产排程",
                "inventory_supply": "库存与供应",
                "quotation_service": "报价与客户服务",
                "office_documents": "办公文档处理",
            },
        },
        "retail": {
            "subbranches": {
                "ecommerce": "电子商务",
                "chain_retail": "连锁零售",
                "brand_direct": "品牌直营",
                "wholesale_distribution": "批发分销",
            },
            "departments": {
                "merchandising": "商品运营",
                "store_operations": "门店运营",
                "supply_chain": "供应链",
                "marketing": "市场营销",
                "customer_service": "客户服务",
                "finance_hr": "财务与人力",
            },
            "pains": {
                "customer_service": "客户服务",
                "marketing_content": "营销内容",
                "member_operations": "会员运营",
                "inventory_replenishment": "库存补货",
                "sales_analysis": "销售分析",
                "pricing_selection": "选品与定价",
                "supply_reconciliation": "供应链对账",
                "office_knowledge": "办公知识管理",
            },
        },
        "professional_knowledge": {
            "subbranches": {
                "consulting": "咨询服务",
                "tax_accounting": "财税服务",
                "legal": "法律服务",
                "human_resources": "人力资源服务",
            },
            "departments": {
                "delivery": "项目交付",
                "knowledge_research": "知识研究",
                "client_growth": "客户增长",
                "contracts_risk": "合同与风险",
                "operations": "运营管理",
                "people": "人才管理",
            },
            "pains": {
                "document_search": "文档检索",
                "proposal_drafting": "方案撰写",
                "project_delivery": "项目交付",
                "contract_review": "合同审查",
                "client_service": "客户服务",
                "lead_followup": "商机跟进",
                "billing_reconciliation": "账单与对账",
                "talent_knowledge": "人才与知识管理",
            },
        },
        "software_creative": {
            "subbranches": {
                "software": "软件服务",
                "design": "设计服务",
                "advertising": "广告服务",
                "marketing_services": "营销服务",
            },
            "departments": {
                "product_delivery": "产品与交付",
                "design_content": "设计与内容",
                "engineering": "工程研发",
                "marketing_sales": "市场与销售",
                "customer_success": "客户成功",
                "operations": "运营管理",
            },
            "pains": {
                "requirements": "需求管理",
                "content_creation": "内容创作",
                "project_delivery": "项目交付",
                "quality_review": "质量审查",
                "customer_support": "客户支持",
                "marketing_sales": "市场与销售",
                "knowledge_docs": "知识文档",
                "operations_analysis": "运营分析",
            },
        },
    }
    expected_company_sizes = {
        "under_50": "50 人以下",
        "50_200": "50—200 人",
        "200_500": "200—500 人",
        "500_plus": "500 人以上",
    }

    for branch_code, labels in expected.items():
        catalog = repository().load_published_catalog(branch_code)
        industry_id = catalog_db.execute(
            "SELECT id FROM industries WHERE code=?", (branch_code,)
        ).fetchone()[0]
        actual = {
            "subbranches": dict(
                catalog_db.execute(
                    "SELECT code,name FROM industry_branches "
                    "WHERE industry_id=? ORDER BY sort_order",
                    (industry_id,),
                )
            ),
            "departments": dict(
                catalog_db.execute(
                    "SELECT code,name FROM departments "
                    "WHERE industry_id=? ORDER BY sort_order",
                    (industry_id,),
                )
            ),
            "pains": dict(
                catalog_db.execute(
                    "SELECT code,name FROM pain_points "
                    "WHERE industry_id=? ORDER BY sort_order",
                    (industry_id,),
                )
            ),
        }

        assert tuple(labels["subbranches"]) == catalog.subbranch_codes
        assert tuple(labels["departments"]) == catalog.department_codes
        assert tuple(labels["pains"]) == catalog.pain_codes
        assert actual == labels
        assert all(
            code != name
            for choice_labels in actual.values()
            for code, name in choice_labels.items()
        )

    company_sizes = dict(
        catalog_db.execute(
            "SELECT code,name FROM company_sizes ORDER BY sort_order"
        )
    )
    assert company_sizes == expected_company_sizes
    assert all(code != name for code, name in company_sizes.items())


def test_seeded_choices_and_roi_ranges_are_exact_and_ordered(catalog_db):
    company_sizes = tuple(
        row[0]
        for row in catalog_db.execute(
            "SELECT code FROM company_sizes ORDER BY sort_order"
        )
    )
    version_id = catalog_db.execute(
        "SELECT id FROM assessment_versions WHERE code=?", (VERSION_CODE,)
    ).fetchone()[0]
    roi_ranges = {
        (row[0], row[1]): (row[2], row[3], row[4])
        for row in catalog_db.execute(
            "SELECT option_group, code, low_value, mid_value, high_value "
            "FROM roi_option_ranges WHERE assessment_version_id=?",
            (version_id,),
        )
    }

    assert company_sizes == ("under_50", "50_200", "200_500", "500_plus")
    assert len(roi_ranges) == 20
    assert roi_ranges[("headcount", "50_plus")] == (51, 75, 100)
    assert roi_ranges[("monthly_hours", "160_plus")] == (160, 200, 240)
    assert roi_ranges[("monthly_cost", "under_8000")] == (5000, 6500, 8000)
    assert roi_ranges[("loss_factor", "severe")] == (0.35, 0.5, 0.7)
    assert roi_ranges[("budget", "500000_plus")] == (500000, 750000, 1000000)
    assert all(low <= mid <= high for low, mid, high in roi_ranges.values())


def test_scenarios_return_exact_typed_rules_and_valid_database_links(catalog_db):
    catalog_db.close()
    scenarios = repository().get_scenarios()
    by_code = {scenario.code: scenario for scenario in scenarios}

    assert len(scenarios) == 13
    assert tuple(scenario.sort_order for scenario in scenarios) == tuple(range(1, 14))
    assert by_code["mfg_quality_inspection"].branch_codes == ("manufacturing",)
    assert by_code["project_delivery_automation"].branch_codes == (
        "professional_knowledge",
        "software_creative",
    )
    assert by_code["mfg_quality_inspection"].minimum_scores == dict(
        zip(DIMENSIONS, (50, 50, 50, 50, 40, 40))
    )
    assert by_code["mfg_quality_inspection"].efficiency == (
        Decimal("0.10"),
        Decimal("0.20"),
        Decimal("0.30"),
    )
    assert by_code["mfg_quality_inspection"].annual_support_rate == (
        Decimal("0.12"),
        Decimal("0.15"),
        Decimal("0.20"),
    )
    fallback = by_code["data_process_foundation"]
    assert fallback.fallback_only is True
    assert fallback.pain_codes == ()
    assert fallback.branch_codes == (
        "manufacturing",
        "retail",
        "professional_knowledge",
        "software_creative",
    )

    db = models.get_db()
    try:
        ordinary = [scenario for scenario in scenarios if not scenario.fallback_only]
        assert all(
            scenario.category_code
            and scenario.branch_codes
            and scenario.department_codes
            and scenario.pain_codes
            and scenario.risk_codes
            and len(scenario.minimum_scores) == 6
            and scenario.budget_codes
            and scenario.min_weeks <= scenario.max_weeks
            and len(scenario.efficiency) == 3
            and len(scenario.loss_improvement) == 3
            and len(scenario.annual_support_rate) == 3
            and scenario.service_code
            for scenario in ordinary
        )
        branch_link_counts = {
            row[0]: row[1]
            for row in db.execute(
                "SELECT s.code, COUNT(*) FROM scenarios s "
                "JOIN scenario_branches sb ON sb.scenario_id=s.id "
                "GROUP BY s.code"
            )
        }
        assert branch_link_counts["mfg_knowledge_assistant"] == 4
        assert branch_link_counts["project_delivery_automation"] == 8
        assert branch_link_counts["data_process_foundation"] == 16
        invalid_links = db.execute(
            "SELECT COUNT(*) FROM scenario_services ss "
            "LEFT JOIN scenarios sc ON sc.id=ss.scenario_id "
            "LEFT JOIN services sv ON sv.id=ss.service_id "
            "WHERE sc.id IS NULL OR sv.id IS NULL"
        ).fetchone()[0]
        assert invalid_links == 0
    finally:
        db.close()


def test_service_packages_have_exact_scope_delivery_and_support(catalog_db):
    catalog_db.close()
    packages = repository().get_service_packages()
    by_code = {package.code: package for package in packages}

    assert tuple(by_code) == (
        "foundation_workshop",
        "knowledge_assistant_pilot",
        "customer_growth_pilot",
        "workflow_automation",
        "data_insight",
        "industry_integration",
    )
    foundation = by_code["foundation_workshop"]
    assert foundation.public_name == "AI 就绪基础工作坊"
    assert (foundation.min_budget, foundation.max_budget) == (
        Decimal("20000"),
        Decimal("50000"),
    )
    assert foundation.implementation_steps == (
        "资料准备",
        "两次业务工作坊",
        "基线与优先级整理",
        "90 天计划评审",
    )
    assert {
        code: package.not_included for code, package in by_code.items()
    } == CHINESE_SERVICE_EXCLUSIONS
    assert foundation.support_days == 15
    assert by_code["industry_integration"].support_days == 60
    assert all(
        package.deliverables
        and package.implementation_steps
        and package.prerequisites
        and package.not_included
        and package.acceptance
        and package.support_days > 0
        for package in packages
    )

    db = models.get_db()
    try:
        package_row = db.execute(
            "SELECT public_disclaimer, support_description, "
            "implementation_steps_json, not_included_json "
            "FROM services WHERE code='foundation_workshop'"
        ).fetchone()
        assert package_row["public_disclaimer"] == (
            "参考预算，最终范围和报价以需求确认结果为准"
        )
        assert package_row["support_description"] == "15 天内一次复盘会"
        assert json.loads(package_row["implementation_steps_json"]) == list(
            foundation.implementation_steps
        )
        assert json.loads(package_row["not_included_json"]) == list(
            foundation.not_included
        )
        package_scenarios = {
            row[0]: tuple(filter(None, row[1].split(",")))
            for row in db.execute(
                "SELECT sv.code, GROUP_CONCAT(sc.code) FROM services sv "
                "JOIN scenario_services ss ON ss.service_id=sv.id "
                "JOIN scenarios sc ON sc.id=ss.scenario_id "
                "WHERE sv.code IS NOT NULL GROUP BY sv.code ORDER BY sv.sort_order"
            )
        }
        assert package_scenarios["foundation_workshop"] == (
            "data_process_foundation",
        )
        assert set(package_scenarios["knowledge_assistant_pilot"]) == {
            "mfg_knowledge_assistant",
            "pro_document_knowledge",
            "software_support_knowledge",
        }
    finally:
        db.close()


def test_catalog_default_ignores_newer_published_version(catalog_db):
    insert_later_version_and_unrelated_service(catalog_db)

    catalog = repository().load_published_catalog("manufacturing")

    assert catalog.version_code == VERSION_CODE
    assert len(catalog.questions) == 12


def test_scenarios_default_uses_exact_v2_roi_profiles(catalog_db):
    insert_later_version_and_unrelated_service(catalog_db)

    scenarios = repository().get_scenarios()

    assert tuple(scenario.code for scenario in scenarios) == (
        "mfg_knowledge_assistant",
        "mfg_quality_inspection",
        "mfg_operations_reporting",
        "retail_ai_service",
        "retail_marketing_content",
        "retail_inventory_insight",
        "pro_document_knowledge",
        "pro_delivery_drafting",
        "pro_contract_review",
        "creative_content_workflow",
        "software_support_knowledge",
        "project_delivery_automation",
        "data_process_foundation",
    )


def test_service_packages_default_only_returns_exact_v2_scenario_links(catalog_db):
    insert_later_version_and_unrelated_service(catalog_db)

    packages = repository().get_service_packages()

    assert tuple(package.code for package in packages) == (
        "foundation_workshop",
        "knowledge_assistant_pilot",
        "customer_growth_pilot",
        "workflow_automation",
        "data_insight",
        "industry_integration",
    )


def test_repeated_init_never_overwrites_the_published_version(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    try:
        version_id = db.execute(
            "SELECT id FROM assessment_versions WHERE code=?", (VERSION_CODE,)
        ).fetchone()[0]
        db.execute(
            "UPDATE assessment_questions SET prompt=? "
            "WHERE assessment_version_id=? AND code='business_value_frequency'",
            ("published sentinel", version_id),
        )
        db.commit()
    finally:
        db.close()

    models.init_db()
    db = models.get_db()
    try:
        version_count = db.execute(
            "SELECT COUNT(*) FROM assessment_versions WHERE code=?", (VERSION_CODE,)
        ).fetchone()[0]
        prompt = db.execute(
            "SELECT prompt FROM assessment_questions "
            "WHERE assessment_version_id=? AND code='business_value_frequency'",
            (version_id,),
        ).fetchone()[0]
    finally:
        db.close()

    assert version_count == 1
    assert prompt == "published sentinel"


def test_repeated_init_reconciles_only_exact_legacy_service_exclusions(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    try:
        db.executemany(
            "UPDATE services SET not_included_json=? "
            "WHERE code=? AND status='published'",
            [
                (
                    json.dumps(values, ensure_ascii=False, separators=(",", ":")),
                    code,
                )
                for code, values in LEGACY_SERVICE_EXCLUSIONS.items()
            ],
        )
        insert_later_version_and_unrelated_service(db)
    finally:
        db.close()

    models.init_db()
    db = models.get_db()
    try:
        reconciled = {
            row["code"]: tuple(json.loads(row["not_included_json"]))
            for row in db.execute(
                "SELECT code,not_included_json FROM services "
                "WHERE code IN ({})".format(
                    ",".join("?" for _ in LEGACY_SERVICE_EXCLUSIONS)
                ),
                tuple(LEGACY_SERVICE_EXCLUSIONS),
            )
        }
        unrelated = db.execute(
            "SELECT not_included_json FROM services "
            "WHERE code='unrelated_published_service'"
        ).fetchone()[0]
    finally:
        db.close()

    assert reconciled == CHINESE_SERVICE_EXCLUSIONS
    assert json.loads(unrelated) == ["excluded"]


def test_repeated_init_preserves_custom_frozen_service_exclusions(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    custom = '["客户已审批的定制边界"]'
    db = models.get_db()
    try:
        db.execute(
            "UPDATE services SET not_included_json=? "
            "WHERE code='foundation_workshop' AND status='published'",
            (custom,),
        )
        db.commit()
    finally:
        db.close()

    models.init_db()
    db = models.get_db()
    try:
        stored = db.execute(
            "SELECT not_included_json FROM services "
            "WHERE code='foundation_workshop'"
        ).fetchone()[0]
    finally:
        db.close()

    assert stored == custom
