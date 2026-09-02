"""Immutable boundary types shared by assessment rules and repositories."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


ReportSnapshot = dict[str, object]


@dataclass(frozen=True)
class QuestionOption:
    code: str
    label: str
    score: int


@dataclass(frozen=True)
class Question:
    code: str
    dimension: str
    prompt: str
    options: tuple[QuestionOption, ...]


@dataclass(frozen=True)
class AssessmentProfile:
    branch_code: str
    subbranch_code: str
    department_code: str
    company_size_code: str
    pain_codes: tuple[str, ...]
    answers: Mapping[str, str]
    roi_choices: Mapping[str, str]


@dataclass(frozen=True)
class AssessmentCatalog:
    version_id: int
    version_code: str
    subbranch_codes: tuple[str, ...]
    department_codes: tuple[str, ...]
    pain_codes: tuple[str, ...]
    questions: tuple[Question, ...]
    branch_weights: Mapping[str, Mapping[str, int]]
    reference_lines: Mapping[str, Mapping[str, int]]


class AssessmentInputError(ValueError):
    """Raised when an assessment profile or catalog cannot be scored."""


@dataclass(frozen=True)
class ScoreResult:
    dimension_scores: Mapping[str, int]
    overall_score: int
    maturity_code: str
    strongest_dimension: str
    weakest_dimension: str


@dataclass(frozen=True)
class Scenario:
    code: str
    category_code: str
    branch_codes: tuple[str, ...]
    department_codes: tuple[str, ...]
    pain_codes: tuple[str, ...]
    minimum_scores: Mapping[str, int]
    integration_level: str
    budget_codes: tuple[str, ...]
    min_weeks: int
    max_weeks: int
    efficiency: tuple[Decimal, Decimal, Decimal]
    loss_improvement: tuple[Decimal, Decimal, Decimal]
    annual_support_rate: tuple[Decimal, Decimal, Decimal]
    risk_codes: tuple[str, ...]
    service_code: str
    sort_order: int
    fallback_only: bool = False


@dataclass(frozen=True)
class ServicePackage:
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


@dataclass(frozen=True)
class ScenarioMatch:
    scenario: Scenario
    service: ServicePackage
    total_score: int
    components: Mapping[str, int]
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RoiBand:
    band_code: str
    current_annual_cost: Decimal
    labor_savings: Decimal
    loss_savings: Decimal
    annual_savings: Decimal
    initial_investment: Decimal
    annual_support: Decimal
    payback_months: Decimal | None
    three_year_support: Decimal
    three_year_net: Decimal


@dataclass(frozen=True)
class RoiResult:
    conservative: RoiBand
    midpoint: RoiBand
    ideal: RoiBand


@dataclass(frozen=True)
class Contact:
    company_name: str
    contact_name: str
    phone: str
    email: str = ""
    wechat: str = ""


@dataclass(frozen=True)
class Consent:
    accepted: bool
    policy_version: str
    source: str = "website_assessment"


@dataclass(frozen=True)
class Attribution:
    source: str
    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""


@dataclass(frozen=True)
class CompletionRequest:
    submission_key: str
    profile: AssessmentProfile
    contact: Contact
    consent: Consent
    attribution: Attribution


@dataclass(frozen=True)
class CompletionResult:
    assessment_id: int
    lead_id: int
    created: bool


@dataclass(frozen=True)
class ReleaseLabeledCode:
    code: str
    label: str
    sort_order: int


@dataclass(frozen=True)
class ReleaseIndustry:
    code: str
    label: str
    sort_order: int
    subbranches: tuple[ReleaseLabeledCode, ...]
    departments: tuple[ReleaseLabeledCode, ...]
    pain_points: tuple[ReleaseLabeledCode, ...]


@dataclass(frozen=True)
class ReleaseQuestionOption:
    code: str
    label: str
    score: int
    sort_order: int


@dataclass(frozen=True)
class ReleaseQuestion:
    code: str
    dimension: str
    prompt: str
    sort_order: int
    options: tuple[ReleaseQuestionOption, ...]


@dataclass(frozen=True)
class ReleaseBenchmark:
    branch_code: str
    label: str
    scores: Mapping[str, int]


@dataclass(frozen=True)
class ReleaseScopedCode:
    branch_code: str
    code: str
    sort_order: int


@dataclass(frozen=True)
class ReleaseScenario:
    code: str
    category_code: str
    public_name: str
    description: str
    branch_codes: tuple[str, ...]
    department_links: tuple[ReleaseScopedCode, ...]
    pain_links: tuple[ReleaseScopedCode, ...]
    minimum_scores: Mapping[str, int]
    integration_level: str
    budget_codes: tuple[str, ...]
    min_weeks: int
    max_weeks: int
    efficiency: tuple[Decimal, Decimal, Decimal]
    loss_improvement: tuple[Decimal, Decimal, Decimal]
    annual_support_rate: tuple[Decimal, Decimal, Decimal]
    risk_codes: tuple[str, ...]
    service_code: str
    sort_order: int
    fallback_only: bool = False


@dataclass(frozen=True)
class ReleaseService:
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
    sort_order: int


@dataclass(frozen=True)
class ReleasePublicLabels:
    risk_labels: Mapping[str, str]
    risk_explanations: Mapping[str, str]
    dimensions: Mapping[str, str]
    maturities: Mapping[str, str]
    integrations: Mapping[str, str]
    roi_groups: Mapping[str, str]
    roi_options: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class RuleReleaseDraft:
    id: int
    code: str
    name: str
    status: str
    copied_from_id: int | None
    lock_version: int
    pain_min_selections: int
    pain_max_selections: int
    industries: tuple[ReleaseIndustry, ...]
    company_sizes: tuple[ReleaseLabeledCode, ...]
    questions: tuple[ReleaseQuestion, ...]
    branch_weights: Mapping[str, Mapping[str, int]]
    benchmarks: tuple[ReleaseBenchmark, ...]
    roi_ranges: Mapping[str, Mapping[str, tuple[Decimal, Decimal, Decimal]]]
    scenarios: tuple[ReleaseScenario, ...]
    services: tuple[ReleaseService, ...]
    public_labels: ReleasePublicLabels
    created_at: str
    updated_at: str
    published_at: str | None = None


@dataclass(frozen=True)
class RuleReleaseSnapshot:
    schema_version: str
    canonical_json: str
    sha256: str


@dataclass(frozen=True)
class RuleReleaseFilters:
    status: str | None = None


@dataclass(frozen=True)
class RuleReleaseRow:
    id: int
    code: str
    name: str
    status: str
    lock_version: int
    updated_at: str
