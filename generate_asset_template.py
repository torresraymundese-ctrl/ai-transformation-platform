#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成家具资产录入 Excel 模板 — 含编码表、录入表、标签打印表"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from models import get_db, init_db
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

OUTPUT = os.path.join(os.path.dirname(__file__), "资产录入模板.xlsx")

# ── 样式常量 ──────────────────────────────────────────
BLUE_FILL  = PatternFill(start_color="0071E3", end_color="0071E3", fill_type="solid")
RED_FILL   = PatternFill(start_color="FF3B30", end_color="FF3B30", fill_type="solid")
WHITE_FILL = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
GRAY_FILL  = PatternFill(start_color="F2F2F7", end_color="F2F2F7", fill_type="solid")
WHITE_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
BLACK_FONT = Font(name="微软雅黑", size=10, color="000000")
BOLD_FONT  = Font(name="微软雅黑", size=10, bold=True, color="000000")
TITLE_FONT = Font(name="微软雅黑", size=14, bold=True, color="0071E3")
THIN_BORDER = Border(
    left=Side(style='thin', color='999999'),
    right=Side(style='thin', color='999999'),
    top=Side(style='thin', color='999999'),
    bottom=Side(style='thin', color='999999'))
CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
LEFT   = Alignment(horizontal='left', vertical='center', wrap_text=True)

def apply_style(ws, row, cols, font=None, fill=None, alignment=None, border=None):
    for col in range(1, cols + 1):
        cell = ws.cell(row=row, column=col)
        if font: cell.font = font
        if fill: cell.fill = fill
        if alignment: cell.alignment = alignment
        if border: cell.border = border

def apply_range_style(ws, min_row, max_row, min_col, max_col, border=THIN_BORDER):
    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = border
            cell.alignment = CENTER

# ── Sheet 1: 资产编码表 ──────────────────────────────
def build_code_sheet(wb, tables, chairs):
    ws = wb.active
    ws.title = "资产编码表"
    ws.sheet_properties.showGridLines = False

    ws.merge_cells('A1:C1')
    ws.cell(row=1, column=1, value="资产编码参考表").font = TITLE_FONT
    ws.cell(row=1, column=1).alignment = CENTER

    row = 3
    for title, codes, color in [("桌子编码", tables, "0071E3"), ("椅子编码", chairs, "BF4800")]:
        fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        ws.cell(row=row, column=1, value=title).font = Font(name="微软雅黑", size=12, bold=True, color="FFFFFF")
        ws.cell(row=row, column=1).fill = fill
        ws.cell(row=row, column=1).alignment = CENTER
        row += 1
        for hdr, c in [("类别", 1), ("编码", 2), ("名称", 3)]:
            cell = ws.cell(row=row, column=c, value=hdr)
            cell.font = WHITE_FONT; cell.fill = fill; cell.alignment = CENTER; cell.border = THIN_BORDER
        row += 1
        for code in codes:
            ws.cell(row=row, column=1, value="桌子" if code["category"] == "table" else "椅子").font = BLACK_FONT
            ws.cell(row=row, column=2, value=code["code"]).font = BOLD_FONT
            ws.cell(row=row, column=3, value=code["name"]).font = BLACK_FONT
            apply_style(ws, row, 3, border=THIN_BORDER)
            row += 1
        row += 1

    ws.column_dimensions['A'].width = 10
    ws.column_dimensions['B'].width = 14
    ws.column_dimensions['C'].width = 30

# ── Sheet 2: 单位A 资产录入 ──────────────────────────
def build_unit_a_sheet(wb, all_codes, departments):
    ws = wb.create_sheet("单位A资产录入")
    headers = ["科室", "资产类型", "资产编码", "数量", "备注"]
    hdr_fill = BLUE_FILL

    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = WHITE_FONT; cell.fill = hdr_fill; cell.alignment = CENTER; cell.border = THIN_BORDER

    apply_range_style(ws, 2, 51, 1, 5)

    # 数据验证: 科室下拉
    if departments:
        dept_list = '"' + ",".join(d["name"] for d in departments) + '"'
    else:
        dept_list = '"财务科,人事科,行政科,技术部"'
    dv_dept = DataValidation(type="list", formula1=dept_list, allow_blank=True, showDropDown=False,
                             showErrorMessage=True, error="请选择有效科室", errorTitle="无效输入")
    dv_dept.add("A2:A51")
    ws.add_data_validation(dv_dept)

    # 数据验证: 资产类型
    dv_type = DataValidation(type="list", formula1='"桌子,椅子"', allow_blank=True, showDropDown=False,
                             showErrorMessage=True, error="请选择桌子或椅子", errorTitle="无效输入")
    dv_type.add("B2:B51")
    ws.add_data_validation(dv_type)

    # 数据验证: 编码下拉（全部编码）
    code_list = '"' + ",".join(f"{c['code']}-{c['name']}" for c in all_codes) + '"'
    dv_code = DataValidation(type="list", formula1=code_list, allow_blank=True, showDropDown=False,
                             showErrorMessage=True, error="请从列表中选择有效编码", errorTitle="无效输入")
    dv_code.add("C2:C51")
    ws.add_data_validation(dv_code)

    ws.column_dimensions['A'].width = 14
    ws.column_dimensions['B'].width = 12
    ws.column_dimensions['C'].width = 26
    ws.column_dimensions['D'].width = 8
    ws.column_dimensions['E'].width = 24
    ws.page_setup.orientation = 'portrait'
    ws.page_setup.paperSize = ws.PAPERSIZE_A4

# ── Sheet 3: 单位B 资产录入 ──────────────────────────
def build_unit_b_sheet(wb, all_codes):
    ws = wb.create_sheet("单位B资产录入")
    headers = ["资产类型", "资产编码", "数量", "备注"]
    hdr_fill = RED_FILL

    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = WHITE_FONT; cell.fill = hdr_fill; cell.alignment = CENTER; cell.border = THIN_BORDER

    apply_range_style(ws, 2, 51, 1, 4)

    dv_type = DataValidation(type="list", formula1='"桌子,椅子"', allow_blank=True, showDropDown=False,
                             showErrorMessage=True, error="请选择桌子或椅子", errorTitle="无效输入")
    dv_type.add("A2:A51")
    ws.add_data_validation(dv_type)

    code_list = '"' + ",".join(f"{c['code']}-{c['name']}" for c in all_codes) + '"'
    dv_code = DataValidation(type="list", formula1=code_list, allow_blank=True, showDropDown=False,
                             showErrorMessage=True, error="请从列表中选择有效编码", errorTitle="无效输入")
    dv_code.add("B2:B51")
    ws.add_data_validation(dv_code)

    ws.column_dimensions['A'].width = 12
    ws.column_dimensions['B'].width = 26
    ws.column_dimensions['C'].width = 8
    ws.column_dimensions['D'].width = 24
    ws.page_setup.orientation = 'portrait'
    ws.page_setup.paperSize = ws.PAPERSIZE_A4

# ── Sheet 4: 白底标签 (单位A) ────────────────────────
def build_label_sheet(wb, unit_a_data, sheet_name, bg_fill, font_color):
    ws = wb.create_sheet(sheet_name)
    ws.sheet_properties.showGridLines = False

    row = 1
    col = 1
    for asset in unit_a_data:
        cell = ws.cell(row=row, column=col)
        label_text = f"{asset['code']}\n{asset['code_name']}"
        if 'department' in asset and asset.get('department'):
            label_text += f"\n{asset['department']}"
        label_text += f"\n× {asset['quantity']}"
        cell.value = label_text
        cell.font = Font(name="微软雅黑", size=9, bold=True, color=font_color)
        cell.fill = bg_fill
        cell.alignment = CENTER
        cell.border = Border(
            left=Side(style='medium', color='333333'),
            right=Side(style='medium', color='333333'),
            top=Side(style='medium', color='333333'),
            bottom=Side(style='medium', color='333333'))

        ws.row_dimensions[row].height = 55
        col += 1
        if col > 3:
            col = 1
            row += 1

    # 设置列宽（3 列标签布局）
    for c in range(1, 4):
        ws.column_dimensions[get_column_letter(c)].width = 28

    ws.page_setup.orientation = 'portrait'
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4

# ── Main ───────────────────────────────────────────────
def main():
    init_db()
    db = get_db()
    tables = db.execute("SELECT code, name, category FROM asset_codes WHERE category='table' ORDER BY sort_order").fetchall()
    chairs = db.execute("SELECT code, name, category FROM asset_codes WHERE category='chair' ORDER BY sort_order").fetchall()
    all_codes = db.execute("SELECT code, name, category FROM asset_codes ORDER BY category, sort_order").fetchall()
    departments = db.execute("SELECT name FROM asset_departments ORDER BY sort_order").fetchall()
    unit_a_data = db.execute(
        "SELECT ua.department, ua.quantity, ac.code, ac.name as code_name "
        "FROM unit_a_assets ua JOIN asset_codes ac ON ua.asset_code_id = ac.id "
        "ORDER BY ua.department, ac.category, ac.sort_order"
    ).fetchall()
    unit_b_data = db.execute(
        "SELECT ub.quantity, ac.code, ac.name as code_name "
        "FROM unit_b_assets ub JOIN asset_codes ac ON ub.asset_code_id = ac.id "
        "ORDER BY ac.category, ac.sort_order"
    ).fetchall()
    db.close()

    wb = Workbook()
    build_code_sheet(wb, tables, chairs)
    build_unit_a_sheet(wb, all_codes, departments)
    build_unit_b_sheet(wb, all_codes)
    build_label_sheet(wb, unit_a_data, "标签打印-白底A单位",
                      PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid"), "000000")
    build_label_sheet(wb, unit_b_data, "标签打印-红底B单位",
                      PatternFill(start_color="FF3B30", end_color="FF3B30", fill_type="solid"), "FFFFFF")

    wb.save(OUTPUT)
    print(f"模板已生成：{OUTPUT}")

if __name__ == "__main__":
    main()
