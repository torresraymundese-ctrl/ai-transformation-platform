"""Admin asset-management routes."""

import re

from flask import abort, redirect, render_template, request

from blueprints.admin import bp
from models import get_db
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


def validate_asset_references(db, item):
    if db.execute(
        "SELECT 1 FROM asset_codes WHERE id=?", (item["asset_code_id"],)
    ).fetchone() is None:
        raise ValidationError("asset_code_id does not exist")
    if "department" in item and db.execute(
        "SELECT 1 FROM asset_departments WHERE name=?", (item["department"],)
    ).fetchone() is None:
        raise ValidationError("department does not exist")


@bp.route("/admin/assets")
def admin_assets_dashboard():
    db = get_db()
    stats = {
        "total_codes": db.execute("SELECT COUNT(*) FROM asset_codes").fetchone()[0],
        "total_unit_a": db.execute("SELECT COUNT(*) FROM unit_a_assets").fetchone()[0],
        "total_unit_b": db.execute("SELECT COUNT(*) FROM unit_b_assets").fetchone()[0],
        "total_qty_a": db.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM unit_a_assets"
        ).fetchone()[0],
        "total_qty_b": db.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM unit_b_assets"
        ).fetchone()[0],
    }
    unit_a_by_dept = db.execute(
        "SELECT department,COUNT(*) AS cnt,SUM(quantity) AS total_qty "
        "FROM unit_a_assets GROUP BY department ORDER BY department"
    ).fetchall()
    unit_a_table_qty = db.execute(
        "SELECT COALESCE(SUM(ua.quantity),0) FROM unit_a_assets ua "
        "JOIN asset_codes ac ON ua.asset_code_id=ac.id WHERE ac.category='table'"
    ).fetchone()[0]
    unit_a_chair_qty = db.execute(
        "SELECT COALESCE(SUM(ua.quantity),0) FROM unit_a_assets ua "
        "JOIN asset_codes ac ON ua.asset_code_id=ac.id WHERE ac.category='chair'"
    ).fetchone()[0]
    unit_b_table_qty = db.execute(
        "SELECT COALESCE(SUM(ub.quantity),0) FROM unit_b_assets ub "
        "JOIN asset_codes ac ON ub.asset_code_id=ac.id WHERE ac.category='table'"
    ).fetchone()[0]
    unit_b_chair_qty = db.execute(
        "SELECT COALESCE(SUM(ub.quantity),0) FROM unit_b_assets ub "
        "JOIN asset_codes ac ON ub.asset_code_id=ac.id WHERE ac.category='chair'"
    ).fetchone()[0]
    db.close()
    return render_template(
        "admin/assets_dashboard.html",
        stats=stats,
        unit_a_by_dept=unit_a_by_dept,
        unit_a_table_qty=unit_a_table_qty,
        unit_a_chair_qty=unit_a_chair_qty,
        unit_b_table_qty=unit_b_table_qty,
        unit_b_chair_qty=unit_b_chair_qty,
    )


@bp.route("/admin/assets/codes")
def admin_asset_codes_list():
    db = get_db()
    codes = db.execute(
        "SELECT * FROM asset_codes ORDER BY category,sort_order"
    ).fetchall()
    db.close()
    return render_template("admin/asset_codes.html", codes=codes)


@bp.route("/admin/assets/code/new", methods=["GET", "POST"])
def admin_asset_code_new():
    if request.method == "POST":
        item = asset_code_payload(request.form)
        db = get_db()
        db.execute(
            "INSERT INTO asset_codes (code,name,category,sort_order) VALUES (?,?,?,?)",
            tuple(item.values()),
        )
        db.commit()
        db.close()
        return redirect("/admin/assets/codes")
    return render_template("admin/asset_code_edit.html", code=None)


@bp.route("/admin/assets/code/<int:code_id>", methods=["GET", "POST"])
def admin_asset_code_edit(code_id):
    if request.method == "POST":
        item = asset_code_payload(request.form)
        db = get_db()
        db.execute(
            "UPDATE asset_codes SET code=?,name=?,category=?,sort_order=? WHERE id=?",
            (*item.values(), code_id),
        )
        db.commit()
        db.close()
        return redirect("/admin/assets/codes")
    db = get_db()
    code = db.execute("SELECT * FROM asset_codes WHERE id=?", (code_id,)).fetchone()
    db.close()
    if code is None:
        abort(404)
    return render_template("admin/asset_code_edit.html", code=code)


@bp.route("/admin/assets/departments")
def admin_departments_list():
    db = get_db()
    departments = db.execute(
        "SELECT * FROM asset_departments ORDER BY sort_order"
    ).fetchall()
    db.close()
    return render_template("admin/departments.html", departments=departments)


@bp.route("/admin/assets/departments/new", methods=["GET", "POST"])
def admin_department_new():
    if request.method == "POST":
        item = department_payload(request.form)
        db = get_db()
        db.execute(
            "INSERT INTO asset_departments (name,sort_order) VALUES (?,?)",
            tuple(item.values()),
        )
        db.commit()
        db.close()
        return redirect("/admin/assets/departments")
    return render_template("admin/department_edit.html", department=None)


@bp.route("/admin/assets/departments/<int:dept_id>", methods=["GET", "POST"])
def admin_department_edit(dept_id):
    if request.method == "POST":
        item = department_payload(request.form)
        db = get_db()
        db.execute(
            "UPDATE asset_departments SET name=?,sort_order=? WHERE id=?",
            (*item.values(), dept_id),
        )
        db.commit()
        db.close()
        return redirect("/admin/assets/departments")
    db = get_db()
    department = db.execute(
        "SELECT * FROM asset_departments WHERE id=?", (dept_id,)
    ).fetchone()
    db.close()
    if department is None:
        abort(404)
    return render_template("admin/department_edit.html", department=department)


@bp.route("/admin/assets/unit-a")
def admin_unit_a_list():
    department = valid_text(request.args, "department", maximum=120)
    db = get_db()
    if department:
        assets = db.execute(
            "SELECT ua.*,ac.code,ac.name AS code_name,ac.category "
            "FROM unit_a_assets ua JOIN asset_codes ac ON ua.asset_code_id=ac.id "
            "WHERE ua.department=? ORDER BY ua.department,ac.category,ac.sort_order",
            (department,),
        ).fetchall()
    else:
        assets = db.execute(
            "SELECT ua.*,ac.code,ac.name AS code_name,ac.category "
            "FROM unit_a_assets ua JOIN asset_codes ac ON ua.asset_code_id=ac.id "
            "ORDER BY ua.department,ac.category,ac.sort_order"
        ).fetchall()
    departments = [
        row["department"]
        for row in db.execute(
            "SELECT DISTINCT department FROM unit_a_assets ORDER BY department"
        ).fetchall()
    ]
    db.close()
    return render_template(
        "admin/unit_a_assets.html",
        assets=assets,
        current_department=department,
        departments=departments,
    )


def unit_a_form(asset_id=None):
    if request.method == "POST":
        item = asset_payload(request.form, include_department=True)
        db = get_db()
        try:
            validate_asset_references(db, item)
            if asset_id is None:
                db.execute(
                    "INSERT INTO unit_a_assets (department,asset_code_id,quantity,remark) "
                    "VALUES (?,?,?,?)",
                    (
                        item["department"], item["asset_code_id"], item["quantity"],
                        item["remark"],
                    ),
                )
            else:
                db.execute(
                    "UPDATE unit_a_assets SET department=?,asset_code_id=?,quantity=?,"
                    "remark=? WHERE id=?",
                    (
                        item["department"], item["asset_code_id"], item["quantity"],
                        item["remark"], asset_id,
                    ),
                )
            db.commit()
        finally:
            db.close()
        return redirect("/admin/assets/unit-a")
    db = get_db()
    asset = None if asset_id is None else db.execute(
        "SELECT * FROM unit_a_assets WHERE id=?", (asset_id,)
    ).fetchone()
    codes = db.execute("SELECT * FROM asset_codes ORDER BY category,sort_order").fetchall()
    departments = db.execute(
        "SELECT * FROM asset_departments ORDER BY sort_order"
    ).fetchall()
    db.close()
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
    db = get_db()
    db.execute("DELETE FROM unit_a_assets WHERE id=?", (asset_id,))
    db.commit()
    db.close()
    return redirect("/admin/assets/unit-a")


@bp.route("/admin/assets/unit-b")
def admin_unit_b_list():
    db = get_db()
    assets = db.execute(
        "SELECT ub.*,ac.code,ac.name AS code_name,ac.category "
        "FROM unit_b_assets ub JOIN asset_codes ac ON ub.asset_code_id=ac.id "
        "ORDER BY ac.category,ac.sort_order"
    ).fetchall()
    db.close()
    return render_template("admin/unit_b_assets.html", assets=assets)


def unit_b_form(asset_id=None):
    if request.method == "POST":
        item = asset_payload(request.form, include_department=False)
        db = get_db()
        try:
            validate_asset_references(db, item)
            if asset_id is None:
                db.execute(
                    "INSERT INTO unit_b_assets (asset_code_id,quantity,remark) "
                    "VALUES (?,?,?)",
                    (item["asset_code_id"], item["quantity"], item["remark"]),
                )
            else:
                db.execute(
                    "UPDATE unit_b_assets SET asset_code_id=?,quantity=?,remark=? WHERE id=?",
                    (item["asset_code_id"], item["quantity"], item["remark"], asset_id),
                )
            db.commit()
        finally:
            db.close()
        return redirect("/admin/assets/unit-b")
    db = get_db()
    asset = None if asset_id is None else db.execute(
        "SELECT * FROM unit_b_assets WHERE id=?", (asset_id,)
    ).fetchone()
    codes = db.execute("SELECT * FROM asset_codes ORDER BY category,sort_order").fetchall()
    db.close()
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
    db = get_db()
    db.execute("DELETE FROM unit_b_assets WHERE id=?", (asset_id,))
    db.commit()
    db.close()
    return redirect("/admin/assets/unit-b")


@bp.route("/admin/assets/labels")
def admin_labels():
    unit = valid_text(request.args, "unit", maximum=1, default="A").upper() or "A"
    if unit not in {"A", "B"}:
        raise ValidationError("unit has an invalid value")
    db = get_db()
    if unit == "B":
        labels = db.execute(
            "SELECT ub.*,ac.code,ac.name AS code_name,ac.category "
            "FROM unit_b_assets ub JOIN asset_codes ac ON ub.asset_code_id=ac.id "
            "ORDER BY ac.category,ac.sort_order"
        ).fetchall()
    else:
        labels = db.execute(
            "SELECT ua.*,ac.code,ac.name AS code_name,ac.category "
            "FROM unit_a_assets ua JOIN asset_codes ac ON ua.asset_code_id=ac.id "
            "ORDER BY ua.department,ac.category,ac.sort_order"
        ).fetchall()
    db.close()
    return render_template("admin/labels.html", labels=labels, unit=unit)
