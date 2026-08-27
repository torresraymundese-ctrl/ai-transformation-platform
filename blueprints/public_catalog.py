"""HTTP-only public adapters for the published core content catalog."""

from decimal import Decimal

from flask import Blueprint, abort, current_app, redirect, render_template, request

import catalog_content_repository as catalog
import case_repository as cases
from content_clock import shanghai_now
from pagination import parse_pagination
import resource_repository as resources


bp = Blueprint("public_catalog", __name__)


def _canonical(path):
    return f"{current_app.config['PUBLIC_BASE_URL']}{path}"


def _content_now():
    provider = current_app.config.get("CONTENT_NOW_PROVIDER")
    return provider() if callable(provider) else shanghai_now()


def _group_decimal_whole(whole):
    """Group a non-negative decimal whole-number string without numeric coercion."""
    first_group = len(whole) % 3 or 3
    groups = [whole[:first_group]]
    groups.extend(
        whole[index:index + 3]
        for index in range(first_group, len(whole), 3)
    )
    return ",".join(groups)


def _group_exact_integer(value):
    """Group an exact integer without invoking Python's digit-limited conversion."""
    chunks = []
    while value >= 1000:
        value, remainder = divmod(value, 1000)
        chunks.append(f"{remainder:03d}")
    chunks.append(f"{value:d}")
    return ",".join(reversed(chunks))


def _format_cny_amount(value):
    """Render one validated public budget without rounding or exponent notation."""
    if type(value) not in (int, float):
        raise TypeError("budget amount must be an exact int or float")
    if type(value) is int:
        suffix = ""
        if value >= 10000 and value % 10000 == 0:
            value //= 10000
            suffix = "万"
        return f"¥{_group_exact_integer(value)}{suffix}"
    source = str(value)
    number = Decimal(source)
    suffix = ""
    if "e" not in source.lower() and number >= 10000 and number % 10000 == 0:
        number /= 10000
        suffix = "万"
    plain = format(number, "f")
    if "." in plain:
        plain = plain.rstrip("0").rstrip(".")
    whole, separator, fraction = plain.partition(".")
    grouped = _group_decimal_whole(whole)
    if separator:
        grouped = f"{grouped}.{fraction}"
    return f"¥{grouped}{suffix}"


@bp.get("/industries")
def industries():
    return render_template(
        "industries.html", industries=catalog.public_industries(shanghai_now()),
        canonical=_canonical("/industries"),
    )


@bp.get("/industries/<slug>")
def industry_detail(slug):
    industry = catalog.public_industry(slug, shanghai_now())
    if industry is None:
        abort(404)
    if industry["redirect"]:
        return redirect(f"/industries/{industry['slug']}", code=301)
    return render_template("industry_detail.html", industry=industry, canonical=_canonical(f"/industries/{industry['slug']}"))


@bp.get("/scenarios")
def scenarios():
    filters = catalog.parse_public_scenario_filters(request.args)
    page = catalog.public_scenarios(filters, parse_pagination(request.args), shanghai_now())
    return render_template(
        "scenarios.html", page=page, filters=filters,
        maturity_labels=catalog.MATURITY_LABELS, canonical=_canonical("/scenarios"),
    )


@bp.get("/scenarios/<slug>")
def scenario_detail(slug):
    scenario = catalog.public_scenario(slug, shanghai_now())
    if scenario is None:
        abort(404)
    if scenario["redirect"]:
        return redirect(f"/scenarios/{scenario['slug']}", code=301)
    return render_template(
        "scenario_detail.html",
        scenario=scenario,
        format_cny_amount=_format_cny_amount,
        canonical=_canonical(f"/scenarios/{scenario['slug']}"),
    )


@bp.get("/service-packages")
def service_packages():
    page = catalog.public_services(parse_pagination(request.args), shanghai_now())
    return render_template(
        "service_packages.html", page=page,
        canonical=_canonical("/service-packages"),
    )


@bp.get("/service-packages/<slug>")
def service_package_detail(slug):
    service = catalog.public_service(slug, shanghai_now())
    if service is None:
        abort(404)
    if service["redirect"]:
        return redirect(f"/service-packages/{service['slug']}", code=301)
    return render_template(
        "service_package_detail.html", service=service,
        canonical=_canonical(f"/service-packages/{service['slug']}"),
    )


@bp.get("/cases")
def cases_page():
    page = cases.public_cases(parse_pagination(request.args), shanghai_now())
    return render_template("cases.html", page=page, canonical=_canonical("/cases"))


@bp.get("/cases/<slug>")
def case_detail(slug):
    case = cases.public_case(slug, shanghai_now())
    if case is None:
        abort(404)
    if case.redirect:
        return redirect(f"/cases/{case.slug}", code=301)
    return render_template(
        "case_detail.html",
        case=case,
        canonical=_canonical(f"/cases/{case.slug}"),
    )


@bp.get("/resources")
def resources_page():
    filters = resources.parse_resource_filters(request.args)
    page = resources.list_published_resources(
        filters, parse_pagination(request.args), now=_content_now()
    )
    return render_template(
        "resources.html",
        page=page,
        filters=filters,
        resource_types=resources.RESOURCE_TYPE_LABELS,
        canonical=_canonical("/resources"),
    )


@bp.get("/resources/<slug>")
def resource_detail(slug):
    resource = resources.get_published_resource(slug, now=_content_now())
    if resource is None:
        abort(404)
    if resource.redirect:
        return redirect(f"/resources/{resource.slug}", code=301)
    return render_template(
        "resource_detail.html",
        resource=resource,
        canonical=_canonical(f"/resources/{resource.slug}"),
    )


@bp.get("/announcements/<slug>")
def announcement_detail(slug):
    announcement = resources.get_current_announcement(slug, now=_content_now())
    if announcement is None:
        abort(404)
    if announcement.redirect:
        return redirect(f"/announcements/{announcement.slug}", code=301)
    return render_template(
        "announcement_detail.html",
        announcement=announcement,
        canonical=_canonical(f"/announcements/{announcement.slug}"),
    )
