"""Immutable boundary types shared by assessment rules and repositories."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


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
