"""Strict HTTP-boundary validation for the public V2 assessment APIs."""

from collections import Counter
import re

from assessment.contracts import (
    AssessmentCatalog,
    AssessmentProfile,
    Attribution,
    CompletionRequest,
    Consent,
    Contact,
)
from assessment.reporting import RISK_EXPLANATIONS
from assessment.scoring import DIMENSION_ORDER
from validation import ValidationError, validated_submission_key


SCHEMA_VERSION = "2.0"
CONSENT_POLICY_VERSION = "2026-08-19"
BRANCH_CODES = frozenset(
    {
        "manufacturing",
        "retail",
        "professional_knowledge",
        "software_creative",
    }
)
QUESTION_CODES = (
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
)
COMPANY_SIZE_CODES = (
    "under_50",
    "50_200",
    "200_500",
    "500_plus",
)
ROI_OPTION_CODES = {
    "headcount": ("1_5", "6_20", "21_50", "50_plus"),
    "monthly_hours": ("under_20", "20_80", "80_160", "160_plus"),
    "monthly_cost": (
        "under_8000",
        "8000_15000",
        "15000_30000",
        "30000_plus",
    ),
    "loss_factor": ("rare", "normal", "high", "severe"),
    "budget": (
        "under_50000",
        "50000_200000",
        "200000_500000",
        "500000_plus",
    ),
}
BRANCH_WEIGHTS = {
    "manufacturing": (20, 20, 20, 15, 10, 15),
    "retail": (25, 15, 20, 15, 10, 15),
    "professional_knowledge": (25, 20, 15, 10, 15, 15),
    "software_creative": (25, 15, 15, 15, 15, 15),
}
REFERENCE_LINES = {
    "manufacturing": (60, 55, 55, 50, 50, 55),
    "retail": (60, 55, 60, 60, 50, 55),
    "professional_knowledge": (60, 60, 55, 50, 55, 55),
    "software_creative": (60, 55, 55, 60, 55, 55),
}
SCENARIO_CODES = frozenset(
    {
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
    }
)
SERVICE_CODES = frozenset(
    {
        "foundation_workshop",
        "knowledge_assistant_pilot",
        "customer_growth_pilot",
        "workflow_automation",
        "data_insight",
        "industry_integration",
    }
)
SERVICE_CATEGORIES = {
    "foundation_workshop": "foundation",
    "knowledge_assistant_pilot": "pilot",
    "customer_growth_pilot": "pilot",
    "workflow_automation": "standard",
    "data_insight": "standard",
    "industry_integration": "integration",
}
SCENARIO_SERVICE_CODES = {
    "mfg_knowledge_assistant": "knowledge_assistant_pilot",
    "mfg_quality_inspection": "industry_integration",
    "mfg_operations_reporting": "data_insight",
    "retail_ai_service": "customer_growth_pilot",
    "retail_marketing_content": "customer_growth_pilot",
    "retail_inventory_insight": "data_insight",
    "pro_document_knowledge": "knowledge_assistant_pilot",
    "pro_delivery_drafting": "workflow_automation",
    "pro_contract_review": "workflow_automation",
    "creative_content_workflow": "customer_growth_pilot",
    "software_support_knowledge": "knowledge_assistant_pilot",
    "project_delivery_automation": "industry_integration",
    "data_process_foundation": "foundation_workshop",
}
EXPECTED_BRANCH_COLLECTION_LENGTHS = {
    "subbranches": 4,
    "departments": 6,
    "pain_points": 8,
}
CODE_PATTERN = re.compile(r"^[a-z0-9_]+$")
EMBEDDED_EMAIL_PATTERN = re.compile(
    r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
    re.I,
)
EMBEDDED_MAINLAND_MOBILE_PATTERN = re.compile(
    r"(?<!\d)(?:(?:\+?86|0086)[\s.-]*)?"
    r"1[3-9](?:[\s.-]*\d){9}(?!\d)"
)


class AssessmentRulesUnavailable(RuntimeError):
    """Raised when a published rule bundle cannot safely serve a request."""


def validated_branch_code(value):
    if value not in BRANCH_CODES:
        raise ValidationError("invalid assessment payload")
    return value


def parse_preview_payload(data) -> AssessmentProfile:
    payload = _object(data)
    _exact_keys(
        payload,
        {"schema_version", "profile", "answers", "roi_choices"},
    )
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValidationError("invalid assessment payload")

    profile = _object(payload["profile"])
    _exact_keys(
        profile,
        {
            "branch_code",
            "subbranch_code",
            "department_code",
            "company_size_code",
            "pain_codes",
        },
    )
    branch_code = validated_branch_code(profile["branch_code"])
    subbranch_code = _code(profile["subbranch_code"])
    department_code = _code(profile["department_code"])
    company_size_code = _code(profile["company_size_code"])

    pain_values = profile["pain_codes"]
    if not isinstance(pain_values, list) or not 1 <= len(pain_values) <= 3:
        raise ValidationError("invalid assessment payload")
    pain_codes = tuple(_code(value) for value in pain_values)
    if len(set(pain_codes)) != len(pain_codes):
        raise ValidationError("invalid assessment payload")

    answers = _code_mapping(payload["answers"], expected_keys=QUESTION_CODES)
    roi_choices = _code_mapping(
        payload["roi_choices"], expected_keys=ROI_OPTION_CODES
    )
    return AssessmentProfile(
        branch_code=branch_code,
        subbranch_code=subbranch_code,
        department_code=department_code,
        company_size_code=company_size_code,
        pain_codes=pain_codes,
        answers=answers,
        roi_choices=roi_choices,
    )


def parse_completion_payload(data) -> CompletionRequest:
    payload = _object(data)
    _exact_keys(
        payload,
        {"submission_key", "assessment", "contact", "consent", "attribution"},
    )
    submission_key = validated_submission_key(payload["submission_key"])
    profile = parse_preview_payload(payload["assessment"])

    contact = _object(payload["contact"])
    _allowed_keys(
        contact,
        required={"company_name", "contact_name", "phone"},
        allowed={"company_name", "contact_name", "phone", "email", "wechat"},
    )
    contact_value = Contact(
        company_name=_text(contact["company_name"], maximum=200, required=True),
        contact_name=_text(contact["contact_name"], maximum=100, required=True),
        phone=_text(contact["phone"], maximum=32, required=True),
        email=_text(contact.get("email", ""), maximum=254),
        wechat=_text(contact.get("wechat", ""), maximum=64),
    )

    consent = _object(payload["consent"])
    _exact_keys(consent, {"accepted", "policy_version"})
    if consent["accepted"] is not True:
        raise ValidationError("invalid assessment payload")
    policy_version = _text(
        consent["policy_version"], maximum=50, required=True
    )
    if policy_version != CONSENT_POLICY_VERSION:
        raise ValidationError("invalid assessment payload")
    consent_value = Consent(accepted=True, policy_version=policy_version)

    attribution = _object(payload["attribution"])
    _allowed_keys(
        attribution,
        required={"source"},
        allowed={"source", "utm_source", "utm_medium", "utm_campaign"},
    )
    attribution_value = Attribution(
        source=_attribution_text(
            attribution["source"], maximum=100, required=True
        ),
        utm_source=_attribution_text(
            attribution.get("utm_source", ""), maximum=100
        ),
        utm_medium=_attribution_text(
            attribution.get("utm_medium", ""), maximum=100
        ),
        utm_campaign=_attribution_text(
            attribution.get("utm_campaign", ""), maximum=100
        ),
    )
    return CompletionRequest(
        submission_key=submission_key,
        profile=profile,
        contact=contact_value,
        consent=consent_value,
        attribution=attribution_value,
    )


def validate_published_rule_bundle(
    catalog,
    branch_code,
    public_config,
    scenarios,
    services,
    ranges,
):
    """Fail closed when the exact published V2 rule bundle is incomplete."""
    if not isinstance(catalog, AssessmentCatalog):
        raise AssessmentRulesUnavailable("catalog_type")
    if catalog.version_code != "v2.0-2026-08-19":
        raise AssessmentRulesUnavailable("version")
    if tuple(question.code for question in catalog.questions) != QUESTION_CODES:
        raise AssessmentRulesUnavailable("questions")
    dimensions = Counter(question.dimension for question in catalog.questions)
    if dimensions != Counter({dimension: 2 for dimension in DIMENSION_ORDER}):
        raise AssessmentRulesUnavailable("dimensions")
    for question in catalog.questions:
        if not question.prompt.strip() or tuple(
            (option.code, option.score) for option in question.options
        ) != tuple((f"level_{score}", score) for score in range(4)):
            raise AssessmentRulesUnavailable("options")
        if any(not option.label.strip() for option in question.options):
            raise AssessmentRulesUnavailable("option_labels")

    if {
        code: tuple(catalog.branch_weights.get(code, {}).get(dimension) for dimension in DIMENSION_ORDER)
        for code in BRANCH_WEIGHTS
    } != BRANCH_WEIGHTS or set(catalog.branch_weights) != set(BRANCH_WEIGHTS):
        raise AssessmentRulesUnavailable("weights")
    if {
        code: tuple(catalog.reference_lines.get(code, {}).get(dimension) for dimension in DIMENSION_ORDER)
        for code in REFERENCE_LINES
    } != REFERENCE_LINES or set(catalog.reference_lines) != set(REFERENCE_LINES):
        raise AssessmentRulesUnavailable("reference_line")

    _validate_public_config(catalog, branch_code, public_config)
    _validate_completion_dependencies(scenarios, services, ranges)


def validate_profile_membership(profile, catalog, public_config):
    if profile.subbranch_code not in catalog.subbranch_codes:
        raise ValidationError("invalid assessment payload")
    if profile.department_code not in catalog.department_codes:
        raise ValidationError("invalid assessment payload")
    if profile.company_size_code not in {
        item["code"] for item in public_config["company_sizes"]
    }:
        raise ValidationError("invalid assessment payload")
    if any(code not in catalog.pain_codes for code in profile.pain_codes):
        raise ValidationError("invalid assessment payload")
    for group, option_codes in ROI_OPTION_CODES.items():
        if profile.roi_choices[group] not in option_codes:
            raise ValidationError("invalid assessment payload")


def _validate_public_config(catalog, branch_code, public_config):
    if public_config.get("branch", {}).get("code") != branch_code:
        raise AssessmentRulesUnavailable("branch")
    if not public_config["branch"].get("label"):
        raise AssessmentRulesUnavailable("branch_label")
    for name, expected_length in EXPECTED_BRANCH_COLLECTION_LENGTHS.items():
        items = public_config.get(name)
        if not isinstance(items, list) or len(items) != expected_length:
            raise AssessmentRulesUnavailable(name)
        if any(
            set(item) != {"code", "label"}
            or not item["code"]
            or not item["label"]
            for item in items
        ):
            raise AssessmentRulesUnavailable(f"{name}_shape")
    if tuple(item["code"] for item in public_config["subbranches"]) != tuple(
        catalog.subbranch_codes
    ):
        raise AssessmentRulesUnavailable("subbranch_mismatch")
    if tuple(item["code"] for item in public_config["departments"]) != tuple(
        catalog.department_codes
    ):
        raise AssessmentRulesUnavailable("department_mismatch")
    if tuple(item["code"] for item in public_config["pain_points"]) != tuple(
        catalog.pain_codes
    ):
        raise AssessmentRulesUnavailable("pain_mismatch")
    if tuple(item["code"] for item in public_config.get("company_sizes", ())) != COMPANY_SIZE_CODES:
        raise AssessmentRulesUnavailable("company_sizes")
    if public_config.get("pain_selection") != {"minimum": 1, "maximum": 3}:
        raise AssessmentRulesUnavailable("pain_selection")
    roi_options = public_config.get("roi_options")
    if not isinstance(roi_options, dict) or {
        group: tuple(codes) for group, codes in roi_options.items()
    } != ROI_OPTION_CODES:
        raise AssessmentRulesUnavailable("roi_options")
    if public_config.get("reference_label") != "平台建议就绪参考线":
        raise AssessmentRulesUnavailable("reference_label")


def _validate_completion_dependencies(scenarios, services, ranges):
    if not scenarios or not services:
        raise AssessmentRulesUnavailable("recommendations")
    if (
        {scenario.code for scenario in scenarios} != SCENARIO_CODES
        or len(scenarios) != len(SCENARIO_CODES)
    ):
        raise AssessmentRulesUnavailable("scenario_duplicates")
    service_by_code = {service.code: service for service in services}
    if set(service_by_code) != SERVICE_CODES or len(service_by_code) != len(services):
        raise AssessmentRulesUnavailable("service_duplicates")
    foundation = [
        scenario
        for scenario in scenarios
        if scenario.code == "data_process_foundation" and scenario.fallback_only
    ]
    if len(foundation) != 1:
        raise AssessmentRulesUnavailable("foundation")
    for scenario in scenarios:
        if (
            set(scenario.minimum_scores) != set(DIMENSION_ORDER)
            or any(
                not isinstance(value, int) or not 0 <= value <= 100
                for value in scenario.minimum_scores.values()
            )
            or scenario.service_code != SCENARIO_SERVICE_CODES.get(scenario.code)
            or scenario.integration_level not in {"low", "medium", "high"}
            or not _positive_integer_range(
                scenario.min_weeks, scenario.max_weeks
            )
            or not scenario.budget_codes
            or not set(scenario.budget_codes) <= set(ROI_OPTION_CODES["budget"])
            or len(scenario.efficiency) != 3
            or len(scenario.loss_improvement) != 3
            or len(scenario.annual_support_rate) != 3
            or not _ordered_unit_triple(scenario.efficiency)
            or not _ordered_unit_triple(scenario.loss_improvement)
            or not _ordered_unit_triple(scenario.annual_support_rate)
            or not scenario.risk_codes
            or not set(scenario.risk_codes) <= set(RISK_EXPLANATIONS)
        ):
            raise AssessmentRulesUnavailable("scenario")
        if not scenario.fallback_only and (
            not scenario.branch_codes
            or not scenario.department_codes
            or not scenario.pain_codes
        ):
            raise AssessmentRulesUnavailable("scenario_links")
    for service in services:
        if (
            not service.public_name
            or service.category != SERVICE_CATEGORIES.get(service.code)
            or not _ordered_nonnegative_pair(
                service.min_budget, service.max_budget
            )
            or not _positive_integer_range(service.min_weeks, service.max_weeks)
            or not service.deliverables
            or not service.implementation_steps
            or not service.prerequisites
            or not service.not_included
            or not service.acceptance
            or service.support_days < 1
        ):
            raise AssessmentRulesUnavailable("service")
    if set(ranges) != set(ROI_OPTION_CODES):
        raise AssessmentRulesUnavailable("roi_groups")
    for group, expected_codes in ROI_OPTION_CODES.items():
        if tuple(ranges[group]) != expected_codes:
            raise AssessmentRulesUnavailable("roi_codes")
        if any(
            not _ordered_nonnegative_triple(values)
            for values in ranges[group].values()
        ):
            raise AssessmentRulesUnavailable("roi_ranges")


def _ordered_unit_triple(values):
    return (
        _ordered_nonnegative_triple(values)
        and values[2] <= 1
    )


def _ordered_nonnegative_triple(values):
    return (
        len(values) == 3
        and all(getattr(value, "is_finite", lambda: False)() for value in values)
        and 0 <= values[0] <= values[1] <= values[2]
    )


def _ordered_nonnegative_pair(low, high):
    return (
        getattr(low, "is_finite", lambda: False)()
        and getattr(high, "is_finite", lambda: False)()
        and 0 <= low <= high
    )


def _positive_integer_range(low, high):
    return (
        isinstance(low, int)
        and not isinstance(low, bool)
        and isinstance(high, int)
        and not isinstance(high, bool)
        and 1 <= low <= high
    )


def _object(value):
    if not isinstance(value, dict):
        raise ValidationError("invalid assessment payload")
    return value


def _exact_keys(value, expected):
    if set(value) != set(expected):
        raise ValidationError("invalid assessment payload")


def _allowed_keys(value, *, required, allowed):
    if not set(required) <= set(value) or not set(value) <= set(allowed):
        raise ValidationError("invalid assessment payload")


def _code(value):
    if (
        not isinstance(value, str)
        or len(value) > 100
        or CODE_PATTERN.fullmatch(value) is None
    ):
        raise ValidationError("invalid assessment payload")
    return value


def _code_mapping(value, *, expected_keys):
    mapping = _object(value)
    if set(mapping) != set(expected_keys):
        raise ValidationError("invalid assessment payload")
    return {_code(key): _code(option) for key, option in mapping.items()}


def _text(value, *, maximum, required=False):
    if not isinstance(value, str):
        raise ValidationError("invalid assessment payload")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise ValidationError("invalid assessment payload")
    return value


def _attribution_text(value, *, maximum, required=False):
    value = _text(value, maximum=maximum, required=required)
    if (
        EMBEDDED_EMAIL_PATTERN.search(value)
        or EMBEDDED_MAINLAND_MOBILE_PATTERN.search(value)
    ):
        raise ValidationError("invalid assessment payload")
    return value
