"""HTTP-only public adapters for published industry and scenario content."""

from flask import Blueprint, abort, current_app, redirect, render_template, request

import catalog_content_repository as catalog
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
