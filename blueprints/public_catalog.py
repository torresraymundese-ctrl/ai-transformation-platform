"""HTTP-only public adapters for the published core content catalog."""

from flask import Blueprint, abort, current_app, redirect, render_template, request

import catalog_content_repository as catalog
import case_repository as cases
from content_clock import shanghai_now
from pagination import parse_pagination


bp = Blueprint("public_catalog", __name__)


def _canonical(path):
    return f"{current_app.config['PUBLIC_BASE_URL']}{path}"


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
    return render_template("scenario_detail.html", scenario=scenario, canonical=_canonical(f"/scenarios/{scenario['slug']}"))


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
