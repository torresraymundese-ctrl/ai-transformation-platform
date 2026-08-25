"""Exact live-V2 service authority shared by publication and public reads."""

from dataclasses import dataclass
import re

from content_json import ContentJsonError, decode_database_json
from content_validation import (
    is_exact_nonblank_text,
    is_valid_public_budget_range,
    is_valid_public_week_range,
)


SERVICE_CATEGORY_CODES = frozenset({"foundation", "pilot", "standard", "integration"})
INTEGRATION_CODES = ("low", "medium", "high")
CORE_CODE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
DELIVERABLE_CODE = re.compile(r"^[a-z0-9]+(?:(?:_|:|-)[a-z0-9]+)*$")


@dataclass(frozen=True)
class ServiceFacet:
    code: str
    label: str


@dataclass(frozen=True)
class ServiceDeliverable:
    code: str
    title: str
    description: str | None


@dataclass(frozen=True)
class ServiceScenario:
    scenario_id: int
    code: str
    core_name: str
    integration_code: str
    title: str | None = None
    slug: str | None = None


@dataclass(frozen=True)
class ServiceAuthority:
    service_id: int
    code: str
    category_code: str
    public_name: str
    min_budget: int | float
    max_budget: int | float
    min_weeks: int
    max_weeks: int
    implementation_steps: tuple[str, ...]
    prerequisites: tuple[str, ...]
    not_included: tuple[str, ...]
    acceptance: tuple[str, ...]
    support_days: int
    support_description: str
    public_disclaimer: str
    deliverables: tuple[ServiceDeliverable, ...]
    scenarios: tuple[ServiceScenario, ...]
    industries: tuple[ServiceFacet, ...]
    departments: tuple[ServiceFacet, ...]
    pains: tuple[ServiceFacet, ...]
    integration_codes: tuple[str, ...]


def _exact_json_strings(value):
    try:
        decoded = decode_database_json(value)
    except ContentJsonError:
        return None
    if type(decoded) is not list or not decoded:
        return None
    if not all(is_exact_nonblank_text(item) for item in decoded):
        return None
    return tuple(decoded)


def _exact_core_code(value):
    return type(value) is str and CORE_CODE.fullmatch(value) is not None


def _exact_deliverable_code(value):
    return type(value) is str and DELIVERABLE_CODE.fullmatch(value) is not None


def _deduplicated_facets(rows):
    facets = []
    seen = set()
    for row in rows:
        if (
            row["relation_status"] != "published"
            or row["catalog_status"] != "published"
            or not _exact_core_code(row["code"])
            or not is_exact_nonblank_text(row["name"])
        ):
            return None
        if row["code"] in seen:
            continue
        seen.add(row["code"])
        facets.append(ServiceFacet(row["code"], row["name"]))
    return tuple(facets)


def _service_facets(db, scenario_ids, kind):
    placeholders = ",".join("?" for _ in scenario_ids)
    if kind == "industries":
        sql = (
            "SELECT link.scenario_id,i.code,i.name,i.sort_order,i.id,"
            "branch.status AS relation_status,i.status AS catalog_status "
            "FROM scenario_branches link "
            "JOIN industry_branches branch ON branch.id=link.industry_branch_id "
            "JOIN industries i ON i.id=branch.industry_id "
            f"WHERE link.scenario_id IN ({placeholders}) "
            "ORDER BY i.sort_order,i.id,link.scenario_id"
        )
    elif kind == "departments":
        sql = (
            "SELECT link.scenario_id,d.code,d.name,d.sort_order,d.id,"
            "d.status AS relation_status,d.status AS catalog_status "
            "FROM scenario_departments link JOIN departments d ON d.id=link.department_id "
            f"WHERE link.scenario_id IN ({placeholders}) "
            "ORDER BY d.sort_order,d.id,link.scenario_id"
        )
    else:
        sql = (
            "SELECT link.scenario_id,p.code,p.name,p.sort_order,p.id,"
            "p.status AS relation_status,p.status AS catalog_status "
            "FROM scenario_pains link JOIN pain_points p ON p.id=link.pain_point_id "
            f"WHERE link.scenario_id IN ({placeholders}) "
            "ORDER BY p.sort_order,p.id,link.scenario_id"
        )
    rows = db.execute(sql, scenario_ids).fetchall()
    if kind in {"industries", "departments"}:
        covered = {row["scenario_id"] for row in rows}
        if covered != set(scenario_ids):
            return None
    return _deduplicated_facets(rows)


def valid_service_authority(authority):
    if type(authority) is not ServiceAuthority:
        return False
    if not all(
        type(values) is tuple
        for values in (
            authority.implementation_steps,
            authority.prerequisites,
            authority.not_included,
            authority.acceptance,
            authority.deliverables,
            authority.scenarios,
            authority.industries,
            authority.departments,
            authority.pains,
            authority.integration_codes,
        )
    ):
        return False
    if (
        not all(type(item) is ServiceDeliverable for item in authority.deliverables)
        or not all(type(item) is ServiceScenario for item in authority.scenarios)
        or not all(
            type(item) is ServiceFacet
            for values in (authority.industries, authority.departments, authority.pains)
            for item in values
        )
    ):
        return False
    if not (
        type(authority.service_id) is int
        and authority.service_id > 0
        and _exact_core_code(authority.code)
        and type(authority.category_code) is str
        and authority.category_code in SERVICE_CATEGORY_CODES
        and is_exact_nonblank_text(authority.public_name)
        and is_valid_public_budget_range(authority.min_budget, authority.max_budget)
        and is_valid_public_week_range(authority.min_weeks, authority.max_weeks)
        and all(
            values and all(is_exact_nonblank_text(value) for value in values)
            for values in (
                authority.implementation_steps,
                authority.prerequisites,
                authority.not_included,
                authority.acceptance,
            )
        )
        and type(authority.support_days) is int
        and authority.support_days > 0
        and is_exact_nonblank_text(authority.support_description)
        and is_exact_nonblank_text(authority.public_disclaimer)
    ):
        return False
    if not authority.deliverables or not all(
        _exact_deliverable_code(item.code)
        and is_exact_nonblank_text(item.title)
        and (item.description is None or is_exact_nonblank_text(item.description))
        for item in authority.deliverables
    ):
        return False
    if len({item.code for item in authority.deliverables}) != len(authority.deliverables):
        return False
    if not authority.scenarios or not all(
        type(item.scenario_id) is int
        and item.scenario_id > 0
        and _exact_core_code(item.code)
        and is_exact_nonblank_text(item.core_name)
        and type(item.integration_code) is str
        and item.integration_code in INTEGRATION_CODES
        and (
            (item.title is None and item.slug is None)
            or (
                is_exact_nonblank_text(item.title)
                and is_exact_nonblank_text(item.slug)
            )
        )
        for item in authority.scenarios
    ):
        return False
    if (
        len({item.scenario_id for item in authority.scenarios}) != len(authority.scenarios)
        or len({item.code for item in authority.scenarios}) != len(authority.scenarios)
    ):
        return False
    facets = (authority.industries, authority.departments, authority.pains)
    if not authority.industries or not authority.departments or not all(
        _exact_core_code(item.code) and is_exact_nonblank_text(item.label)
        for values in facets
        for item in values
    ):
        return False
    if any(len({item.code for item in values}) != len(values) for values in facets):
        return False
    expected_integrations = tuple(
        code for code in INTEGRATION_CODES
        if any(scenario.integration_code == code for scenario in authority.scenarios)
    )
    return authority.integration_codes == expected_integrations


def load_service_authority(db, service_id):
    row = db.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
    if row is None or row["status"] != "published":
        return None
    structured = tuple(
        _exact_json_strings(row[column])
        for column in (
            "implementation_steps_json",
            "prerequisites_json",
            "not_included_json",
            "acceptance_json",
        )
    )
    if any(values is None for values in structured):
        return None
    deliverable_rows = db.execute(
        "SELECT code,title,description,status FROM service_deliverables "
        "WHERE service_id=? ORDER BY sort_order,id",
        (service_id,),
    ).fetchall()
    if not deliverable_rows or any(item["status"] != "published" for item in deliverable_rows):
        return None
    scenario_rows = db.execute(
        "SELECT scenario.id,scenario.code,scenario.public_name,scenario.integration_level,"
        "scenario.status FROM scenario_services link "
        "JOIN scenarios scenario ON scenario.id=link.scenario_id "
        "WHERE link.service_id=? ORDER BY scenario.sort_order,scenario.id",
        (service_id,),
    ).fetchall()
    if not scenario_rows or any(item["status"] != "published" for item in scenario_rows):
        return None
    scenarios = tuple(
        ServiceScenario(
            item["id"], item["code"], item["public_name"], item["integration_level"]
        )
        for item in scenario_rows
    )
    scenario_ids = tuple(item.scenario_id for item in scenarios)
    industries = _service_facets(db, scenario_ids, "industries")
    departments = _service_facets(db, scenario_ids, "departments")
    pains = _service_facets(db, scenario_ids, "pains")
    if industries is None or departments is None or pains is None:
        return None
    authority = ServiceAuthority(
        service_id=row["id"],
        code=row["code"],
        category_code=row["category"],
        public_name=row["public_name"],
        min_budget=row["min_budget"],
        max_budget=row["max_budget"],
        min_weeks=row["min_weeks"],
        max_weeks=row["max_weeks"],
        implementation_steps=structured[0],
        prerequisites=structured[1],
        not_included=structured[2],
        acceptance=structured[3],
        support_days=row["support_days"],
        support_description=row["support_description"],
        public_disclaimer=row["public_disclaimer"],
        deliverables=tuple(
            ServiceDeliverable(item["code"], item["title"], item["description"])
            for item in deliverable_rows
        ),
        scenarios=scenarios,
        industries=industries,
        departments=departments,
        pains=pains,
        integration_codes=tuple(
            code for code in INTEGRATION_CODES
            if code in {scenario.integration_code for scenario in scenarios}
        ),
    )
    return authority if valid_service_authority(authority) else None
