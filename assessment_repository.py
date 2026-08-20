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
from models import get_db


DIMENSIONS = (
    "business_value",
    "process",
    "data",
    "systems",
    "organization",
    "delivery",
)
DEFAULT_VERSION_CODE = "v2.0-2026-08-19"
REPORT_MATURITY_CODES = frozenset({"explore", "pilot", "scale", "collaborate"})
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
                    for dimension in DIMENSIONS
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
            "SELECT a.report_snapshot_json,a.branch_code,a.subbranch_code,"
            "a.department_code,a.company_size_code,a.dimension_scores_json,"
            "a.overall_score,a.maturity_code,v.code AS rule_version_code "
            "FROM assessments a "
            "JOIN assessment_versions v ON v.id=a.rule_version_id "
            "WHERE a.id=? AND a.submission_key IS NOT NULL "
            "AND a.lead_id IS NOT NULL AND a.completed_at IS NOT NULL",
            (assessment_id,),
        ).fetchone()
        if row is None or not isinstance(row["report_snapshot_json"], str):
            return None
        try:
            snapshot = json.loads(row["report_snapshot_json"])
            stored_dimensions = json.loads(row["dimension_scores_json"])
        except (json.JSONDecodeError, TypeError):
            return None
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
            dimension: row[f"{dimension}_{suffix}"] for dimension in DIMENSIONS
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
    required = {
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
    if not required <= snapshot.keys():
        return False
    if snapshot["schema_version"] != "2.0":
        return False
    if not _nonempty_text(snapshot["rule_version"]):
        return False
    if not _nonempty_text(snapshot["disclaimer"]):
        return False
    return all(
        (
            _valid_report_assessment(snapshot["assessment"]),
            _valid_report_scores(snapshot["scores"]),
            _valid_recommendations(snapshot["recommendations"]),
            _valid_roi(snapshot["roi"]),
            _valid_calculation_basis(snapshot["calculation_basis"]),
            _valid_roadmap(snapshot["roadmap_90_days"], "days", 4),
            _valid_roadmap(snapshot["roadmap_years_1_3"], "year", 3),
        )
    )


def _valid_report_assessment(value) -> bool:
    if not isinstance(value, dict):
        return False
    required_text = (
        "branch_code",
        "subbranch_code",
        "department_code",
        "company_size_code",
    )
    return (
        all(_nonempty_text(value.get(field)) for field in required_text)
        and isinstance(value.get("pain_codes"), list)
        and 1 <= len(value["pain_codes"]) <= 3
        and all(_nonempty_text(item) for item in value["pain_codes"])
        and isinstance(value.get("answers"), dict)
        and all(
            _nonempty_text(key) and _nonempty_text(item)
            for key, item in value["answers"].items()
        )
        and isinstance(value.get("roi_choices"), dict)
        and all(
            _nonempty_text(key) and _nonempty_text(item)
            for key, item in value["roi_choices"].items()
        )
    )


def _valid_report_scores(value) -> bool:
    if not isinstance(value, dict):
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
    if value.get("maturity_code") not in REPORT_MATURITY_CODES:
        return False
    return _valid_dimension_explanation(value.get("strongest")) and (
        _valid_dimension_explanation(value.get("weakest"))
    )


def _valid_dimension_values(value) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(DIMENSIONS)
        and all(type(score) is int and 0 <= score <= 100 for score in value.values())
    )


def _valid_dimension_explanation(value) -> bool:
    return (
        isinstance(value, dict)
        and value.get("dimension") in DIMENSIONS
        and _nonempty_text(value.get("explanation"))
    )


def _valid_recommendations(value) -> bool:
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        return False
    return all(_valid_recommendation(item) for item in value)


def _valid_recommendation(value) -> bool:
    if not isinstance(value, dict):
        return False
    scenario = value.get("scenario")
    package = value.get("package")
    risks = value.get("risks")
    match_score = value.get("match_score")
    components = value.get("components")
    reason_codes = value.get("reason_codes")
    return (
        isinstance(scenario, dict)
        and _nonempty_text(scenario.get("code"))
        and _nonempty_text(scenario.get("category_code"))
        and scenario.get("integration_level") in {"low", "medium", "high"}
        and _valid_week_range(scenario.get("delivery_weeks"))
        and type(match_score) is int
        and 0 <= match_score <= 100
        and isinstance(components, dict)
        and components
        and all(
            _nonempty_text(key) and type(score) is int and score >= 0
            for key, score in components.items()
        )
        and isinstance(reason_codes, list)
        and reason_codes
        and all(_nonempty_text(item) for item in reason_codes)
        and isinstance(value.get("reasons"), list)
        and value["reasons"]
        and all(_nonempty_text(item) for item in value["reasons"])
        and len(reason_codes) == len(value["reasons"])
        and isinstance(risks, list)
        and len(risks) >= 1
        and all(
            isinstance(item, dict)
            and _nonempty_text(item.get("code"))
            and _nonempty_text(item.get("explanation"))
            for item in risks
        )
        and _valid_package(package)
    )


def _valid_package(value) -> bool:
    if not isinstance(value, dict):
        return False
    list_fields = (
        "deliverables",
        "implementation_steps",
        "prerequisites",
        "not_included",
        "acceptance",
    )
    budget = value.get("budget_range")
    budget_min = _decimal(budget.get("min")) if isinstance(budget, dict) else None
    budget_max = _decimal(budget.get("max")) if isinstance(budget, dict) else None
    return (
        all(
            _nonempty_text(value.get(field))
            for field in ("code", "category", "public_name")
        )
        and isinstance(budget, dict)
        and budget_min is not None
        and budget_max is not None
        and Decimal(0) <= budget_min <= budget_max
        and _valid_week_range(value.get("delivery_weeks"))
        and all(
            isinstance(value.get(field), list)
            and value[field]
            and all(_nonempty_text(item) for item in value[field])
            for field in list_fields
        )
        and type(value.get("support_days")) is int
        and value["support_days"] >= 0
    )


def _valid_week_range(value) -> bool:
    return (
        isinstance(value, dict)
        and type(value.get("min")) is int
        and type(value.get("max")) is int
        and 0 < value["min"] <= value["max"]
    )


def _valid_roi(value) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "conservative",
        "midpoint",
        "ideal",
    }:
        return False
    required_money = (
        "current_annual_cost",
        "labor_savings",
        "loss_savings",
        "annual_savings",
        "initial_investment",
        "annual_support",
        "three_year_support",
        "three_year_net",
    )
    for band in value.values():
        if not isinstance(band, dict):
            return False
        if not all(_finite_decimal(band.get(field)) for field in required_money):
            return False
        payback = band.get("payback_months")
        if payback is not None and not _finite_decimal(payback):
            return False
    return True


def _valid_roadmap(value, position_key, expected_length) -> bool:
    if not (
        isinstance(value, list)
        and len(value) == expected_length
        and all(
            isinstance(item, dict)
            and position_key in item
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
    return [item[position_key] for item in value] == [1, 2, 3]


def _valid_calculation_basis(value) -> bool:
    if not isinstance(value, dict):
        return False
    coefficients = value.get("coefficients")
    choices = value.get("selected_roi_choices")
    if not isinstance(coefficients, dict) or set(coefficients) != {
        "efficiency",
        "loss_improvement",
        "annual_support_rate",
    }:
        return False
    return (
        _nonempty_text(value.get("selected_scenario"))
        and isinstance(choices, dict)
        and choices
        and all(
            _nonempty_text(key) and _nonempty_text(item)
            for key, item in choices.items()
        )
        and all(
            isinstance(coefficients[name], list)
            and len(coefficients[name]) == 3
            and all(_finite_decimal(item) for item in coefficients[name])
            for name in coefficients
        )
        and value.get("selected_roi_bands")
        == ["conservative", "midpoint", "ideal"]
    )


def _finite_decimal(value) -> bool:
    return _decimal(value) is not None


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
