import pytest

from assessment.contracts import (
    AssessmentCatalog,
    AssessmentProfile,
    Question,
    QuestionOption,
)
from assessment.scoring import (
    AssessmentInputError,
    maturity_for_score,
    score_assessment,
)


DIMENSIONS = (
    "business_value",
    "process",
    "data",
    "systems",
    "organization",
    "delivery",
)

QUESTION_DIMENSIONS = {
    "business_value_frequency": "business_value",
    "business_value_scope": "business_value",
    "process_documentation": "process",
    "process_stability": "process",
    "data_availability": "data",
    "data_quality": "data",
    "systems_foundation": "systems",
    "systems_automation": "systems",
    "organization_owner": "organization",
    "organization_adoption": "organization",
    "delivery_budget": "delivery",
    "delivery_timeline": "delivery",
}


def _question(code, dimension):
    return Question(
        code=code,
        dimension=dimension,
        prompt=f"Prompt for {code}",
        options=tuple(
            QuestionOption(code=f"level_{score}", label=f"Level {score}", score=score)
            for score in range(4)
        ),
    )


@pytest.fixture()
def catalog():
    return AssessmentCatalog(
        version_id=1,
        version_code="test-v2",
        subbranch_codes=("discrete_manufacturing",),
        department_codes=("production",),
        pain_codes=("knowledge_search",),
        questions=tuple(
            _question(code, dimension)
            for code, dimension in QUESTION_DIMENSIONS.items()
        ),
        branch_weights={
            "manufacturing": {
                "business_value": 20,
                "process": 20,
                "data": 20,
                "systems": 15,
                "organization": 10,
                "delivery": 15,
            }
        },
        reference_lines={},
    )


@pytest.fixture()
def profile():
    # Literal scores make the weighted expectation independent of implementation.
    scores = {
        "business_value_frequency": 3,
        "business_value_scope": 3,
        "process_documentation": 2,
        "process_stability": 1,
        "data_availability": 2,
        "data_quality": 1,
        "systems_foundation": 2,
        "systems_automation": 2,
        "organization_owner": 0,
        "organization_adoption": 0,
        "delivery_budget": 3,
        "delivery_timeline": 3,
    }
    return AssessmentProfile(
        branch_code="manufacturing",
        subbranch_code="discrete_manufacturing",
        department_code="production",
        company_size_code="50_200",
        pain_codes=("knowledge_search",),
        answers={code: f"level_{score}" for code, score in scores.items()},
        roi_choices={},
    )


@pytest.mark.parametrize(
    ("score", "level"),
    [
        (0, "explore"),
        (39, "explore"),
        (40, "pilot"),
        (59, "pilot"),
        (60, "scale"),
        (79, "scale"),
        (80, "collaborate"),
        (100, "collaborate"),
    ],
)
def test_maturity_boundaries(score, level):
    assert maturity_for_score(score) == level


def test_manufacturing_weighted_score_uses_approved_weights(catalog, profile):
    result = score_assessment(catalog, profile)

    assert result.dimension_scores == {
        "business_value": 100,
        "process": 50,
        "data": 50,
        "systems": 67,
        "organization": 0,
        "delivery": 100,
    }
    assert result.dimension_scores["business_value"] == 100
    assert result.dimension_scores["organization"] == 0
    assert result.overall_score == 65
    assert result.maturity_code == "scale"
    assert result.strongest_dimension == "business_value"
    assert result.weakest_dimension == "organization"


def test_all_zero_answers_score_zero_and_explore(catalog, profile):
    zero_profile = AssessmentProfile(**{**profile.__dict__, "answers": {
        code: "level_0" for code in QUESTION_DIMENSIONS
    }})

    result = score_assessment(catalog, zero_profile)

    assert result.dimension_scores == {dimension: 0 for dimension in DIMENSIONS}
    assert result.overall_score == 0
    assert result.maturity_code == "explore"
    assert result.strongest_dimension == "business_value"
    assert result.weakest_dimension == "business_value"


def test_all_three_answers_score_one_hundred_and_collaborate(catalog, profile):
    full_profile = AssessmentProfile(**{**profile.__dict__, "answers": {
        code: "level_3" for code in QUESTION_DIMENSIONS
    }})

    result = score_assessment(catalog, full_profile)

    assert result.dimension_scores == {dimension: 100 for dimension in DIMENSIONS}
    assert result.overall_score == 100
    assert result.maturity_code == "collaborate"


def test_missing_answer_raises_assessment_input_error(catalog, profile):
    answers = dict(profile.answers)
    del answers["data_quality"]
    incomplete = AssessmentProfile(**{**profile.__dict__, "answers": answers})

    with pytest.raises(AssessmentInputError):
        score_assessment(catalog, incomplete)


def test_unknown_answer_option_raises_assessment_input_error(catalog, profile):
    answers = dict(profile.answers)
    answers["data_quality"] = "level_unknown"
    invalid = AssessmentProfile(**{**profile.__dict__, "answers": answers})

    with pytest.raises(AssessmentInputError):
        score_assessment(catalog, invalid)


def test_unknown_answer_question_raises_assessment_input_error(catalog, profile):
    answers = {**profile.answers, "not_a_question": "level_0"}
    invalid = AssessmentProfile(**{**profile.__dict__, "answers": answers})

    with pytest.raises(AssessmentInputError):
        score_assessment(catalog, invalid)


def test_weight_total_other_than_one_hundred_fails_closed(catalog, profile):
    invalid_catalog = AssessmentCatalog(**{
        **catalog.__dict__,
        "branch_weights": {
            "manufacturing": {
                **catalog.branch_weights["manufacturing"],
                "delivery": 14,
            }
        },
    })

    with pytest.raises(AssessmentInputError):
        score_assessment(invalid_catalog, profile)
