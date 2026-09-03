"""Pure validation and canonical compilation for assessment rule releases."""

from collections import Counter
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
import re
import unicodedata

from assessment.contracts import (
    ReleaseBenchmark,
    ReleaseIndustry,
    ReleaseLabeledCode,
    ReleasePublicLabels,
    ReleaseQuestion,
    ReleaseQuestionOption,
    ReleaseScenario,
    ReleaseScopedCode,
    ReleaseService,
    RuleReleaseDraft,
    RuleReleaseSnapshot,
)
from assessment.reporting import RISK_EXPLANATIONS
from assessment.scoring import DIMENSION_ORDER
from assessment_validation import (
    BRANCH_CODES,
    COMPANY_SIZE_CODES,
    QUESTION_CODES,
    ROI_OPTION_CODES,
)


SNAPSHOT_SCHEMA_VERSION = "2.0"
MAX_RULE_SNAPSHOT_BYTES = 1024 * 1024
MAX_RULE_DECIMAL_DIGITS = 256
MAX_RULE_DECIMAL_FIXED_LENGTH = 2048
CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")
RELEASE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[\w.!#$%&'*+/=?^_`{|}~-]+@(?:[\w-]+\.)+[\w-]{2,}(?![\w.-])",
    re.I | re.UNICODE,
)
MOBILE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?86[\s().-]*)?1[3-9](?:[\s().-]*\d){9}(?![\s().-]*\d)"
)
LANDLINE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?86[\s().-]*)?\(?0\d{2,3}\)?[\s().-]*"
    r"(?:\d[\s().-]*){6,7}\d(?![\s().-]*\d)"
)
HOTLINE_PATTERN = re.compile(
    r"(?<!\d)(?:400|800)(?:[\s().-]*\d){7}(?![\s().-]*\d)"
)
WECHAT_PATTERN = re.compile(
    r"(?:微信号\s*[:：]?|微信\s*[:：]|wechat\s*[:：]|weixin\s*[:：]|wxid[_:：-])\s*"
    r"[A-Za-z][A-Za-z0-9_-]{5,19}",
    re.I,
)

OPTION_EXPECTED_SCORES = {f"level_{score}": score for score in range(4)}


def validate_release_draft(draft: RuleReleaseDraft) -> tuple[str, ...]:
    """Pure, total validation with exact nested container/dataclass gates."""
    shape_errors = _shape_errors(draft)
    if shape_errors:
        return shape_errors
    try:
        raw_errors = _legacy_validate_release_draft(draft)
        if raw_errors:
            return raw_errors
        return _legacy_validate_release_draft(normalize_release_draft(draft))
    except (AttributeError, KeyError, TypeError, ValueError, ArithmeticError):
        return ("draft_shape",)


def _shape_errors(draft):
    if type(draft) is not RuleReleaseDraft:
        return ("draft_type",)
    errors = []

    def exact_tuple(value, item_type, error):
        if type(value) is not tuple or any(type(item) is not item_type for item in value):
            errors.append(error)
            return False
        return True

    if exact_tuple(draft.industries, ReleaseIndustry, "industries_shape"):
        for item in draft.industries:
            exact_tuple(item.subbranches, ReleaseLabeledCode, "subbranches_shape")
            exact_tuple(item.departments, ReleaseLabeledCode, "departments_shape")
            exact_tuple(item.pain_points, ReleaseLabeledCode, "pain_points_shape")
    exact_tuple(draft.company_sizes, ReleaseLabeledCode, "company_sizes_shape")
    if exact_tuple(draft.questions, ReleaseQuestion, "questions_shape"):
        for item in draft.questions:
            exact_tuple(item.options, ReleaseQuestionOption, "question_options_shape")
    if type(draft.branch_weights) is not dict or any(
        type(value) is not dict for value in draft.branch_weights.values()
    ):
        errors.append("branch_weights_shape")
    if exact_tuple(draft.benchmarks, ReleaseBenchmark, "benchmarks_shape"):
        if any(type(item.scores) is not dict for item in draft.benchmarks):
            errors.append("benchmark_scores_shape")
    if type(draft.roi_ranges) is not dict or any(
        type(values) is not dict for values in draft.roi_ranges.values()
    ):
        errors.append("roi_ranges_shape")
    elif any(
        type(triple) is not tuple
        for values in draft.roi_ranges.values()
        for triple in values.values()
    ):
        errors.append("roi_triple_shape")
    if exact_tuple(draft.scenarios, ReleaseScenario, "scenarios_shape"):
        for item in draft.scenarios:
            if type(item.minimum_scores) is not dict:
                errors.append("scenario_scores_shape")
            exact_tuple(item.branch_codes, str, "scenario_branches_shape")
            exact_tuple(item.department_links, ReleaseScopedCode, "scenario_links_shape")
            exact_tuple(item.pain_links, ReleaseScopedCode, "scenario_links_shape")
            exact_tuple(item.budget_codes, str, "scenario_budgets_shape")
            exact_tuple(item.risk_codes, str, "scenario_risks_shape")
            for triple in (
                item.efficiency,
                item.loss_improvement,
                item.annual_support_rate,
            ):
                if type(triple) is not tuple:
                    errors.append("scenario_roi_shape")
    if exact_tuple(draft.services, ReleaseService, "services_shape"):
        for item in draft.services:
            for collection in (
                item.deliverables,
                item.implementation_steps,
                item.prerequisites,
                item.not_included,
                item.acceptance,
            ):
                exact_tuple(collection, str, "service_content")
    labels = draft.public_labels
    if type(labels) is not ReleasePublicLabels:
        errors.append("public_labels_shape")
    else:
        for value in (
            labels.risk_labels,
            labels.risk_explanations,
            labels.dimensions,
            labels.maturities,
            labels.integrations,
            labels.roi_groups,
        ):
            if type(value) is not dict:
                errors.append("public_labels_shape")
        if type(labels.roi_options) is not dict or any(
            type(value) is not dict for value in labels.roi_options.values()
        ):
            errors.append("public_labels_shape")
    return tuple(dict.fromkeys(errors))


def _legacy_validate_release_draft(draft: RuleReleaseDraft) -> tuple[str, ...]:
    """Return stable error codes without mutating or consulting persistence."""
    if not isinstance(draft, RuleReleaseDraft):
        return ("draft_type",)
    errors: list[str] = []
    if type(draft.code) is not str or RELEASE_CODE_PATTERN.fullmatch(draft.code) is None:
        errors.append("release_code")
    if not _text(draft.name, 200):
        errors.append("release_name")
    if draft.status != "draft":
        errors.append("release_status")
    if not _exact_int(draft.lock_version, 1):
        errors.append("lock_version")
    if (
        not _exact_int(draft.pain_min_selections, 0)
        or not _exact_int(draft.pain_max_selections, 0)
        or draft.pain_min_selections > draft.pain_max_selections
    ):
        errors.append("pain_selection")

    branch_codes = tuple(item.code for item in draft.industries)
    if set(branch_codes) != set(BRANCH_CODES) or not _unique_ordered(
        draft.industries, lambda item: item.code
    ):
        errors.append("industries")
    branch_departments: dict[str, set[str]] = {}
    branch_pains: dict[str, set[str]] = {}
    for industry in draft.industries:
        if not _code_label(industry.code, industry.label) or not _exact_int(
            industry.sort_order, 1
        ):
            errors.append("industries")
            errors.append("industry")
            continue
        if not _labeled_collection(industry.subbranches):
            errors.append("subbranches")
        if not _labeled_collection(industry.departments):
            errors.append("departments")
        if not _labeled_collection(industry.pain_points):
            errors.append("pain_points")
        branch_departments[industry.code] = {
            item.code for item in industry.departments
        }
        branch_pains[industry.code] = {item.code for item in industry.pain_points}

    if (
        {item.code for item in draft.company_sizes} != set(COMPANY_SIZE_CODES)
        or not _labeled_collection(draft.company_sizes)
    ):
        errors.append("company_sizes")

    question_codes = tuple(item.code for item in draft.questions)
    if set(question_codes) != set(QUESTION_CODES) or not _unique_ordered(
        draft.questions, lambda item: item.code
    ):
        errors.append("questions")
    if Counter(item.dimension for item in draft.questions) != Counter(
        {dimension: 2 for dimension in DIMENSION_ORDER}
    ):
        errors.append("question_dimensions")
    for question in draft.questions:
        if (
            question.dimension not in DIMENSION_ORDER
            or not _text(question.prompt, 500)
            or not _exact_int(question.sort_order, 1)
        ):
            errors.append("question")
        if (
            len(question.options) != 4
            or {option.code for option in question.options}
            != set(OPTION_EXPECTED_SCORES)
            or not _unique_ordered(question.options, lambda option: option.code)
            or any(
                not _exact_int(
                    option.score,
                    OPTION_EXPECTED_SCORES[option.code],
                    OPTION_EXPECTED_SCORES[option.code],
                )
                for option in question.options
            )
        ):
            errors.append("question_options")
        if any(not _text(option.label, 200) for option in question.options):
            errors.append("question_option_labels")

    if set(draft.branch_weights) != set(BRANCH_CODES):
        errors.append("branch_weights")
    else:
        for weights in draft.branch_weights.values():
            if set(weights) != set(DIMENSION_ORDER) or any(
                not _exact_int(value, 0, 100) for value in weights.values()
            ) or sum(weights.values()) != 100:
                errors.append("branch_weights")
                break
    if type(draft.benchmarks) is not tuple or {item.branch_code for item in draft.benchmarks} != set(BRANCH_CODES):
        errors.append("benchmarks")
    for benchmark in draft.benchmarks:
        if not _text(benchmark.label, 200) or set(benchmark.scores) != set(DIMENSION_ORDER) or any(
            not _exact_int(value, 0, 100) for value in benchmark.scores.values()
        ):
            errors.append("benchmark")

    if set(draft.roi_ranges) != set(ROI_OPTION_CODES):
        errors.append("roi_groups")
    else:
        for group, codes in ROI_OPTION_CODES.items():
            values = draft.roi_ranges[group]
            if tuple(values) != tuple(codes) or any(
                not _decimal_triple(triple, unit=(group == "loss_factor"))
                for triple in values.values()
            ):
                errors.append("roi_ranges")
                break

    labels = draft.public_labels
    if type(labels) is not ReleasePublicLabels:
        errors.append("public_labels")
    else:
        domains = (
            (labels.risk_labels, set(RISK_EXPLANATIONS), "risk_labels"),
            (labels.risk_explanations, set(RISK_EXPLANATIONS), "risk_explanations"),
            (labels.dimensions, set(DIMENSION_ORDER), "dimension_labels"),
            (labels.maturities, {"explore", "pilot", "scale", "collaborate"}, "maturity_labels"),
            (labels.integrations, {"low", "medium", "high"}, "integration_labels"),
            (labels.roi_groups, set(ROI_OPTION_CODES), "roi_group_labels"),
        )
        for values, expected_codes, error in domains:
            if (
                type(values) is not dict
                or set(values) != expected_codes
                or any(not _text(value, 500) for value in values.values())
            ):
                errors.append(error)
        if (
            type(labels.roi_options) is not dict
            or set(labels.roi_options) != set(ROI_OPTION_CODES)
        ):
            errors.append("roi_option_labels")
        else:
            for group, expected_codes in ROI_OPTION_CODES.items():
                values = labels.roi_options[group]
                if (
                    type(values) is not dict
                    or set(values) != set(expected_codes)
                    or any(not _text(value, 500) for value in values.values())
                ):
                    errors.append("roi_option_labels")
                    break

    service_codes = tuple(service.code for service in draft.services)
    if type(draft.services) is not tuple or len(draft.services) != 6:
        errors.append("service_cardinality")
    if type(draft.services) is not tuple or not service_codes or len(set(service_codes)) != len(service_codes) or not _strict_orders(
        draft.services
    ):
        errors.append("services")
    for service in draft.services:
        if not _code_label(service.code, service.public_name) or not _text(
            service.category, 100
        ):
            errors.append("service_identity")
        if not _decimal_pair(service.min_budget, service.max_budget) or service.min_budget <= 0:
            errors.append("service_budget")
        if not _integer_range(service.min_weeks, service.max_weeks):
            errors.append("service_weeks")
        if not _exact_int(service.support_days, 0):
            errors.append("service_support_days")
        collections = (
            service.deliverables,
            service.implementation_steps,
            service.prerequisites,
            service.not_included,
            service.acceptance,
        )
        if (
            any(type(collection) is not tuple or not collection for collection in collections)
            or any(not _text(value, 500) for collection in collections for value in collection)
            or any(len(set(collection)) != len(collection) for collection in collections)
        ):
            errors.append("service_content")
        if not _text(service.support_description, 500) or not _text(
            service.public_disclaimer, 500
        ):
            errors.append("service_public_copy")

    scenario_codes = tuple(scenario.code for scenario in draft.scenarios)
    if type(draft.scenarios) is not tuple or len(draft.scenarios) != 13:
        errors.append("scenario_cardinality")
    if type(draft.scenarios) is not tuple or not scenario_codes or len(set(scenario_codes)) != len(scenario_codes) or not _strict_orders(
        draft.scenarios
    ):
        errors.append("scenarios")
    for scenario in draft.scenarios:
        if not _code_label(scenario.code, scenario.public_name) or not _text(
            scenario.category_code, 100
        ) or not _optional_text(scenario.description, 1000):
            errors.append("scenario_identity")
        if type(scenario.fallback_only) is not bool:
            errors.append("scenario_fallback")
        if set(scenario.minimum_scores) != set(DIMENSION_ORDER) or any(
            not _exact_int(value, 0, 100) for value in scenario.minimum_scores.values()
        ):
            errors.append("scenario_thresholds")
        if scenario.integration_level not in {"low", "medium", "high"} or not _integer_range(
            scenario.min_weeks, scenario.max_weeks
        ):
            errors.append("scenario_delivery")
        if type(scenario.branch_codes) is not tuple or not scenario.branch_codes or len(set(scenario.branch_codes)) != len(
            scenario.branch_codes
        ) or any(code not in BRANCH_CODES for code in scenario.branch_codes):
            errors.append("scenario_branches")
        if not scenario.fallback_only and (not scenario.department_links or not scenario.pain_links):
            errors.append("scenario_links")
        for item in scenario.department_links:
            if (
                type(item) is not ReleaseScopedCode
                or item.branch_code not in scenario.branch_codes
                or item.code not in branch_departments.get(item.branch_code, ())
            ):
                errors.append("scenario_department_reference")
        for item in scenario.pain_links:
            if (
                type(item) is not ReleaseScopedCode
                or item.branch_code not in scenario.branch_codes
                or item.code not in branch_pains.get(item.branch_code, ())
            ):
                errors.append("scenario_pain_reference")
        if (
            type(scenario.department_links) is not tuple
            or type(scenario.pain_links) is not tuple
            or not _strict_orders(scenario.department_links)
            or not _strict_orders(scenario.pain_links)
            or len({(item.branch_code, item.code) for item in scenario.department_links})
            != len(scenario.department_links)
            or len({(item.branch_code, item.code) for item in scenario.pain_links})
            != len(scenario.pain_links)
        ):
            errors.append("scenario_links")
        if type(scenario.budget_codes) is not tuple or not scenario.budget_codes or any(
            code not in ROI_OPTION_CODES["budget"] for code in scenario.budget_codes
        ) or len(set(scenario.budget_codes)) != len(scenario.budget_codes):
            errors.append("scenario_budgets")
        if scenario.service_code not in service_codes:
            errors.append("scenario_service_reference")
        if not _decimal_triple(scenario.efficiency, unit=True) or not _decimal_triple(
            scenario.loss_improvement, unit=True
        ) or not _decimal_triple(scenario.annual_support_rate, unit=True):
            errors.append("scenario_roi")
        if type(scenario.risk_codes) is not tuple or not scenario.risk_codes or len(set(scenario.risk_codes)) != len(
            scenario.risk_codes
        ) or any(code not in RISK_EXPLANATIONS for code in scenario.risk_codes):
            errors.append("scenario_risks")
    fallbacks = tuple(item for item in draft.scenarios if item.fallback_only)
    if len(fallbacks) != 1 or fallbacks[0].code != "data_process_foundation":
        errors.append("fallback_policy")
    return tuple(dict.fromkeys(errors))


def validate_canonical_release_json(
    canonical_json, root_code, root_name, pain_min_selections, pain_max_selections
) -> bool:
    """Fail-closed validation used by SQLite release lifecycle triggers."""
    try:
        if (
            type(canonical_json) is not str
            or len(canonical_json.encode("utf-8")) > MAX_RULE_SNAPSHOT_BYTES
        ):
            return False
        payload = json.loads(
            canonical_json,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
        if type(payload) is not dict or json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ) != canonical_json:
            return False
        if set(payload) != {
            "schema_version",
            "release",
            "industries",
            "company_sizes",
            "questions",
            "branch_weights",
            "benchmarks",
            "roi_ranges",
            "public_labels",
            "scenarios",
            "services",
        } or payload["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
            return False
        release = payload["release"]
        if not _canonical_mapping(release, {"code", "name", "pain_selection"}):
            return False
        pain = release["pain_selection"]
        if not _canonical_mapping(pain, {"minimum", "maximum"}):
            return False
        if (
            release["code"] != root_code
            or release["name"] != root_name
            or pain["minimum"] != pain_min_selections
            or pain["maximum"] != pain_max_selections
            or not _canonical_int(pain["minimum"], 0)
            or not _canonical_int(pain["maximum"], pain["minimum"])
            or not _canonical_code(release["code"], release=True)
            or not _canonical_text(release["name"], 200)
        ):
            return False

        industries = payload["industries"]
        if type(industries) is not list or len(industries) != 4:
            return False
        if [item.get("code") for item in industries if type(item) is dict] and (
            len({item.get("code") for item in industries if type(item) is dict}) != 4
            or {item.get("code") for item in industries if type(item) is dict}
            != set(BRANCH_CODES)
        ):
            return False
        branch_departments = {}
        branch_pains = {}
        for industry in industries:
            if not _canonical_mapping(
                industry, {"code", "label", "subbranches", "departments", "pain_points"}
            ) or not _canonical_code_label(industry["code"], industry["label"]):
                return False
            for collection_name in ("subbranches", "departments", "pain_points"):
                if not _canonical_labeled_list(industry[collection_name]):
                    return False
            branch_departments[industry["code"]] = {
                item["code"] for item in industry["departments"]
            }
            branch_pains[industry["code"]] = {
                item["code"] for item in industry["pain_points"]
            }

        sizes = payload["company_sizes"]
        if not _canonical_labeled_list(sizes) or {
            item["code"] for item in sizes
        } != set(COMPANY_SIZE_CODES):
            return False

        questions = payload["questions"]
        if (
            type(questions) is not list
            or len(questions) != 12
            or any(type(item) is not dict for item in questions)
            or {item.get("code") for item in questions} != set(QUESTION_CODES)
        ):
            return False
        dimensions = []
        for question in questions:
            if not _canonical_mapping(
                question, {"code", "dimension", "prompt", "options"}
            ) or question["dimension"] not in DIMENSION_ORDER or not _canonical_text(
                question["prompt"], 500
            ):
                return False
            dimensions.append(question["dimension"])
            options = question["options"]
            if (
                type(options) is not list
                or len(options) != 4
                or any(type(option) is not dict for option in options)
                or {option.get("code") for option in options}
                != set(OPTION_EXPECTED_SCORES)
            ):
                return False
            for option in options:
                if not _canonical_mapping(option, {"code", "label", "score"}):
                    return False
                if (
                    not _canonical_int(
                        option["score"],
                        OPTION_EXPECTED_SCORES[option["code"]],
                        OPTION_EXPECTED_SCORES[option["code"]],
                    )
                    or not _canonical_text(option["label"], 200)
                ):
                    return False
        if Counter(dimensions) != Counter(
            {dimension: 2 for dimension in DIMENSION_ORDER}
        ):
            return False

        weights = payload["branch_weights"]
        if not _canonical_mapping(weights, set(BRANCH_CODES)):
            return False
        for values in weights.values():
            if not _canonical_mapping(values, set(DIMENSION_ORDER)) or any(
                not _canonical_int(value, 0, 100) for value in values.values()
            ) or sum(values.values()) != 100:
                return False

        benchmarks = payload["benchmarks"]
        if type(benchmarks) is not list or len(benchmarks) != 4 or {
            item.get("branch_code") for item in benchmarks if type(item) is dict
        } != set(BRANCH_CODES):
            return False
        for benchmark in benchmarks:
            if not _canonical_mapping(benchmark, {"branch_code", "label", "scores"}):
                return False
            if not _canonical_text(benchmark["label"], 200) or not _canonical_mapping(
                benchmark["scores"], set(DIMENSION_ORDER)
            ) or any(
                not _canonical_int(value, 0, 100)
                for value in benchmark["scores"].values()
            ):
                return False

        ranges = payload["roi_ranges"]
        if not _canonical_mapping(ranges, set(ROI_OPTION_CODES)):
            return False
        for group, codes in ROI_OPTION_CODES.items():
            if not _canonical_mapping(ranges[group], set(codes)) or any(
                not _canonical_decimal_triple(
                    triple, unit=(group == "loss_factor")
                )
                for triple in ranges[group].values()
            ):
                return False

        if not _canonical_public_labels(payload["public_labels"]):
            return False

        services = payload["services"]
        if type(services) is not list or len(services) != 6:
            return False
        service_codes = []
        for service in services:
            if not _canonical_mapping(
                service,
                {
                    "code", "category", "public_name", "budget", "weeks",
                    "deliverables", "implementation_steps", "prerequisites",
                    "not_included", "acceptance", "support_days",
                    "support_description", "public_disclaimer",
                },
            ):
                return False
            if not _canonical_code_label(service["code"], service["public_name"]) or not _canonical_text(
                service["category"], 100
            ):
                return False
            service_codes.append(service["code"])
            if not _canonical_decimal_pair(service["budget"], positive=True) or not _canonical_int_pair(
                service["weeks"], minimum=1
            ) or not _canonical_int(service["support_days"], 0):
                return False
            for collection in (
                "deliverables", "implementation_steps", "prerequisites",
                "not_included", "acceptance",
            ):
                values = service[collection]
                if type(values) is not list or not values or len(set(values)) != len(values) or any(
                    not _canonical_text(value, 500) for value in values
                ):
                    return False
            if not _canonical_text(service["support_description"], 500) or not _canonical_text(
                service["public_disclaimer"], 500
            ):
                return False
        if len(set(service_codes)) != 6:
            return False

        scenarios = payload["scenarios"]
        if type(scenarios) is not list or len(scenarios) != 13:
            return False
        scenario_codes = []
        fallback_codes = []
        for scenario in scenarios:
            if not _canonical_mapping(
                scenario,
                {
                    "code", "category_code", "public_name", "description",
                    "branch_codes", "department_links", "pain_links",
                    "minimum_scores", "integration_level", "budget_codes",
                    "weeks", "efficiency", "loss_improvement",
                    "annual_support_rate", "risk_codes", "service_code",
                    "fallback_only",
                },
            ):
                return False
            if not _canonical_code_label(scenario["code"], scenario["public_name"]) or not _canonical_text(
                scenario["category_code"], 100
            ) or not _canonical_optional_text(scenario["description"], 1000):
                return False
            scenario_codes.append(scenario["code"])
            if type(scenario["fallback_only"]) is not bool:
                return False
            if scenario["fallback_only"]:
                fallback_codes.append(scenario["code"])
            branches = scenario["branch_codes"]
            if type(branches) is not list or not branches or len(set(branches)) != len(branches) or any(
                branch not in BRANCH_CODES for branch in branches
            ):
                return False
            for name, authority in (
                ("department_links", branch_departments),
                ("pain_links", branch_pains),
            ):
                links = scenario[name]
                if type(links) is not list or len(
                    {(item.get("branch_code"), item.get("code")) for item in links if type(item) is dict}
                ) != len(links):
                    return False
                for link in links:
                    if not _canonical_mapping(link, {"branch_code", "code"}) or link[
                        "branch_code"
                    ] not in branches or link["code"] not in authority.get(link["branch_code"], ()):
                        return False
                if not scenario["fallback_only"] and not links:
                    return False
            if not _canonical_mapping(scenario["minimum_scores"], set(DIMENSION_ORDER)) or any(
                not _canonical_int(value, 0, 100)
                for value in scenario["minimum_scores"].values()
            ):
                return False
            if scenario["integration_level"] not in {"low", "medium", "high"} or not _canonical_int_pair(
                scenario["weeks"], minimum=1
            ):
                return False
            budgets = scenario["budget_codes"]
            if type(budgets) is not list or not budgets or len(set(budgets)) != len(budgets) or any(
                code not in ROI_OPTION_CODES["budget"] for code in budgets
            ):
                return False
            if scenario["service_code"] not in service_codes:
                return False
            if any(
                not _canonical_decimal_triple(scenario[field], unit=True)
                for field in ("efficiency", "loss_improvement", "annual_support_rate")
            ):
                return False
            risks = scenario["risk_codes"]
            if type(risks) is not list or not risks or len(set(risks)) != len(risks) or any(
                code not in RISK_EXPLANATIONS for code in risks
            ):
                return False
        return len(set(scenario_codes)) == 13 and fallback_codes == [
            "data_process_foundation"
        ]
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        ArithmeticError,
        RecursionError,
    ):
        return False


def _canonical_mapping(value, keys):
    return type(value) is dict and set(value) == set(keys)


def _canonical_int(value, minimum, maximum=None):
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def _canonical_code(value, *, release=False):
    return type(value) is str and (
        RELEASE_CODE_PATTERN if release else CODE_PATTERN
    ).fullmatch(value) is not None


def _canonical_code_label(code, label):
    return _canonical_code(code) and _canonical_text(label, 200)


def _canonical_text(value, maximum):
    return _text(value, maximum) and normalize_public_text(value) == value


def _canonical_labeled_list(values):
    return type(values) is list and bool(values) and len(
        {item.get("code") for item in values if type(item) is dict}
    ) == len(values) and all(
        _canonical_mapping(item, {"code", "label"})
        and _canonical_code_label(item["code"], item["label"])
        for item in values
    )


def _canonical_decimal(value):
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_RULE_DECIMAL_FIXED_LENGTH
    ):
        return None
    try:
        decimal = Decimal(value)
    except ArithmeticError:
        return None
    return decimal if _bounded_decimal(decimal) and _decimal(decimal) == value else None


def _canonical_decimal_pair(values, *, positive=False):
    if type(values) is not list or len(values) != 2:
        return False
    low, high = map(_canonical_decimal, values)
    return low is not None and high is not None and (low > 0 if positive else low >= 0) and low <= high


def _canonical_decimal_triple(values, *, unit):
    if type(values) is not list or len(values) != 3:
        return False
    parsed = tuple(_canonical_decimal(value) for value in values)
    return all(value is not None for value in parsed) and Decimal(0) <= parsed[0] <= parsed[1] <= parsed[2] and (
        not unit or parsed[2] <= Decimal(1)
    )


def _canonical_int_pair(values, *, minimum):
    return type(values) is list and len(values) == 2 and _canonical_int(
        values[0], minimum
    ) and _canonical_int(values[1], values[0])


def _canonical_optional_text(value, maximum):
    return value == "" or _canonical_text(value, maximum)


def _canonical_public_labels(labels):
    if not _canonical_mapping(
        labels,
        {
            "risk_labels", "risk_explanations", "dimensions", "maturities",
            "integrations", "roi_groups", "roi_options",
        },
    ):
        return False
    domains = (
        ("risk_labels", set(RISK_EXPLANATIONS)),
        ("risk_explanations", set(RISK_EXPLANATIONS)),
        ("dimensions", set(DIMENSION_ORDER)),
        ("maturities", {"explore", "pilot", "scale", "collaborate"}),
        ("integrations", {"low", "medium", "high"}),
        ("roi_groups", set(ROI_OPTION_CODES)),
    )
    for name, codes in domains:
        if not _canonical_mapping(labels[name], codes) or any(
            not _canonical_text(value, 500) for value in labels[name].values()
        ):
            return False
    options = labels["roi_options"]
    return _canonical_mapping(options, set(ROI_OPTION_CODES)) and all(
        _canonical_mapping(options[group], set(codes))
        and all(_canonical_text(value, 500) for value in options[group].values())
        for group, codes in ROI_OPTION_CODES.items()
    )


def normalize_public_text(value: str) -> str:
    """Canonicalize accepted public copy without changing identifier codes."""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def normalize_release_draft(draft: RuleReleaseDraft) -> RuleReleaseDraft:
    """Return a recursively NFKC/whitespace-normalized release draft."""
    labels = draft.public_labels

    def mapping(values):
        return {code: normalize_public_text(label) for code, label in values.items()}

    normalized_labels = replace(
        labels,
        risk_labels=mapping(labels.risk_labels),
        risk_explanations=mapping(labels.risk_explanations),
        dimensions=mapping(labels.dimensions),
        maturities=mapping(labels.maturities),
        integrations=mapping(labels.integrations),
        roi_groups=mapping(labels.roi_groups),
        roi_options={group: mapping(values) for group, values in labels.roi_options.items()},
    )
    industries = tuple(
        replace(
            item,
            label=normalize_public_text(item.label),
            subbranches=tuple(
                replace(value, label=normalize_public_text(value.label))
                for value in item.subbranches
            ),
            departments=tuple(
                replace(value, label=normalize_public_text(value.label))
                for value in item.departments
            ),
            pain_points=tuple(
                replace(value, label=normalize_public_text(value.label))
                for value in item.pain_points
            ),
        )
        for item in draft.industries
    )
    questions = tuple(
        replace(
            item,
            prompt=normalize_public_text(item.prompt),
            options=tuple(
                replace(option, label=normalize_public_text(option.label))
                for option in item.options
            ),
        )
        for item in draft.questions
    )
    scenarios = tuple(
        replace(
            item,
            public_name=normalize_public_text(item.public_name),
            description=normalize_public_text(item.description) if item.description else "",
        )
        for item in draft.scenarios
    )
    services = tuple(
        replace(
            item,
            public_name=normalize_public_text(item.public_name),
            deliverables=tuple(map(normalize_public_text, item.deliverables)),
            implementation_steps=tuple(map(normalize_public_text, item.implementation_steps)),
            prerequisites=tuple(map(normalize_public_text, item.prerequisites)),
            not_included=tuple(map(normalize_public_text, item.not_included)),
            acceptance=tuple(map(normalize_public_text, item.acceptance)),
            support_description=normalize_public_text(item.support_description),
            public_disclaimer=normalize_public_text(item.public_disclaimer),
        )
        for item in draft.services
    )
    return replace(
        draft,
        name=normalize_public_text(draft.name),
        industries=industries,
        company_sizes=tuple(
            replace(item, label=normalize_public_text(item.label))
            for item in draft.company_sizes
        ),
        questions=questions,
        benchmarks=tuple(
            replace(item, label=normalize_public_text(item.label))
            for item in draft.benchmarks
        ),
        scenarios=scenarios,
        services=services,
        public_labels=normalized_labels,
    )


def compile_release_snapshot(draft: RuleReleaseDraft) -> RuleReleaseSnapshot:
    """Compile deterministic UTF-8 JSON with Decimal values encoded as strings."""
    errors = validate_release_draft(draft)
    if errors:
        raise ValueError("invalid rule release: " + ",".join(errors))
    draft = normalize_release_draft(draft)
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "release": {
            "code": draft.code,
            "name": draft.name,
            "pain_selection": {
                "minimum": draft.pain_min_selections,
                "maximum": draft.pain_max_selections,
            },
        },
        "industries": [
            {
                "code": item.code,
                "label": item.label,
                "subbranches": [_labeled_payload(value) for value in item.subbranches],
                "departments": [_labeled_payload(value) for value in item.departments],
                "pain_points": [_labeled_payload(value) for value in item.pain_points],
            }
            for item in draft.industries
        ],
        "company_sizes": [_labeled_payload(item) for item in draft.company_sizes],
        "questions": [
            {
                "code": item.code,
                "dimension": item.dimension,
                "prompt": item.prompt,
                "options": [
                    {"code": option.code, "label": option.label, "score": option.score}
                    for option in item.options
                ],
            }
            for item in draft.questions
        ],
        "branch_weights": {
            code: {dimension: values[dimension] for dimension in DIMENSION_ORDER}
            for code, values in draft.branch_weights.items()
        },
        "benchmarks": [
            {
                "branch_code": item.branch_code,
                "label": item.label,
                "scores": {dimension: item.scores[dimension] for dimension in DIMENSION_ORDER},
            }
            for item in draft.benchmarks
        ],
        "roi_ranges": {
            group: {
                code: [_decimal(value) for value in triple]
                for code, triple in values.items()
            }
            for group, values in draft.roi_ranges.items()
        },
        "public_labels": {
            "risk_labels": dict(draft.public_labels.risk_labels),
            "risk_explanations": dict(draft.public_labels.risk_explanations),
            "dimensions": dict(draft.public_labels.dimensions),
            "maturities": dict(draft.public_labels.maturities),
            "integrations": dict(draft.public_labels.integrations),
            "roi_groups": dict(draft.public_labels.roi_groups),
            "roi_options": {
                group: dict(values)
                for group, values in draft.public_labels.roi_options.items()
            },
        },
        "scenarios": [_scenario_payload(item) for item in draft.scenarios],
        "services": [_service_payload(item) for item in draft.services],
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    if len(canonical.encode("utf-8")) > MAX_RULE_SNAPSHOT_BYTES:
        raise ValueError("invalid rule release: snapshot_size")
    return RuleReleaseSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        canonical_json=canonical,
        sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _scenario_payload(item):
    return {
        "code": item.code,
        "category_code": item.category_code,
        "public_name": item.public_name,
        "description": item.description,
        "branch_codes": list(item.branch_codes),
        "department_links": [
            {"branch_code": link.branch_code, "code": link.code}
            for link in item.department_links
        ],
        "pain_links": [
            {"branch_code": link.branch_code, "code": link.code}
            for link in item.pain_links
        ],
        "minimum_scores": {dimension: item.minimum_scores[dimension] for dimension in DIMENSION_ORDER},
        "integration_level": item.integration_level,
        "budget_codes": list(item.budget_codes),
        "weeks": [item.min_weeks, item.max_weeks],
        "efficiency": [_decimal(value) for value in item.efficiency],
        "loss_improvement": [_decimal(value) for value in item.loss_improvement],
        "annual_support_rate": [_decimal(value) for value in item.annual_support_rate],
        "risk_codes": list(item.risk_codes),
        "service_code": item.service_code,
        "fallback_only": item.fallback_only,
    }


def _service_payload(item):
    return {
        "code": item.code,
        "category": item.category,
        "public_name": item.public_name,
        "budget": [_decimal(item.min_budget), _decimal(item.max_budget)],
        "weeks": [item.min_weeks, item.max_weeks],
        "deliverables": list(item.deliverables),
        "implementation_steps": list(item.implementation_steps),
        "prerequisites": list(item.prerequisites),
        "not_included": list(item.not_included),
        "acceptance": list(item.acceptance),
        "support_days": item.support_days,
        "support_description": item.support_description,
        "public_disclaimer": item.public_disclaimer,
    }


def _labeled_payload(item):
    return {"code": item.code, "label": item.label}


def _decimal(value):
    if value == 0:
        return "0"
    sign, digits, exponent = value.as_tuple()
    digits = list(digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    return format(Decimal((sign, tuple(digits), exponent)), "f")


def _exact_int(value, minimum, maximum=None):
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def _integer_range(low, high):
    return _exact_int(low, 1) and _exact_int(high, low)


def _decimal_triple(values, *, unit):
    return type(values) is tuple and len(values) == 3 and all(
        _bounded_decimal(value) for value in values
    ) and Decimal(0) <= values[0] <= values[1] <= values[2] and (
        not unit or values[2] <= Decimal(1)
    )


def _decimal_pair(low, high):
    return (
        _bounded_decimal(low)
        and _bounded_decimal(high)
        and Decimal(0) <= low <= high
    )


def _bounded_decimal(value):
    if type(value) is not Decimal or not value.is_finite():
        return False
    sign, raw_digits, exponent = value.as_tuple()
    digits = list(raw_digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if max(1, len(digits)) > MAX_RULE_DECIMAL_DIGITS:
        return False
    if not digits:
        fixed_length = 1 + sign
    elif exponent >= 0:
        fixed_length = sign + len(digits) + exponent
    else:
        point = len(digits) + exponent
        fixed_length = (
            sign + len(digits) + 1
            if point > 0
            else sign + 2 + (-point) + len(digits)
        )
    return fixed_length <= MAX_RULE_DECIMAL_FIXED_LENGTH


def _code_label(code, label):
    return type(code) is str and CODE_PATTERN.fullmatch(code) is not None and _text(label, 200)


def _labeled_collection(items):
    return type(items) is tuple and bool(items) and _unique_ordered(items, lambda item: item.code) and all(
        _code_label(item.code, item.label) and _exact_int(item.sort_order, 1)
        for item in items
    )


def _unique_ordered(items, code):
    return type(items) is tuple and len({code(item) for item in items}) == len(items) and _strict_orders(items)


def _strict_orders(items):
    return all(
        type(item.sort_order) is int and item.sort_order == expected
        for expected, item in enumerate(items, 1)
    )


def _optional_text(value, maximum):
    return value == "" or _text(value, maximum)


def _text(value, maximum):
    if type(value) is not str:
        return False
    normalized = unicodedata.normalize("NFKC", value)
    if not normalized.strip() or len(normalized) > maximum:
        return False
    if any(unicodedata.category(char).startswith("C") for char in normalized):
        return False
    return not any(
        pattern.search(normalized)
        for pattern in (
            EMAIL_PATTERN,
            MOBILE_PATTERN,
            LANDLINE_PATTERN,
            HOTLINE_PATTERN,
            WECHAT_PATTERN,
        )
    )
