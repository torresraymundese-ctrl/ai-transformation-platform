"""Authenticated rule-release draft list, edit, copy, and preview routes."""

from dataclasses import replace
from decimal import Decimal, InvalidOperation
import re

from flask import abort, make_response, redirect, render_template, request, session, url_for

from assessment.contracts import ReleaseScopedCode, RuleReleaseFilters
from assessment.scoring import DIMENSION_ORDER
from blueprints.admin import bp
from content_clock import shanghai_now
from pagination import parse_pagination
from repository import DataConflictError
from rule_release_repository import (
    copy_active_release,
    load_release_draft,
    query_rule_releases,
    save_release_draft,
)
from rule_release_service import PreviewRequest, preview_release
from rule_release_validation import compile_release_snapshot, validate_release_draft


_STATUSES = frozenset({"draft", "published", "archived"})
_INTEGRATION_LEVELS = ("low", "medium", "high")
_DECIMAL_INPUT = re.compile(
    r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE]([+-]?[0-9]+))?$"
)
_MAX_DECIMAL_INPUT_LENGTH = 512
_MAX_DECIMAL_DIGITS = 256
_MAX_DECIMAL_FIXED_LENGTH = 2048


class RuleFormError(ValueError):
    pass


def _no_store(response):
    response = make_response(response)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _list_status(values):
    supplied = values.getlist("status")
    return supplied[0] if len(supplied) == 1 and supplied[0] in _STATUSES else None


def _one(data, name):
    values = data.getlist(name)
    if len(values) != 1:
        raise RuleFormError("invalid form")
    return values[0]


def _integer(data, name, *, minimum=0, maximum=2_147_483_647):
    raw = _one(data, name)
    if (
        type(raw) is not str
        or len(raw) > 10
        or not raw.isascii()
        or not raw.isdecimal()
    ):
        raise RuleFormError("invalid form")
    try:
        value = int(raw, 10)
    except (ValueError, OverflowError):
        raise RuleFormError("invalid form") from None
    if not minimum <= value <= maximum:
        raise RuleFormError("invalid form")
    return value


def _decimal(data, name):
    raw = _one(data, name)
    if type(raw) is not str or len(raw) > _MAX_DECIMAL_INPUT_LENGTH:
        raise RuleFormError("invalid form")
    match = _DECIMAL_INPUT.fullmatch(raw)
    if match is None or sum(character.isdecimal() for character in raw) > _MAX_DECIMAL_DIGITS:
        raise RuleFormError("invalid form")
    exponent_text = match.group(1)
    if exponent_text is not None and len(exponent_text.lstrip("+-")) > 5:
        raise RuleFormError("invalid form")
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError):
        raise RuleFormError("invalid form") from None
    if not value.is_finite() or _decimal_fixed_length(value) > _MAX_DECIMAL_FIXED_LENGTH:
        raise RuleFormError("invalid form")
    return value


def _decimal_fixed_length(value):
    _sign, digits, exponent = value.as_tuple()
    digit_count = max(len(digits), 1)
    if exponent >= 0:
        return digit_count + exponent
    decimal_position = digit_count + exponent
    if decimal_position <= 0:
        return 2 - decimal_position + digit_count
    return digit_count + 1


def _actor():
    return session.get("admin_username", "admin")


def _now():
    return shanghai_now()


def _load_or_404(release_id):
    try:
        return load_release_draft(release_id)
    except (LookupError, ValueError):
        abort(404)


def _edit_context(draft, errors=()):
    validation_errors = tuple(errors) or validate_release_draft(draft)
    digest = None
    if not validation_errors:
        try:
            digest = compile_release_snapshot(draft).sha256
        except ValueError:
            validation_errors = ("规则草稿未通过验证",)
    branch_choices = tuple(item.code for item in draft.industries)
    department_choices = tuple(
        (f"{industry.code}:{item.code}", f"{industry.label} / {item.label}")
        for industry in draft.industries
        for item in industry.departments
    )
    pain_choices = tuple(
        (f"{industry.code}:{item.code}", f"{industry.label} / {item.label}")
        for industry in draft.industries
        for item in industry.pain_points
    )
    return {
        "draft": draft,
        "validation_errors": validation_errors,
        "compiled_digest": digest,
        "dimension_order": DIMENSION_ORDER,
        "integration_levels": _INTEGRATION_LEVELS,
        "branch_choices": branch_choices,
        "department_choices": department_choices,
        "pain_choices": pain_choices,
        "budget_choices": tuple(draft.roi_ranges["budget"]),
        "service_choices": tuple(item.code for item in draft.services),
        "risk_choices": tuple(draft.public_labels.risk_explanations),
        "scenario_categories": tuple(
            dict.fromkeys(item.category_code for item in draft.scenarios)
        ),
        "service_categories": tuple(
            dict.fromkeys(item.category for item in draft.services)
        ),
    }


def _render_edit(draft, *, errors=(), status=200):
    return _no_store(
        make_response(
            render_template("admin/rule_release_edit.html", **_edit_context(draft, errors)),
            status,
        )
    )


@bp.get("/admin/rules")
def admin_rule_releases():
    status = _list_status(request.args)
    page = query_rule_releases(
        RuleReleaseFilters(status=status), parse_pagination(request.args)
    )
    return _no_store(
        render_template(
            "admin/rule_releases.html",
            page=page,
            selected_status=status,
            statuses=("draft", "published", "archived"),
        )
    )


@bp.post("/admin/rules/copy")
def admin_rule_copy():
    expected = {"csrf_token", "code", "name"}
    if set(request.form) != expected:
        return _no_store(("提交内容无效", 400))
    try:
        code = _one(request.form, "code")
        name = _one(request.form, "name")
        release_id = copy_active_release(code, name, _actor(), _now())
    except RuleFormError:
        return _no_store(("提交内容无效", 400))
    except (DataConflictError, ValueError):
        return _no_store(("无法复制规则版本", 409))
    return _no_store(
        redirect(url_for("admin.admin_rule_edit", release_id=release_id), code=303)
    )


@bp.route("/admin/rules/<int:release_id>", methods=("GET", "POST"))
def admin_rule_edit(release_id):
    draft = _load_or_404(release_id)
    if request.method == "GET":
        return _render_edit(draft)
    if draft.status != "draft":
        return _render_edit(draft, errors=("当前版本不可编辑",), status=409)
    try:
        submitted = _parse_edit_form(request.form, draft)
    except RuleFormError:
        return _render_edit(draft, errors=("提交内容无效",), status=400)
    errors = validate_release_draft(submitted)
    if errors:
        return _render_edit(submitted, errors=("规则草稿未通过验证",), status=400)
    try:
        save_release_draft(
            release_id, submitted.lock_version, submitted, _now()
        )
    except DataConflictError:
        return _render_edit(submitted, errors=("更新冲突",), status=409)
    except ValueError:
        return _render_edit(submitted, errors=("规则草稿未通过验证",), status=400)
    return _no_store(
        redirect(url_for("admin.admin_rule_edit", release_id=release_id), code=303)
    )


@bp.post("/admin/rules/<int:release_id>/preview")
def admin_rule_preview(release_id):
    draft = _load_or_404(release_id)
    try:
        preview_request = _parse_preview_form(request.form, draft)
        preview = preview_release(release_id, preview_request)
    except (RuleFormError, ValueError):
        return _render_edit(draft, errors=("预览输入无效",), status=400)
    return _no_store(
        render_template(
            "admin/rule_release_preview.html",
            draft=draft,
            preview=preview,
        )
    )


def _parse_edit_form(data, draft):
    single = {
        "csrf_token",
        "expected_lock_version",
        "name",
        "pain_min_selections",
        "pain_max_selections",
    }
    multi = set()
    for industry in draft.industries:
        prefix = f"industry__{industry.code}__"
        single.update({prefix + "label", prefix + "position"})
        for collection, family in (
            (industry.subbranches, "subbranch"),
            (industry.departments, "department"),
            (industry.pain_points, "pain"),
        ):
            for item in collection:
                item_prefix = prefix + f"{family}__{item.code}__"
                single.update({item_prefix + "label", item_prefix + "position"})
    for item in draft.company_sizes:
        prefix = f"company_size__{item.code}__"
        single.update({prefix + "label", prefix + "position"})
    for family in (
        "risk_labels",
        "risk_explanations",
        "dimensions",
        "maturities",
        "integrations",
        "roi_groups",
    ):
        single.update(
            f"public__{family}__{code}"
            for code in getattr(draft.public_labels, family)
        )
    for group, labels in draft.public_labels.roi_options.items():
        single.update(
            f"public__roi_options__{group}__{code}" for code in labels
        )
    for question in draft.questions:
        prefix = f"question__{question.code}__"
        single.update({prefix + "dimension", prefix + "prompt", prefix + "position"})
        for option in question.options:
            option_prefix = prefix + f"option__{option.code}__"
            single.update(
                {option_prefix + "label", option_prefix + "score", option_prefix + "position"}
            )
    for branch_code in draft.branch_weights:
        single.update(
            f"weight__{branch_code}__{dimension}" for dimension in DIMENSION_ORDER
        )
    for benchmark in draft.benchmarks:
        single.add(f"benchmark__{benchmark.branch_code}__label")
        single.update(
            f"benchmark__{benchmark.branch_code}__{dimension}"
            for dimension in DIMENSION_ORDER
        )
    for group, options in draft.roi_ranges.items():
        single.update(
            f"roi__{group}__{code}__{band}"
            for code in options
            for band in ("low", "mid", "high")
        )
    for scenario in draft.scenarios:
        prefix = f"scenario__{scenario.code}__"
        single.update(
            {
                prefix + "integration_level",
                prefix + "service_code",
                prefix + "category_code",
                prefix + "public_name",
                prefix + "description",
                prefix + "min_weeks",
                prefix + "max_weeks",
                prefix + "position",
                *(prefix + "minimum__" + dimension for dimension in DIMENSION_ORDER),
                *(
                    prefix + f"{name}__{index}"
                    for name in ("efficiency", "loss_improvement", "annual_support_rate")
                    for index in range(3)
                ),
            }
        )
        multi.update(
            prefix + name
            for name in ("branches", "departments", "pains", "budgets", "risks")
        )
    service_fields = (
        "category",
        "public_name",
        "min_budget",
        "max_budget",
        "min_weeks",
        "max_weeks",
        "deliverables",
        "implementation_steps",
        "prerequisites",
        "not_included",
        "acceptance",
        "support_days",
        "support_description",
        "public_disclaimer",
        "position",
    )
    for service in draft.services:
        single.update(f"service__{service.code}__{name}" for name in service_fields)
    if (
        not single <= set(data)
        or set(data) - (single | multi)
        or any(len(data.getlist(name)) != 1 for name in single)
    ):
        raise RuleFormError("invalid form")
    expected_lock = _integer(data, "expected_lock_version", minimum=1)
    industries = _labeled_items(data, "industry", draft.industries)
    industries = tuple(
        replace(
            industry,
            subbranches=_labeled_items(
                data,
                f"industry__{industry.code}__subbranch",
                industry.subbranches,
            ),
            departments=_labeled_items(
                data,
                f"industry__{industry.code}__department",
                industry.departments,
            ),
            pain_points=_labeled_items(
                data,
                f"industry__{industry.code}__pain",
                industry.pain_points,
            ),
        )
        for industry in industries
    )
    company_sizes = _labeled_items(data, "company_size", draft.company_sizes)
    question_positions = _positions(data, "question", draft.questions)
    scenario_positions = _positions(data, "scenario", draft.scenarios)
    service_positions = _positions(data, "service", draft.services)
    industry_codes = {item.code for item in draft.industries}
    departments = {
        f"{industry.code}:{item.code}"
        for industry in draft.industries
        for item in industry.departments
    }
    pains = {
        f"{industry.code}:{item.code}"
        for industry in draft.industries
        for item in industry.pain_points
    }
    budgets = set(draft.roi_ranges["budget"])
    risks = set(draft.public_labels.risk_explanations)
    services = {item.code for item in draft.services}
    scenario_categories = {item.category_code for item in draft.scenarios}
    scenarios = []
    for scenario in draft.scenarios:
        prefix = f"scenario__{scenario.code}__"
        branch_values = _choices(data, prefix + "branches", industry_codes)
        department_values = _choices(data, prefix + "departments", departments)
        pain_values = _choices(data, prefix + "pains", pains, allow_empty=True)
        integration = _one(data, prefix + "integration_level")
        service_code = _one(data, prefix + "service_code")
        category_code = _one(data, prefix + "category_code")
        if (
            integration not in _INTEGRATION_LEVELS
            or service_code not in services
            or category_code not in scenario_categories
        ):
            raise RuleFormError("invalid form")
        scenarios.append(
            replace(
                scenario,
                branch_codes=branch_values,
                department_links=_scoped_codes(department_values),
                pain_links=_scoped_codes(pain_values),
                category_code=category_code,
                public_name=_one(data, prefix + "public_name"),
                description=_one(data, prefix + "description"),
                minimum_scores={
                    dimension: _integer(data, prefix + "minimum__" + dimension, maximum=100)
                    for dimension in DIMENSION_ORDER
                },
                integration_level=integration,
                budget_codes=_choices(data, prefix + "budgets", budgets),
                min_weeks=_integer(data, prefix + "min_weeks", minimum=1),
                max_weeks=_integer(data, prefix + "max_weeks", minimum=1),
                efficiency=_triple(data, prefix, "efficiency"),
                loss_improvement=_triple(data, prefix, "loss_improvement"),
                annual_support_rate=_triple(data, prefix, "annual_support_rate"),
                risk_codes=_choices(data, prefix + "risks", risks),
                service_code=service_code,
                sort_order=scenario_positions[scenario.code],
            )
        )
    questions = tuple(sorted((
        replace(
            question,
            dimension=_allowed(
                data, f"question__{question.code}__dimension", set(DIMENSION_ORDER)
            ),
            prompt=_one(data, f"question__{question.code}__prompt"),
            sort_order=question_positions[question.code],
            options=tuple(sorted((
                replace(
                    option,
                    label=_one(
                        data,
                        f"question__{question.code}__option__{option.code}__label",
                    ),
                    score=_integer(
                        data,
                        f"question__{question.code}__option__{option.code}__score",
                        maximum=3,
                    ),
                    sort_order=_positions(
                        data,
                        f"question__{question.code}__option",
                        question.options,
                    )[option.code],
                )
                for option in question.options
            ), key=lambda item: item.sort_order)),
        )
        for question in draft.questions
    ), key=lambda item: item.sort_order))
    branch_weights = {
        branch_code: {
            dimension: _integer(
                data, f"weight__{branch_code}__{dimension}", maximum=100
            )
            for dimension in DIMENSION_ORDER
        }
        for branch_code in draft.branch_weights
    }
    benchmarks = tuple(
        replace(
            benchmark,
            label=_one(data, f"benchmark__{benchmark.branch_code}__label"),
            scores={
                dimension: _integer(
                    data,
                    f"benchmark__{benchmark.branch_code}__{dimension}",
                    maximum=100,
                )
                for dimension in DIMENSION_ORDER
            },
        )
        for benchmark in draft.benchmarks
    )
    roi_ranges = {
        group: {
            code: tuple(
                _decimal(data, f"roi__{group}__{code}__{band}")
                for band in ("low", "mid", "high")
            )
            for code in options
        }
        for group, options in draft.roi_ranges.items()
    }
    service_categories = {item.category for item in draft.services}
    changed_services = tuple(
        replace(
            service,
            category=_allowed(
                data, f"service__{service.code}__category", service_categories
            ),
            public_name=_one(data, f"service__{service.code}__public_name"),
            min_budget=_decimal(data, f"service__{service.code}__min_budget"),
            max_budget=_decimal(data, f"service__{service.code}__max_budget"),
            min_weeks=_integer(
                data, f"service__{service.code}__min_weeks", minimum=1
            ),
            max_weeks=_integer(
                data, f"service__{service.code}__max_weeks", minimum=1
            ),
            deliverables=_lines(data, f"service__{service.code}__deliverables"),
            implementation_steps=_lines(
                data, f"service__{service.code}__implementation_steps"
            ),
            prerequisites=_lines(data, f"service__{service.code}__prerequisites"),
            not_included=_lines(data, f"service__{service.code}__not_included"),
            acceptance=_lines(data, f"service__{service.code}__acceptance"),
            support_days=_integer(data, f"service__{service.code}__support_days"),
            support_description=_one(
                data, f"service__{service.code}__support_description"
            ),
            public_disclaimer=_one(
                data, f"service__{service.code}__public_disclaimer"
            ),
            sort_order=service_positions[service.code],
        )
        for service in draft.services
    )
    simple_labels = {}
    for family in (
        "risk_labels",
        "risk_explanations",
        "dimensions",
        "maturities",
        "integrations",
        "roi_groups",
    ):
        simple_labels[family] = {
            code: _one(data, f"public__{family}__{code}")
            for code in getattr(draft.public_labels, family)
        }
    labels = replace(
        draft.public_labels,
        **simple_labels,
        roi_options={
            group: {
                code: _one(data, f"public__roi_options__{group}__{code}")
                for code in values
            }
            for group, values in draft.public_labels.roi_options.items()
        },
    )
    return replace(
        draft,
        name=_one(data, "name"),
        lock_version=expected_lock,
        pain_min_selections=_integer(data, "pain_min_selections", minimum=1, maximum=3),
        pain_max_selections=_integer(data, "pain_max_selections", minimum=1, maximum=3),
        industries=industries,
        company_sizes=company_sizes,
        questions=questions,
        branch_weights=branch_weights,
        benchmarks=benchmarks,
        roi_ranges=roi_ranges,
        scenarios=tuple(sorted(scenarios, key=lambda item: item.sort_order)),
        services=tuple(sorted(changed_services, key=lambda item: item.sort_order)),
        public_labels=labels,
    )


def _positions(data, family, items):
    maximum = len(items)
    positions = {
        item.code: _integer(
            data, f"{family}__{item.code}__position", minimum=1, maximum=maximum
        )
        for item in items
    }
    if set(positions.values()) != set(range(1, maximum + 1)):
        raise RuleFormError("invalid form")
    return positions


def _labeled_items(data, family, items):
    positions = _positions(data, family, items)
    return tuple(
        sorted(
            (
                replace(
                    item,
                    label=_one(data, f"{family}__{item.code}__label"),
                    sort_order=positions[item.code],
                )
                for item in items
            ),
            key=lambda item: item.sort_order,
        )
    )


def _allowed(data, name, choices):
    value = _one(data, name)
    if value not in choices:
        raise RuleFormError("invalid form")
    return value


def _lines(data, name):
    value = _one(data, name)
    if len(value) > 20_000:
        raise RuleFormError("invalid form")
    return tuple(value.splitlines())


def _choices(data, name, allowed, *, allow_empty=False):
    values = tuple(data.getlist(name))
    if (
        (not values and not allow_empty)
        or len(values) != len(set(values))
        or not set(values) <= set(allowed)
    ):
        raise RuleFormError("invalid form")
    return values


def _triple(data, prefix, name):
    return tuple(_decimal(data, prefix + f"{name}__{index}") for index in range(3))


def _scoped_codes(values):
    result = []
    for index, value in enumerate(values, 1):
        branch_code, code = value.split(":", 1)
        result.append(ReleaseScopedCode(branch_code, code, index))
    return tuple(result)


def _parse_preview_form(data, draft):
    single = {
        "csrf_token",
        "branch_code",
        "subbranch_code",
        "department_code",
        "company_size_code",
        *(f"answer__{question.code}" for question in draft.questions),
        *(f"roi__{group}" for group in draft.roi_ranges),
    }
    multi = {"pain_codes"}
    if set(data) != single | multi or any(len(data.getlist(name)) != 1 for name in single):
        raise RuleFormError("invalid form")
    pain_codes = tuple(data.getlist("pain_codes"))
    if not pain_codes or len(pain_codes) != len(set(pain_codes)):
        raise RuleFormError("invalid form")
    return PreviewRequest(
        branch_code=_one(data, "branch_code"),
        subbranch_code=_one(data, "subbranch_code"),
        department_code=_one(data, "department_code"),
        company_size_code=_one(data, "company_size_code"),
        pain_codes=pain_codes,
        answers={
            question.code: _one(data, f"answer__{question.code}")
            for question in draft.questions
        },
        roi_choices={
            group: _one(data, f"roi__{group}") for group in draft.roi_ranges
        },
    )
