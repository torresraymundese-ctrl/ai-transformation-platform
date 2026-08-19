"""Load the immutable published V2 assessment and starter catalog."""

import json
from pathlib import Path


SEED_DATA_DIR = Path(__file__).resolve().parents[1] / "seed_data"


def _load_json(name):
    return json.loads((SEED_DATA_DIR / name).read_text(encoding="utf-8"))


def _json_tuple(values):
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def seed_v2_defaults(connection):
    """Insert the one published catalog version, returning if it already exists."""
    if connection.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='assessment_versions'"
    ).fetchone() is None:
        return
    assessment = _load_json("assessment_v2.json")
    version = assessment["version"]
    if connection.execute(
        "SELECT 1 FROM assessment_versions WHERE code=?", (version["code"],)
    ).fetchone():
        return

    core = _load_json("core_catalog_v2.json")
    industry_ids = _seed_industries(connection, core["industries"])
    _seed_company_sizes(connection, core["company_sizes"])
    version_id = connection.execute(
        "INSERT INTO assessment_versions "
        "(code,name,pain_min_selections,pain_max_selections,status,published_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            version["code"],
            version["name"],
            version["pain_min_selections"],
            version["pain_max_selections"],
            version["status"],
            version["published_at"],
        ),
    ).lastrowid
    _seed_assessment_rules(connection, assessment, version_id, industry_ids)
    service_ids = _seed_services(connection, core)
    _seed_scenarios(connection, core["scenarios"], version_id, industry_ids, service_ids)


def _seed_industries(connection, industries):
    industry_ids = {}
    for industry_order, industry in enumerate(industries, 1):
        connection.execute(
            "INSERT OR IGNORE INTO industries (code,name,status,sort_order) "
            "VALUES (?,?,?,?)",
            (industry["code"], industry["name"], "published", industry_order),
        )
        industry_id = connection.execute(
            "SELECT id FROM industries WHERE code=?", (industry["code"],)
        ).fetchone()[0]
        industry_ids[industry["code"]] = industry_id
        for sort_order, code in enumerate(industry["subbranches"], 1):
            connection.execute(
                "INSERT OR IGNORE INTO industry_branches "
                "(industry_id,code,name,status,sort_order) VALUES (?,?,?,?,?)",
                (industry_id, code, code, "published", sort_order),
            )
        for sort_order, code in enumerate(industry["departments"], 1):
            connection.execute(
                "INSERT OR IGNORE INTO departments "
                "(industry_id,code,name,status,sort_order) VALUES (?,?,?,?,?)",
                (industry_id, code, code, "published", sort_order),
            )
        for sort_order, code in enumerate(industry["pain_codes"], 1):
            connection.execute(
                "INSERT OR IGNORE INTO pain_points "
                "(industry_id,code,name,status,sort_order) VALUES (?,?,?,?,?)",
                (industry_id, code, code, "published", sort_order),
            )
    return industry_ids


def _seed_company_sizes(connection, company_sizes):
    for sort_order, code in enumerate(company_sizes, 1):
        connection.execute(
            "INSERT OR IGNORE INTO company_sizes (code,name,status,sort_order) "
            "VALUES (?,?,?,?)",
            (code, code, "published", sort_order),
        )


def _seed_assessment_rules(connection, assessment, version_id, industry_ids):
    for question_order, question in enumerate(assessment["questions"], 1):
        question_id = connection.execute(
            "INSERT INTO assessment_questions "
            "(assessment_version_id,code,dimension_code,prompt,sort_order,status) "
            "VALUES (?,?,?,?,?,?)",
            (
                version_id,
                question["code"],
                question["dimension"],
                question["prompt"],
                question_order,
                "published",
            ),
        ).lastrowid
        connection.executemany(
            "INSERT INTO assessment_options "
            "(question_id,code,label,score,sort_order) VALUES (?,?,?,?,?)",
            [
                (question_id, f"level_{score}", label, score, score + 1)
                for score, label in enumerate(question["options"])
            ],
        )

    for branch_code, weights in assessment["branch_weights"].items():
        connection.execute(
            "INSERT INTO assessment_branch_weights "
            "(assessment_version_id,industry_id,business_value_weight,"
            "process_weight,data_weight,systems_weight,organization_weight,"
            "delivery_weight) VALUES (?,?,?,?,?,?,?,?)",
            (version_id, industry_ids[branch_code], *weights),
        )
    for branch_code, scores in assessment["reference_lines"].items():
        connection.execute(
            "INSERT INTO industry_benchmarks "
            "(assessment_version_id,industry_id,label,business_value_score,"
            "process_score,data_score,systems_score,organization_score,delivery_score) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                version_id,
                industry_ids[branch_code],
                assessment["reference_label"],
                *scores,
            ),
        )
    for group, ranges in assessment["roi_ranges"].items():
        connection.executemany(
            "INSERT INTO roi_option_ranges "
            "(assessment_version_id,option_group,code,low_value,mid_value,high_value) "
            "VALUES (?,?,?,?,?,?)",
            [(version_id, group, code, *values) for code, values in ranges.items()],
        )


def _seed_services(connection, core):
    service_ids = {}
    for sort_order, service in enumerate(core["services"], 1):
        connection.execute(
            "INSERT OR IGNORE INTO services "
            "(code,name,tier,category,public_name,min_budget,max_budget,min_weeks,"
            "max_weeks,implementation_steps_json,prerequisites_json,"
            "not_included_json,acceptance_json,support_days,support_description,"
            "public_disclaimer,status,sort_order) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                service["code"],
                service["public_name"],
                "assessment",
                service["category"],
                service["public_name"],
                *service["budget"],
                *service["weeks"],
                _json_tuple(service["implementation_steps"]),
                _json_tuple(service["prerequisites"]),
                _json_tuple(service["not_included"]),
                _json_tuple(service["acceptance"]),
                service["support_days"],
                service["support_description"],
                core["public_disclaimer"],
                "published",
                sort_order,
            ),
        )
        service_id = connection.execute(
            "SELECT id FROM services WHERE code=?", (service["code"],)
        ).fetchone()[0]
        service_ids[service["code"]] = service_id
        for deliverable_order, title in enumerate(service["deliverables"], 1):
            connection.execute(
                "INSERT OR IGNORE INTO service_deliverables "
                "(code,service_id,title,status,sort_order) VALUES (?,?,?,?,?)",
                (
                    f"{service['code']}:{deliverable_order}",
                    service_id,
                    title,
                    "published",
                    deliverable_order,
                ),
            )
    return service_ids


def _seed_scenarios(connection, scenarios, version_id, industry_ids, service_ids):
    for sort_order, scenario in enumerate(scenarios, 1):
        minimums = scenario["minimum_scores"]
        connection.execute(
            "INSERT OR IGNORE INTO scenarios "
            "(code,category_code,public_name,minimum_business_value,minimum_process,"
            "minimum_data,minimum_systems,minimum_organization,minimum_delivery,"
            "integration_level,min_weeks,max_weeks,risk_codes_json,fallback_only,"
            "status,sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                scenario["code"],
                scenario["category_code"],
                scenario["code"],
                *minimums,
                scenario["integration_level"],
                *scenario["weeks"],
                _json_tuple(scenario["risk_codes"]),
                int(scenario.get("fallback_only", False)),
                "published",
                sort_order,
            ),
        )
        scenario_id = connection.execute(
            "SELECT id FROM scenarios WHERE code=?", (scenario["code"],)
        ).fetchone()[0]
        branch_ids = [industry_ids[code] for code in scenario["branches"]]
        placeholders = ",".join("?" for _ in branch_ids)
        subbranch_ids = [
            row[0]
            for row in connection.execute(
                f"SELECT id FROM industry_branches WHERE industry_id IN ({placeholders})",
                branch_ids,
            )
        ]
        connection.executemany(
            "INSERT INTO scenario_branches (scenario_id,industry_branch_id) "
            "VALUES (?,?)",
            [(scenario_id, subbranch_id) for subbranch_id in subbranch_ids],
        )
        _seed_scenario_code_links(
            connection,
            "departments",
            "scenario_departments",
            "department_id",
            scenario_id,
            branch_ids,
            scenario["departments"],
        )
        _seed_scenario_code_links(
            connection,
            "pain_points",
            "scenario_pains",
            "pain_point_id",
            scenario_id,
            branch_ids,
            scenario["pain_codes"],
        )
        connection.executemany(
            "INSERT INTO scenario_budget_options "
            "(scenario_id,budget_code,sort_order) VALUES (?,?,?)",
            [
                (scenario_id, code, budget_order)
                for budget_order, code in enumerate(scenario["budget_codes"], 1)
            ],
        )
        connection.execute(
            "INSERT INTO scenario_services (scenario_id,service_id) VALUES (?,?)",
            (scenario_id, service_ids[scenario["service_code"]]),
        )
        connection.execute(
            "INSERT INTO scenario_roi_profiles "
            "(assessment_version_id,scenario_id,efficiency_low,efficiency_mid,"
            "efficiency_high,loss_improvement_low,loss_improvement_mid,"
            "loss_improvement_high,annual_support_rate_low,annual_support_rate_mid,"
            "annual_support_rate_high) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                version_id,
                scenario_id,
                *scenario["efficiency"],
                *scenario["loss_improvement"],
                *scenario["annual_support_rate"],
            ),
        )


def _seed_scenario_code_links(
    connection, source_table, link_table, target_column, scenario_id, industry_ids, codes
):
    if not codes:
        return
    industry_placeholders = ",".join("?" for _ in industry_ids)
    code_placeholders = ",".join("?" for _ in codes)
    target_ids = [
        row[0]
        for row in connection.execute(
            f"SELECT id FROM {source_table} "
            f"WHERE industry_id IN ({industry_placeholders}) "
            f"AND code IN ({code_placeholders})",
            (*industry_ids, *codes),
        )
    ]
    connection.executemany(
        f"INSERT INTO {link_table} (scenario_id,{target_column}) VALUES (?,?)",
        [(scenario_id, target_id) for target_id in target_ids],
    )
