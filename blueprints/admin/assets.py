"""Admin asset-management routes."""

import re

from flask import abort, redirect, render_template, request

import asset_repository
from blueprints.admin import bp
from validation import (ValidationError, choice as valid_choice,
                        integer as valid_integer, text as valid_text)


def asset_code_payload(data):
    code = valid_text(data, "code", maximum=32, required=True).upper()
    if not re.fullmatch(r"[A-Z0-9_-]+", code):
        raise ValidationError("code contains unsupported characters")
    return {
        "code": code,
        "name": valid_text(data, "name", maximum=120, required=True),
        "category": valid_choice(data, "category", {"table", "chair"}),
        "sort_order": valid_integer(
            data, "sort_order", minimum=-10000, maximum=10000, default=0
        ),
    }


def department_payload(data):
    return {
        "name": valid_text(data, "name", maximum=120, required=True),
        "sort_order": valid_integer(
            data, "sort_order", minimum=-10000, maximum=10000, default=0
        ),
    }


def asset_payload(data, *, include_department):
    item = {
        "asset_code_id": valid_integer(
            data, "asset_code_id", minimum=1, maximum=2147483647
        ),
        "quantity": valid_integer(
            data, "quantity", minimum=1, maximum=100000, default=1
        ),
        "remark": valid_text(data, "remark", maximum=500),
    }
    if include_department:
        item["department"] = valid_text(
            data, "department", maximum=120, required=True
        )
    return item


@bp.route("/admin/assets")
def admin_assets_dashboard():
    return render_template(
        "admin/assets_dashboard.html", **asset_repository.dashboard_data()
    )


@bp.route("/admin/assets/codes")
def admin_asset_codes_list():
    return render_template("admin/asset_codes.html", codes=asset_repository.list_codes())


@bp.route("/admin/assets/code/new", methods=["GET", "POST"])
def admin_asset_code_new():
    if request.method == "POST":
        item = asset_code_payload(request.form)
        asset_repository.create_code(item)
        return redirect("/admin/assets/codes")
    return render_template("admin/asset_code_edit.html", code=None)


@bp.route("/admin/assets/code/<int:code_id>", methods=["GET", "POST"])
def admin_asset_code_edit(code_id):
    if request.method == "POST":
        item = asset_code_payload(request.form)
        asset_repository.update_code(code_id, item)
        return redirect("/admin/assets/codes")
    code = asset_repository.get_code(code_id)
    if code is None:
        abort(404)
    return render_template("admin/asset_code_edit.html", code=code)


@bp.route("/admin/assets/departments")
def admin_departments_list():
    return render_template(
        "admin/departments.html", departments=asset_repository.list_departments()
    )


@bp.route("/admin/assets/departments/new", methods=["GET", "POST"])
def admin_department_new():
    if request.method == "POST":
        item = department_payload(request.form)
        asset_repository.create_department(item)
        return redirect("/admin/assets/departments")
    return render_template("admin/department_edit.html", department=None)


@bp.route("/admin/assets/departments/<int:dept_id>", methods=["GET", "POST"])
def admin_department_edit(dept_id):
    if request.method == "POST":
        item = department_payload(request.form)
        asset_repository.update_department(dept_id, item)
        return redirect("/admin/assets/departments")
    department = asset_repository.get_department(dept_id)
    if department is None:
        abort(404)
    return render_template("admin/department_edit.html", department=department)


@bp.route("/admin/assets/unit-a")
def admin_unit_a_list():
    department = valid_text(request.args, "department", maximum=120)
    assets, departments = asset_repository.list_unit_a(department)
    return render_template(
        "admin/unit_a_assets.html",
        assets=assets,
        current_department=department,
        departments=departments,
    )


def unit_a_form(asset_id=None):
    if request.method == "POST":
        item = asset_payload(request.form, include_department=True)
        asset_repository.save_unit_a(asset_id, item)
        return redirect("/admin/assets/unit-a")
    asset, codes, departments = asset_repository.unit_a_form_data(asset_id)
    if asset_id is not None and asset is None:
        abort(404)
    return render_template(
        "admin/unit_a_edit.html", asset=asset, codes=codes, departments=departments
    )


@bp.route("/admin/assets/unit-a/new", methods=["GET", "POST"])
def admin_unit_a_new():
    return unit_a_form()


@bp.route("/admin/assets/unit-a/<int:asset_id>", methods=["GET", "POST"])
def admin_unit_a_edit(asset_id):
    return unit_a_form(asset_id)


@bp.route("/admin/assets/unit-a/delete/<int:asset_id>", methods=["POST"])
def admin_unit_a_delete(asset_id):
    asset_repository.delete_unit_a(asset_id)
    return redirect("/admin/assets/unit-a")


@bp.route("/admin/assets/unit-b")
def admin_unit_b_list():
    return render_template(
        "admin/unit_b_assets.html", assets=asset_repository.list_unit_b()
    )


def unit_b_form(asset_id=None):
    if request.method == "POST":
        item = asset_payload(request.form, include_department=False)
        asset_repository.save_unit_b(asset_id, item)
        return redirect("/admin/assets/unit-b")
    asset, codes = asset_repository.unit_b_form_data(asset_id)
    if asset_id is not None and asset is None:
        abort(404)
    return render_template("admin/unit_b_edit.html", asset=asset, codes=codes)


@bp.route("/admin/assets/unit-b/new", methods=["GET", "POST"])
def admin_unit_b_new():
    return unit_b_form()


@bp.route("/admin/assets/unit-b/<int:asset_id>", methods=["GET", "POST"])
def admin_unit_b_edit(asset_id):
    return unit_b_form(asset_id)


@bp.route("/admin/assets/unit-b/delete/<int:asset_id>", methods=["POST"])
def admin_unit_b_delete(asset_id):
    asset_repository.delete_unit_b(asset_id)
    return redirect("/admin/assets/unit-b")


@bp.route("/admin/assets/labels")
def admin_labels():
    unit = valid_text(request.args, "unit", maximum=1, default="A").upper() or "A"
    if unit not in {"A", "B"}:
        raise ValidationError("unit has an invalid value")
    return render_template(
        "admin/labels.html", labels=asset_repository.list_labels(unit), unit=unit
    )
