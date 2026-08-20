"""Typed read access to the published assessment and starter catalog."""

import json
from decimal import Decimal, InvalidOperation

from assessment.contracts import (
    AssessmentCatalog,
    Question,
    QuestionOption,
    Scenario,
    ServicePackage,
)
from assessment.matching import COMPONENT_MAX, REASON_TEMPLATES
from assessment.reporting import DISCLAIMER, RISK_EXPLANATIONS, ROI_CHOICE_ORDER
from assessment.scoring import DIMENSION_ORDER, maturity_for_score
from assessment.seed import load_assessment_manifest, load_core_catalog_manifest
from assessment_validation import (
    BRANCH_CODES,
    COMPANY_SIZE_CODES,
    FROZEN_SCENARIO_RULES,
    QUESTION_CODES,
    REFERENCE_LINES,
    ROI_OPTION_CODES,
    SCENARIO_CODES,
)
from models import get_db


DEFAULT_VERSION_CODE = "v2.0-2026-08-19"
MAX_REPORT_SNAPSHOT_BYTES = 128 * 1024
PRIVATE_REPORT_KEYS = frozenset(
    {
        "company",
        "company_name",
        "contact",
        "contact_name",
        "phone",
        "phone_normalized",
        "mobile",
        "email",
        "contact_email",
        "wechat",
    }
)
ANSWER_OPTION_CODES = frozenset({"level_0", "level_1", "level_2", "level_3"})
REPORT_SNAPSHOT_KEYS = frozenset(
    {
        "schema_version",
        "rule_version",
        "assessment",
        "scores",
        "recommendations",
        "roi",
        "calculation_basis",
        "roadmap_90_days",
        "roadmap_years_1_3",
        "disclaimer",
    }
)
ROI_BAND_KEYS = frozenset(
    {
        "current_annual_cost",
        "labor_savings",
        "loss_savings",
        "annual_savings",
        "initial_investment",
        "annual_support",
        "payback_months",
        "three_year_support",
        "three_year_net",
    }
)
_CORE_CATALOG_MANIFEST = load_core_catalog_manifest()
_ASSESSMENT_MANIFEST = load_assessment_manifest()
FROZEN_INDUSTRIES = {
    industry["code"]: industry for industry in _CORE_CATALOG_MANIFEST["industries"]
}
FROZEN_SERVICES = {
    service["code"]: service for service in _CORE_CATALOG_MANIFEST["services"]
}
FROZEN_SCENARIOS = {
    scenario["code"]: scenario for scenario in _CORE_CATALOG_MANIFEST["scenarios"]
}
FROZEN_ROI_RANGES = _ASSESSMENT_MANIFEST["roi_ranges"]


def load_published_catalog(branch_code: str) -> AssessmentCatalog:
    db = get_db()
    try:
        return load_catalog(db, branch_code)
    finally:
        db.close()


def load_published_rule_bundle(branch_code: str):
    """Load one public rule bundle while keeping connection ownership here."""
    db = get_db()
    try:
        catalog = load_catalog(db, branch_code)
        return (
            catalog,
            load_public_config(db, catalog, branch_code),
            load_scenarios(db, catalog.version_id),
            load_service_packages(db, catalog.version_id),
            load_roi_option_ranges(db, catalog.version_id),
        )
    finally:
        db.close()


def load_catalog(db, branch_code: str) -> AssessmentCatalog:
    """Load one exact published catalog on a caller-owned connection."""
    version = _published_version(db)
    industry = db.execute(
        "SELECT id FROM industries WHERE code=? AND status='published'",
        (branch_code,),
    ).fetchone()
    if industry is None:
        raise ValueError("unknown published branch")
    industry_id = industry["id"]
    question_rows = db.execute(
        "SELECT id,code,dimension_code,prompt FROM assessment_questions "
        "WHERE assessment_version_id=? AND status='published' ORDER BY sort_order",
        (version["id"],),
    ).fetchall()
    questions = tuple(
        Question(
            code=row["code"],
            dimension=row["dimension_code"],
            prompt=row["prompt"],
            options=tuple(
                QuestionOption(
                    code=option["code"],
                    label=option["label"],
                    score=option["score"],
                )
                for option in db.execute(
                    "SELECT code,label,score FROM assessment_options "
                    "WHERE question_id=? ORDER BY sort_order",
                    (row["id"],),
                )
            ),
        )
        for row in question_rows
    )
    return AssessmentCatalog(
        version_id=version["id"],
        version_code=version["code"],
        subbranch_codes=_codes(
            db,
            "SELECT code FROM industry_branches "
            "WHERE industry_id=? AND status='published' ORDER BY sort_order",
            (industry_id,),
        ),
        department_codes=_codes(
            db,
            "SELECT code FROM departments "
            "WHERE industry_id=? AND status='published' ORDER BY sort_order",
            (industry_id,),
        ),
        pain_codes=_codes(
            db,
            "SELECT code FROM pain_points "
            "WHERE industry_id=? AND status='published' ORDER BY sort_order",
            (industry_id,),
        ),
        questions=questions,
        branch_weights=_dimension_maps(
            db,
            version["id"],
            "assessment_branch_weights",
            "weight",
        ),
        reference_lines=_dimension_maps(
            db,
            version["id"],
            "industry_benchmarks",
            "score",
        ),
    )


def get_scenarios() -> tuple[Scenario, ...]:
    db = get_db()
    try:
        version = _published_version(db)
        return load_scenarios(db, version["id"])
    finally:
        db.close()


def load_scenarios(db, version_id: int) -> tuple[Scenario, ...]:
    """Load scenarios whose ROI profile belongs to the supplied rule version."""
    rows = db.execute(
        "SELECT s.*,rp.efficiency_low,rp.efficiency_mid,rp.efficiency_high,"
        "rp.loss_improvement_low,rp.loss_improvement_mid,"
        "rp.loss_improvement_high,rp.annual_support_rate_low,"
        "rp.annual_support_rate_mid,rp.annual_support_rate_high,sv.code service_code "
        "FROM scenarios s "
        "JOIN scenario_roi_profiles rp ON rp.scenario_id=s.id "
        "AND rp.assessment_version_id=? "
        "JOIN scenario_services ss ON ss.scenario_id=s.id "
        "JOIN services sv ON sv.id=ss.service_id AND sv.status='published' "
        "WHERE s.status='published' ORDER BY s.sort_order",
        (version_id,),
    ).fetchall()
    scenarios = []
    for row in rows:
        scenario_id = row["id"]
        scenarios.append(
            Scenario(
                code=row["code"],
                category_code=row["category_code"],
                branch_codes=_codes(
                    db,
                    "SELECT DISTINCT i.code FROM scenario_branches sb "
                    "JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
                    "JOIN industries i ON i.id=ib.industry_id "
                    "WHERE sb.scenario_id=? ORDER BY i.sort_order",
                    (scenario_id,),
                ),
                department_codes=_codes(
                    db,
                    "SELECT DISTINCT d.code FROM scenario_departments sd "
                    "JOIN departments d ON d.id=sd.department_id "
                    "JOIN industries i ON i.id=d.industry_id "
                    "WHERE sd.scenario_id=? ORDER BY i.sort_order,d.sort_order",
                    (scenario_id,),
                ),
                pain_codes=_codes(
                    db,
                    "SELECT DISTINCT p.code FROM scenario_pains sp "
                    "JOIN pain_points p ON p.id=sp.pain_point_id "
                    "JOIN industries i ON i.id=p.industry_id "
                    "WHERE sp.scenario_id=? ORDER BY i.sort_order,p.sort_order",
                    (scenario_id,),
                ),
                minimum_scores={
                    dimension: row[f"minimum_{dimension}"]
                    for dimension in DIMENSION_ORDER
                },
                integration_level=row["integration_level"],
                budget_codes=_codes(
                    db,
                    "SELECT budget_code FROM scenario_budget_options "
                    "WHERE scenario_id=? ORDER BY sort_order",
                    (scenario_id,),
                ),
                min_weeks=row["min_weeks"],
                max_weeks=row["max_weeks"],
                efficiency=_decimal_triple(row, "efficiency"),
                loss_improvement=_decimal_triple(row, "loss_improvement"),
                annual_support_rate=_decimal_triple(row, "annual_support_rate"),
                risk_codes=tuple(json.loads(row["risk_codes_json"])),
                service_code=row["service_code"],
                sort_order=row["sort_order"],
                fallback_only=bool(row["fallback_only"]),
            )
        )
    return tuple(scenarios)


def get_service_packages() -> tuple[ServicePackage, ...]:
    db = get_db()
    try:
        version = _published_version(db)
        return load_service_packages(db, version["id"])
    finally:
        db.close()


def load_service_packages(db, version_id: int) -> tuple[ServicePackage, ...]:
    """Load only packages linked to scenarios in one exact rule version."""
    rows = db.execute(
        "SELECT DISTINCT sv.* FROM services sv "
        "JOIN scenario_services ss ON ss.service_id=sv.id "
        "JOIN scenarios sc ON sc.id=ss.scenario_id AND sc.status='published' "
        "JOIN scenario_roi_profiles rp ON rp.scenario_id=sc.id "
        "AND rp.assessment_version_id=? "
        "WHERE sv.code IS NOT NULL AND sv.status='published' "
        "ORDER BY sv.sort_order",
        (version_id,),
    ).fetchall()
    return tuple(
        ServicePackage(
            code=row["code"],
            category=row["category"],
            public_name=row["public_name"],
            min_budget=Decimal(str(row["min_budget"])),
            max_budget=Decimal(str(row["max_budget"])),
            min_weeks=row["min_weeks"],
            max_weeks=row["max_weeks"],
            deliverables=_codes(
                db,
                "SELECT title FROM service_deliverables "
                "WHERE service_id=? AND status='published' ORDER BY sort_order",
                (row["id"],),
            ),
            implementation_steps=tuple(
                json.loads(row["implementation_steps_json"])
            ),
            prerequisites=tuple(json.loads(row["prerequisites_json"])),
            not_included=tuple(json.loads(row["not_included_json"])),
            acceptance=tuple(json.loads(row["acceptance_json"])),
            support_days=row["support_days"],
        )
        for row in rows
    )


def is_published_company_size(db, company_size_code: str) -> bool:
    return db.execute(
        "SELECT 1 FROM company_sizes WHERE code=? AND status='published'",
        (company_size_code,),
    ).fetchone() is not None


def load_roi_option_ranges(db, version_id: int):
    ranges = {}
    for row in db.execute(
        "SELECT option_group,code,low_value,mid_value,high_value "
        "FROM roi_option_ranges WHERE assessment_version_id=? "
        "ORDER BY option_group,id",
        (version_id,),
    ):
        ranges.setdefault(row["option_group"], {})[row["code"]] = tuple(
            Decimal(str(row[name]))
            for name in ("low_value", "mid_value", "high_value")
        )
    return ranges


def load_public_config(db, catalog: AssessmentCatalog, branch_code: str):
    """Return only published, user-facing questionnaire configuration."""
    version = db.execute(
        "SELECT pain_min_selections,pain_max_selections "
        "FROM assessment_versions WHERE id=? AND status='published'",
        (catalog.version_id,),
    ).fetchone()
    industry = db.execute(
        "SELECT id,code,name FROM industries WHERE code=? AND status='published'",
        (branch_code,),
    ).fetchone()
    if version is None or industry is None:
        raise RuntimeError("published assessment configuration is unavailable")
    reference = db.execute(
        "SELECT label FROM industry_benchmarks "
        "WHERE assessment_version_id=? AND industry_id=?",
        (catalog.version_id, industry["id"]),
    ).fetchone()
    if reference is None:
        raise RuntimeError("published assessment reference line is unavailable")
    return {
        "branch": {"code": industry["code"], "label": industry["name"]},
        "subbranches": _labeled_codes(
            db,
            "SELECT code,name FROM industry_branches "
            "WHERE industry_id=? AND status='published' ORDER BY sort_order",
            (industry["id"],),
        ),
        "departments": _labeled_codes(
            db,
            "SELECT code,name FROM departments "
            "WHERE industry_id=? AND status='published' ORDER BY sort_order",
            (industry["id"],),
        ),
        "pain_points": _labeled_codes(
            db,
            "SELECT code,name FROM pain_points "
            "WHERE industry_id=? AND status='published' ORDER BY sort_order",
            (industry["id"],),
        ),
        "company_sizes": _labeled_codes(
            db,
            "SELECT code,name FROM company_sizes "
            "WHERE status='published' ORDER BY sort_order",
        ),
        "pain_selection": {
            "minimum": version["pain_min_selections"],
            "maximum": version["pain_max_selections"],
        },
        "roi_options": {
            group: list(options)
            for group, options in _roi_option_codes(
                db, catalog.version_id
            ).items()
        },
        "reference_label": reference["label"],
    }


def find_by_submission_key(db, submission_key: str):
    return db.execute(
        "SELECT id,lead_id FROM assessments WHERE submission_key=?",
        (submission_key,),
    ).fetchone()


def load_report_snapshot(assessment_id: int):
    """Return one complete immutable V2 snapshot, or ``None`` when unusable."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT CASE WHEN length(CAST(a.report_snapshot_json AS BLOB))<=? "
            "THEN a.report_snapshot_json END AS report_snapshot_json,"
            "length(CAST(a.report_snapshot_json AS BLOB)) AS report_snapshot_bytes,"
            "a.branch_code,a.subbranch_code,"
            "a.department_code,a.company_size_code,a.dimension_scores_json,"
            "a.overall_score,a.maturity_code,v.code AS rule_version_code "
            "FROM assessments a "
            "JOIN assessment_versions v ON v.id=a.rule_version_id "
            "WHERE a.id=? AND a.submission_key IS NOT NULL "
            "AND a.lead_id IS NOT NULL AND a.completed_at IS NOT NULL",
            (MAX_REPORT_SNAPSHOT_BYTES, assessment_id),
        ).fetchone()
        if (
            row is None
            or row["report_snapshot_bytes"] is None
            or row["report_snapshot_bytes"] > MAX_REPORT_SNAPSHOT_BYTES
            or not isinstance(row["report_snapshot_json"], str)
        ):
            return None
        try:
            snapshot = json.loads(row["report_snapshot_json"])
            stored_dimensions = json.loads(row["dimension_scores_json"])
            if not _valid_report_snapshot(snapshot):
                return None
            assessment = snapshot["assessment"]
            scores = snapshot["scores"]
            if snapshot["rule_version"] != row["rule_version_code"]:
                return None
            if any(
                assessment[field] != row[field]
                for field in (
                    "branch_code",
                    "subbranch_code",
                    "department_code",
                    "company_size_code",
                )
            ):
                return None
            if scores["dimension_scores"] != stored_dimensions:
                return None
            if scores["overall_score"] != row["overall_score"]:
                return None
            if scores["maturity_code"] != row["maturity_code"]:
                return None
            return snapshot
        except (json.JSONDecodeError, ValueError, TypeError, RecursionError):
            return None
    finally:
        db.close()


def insert_completed(
    db,
    lead_id,
    request,
    submission_key,
    catalog,
    scores,
    matches,
    report_snapshot,
    completed_at,
):
    timestamp = completed_at.isoformat(sep=" ")
    assessment_id = db.execute(
        "INSERT INTO assessments "
        "(submission_key,lead_id,rule_version_id,branch_code,subbranch_code,"
        "department_code,company_size_code,answers_json,dimension_scores_json,"
        "overall_score,maturity_code,report_snapshot_json,attribution_json,"
        "completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            submission_key,
            lead_id,
            catalog.version_id,
            request.profile.branch_code,
            request.profile.subbranch_code,
            request.profile.department_code,
            request.profile.company_size_code,
            _json(request.profile.answers),
            _json(scores.dimension_scores),
            scores.overall_score,
            scores.maturity_code,
            _json(report_snapshot),
            _json(request.attribution.__dict__),
            timestamp,
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO roi_estimates "
        "(assessment_id,rule_version_id,recommended_scenarios_json,"
        "estimate_snapshot_json,created_at) VALUES (?,?,?,?,?)",
        (
            assessment_id,
            catalog.version_id,
            _json([match.scenario.code for match in matches]),
            _json(report_snapshot["roi"]),
            timestamp,
        ),
    )
    return assessment_id


def _published_version(db):
    version = db.execute(
        "SELECT id,code FROM assessment_versions "
        "WHERE code=? AND status='published'",
        (DEFAULT_VERSION_CODE,),
    ).fetchone()
    if version is None:
        raise RuntimeError(
            f"published assessment version {DEFAULT_VERSION_CODE} is unavailable"
        )
    return version


def _codes(db, statement, parameters=()):
    return tuple(row[0] for row in db.execute(statement, parameters))


def _labeled_codes(db, statement, parameters=()):
    return [
        {"code": row["code"], "label": row["name"]}
        for row in db.execute(statement, parameters)
    ]


def _roi_option_codes(db, version_id):
    groups = {}
    for row in db.execute(
        "SELECT option_group,code FROM roi_option_ranges "
        "WHERE assessment_version_id=? ORDER BY option_group,id",
        (version_id,),
    ):
        groups.setdefault(row["option_group"], []).append(row["code"])
    return groups


def _dimension_maps(db, version_id, table, suffix):
    rows = db.execute(
        f"SELECT i.code,r.* FROM {table} r "
        "JOIN industries i ON i.id=r.industry_id "
        "WHERE r.assessment_version_id=? ORDER BY i.sort_order",
        (version_id,),
    ).fetchall()
    return {
        row["code"]: {
            dimension: row[f"{dimension}_{suffix}"]
            for dimension in DIMENSION_ORDER
        }
        for row in rows
    }


def _decimal_triple(row, prefix):
    return tuple(
        Decimal(str(row[f"{prefix}_{band}"])) for band in ("low", "mid", "high")
    )


def _json(value):
    return json.dumps(
        dict(value) if hasattr(value, "items") else value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _valid_report_snapshot(snapshot) -> bool:
    if not isinstance(snapshot, dict) or _contains_private_report_key(snapshot):
        return False
    if set(snapshot) != REPORT_SNAPSHOT_KEYS:
        return False
    if snapshot["schema_version"] != "2.0" or snapshot["rule_version"] != (
        DEFAULT_VERSION_CODE
    ):
        return False
    if snapshot["disclaimer"] != DISCLAIMER:
        return False
    assessment = snapshot["assessment"]
    scores = snapshot["scores"]
    recommendations = snapshot["recommendations"]
    if not _valid_report_assessment(assessment):
        return False
    return (
        _valid_report_scores(scores, assessment)
        and _valid_recommendations(recommendations)
        and _valid_roi(snapshot["roi"])
        and _valid_calculation_basis(
            snapshot["calculation_basis"], assessment, recommendations
        )
        and _valid_roadmap(snapshot["roadmap_90_days"], "days", 4)
        and _valid_roadmap(snapshot["roadmap_years_1_3"], "year", 3)
    )


def _valid_report_assessment(value) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "branch_code",
        "subbranch_code",
        "department_code",
        "company_size_code",
        "pain_codes",
        "answers",
        "roi_choices",
    }:
        return False
    branch_code = value["branch_code"]
    industry = FROZEN_INDUSTRIES.get(branch_code)
    if industry is None:
        return False
    pain_codes = value["pain_codes"]
    answers = value["answers"]
    choices = value["roi_choices"]
    return (
        branch_code in BRANCH_CODES
        and value["subbranch_code"] in industry["subbranches"]
        and value["department_code"] in industry["departments"]
        and value["company_size_code"] in COMPANY_SIZE_CODES
        and isinstance(pain_codes, list)
        and 1 <= len(pain_codes) <= 3
        and len(set(pain_codes)) == len(pain_codes)
        and all(code in industry["pain_codes"] for code in pain_codes)
        and isinstance(answers, dict)
        and set(answers) == set(QUESTION_CODES)
        and len(answers) == 12
        and all(option in ANSWER_OPTION_CODES for option in answers.values())
        and isinstance(choices, dict)
        and set(choices) == set(ROI_OPTION_CODES)
        and len(choices) == 5
        and all(
            choices[group] in ROI_OPTION_CODES[group] for group in ROI_OPTION_CODES
        )
    )


def _valid_report_scores(value, assessment) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "overall_score",
        "maturity_code",
        "dimension_scores",
        "reference_line",
        "strongest",
        "weakest",
    }:
        return False
    dimensions = value.get("dimension_scores")
    reference = value.get("reference_line")
    if not _valid_dimension_values(dimensions) or not _valid_dimension_values(
        reference
    ):
        return False
    overall = value.get("overall_score")
    if type(overall) is not int or not 0 <= overall <= 100:
        return False
    if value.get("maturity_code") != maturity_for_score(overall):
        return False
    expected_reference = dict(
        zip(DIMENSION_ORDER, REFERENCE_LINES[assessment["branch_code"]])
    )
    if reference != expected_reference:
        return False
    strongest = value.get("strongest")
    weakest = value.get("weakest")
    return (
        _valid_dimension_explanation(strongest)
        and _valid_dimension_explanation(weakest)
        and strongest["dimension"]
        == max(DIMENSION_ORDER, key=dimensions.get)
        and weakest["dimension"] == min(DIMENSION_ORDER, key=dimensions.get)
    )


def _valid_dimension_values(value) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(DIMENSION_ORDER)
        and all(type(score) is int and 0 <= score <= 100 for score in value.values())
    )


def _valid_dimension_explanation(value) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"dimension", "explanation"}
        and value["dimension"] in DIMENSION_ORDER
        and _bounded_text(value["explanation"])
    )


def _valid_recommendations(value) -> bool:
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        return False
    if not all(_valid_recommendation(item) for item in value):
        return False
    scenario_codes = [item["scenario"]["code"] for item in value]
    return len(set(scenario_codes)) == len(scenario_codes)


def _valid_recommendation(value) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "scenario",
        "match_score",
        "components",
        "reason_codes",
        "reasons",
        "risks",
        "package",
    }:
        return False
    scenario = value["scenario"]
    package = value["package"]
    risks = value["risks"]
    match_score = value["match_score"]
    components = value["components"]
    reason_codes = value["reason_codes"]
    if not isinstance(scenario, dict) or set(scenario) != {
        "code",
        "category_code",
        "integration_level",
        "delivery_weeks",
    }:
        return False
    scenario_rule = FROZEN_SCENARIO_RULES.get(scenario["code"])
    scenario_manifest = FROZEN_SCENARIOS.get(scenario["code"])
    if scenario_rule is None or scenario_manifest is None:
        return False
    expected_weeks = {
        "min": scenario_rule["weeks"][0],
        "max": scenario_rule["weeks"][1],
    }
    if (
        scenario["category_code"] != scenario_rule["category_code"]
        or not _exact_integer_mapping(
            scenario["delivery_weeks"], expected_weeks
        )
        or scenario["integration_level"] != scenario_manifest["integration_level"]
    ):
        return False
    if not (
        type(match_score) is int
        and 0 <= match_score <= 100
        and isinstance(components, dict)
        and set(components) == set(COMPONENT_MAX)
        and all(
            type(components[name]) is int
            and 0 <= components[name] <= maximum
            for name, maximum in COMPONENT_MAX.items()
        )
        and sum(components.values()) == match_score
    ):
        return False
    if not (
        isinstance(reason_codes, list)
        and 1 <= len(reason_codes) <= len(REASON_TEMPLATES)
        and len(set(reason_codes)) == len(reason_codes)
        and all(code in REASON_TEMPLATES for code in reason_codes)
        and value["reasons"] == [REASON_TEMPLATES[code] for code in reason_codes]
    ):
        return False
    expected_risks = [
        {"code": code, "explanation": RISK_EXPLANATIONS[code]}
        for code in scenario_rule["risk_codes"]
    ]
    return (
        isinstance(risks, list)
        and risks == expected_risks
        and _valid_package(package, scenario_rule["service_code"])
    )


def _valid_package(value, expected_service_code) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "code",
        "category",
        "public_name",
        "budget_range",
        "delivery_weeks",
        "deliverables",
        "implementation_steps",
        "prerequisites",
        "not_included",
        "acceptance",
        "support_days",
    }:
        return False
    service = FROZEN_SERVICES.get(expected_service_code)
    if service is None or value["code"] != expected_service_code:
        return False
    budget = value["budget_range"]
    expected_budget = {
        "min": _decimal(service["budget"][0]),
        "max": _decimal(service["budget"][1]),
    }
    expected_weeks = {"min": service["weeks"][0], "max": service["weeks"][1]}
    return (
        value["category"] == service["category"]
        and value["public_name"] == service["public_name"]
        and isinstance(budget, dict)
        and set(budget) == {"min", "max"}
        and {name: _decimal(amount) for name, amount in budget.items()}
        == expected_budget
        and _exact_integer_mapping(value["delivery_weeks"], expected_weeks)
        and value["deliverables"] == service["deliverables"]
        and value["implementation_steps"] == service["implementation_steps"]
        and value["prerequisites"] == service["prerequisites"]
        and value["not_included"] == service["not_included"]
        and value["acceptance"] == service["acceptance"]
        and type(value["support_days"]) is int
        and value["support_days"] == service["support_days"]
    )


def _valid_roi(value) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "conservative",
        "midpoint",
        "ideal",
    }:
        return False
    nonnegative_money = (
        "current_annual_cost",
        "labor_savings",
        "loss_savings",
        "annual_savings",
        "initial_investment",
        "annual_support",
        "three_year_support",
    )
    for band in value.values():
        if not isinstance(band, dict) or set(band) != ROI_BAND_KEYS:
            return False
        if not all(
            _nonnegative_decimal(band[field]) for field in nonnegative_money
        ):
            return False
        if not _finite_decimal(band["three_year_net"]):
            return False
        payback = band["payback_months"]
        if payback is not None and not _positive_decimal(payback):
            return False
    return True


def _valid_roadmap(value, position_key, expected_length) -> bool:
    if not (
        isinstance(value, list)
        and len(value) == expected_length
        and all(
            isinstance(item, dict)
            and set(item) == {position_key, "action"}
            and _nonempty_text(item.get("action"))
            for item in value
        )
    ):
        return False
    if position_key == "days":
        return [item[position_key] for item in value] == [
            "1-15",
            "16-30",
            "31-60",
            "61-90",
        ]
    years = [item[position_key] for item in value]
    return all(type(year) is int for year in years) and years == [1, 2, 3]


def _valid_calculation_basis(value, assessment, recommendations) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "selected_scenario",
        "selected_roi_choices",
        "coefficients",
        "selected_roi_bands",
    }:
        return False
    coefficients = value.get("coefficients")
    choices = value.get("selected_roi_choices")
    selected_bands = value.get("selected_roi_bands")
    if not isinstance(coefficients, dict) or set(coefficients) != {
        "efficiency",
        "loss_improvement",
        "annual_support_rate",
    }:
        return False
    selected_scenario = value["selected_scenario"]
    if (
        selected_scenario not in SCENARIO_CODES
        or selected_scenario != recommendations[0]["scenario"]["code"]
        or choices != assessment["roi_choices"]
        or set(choices) != set(ROI_CHOICE_ORDER)
        or len(choices) != 5
    ):
        return False
    scenario = FROZEN_SCENARIOS[selected_scenario]
    for name in coefficients:
        values = coefficients[name]
        if not isinstance(values, list) or len(values) != 3:
            return False
        expected = [_decimal(item) for item in scenario[name]]
        if any(_decimal(item) is None for item in values):
            return False
        if [_decimal(item) for item in values] != expected:
            return False
    if not isinstance(selected_bands, dict) or set(selected_bands) != set(
        ROI_CHOICE_ORDER
    ):
        return False
    for group in ROI_CHOICE_ORDER:
        band = selected_bands[group]
        if not isinstance(band, dict) or set(band) != {"low", "mid", "high"}:
            return False
        values = [_decimal(band[name]) for name in ("low", "mid", "high")]
        expected = [
            _decimal(item) for item in FROZEN_ROI_RANGES[group][choices[group]]
        ]
        if any(item is None for item in values) or values != expected:
            return False
    return True


def _finite_decimal(value) -> bool:
    return _decimal(value) is not None


def _exact_integer_mapping(value, expected) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(expected)
        and all(
            type(value[name]) is int and value[name] == expected[name]
            for name in expected
        )
    )


def _nonnegative_decimal(value) -> bool:
    parsed = _decimal(value)
    return parsed is not None and parsed >= Decimal(0)


def _positive_decimal(value) -> bool:
    parsed = _decimal(value)
    return parsed is not None and parsed > Decimal(0)


def _decimal(value):
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _contains_private_report_key(value) -> bool:
    if isinstance(value, dict):
        if PRIVATE_REPORT_KEYS.intersection(value):
            return True
        return any(_contains_private_report_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_private_report_key(item) for item in value)
    return False


def _nonempty_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _bounded_text(value, maximum=4_000) -> bool:
    return _nonempty_text(value) and len(value) <= maximum
