"""Transactional persistence helpers and startup reconciliation for rule releases."""

from dataclasses import replace
from decimal import Decimal
import hashlib
import json
import sqlite3

from assessment.contracts import (
    ReleaseBenchmark,
    ReleaseIndustry,
    ReleaseLabeledCode,
    ReleaseQuestion,
    ReleaseQuestionOption,
    ReleasePublicLabels,
    ReleaseScenario,
    ReleaseScopedCode,
    ReleaseService,
    RuleReleaseDraft,
)
from assessment.scoring import DIMENSION_ORDER
from assessment.reporting import RISK_EXPLANATIONS, RISK_LABELS
from content_clock import format_shanghai
from rule_release_validation import compile_release_snapshot


INITIAL_VERSION_CODE = "v2.0-2026-08-19"

_DIMENSION_LABELS = {
    "business_value": "业务价值",
    "process": "流程基础",
    "data": "数据基础",
    "systems": "系统基础",
    "organization": "组织准备",
    "delivery": "落地条件",
}
_MATURITY_LABELS = {
    "explore": "探索起步",
    "pilot": "单点试验",
    "scale": "规模扩展",
    "collaborate": "智能协同",
}
_INTEGRATION_LABELS = {"low": "低", "medium": "中", "high": "高"}
_ROI_GROUP_LABELS = {
    "headcount": "参与人数",
    "monthly_hours": "每人每月耗时",
    "monthly_cost": "人均月综合成本",
    "loss_factor": "返工或损耗程度",
    "budget": "可接受投入",
}
_ROI_OPTION_LABELS = {
    "headcount": {"1_5": "1—5 人", "6_20": "6—20 人", "21_50": "21—50 人", "50_plus": "50 人以上"},
    "monthly_hours": {"under_20": "20 小时内", "20_80": "20—80 小时", "80_160": "80—160 小时", "160_plus": "160 小时以上"},
    "monthly_cost": {"under_8000": "8000 元内", "8000_15000": "0.8—1.5 万元", "15000_30000": "1.5—3 万元", "30000_plus": "3 万元以上"},
    "loss_factor": {"rare": "很少", "normal": "一般", "high": "较高", "severe": "严重"},
    "budget": {"under_50000": "5 万元内", "50000_200000": "5—20 万元", "200000_500000": "20—50 万元", "500000_plus": "50 万元以上"},
}


def _initial_public_labels():
    return ReleasePublicLabels(
        risk_labels=dict(RISK_LABELS),
        risk_explanations=dict(RISK_EXPLANATIONS),
        dimensions=dict(_DIMENSION_LABELS),
        maturities=dict(_MATURITY_LABELS),
        integrations=dict(_INTEGRATION_LABELS),
        roi_groups=dict(_ROI_GROUP_LABELS),
        roi_options={group: dict(values) for group, values in _ROI_OPTION_LABELS.items()},
    )


def _has_release_schema(db):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='active_assessment_version'"
    ).fetchone() is not None


def reconcile_initial_v2_release(db, now):
    """Backfill the frozen V2 release exactly once after migration 015."""
    if not _has_release_schema(db):
        return
    try:
        db.execute("BEGIN IMMEDIATE")
        active = db.execute(
            "SELECT v.id,v.status,v.validated_digest,s.sha256,s.canonical_json,"
            "(SELECT COUNT(*) FROM assessment_version_snapshots sx "
            " WHERE sx.assessment_version_id=v.id) snapshot_count "
            "FROM active_assessment_version a "
            "JOIN assessment_versions v ON v.id=a.assessment_version_id "
            "LEFT JOIN assessment_version_snapshots s ON s.assessment_version_id=v.id"
        ).fetchone()
        if active is not None:
            if (
                active["status"] != "published"
                or active["snapshot_count"] != 1
                or active["validated_digest"] != active["sha256"]
                or type(active["canonical_json"]) is not str
                or hashlib.sha256(active["canonical_json"].encode("utf-8")).hexdigest()
                != active["sha256"]
            ):
                raise RuntimeError("active assessment release is invalid")
            db.commit()
            return

        version = db.execute(
            "SELECT * FROM assessment_versions WHERE code=? AND status='published'",
            (INITIAL_VERSION_CODE,),
        ).fetchone()
        if version is None:
            raise RuntimeError("initial V2 release is unavailable")
        if db.execute(
            "SELECT 1 FROM assessment_version_snapshots WHERE assessment_version_id=?",
            (version["id"],),
        ).fetchone() is not None:
            raise RuntimeError("initial V2 snapshot exists without active pointer")
        timestamp = _timestamp(now)
        if any(
            db.execute(
                f"SELECT 1 FROM {table} WHERE assessment_version_id=? LIMIT 1",
                (version["id"],),
            ).fetchone()
            for table in _RELEASE_ROOT_TABLES
        ):
            raise RuntimeError("initial V2 release backfill is partial")
        initial = _initial_manifest_draft(db, version, timestamp)
        _insert_release_projection(db, version["id"], initial)
        compiled_draft = replace(
            _load_release_draft_from_db(db, version["id"]), status="draft"
        )
        snapshot = compile_release_snapshot(compiled_draft)
        expected = compile_release_snapshot(replace(initial, status="draft"))
        if snapshot != expected:
            raise RuntimeError("initial V2 release parity check failed")
        updated = db.execute(
            "UPDATE assessment_versions SET validated_digest=?,updated_at=? "
            "WHERE id=? AND status='published' AND validated_digest IS NULL",
            (snapshot.sha256, timestamp, version["id"]),
        ).rowcount
        if updated != 1:
            raise RuntimeError("initial V2 digest reconciliation conflict")
        db.execute(
            "INSERT INTO assessment_version_snapshots "
            "(assessment_version_id,schema_version,canonical_json,sha256,created_at) "
            "VALUES (?,?,?,?,?)",
            (
                version["id"],
                snapshot.schema_version,
                snapshot.canonical_json,
                snapshot.sha256,
                timestamp,
            ),
        )
        db.execute(
            "INSERT INTO active_assessment_version "
            "(singleton_id,assessment_version_id,updated_at) VALUES (1,?,?)",
            (version["id"], timestamp),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def _timestamp(now):
    try:
        return format_shanghai(now)
    except (TypeError, ValueError) as error:
        raise ValueError("now must be an aware datetime") from error


def _initial_manifest_draft(db, root, timestamp):
    """Read the migration-time <=014 relational authority without seed manifests."""
    industries = tuple(
        _legacy_industry(db, row)
        for row in db.execute(
            "SELECT * FROM industries WHERE status='published' ORDER BY sort_order,id"
        )
    )
    questions = tuple(
        _load_question(db, row)
        for row in db.execute(
            "SELECT * FROM assessment_questions WHERE assessment_version_id=? "
            "ORDER BY sort_order,id",
            (root["id"],),
        )
    )
    weights = _load_dimension_maps(
        db, root["id"], "assessment_branch_weights", "weight"
    )
    benchmarks = tuple(
        ReleaseBenchmark(
            branch_code=row["code"],
            label=row["label"],
            scores={name: row[f"{name}_score"] for name in DIMENSION_ORDER},
        )
        for row in db.execute(
            "SELECT b.*,i.code FROM industry_benchmarks b "
            "JOIN industries i ON i.id=b.industry_id "
            "WHERE b.assessment_version_id=? ORDER BY i.sort_order,b.id",
            (root["id"],),
        )
    )
    roi_ranges = {}
    for row in db.execute(
        "SELECT * FROM roi_option_ranges WHERE assessment_version_id=? "
        "ORDER BY option_group,id",
        (root["id"],),
    ):
        roi_ranges.setdefault(row["option_group"], {})[row["code"]] = tuple(
            Decimal(str(row[f"{band}_value"])) for band in ("low", "mid", "high")
        )
    scenarios = tuple(
        _legacy_scenario(db, root["id"], row)
        for row in db.execute(
            "SELECT * FROM scenarios WHERE status='published' ORDER BY sort_order,id"
        )
    )
    services = tuple(
        _legacy_service(db, row)
        for row in db.execute(
            "SELECT * FROM services WHERE code IS NOT NULL AND status='published' "
            "ORDER BY sort_order,id"
        )
    )
    return RuleReleaseDraft(
        id=root["id"],
        code=root["code"],
        name=root["name"],
        status=root["status"],
        copied_from_id=root["copied_from_id"],
        lock_version=root["lock_version"],
        pain_min_selections=root["pain_min_selections"],
        pain_max_selections=root["pain_max_selections"],
        industries=industries,
        company_sizes=tuple(
            ReleaseLabeledCode(row["code"], row["name"], row["sort_order"])
            for row in db.execute(
                "SELECT * FROM company_sizes WHERE status='published' ORDER BY sort_order,id"
            )
        ),
        questions=questions,
        branch_weights=weights,
        benchmarks=benchmarks,
        roi_ranges=roi_ranges,
        scenarios=scenarios,
        services=services,
        public_labels=_initial_public_labels(),
        created_at=root["created_at"],
        updated_at=timestamp,
        published_at=root["published_at"],
    )


def _legacy_industry(db, row):
    def values(table):
        return tuple(
            ReleaseLabeledCode(item["code"], item["name"], item["sort_order"])
            for item in db.execute(
                f"SELECT * FROM {table} WHERE industry_id=? AND status='published' "
                "ORDER BY sort_order,id",
                (row["id"],),
            )
        )

    return ReleaseIndustry(
        row["code"],
        row["name"],
        row["sort_order"],
        values("industry_branches"),
        values("departments"),
        values("pain_points"),
    )


def _legacy_scenario(db, version_id, row):
    scenario_id = row["id"]
    branch_codes = tuple(
        item[0]
        for item in db.execute(
            "SELECT i.code FROM scenario_branches x "
            "JOIN industry_branches b ON b.id=x.industry_branch_id "
            "JOIN industries i ON i.id=b.industry_id WHERE x.scenario_id=? "
            "GROUP BY i.id,i.code,i.sort_order ORDER BY i.sort_order,i.id",
            (scenario_id,),
        )
    )
    roi = db.execute(
        "SELECT * FROM scenario_roi_profiles WHERE assessment_version_id=? AND scenario_id=?",
        (version_id, scenario_id),
    ).fetchone()
    service = db.execute(
        "SELECT s.code FROM scenario_services x JOIN services s ON s.id=x.service_id "
        "WHERE x.scenario_id=?",
        (scenario_id,),
    ).fetchone()

    def scoped_codes(link_table, source_table, target_column):
        return tuple(
            ReleaseScopedCode(item["branch_code"], item["code"], index)
            for index, item in enumerate(db.execute(
                f"SELECT i.code branch_code,t.code FROM {link_table} x JOIN {source_table} t "
                f"ON t.id=x.{target_column} JOIN industries i ON i.id=t.industry_id "
                "WHERE x.scenario_id=? GROUP BY i.code,t.code "
                "ORDER BY MIN(i.sort_order),MIN(t.sort_order),MIN(t.id)",
                (scenario_id,),
            ), 1)
        )

    return ReleaseScenario(
        code=row["code"],
        category_code=row["category_code"],
        public_name=row["public_name"],
        description="" if row["description"] is None else row["description"],
        branch_codes=branch_codes,
        department_links=scoped_codes("scenario_departments", "departments", "department_id"),
        pain_links=scoped_codes("scenario_pains", "pain_points", "pain_point_id"),
        minimum_scores={name: row[f"minimum_{name}"] for name in DIMENSION_ORDER},
        integration_level=row["integration_level"],
        budget_codes=tuple(
            item[0]
            for item in db.execute(
                "SELECT budget_code FROM scenario_budget_options WHERE scenario_id=? "
                "ORDER BY sort_order,budget_code",
                (scenario_id,),
            )
        ),
        min_weeks=row["min_weeks"],
        max_weeks=row["max_weeks"],
        efficiency=tuple(Decimal(str(roi[f"efficiency_{band}"])) for band in ("low", "mid", "high")),
        loss_improvement=tuple(Decimal(str(roi[f"loss_improvement_{band}"])) for band in ("low", "mid", "high")),
        annual_support_rate=tuple(Decimal(str(roi[f"annual_support_rate_{band}"])) for band in ("low", "mid", "high")),
        risk_codes=tuple(json.loads(row["risk_codes_json"])),
        service_code=service[0],
        sort_order=row["sort_order"],
        fallback_only=bool(row["fallback_only"]),
    )


def _legacy_service(db, row):
    def json_values(column):
        value = json.loads(row[column])
        return tuple(value)

    return ReleaseService(
        code=row["code"],
        category=row["category"],
        public_name=row["public_name"],
        min_budget=Decimal(str(row["min_budget"])),
        max_budget=Decimal(str(row["max_budget"])),
        min_weeks=row["min_weeks"],
        max_weeks=row["max_weeks"],
        deliverables=tuple(
            item[0]
            for item in db.execute(
                "SELECT title FROM service_deliverables WHERE service_id=? AND status='published' "
                "ORDER BY sort_order,id",
                (row["id"],),
            )
        ),
        implementation_steps=json_values("implementation_steps_json"),
        prerequisites=json_values("prerequisites_json"),
        not_included=json_values("not_included_json"),
        acceptance=json_values("acceptance_json"),
        support_days=row["support_days"],
        support_description=row["support_description"],
        public_disclaimer=row["public_disclaimer"],
        sort_order=row["sort_order"],
    )


_RELEASE_ROOT_TABLES = (
    "assessment_release_industries",
    "assessment_release_company_sizes",
    "assessment_release_scenarios",
    "assessment_release_services",
    "assessment_release_public_labels",
    "assessment_release_roi_ranges",
)


def _insert_all_release_children(db, version_id, draft):
    _insert_existing_children(db, version_id, draft)
    _insert_release_projection(db, version_id, draft)


def _insert_existing_children(db, version_id, draft):
    industry_ids = {
        row["code"]: row["id"] for row in db.execute("SELECT id,code FROM industries")
    }
    for question in draft.questions:
        question_id = db.execute(
            "INSERT INTO assessment_questions "
            "(assessment_version_id,code,dimension_code,prompt,sort_order,status) "
            "VALUES (?,?,?,?,?,'published')",
            (version_id, question.code, question.dimension, question.prompt, question.sort_order),
        ).lastrowid
        db.executemany(
            "INSERT INTO assessment_options (question_id,code,label,score,sort_order) "
            "VALUES (?,?,?,?,?)",
            [
                (question_id, item.code, item.label, item.score, item.sort_order)
                for item in question.options
            ],
        )
    for code, weights in draft.branch_weights.items():
        db.execute(
            "INSERT INTO assessment_branch_weights "
            "(assessment_version_id,industry_id,business_value_weight,process_weight,"
            "data_weight,systems_weight,organization_weight,delivery_weight) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (version_id, industry_ids[code], *(weights[name] for name in DIMENSION_ORDER)),
        )
    for item in draft.benchmarks:
        db.execute(
            "INSERT INTO industry_benchmarks "
            "(assessment_version_id,industry_id,label,business_value_score,process_score,"
            "data_score,systems_score,organization_score,delivery_score) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (version_id, industry_ids[item.branch_code], item.label, *(item.scores[name] for name in DIMENSION_ORDER)),
        )
    for group, options in draft.roi_ranges.items():
        db.executemany(
            "INSERT INTO roi_option_ranges "
            "(assessment_version_id,option_group,code,low_value,mid_value,high_value) "
            "VALUES (?,?,?,?,?,?)",
            [
                (version_id, group, code, *(str(value) for value in values))
                for code, values in options.items()
            ],
        )


def _insert_release_projection(db, version_id, draft):
    for family in (
        "risk_labels",
        "risk_explanations",
        "dimensions",
        "maturities",
        "integrations",
        "roi_groups",
    ):
        db.executemany(
            "INSERT INTO assessment_release_public_labels "
            "(assessment_version_id,family,parent_code,code,label,sort_order) "
            "VALUES (?,?, '',?,?,?)",
            [
                (version_id, family, code, label, index)
                for index, (code, label) in enumerate(
                    getattr(draft.public_labels, family).items(), 1
                )
            ],
        )
    for group, values in draft.public_labels.roi_options.items():
        db.executemany(
            "INSERT INTO assessment_release_public_labels "
            "(assessment_version_id,family,parent_code,code,label,sort_order) "
            "VALUES (?,'roi_options',?,?,?,?)",
            [
                (version_id, group, code, label, index)
                for index, (code, label) in enumerate(values.items(), 1)
            ],
        )
    for group, options in draft.roi_ranges.items():
        db.executemany(
            "INSERT INTO assessment_release_roi_ranges "
            "(assessment_version_id,option_group,code,low_value,mid_value,high_value,sort_order) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                (
                    version_id,
                    group,
                    code,
                    *(str(value) for value in values),
                    index,
                )
                for index, (code, values) in enumerate(options.items(), 1)
            ],
        )
    for industry in draft.industries:
        industry_id = db.execute(
            "INSERT INTO assessment_release_industries "
            "(assessment_version_id,code,label,sort_order) VALUES (?,?,?,?)",
            (version_id, industry.code, industry.label, industry.sort_order),
        ).lastrowid
        db.executemany(
            "INSERT INTO assessment_release_subbranches "
            "(assessment_version_id,industry_id,code,label,sort_order) VALUES (?,?,?,?,?)",
            [
                (version_id, industry_id, item.code, item.label, item.sort_order)
                for item in industry.subbranches
            ],
        )
        for table, items in (
            ("assessment_release_departments", industry.departments),
            ("assessment_release_pain_points", industry.pain_points),
        ):
            db.executemany(
                f"INSERT INTO {table} "
                "(assessment_version_id,industry_id,branch_code,code,label,sort_order) "
                "VALUES (?,?,?,?,?,?)",
                [
                    (
                        version_id,
                        industry_id,
                        industry.code,
                        item.code,
                        item.label,
                        item.sort_order,
                    )
                    for item in items
                ],
            )
    db.executemany(
        "INSERT INTO assessment_release_company_sizes "
        "(assessment_version_id,code,label,sort_order) VALUES (?,?,?,?)",
        [(version_id, item.code, item.label, item.sort_order) for item in draft.company_sizes],
    )
    service_ids = {}
    item_tables = (
        ("assessment_release_service_deliverables", "deliverables"),
        ("assessment_release_service_steps", "implementation_steps"),
        ("assessment_release_service_prerequisites", "prerequisites"),
        ("assessment_release_service_exclusions", "not_included"),
        ("assessment_release_service_acceptance", "acceptance"),
    )
    for service in draft.services:
        service_id = db.execute(
            "INSERT INTO assessment_release_services "
            "(assessment_version_id,code,category,public_name,min_budget,max_budget,min_weeks,max_weeks,"
            "support_days,support_description,public_disclaimer,sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                version_id, service.code, service.category, service.public_name,
                str(service.min_budget), str(service.max_budget), service.min_weeks,
                service.max_weeks, service.support_days, service.support_description,
                service.public_disclaimer, service.sort_order,
            ),
        ).lastrowid
        service_ids[service.code] = service_id
        for table, attribute in item_tables:
            db.executemany(
                f"INSERT INTO {table} (assessment_version_id,service_id,value,sort_order) "
                "VALUES (?,?,?,?)",
                [
                    (version_id, service_id, value, index)
                    for index, value in enumerate(getattr(service, attribute), 1)
                ],
            )
    for scenario in draft.scenarios:
        scenario_id = db.execute(
            "INSERT INTO assessment_release_scenarios "
            "(assessment_version_id,code,category_code,public_name,description,minimum_business_value,"
            "minimum_process,minimum_data,minimum_systems,minimum_organization,minimum_delivery,"
            "integration_level,min_weeks,max_weeks,fallback_only,sort_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                version_id, scenario.code, scenario.category_code, scenario.public_name,
                scenario.description, *(scenario.minimum_scores[name] for name in DIMENSION_ORDER),
                scenario.integration_level, scenario.min_weeks, scenario.max_weeks,
                int(scenario.fallback_only), scenario.sort_order,
            ),
        ).lastrowid
        db.executemany(
            "INSERT INTO assessment_release_scenario_branches "
            "(assessment_version_id,scenario_id,branch_code,sort_order) VALUES (?,?,?,?)",
            [(version_id, scenario_id, code, index) for index, code in enumerate(scenario.branch_codes, 1)],
        )
        db.executemany(
            "INSERT INTO assessment_release_scenario_departments "
            "(assessment_version_id,scenario_id,branch_code,department_code,sort_order) VALUES (?,?,?,?,?)",
            [
                (version_id, scenario_id, item.branch_code, item.code, item.sort_order)
                for item in scenario.department_links
            ],
        )
        db.executemany(
            "INSERT INTO assessment_release_scenario_pains "
            "(assessment_version_id,scenario_id,branch_code,pain_code,sort_order) VALUES (?,?,?,?,?)",
            [
                (version_id, scenario_id, item.branch_code, item.code, item.sort_order)
                for item in scenario.pain_links
            ],
        )
        for table, column, values in (
            ("assessment_release_scenario_budgets", "budget_code", scenario.budget_codes),
            ("assessment_release_scenario_risks", "risk_code", scenario.risk_codes),
        ):
            db.executemany(
                f"INSERT INTO {table} (assessment_version_id,scenario_id,{column},sort_order) VALUES (?,?,?,?)",
                [(version_id, scenario_id, code, index) for index, code in enumerate(values, 1)],
            )
        db.execute(
            "INSERT INTO assessment_release_scenario_roi "
            "(assessment_version_id,scenario_id,efficiency_low,efficiency_mid,efficiency_high,"
            "loss_improvement_low,loss_improvement_mid,loss_improvement_high,annual_support_rate_low,"
            "annual_support_rate_mid,annual_support_rate_high) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                version_id, scenario_id, *(str(value) for value in scenario.efficiency),
                *(str(value) for value in scenario.loss_improvement),
                *(str(value) for value in scenario.annual_support_rate),
            ),
        )
        db.execute(
            "INSERT INTO assessment_release_scenario_services "
            "(assessment_version_id,scenario_id,service_id) VALUES (?,?,?)",
            (version_id, scenario_id, service_ids[scenario.service_code]),
        )


def _delete_all_release_children(db, version_id):
    for table in (
        "assessment_options",
        "assessment_release_scenario_services",
        "assessment_release_scenario_roi",
        "assessment_release_scenario_risks",
        "assessment_release_scenario_budgets",
        "assessment_release_scenario_pains",
        "assessment_release_scenario_departments",
        "assessment_release_scenario_branches",
        "assessment_release_service_acceptance",
        "assessment_release_service_exclusions",
        "assessment_release_service_prerequisites",
        "assessment_release_service_steps",
        "assessment_release_service_deliverables",
        "assessment_release_public_labels",
        "assessment_release_roi_ranges",
    ):
        if table == "assessment_options":
            db.execute(
                "DELETE FROM assessment_options WHERE question_id IN "
                "(SELECT id FROM assessment_questions WHERE assessment_version_id=?)",
                (version_id,),
            )
        else:
            db.execute(f"DELETE FROM {table} WHERE assessment_version_id=?", (version_id,))
    for table in (
        "assessment_release_scenarios",
        "assessment_release_services",
        "assessment_release_subbranches",
        "assessment_release_departments",
        "assessment_release_pain_points",
        "assessment_release_industries",
        "assessment_release_company_sizes",
        "assessment_questions",
        "assessment_branch_weights",
        "industry_benchmarks",
        "roi_option_ranges",
    ):
        db.execute(f"DELETE FROM {table} WHERE assessment_version_id=?", (version_id,))


def _load_release_draft_from_db(db, release_id):
    root = db.execute("SELECT * FROM assessment_versions WHERE id=?", (release_id,)).fetchone()
    if root is None:
        raise LookupError("rule release not found")
    industries = tuple(_load_industry(db, row) for row in db.execute(
        "SELECT * FROM assessment_release_industries WHERE assessment_version_id=? ORDER BY sort_order",
        (release_id,),
    ))
    questions = tuple(_load_question(db, row) for row in db.execute(
        "SELECT * FROM assessment_questions WHERE assessment_version_id=? ORDER BY sort_order",
        (release_id,),
    ))
    weights = _load_dimension_maps(db, release_id, "assessment_branch_weights", "weight")
    benchmarks = tuple(
        ReleaseBenchmark(
            branch_code=row["code"], label=row["label"],
            scores={name: row[f"{name}_score"] for name in DIMENSION_ORDER},
        )
        for row in db.execute(
            "SELECT b.*,i.code FROM industry_benchmarks b JOIN industries i ON i.id=b.industry_id "
            "WHERE b.assessment_version_id=? ORDER BY i.sort_order", (release_id,)
        )
    )
    roi_ranges = {}
    for row in db.execute(
        "SELECT * FROM assessment_release_roi_ranges WHERE assessment_version_id=? "
        "ORDER BY option_group,sort_order",
        (release_id,),
    ):
        roi_ranges.setdefault(row["option_group"], {})[row["code"]] = tuple(
            Decimal(str(row[f"{band}_value"])) for band in ("low", "mid", "high")
        )
    services = tuple(_load_service(db, row) for row in db.execute(
        "SELECT * FROM assessment_release_services WHERE assessment_version_id=? ORDER BY sort_order",
        (release_id,),
    ))
    scenarios = tuple(_load_scenario(db, row) for row in db.execute(
        "SELECT * FROM assessment_release_scenarios WHERE assessment_version_id=? ORDER BY sort_order",
        (release_id,),
    ))
    return RuleReleaseDraft(
        id=root["id"], code=root["code"], name=root["name"], status=root["status"],
        copied_from_id=root["copied_from_id"], lock_version=root["lock_version"],
        pain_min_selections=root["pain_min_selections"], pain_max_selections=root["pain_max_selections"],
        industries=industries,
        company_sizes=tuple(
            ReleaseLabeledCode(row["code"], row["label"], row["sort_order"])
            for row in db.execute(
                "SELECT * FROM assessment_release_company_sizes WHERE assessment_version_id=? ORDER BY sort_order",
                (release_id,),
            )
        ),
        questions=questions, branch_weights=weights, benchmarks=benchmarks,
        roi_ranges=roi_ranges, scenarios=scenarios, services=services,
        public_labels=_load_public_labels(db, release_id),
        created_at=root["created_at"], updated_at=root["updated_at"], published_at=root["published_at"],
    )


def _load_public_labels(db, release_id):
    simple = {}
    for family in (
        "risk_labels",
        "risk_explanations",
        "dimensions",
        "maturities",
        "integrations",
        "roi_groups",
    ):
        simple[family] = {
            row["code"]: row["label"]
            for row in db.execute(
                "SELECT code,label FROM assessment_release_public_labels "
                "WHERE assessment_version_id=? AND family=? AND parent_code='' "
                "ORDER BY sort_order",
                (release_id, family),
            )
        }
    roi_options = {}
    for row in db.execute(
        "SELECT parent_code,code,label FROM assessment_release_public_labels "
        "WHERE assessment_version_id=? AND family='roi_options' "
        "ORDER BY parent_code,sort_order",
        (release_id,),
    ):
        roi_options.setdefault(row["parent_code"], {})[row["code"]] = row["label"]
    return ReleasePublicLabels(**simple, roi_options=roi_options)


def _load_industry(db, row):
    def values(table):
        return tuple(
            ReleaseLabeledCode(item["code"], item["label"], item["sort_order"])
            for item in db.execute(f"SELECT * FROM {table} WHERE industry_id=? ORDER BY sort_order", (row["id"],))
        )
    return ReleaseIndustry(
        row["code"], row["label"], row["sort_order"],
        values("assessment_release_subbranches"),
        values("assessment_release_departments"),
        values("assessment_release_pain_points"),
    )


def _load_question(db, row):
    return ReleaseQuestion(
        code=row["code"], dimension=row["dimension_code"], prompt=row["prompt"], sort_order=row["sort_order"],
        options=tuple(
            ReleaseQuestionOption(item["code"], item["label"], item["score"], item["sort_order"])
            for item in db.execute("SELECT * FROM assessment_options WHERE question_id=? ORDER BY sort_order", (row["id"],))
        ),
    )


def _load_dimension_maps(db, release_id, table, suffix):
    return {
        row["code"]: {name: row[f"{name}_{suffix}"] for name in DIMENSION_ORDER}
        for row in db.execute(
            f"SELECT r.*,i.code FROM {table} r JOIN industries i ON i.id=r.industry_id "
            "WHERE r.assessment_version_id=? ORDER BY i.sort_order", (release_id,)
        )
    }


def _load_service(db, row):
    def values(table):
        return tuple(item[0] for item in db.execute(
            f"SELECT value FROM {table} WHERE service_id=? ORDER BY sort_order", (row["id"],)
        ))
    return ReleaseService(
        code=row["code"], category=row["category"], public_name=row["public_name"],
        min_budget=Decimal(row["min_budget"]), max_budget=Decimal(row["max_budget"]),
        min_weeks=row["min_weeks"], max_weeks=row["max_weeks"],
        deliverables=values("assessment_release_service_deliverables"),
        implementation_steps=values("assessment_release_service_steps"),
        prerequisites=values("assessment_release_service_prerequisites"),
        not_included=values("assessment_release_service_exclusions"),
        acceptance=values("assessment_release_service_acceptance"),
        support_days=row["support_days"], support_description=row["support_description"],
        public_disclaimer=row["public_disclaimer"], sort_order=row["sort_order"],
    )


def _load_scenario(db, row):
    scenario_id = row["id"]
    def codes(table, column, distinct=False):
        select = "SELECT DISTINCT" if distinct else "SELECT"
        order = "MIN(sort_order)" if distinct else "sort_order"
        group = f" GROUP BY {column}" if distinct else ""
        return tuple(item[0] for item in db.execute(
            f"{select} {column} FROM {table} WHERE scenario_id=?{group} ORDER BY {order}", (scenario_id,)
        ))
    roi = db.execute("SELECT * FROM assessment_release_scenario_roi WHERE scenario_id=?", (scenario_id,)).fetchone()
    service = db.execute(
        "SELECT s.code FROM assessment_release_scenario_services x "
        "JOIN assessment_release_services s ON s.id=x.service_id WHERE x.scenario_id=?", (scenario_id,)
    ).fetchone()
    return ReleaseScenario(
        code=row["code"], category_code=row["category_code"], public_name=row["public_name"],
        description=row["description"], branch_codes=codes("assessment_release_scenario_branches", "branch_code"),
        department_links=tuple(
            ReleaseScopedCode(item["branch_code"], item["department_code"], item["sort_order"])
            for item in db.execute(
                "SELECT * FROM assessment_release_scenario_departments "
                "WHERE scenario_id=? ORDER BY sort_order", (scenario_id,)
            )
        ),
        pain_links=tuple(
            ReleaseScopedCode(item["branch_code"], item["pain_code"], item["sort_order"])
            for item in db.execute(
                "SELECT * FROM assessment_release_scenario_pains "
                "WHERE scenario_id=? ORDER BY sort_order", (scenario_id,)
            )
        ),
        minimum_scores={name: row[f"minimum_{name}"] for name in DIMENSION_ORDER},
        integration_level=row["integration_level"],
        budget_codes=codes("assessment_release_scenario_budgets", "budget_code"),
        min_weeks=row["min_weeks"], max_weeks=row["max_weeks"],
        efficiency=tuple(Decimal(roi[f"efficiency_{band}"]) for band in ("low", "mid", "high")),
        loss_improvement=tuple(Decimal(roi[f"loss_improvement_{band}"]) for band in ("low", "mid", "high")),
        annual_support_rate=tuple(Decimal(roi[f"annual_support_rate_{band}"]) for band in ("low", "mid", "high")),
        risk_codes=codes("assessment_release_scenario_risks", "risk_code"),
        service_code=service[0], sort_order=row["sort_order"], fallback_only=bool(row["fallback_only"]),
    )
