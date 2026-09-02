"""Read-only draft previews through the production assessment rule engine."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from assessment.contracts import (
    AssessmentCatalog,
    AssessmentInputError,
    Question,
    QuestionOption,
    RuleReleaseDraft,
    Scenario,
    ServicePackage,
)
from assessment.matching import match_scenarios
from assessment.reporting import ReportPublicCopy, build_report_snapshot
from assessment.roi import calculate_roi
from assessment.scoring import score_assessment
from assessment_repository import build_public_config
from assessment_validation import parse_preview_payload, validate_profile_membership
from rule_release_repository import load_release_draft
from rule_release_validation import compile_release_snapshot
from validation import ValidationError


@dataclass(frozen=True)
class PreviewRequest:
    """Exact immutable inputs for one draft preview."""

    branch_code: str
    subbranch_code: str
    department_code: str
    company_size_code: str
    pain_codes: tuple[str, ...]
    answers: Mapping[str, str]
    roi_choices: Mapping[str, str]

    def __post_init__(self):
        codes = (
            self.branch_code,
            self.subbranch_code,
            self.department_code,
            self.company_size_code,
        )
        if any(type(value) is not str for value in codes):
            raise TypeError("invalid preview request")
        if type(self.pain_codes) is not tuple or any(
            type(value) is not str for value in self.pain_codes
        ):
            raise TypeError("invalid preview request")
        if not isinstance(self.answers, Mapping) or not isinstance(
            self.roi_choices, Mapping
        ):
            raise TypeError("invalid preview request")
        if any(
            type(key) is not str or type(value) is not str
            for mapping in (self.answers, self.roi_choices)
            for key, value in mapping.items()
        ):
            raise TypeError("invalid preview request")
        object.__setattr__(self, "answers", MappingProxyType(dict(self.answers)))
        object.__setattr__(
            self, "roi_choices", MappingProxyType(dict(self.roi_choices))
        )


@dataclass(frozen=True)
class ReleasePreview:
    """JSON-compatible result of the production preview pipeline."""

    public_config: Mapping
    scores: Mapping[str, object]
    recommendations: tuple[Mapping, ...]
    roi: Mapping
    report_snapshot: Mapping
    services: tuple["PreviewService", ...]


@dataclass(frozen=True)
class PreviewService:
    """Release-owned service copy used only by the admin preview UI."""

    code: str
    category: str
    public_name: str
    min_budget: Decimal
    max_budget: Decimal
    min_weeks: int
    max_weeks: int
    deliverables: tuple[str, ...]
    implementation_steps: tuple[str, ...]
    prerequisites: tuple[str, ...]
    not_included: tuple[str, ...]
    acceptance: tuple[str, ...]
    support_days: int
    support_description: str
    public_disclaimer: str


def preview_release(release_id: int, request: PreviewRequest) -> ReleasePreview:
    """Compile and preview one draft without persisting any assessment domain row."""
    if type(release_id) is not int or release_id <= 0:
        raise ValueError("invalid rule release preview")
    if type(request) is not PreviewRequest:
        raise TypeError("invalid preview request")
    try:
        draft = load_release_draft(release_id)
        compile_release_snapshot(draft)
        catalog = _draft_catalog(draft, request.branch_code)
        public_config = _draft_public_config(draft, catalog, request.branch_code)
        profile = parse_preview_payload(_preview_payload(request))
        validate_profile_membership(profile, catalog, public_config)
        scores = score_assessment(catalog, profile)
        scenarios = _draft_scenarios(draft, request.branch_code)
        services = _draft_services(draft)
        matches = match_scenarios(profile, scores, scenarios, services)
        primary = matches[0]
        roi = calculate_roi(
            profile.roi_choices,
            draft.roi_ranges,
            primary.scenario,
            primary.service,
        )
        report = build_report_snapshot(
            profile,
            scores,
            matches,
            roi,
            catalog,
            draft.roi_ranges,
            public_copy=ReportPublicCopy(draft.public_labels.risk_explanations),
        )
    except (AssessmentInputError, LookupError, ValidationError, ValueError) as error:
        raise ValueError("invalid rule release preview") from error
    return ReleasePreview(
        public_config=public_config,
        scores=report["scores"],
        recommendations=tuple(report["recommendations"]),
        roi=report["roi"],
        report_snapshot=report,
        services=_preview_services(draft, matches),
    )


def _preview_services(draft, matches):
    selected_codes = tuple(dict.fromkeys(match.service.code for match in matches))
    by_code = {service.code: service for service in draft.services}
    return tuple(
        PreviewService(
            code=service.code,
            category=service.category,
            public_name=service.public_name,
            min_budget=service.min_budget,
            max_budget=service.max_budget,
            min_weeks=service.min_weeks,
            max_weeks=service.max_weeks,
            deliverables=tuple(service.deliverables),
            implementation_steps=tuple(service.implementation_steps),
            prerequisites=tuple(service.prerequisites),
            not_included=tuple(service.not_included),
            acceptance=tuple(service.acceptance),
            support_days=service.support_days,
            support_description=service.support_description,
            public_disclaimer=service.public_disclaimer,
        )
        for code in selected_codes
        for service in (by_code[code],)
    )


def _preview_payload(request: PreviewRequest) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "profile": {
            "branch_code": request.branch_code,
            "subbranch_code": request.subbranch_code,
            "department_code": request.department_code,
            "company_size_code": request.company_size_code,
            "pain_codes": list(request.pain_codes),
        },
        "answers": dict(request.answers),
        "roi_choices": dict(request.roi_choices),
    }


def _draft_catalog(draft: RuleReleaseDraft, branch_code: str) -> AssessmentCatalog:
    industry = _industry(draft, branch_code)
    return AssessmentCatalog(
        version_id=draft.id,
        version_code=draft.code,
        subbranch_codes=tuple(item.code for item in industry.subbranches),
        department_codes=tuple(item.code for item in industry.departments),
        pain_codes=tuple(item.code for item in industry.pain_points),
        questions=tuple(
            Question(
                code=item.code,
                dimension=item.dimension,
                prompt=item.prompt,
                options=tuple(
                    QuestionOption(
                        code=option.code,
                        label=option.label,
                        score=option.score,
                    )
                    for option in item.options
                ),
            )
            for item in draft.questions
        ),
        branch_weights={
            code: dict(weights) for code, weights in draft.branch_weights.items()
        },
        reference_lines={
            item.branch_code: dict(item.scores) for item in draft.benchmarks
        },
    )


def _draft_public_config(
    draft: RuleReleaseDraft,
    catalog: AssessmentCatalog,
    branch_code: str,
) -> dict[str, object]:
    industry = _industry(draft, branch_code)
    reference = next(
        item for item in draft.benchmarks if item.branch_code == branch_code
    )
    labeled = lambda items: [
        {"code": item.code, "label": item.label} for item in items
    ]
    return build_public_config(
        catalog,
        branch={"code": industry.code, "label": industry.label},
        subbranches=labeled(industry.subbranches),
        departments=labeled(industry.departments),
        pain_points=labeled(industry.pain_points),
        company_sizes=labeled(draft.company_sizes),
        pain_selection={
            "minimum": draft.pain_min_selections,
            "maximum": draft.pain_max_selections,
        },
        roi_options={
            group: list(options) for group, options in draft.roi_ranges.items()
        },
        reference_label=reference.label,
    )


def _draft_scenarios(
    draft: RuleReleaseDraft, branch_code: str
) -> tuple[Scenario, ...]:
    return tuple(
        Scenario(
            code=item.code,
            category_code=item.category_code,
            branch_codes=tuple(item.branch_codes),
            department_codes=tuple(
                link.code
                for link in item.department_links
                if link.branch_code == branch_code
            ),
            pain_codes=tuple(
                link.code for link in item.pain_links if link.branch_code == branch_code
            ),
            minimum_scores=dict(item.minimum_scores),
            integration_level=item.integration_level,
            budget_codes=tuple(item.budget_codes),
            min_weeks=item.min_weeks,
            max_weeks=item.max_weeks,
            efficiency=tuple(item.efficiency),
            loss_improvement=tuple(item.loss_improvement),
            annual_support_rate=tuple(item.annual_support_rate),
            risk_codes=tuple(item.risk_codes),
            service_code=item.service_code,
            sort_order=item.sort_order,
            fallback_only=item.fallback_only,
        )
        for item in draft.scenarios
    )


def _draft_services(draft: RuleReleaseDraft) -> tuple[ServicePackage, ...]:
    return tuple(
        ServicePackage(
            code=item.code,
            category=item.category,
            public_name=item.public_name,
            min_budget=item.min_budget,
            max_budget=item.max_budget,
            min_weeks=item.min_weeks,
            max_weeks=item.max_weeks,
            deliverables=tuple(item.deliverables),
            implementation_steps=tuple(item.implementation_steps),
            prerequisites=tuple(item.prerequisites),
            not_included=tuple(item.not_included),
            acceptance=tuple(item.acceptance),
            support_days=item.support_days,
        )
        for item in draft.services
    )


def _industry(draft: RuleReleaseDraft, branch_code: str):
    industry = next(
        (item for item in draft.industries if item.code == branch_code), None
    )
    if industry is None:
        raise ValueError("invalid rule release preview")
    return industry
