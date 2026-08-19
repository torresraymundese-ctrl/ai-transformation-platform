from decimal import Decimal

import pytest

from assessment.contracts import (
    AssessmentInputError,
    AssessmentProfile,
    Scenario,
    ScoreResult,
    ServicePackage,
)
from assessment.matching import match_scenarios


DIMENSIONS = (
    "business_value",
    "process",
    "data",
    "systems",
    "organization",
    "delivery",
)


def score_result(**overrides):
    values = {dimension: 100 for dimension in DIMENSIONS}
    values.update(overrides)
    return ScoreResult(
        dimension_scores=values,
        overall_score=100,
        maturity_code="collaborate",
        strongest_dimension="business_value",
        weakest_dimension="delivery",
    )


def profile(branch="manufacturing", department="production", pain="scheduling", **overrides):
    values = {
        "branch_code": branch,
        "subbranch_code": "discrete_manufacturing",
        "department_code": department,
        "company_size_code": "50_200",
        "pain_codes": (pain,),
        "answers": {"delivery_timeline": "level_3"},
        "roi_choices": {"budget": "200000_500000"},
    }
    values.update(overrides)
    return AssessmentProfile(**values)


def scenario(
    code,
    *,
    departments=("production",),
    pains=("scheduling",),
    minimum=50,
    integration="medium",
    budgets=("200000_500000",),
    weeks=(8, 12),
    service_code="standard_service",
    sort_order=1,
    fallback_only=False,
):
    return Scenario(
        code=code,
        category_code="test",
        branch_codes=("manufacturing",),
        department_codes=departments,
        pain_codes=pains,
        minimum_scores={dimension: minimum for dimension in DIMENSIONS},
        integration_level=integration,
        budget_codes=budgets,
        min_weeks=weeks[0],
        max_weeks=weeks[1],
        efficiency=(Decimal("0"),) * 3,
        loss_improvement=(Decimal("0"),) * 3,
        annual_support_rate=(Decimal("0"),) * 3,
        risk_codes=(),
        service_code=service_code,
        sort_order=sort_order,
        fallback_only=fallback_only,
    )


def service(code, category):
    return ServicePackage(
        code=code,
        category=category,
        public_name=code,
        min_budget=Decimal("0"),
        max_budget=Decimal("1"),
        min_weeks=1,
        max_weeks=24,
        deliverables=("deliverable",),
        implementation_steps=("step",),
        prerequisites=("prerequisite",),
        not_included=("excluded",),
        acceptance=("acceptance",),
        support_days=1,
    )


@pytest.fixture()
def services():
    return (
        service("foundation_service", "foundation"),
        service("pilot_service", "pilot"),
        service("standard_service", "standard"),
        service("integration_service", "integration"),
    )


@pytest.fixture()
def foundation():
    return scenario(
        "data_process_foundation",
        minimum=0,
        pains=(),
        service_code="foundation_service",
        fallback_only=True,
        weeks=(2, 4),
    )


def test_low_data_blocks_advanced_scenario_and_returns_foundation(services, foundation):
    advanced = scenario("advanced", minimum=40, integration="high", service_code="integration_service")

    matches = match_scenarios(
        profile(), score_result(data=33, process=50, systems=67, delivery=67),
        (advanced, foundation), services,
    )

    assert [match.scenario.code for match in matches] == ["data_process_foundation"]
    assert matches[0].reason_codes == ("foundation_required",)


def test_match_score_uses_35_20_25_10_10_components(services, foundation):
    matches = match_scenarios(profile(), score_result(), (scenario("full_match"), foundation), services)

    assert matches[0].total_score == 100
    assert matches[0].components == {
        "pain": 35,
        "industry": 20,
        "readiness": 25,
        "budget": 10,
        "timeline": 10,
    }
    assert matches[0].reason_codes == (
        "pain_aligned",
        "industry_department_aligned",
        "readiness_sufficient",
        "budget_aligned",
        "timeline_aligned",
    )
    assert matches[0].reasons == (
        "已匹配您选择的业务痛点。",
        "适配您所在的行业与部门。",
        "当前就绪度满足该场景的实施条件。",
        "预算范围与该场景匹配。",
        "交付节奏与您的时间安排匹配。",
    )


def test_systems_below_forty_blocks_high_integration_scenario(services, foundation):
    high_integration = scenario("high_integration", minimum=0, integration="high", service_code="integration_service")

    matches = match_scenarios(profile(), score_result(systems=39), (high_integration, foundation), services)

    assert [match.scenario.code for match in matches] == ["data_process_foundation"]


def test_low_delivery_only_allows_foundation_or_pilot_packages(services, foundation):
    standard = scenario("standard", minimum=0, service_code="standard_service")
    pilot = scenario("pilot", minimum=0, service_code="pilot_service", sort_order=2)

    matches = match_scenarios(profile(), score_result(delivery=33), (standard, pilot, foundation), services)

    assert [match.scenario.code for match in matches] == ["pilot"]


def test_department_mismatch_cannot_be_recommended(services, foundation):
    wrong_department = scenario("quality_only", departments=("quality",))

    matches = match_scenarios(profile(department="production"), score_result(), (wrong_department, foundation), services)

    assert [match.scenario.code for match in matches] == ["data_process_foundation"]


def test_ties_resolve_by_scenario_sort_order_then_stable_code(services, foundation):
    later = scenario("a_later", sort_order=2)
    first_code = scenario("a_first", sort_order=1)
    second_code = scenario("b_second", sort_order=1)

    matches = match_scenarios(profile(), score_result(), (later, second_code, first_code, foundation), services)

    assert [match.scenario.code for match in matches] == ["a_first", "b_second", "a_later"]


def test_fewer_than_three_eligible_scenarios_are_not_padded(services, foundation):
    matched = scenario("matched", budgets=("under_50000",), weeks=(2, 4))
    unrelated = scenario("unrelated", pains=("different_pain",), minimum=100)

    matches = match_scenarios(
        profile(
            answers={"delivery_timeline": "level_0"},
            roi_choices={"budget": "under_50000"},
        ),
        score_result(),
        (matched, unrelated, foundation),
        services,
    )

    assert [match.scenario.code for match in matches] == ["matched"]


def test_adjacent_budget_contributes_five_points(services, foundation):
    adjacent = scenario("adjacent", budgets=("50000_200000",))

    match = match_scenarios(profile(), score_result(), (adjacent, foundation), services)[0]

    assert match.components["budget"] == 5
    assert match.total_score == 95


@pytest.mark.parametrize(
    ("timeline", "weeks", "expected"),
    [
        ("level_0", (2, 4), 5),
        ("level_0", (4, 5), 0),
        ("level_1", (4, 8), 5),
        ("level_1", (6, 9), 0),
        ("level_2", (8, 12), 10),
        ("level_2", (8, 13), 5),
        ("level_3", (12, 24), 10),
    ],
)
def test_timeline_score_follows_selected_delivery_expectation(services, foundation, timeline, weeks, expected):
    timed = scenario("timed", weeks=weeks)

    match = match_scenarios(
        profile(answers={"delivery_timeline": timeline}), score_result(), (timed, foundation), services,
    )[0]

    assert match.components["timeline"] == expected


def test_unknown_timeline_code_fails_before_matching(services, foundation):
    with pytest.raises(AssessmentInputError):
        match_scenarios(
            profile(answers={"delivery_timeline": "tomorrow"}), score_result(),
            (scenario("timed"), foundation), services,
        )
