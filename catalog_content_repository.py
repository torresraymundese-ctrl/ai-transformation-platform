"""Read models and transaction services for the core content catalog."""

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Mapping

import models
from content_clock import as_shanghai, format_shanghai
from content_contracts import ContentDraft
from content_validation import ContentValidationError
from pagination import Page, PageRequest
import publishing_repository
import publishing_service
from publishing_repository import ContentConflictError, ContentNotFoundError


KIND_CONFIG = {
    "industry": {
        "table": "industries",
        "identity": "industry_id",
        "fields": (
            ("code", "稳定代码"),
            ("name", "核心名称"),
            ("sort_order", "目录顺序"),
        ),
    },
    "scenario": {
        "table": "scenarios",
        "identity": "scenario_id",
        "fields": (
            ("code", "稳定代码"),
            ("category_code", "类别代码"),
            ("minimum_business_value", "业务价值门槛"),
            ("minimum_process", "流程门槛"),
            ("minimum_data", "数据门槛"),
            ("minimum_systems", "系统门槛"),
            ("minimum_organization", "组织门槛"),
            ("minimum_delivery", "交付门槛"),
            ("integration_level", "集成级别"),
            ("min_weeks", "最短周期"),
            ("max_weeks", "最长周期"),
            ("risk_codes_json", "风险代码"),
            ("fallback_only", "仅作兜底"),
            ("sort_order", "目录顺序"),
        ),
    },
    "service": {
        "table": "services",
        "identity": "service_id",
        "fields": (
            ("code", "稳定代码"),
            ("public_name", "核心名称"),
            ("category", "服务类别"),
            ("min_budget", "预算下限"),
            ("max_budget", "预算上限"),
            ("min_weeks", "最短周期"),
            ("max_weeks", "最长周期"),
            ("implementation_steps_json", "实施步骤"),
            ("prerequisites_json", "客户配合"),
            ("not_included_json", "不包含范围"),
            ("acceptance_json", "验收标准"),
            ("support_days", "支持天数"),
            ("support_description", "支持说明"),
            ("public_disclaimer", "公开声明"),
            ("sort_order", "目录顺序"),
        ),
    },
}


class CatalogKindError(LookupError):
    pass


@dataclass(frozen=True)
class CatalogRow:
    kind: str
    core_id: int
    code: str
    group_key: str
    group_id: int
    slug: str
    title: str
    status: str
    draft_id: int | None
    public_id: int | None


@dataclass(frozen=True)
class RevisionProjection:
    id: int
    revision_number: int
    status: str
    lock_version: int
    slug: str
    title: str
    summary: str
    seo_title: str
    seo_description: str
    share_image_media_id: int | None
    blocks: tuple[Any, ...]
    relations: tuple[Any, ...]
    maturity_codes: tuple[str, ...]


@dataclass(frozen=True)
class RelationChoice:
    group_id: int
    entry_type: str
    title: str


@dataclass(frozen=True)
class MediaChoice:
    id: int
    display_name: str
    detected_mime: str


@dataclass(frozen=True)
class EditorProjection:
    kind: str
    core_id: int
    code: str
    group_key: str
    group_id: int
    slug: str
    readonly_fields: tuple[tuple[str, Any], ...]
    public_revision: RevisionProjection | None
    draft_revision: RevisionProjection | None
    latest_archived: RevisionProjection | None
    relation_choices: tuple[RelationChoice, ...]
    media_choices: tuple[MediaChoice, ...]


@dataclass(frozen=True)
class SaveResult:
    content_id: int
    lock_version: int
    published: bool


MATURITY_LABELS = {
    "explore": "探索",
    "pilot": "试点",
    "scale": "规模化",
    "collaborate": "协同",
}


@dataclass(frozen=True)
class ScenarioFilters:
    industry: str = ""
    department: str = ""
    maturity: str = ""


@dataclass(frozen=True)
class ScenarioCard:
    code: str
    slug: str
    title: str
    summary: str
    industries: tuple[str, ...]
    departments: tuple[str, ...]
    maturity: tuple[str, ...]


@dataclass(frozen=True)
class ScenarioAuthority:
    """Frozen V2 scenario controls; 5B may replace this with an active snapshot."""
    scenario_id: int
    code: str
    category_code: str
    minimum_business_value: int
    minimum_process: int
    minimum_data: int
    minimum_systems: int
    minimum_organization: int
    minimum_delivery: int
    integration_level: str
    min_weeks: int
    max_weeks: int
    risk_codes: tuple[str, ...]
    fallback_only: bool


def _public_item_where(now):
    return "ci.status='published' AND (ci.publish_at IS NULL OR ci.publish_at<=?)", (format_shanghai(now),)


def _published_codes(db, table):
    return {
        row[0] for row in db.execute(
            f"SELECT code FROM {table} WHERE status='published' AND code IS NOT NULL"
        )
    }


def parse_public_scenario_filters(values) -> ScenarioFilters:
    """GET filters intentionally degrade unknown values to the empty filter."""
    db = models.get_db()
    try:
        def valid(name, allowed):
            raw = values.get(name) if hasattr(values, "get") else None
            return raw if type(raw) is str and raw in allowed else ""

        return ScenarioFilters(
            industry=valid("industry", _published_codes(db, "industries")),
            department=valid("department", _published_codes(db, "departments")),
            maturity=valid("maturity", set(MATURITY_LABELS)),
        )
    finally:
        db.close()


def _names(db, sql, arguments):
    return tuple(row[0] for row in db.execute(sql, arguments))


def _scenario_card(db, row) -> ScenarioCard:
    scenario_id = row["scenario_id"]
    return ScenarioCard(
        code=row["code"], slug=row["slug"], title=row["title"], summary=row["summary"],
        industries=_names(
            db,
            "SELECT DISTINCT i.name FROM scenario_branches sb "
            "JOIN industry_branches ib ON ib.id=sb.industry_branch_id "
            "JOIN industries i ON i.id=ib.industry_id WHERE sb.scenario_id=? "
            "ORDER BY i.sort_order,i.id",
            (scenario_id,),
        ),
        departments=_names(
            db,
            "SELECT d.name FROM scenario_departments sd JOIN departments d ON d.id=sd.department_id "
            "WHERE sd.scenario_id=? ORDER BY d.industry_id,d.sort_order,d.id",
            (scenario_id,),
        ),
        maturity=_names(
            db,
            "SELECT maturity_code FROM content_maturity_levels WHERE content_item_id=? "
            "ORDER BY sort_order,maturity_code",
            (row["content_id"],),
        ),
    )


def _public_scenarios(db, filters: ScenarioFilters, page_request: PageRequest, now) -> Page[ScenarioCard]:
    clause, arguments = _public_item_where(now)
    joins = [
        "FROM scenarios s JOIN content_groups g ON g.scenario_id=s.id "
        "JOIN content_items ci ON ci.content_group_id=g.id",
    ]
    conditions = ["s.status='published'", clause]
    parameters = list(arguments)
    if filters.industry:
        joins.append("JOIN scenario_branches filter_branch ON filter_branch.scenario_id=s.id "
                     "JOIN industry_branches filter_industry_branch ON filter_industry_branch.id=filter_branch.industry_branch_id "
                     "JOIN industries filter_industry ON filter_industry.id=filter_industry_branch.industry_id")
        conditions.append("filter_industry.code=? AND filter_industry.status='published'")
        parameters.append(filters.industry)
    if filters.department:
        joins.append("JOIN scenario_departments filter_department_link ON filter_department_link.scenario_id=s.id "
                     "JOIN departments filter_department ON filter_department.id=filter_department_link.department_id")
        conditions.append("filter_department.code=? AND filter_department.status='published'")
        parameters.append(filters.department)
    if filters.maturity:
        joins.append("JOIN content_maturity_levels filter_maturity ON filter_maturity.content_item_id=ci.id")
        conditions.append("filter_maturity.maturity_code=?")
        parameters.append(filters.maturity)
    query_from = " ".join(joins) + " WHERE " + " AND ".join(conditions)
    total = db.execute("SELECT COUNT(DISTINCT s.id) " + query_from, parameters).fetchone()[0]
    if total == 0:
        return Page((), 1, page_request.per_page, 0, 0)
    total_pages = (total + page_request.per_page - 1) // page_request.per_page
    page_number = page_request.page if page_request.page <= total_pages else 1
    rows = db.execute(
        "SELECT DISTINCT s.id AS scenario_id,s.code,ci.id AS content_id,ci.slug,ci.title,ci.summary "
        + query_from + " ORDER BY s.sort_order,s.id LIMIT ? OFFSET ?",
        [*parameters, page_request.per_page, (page_number - 1) * page_request.per_page],
    ).fetchall()
    return Page(tuple(_scenario_card(db, row) for row in rows), page_number, page_request.per_page, total, total_pages)


def public_industries(now) -> tuple[Mapping[str, Any], ...]:
    db = models.get_db()
    try:
        clause, arguments = _public_item_where(now)
        rows = db.execute(
            "SELECT i.id AS industry_id,i.code,ci.slug,ci.title,ci.summary "
            "FROM industries i JOIN content_groups g ON g.industry_id=i.id "
            "JOIN content_items ci ON ci.content_group_id=g.id "
            f"WHERE i.status='published' AND {clause} ORDER BY i.sort_order,i.id",
            arguments,
        ).fetchall()
        return tuple(MappingProxyType(dict(row)) for row in rows)
    finally:
        db.close()


def _resolution(db, entry_type, slug, now):
    clause, arguments = _public_item_where(now)
    row = db.execute(
        "SELECT ci.*,g.canonical_slug FROM content_items ci JOIN content_groups g "
        f"ON g.id=ci.content_group_id WHERE ci.entry_type=? AND ci.slug=? AND {clause}",
        (entry_type, slug, *arguments),
    ).fetchone()
    if row is not None:
        return row, False
    row = db.execute(
        "SELECT ci.*,g.canonical_slug FROM content_slug_aliases alias "
        "JOIN content_items ci ON ci.content_group_id=alias.content_group_id "
        "JOIN content_groups g ON g.id=ci.content_group_id "
        f"WHERE alias.entry_type=? AND alias.old_slug=? AND ci.entry_type=? AND {clause}",
        (entry_type, slug, entry_type, *arguments),
    ).fetchone()
    return (row, row is not None)


def _blocks(db, content_id):
    return tuple(
        MappingProxyType(dict(row)) for row in db.execute(
            "SELECT block_type,title,body_html FROM content_blocks WHERE content_item_id=? "
            "ORDER BY sort_order,id", (content_id,)
        )
    )


def _services_for_scenario(db, scenario_id):
    rows = db.execute(
        "SELECT s.id,s.code,s.public_name,s.min_budget,s.max_budget,s.min_weeks,s.max_weeks,"
        "s.implementation_steps_json,s.prerequisites_json FROM scenario_services link "
        "JOIN services s ON s.id=link.service_id WHERE link.scenario_id=? "
        "AND s.status='published' ORDER BY s.sort_order,s.id", (scenario_id,)
    ).fetchall()
    result = []
    for row in rows:
        values = dict(row)
        values["steps"] = tuple(json.loads(values.pop("implementation_steps_json") or "[]"))
        values["prerequisites"] = tuple(json.loads(values.pop("prerequisites_json") or "[]"))
        values["deliverables"] = _names(
            db, "SELECT title FROM service_deliverables WHERE service_id=? AND status='published' ORDER BY sort_order,id", (row["id"],)
        )
        result.append(MappingProxyType(values))
    return tuple(result)


def _scenario_authority(db, scenario_id):
    row = db.execute("SELECT * FROM scenarios WHERE id=? AND status='published'", (scenario_id,)).fetchone()
    if row is None:
        return None
    return ScenarioAuthority(
        scenario_id=row["id"], code=row["code"], category_code=row["category_code"],
        minimum_business_value=row["minimum_business_value"], minimum_process=row["minimum_process"],
        minimum_data=row["minimum_data"], minimum_systems=row["minimum_systems"],
        minimum_organization=row["minimum_organization"], minimum_delivery=row["minimum_delivery"],
        integration_level=row["integration_level"], min_weeks=row["min_weeks"], max_weeks=row["max_weeks"],
        risk_codes=tuple(json.loads(row["risk_codes_json"])), fallback_only=bool(row["fallback_only"]),
    )


def public_industry(slug: str, now) -> Mapping[str, Any] | None:
    db = models.get_db()
    try:
        item, redirect = _resolution(db, "industry", slug, now)
        if item is None:
            return None
        row = db.execute("SELECT i.id,i.code,i.name FROM industries i JOIN content_groups g ON g.industry_id=i.id WHERE g.id=? AND i.status='published'", (item["content_group_id"],)).fetchone()
        if row is None:
            return None
        page = _public_scenarios(db, ScenarioFilters(industry=row["code"]), PageRequest(1, 50), now)
        service_ids = tuple({service["id"] for card in page.items for service in _services_for_scenario(db, db.execute("SELECT id FROM scenarios WHERE code=?", (card.code,)).fetchone()[0])})
        services = tuple(
            MappingProxyType(dict(service)) for service in db.execute(
                f"SELECT id,code,public_name FROM services WHERE id IN ({','.join('?' for _ in service_ids)}) ORDER BY sort_order,id", service_ids
            )
        ) if service_ids else ()
        return MappingProxyType({
            "slug": item["slug"], "redirect": redirect, "title": item["title"], "summary": item["summary"],
            "seo_title": item["seo_title"], "seo_description": item["seo_description"], "blocks": _blocks(db, item["id"]),
            "pains": _names(db, "SELECT name FROM pain_points WHERE industry_id=? AND status='published' ORDER BY sort_order,id", (row["id"],)),
            "departments": _names(db, "SELECT name FROM departments WHERE industry_id=? AND status='published' ORDER BY sort_order,id", (row["id"],)),
            "company_sizes": _names(db, "SELECT name FROM company_sizes WHERE status='published' ORDER BY sort_order,id", ()),
            "scenarios": page.items, "services": services,
        })
    finally:
        db.close()


def public_scenarios(filters: ScenarioFilters, page: PageRequest, now) -> Page[ScenarioCard]:
    db = models.get_db()
    try:
        return _public_scenarios(db, filters, page, now)
    finally:
        db.close()


def public_scenario(slug: str, now, authority: ScenarioAuthority | None = None) -> Mapping[str, Any] | None:
    db = models.get_db()
    try:
        item, redirect = _resolution(db, "scenario", slug, now)
        if item is None:
            return None
        authority = authority or _scenario_authority(db, item["content_group_id"] and db.execute("SELECT scenario_id FROM content_groups WHERE id=?", (item["content_group_id"],)).fetchone()[0])
        if authority is None:
            return None
        services = _services_for_scenario(db, authority.scenario_id)
        return MappingProxyType({
            "slug": item["slug"], "redirect": redirect, "title": item["title"], "summary": item["summary"],
            "seo_title": item["seo_title"], "seo_description": item["seo_description"], "blocks": _blocks(db, item["id"]),
            "industries": _names(db, "SELECT DISTINCT i.name FROM scenario_branches sb JOIN industry_branches ib ON ib.id=sb.industry_branch_id JOIN industries i ON i.id=ib.industry_id WHERE sb.scenario_id=? ORDER BY i.sort_order,i.id", (authority.scenario_id,)),
            "departments": _names(db, "SELECT d.name FROM scenario_departments link JOIN departments d ON d.id=link.department_id WHERE link.scenario_id=? ORDER BY d.industry_id,d.sort_order,d.id", (authority.scenario_id,)),
            "pains": _names(db, "SELECT p.name FROM scenario_pains link JOIN pain_points p ON p.id=link.pain_point_id WHERE link.scenario_id=? ORDER BY p.industry_id,p.sort_order,p.id", (authority.scenario_id,)),
            "maturity": tuple(MATURITY_LABELS[code] for code in _names(db, "SELECT maturity_code FROM content_maturity_levels WHERE content_item_id=? ORDER BY sort_order,maturity_code", (item["id"],))),
            "services": services,
            "prerequisites": tuple(value for service in services for value in service["prerequisites"]),
            "outputs": tuple(value for service in services for value in service["deliverables"]),
            "steps": tuple(value for service in services for value in service["steps"]),
            "timeline": tuple((service["min_weeks"], service["max_weeks"]) for service in services),
            "budget": tuple((service["min_budget"], service["max_budget"]) for service in services),
        })
    finally:
        db.close()


def _config(kind):
    try:
        return KIND_CONFIG[kind]
    except (KeyError, TypeError) as error:
        raise CatalogKindError(kind) from error


def list_catalog(db, kind: str, page_request: PageRequest) -> Page[CatalogRow]:
    config = _config(kind)
    table = config["table"]
    identity = config["identity"]
    total = db.execute(
        f"SELECT COUNT(*) FROM content_groups g JOIN {table} core "
        f"ON core.id=g.{identity} WHERE g.entry_type=? AND core.status='published' "
        "AND core.code IS NOT NULL",
        (kind,),
    ).fetchone()[0]
    if total == 0:
        return Page((), 1, page_request.per_page, 0, 0)
    total_pages = (total + page_request.per_page - 1) // page_request.per_page
    page_number = page_request.page if page_request.page <= total_pages else 1
    rows = db.execute(
        f"SELECT core.id AS core_id,core.code,g.id AS group_id,g.canonical_slug,"
        "d.id AS draft_id,d.title AS draft_title,p.id AS public_id,p.title AS public_title "
        f"FROM content_groups g JOIN {table} core ON core.id=g.{identity} "
        "LEFT JOIN content_items d ON d.content_group_id=g.id AND d.status='draft' "
        "LEFT JOIN content_items p ON p.content_group_id=g.id AND p.status='published' "
        "WHERE g.entry_type=? AND core.status='published' AND core.code IS NOT NULL "
        "ORDER BY core.sort_order,core.id LIMIT ? OFFSET ?",
        (
            kind,
            page_request.per_page,
            (page_number - 1) * page_request.per_page,
        ),
    ).fetchall()
    items = tuple(
        CatalogRow(
            kind=kind,
            core_id=row["core_id"],
            code=row["code"],
            group_key=f"{kind}:{row['code']}",
            group_id=row["group_id"],
            slug=row["canonical_slug"],
            title=row["draft_title"] or row["public_title"] or row["code"],
            status="draft" if row["draft_id"] else "published" if row["public_id"] else "archived",
            draft_id=row["draft_id"],
            public_id=row["public_id"],
        )
        for row in rows
    )
    return Page(items, page_number, page_request.per_page, total, total_pages)


def get_catalog_page(kind: str, page_request: PageRequest) -> Page[CatalogRow]:
    db = models.get_db()
    try:
        return list_catalog(db, kind, page_request)
    finally:
        db.close()


def _load_identity(db, kind, core_id):
    config = _config(kind)
    if type(core_id) is not int or core_id < 1:
        raise ContentNotFoundError()
    row = db.execute(
        f"SELECT core.*,g.id AS group_id,g.canonical_slug FROM {config['table']} core "
        f"JOIN content_groups g ON g.{config['identity']}=core.id "
        "WHERE core.id=? AND core.code IS NOT NULL AND core.status='published' "
        "AND g.entry_type=?",
        (core_id, kind),
    ).fetchone()
    if row is None:
        raise ContentNotFoundError()
    return row, config


def _revision(db, content_id):
    if content_id is None:
        return None
    item = db.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone()
    if item is None:
        return None
    aggregate = publishing_repository.load_content_draft(db, content_id)
    return RevisionProjection(
        id=item["id"],
        revision_number=item["revision_number"],
        status=item["status"],
        lock_version=item["lock_version"],
        slug=item["slug"],
        title=aggregate.title,
        summary=aggregate.summary,
        seo_title=aggregate.seo_title,
        seo_description=aggregate.seo_description,
        share_image_media_id=aggregate.share_image_media_id,
        blocks=aggregate.blocks,
        relations=aggregate.relations,
        maturity_codes=aggregate.maturity_codes,
    )


def load_editor(db, kind: str, core_id: int) -> EditorProjection:
    identity_row, config = _load_identity(db, kind, core_id)
    group_id = identity_row["group_id"]
    states = {
        row["status"]: row["id"]
        for row in db.execute(
            "SELECT id,status FROM content_items WHERE content_group_id=? "
            "AND status IN ('draft','published')",
            (group_id,),
        )
    }
    archived = db.execute(
        "SELECT id FROM content_items WHERE content_group_id=? AND status='archived' "
        "ORDER BY revision_number DESC LIMIT 1",
        (group_id,),
    ).fetchone()
    relation_choices = tuple(
        RelationChoice(row["group_id"], row["entry_type"], row["title"])
        for row in db.execute(
            "SELECT g.id AS group_id,g.entry_type,ci.title FROM content_groups g "
            "JOIN content_items ci ON ci.content_group_id=g.id AND ci.status='published' "
            "WHERE g.entry_type IN ('case','resource') "
            "ORDER BY g.entry_type,ci.title,g.id"
        )
    )
    media_choices = tuple(
        MediaChoice(row["id"], row["display_name"], row["detected_mime"])
        for row in db.execute(
            "SELECT id,display_name,detected_mime FROM media_assets "
            "WHERE status='ready' ORDER BY display_name,id"
        )
    )
    return EditorProjection(
        kind=kind,
        core_id=core_id,
        code=identity_row["code"],
        group_key=f"{kind}:{identity_row['code']}",
        group_id=group_id,
        slug=identity_row["canonical_slug"],
        readonly_fields=tuple(
            (label, identity_row[column]) for column, label in config["fields"]
        ),
        public_revision=_revision(db, states.get("published")),
        draft_revision=_revision(db, states.get("draft")),
        latest_archived=_revision(db, archived["id"] if archived else None),
        relation_choices=relation_choices,
        media_choices=media_choices,
    )


def get_editor(kind: str, core_id: int) -> EditorProjection:
    db = models.get_db()
    try:
        return load_editor(db, kind, core_id)
    finally:
        db.close()


def ensure_editable_revision(kind: str, core_id: int, *, actor: str, now) -> EditorProjection:
    view = get_editor(kind, core_id)
    if view.draft_revision is not None:
        return view
    source = view.public_revision or view.latest_archived
    if source is None:
        raise ContentNotFoundError()
    try:
        publishing_service.copy_revision(source.id, actor=actor, now=now)
    except ContentConflictError as error:
        if error.code != "draft_already_exists":
            raise
    return get_editor(kind, core_id)


def _assert_content_identity(db, kind, core_id, content_id):
    identity_row, _ = _load_identity(db, kind, core_id)
    item = db.execute(
        "SELECT * FROM content_items WHERE id=? AND content_group_id=? AND entry_type=?",
        (content_id, identity_row["group_id"], kind),
    ).fetchone()
    if item is None:
        raise ContentNotFoundError()
    return item


def _assert_relation_targets(db, draft):
    for relation in draft.relations:
        expected_type = "case" if relation.relation_type.endswith("_case") else "resource"
        target = db.execute(
            "SELECT 1 FROM content_groups g JOIN content_items ci ON ci.content_group_id=g.id "
            "WHERE g.id=? AND g.entry_type=? AND ci.status='published'",
            (relation.target_group_id, expected_type),
        ).fetchone()
        if target is None:
            raise ContentValidationError("relation_target_not_published")


def _assert_media_choices(db, draft):
    media_ids = [draft.share_image_media_id]
    media_ids.extend(block.media_asset_id for block in draft.blocks)
    for media_id in media_ids:
        if media_id is None:
            continue
        ready = db.execute(
            "SELECT 1 FROM media_assets WHERE id=? AND status='ready'",
            (media_id,),
        ).fetchone()
        if ready is None:
            raise ContentValidationError("media_not_ready")


def save_catalog_draft(
    kind: str,
    core_id: int,
    content_id: int,
    expected_lock_version: int,
    draft: ContentDraft,
    *,
    action: str,
    actor: str,
    now,
) -> SaveResult:
    if action not in {"save", "review", "publish"}:
        raise ContentValidationError("action_invalid")
    instant = as_shanghai(now)
    db = models.get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        _assert_content_identity(db, kind, core_id, content_id)
        _assert_relation_targets(db, draft)
        _assert_media_choices(db, draft)
        lock_version = publishing_repository.update_content_draft(
            db,
            content_id,
            expected_lock_version,
            draft,
            actor=actor,
            now=instant,
        )
        published = False
        if action == "review":
            publishing_repository.validate_for_publication(db, content_id, instant)
            publishing_repository.write_audit_event(
                db, content_id, "content_reviewed", actor, instant
            )
        elif action == "publish":
            publishing_service._publish_in_transaction(
                db, content_id, lock_version, actor, instant
            )
            published = True
            lock_version += 1
        db.commit()
        return SaveResult(content_id, lock_version, published)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def archive_catalog_revision(
    kind: str,
    core_id: int,
    content_id: int,
    expected_lock_version: int,
    *,
    actor: str,
    now,
):
    db = models.get_db()
    try:
        _assert_content_identity(db, kind, core_id, content_id)
    finally:
        db.close()
    publishing_service.archive_content(
        content_id,
        expected_lock_version,
        actor=actor,
        now=now,
    )
