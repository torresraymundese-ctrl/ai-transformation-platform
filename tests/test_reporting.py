import json
from decimal import Decimal

import pytest

from assessment.contracts import (
    AssessmentCatalog,
    AssessmentProfile,
    RoiBand,
    RoiResult,
    Scenario,
    ScenarioMatch,
    ScoreResult,
    ServicePackage,
)
from assessment.reporting import DISCLAIMER, build_report_snapshot


DIMENSIONS = (
    "business_value",
    "process",
    "data",
    "systems",
    "organization",
    "delivery",
)


@pytest.fixture()
def catalog():
    return AssessmentCatalog(
        version_id=2,
        version_code="v2.0-2026-08-19",
        subbranch_codes=("discrete_manufacturing",),
        department_codes=("production",),
        pain_codes=("scheduling",),
        questions=(),
        branch_weights={},
        reference_lines={
            "manufacturing": dict(zip(DIMENSIONS, (60, 55, 55, 50, 50, 55)))
        },
    )


@pytest.fixture()
def profile():
    return AssessmentProfile(
        branch_code="manufacturing",
        subbranch_code="discrete_manufacturing",
        department_code="production",
        company_size_code="50_200",
        pain_codes=("scheduling",),
        answers={"delivery_timeline": "level_3"},
        roi_choices={
            "headcount": "6_20",
            "monthly_hours": "20_80",
            "monthly_cost": "8000_15000",
            "loss_factor": "normal",
            "budget": "200000_500000",
        },
    )


@pytest.fixture()
def scores():
    return ScoreResult(
        dimension_scores=dict(zip(DIMENSIONS, (90, 55, 45, 70, 40, 75))),
        overall_score=65,
        maturity_code="scale",
        strongest_dimension="business_value",
        weakest_dimension="organization",
    )


@pytest.fixture()
def roi_option_ranges():
    return {
        "headcount": {"6_20": (Decimal("6"), Decimal("13"), Decimal("20"))},
        "monthly_hours": {
            "20_80": (Decimal("20"), Decimal("50"), Decimal("80"))
        },
        "monthly_cost": {
            "8000_15000": (
                Decimal("8000"),
                Decimal("11500"),
                Decimal("15000"),
            )
        },
        "loss_factor": {
            "normal": (Decimal("0.05"), Decimal("0.10"), Decimal("0.15"))
        },
        "budget": {
            "200000_500000": (
                Decimal("200000"),
                Decimal("350000"),
                Decimal("500000"),
            )
        },
    }


@pytest.fixture()
def match():
    scenario = Scenario(
        code="mfg_operations_reporting",
        category_code="data_insight",
        branch_codes=("manufacturing",),
        department_codes=("production",),
        pain_codes=("scheduling",),
        minimum_scores=dict(zip(DIMENSIONS, (40, 40, 40, 30, 30, 30))),
        integration_level="medium",
        budget_codes=("200000_500000",),
        min_weeks=8,
        max_weeks=12,
        efficiency=(Decimal("0.20"), Decimal("0.35"), Decimal("0.50")),
        loss_improvement=(Decimal("0.05"), Decimal("0.12"), Decimal("0.20")),
        annual_support_rate=(Decimal("0.10"), Decimal("0.12"), Decimal("0.15")),
        risk_codes=("metric_definition", "source_consistency", "data_refresh"),
        service_code="data_insight",
        sort_order=3,
    )
    service = ServicePackage(
        code="data_insight",
        category="standard",
        public_name="数据洞察交付包",
        min_budget=Decimal("100000"),
        max_budget=Decimal("250000"),
        min_weeks=8,
        max_weeks=12,
        deliverables=("指标口径表", "数据看板"),
        implementation_steps=("明确口径", "数据验证"),
        prerequisites=("明确负责人",),
        not_included=("unlisted system interfaces",),
        acceptance=("约定指标可复算",),
        support_days=30,
    )
    return ScenarioMatch(
        scenario=scenario,
        service=service,
        total_score=95,
        components={"pain": 35, "industry": 20, "readiness": 25, "budget": 5, "timeline": 10},
        reason_codes=("pain_aligned", "industry_department_aligned"),
        reasons=("已匹配您选择的业务痛点。", "适配您所在的行业与部门。"),
    )


@pytest.fixture()
def roi():
    def band(code, multiplier):
        return RoiBand(
            band_code=code,
            current_annual_cost=Decimal("100000.00") * multiplier,
            labor_savings=Decimal("20000.00") * multiplier,
            loss_savings=Decimal("5000.00") * multiplier,
            annual_savings=Decimal("25000.00") * multiplier,
            initial_investment=Decimal("120000.00") * multiplier,
            annual_support=Decimal("14400.00") * multiplier,
            payback_months=Decimal("57.6"),
            three_year_support=Decimal("43200.00") * multiplier,
            three_year_net=Decimal("-88200.00") * multiplier,
        )

    return RoiResult(
        conservative=band("conservative", Decimal("1")),
        midpoint=band("midpoint", Decimal("2")),
        ideal=band("ideal", Decimal("3")),
    )


def test_report_snapshot_contains_required_sections_and_no_contact_pii(
    catalog, profile, scores, match, roi, roi_option_ranges
):
    snapshot = build_report_snapshot(
        profile, scores, (match,), roi, catalog, roi_option_ranges
    )

    assert snapshot["schema_version"] == "2.0"
    assert snapshot["rule_version"] == "v2.0-2026-08-19"
    assert set(snapshot) == {
        "schema_version", "rule_version", "assessment", "scores",
        "recommendations", "roi", "calculation_basis", "roadmap_90_days",
        "roadmap_years_1_3", "disclaimer",
    }
    assert snapshot["scores"]["reference_line"] == {
        "business_value": 60, "process": 55, "data": 55, "systems": 50,
        "organization": 50, "delivery": 55,
    }
    assert len(snapshot["recommendations"]) <= 3
    assert [item["days"] for item in snapshot["roadmap_90_days"]] == [
        "1-15", "16-30", "31-60", "61-90"
    ]
    assert snapshot["disclaimer"] == DISCLAIMER

    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "phone" not in serialized
    assert "contact_name" not in serialized
    assert "company_name" not in serialized
    assert "Decimal" not in serialized


def test_report_snapshot_captures_controlled_reasons_risks_packages_and_calculation_basis(
    catalog, profile, scores, match, roi, roi_option_ranges
):
    snapshot = build_report_snapshot(
        profile, scores, (match,), roi, catalog, roi_option_ranges
    )

    assert snapshot["scores"]["strongest"] == {
        "dimension": "business_value",
        "explanation": "业务价值维度得分较高，建议将已识别痛点作为试点收益和验收指标的起点。",
    }
    assert snapshot["scores"]["weakest"] == {
        "dimension": "organization",
        "explanation": "组织与推广维度仍需补齐，建议明确业务负责人、协作资源和试点采用安排。",
    }
    recommendation = snapshot["recommendations"][0]
    assert recommendation["reason_codes"] == [
        "pain_aligned", "industry_department_aligned"
    ]
    assert recommendation["risks"] == [
        {"code": "metric_definition", "explanation": "先统一指标定义、计算口径和复核责任。"},
        {"code": "source_consistency", "explanation": "先核对来源系统、字段含义和更新频率。"},
        {"code": "data_refresh", "explanation": "明确数据刷新节奏、延迟边界和异常处理。"},
    ]
    assert recommendation["package"] == {
        "code": "data_insight",
        "category": "standard",
        "public_name": "数据洞察交付包",
        "budget_range": {"min": "100000", "max": "250000"},
        "delivery_weeks": {"min": 8, "max": 12},
        "deliverables": ["指标口径表", "数据看板"],
        "implementation_steps": ["明确口径", "数据验证"],
        "prerequisites": ["明确负责人"],
        "not_included": ["unlisted system interfaces"],
        "acceptance": ["约定指标可复算"],
        "support_days": 30,
    }
    assert snapshot["calculation_basis"] == {
        "selected_roi_choices": {
            "headcount": "6_20", "monthly_hours": "20_80",
            "monthly_cost": "8000_15000", "loss_factor": "normal",
            "budget": "200000_500000",
        },
        "selected_scenario": "mfg_operations_reporting",
        "coefficients": {
            "efficiency": ["0.20", "0.35", "0.50"],
            "loss_improvement": ["0.05", "0.12", "0.20"],
            "annual_support_rate": ["0.10", "0.12", "0.15"],
        },
        "selected_roi_bands": {
            "headcount": {"low": "6", "mid": "13", "high": "20"},
            "monthly_hours": {"low": "20", "mid": "50", "high": "80"},
            "monthly_cost": {
                "low": "8000", "mid": "11500", "high": "15000",
            },
            "loss_factor": {
                "low": "0.05", "mid": "0.10", "high": "0.15",
            },
            "budget": {
                "low": "200000", "mid": "350000", "high": "500000",
            },
        },
    }
    assert snapshot["roi"]["midpoint"]["annual_savings"] == "50000.00"
    assert snapshot["roi"]["midpoint"]["payback_months"] == "57.6"


@pytest.mark.parametrize(
    ("maturity", "year_one"),
    [
        ("explore", "完成流程和数据基础梳理，选择 1 个低集成高价值场景试点并建立验收基线"),
        ("pilot", "完成 1—2 个高价值场景试点，建立数据、流程和效果基线"),
        ("scale", "稳定运行 2—3 个高价值场景，固化负责人、验收和运营机制"),
        ("collaborate", "优化跨系统协同场景，同时复核数据基线、权限和业务验收指标"),
    ],
)
def test_report_snapshot_uses_exact_maturity_specific_year_one_roadmap(
    catalog, profile, scores, match, roi, roi_option_ranges, maturity, year_one
):
    maturity_scores = ScoreResult(
        dimension_scores=scores.dimension_scores,
        overall_score=scores.overall_score,
        maturity_code=maturity,
        strongest_dimension=scores.strongest_dimension,
        weakest_dimension=scores.weakest_dimension,
    )

    snapshot = build_report_snapshot(
        profile, maturity_scores, (match,), roi, catalog, roi_option_ranges
    )

    assert snapshot["roadmap_years_1_3"] == [
        {"year": 1, "action": year_one},
        {"year": 2, "action": "复制到相邻部门，打通必要系统并建立统一运营指标"},
        {"year": 3, "action": "形成跨部门协同、治理和持续优化机制"},
    ]
    if maturity == "explore":
        assert "大规模集成" not in snapshot["roadmap_years_1_3"][0]["action"]
    if maturity == "collaborate":
        assert "跨系统协同" in snapshot["roadmap_years_1_3"][0]["action"]


def test_report_snapshot_is_deterministic_and_not_affected_by_later_input_mutation(
    catalog, profile, scores, match, roi, roi_option_ranges
):
    first = build_report_snapshot(
        profile, scores, (match,), roi, catalog, roi_option_ranges
    )
    second = build_report_snapshot(
        profile, scores, (match,), roi, catalog, roi_option_ranges
    )
    profile.roi_choices["budget"] = "under_50000"
    match.components["pain"] = 0

    assert first == second
    assert first["assessment"]["roi_choices"]["budget"] == "200000_500000"
    assert first["recommendations"][0]["components"]["pain"] == 35
