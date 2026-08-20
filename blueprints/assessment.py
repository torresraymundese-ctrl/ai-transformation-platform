"""Public V2 assessment configuration, preview, and completion APIs."""

from decimal import Decimal, DecimalException
import hashlib
import json
from math import cos, pi, sin
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    after_this_request,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
    session,
)

import assessment_repository
import report_pdf
from assessment.contracts import AssessmentInputError
from assessment.reporting import RISK_LABELS, public_service_not_included
from assessment.scoring import score_assessment
from assessment_completion_service import complete_assessment
from assessment_validation import (
    AssessmentRulesUnavailable,
    CONSENT_POLICY_VERSION,
    parse_completion_payload,
    parse_preview_payload,
    validate_profile_membership,
    validate_published_rule_bundle,
    validated_branch_code,
)
from repository import DataConflictError
from security import (
    consume_rate_limit,
    csrf_token,
    rate_limit_response,
    request_identity_hash,
    require_public_csrf,
)
from validation import ValidationError


bp = Blueprint("assessment_v2", __name__)

PRIVACY_DISCLOSURE_TEXT = {
    "purpose": "用于生成评估报告、联系需求诊断并改进平台服务。",
    "required_data_categories": ["企业名称", "联系人", "手机号", "隐私与联系授权"],
    "optional_data_categories": ["邮箱", "微信"],
    "retention": "未成交线索在最后一次有效跟进后保存365天。",
    "expiry_action": "到期后匿名化联系信息和跟进备注，仅保留不可回溯个人的评估与转化统计。",
    "rights": "可通过上述联系方式申请查阅、更正、撤回同意或删除个人信息。",
}

REPORT_DIMENSIONS = (
    ("business_value", "业务价值"),
    ("process", "流程基础"),
    ("data", "数据基础"),
    ("systems", "系统基础"),
    ("organization", "组织准备"),
    ("delivery", "落地条件"),
)

MATURITY_LABELS = {
    "explore": "探索起步",
    "pilot": "单点试验",
    "scale": "规模扩展",
    "collaborate": "智能协同",
}

SCENARIO_LABELS = {
    "mfg_knowledge_assistant": "制造业知识助手",
    "mfg_quality_inspection": "制造业质量检测",
    "mfg_operations_reporting": "生产经营数据洞察",
    "retail_ai_service": "零售智能客服",
    "retail_marketing_content": "零售营销内容助手",
    "retail_inventory_insight": "零售库存洞察",
    "pro_document_knowledge": "专业文档知识助手",
    "pro_delivery_drafting": "专业交付文档自动化",
    "pro_contract_review": "合同审阅辅助",
    "creative_content_workflow": "创意内容工作流",
    "software_support_knowledge": "软件服务知识助手",
    "project_delivery_automation": "项目交付自动化",
    "data_process_foundation": "数据与流程准备",
}

ROI_BANDS = (
    ("conservative", "保守"),
    ("midpoint", "中位"),
    ("ideal", "理想"),
)

INTEGRATION_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
}

SERVICE_CATEGORY_LABELS = {
    "foundation": "基础准备",
    "pilot": "试点验证",
    "standard": "标准交付",
    "integration": "集成交付",
}

ROI_INPUT_FIELDS = (
    (
        "headcount",
        "参与人数",
        {
            "1_5": "1—5 人",
            "6_20": "6—20 人",
            "21_50": "21—50 人",
            "50_plus": "50 人以上",
        },
    ),
    (
        "monthly_hours",
        "每人每月耗时",
        {
            "under_20": "20 小时内",
            "20_80": "20—80 小时",
            "80_160": "80—160 小时",
            "160_plus": "160 小时以上",
        },
    ),
    (
        "monthly_cost",
        "人均月综合成本",
        {
            "under_8000": "8,000 元内",
            "8000_15000": "8,000—15,000 元",
            "15000_30000": "15,000—30,000 元",
            "30000_plus": "30,000 元以上",
        },
    ),
    (
        "loss_factor",
        "返工或损耗程度",
        {"rare": "很少", "normal": "一般", "high": "较高", "severe": "严重"},
    ),
    (
        "budget",
        "可接受投入",
        {
            "under_50000": "5 万元内",
            "50000_200000": "5—20 万元",
            "200000_500000": "20—50 万元",
            "500000_plus": "50 万元以上",
        },
    ),
)


@bp.get("/api/v2/assessment/config/<branch_code>")
def assessment_config(branch_code):
    try:
        branch_code = validated_branch_code(branch_code)
        privacy = _privacy_disclosure()
        catalog, public_config = _published_context(branch_code)
    except ValidationError:
        return _invalid_response()
    except _RULE_FAILURES as error:
        return _unavailable_response(error)

    return jsonify(
        {
            "schema_version": "2.0",
            "rule_version": catalog.version_code,
            "consent_policy_version": CONSENT_POLICY_VERSION,
            "branch": public_config["branch"],
            "subbranches": public_config["subbranches"],
            "departments": public_config["departments"],
            "company_sizes": public_config["company_sizes"],
            "pain_points": public_config["pain_points"],
            "pain_selection": public_config["pain_selection"],
            "questions": [
                {
                    "code": question.code,
                    "dimension": question.dimension,
                    "prompt": question.prompt,
                    "options": [
                        {
                            "code": option.code,
                            "label": option.label,
                            "score": option.score,
                        }
                        for option in question.options
                    ],
                }
                for question in catalog.questions
            ],
            "roi_options": public_config["roi_options"],
            "reference_line": {
                "label": public_config["reference_label"],
                "scores": dict(catalog.reference_lines[branch_code]),
            },
            "privacy_disclosure": privacy,
            "csrf_token": csrf_token(),
        }
    )


@bp.post("/api/v2/assessment/preview")
def assessment_preview():
    try:
        profile = parse_preview_payload(request.get_json(silent=True))
        _privacy_disclosure()
        catalog, public_config = _published_context(profile.branch_code)
        validate_profile_membership(profile, catalog, public_config)
        scores = score_assessment(catalog, profile)
    except ValidationError:
        return _invalid_response()
    except AssessmentInputError:
        return _invalid_response()
    except _RULE_FAILURES as error:
        return _unavailable_response(error)
    if not consume_rate_limit(
        "assessment_v2_preview",
        current_app.config["ASSESSMENT_PREVIEW_RATE_LIMIT"],
        current_app.config["ASSESSMENT_PREVIEW_RATE_WINDOW"],
    ):
        return rate_limit_response(
            current_app.config["ASSESSMENT_PREVIEW_RATE_WINDOW"]
        )
    return jsonify(
        {
            "maturity": scores.maturity_code,
            "strongest": scores.strongest_dimension,
            "weakest": scores.weakest_dimension,
        }
    )


@bp.post("/api/v2/assessment/complete")
def assessment_complete():
    require_public_csrf()
    try:
        completion_request = parse_completion_payload(request.get_json(silent=True))
        _privacy_disclosure()
        catalog, public_config = _published_context(
            completion_request.profile.branch_code
        )
        validate_profile_membership(
            completion_request.profile, catalog, public_config
        )
        score_assessment(catalog, completion_request.profile)
    except ValidationError:
        return _invalid_response()
    except AssessmentInputError:
        return _invalid_response()
    except _RULE_FAILURES as error:
        return _unavailable_response(error)
    if not consume_rate_limit(
        "assessment_v2_complete",
        current_app.config["ASSESSMENT_COMPLETE_RATE_LIMIT"],
        current_app.config["ASSESSMENT_COMPLETE_RATE_WINDOW"],
    ):
        return rate_limit_response(
            current_app.config["ASSESSMENT_COMPLETE_RATE_WINDOW"]
        )
    try:
        result = complete_assessment(completion_request, request_identity_hash())
    except ValidationError:
        return _invalid_response()
    except AssessmentInputError:
        return _invalid_response()
    except DataConflictError:
        return _unavailable_response(DataConflictError())
    except _RULE_FAILURES as error:
        return _unavailable_response(error)

    report_ids = list(session.get("assessment_report_ids", ()))
    if not result.created:
        if result.assessment_id not in report_ids:
            return jsonify({"error": "assessment conflict"}), 409
    else:
        report_ids.append(result.assessment_id)
        session["assessment_report_ids"] = report_ids[-5:]
    return jsonify(
        {
            "success": True,
            "assessment_id": result.assessment_id,
            "report_url": f"/assessment/report/{result.assessment_id}",
            "pdf_url": f"/assessment/report/{result.assessment_id}/pdf",
        }
    )


@bp.get("/assessment/report/<int:assessment_id>")
def assessment_report(assessment_id):
    _protect_report_response()
    snapshot = _authorized_report_snapshot(assessment_id)
    if snapshot is None:
        abort(404)
    return render_template(
        "assessment/report.html",
        **_report_template_context(assessment_id, snapshot, pdf_mode=False),
    )


@bp.get("/assessment/report/<int:assessment_id>/pdf")
def assessment_report_pdf(assessment_id):
    _protect_report_response()
    snapshot = _authorized_report_snapshot(assessment_id)
    if snapshot is None:
        abort(404)
    html = render_template(
        "assessment/report_pdf.html",
        **_report_template_context(assessment_id, snapshot, pdf_mode=True),
    )
    try:
        pdf = report_pdf.render_pdf(html, _trusted_app_base_url())
        if not isinstance(pdf, (bytes, bytearray)) or not pdf:
            raise TypeError("PDF renderer returned no bytes")
    except Exception as error:
        current_app.logger.error(
            "PDF report generation unavailable failure_type=%s endpoint=%s",
            type(error).__name__,
            request.endpoint or "unknown",
        )
        return render_template(
            "error.html",
            title="PDF 暂时无法生成",
            message="在线报告仍可查看，请稍后重试 PDF 下载。",
        ), 503
    response = make_response(bytes(pdf))
    response.mimetype = "application/pdf"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="ai-readiness-report-{assessment_id}.pdf"'
    )
    return response


def _protect_report_response():
    @after_this_request
    def private_no_store(response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


def _authorized_report_snapshot(assessment_id):
    report_ids = session.get("assessment_report_ids")
    if not isinstance(report_ids, (list, tuple)):
        return None
    if not any(
        type(value) is int and value == assessment_id for value in report_ids
    ):
        return None
    return assessment_repository.load_report_snapshot(assessment_id)


def _report_template_context(assessment_id, snapshot, pdf_mode):
    scores = snapshot["scores"]
    dimension_rows = []
    for code, label in REPORT_DIMENSIONS:
        dimension_rows.append(
            {
                "code": code,
                "label": label,
                "score": scores["dimension_scores"][code],
                "reference": scores["reference_line"][code],
            }
        )
    return {
        "assessment_id": assessment_id,
        "snapshot": snapshot,
        "snapshot_digest": hashlib.sha256(
            json.dumps(
                snapshot,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        "dimension_rows": dimension_rows,
        "dimension_labels": dict(REPORT_DIMENSIONS),
        "radar": _radar_context(dimension_rows),
        "maturity_label": MATURITY_LABELS[scores["maturity_code"]],
        "scenario_labels": SCENARIO_LABELS,
        "integration_labels": INTEGRATION_LABELS,
        "service_category_labels": SERVICE_CATEGORY_LABELS,
        "risk_labels": RISK_LABELS,
        "roi_bands": ROI_BANDS,
        "roi_choice_rows": _roi_choice_rows(snapshot["calculation_basis"]),
        "format_roi_currency": _format_roi_currency,
        "format_budget_currency": _format_budget_currency,
        "public_service_not_included": public_service_not_included,
        "pdf_mode": pdf_mode,
    }


def _roi_choice_rows(calculation_basis):
    choices = calculation_basis["selected_roi_choices"]
    bands = calculation_basis["selected_roi_bands"]
    return [
        {
            "label": label,
            "selection": descriptions[choices[group]],
            "low": _format_roi_input(group, bands[group]["low"]),
            "mid": _format_roi_input(group, bands[group]["mid"]),
            "high": _format_roi_input(group, bands[group]["high"]),
        }
        for group, label, descriptions in ROI_INPUT_FIELDS
    ]


def _format_roi_input(group, value):
    number = Decimal(value)
    if group == "loss_factor":
        return f"{format((number * 100).normalize(), 'f')}%"
    formatted = f"{number:,.0f}"
    if group == "headcount":
        return f"{formatted} 人"
    if group == "monthly_hours":
        return f"{formatted} 小时"
    return f"¥{formatted}"


def _format_roi_currency(value):
    return _format_currency(value, decimal_places=2)


def _format_budget_currency(value):
    return _format_currency(value, decimal_places=0)


def _format_currency(value, decimal_places):
    number = Decimal(value)
    sign = "-" if number < 0 else ""
    return f"{sign}¥{abs(number):,.{decimal_places}f}"


def _radar_context(dimension_rows):
    center = 160.0
    radius = 100.0
    angles = tuple(-pi / 2 + index * pi / 3 for index in range(6))

    def polygon(values, scale=radius):
        return " ".join(
            f"{center + cos(angle) * scale * value / 100:.1f},"
            f"{center + sin(angle) * scale * value / 100:.1f}"
            for angle, value in zip(angles, values)
        )

    axes = []
    anchors = ("middle", "start", "start", "middle", "end", "end")
    for row, angle, anchor in zip(dimension_rows, angles, anchors):
        axes.append(
            {
                "label": row["label"],
                "x": f"{center + cos(angle) * radius:.1f}",
                "y": f"{center + sin(angle) * radius:.1f}",
                "label_x": f"{center + cos(angle) * 126:.1f}",
                "label_y": f"{center + sin(angle) * 126 + 4:.1f}",
                "anchor": anchor,
            }
        )
    return {
        "grid": [polygon((100,) * 6, scale) for scale in (25, 50, 75, 100)],
        "score": polygon([row["score"] for row in dimension_rows]),
        "reference": polygon([row["reference"] for row in dimension_rows]),
        "axes": axes,
    }


def _trusted_app_base_url():
    return f"{Path(current_app.root_path).resolve().as_uri().rstrip('/')}/"


def _published_context(branch_code):
    (
        catalog,
        public_config,
        scenarios,
        services,
        ranges,
    ) = assessment_repository.load_published_rule_bundle(branch_code)
    validate_published_rule_bundle(
        catalog,
        branch_code,
        public_config,
        scenarios,
        services,
        ranges,
    )
    return catalog, public_config


def _privacy_disclosure():
    values = {
        "processor_name": current_app.config.get("PRIVACY_PROCESSOR_NAME"),
        "contact": current_app.config.get("PRIVACY_CONTACT"),
        "policy_url": current_app.config.get("PRIVACY_POLICY_URL"),
    }
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise AssessmentRulesUnavailable("privacy_configuration")
    policy = urlsplit(values["policy_url"].strip())
    if (
        policy.scheme not in {"http", "https"}
        or not policy.netloc
        or policy.username is not None
        or policy.password is not None
    ):
        raise AssessmentRulesUnavailable("privacy_policy_url")
    return {
        "processor_name": values["processor_name"].strip(),
        "contact": values["contact"].strip(),
        "policy_url": values["policy_url"].strip(),
        **PRIVACY_DISCLOSURE_TEXT,
    }


def _invalid_response():
    return jsonify({"error": "invalid assessment payload"}), 400


def _unavailable_response(error):
    current_app.logger.error(
        "Assessment API unavailable failure_type=%s endpoint=%s",
        type(error).__name__,
        request.endpoint or "unknown",
    )
    return jsonify(
        {"error": "assessment temporarily unavailable", "recoverable": True}
    ), 503


_RULE_FAILURES = (
    AssessmentRulesUnavailable,
    RuntimeError,
    KeyError,
    TypeError,
    ValueError,
    DecimalException,
    sqlite3.DatabaseError,
)
