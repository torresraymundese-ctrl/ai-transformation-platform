"""Read-only administrator display labels; never normalize submitted values."""

import json

from assessment_repository import report_summary_from_snapshot


LABELS = {
    "status": {
        "draft": "草稿", "scheduled": "已排期", "published": "已发布",
        "archived": "已归档", "new": "新线索", "pending_contact": "待联系",
        "contacted": "已联系", "diagnosis_scheduled": "已预约诊断",
        "proposal": "方案沟通中", "won": "已成交", "not_progressing": "暂不推进",
        "pending": "待处理", "confirmed": "已确认", "completed": "已完成",
        "cancelled": "已取消", "received": "已收到", "verifying": "核验中",
        "rejected": "已驳回", "ready": "可使用", "fetched": "已抓取",
        "pending_review": "待审核", "accepted": "已采纳", "open": "未完成",
    },
    "appointment": {"pending": "待确认"},
    "branch": {
        "manufacturing": "制造业", "retail": "零售电商",
        "professional_knowledge": "知识型专业服务", "software_creative": "软件与创意服务",
    },
    "catalog": {"industry": "行业文案", "scenario": "场景文案", "service": "服务文案"},
    "legal": {
        "privacy": "隐私政策", "terms": "服务条款",
        "roi_disclaimer": "收益测算说明", "ai_content_notice": "AI 内容说明",
        "internal": "站内文档", "external_legacy": "历史外部文档",
    },
    "request": {"access": "查阅与复制", "correction": "更正信息", "withdrawal": "撤回授权", "deletion": "删除信息"},
    "channel": {"email": "邮箱", "phone": "电话", "wechat": "微信", "other": "其他"},
    "time_slot": {"morning": "上午", "afternoon": "下午", "evening": "晚上"},
}

# V2.0 snapshots predate release-owned display_labels. Keep their historical
# names here; do not query today's editable content or change the public report.
LEGACY_SCENARIO_LABELS = {
    "mfg_knowledge_assistant": "制造业知识助手", "mfg_quality_inspection": "制造业质量检测",
    "mfg_operations_reporting": "生产经营数据洞察", "retail_ai_service": "零售智能客服",
    "retail_marketing_content": "零售营销内容助手", "retail_inventory_insight": "零售库存洞察",
    "pro_document_knowledge": "专业文档知识助手", "pro_delivery_drafting": "专业交付文档自动化",
    "pro_contract_review": "合同审阅辅助", "creative_content_workflow": "创意内容工作流",
    "project_delivery_automation": "项目交付自动化", "software_support_knowledge": "软件服务知识助手",
    "data_process_foundation": "数据与流程准备",
}


def admin_label(value, domain="status"):
    """Known enums get readable labels; unknown values stay visible and escaped."""
    if value is None or value == "":
        return "—"
    text = str(value)
    return LABELS.get(domain, {}).get(text, LABELS["status"].get(text, text))


def assessment_result_labels(raw):
    """Display only a validated, bounded saved result; never recalculate it."""
    summary = report_summary_from_snapshot(raw)
    if summary is None:
        return "结果暂不可用", None
    snapshot = json.loads(raw)
    labels = snapshot.get("display_labels", {}).get("scenarios", LEGACY_SCENARIO_LABELS)
    code = summary[1]
    label = labels.get(code, code)
    if label == code:
        label = LEGACY_SCENARIO_LABELS.get(code, code)
    return label, snapshot["recommendations"][0]["package"]["public_name"]
