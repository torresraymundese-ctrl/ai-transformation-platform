"""Data access and transactions for the asset-management module."""

from models import get_db
from repository import execute_write, run_transaction
from validation import ValidationError


def dashboard_data():
    db = get_db()
    try:
        stats = {
            "total_codes": db.execute(
                "SELECT COUNT(*) FROM asset_codes"
            ).fetchone()[0],
            "total_unit_a": db.execute(
                "SELECT COUNT(*) FROM unit_a_assets"
            ).fetchone()[0],
            "total_unit_b": db.execute(
                "SELECT COUNT(*) FROM unit_b_assets"
            ).fetchone()[0],
            "total_qty_a": db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM unit_a_assets"
            ).fetchone()[0],
            "total_qty_b": db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM unit_b_assets"
            ).fetchone()[0],
        }
        return {
            "stats": stats,
            "unit_a_by_dept": db.execute(
                "SELECT department,COUNT(*) AS cnt,SUM(quantity) AS total_qty "
                "FROM unit_a_assets GROUP BY department ORDER BY department"
            ).fetchall(),
            "unit_a_table_qty": _category_quantity(db, "unit_a_assets", "ua", "table"),
            "unit_a_chair_qty": _category_quantity(db, "unit_a_assets", "ua", "chair"),
            "unit_b_table_qty": _category_quantity(db, "unit_b_assets", "ub", "table"),
            "unit_b_chair_qty": _category_quantity(db, "unit_b_assets", "ub", "chair"),
        }
    finally:
        db.close()


def _category_quantity(db, table, alias, category):
    return db.execute(
        f"SELECT COALESCE(SUM({alias}.quantity),0) FROM {table} {alias} "
        f"JOIN asset_codes ac ON {alias}.asset_code_id=ac.id WHERE ac.category=?",
        (category,),
    ).fetchone()[0]


def list_codes():
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM asset_codes ORDER BY category,sort_order"
        ).fetchall()
    finally:
        db.close()


def get_code(code_id):
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM asset_codes WHERE id=?", (code_id,)
        ).fetchone()
    finally:
        db.close()


def create_code(item):
    return execute_write(
        "INSERT INTO asset_codes (code,name,category,sort_order) VALUES (?,?,?,?)",
        tuple(item.values()),
    )


def update_code(code_id, item):
    execute_write(
        "UPDATE asset_codes SET code=?,name=?,category=?,sort_order=? WHERE id=?",
        (*item.values(), code_id),
    )


def list_departments():
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM asset_departments ORDER BY sort_order"
        ).fetchall()
    finally:
        db.close()


def get_department(department_id):
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM asset_departments WHERE id=?", (department_id,)
        ).fetchone()
    finally:
        db.close()


def create_department(item):
    return execute_write(
        "INSERT INTO asset_departments (name,sort_order) VALUES (?,?)",
        tuple(item.values()),
    )


def update_department(department_id, item):
    execute_write(
        "UPDATE asset_departments SET name=?,sort_order=? WHERE id=?",
        (*item.values(), department_id),
    )


def list_unit_a(department):
    db = get_db()
    try:
        query = (
            "SELECT ua.*,ac.code,ac.name AS code_name,ac.category "
            "FROM unit_a_assets ua JOIN asset_codes ac ON ua.asset_code_id=ac.id "
        )
        params = ()
        if department:
            query += "WHERE ua.department=? "
            params = (department,)
        query += "ORDER BY ua.department,ac.category,ac.sort_order"
        assets = db.execute(query, params).fetchall()
        departments = [
            row["department"]
            for row in db.execute(
                "SELECT DISTINCT department FROM unit_a_assets ORDER BY department"
            ).fetchall()
        ]
        return assets, departments
    finally:
        db.close()


def unit_a_form_data(asset_id):
    db = get_db()
    try:
        asset = None
        if asset_id is not None:
            asset = db.execute(
                "SELECT * FROM unit_a_assets WHERE id=?", (asset_id,)
            ).fetchone()
        return (
            asset,
            db.execute(
                "SELECT * FROM asset_codes ORDER BY category,sort_order"
            ).fetchall(),
            db.execute(
                "SELECT * FROM asset_departments ORDER BY sort_order"
            ).fetchall(),
        )
    finally:
        db.close()


def save_unit_a(asset_id, item):
    def save(db):
        _validate_references(db, item)
        if asset_id is None:
            return db.execute(
                "INSERT INTO unit_a_assets "
                "(department,asset_code_id,quantity,remark) VALUES (?,?,?,?)",
                (
                    item["department"], item["asset_code_id"], item["quantity"],
                    item["remark"],
                ),
            )
        return db.execute(
            "UPDATE unit_a_assets SET department=?,asset_code_id=?,quantity=?,"
            "remark=? WHERE id=?",
            (
                item["department"], item["asset_code_id"], item["quantity"],
                item["remark"], asset_id,
            ),
        )

    return run_transaction(save)


def delete_unit_a(asset_id):
    execute_write("DELETE FROM unit_a_assets WHERE id=?", (asset_id,))


def list_unit_b():
    db = get_db()
    try:
        return db.execute(
            "SELECT ub.*,ac.code,ac.name AS code_name,ac.category "
            "FROM unit_b_assets ub JOIN asset_codes ac ON ub.asset_code_id=ac.id "
            "ORDER BY ac.category,ac.sort_order"
        ).fetchall()
    finally:
        db.close()


def unit_b_form_data(asset_id):
    db = get_db()
    try:
        asset = None
        if asset_id is not None:
            asset = db.execute(
                "SELECT * FROM unit_b_assets WHERE id=?", (asset_id,)
            ).fetchone()
        codes = db.execute(
            "SELECT * FROM asset_codes ORDER BY category,sort_order"
        ).fetchall()
        return asset, codes
    finally:
        db.close()


def save_unit_b(asset_id, item):
    def save(db):
        _validate_references(db, item)
        if asset_id is None:
            return db.execute(
                "INSERT INTO unit_b_assets (asset_code_id,quantity,remark) "
                "VALUES (?,?,?)",
                (item["asset_code_id"], item["quantity"], item["remark"]),
            )
        return db.execute(
            "UPDATE unit_b_assets SET asset_code_id=?,quantity=?,remark=? WHERE id=?",
            (item["asset_code_id"], item["quantity"], item["remark"], asset_id),
        )

    return run_transaction(save)


def delete_unit_b(asset_id):
    execute_write("DELETE FROM unit_b_assets WHERE id=?", (asset_id,))


def list_labels(unit):
    db = get_db()
    try:
        if unit == "B":
            return db.execute(
                "SELECT ub.*,ac.code,ac.name AS code_name,ac.category "
                "FROM unit_b_assets ub JOIN asset_codes ac ON ub.asset_code_id=ac.id "
                "ORDER BY ac.category,ac.sort_order"
            ).fetchall()
        return db.execute(
            "SELECT ua.*,ac.code,ac.name AS code_name,ac.category "
            "FROM unit_a_assets ua JOIN asset_codes ac ON ua.asset_code_id=ac.id "
            "ORDER BY ua.department,ac.category,ac.sort_order"
        ).fetchall()
    finally:
        db.close()


def _validate_references(db, item):
    if db.execute(
        "SELECT 1 FROM asset_codes WHERE id=?", (item["asset_code_id"],)
    ).fetchone() is None:
        raise ValidationError("asset_code_id does not exist")
    if "department" in item and db.execute(
        "SELECT 1 FROM asset_departments WHERE name=?", (item["department"],)
    ).fetchone() is None:
        raise ValidationError("department does not exist")
