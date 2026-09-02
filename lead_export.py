"""Privacy-safe lead CSV serialization and audit metadata helpers."""

import csv
from io import StringIO
import unicodedata


EXPORT_HEADERS = (
    "企业名称",
    "联系人",
    "手机号",
    "邮箱",
    "微信",
    "线索状态",
    "负责人",
    "行业分支",
    "部门",
    "评估编号",
    "成熟度",
    "推荐主场景",
    "预约状态",
    "意向日期",
    "时间段",
    "最后有效跟进时间",
    "下次跟进时间",
)
EXPORT_FIELDS = (
    "company_name",
    "contact_name",
    "phone",
    "email",
    "wechat",
    "status",
    "owner_text",
    "industry_branch",
    "department",
    "assessment_number",
    "maturity",
    "primary_scenario",
    "appointment_status",
    "preferred_date",
    "time_slot",
    "last_effective_followup_at",
    "next_followup_at",
)
UTF8_BOM = b"\xef\xbb\xbf"


def _normalized_text(value):
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text)
    return "".join(
        character
        for character in text
        if character in {"\r", "\n"}
        or not unicodedata.category(character).startswith("C")
    )


def csv_cell(value, *, force_text=False):
    text = _normalized_text(value)
    if text and (force_text or text.lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + text
    return text


def write_lead_csv(rows) -> bytes:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(EXPORT_HEADERS)
    for row in rows:
        writer.writerow(
            [
                csv_cell(row[field], force_text=(field == "phone"))
                for field in EXPORT_FIELDS
            ]
        )
    return UTF8_BOM + output.getvalue().encode("utf-8")


def audit_filter_metadata(filters):
    metadata = {
        "queue": filters.queue,
        "search_used": filters.search is not None,
    }
    for source, target in (
        ("status", "status"),
        ("branch", "industry_branch"),
        ("date_from", "created_from"),
        ("date_to", "created_to"),
    ):
        value = getattr(filters, source)
        if value is not None:
            metadata[target] = value
    return metadata
