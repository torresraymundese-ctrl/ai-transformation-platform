"""Pure scoring rules for the published six-dimension assessment."""

from collections import defaultdict
from collections.abc import Mapping
from types import MappingProxyType
from typing import Iterable

from .contracts import (
    AssessmentCatalog,
    AssessmentInputError,
    AssessmentProfile,
    ScoreResult,
)


DIMENSION_ORDER = (
    "business_value",
    "process",
    "data",
    "systems",
    "organization",
    "delivery",
)


def dimension_score(scores: Iterable[int]) -> int:
    """Normalize 0–3 question scores for one dimension to an integer percent."""
    values = tuple(scores)
    if not values:
        raise AssessmentInputError("a dimension must have at least one question")
    return round(sum(values) / (len(values) * 3) * 100)


def maturity_for_score(score: int) -> str:
    if score < 40:
        return "explore"
    if score < 60:
        return "pilot"
    if score < 80:
        return "scale"
    return "collaborate"


def score_assessment(
    catalog: AssessmentCatalog, profile: AssessmentProfile
) -> ScoreResult:
    """Score a profile against its immutable assessment catalog."""
    weights = catalog.branch_weights.get(profile.branch_code)
    if weights is None:
        raise AssessmentInputError(
            f"no scoring weights for branch {profile.branch_code!r}"
        )
    if set(weights) != set(DIMENSION_ORDER):
        raise AssessmentInputError("scoring weights must cover exactly six dimensions")
    if any(
        isinstance(weight, bool) or not isinstance(weight, int) or weight < 0
        for weight in weights.values()
    ) or sum(weights.values()) != 100:
        raise AssessmentInputError("scoring weights must be non-negative integers totaling 100")

    question_by_code = {}
    questions_by_dimension = defaultdict(list)
    for question in catalog.questions:
        if question.code in question_by_code:
            raise AssessmentInputError(f"duplicate question code: {question.code!r}")
        if question.dimension not in DIMENSION_ORDER:
            raise AssessmentInputError(
                f"unknown question dimension: {question.dimension!r}"
            )
        question_by_code[question.code] = question
        questions_by_dimension[question.dimension].append(question)

    if set(questions_by_dimension) != set(DIMENSION_ORDER) or any(
        len(questions_by_dimension[dimension]) != 2
        for dimension in DIMENSION_ORDER
    ):
        raise AssessmentInputError(
            "catalog must contain exactly two questions for each dimension"
        )

    answers = profile.answers
    if not isinstance(answers, Mapping):
        raise AssessmentInputError("answers must be a mapping")
    if any(
        not isinstance(question_code, str)
        or not isinstance(option_code, str)
        for question_code, option_code in answers.items()
    ):
        raise AssessmentInputError("answer question and option codes must be strings")
    expected_codes = set(question_by_code)
    answer_codes = set(answers)
    missing = expected_codes - answer_codes
    unknown = answer_codes - expected_codes
    if missing:
        raise AssessmentInputError(f"missing answers: {sorted(missing)!r}")
    if unknown:
        raise AssessmentInputError(f"unknown answers: {sorted(unknown)!r}")

    scores_by_dimension = defaultdict(list)
    for question in catalog.questions:
        option_code = answers[question.code]
        options = {option.code: option for option in question.options}
        option = options.get(option_code)
        if option is None:
            raise AssessmentInputError(
                f"unknown option {option_code!r} for question {question.code!r}"
            )
        if isinstance(option.score, bool) or not isinstance(option.score, int):
            raise AssessmentInputError(
                f"invalid score for option {option_code!r} of question {question.code!r}"
            )
        if not 0 <= option.score <= 3:
            raise AssessmentInputError(
                f"option score out of range for question {question.code!r}"
            )
        scores_by_dimension[question.dimension].append(option.score)

    if set(scores_by_dimension) != set(DIMENSION_ORDER):
        raise AssessmentInputError("catalog questions must cover exactly six dimensions")

    dimension_scores = MappingProxyType({
        dimension: dimension_score(scores_by_dimension[dimension])
        for dimension in DIMENSION_ORDER
    })
    overall_score = round(
        sum(dimension_scores[dimension] * weights[dimension] for dimension in DIMENSION_ORDER)
        / 100
    )
    strongest_dimension = max(
        DIMENSION_ORDER, key=lambda dimension: dimension_scores[dimension]
    )
    weakest_dimension = min(
        DIMENSION_ORDER, key=lambda dimension: dimension_scores[dimension]
    )
    return ScoreResult(
        dimension_scores=dimension_scores,
        overall_score=overall_score,
        maturity_code=maturity_for_score(overall_score),
        strongest_dimension=strongest_dimension,
        weakest_dimension=weakest_dimension,
    )
