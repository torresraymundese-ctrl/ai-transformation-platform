"""Pure, deterministic scenario and service-package matching rules."""

from collections.abc import Mapping
from types import MappingProxyType

from .contracts import (
    AssessmentInputError,
    AssessmentProfile,
    Scenario,
    ScenarioMatch,
    ScoreResult,
    ServicePackage,
)


DIMENSION_ORDER = (
    "business_value",
    "process",
    "data",
    "systems",
    "organization",
    "delivery",
)
COMPONENT_MAX = {
    "pain": 35,
    "industry": 20,
    "readiness": 25,
    "budget": 10,
    "timeline": 10,
}
BUDGET_ORDER = (
    "under_50000",
    "50000_200000",
    "200000_500000",
    "500000_plus",
)
TIMELINE_CODES = frozenset({"level_0", "level_1", "level_2", "level_3"})
LOW_DELIVERY_CATEGORIES = frozenset({"foundation", "pilot"})

REASON_TEMPLATES = {
    "pain_aligned": "已匹配您选择的业务痛点。",
    "industry_department_aligned": "适配您所在的行业与部门。",
    "readiness_sufficient": "当前就绪度满足该场景的实施条件。",
    "budget_aligned": "预算范围与该场景匹配。",
    "budget_adjacent": "预算范围与该场景相邻，可从相近范围开始规划。",
    "timeline_aligned": "交付节奏与您的时间安排匹配。",
    "foundation_required": "建议先完成数据与流程基础梳理。",
}


def match_scenarios(
    profile: AssessmentProfile,
    scores: ScoreResult,
    scenarios: tuple[Scenario, ...],
    services: tuple[ServicePackage, ...],
    limit: int = 3,
) -> tuple[ScenarioMatch, ...]:
    """Return up to three scored ordinary matches, or the universal foundation."""
    timeline_code = _timeline_code(profile)
    _validate_dimension_scores(scores)
    service_by_code = {service.code: service for service in services}
    eligible = (
        scenario
        for scenario in scenarios
        if _passes_gates(scenario, profile, scores, service_by_code)
    )
    ranked = sorted(
        (
            _build_match(scenario, profile, scores, service_by_code[scenario.service_code], timeline_code)
            for scenario in eligible
        ),
        key=lambda item: (-item.total_score, item.scenario.sort_order, item.scenario.code),
    )
    accepted = tuple(
        item for item in ranked if item.total_score >= 60
    )[: _match_limit(limit)]
    if accepted:
        return accepted
    return (_foundation_match(scenarios, service_by_code),)


def _passes_gates(
    scenario: Scenario,
    profile: AssessmentProfile,
    scores: ScoreResult,
    service_by_code: Mapping[str, ServicePackage],
) -> bool:
    if scenario.fallback_only:
        return False
    if profile.branch_code not in scenario.branch_codes:
        return False
    if profile.department_code not in scenario.department_codes:
        return False
    if scenario.service_code not in service_by_code:
        return False
    if any(
        scores.dimension_scores[dimension] < scenario.minimum_scores.get(dimension, 0)
        for dimension in DIMENSION_ORDER
    ):
        return False
    if scenario.integration_level == "high" and scores.dimension_scores["systems"] < 40:
        return False
    service = service_by_code[scenario.service_code]
    return not (
        scores.dimension_scores["delivery"] < 40
        and service.category not in LOW_DELIVERY_CATEGORIES
    )


def _build_match(
    scenario: Scenario,
    profile: AssessmentProfile,
    scores: ScoreResult,
    service: ServicePackage,
    timeline_code: str,
) -> ScenarioMatch:
    components = {
        "pain": _pain_component(profile, scenario),
        "industry": COMPONENT_MAX["industry"],
        "readiness": _readiness_component(scores, scenario),
        "budget": _budget_component(profile, scenario),
        "timeline": _timeline_component(timeline_code, scenario.max_weeks),
    }
    reason_codes = _reason_codes(components)
    return ScenarioMatch(
        scenario=scenario,
        service=service,
        total_score=sum(components.values()),
        components=MappingProxyType(components),
        reason_codes=reason_codes,
        reasons=tuple(REASON_TEMPLATES[code] for code in reason_codes),
    )


def _pain_component(profile: AssessmentProfile, scenario: Scenario) -> int:
    return COMPONENT_MAX["pain"] if set(profile.pain_codes) & set(scenario.pain_codes) else 0


def _readiness_component(scores: ScoreResult, scenario: Scenario) -> int:
    ratios = tuple(
        1
        if scenario.minimum_scores.get(dimension, 0) == 0
        else min(scores.dimension_scores[dimension] / scenario.minimum_scores[dimension], 1)
        for dimension in DIMENSION_ORDER
    )
    return round(COMPONENT_MAX["readiness"] * sum(ratios) / len(ratios))


def _budget_component(profile: AssessmentProfile, scenario: Scenario) -> int:
    budget_code = profile.roi_choices.get("budget")
    if budget_code in scenario.budget_codes:
        return COMPONENT_MAX["budget"]
    if budget_code not in BUDGET_ORDER:
        return 0
    budget_position = BUDGET_ORDER.index(budget_code)
    if any(abs(BUDGET_ORDER.index(code) - budget_position) == 1 for code in scenario.budget_codes):
        return 5
    return 0


def _timeline_component(timeline_code: str, maximum_weeks: int) -> int:
    if timeline_code == "level_0":
        return 5 if maximum_weeks <= 4 else 0
    if timeline_code == "level_1":
        return 5 if maximum_weeks <= 8 else 0
    if timeline_code == "level_2":
        return 10 if maximum_weeks <= 12 else 5
    return COMPONENT_MAX["timeline"]


def _reason_codes(components: Mapping[str, int]) -> tuple[str, ...]:
    codes = ["industry_department_aligned", "readiness_sufficient"]
    if components["pain"]:
        codes.insert(0, "pain_aligned")
    if components["budget"] == COMPONENT_MAX["budget"]:
        codes.append("budget_aligned")
    elif components["budget"]:
        codes.append("budget_adjacent")
    if components["timeline"]:
        codes.append("timeline_aligned")
    return tuple(codes)


def _timeline_code(profile: AssessmentProfile) -> str:
    if not isinstance(profile.answers, Mapping):
        raise AssessmentInputError("answers must be a mapping")
    timeline_code = profile.answers.get("delivery_timeline")
    if timeline_code not in TIMELINE_CODES:
        raise AssessmentInputError("unknown delivery_timeline code")
    return timeline_code


def _validate_dimension_scores(scores: ScoreResult) -> None:
    if not isinstance(scores.dimension_scores, Mapping) or set(scores.dimension_scores) != set(DIMENSION_ORDER):
        raise AssessmentInputError("dimension scores must cover exactly six dimensions")


def _match_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise AssessmentInputError("match limit must be an integer")
    return min(max(limit, 0), 3)


def _foundation_match(
    scenarios: tuple[Scenario, ...], service_by_code: Mapping[str, ServicePackage]
) -> ScenarioMatch:
    foundation = next(
        (scenario for scenario in scenarios if scenario.code == "data_process_foundation"),
        None,
    )
    if foundation is None or foundation.service_code not in service_by_code:
        raise AssessmentInputError("foundation scenario and service are required")
    return ScenarioMatch(
        scenario=foundation,
        service=service_by_code[foundation.service_code],
        total_score=0,
        components=MappingProxyType({component: 0 for component in COMPONENT_MAX}),
        reason_codes=("foundation_required",),
        reasons=(REASON_TEMPLATES["foundation_required"],),
    )
