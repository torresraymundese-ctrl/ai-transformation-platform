"""Typed read access to the published assessment and starter catalog."""

import json
from decimal import Decimal

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


def load_published_catalog(branch_code: str) -> AssessmentCatalog:
    db = get_db()
    try:
        version = _published_version(db)
        industry = db.execute(
            "SELECT id FROM industries WHERE code=? AND status='published'",
            (branch_code,),
        ).fetchone()
        if industry is None:
            raise ValueError(f"unknown published branch: {branch_code}")
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
    finally:
        db.close()


def get_scenarios() -> tuple[Scenario, ...]:
    db = get_db()
    try:
        version = _published_version(db)
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
            (version["id"],),
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
    finally:
        db.close()


def get_service_packages() -> tuple[ServicePackage, ...]:
    db = get_db()
    try:
        version = _published_version(db)
        rows = db.execute(
            "SELECT DISTINCT sv.* FROM services sv "
            "JOIN scenario_services ss ON ss.service_id=sv.id "
            "JOIN scenarios sc ON sc.id=ss.scenario_id AND sc.status='published' "
            "JOIN scenario_roi_profiles rp ON rp.scenario_id=sc.id "
            "AND rp.assessment_version_id=? "
            "WHERE sv.code IS NOT NULL AND sv.status='published' "
            "ORDER BY sv.sort_order",
            (version["id"],),
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
    finally:
        db.close()


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
