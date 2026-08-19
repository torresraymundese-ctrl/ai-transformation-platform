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


@pytest.fixture()
def catalog_db(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    return models.get_db()


def repository():
    return importlib.import_module("assessment_repository")


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
    assert foundation.not_included == (
        "software development",
        "system integration",
        "data cleansing execution",
    )
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
