"""Strict deserialization of immutable assessment rule-release snapshots."""

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import sqlite3

from assessment.contracts import (
    AssessmentCatalog,
    Question,
    QuestionOption,
    ReleaseBenchmark,
    ReleaseIndustry,
    ReleaseLabeledCode,
    ReleasePublicLabels,
    ReleaseQuestion,
    ReleaseQuestionOption,
    ReleaseScenario,
    ReleaseScopedCode,
    ReleaseService,
    RuleReleaseDraft,
    Scenario,
    ServicePackage,
)
from assessment_repository import build_public_config
from assessment_validation import ROI_OPTION_CODES
from rule_release_validation import (
    MAX_RULE_SNAPSHOT_BYTES,
    SNAPSHOT_SCHEMA_VERSION,
    compile_release_snapshot,
    validate_canonical_release_json,
)


class RuleRuntimeError(RuntimeError):
    """Raised when a persisted rule release cannot be trusted at runtime."""


@dataclass(frozen=True)
class RuleBundle:
    """One branch projection from one exact immutable rule snapshot."""

    version_id: int
    version_code: str
    snapshot_sha256: str
    catalog: AssessmentCatalog
    public_config: dict[str, object]
    scenarios: tuple[Scenario, ...]
    services: tuple[ServicePackage, ...]
    roi_ranges: dict[str, dict[str, tuple[Decimal, Decimal, Decimal]]]
    release: RuleReleaseDraft


def load_active_rule_bundle(
    db: sqlite3.Connection, branch_code: str
) -> RuleBundle:
    """Load the active published release using only the caller's transaction."""
    _connection(db)
    row = db.execute(
        "SELECT v.*,s.schema_version,s.canonical_json,s.sha256 "
        "FROM active_assessment_version a "
        "JOIN assessment_versions v ON v.id=a.assessment_version_id "
        "JOIN assessment_version_snapshots s ON s.assessment_version_id=v.id "
        "WHERE a.singleton_id=1 AND v.status='published'"
    ).fetchone()
    if row is None:
        raise RuleRuntimeError("rule release unavailable")
    return _bundle_from_row(row, branch_code)


def load_rule_bundle(
    db: sqlite3.Connection, version_id: int, branch_code: str
) -> RuleBundle:
    """Load one published or archived historical release on a caller connection."""
    _connection(db)
    if type(version_id) is not int or version_id <= 0:
        raise RuleRuntimeError("rule release unavailable")
    row = db.execute(
        "SELECT v.*,s.schema_version,s.canonical_json,s.sha256 "
        "FROM assessment_versions v "
        "JOIN assessment_version_snapshots s ON s.assessment_version_id=v.id "
        "WHERE v.id=? AND v.status IN ('published','archived')",
        (version_id,),
    ).fetchone()
    if row is None:
        raise RuleRuntimeError("rule release unavailable")
    return _bundle_from_row(row, branch_code)


def _connection(db):
    if not isinstance(db, sqlite3.Connection):
        raise RuleRuntimeError("rule release unavailable")


def _bundle_from_row(row, branch_code):
    canonical = row["canonical_json"]
    digest = row["sha256"]
    try:
        if (
            type(branch_code) is not str
            or type(canonical) is not str
            or len(canonical.encode("utf-8")) > MAX_RULE_SNAPSHOT_BYTES
            or row["schema_version"] != SNAPSHOT_SCHEMA_VERSION
            or type(digest) is not str
            or len(digest) != 64
            or digest != digest.lower()
            or hashlib.sha256(canonical.encode("utf-8")).hexdigest() != digest
            or row["validated_digest"] != digest
            or not validate_canonical_release_json(
                canonical,
                row["code"],
                row["name"],
                row["pain_min_selections"],
                row["pain_max_selections"],
            )
        ):
            raise RuleRuntimeError("rule release unavailable")
        payload = json.loads(canonical)
        draft = _draft_from_payload(row, payload)
        compiled = compile_release_snapshot(draft)
        if compiled.canonical_json != canonical or compiled.sha256 != digest:
            raise RuleRuntimeError("rule release unavailable")
        industry = next(
            (item for item in draft.industries if item.code == branch_code), None
        )
        if industry is None:
            raise RuleRuntimeError("rule release unavailable")
        catalog = _catalog(draft, industry)
        public_config = _public_config(draft, catalog, industry)
        return RuleBundle(
            version_id=draft.id,
            version_code=draft.code,
            snapshot_sha256=digest,
            catalog=catalog,
            public_config=public_config,
            scenarios=_scenarios(draft, branch_code),
            services=_services(draft),
            roi_ranges={
                group: dict(values) for group, values in draft.roi_ranges.items()
            },
            release=draft,
        )
    except RuleRuntimeError:
        raise
    except (
        AttributeError,
        KeyError,
        LookupError,
        TypeError,
        ValueError,
        UnicodeError,
        ArithmeticError,
        json.JSONDecodeError,
    ) as error:
        raise RuleRuntimeError("rule release unavailable") from error


def _draft_from_payload(row, payload) -> RuleReleaseDraft:
    industries = tuple(
        ReleaseIndustry(
            code=item["code"],
            label=item["label"],
            sort_order=index,
            subbranches=_labeled(item["subbranches"]),
            departments=_labeled(item["departments"]),
            pain_points=_labeled(item["pain_points"]),
        )
        for index, item in enumerate(payload["industries"], 1)
    )
    questions = tuple(
        ReleaseQuestion(
            code=item["code"],
            dimension=item["dimension"],
            prompt=item["prompt"],
            sort_order=index,
            options=tuple(
                ReleaseQuestionOption(
                    option["code"], option["label"], option["score"], option_index
                )
                for option_index, option in enumerate(item["options"], 1)
            ),
        )
        for index, item in enumerate(payload["questions"], 1)
    )
    scenarios = tuple(
        ReleaseScenario(
            code=item["code"],
            category_code=item["category_code"],
            public_name=item["public_name"],
            description=item["description"],
            branch_codes=tuple(item["branch_codes"]),
            department_links=tuple(
                ReleaseScopedCode(link["branch_code"], link["code"], link_index)
                for link_index, link in enumerate(item["department_links"], 1)
            ),
            pain_links=tuple(
                ReleaseScopedCode(link["branch_code"], link["code"], link_index)
                for link_index, link in enumerate(item["pain_links"], 1)
            ),
            minimum_scores=dict(item["minimum_scores"]),
            integration_level=item["integration_level"],
            budget_codes=tuple(item["budget_codes"]),
            min_weeks=item["weeks"][0],
            max_weeks=item["weeks"][1],
            efficiency=_decimals(item["efficiency"]),
            loss_improvement=_decimals(item["loss_improvement"]),
            annual_support_rate=_decimals(item["annual_support_rate"]),
            risk_codes=tuple(item["risk_codes"]),
            service_code=item["service_code"],
            sort_order=index,
            fallback_only=item["fallback_only"],
        )
        for index, item in enumerate(payload["scenarios"], 1)
    )
    services = tuple(
        ReleaseService(
            code=item["code"],
            category=item["category"],
            public_name=item["public_name"],
            min_budget=Decimal(item["budget"][0]),
            max_budget=Decimal(item["budget"][1]),
            min_weeks=item["weeks"][0],
            max_weeks=item["weeks"][1],
            deliverables=tuple(item["deliverables"]),
            implementation_steps=tuple(item["implementation_steps"]),
            prerequisites=tuple(item["prerequisites"]),
            not_included=tuple(item["not_included"]),
            acceptance=tuple(item["acceptance"]),
            support_days=item["support_days"],
            support_description=item["support_description"],
            public_disclaimer=item["public_disclaimer"],
            sort_order=index,
        )
        for index, item in enumerate(payload["services"], 1)
    )
    labels = payload["public_labels"]
    release = payload["release"]
    return RuleReleaseDraft(
        id=row["id"],
        code=release["code"],
        name=release["name"],
        status="draft",
        copied_from_id=row["copied_from_id"],
        lock_version=row["lock_version"],
        pain_min_selections=release["pain_selection"]["minimum"],
        pain_max_selections=release["pain_selection"]["maximum"],
        industries=industries,
        company_sizes=_labeled(payload["company_sizes"]),
        questions=questions,
        branch_weights={
            code: dict(values) for code, values in payload["branch_weights"].items()
        },
        benchmarks=tuple(
            ReleaseBenchmark(
                item["branch_code"], item["label"], dict(item["scores"])
            )
            for item in payload["benchmarks"]
        ),
        roi_ranges={
            group: {
                code: _decimals(payload["roi_ranges"][group][code])
                for code in codes
            }
            for group, codes in ROI_OPTION_CODES.items()
        },
        scenarios=scenarios,
        services=services,
        public_labels=ReleasePublicLabels(
            risk_labels=dict(labels["risk_labels"]),
            risk_explanations=dict(labels["risk_explanations"]),
            dimensions=dict(labels["dimensions"]),
            maturities=dict(labels["maturities"]),
            integrations=dict(labels["integrations"]),
            roi_groups=dict(labels["roi_groups"]),
            roi_options={
                group: dict(values) for group, values in labels["roi_options"].items()
            },
        ),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        published_at=row["published_at"],
    )


def _labeled(items):
    return tuple(
        ReleaseLabeledCode(item["code"], item["label"], index)
        for index, item in enumerate(items, 1)
    )


def _decimals(values):
    return tuple(Decimal(value) for value in values)


def _catalog(draft, industry):
    return AssessmentCatalog(
        version_id=draft.id,
        version_code=draft.code,
        subbranch_codes=tuple(item.code for item in industry.subbranches),
        department_codes=tuple(item.code for item in industry.departments),
        pain_codes=tuple(item.code for item in industry.pain_points),
        questions=tuple(
            Question(
                code=item.code,
                dimension=item.dimension,
                prompt=item.prompt,
                options=tuple(
                    QuestionOption(option.code, option.label, option.score)
                    for option in item.options
                ),
            )
            for item in draft.questions
        ),
        branch_weights={
            code: dict(values) for code, values in draft.branch_weights.items()
        },
        reference_lines={
            item.branch_code: dict(item.scores) for item in draft.benchmarks
        },
    )


def _public_config(draft, catalog, industry):
    labeled = lambda values: [
        {"code": item.code, "label": item.label} for item in values
    ]
    benchmark = next(
        item for item in draft.benchmarks if item.branch_code == industry.code
    )
    return build_public_config(
        catalog,
        branch={"code": industry.code, "label": industry.label},
        subbranches=labeled(industry.subbranches),
        departments=labeled(industry.departments),
        pain_points=labeled(industry.pain_points),
        company_sizes=labeled(draft.company_sizes),
        pain_selection={
            "minimum": draft.pain_min_selections,
            "maximum": draft.pain_max_selections,
        },
        roi_options={
            group: list(options) for group, options in draft.roi_ranges.items()
        },
        reference_label=benchmark.label,
    )


def _scenarios(draft, branch_code):
    return tuple(
        Scenario(
            code=item.code,
            category_code=item.category_code,
            branch_codes=tuple(item.branch_codes),
            department_codes=tuple(
                link.code
                for link in item.department_links
                if link.branch_code == branch_code
            ),
            pain_codes=tuple(
                link.code for link in item.pain_links if link.branch_code == branch_code
            ),
            minimum_scores=dict(item.minimum_scores),
            integration_level=item.integration_level,
            budget_codes=tuple(item.budget_codes),
            min_weeks=item.min_weeks,
            max_weeks=item.max_weeks,
            efficiency=tuple(item.efficiency),
            loss_improvement=tuple(item.loss_improvement),
            annual_support_rate=tuple(item.annual_support_rate),
            risk_codes=tuple(item.risk_codes),
            service_code=item.service_code,
            sort_order=item.sort_order,
            fallback_only=item.fallback_only,
        )
        for item in draft.scenarios
    )


def _services(draft):
    return tuple(
        ServicePackage(
            code=item.code,
            category=item.category,
            public_name=item.public_name,
            min_budget=item.min_budget,
            max_budget=item.max_budget,
            min_weeks=item.min_weeks,
            max_weeks=item.max_weeks,
            deliverables=tuple(item.deliverables),
            implementation_steps=tuple(item.implementation_steps),
            prerequisites=tuple(item.prerequisites),
            not_included=tuple(item.not_included),
            acceptance=tuple(item.acceptance),
            support_days=item.support_days,
        )
        for item in draft.services
    )
