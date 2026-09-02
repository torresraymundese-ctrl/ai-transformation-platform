"""Pure, deterministic builders for JSON-serializable assessment reports."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from .contracts import (
    AssessmentCatalog,
    AssessmentInputError,
    AssessmentProfile,
    RoiBand,
    RoiResult,
    ScenarioMatch,
    ScoreResult,
)
from .matching import REASON_TEMPLATES
from .seed import LEGACY_SERVICE_NOT_INCLUDED, load_core_catalog_manifest


DIMENSION_ORDER = (
    "business_value",
    "process",
    "data",
    "systems",
    "organization",
    "delivery",
)

ROI_CHOICE_ORDER = (
    "headcount",
    "monthly_hours",
    "monthly_cost",
    "loss_factor",
    "budget",
)

DIMENSION_EXPLANATIONS = {
    "business_value": "业务价值维度得分较高，建议将已识别痛点作为试点收益和验收指标的起点。",
    "process": "流程维度得分较高，建议以现有 SOP 和稳定环节界定试点范围。",
    "data": "数据维度得分较高，建议优先使用已明确来源、口径和更新方式的数据。",
    "systems": "系统维度得分较高，建议在权限和接口边界明确后规划必要协同。",
    "organization": "组织与推广维度得分较高，建议由业务负责人持续复核采用和运营效果。",
    "delivery": "交付准备维度得分较高，建议按负责人、范围、验收和复盘节奏推进。",
}

DIMENSION_IMPROVEMENT_EXPLANATIONS = {
    "business_value": "业务价值维度仍需补齐，建议先量化痛点频率、影响范围和可验收收益。",
    "process": "流程维度仍需补齐，建议先梳理 SOP、例外处理和流程边界。",
    "data": "数据维度仍需补齐，建议先确认数据来源、质量责任和可用范围。",
    "systems": "系统维度仍需补齐，建议先确认现有工具、权限边界和必要接口条件。",
    "organization": "组织与推广维度仍需补齐，建议明确业务负责人、协作资源和试点采用安排。",
    "delivery": "交付准备维度仍需补齐，建议明确预算、时间安排和阶段验收条件。",
}

RISK_EXPLANATIONS = {
    "source_quality": "先确认资料来源、质量标准和更新责任。",
    "access_control": "先明确资料和系统的访问权限、审批和审计边界。",
    "adoption": "将使用培训、反馈收集和业务负责人复盘纳入试点验收。",
    "sample_quality": "先验证样本覆盖范围、标注质量和异常样本处理方式。",
    "false_positive": "约定误报处理、人工复核和持续校准机制。",
    "equipment_integration": "先确认设备接口、现场条件和联调责任边界。",
    "metric_definition": "先统一指标定义、计算口径和复核责任。",
    "source_consistency": "先核对来源系统、字段含义和更新频率。",
    "data_refresh": "明确数据刷新节奏、延迟边界和异常处理。",
    "response_accuracy": "约定回答质量评测、人工升级和错误反馈机制。",
    "escalation": "明确无法处理事项的升级路径、责任人和响应时限。",
    "brand_consistency": "将品牌规范、审核流程和样例纳入内容验收。",
    "approval_flow": "明确内容或动作的审批节点、权限和留痕要求。",
    "content_compliance": "在上线前确认内容合规边界、审核责任和例外处理。",
    "forecast_error": "设定预测偏差监控、人工复核和调整节奏。",
    "system_integration": "先确认系统接口、数据权限、联调范围和验收责任。",
    "confidentiality": "明确保密资料范围、访问规则和人工复核要求。",
    "answer_scope": "限定回答范围，并为超出范围的问题设置人工处理路径。",
    "template_quality": "先确认模板版本、适用范围和业务审核责任。",
    "human_review": "保留人工复核节点，并明确抽检和例外处理方式。",
    "exception_handling": "列出异常类型、人工队列和闭环责任。",
    "legal_scope": "明确工具输出的适用边界，保留专业人员复核。",
    "intellectual_property": "确认素材、生成内容和交付物的知识产权使用边界。",
    "source_freshness": "明确知识来源更新频率、过期处理和维护责任。",
    "process_variance": "先识别流程差异、例外路径和可标准化范围。",
    "integration": "先明确跨系统协同的接口、权限、责任和验收范围。",
    "change_management": "制定变更沟通、培训、反馈和业务负责人复盘安排。",
    "owner_availability": "确认业务负责人可投入的时间、决策权限和复盘安排。",
    "data_inventory": "先形成数据清单，标明来源、用途、质量和访问负责人。",
}

RISK_LABELS = {
    "source_quality": "资料来源与质量",
    "access_control": "访问权限控制",
    "adoption": "用户采用",
    "sample_quality": "样本质量",
    "false_positive": "误报风险",
    "equipment_integration": "设备集成",
    "metric_definition": "指标口径",
    "source_consistency": "数据源一致性",
    "data_refresh": "数据刷新",
    "response_accuracy": "回答准确性",
    "escalation": "人工升级",
    "brand_consistency": "品牌一致性",
    "approval_flow": "审批流程",
    "content_compliance": "内容合规",
    "forecast_error": "预测偏差",
    "system_integration": "系统集成",
    "confidentiality": "保密管理",
    "answer_scope": "回答范围",
    "template_quality": "模板质量",
    "human_review": "人工复核",
    "exception_handling": "异常处理",
    "legal_scope": "法律适用边界",
    "intellectual_property": "知识产权",
    "source_freshness": "知识时效",
    "process_variance": "流程差异",
    "integration": "集成边界",
    "change_management": "变更管理",
    "owner_availability": "负责人投入",
    "data_inventory": "数据清单",
}

ROADMAP_90 = (
    ("1-15", "确认痛点、负责人、流程边界和基线指标"),
    ("16-30", "整理数据、确定试点范围和验收标准"),
    ("31-60", "配置或开发试点、完成内部测试和培训"),
    ("61-90", "小范围运行、验收、复盘并决定是否扩展"),
)

YEAR_1_BY_MATURITY = {
    "explore": "完成流程和数据基础梳理，选择 1 个低集成高价值场景试点并建立验收基线",
    "pilot": "完成 1—2 个高价值场景试点，建立数据、流程和效果基线",
    "scale": "稳定运行 2—3 个高价值场景，固化负责人、验收和运营机制",
    "collaborate": "优化跨系统协同场景，同时复核数据基线、权限和业务验收指标",
}

ROADMAP_YEARS_2_3 = (
    (2, "复制到相邻部门，打通必要系统并建立统一运营指标"),
    (3, "形成跨部门协同、治理和持续优化机制"),
)

DISCLAIMER = (
    "本报告由平台规则自动生成，仅用于初步评估和项目沟通，"
    "不构成收益、投资、法律或合规承诺。"
)

_PUBLIC_SERVICE_NOT_INCLUDED = {
    service["code"]: tuple(service["not_included"])
    for service in load_core_catalog_manifest()["services"]
}


@dataclass(frozen=True)
class ReportPublicCopy:
    """Immutable release-owned copy supplied only by draft previews."""

    risk_explanations: Mapping[str, str]

    def __post_init__(self):
        if not isinstance(self.risk_explanations, Mapping) or any(
            type(code) is not str or type(value) is not str
            for code, value in self.risk_explanations.items()
        ):
            raise TypeError("invalid report public copy")
        object.__setattr__(
            self,
            "risk_explanations",
            MappingProxyType(dict(self.risk_explanations)),
        )


def public_service_not_included(package):
    """Return Chinese display copy without changing a persisted legacy snapshot."""
    code = package["code"]
    stored = tuple(package["not_included"])
    if stored == LEGACY_SERVICE_NOT_INCLUDED.get(code):
        return _PUBLIC_SERVICE_NOT_INCLUDED[code]
    return stored


def build_report_snapshot(
    profile: AssessmentProfile,
    scores: ScoreResult,
    matches: tuple[ScenarioMatch, ...],
    roi: RoiResult,
    catalog: AssessmentCatalog,
    roi_option_ranges,
    *,
    public_copy: ReportPublicCopy | None = None,
) -> dict[str, object]:
    """Build the complete stored report record without persistence or generated prose."""
    reference_line = catalog.reference_lines.get(profile.branch_code)
    if reference_line is None:
        raise AssessmentInputError(
            f"no reference line for branch {profile.branch_code!r}"
        )
    if scores.maturity_code not in YEAR_1_BY_MATURITY:
        raise AssessmentInputError(f"unknown maturity code: {scores.maturity_code!r}")
    _validate_dimensions(scores, reference_line)

    if public_copy is not None and type(public_copy) is not ReportPublicCopy:
        raise TypeError("invalid report public copy")
    risk_explanations = (
        RISK_EXPLANATIONS
        if public_copy is None
        else public_copy.risk_explanations
    )
    selected_matches = tuple(matches[:3])
    return {
        "schema_version": "2.0",
        "rule_version": catalog.version_code,
        "assessment": {
            "branch_code": profile.branch_code,
            "subbranch_code": profile.subbranch_code,
            "department_code": profile.department_code,
            "company_size_code": profile.company_size_code,
            "pain_codes": list(profile.pain_codes),
            "answers": dict(profile.answers),
            "roi_choices": dict(profile.roi_choices),
        },
        "scores": {
            "overall_score": scores.overall_score,
            "maturity_code": scores.maturity_code,
            "dimension_scores": {
                dimension: scores.dimension_scores[dimension]
                for dimension in DIMENSION_ORDER
            },
            "reference_line": {
                dimension: reference_line[dimension] for dimension in DIMENSION_ORDER
            },
            "strongest": _dimension_explanation(
                scores.strongest_dimension, DIMENSION_EXPLANATIONS
            ),
            "weakest": _dimension_explanation(
                scores.weakest_dimension, DIMENSION_IMPROVEMENT_EXPLANATIONS
            ),
        },
        "recommendations": [
            _recommendation(match, risk_explanations) for match in selected_matches
        ],
        "roi": {
            band.band_code: _roi_band(band)
            for band in (roi.conservative, roi.midpoint, roi.ideal)
        },
        "calculation_basis": _calculation_basis(
            profile, selected_matches, roi, roi_option_ranges
        ),
        "roadmap_90_days": [
            {"days": days, "action": action} for days, action in ROADMAP_90
        ],
        "roadmap_years_1_3": [
            {"year": 1, "action": YEAR_1_BY_MATURITY[scores.maturity_code]},
            *({"year": year, "action": action} for year, action in ROADMAP_YEARS_2_3),
        ],
        "disclaimer": DISCLAIMER,
    }


def _validate_dimensions(scores: ScoreResult, reference_line: object) -> None:
    if set(scores.dimension_scores) != set(DIMENSION_ORDER):
        raise AssessmentInputError("dimension scores must cover exactly six dimensions")
    if not isinstance(reference_line, dict) and not hasattr(reference_line, "keys"):
        raise AssessmentInputError("reference line must be a mapping")
    if set(reference_line) != set(DIMENSION_ORDER):
        raise AssessmentInputError("reference line must cover exactly six dimensions")
    if scores.strongest_dimension not in DIMENSION_EXPLANATIONS:
        raise AssessmentInputError("unknown strongest dimension")
    if scores.weakest_dimension not in DIMENSION_IMPROVEMENT_EXPLANATIONS:
        raise AssessmentInputError("unknown weakest dimension")


def _dimension_explanation(
    dimension: str, templates: dict[str, str]
) -> dict[str, str]:
    return {"dimension": dimension, "explanation": templates[dimension]}


def _recommendation(
    match: ScenarioMatch, risk_explanations: Mapping[str, str]
) -> dict[str, object]:
    reasons = []
    for code in match.reason_codes:
        explanation = REASON_TEMPLATES.get(code)
        if explanation is None:
            raise AssessmentInputError(f"unknown recommendation reason: {code!r}")
        reasons.append(explanation)
    return {
        "scenario": {
            "code": match.scenario.code,
            "category_code": match.scenario.category_code,
            "integration_level": match.scenario.integration_level,
            "delivery_weeks": {
                "min": match.scenario.min_weeks,
                "max": match.scenario.max_weeks,
            },
        },
        "match_score": match.total_score,
        "components": dict(match.components),
        "reason_codes": list(match.reason_codes),
        "reasons": reasons,
        "risks": [_risk(code, risk_explanations) for code in match.scenario.risk_codes],
        "package": _package(match),
    }


def _risk(code: str, risk_explanations: Mapping[str, str]) -> dict[str, str]:
    explanation = risk_explanations.get(code)
    if explanation is None:
        raise AssessmentInputError(f"unknown recommendation risk: {code!r}")
    return {"code": code, "explanation": explanation}


def _package(match: ScenarioMatch) -> dict[str, object]:
    service = match.service
    return {
        "code": service.code,
        "category": service.category,
        "public_name": service.public_name,
        "budget_range": {
            "min": _decimal_string(service.min_budget),
            "max": _decimal_string(service.max_budget),
        },
        "delivery_weeks": {"min": service.min_weeks, "max": service.max_weeks},
        "deliverables": list(service.deliverables),
        "implementation_steps": list(service.implementation_steps),
        "prerequisites": list(service.prerequisites),
        "not_included": list(service.not_included),
        "acceptance": list(service.acceptance),
        "support_days": service.support_days,
    }


def _roi_band(band: RoiBand) -> dict[str, str | None]:
    return {
        "current_annual_cost": _decimal_string(band.current_annual_cost),
        "labor_savings": _decimal_string(band.labor_savings),
        "loss_savings": _decimal_string(band.loss_savings),
        "annual_savings": _decimal_string(band.annual_savings),
        "initial_investment": _decimal_string(band.initial_investment),
        "annual_support": _decimal_string(band.annual_support),
        "payback_months": (
            None
            if band.payback_months is None
            else _decimal_string(band.payback_months)
        ),
        "three_year_support": _decimal_string(band.three_year_support),
        "three_year_net": _decimal_string(band.three_year_net),
    }


def _calculation_basis(
    profile: AssessmentProfile,
    matches: tuple[ScenarioMatch, ...],
    roi: RoiResult,
    roi_option_ranges,
) -> dict[str, object]:
    primary = matches[0].scenario if matches else None
    try:
        selected_roi_bands = {
            group: {
                name: _decimal_string(value)
                for name, value in zip(
                    ("low", "mid", "high"),
                    roi_option_ranges[group][profile.roi_choices[group]],
                )
            }
            for group in ROI_CHOICE_ORDER
        }
    except (KeyError, TypeError):
        raise AssessmentInputError("ROI calculation basis is incomplete") from None
    if any(len(values) != 3 for values in selected_roi_bands.values()):
        raise AssessmentInputError("ROI calculation basis is incomplete")
    return {
        "selected_roi_choices": {
            group: profile.roi_choices[group] for group in ROI_CHOICE_ORDER
        },
        "selected_scenario": None if primary is None else primary.code,
        "coefficients": {
            "efficiency": [] if primary is None else [_decimal_string(value) for value in primary.efficiency],
            "loss_improvement": [] if primary is None else [_decimal_string(value) for value in primary.loss_improvement],
            "annual_support_rate": [] if primary is None else [_decimal_string(value) for value in primary.annual_support_rate],
        },
        "selected_roi_bands": selected_roi_bands,
    }


def _decimal_string(value: Decimal) -> str:
    return str(value)
