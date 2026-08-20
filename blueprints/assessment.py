"""Public V2 assessment configuration, preview, and completion APIs."""

from decimal import DecimalException
import sqlite3
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify, request, session

import assessment_repository
from assessment.contracts import AssessmentInputError
from assessment.scoring import score_assessment
from assessment_completion_service import complete_assessment
from assessment_validation import (
    AssessmentRulesUnavailable,
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
