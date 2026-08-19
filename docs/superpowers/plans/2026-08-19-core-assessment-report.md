# Core Assessment and Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete choice-based assessment, deterministic scoring and recommendations, ROI estimate, session-only HTML/PDF report, lead consent, appointment intent, and conversion-event loop.

**Architecture:** Extend the existing Flask modular monolith with a focused `assessment/` domain package containing pure scoring, matching, ROI, and report functions. SQLite stores versioned rule/catalog data and immutable result snapshots; HTTP blueprints validate requests and delegate transactional writes to repositories/services. The browser uses vanilla JavaScript for the six-step wizard, while the server remains authoritative for every score and report.

**Tech Stack:** Python 3.12 locally / Python 3.10+ in production, Flask 3, SQLite WAL, Jinja, vanilla JavaScript, pytest, BeautifulSoup, WeasyPrint 69.x, Noto CJK fonts.

**Spec:** `docs/superpowers/specs/2026-08-19-ai-platform-2.0-product-design.md`

## Global Constraints

- Keep production Nginx stopped and do not connect to or mutate the production server during implementation.
- Preserve current public URLs and the legacy `POST /api/assessment` behavior until the V2 flow has its own regression coverage.
- The wizard has 6 steps and exactly 22 choice interactions: branch, subbranch, department, company size, one pain multi-select interaction, 12 scored questions, and 5 ROI choices. Only company, contact name, phone, optional email, optional WeChat, and optional appointment note accept typed text.
- Use the four branch codes `manufacturing`, `retail`, `professional_knowledge`, and `software_creative`.
- Use exactly six dimensions: `business_value`, `process`, `data`, `systems`, `organization`, and `delivery`.
- Every score, match, ROI value, roadmap item, and report statement is deterministic and tied to a published rule version; do not call an LLM.
- Do not add user accounts, SMS verification, online payment, consultant calendars, multiple admin accounts, roles, or permissions.
- Require company name, contact name, normalized mainland China mobile number, and explicit privacy consent before creating the complete report.
- Reports and PDFs are accessible to the public user only through the current server-side Session; do not create permanent public tokens or recovery links.
- Two operators continue sharing the one environment-configured administrator account.
- Unconverted lead PII expires 365 days after the last effective follow-up; converted customers are exempt from this automatic purge.
- Do not remove the unrelated asset module in this plan. Its code and tables are removed only in the content/operations subproject after a production backup rehearsal.
- All new production behavior follows red-green-refactor, uses explicit transaction boundaries, returns generic safe errors, and does not log contact fields or raw request bodies.
- Functional structure comes before final visual redesign; use the current theme and only add the CSS needed for a usable responsive flow.

## File Structure

Create:

- `assessment/__init__.py` — package marker.
- `assessment/contracts.py` — frozen domain dataclasses and enums.
- `assessment/scoring.py` — six-dimension and maturity calculation.
- `assessment/matching.py` — scenario gates, ranking, and fallback.
- `assessment/roi.py` — three-band ROI calculations.
- `assessment/reporting.py` — deterministic report and roadmap snapshot.
- `assessment_validation.py` — request-shape and code validation.
- `assessment_repository.py` — catalog reads and assessment result writes.
- `lead_repository.py` — lead, consent, status, and follow-up persistence.
- `appointment_repository.py` — appointment persistence and transitions.
- `analytics_repository.py` — allowlisted anonymous event writes.
- `assessment_completion_service.py` — one transaction for lead, consent, assessment, and critical event.
- `report_pdf.py` — HTML-to-PDF adapter.
- `blueprints/assessment.py` — V2 config, preview, completion, report, PDF, and appointment routes.
- `blueprints/admin/leads.py` — shared-admin lead, follow-up, retention, and appointment routes.
- `migrations/003_v2_catalog.sql` — catalog and versioned rule schema.
- `migrations/004_v2_assessment_leads.sql` — lead, consent, and V2 assessment columns.
- `migrations/005_v2_appointments_analytics.sql` — appointments and events.
- `seed_data/assessment_v2.json` — exact questions, options, branch weights, and reference lines.
- `seed_data/core_catalog_v2.json` — initial scenarios, packages, deliverables, ROI profiles.
- `templates/assessment/report.html` — session-protected HTML report.
- `templates/assessment/report_pdf.html` — print-specific report using the same snapshot.
- `templates/admin/leads.html`, `templates/admin/lead_detail.html`, `templates/admin/appointments.html`, `templates/admin/data_requests.html` — minimal operational and privacy-request views.
- `static/css/assessment.css`, `static/css/report.css` — functional wizard/report styles.
- `static/js/assessment.js` — six-step state machine and submissions.
- `tests/test_v2_migrations.py`, `tests/test_assessment_catalog.py`, `tests/test_scoring.py`, `tests/test_matching.py`, `tests/test_roi.py`, `tests/test_reporting.py`, `tests/test_assessment_completion.py`, `tests/test_assessment_v2_api.py`, `tests/test_assessment_wizard.py`, `tests/test_report_access.py`, `tests/test_appointments.py`, `tests/test_analytics.py`, `tests/test_lead_operations.py`, `tests/test_core_journey.py`.

Modify:

- `app.py` — register the V2 assessment blueprint and configuration.
- `models.py` — seed published V2 defaults after migrations.
- `blueprints/public.py` — remove only the old `/assessment` page handler after replacement is covered.
- `blueprints/api.py` — preserve the legacy assessment adapter.
- `blueprints/admin/__init__.py` — register the focused lead/appointment route module.
- `templates/assessment.html` — replace inline V0.2 questionnaire with the V2 shell.
- `templates/base.html` — add page CSS/JS blocks only if required by the new shell.
- `templates/components/admin_navigation.html` — add leads and appointments.
- `security.py` — public CSRF checks, V2 rate-limit buckets, and audit-safe event helpers.
- `validation.py` — mobile, UUID idempotency key, ISO date, and allowlisted code validation.
- `manage.py` — add expired-lead purge command.
- `requirements.txt` — add `weasyprint>=69,<70`.
- `docs/deployment/security-and-service.md` — document PDF runtime packages and the Stage 7 preflight command.

---

### Task 1: Add the V2 database schema without losing V0.2 rows

**Files:**
- Create: `migrations/003_v2_catalog.sql`
- Create: `migrations/004_v2_assessment_leads.sql`
- Create: `migrations/005_v2_appointments_analytics.sql`
- Create: `tests/test_v2_migrations.py`
- Modify: `tests/test_app_factory_and_migrations.py`

**Interfaces:**
- Consumes: `models.init_db() -> None`, `migrations.apply_migrations(connection) -> None`.
- Produces: versioned catalog, V2 assessment, lead, appointment, and analytics tables used by every later task.

- [ ] **Step 1: Write failing migration tests**

```python
def test_v2_migrations_preserve_legacy_assessment_and_create_core_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "DB_PATH", str(tmp_path / "platform.db"))
    models.init_db()
    db = models.get_db()
    db.execute(
        "INSERT INTO assessments (company_name, contact_email, scores, result) "
        "VALUES (?,?,?,?)",
        ("旧企业", "legacy@example.invalid", '{"legacy": 1}', "starter"),
    )
    db.commit()
    models.init_db()
    versions = [row[0] for row in db.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )]
    columns = {row[1] for row in db.execute("PRAGMA table_info(assessments)")}
    assert versions == [
        "001_initial", "002_security", "003_v2_catalog",
        "004_v2_assessment_leads", "005_v2_appointments_analytics",
    ]
    assert {
        "submission_key", "lead_id", "rule_version_id", "branch_code",
        "subbranch_code", "department_code", "company_size_code",
        "answers_json", "dimension_scores_json", "overall_score",
        "maturity_code", "report_snapshot_json", "attribution_json", "completed_at",
    } <= columns
    assert db.execute("SELECT company_name FROM assessments").fetchone()[0] == "旧企业"
```

Also assert these tables exist: `industries`, `industry_branches`, `departments`, `scenarios`, `scenario_branches`, `scenario_departments`, `service_deliverables`, `scenario_services`, `assessment_versions`, `assessment_questions`, `assessment_options`, `industry_benchmarks`, `roi_option_ranges`, `scenario_roi_profiles`, `roi_estimates`, `leads`, `lead_consents`, `lead_status_history`, `lead_followups`, `data_subject_requests`, `appointments`, and `analytics_events`.

- [ ] **Step 2: Run the migration tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_migrations.py tests/test_app_factory_and_migrations.py -q`

Expected: FAIL because migrations 003—005 and V2 columns do not exist.

- [ ] **Step 3: Implement the migrations**

`003_v2_catalog.sql` creates catalog/rule tables with foreign keys, unique stable codes, `status CHECK(status IN ('draft','published','archived'))`, and immutable version identifiers.

`004_v2_assessment_leads.sql` creates:

```sql
CREATE TABLE leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    phone_normalized TEXT,
    email TEXT,
    wechat TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    owner_text TEXT,
    source TEXT,
    next_followup_at TEXT,
    last_effective_followup_at TEXT,
    retention_expires_at TEXT,
    anonymized_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE UNIQUE INDEX uq_active_lead_phone
ON leads(phone_normalized) WHERE phone_normalized IS NOT NULL;
```

Add V2 columns to `assessments`, then create a unique index on non-null `submission_key`. Keep all legacy columns.

`004_v2_assessment_leads.sql` also creates consent rows with policy version/time/source/identity hash, `roi_estimates` linked one-to-one to a V2 assessment, and `data_subject_requests` with request types `access/correction/withdrawal/deletion`, statuses `received/verifying/completed/rejected`, channel, requested time, resolution note, completion time, and admin audit timestamps. `005_v2_appointments_analytics.sql` creates appointment states `pending/confirmed/completed/cancelled` and analytics events with no contact columns; add a partial unique index for each non-null `(assessment_id, event_name)` server-critical event so retries cannot duplicate it.

- [ ] **Step 4: Run migration tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_v2_migrations.py tests/test_app_factory_and_migrations.py -q`

Expected: PASS; repeated `models.init_db()` preserves the legacy row.

- [ ] **Step 5: Commit**

```bash
git add migrations tests/test_v2_migrations.py tests/test_app_factory_and_migrations.py
git commit -m "feat: add v2 assessment and lead schema"
```

---

### Task 2: Seed the exact published assessment and starter catalog

**Files:**
- Create: `seed_data/assessment_v2.json`
- Create: `seed_data/core_catalog_v2.json`
- Create: `assessment/contracts.py`
- Create: `assessment/__init__.py`
- Create: `assessment_repository.py`
- Create: `tests/test_assessment_catalog.py`
- Modify: `models.py`

**Interfaces:**
- Consumes: V2 tables from Task 1.
- Produces: `load_published_catalog(branch_code: str) -> AssessmentCatalog`, `get_scenarios() -> tuple[Scenario, ...]`, and `get_service_packages() -> tuple[ServicePackage, ...]`.

Use frozen dataclasses:

```python
@dataclass(frozen=True)
class QuestionOption:
    code: str
    label: str
    score: int

@dataclass(frozen=True)
class Question:
    code: str
    dimension: str
    prompt: str
    options: tuple[QuestionOption, ...]

@dataclass(frozen=True)
class AssessmentProfile:
    branch_code: str
    subbranch_code: str
    department_code: str
    company_size_code: str
    pain_codes: tuple[str, ...]
    answers: Mapping[str, str]
    roi_choices: Mapping[str, str]

@dataclass(frozen=True)
class AssessmentCatalog:
    version_id: int
    version_code: str
    subbranch_codes: tuple[str, ...]
    department_codes: tuple[str, ...]
    pain_codes: tuple[str, ...]
    questions: tuple[Question, ...]
    branch_weights: Mapping[str, Mapping[str, int]]
    reference_lines: Mapping[str, Mapping[str, int]]

@dataclass(frozen=True)
class Scenario:
    code: str
    category_code: str
    branch_codes: tuple[str, ...]
    department_codes: tuple[str, ...]
    pain_codes: tuple[str, ...]
    minimum_scores: Mapping[str, int]
    integration_level: str
    budget_codes: tuple[str, ...]
    min_weeks: int
    max_weeks: int
    efficiency: tuple[Decimal, Decimal, Decimal]
    loss_improvement: tuple[Decimal, Decimal, Decimal]
    annual_support_rate: tuple[Decimal, Decimal, Decimal]
    risk_codes: tuple[str, ...]
    service_code: str
    sort_order: int
    fallback_only: bool = False

@dataclass(frozen=True)
class ServicePackage:
    code: str
    category: str
    public_name: str
    min_budget: Decimal
    max_budget: Decimal
    min_weeks: int
    max_weeks: int
    deliverables: tuple[str, ...]
    implementation_steps: tuple[str, ...]
    prerequisites: tuple[str, ...]
    not_included: tuple[str, ...]
    acceptance: tuple[str, ...]
    support_days: int
```

Seed exactly these 12 scored question IDs with four ordered option codes `level_0` through `level_3`, scoring 0—3:

| ID | Prompt | Level progression |
|---|---|---|
| `business_value_frequency` | 这个问题出现得有多频繁？ | 每月少量 → 每周 → 每天 → 每天多次且持续影响 |
| `business_value_scope` | 这个问题影响多少人或环节？ | 个别人 → 小组 → 整个部门 → 多部门或客户 |
| `process_documentation` | 当前流程是否有统一标准？ | 依赖个人经验 → 有零散说明 → 有统一 SOP → 有指标并持续优化 |
| `process_stability` | 相同任务的处理方式是否稳定？ | 经常变化 → 例外较多 → 大部分稳定 → 高度标准化 |
| `data_availability` | 完成任务所需数据在哪里？ | 个人或纸面 → 分散文件 → 可从系统导出 → 集中且结构化 |
| `data_quality` | 关键数据质量如何？ | 缺失严重 → 需大量整理 → 基本一致 → 完整且持续维护 |
| `systems_foundation` | 当前主要使用什么工具？ | 纸面/聊天 → Excel/单机工具 → 核心业务系统 → 多系统有接口 |
| `systems_automation` | 当前自动化程度如何？ | 全人工 → 模板/宏辅助 → 局部自动化 → 自动运行且可监控 |
| `organization_owner` | 是否有明确负责人和配合资源？ | 没有 → 兼职负责人 → 部门支持 → 跨部门团队 |
| `organization_adoption` | 团队对使用 AI 的准备如何？ | 明显抵触 → 观望 → 愿意试点 → 已有成功经验 |
| `delivery_budget` | 可接受的首期投入？ | 暂无预算 → 5 万内 → 5—20 万 → 20 万以上 |
| `delivery_timeline` | 项目目标和时间安排是否明确？ | 只希望马上见效 → 有方向但无资源 → 1—3 月目标明确 → 分阶段且有验收指标 |

Seed branch weights in dimension order `business_value/process/data/systems/organization/delivery`:

| Branch | Weights |
|---|---|
| `manufacturing` | 20/20/20/15/10/15 |
| `retail` | 25/15/20/15/10/15 |
| `professional_knowledge` | 25/20/15/10/15/15 |
| `software_creative` | 25/15/15/15/15/15 |

Seed platform readiness reference lines in the same dimension order, with public label `平台建议就绪参考线` and never `行业平均`:

| Branch | Reference lines |
|---|---|
| `manufacturing` | 60/55/55/50/50/55 |
| `retail` | 60/55/60/60/50/55 |
| `professional_knowledge` | 60/60/55/50/55/55 |
| `software_creative` | 60/55/55/60/55/55 |

Seed pain codes:

- Manufacturing: `knowledge_search`, `quality_inspection`, `equipment_maintenance`, `production_reporting`, `scheduling`, `inventory_supply`, `quotation_service`, `office_documents`.
- Retail: `customer_service`, `marketing_content`, `member_operations`, `inventory_replenishment`, `sales_analysis`, `pricing_selection`, `supply_reconciliation`, `office_knowledge`.
- Professional knowledge: `document_search`, `proposal_drafting`, `project_delivery`, `contract_review`, `client_service`, `lead_followup`, `billing_reconciliation`, `talent_knowledge`.
- Software creative: `requirements`, `content_creation`, `project_delivery`, `quality_review`, `customer_support`, `marketing_sales`, `knowledge_docs`, `operations_analysis`.

The pain interaction requires 1—3 selected codes from the chosen branch.

Seed exact subbranches:

| Branch | Subbranch codes |
|---|---|
| `manufacturing` | `discrete_manufacturing`, `process_manufacturing`, `equipment_manufacturing`, `consumer_goods_manufacturing` |
| `retail` | `ecommerce`, `chain_retail`, `brand_direct`, `wholesale_distribution` |
| `professional_knowledge` | `consulting`, `tax_accounting`, `legal`, `human_resources` |
| `software_creative` | `software`, `design`, `advertising`, `marketing_services` |

Seed company-size codes `under_50`, `50_200`, `200_500`, and `500_plus`. Seed these branch-specific department codes:

| Branch | Department codes |
|---|---|
| `manufacturing` | `production`, `quality`, `equipment`, `supply_chain`, `sales_service`, `finance_hr` |
| `retail` | `merchandising`, `store_operations`, `supply_chain`, `marketing`, `customer_service`, `finance_hr` |
| `professional_knowledge` | `delivery`, `knowledge_research`, `client_growth`, `contracts_risk`, `operations`, `people` |
| `software_creative` | `product_delivery`, `design_content`, `engineering`, `marketing_sales`, `customer_success`, `operations` |

Seed ROI bands with these `(low, mid, high)` values:

```python
HEADCOUNT = {"1_5": (1, 3, 5), "6_20": (6, 13, 20),
             "21_50": (21, 35, 50), "50_plus": (51, 75, 100)}
MONTHLY_HOURS = {"under_20": (5, 10, 20), "20_80": (20, 50, 80),
                 "80_160": (80, 120, 160), "160_plus": (160, 200, 240)}
MONTHLY_COST = {"under_8000": (5000, 6500, 8000),
                "8000_15000": (8000, 11500, 15000),
                "15000_30000": (15000, 22500, 30000),
                "30000_plus": (30000, 40000, 50000)}
LOSS_FACTOR = {"rare": (0, .02, .05), "normal": (.05, .10, .15),
               "high": (.15, .25, .35), "severe": (.35, .50, .70)}
BUDGET = {"under_50000": (20000, 35000, 50000),
          "50000_200000": (50000, 125000, 200000),
          "200000_500000": (200000, 350000, 500000),
          "500000_plus": (500000, 750000, 1000000)}
```

Seed these 12 scenarios plus the fallback. Minimums are ordered `business/process/data/systems/organization/delivery`; coefficient triples are `(conservative, midpoint, ideal)`. The `annual_support_rate` triple is multiplied by the matching low/mid/high initial investment:

| Code / category | Branch / departments | Pain codes | Minimums | Integration | Budget codes | Weeks | Efficiency / loss improvement / annual support rate | Risk codes | Service |
|---|---|---|---|---|---|---:|---|---|---|
| `mfg_knowledge_assistant` / knowledge_content | manufacturing / equipment, production, finance_hr | knowledge_search, equipment_maintenance, office_documents | 20/20/20/20/20/20 | low | under_50000, 50000_200000 | 4—8 | .15/.25/.35 / .05/.10/.15 / .08/.10/.12 | source_quality, access_control, adoption | `knowledge_assistant_pilot` |
| `mfg_quality_inspection` / vision_quality | manufacturing / quality, production | quality_inspection | 50/50/50/50/40/40 | high | 200000_500000, 500000_plus | 12—24 | .10/.20/.30 / .15/.30/.45 / .12/.15/.20 | sample_quality, false_positive, equipment_integration | `industry_integration` |
| `mfg_operations_reporting` / data_insight | manufacturing / production, supply_chain | production_reporting, scheduling, inventory_supply | 40/40/40/30/30/30 | medium | 50000_200000, 200000_500000 | 8—12 | .20/.35/.50 / .05/.12/.20 / .10/.12/.15 | metric_definition, source_consistency, data_refresh | `data_insight` |
| `retail_ai_service` / customer_growth | retail / customer_service, store_operations | customer_service, member_operations | 30/30/30/30/30/30 | medium | 50000_200000 | 6—10 | .20/.35/.50 / .05/.10/.20 / .08/.10/.12 | response_accuracy, escalation, adoption | `customer_growth_pilot` |
| `retail_marketing_content` / customer_growth | retail / marketing, merchandising | marketing_content, pricing_selection | 20/30/20/20/20/20 | low | 50000_200000 | 4—8 | .20/.40/.60 / .02/.05/.10 / .08/.10/.12 | brand_consistency, approval_flow, content_compliance | `customer_growth_pilot` |
| `retail_inventory_insight` / data_insight | retail / supply_chain, merchandising, store_operations | inventory_replenishment, supply_reconciliation, sales_analysis | 50/40/50/40/40/40 | high | 200000_500000, 500000_plus | 12—20 | .10/.20/.30 / .10/.25/.40 / .12/.15/.20 | source_consistency, forecast_error, system_integration | `data_insight` |
| `pro_document_knowledge` / knowledge_content | professional_knowledge / knowledge_research, delivery, people | document_search, talent_knowledge, client_service | 20/20/20/20/20/20 | low | under_50000, 50000_200000 | 4—8 | .20/.35/.50 / .02/.05/.10 / .08/.10/.12 | source_quality, confidentiality, answer_scope | `knowledge_assistant_pilot` |
| `pro_delivery_drafting` / workflow_automation | professional_knowledge / delivery, operations | proposal_drafting, project_delivery, billing_reconciliation | 30/40/20/20/20/20 | low | 50000_200000 | 6—10 | .20/.40/.60 / .05/.10/.20 / .08/.12/.15 | template_quality, human_review, exception_handling | `workflow_automation` |
| `pro_contract_review` / workflow_automation | professional_knowledge / contracts_risk, delivery | contract_review | 40/50/40/30/40/40 | medium | 50000_200000, 200000_500000 | 8—12 | .15/.25/.35 / .10/.20/.30 / .10/.12/.15 | legal_scope, confidentiality, human_review | `workflow_automation` |
| `creative_content_workflow` / knowledge_content | software_creative / design_content, marketing_sales | content_creation, marketing_sales | 20/30/20/20/20/20 | low | 50000_200000 | 4—8 | .20/.40/.60 / .02/.05/.10 / .08/.10/.12 | brand_consistency, intellectual_property, approval_flow | `customer_growth_pilot` |
| `software_support_knowledge` / knowledge_content | software_creative / customer_success, engineering | customer_support, knowledge_docs | 30/30/30/30/30/30 | medium | 50000_200000 | 6—10 | .20/.35/.50 / .05/.10/.20 / .08/.10/.12 | source_freshness, escalation, access_control | `knowledge_assistant_pilot` |
| `project_delivery_automation` / project_management | professional_knowledge, software_creative / delivery, operations, product_delivery, engineering | project_delivery, requirements, quality_review, operations_analysis | 40/50/40/50/40/40 | high | 200000_500000, 500000_plus | 12—20 | .15/.30/.45 / .10/.20/.35 / .12/.15/.20 | process_variance, integration, change_management | `industry_integration` |
| `data_process_foundation` / foundation | manufacturing, retail, professional_knowledge, software_creative / every seeded department | fallback only | 0/0/0/0/0/0 | low | under_50000, 50000_200000, 200000_500000, 500000_plus | 2—4 | .05/.10/.15 / .02/.05/.08 / .00/.05/.08 | owner_availability, data_inventory | `foundation_workshop` |

The contract represents branch and pain links as tuples, all coefficients as decimal strings, and `data_process_foundation.fallback_only=true`; it never participates in ordinary ranking.

Each service package's applicable branches, departments, maturity levels, pain codes, and scenarios are the union of its published scenario links. Store these exact implementation steps and exclusions:

- `foundation_workshop`: steps `资料准备 → 两次业务工作坊 → 基线与优先级整理 → 90 天计划评审`; excludes software development, system integration, data cleansing execution.
- `knowledge_assistant_pilot`: steps `范围与权限确认 → 资料接入 → 检索与回答配置 → 30 题评测 → 培训与试运行`; excludes source-document creation, unrestricted internet answers, custom core-system integration.
- `customer_growth_pilot`: steps `流程与目标确认 → 话术审批 → 助手和事件配置 → UAT → 培训与试运行`; excludes media spend, guaranteed conversion results, unapproved automated outreach.
- `workflow_automation`: steps `流程冻结 → 接口与异常设计 → 流程配置 → 用例测试 → 培训和上线`; excludes unstable processes, unlisted system interfaces, removal of manual fallback.
- `data_insight`: steps `KPI 确认 → 数据映射 → 数据集与看板配置 → 对账 → 培训和验收`; excludes source-system repair, historical data reconstruction, unagreed predictive models.
- `industry_integration`: steps `架构与范围确认 → 接口联调 → 场景配置 → 安全检查 → UAT → 培训上线`; excludes unlisted connectors, production infrastructure procurement, guaranteed business outcomes.

Seed six published service packages. Every package also carries the public disclaimer “参考预算，最终范围和报价以需求确认结果为准”:

| Code / category / public name | Budget | Weeks | Deliverables | Client prerequisites | Acceptance | Support |
|---|---:|---:|---|---|---|---|
| `foundation_workshop` / foundation / AI 就绪基础工作坊 | ¥20k—¥50k | 2—4 | 流程现状基线、数据清单、场景优先级矩阵、90 天计划、工作坊报告 | 明确负责人、参加两次 90 分钟工作坊、提供脱敏样例文件 | 负责人书面确认现状基线、优先级和下一步计划 | 15 天内一次复盘会 |
| `knowledge_assistant_pilot` / pilot / 企业知识助手试点 | ¥50k—¥100k | 4—8 | 资料清单、权限方案、可检索知识库、30 题评测集、管理员培训 | 明确负责人、批准资料来源和访问规则 | 约定评测集通过率 ≥80%，且不回答未授权资料内容 | 30 天 |
| `customer_growth_pilot` / pilot / 客户增长助手试点 | ¥80k—¥150k | 4—10 | 服务或营销流程图、审核话术模板、配置助手、转化看板、用户培训 | 明确负责人、批准文案、提供脱敏对话或活动数据 | 约定的前三项流程通过 UAT，且看板记录约定漏斗事件 | 30 天 |
| `workflow_automation` / standard / 流程自动化交付包 | ¥100k—¥200k | 6—12 | 流程图、自动化流程、异常队列、执行日志、人工兜底、验收用例、培训 | 稳定 SOP、脱敏样例、系统访问负责人 | 约定正常用例通过率 ≥95%，全部异常进入人工队列 | 30 天 |
| `data_insight` / standard / 数据洞察交付包 | ¥100k—¥250k | 8—16 | KPI 字典、数据源映射、治理数据集、看板、预警规则、培训、验收报告 | KPI 负责人、可导出源数据、对账样例 | 看板 KPI 与签字确认样例在约定误差内一致 | 30 天 |
| `industry_integration` / integration / 行业场景集成交付包 | ¥200k—¥500k | 12—24 | 方案架构、约定接口、配置场景、安全审查、UAT、培训 | 业务发起人、系统负责人、测试环境和接口权限 | 签署 UAT 无严重缺陷，约定接口通过重试、审计和权限测试 | 60 天 |

- [ ] **Step 1: Write failing catalog tests**

```python
def test_published_catalog_has_four_branches_twelve_questions_and_exact_weights():
    catalog = assessment_repository.load_published_catalog("manufacturing")
    assert len(catalog.questions) == 12
    assert catalog.subbranch_codes == (
        "discrete_manufacturing", "process_manufacturing",
        "equipment_manufacturing", "consumer_goods_manufacturing",
    )
    assert sum(catalog.branch_weights["manufacturing"].values()) == 100
    assert catalog.reference_lines["manufacturing"]["business_value"] == 60
    assert [option.score for option in catalog.questions[0].options] == [0, 1, 2, 3]
```

Assert every scenario references existing branch/department/service codes; every ordinary scenario has category, pain, risk, minimum, budget, timeline, efficiency, loss-improvement, and annual-support values; every package has at least one deliverable, step, prerequisite, exclusion, acceptance rule, and support value; and every ROI band has ordered low ≤ mid ≤ high values.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_assessment_catalog.py -q`

Expected: FAIL because seed files, contracts, and repository functions do not exist.

- [ ] **Step 3: Implement seed loading and typed reads**

Use `INSERT OR IGNORE` only for stable codes and never overwrite a published version. `models.init_db()` calls `seed_v2_defaults(connection)` after migrations; the seeder returns immediately if version code `v2.0-2026-08-19` exists.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_assessment_catalog.py tests/test_v2_migrations.py -q`

Expected: PASS with exactly one published V2 rule version after repeated initialization.

- [ ] **Step 5: Commit**

```bash
git add assessment assessment_repository.py seed_data models.py tests/test_assessment_catalog.py
git commit -m "feat: seed versioned assessment and service catalog"
```

---

### Task 3: Implement six-dimension scoring and maturity

**Files:**
- Create: `assessment/scoring.py`
- Create: `tests/test_scoring.py`
- Modify: `assessment/contracts.py`

**Interfaces:**
- Consumes: `AssessmentCatalog`, `AssessmentProfile`.
- Produces: `score_assessment(catalog, profile) -> ScoreResult`, where `ScoreResult` contains `dimension_scores`, `overall_score`, `maturity_code`, `strongest_dimension`, and `weakest_dimension`.

- [ ] **Step 1: Write parameterized failing tests**

```python
@pytest.mark.parametrize(
    ("score", "level"),
    [(0, "explore"), (39, "explore"), (40, "pilot"), (59, "pilot"),
     (60, "scale"), (79, "scale"), (80, "collaborate"), (100, "collaborate")],
)
def test_maturity_boundaries(score, level):
    assert maturity_for_score(score) == level

def test_manufacturing_weighted_score_uses_approved_weights(catalog, profile):
    result = score_assessment(catalog, profile)
    assert result.dimension_scores["business_value"] == 100
    assert result.dimension_scores["organization"] == 0
    assert result.overall_score == 65
```

Also test missing/unknown answers raise `AssessmentInputError`, all-zero/all-three answers, stable strongest/weakest tie-breaking by the spec dimension order, and weight totals other than 100 fail closed.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scoring.py -q`

Expected: FAIL because `score_assessment` and `maturity_for_score` do not exist.

- [ ] **Step 3: Implement pure scoring**

```python
DIMENSION_ORDER = (
    "business_value", "process", "data", "systems", "organization", "delivery"
)

def dimension_score(scores):
    return round(sum(scores) / (len(scores) * 3) * 100)

def maturity_for_score(score):
    if score < 40:
        return "explore"
    if score < 60:
        return "pilot"
    if score < 80:
        return "scale"
    return "collaborate"
```

Keep the module free of Flask and database imports.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scoring.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add assessment/scoring.py assessment/contracts.py tests/test_scoring.py
git commit -m "feat: add deterministic readiness scoring"
```

---

### Task 4: Implement scenario gates, ranking, and service matching

**Files:**
- Create: `assessment/matching.py`
- Create: `tests/test_matching.py`
- Modify: `assessment/contracts.py`

**Interfaces:**
- Consumes: `AssessmentProfile`, `ScoreResult`, scenario and service tuples from Task 2.
- Produces: `match_scenarios(profile, scores, scenarios, services, limit=3) -> tuple[ScenarioMatch, ...]`.

- [ ] **Step 1: Write failing matching tests**

```python
def test_low_data_blocks_advanced_agent_and_returns_foundation():
    scores = score_result(data=33, process=50, systems=67, delivery=67)
    matches = match_scenarios(profile("manufacturing", "scheduling"), scores, scenarios, services)
    assert all(match.scenario.code != "project_delivery_automation" for match in matches)
    assert matches[0].scenario.code == "data_process_foundation"

def test_match_score_uses_35_20_25_10_10_components():
    match = match_scenarios(fully_matching_profile, ready_scores, scenarios, services)[0]
    assert match.total_score == 100
    assert match.components == {
        "pain": 35, "industry": 20, "readiness": 25, "budget": 10, "timeline": 10
    }
```

Test systems < 40 blocks high-integration scenarios, delivery < 40 restricts packages to `foundation` or `pilot`, ties resolve by scenario `sort_order` then stable code, and fewer than three eligible scenarios do not get padded with unrelated content.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_matching.py -q`

Expected: FAIL because matching functions do not exist.

- [ ] **Step 3: Implement gates and weighted components**

```python
COMPONENT_MAX = {"pain": 35, "industry": 20, "readiness": 25,
                 "budget": 10, "timeline": 10}

def match_scenarios(profile, scores, scenarios, services, limit=3):
    eligible = [scenario for scenario in scenarios if passes_gates(scenario, scores)]
    ranked = sorted(
        (build_match(scenario, profile, scores, services) for scenario in eligible),
        key=lambda item: (-item.total_score, item.scenario.sort_order, item.scenario.code),
    )
    accepted = tuple(item for item in ranked if item.total_score >= 60)[:limit]
    return accepted or (foundation_match(services),)
```

Apply these rules exactly:

- A candidate must link to `profile.branch_code`, match or exceed all six minimum dimension scores, and must not have `fallback_only=true`.
- `integration=high` additionally requires systems ≥ 40. When delivery < 40, only `foundation` and `pilot` service categories are eligible.
- Pain contributes 35 when at least one selected pain code is linked, otherwise 0. Industry contributes 20 for the required branch link.
- Readiness contributes `round(25 * mean(min(actual/minimum, 1)))` across six dimensions; a zero minimum has ratio 1.
- Budget contributes 10 when `roi_choices["budget"]` appears in the scenario budget codes, 5 when it is immediately adjacent in `under_50000 → 50000_200000 → 200000_500000 → 500000_plus`, otherwise 0.
- Timeline reads the `delivery_timeline` answer. `level_0` gives 5 only when maximum weeks ≤ 4; `level_1` gives 5 only when maximum weeks ≤ 8; `level_2` gives 10 when maximum weeks ≤ 12 and 5 otherwise; `level_3` gives 10. Unknown timeline codes fail validation before matching.
- Keep ordinary matches with total ≥ 60, maximum three. If none remain, return only `data_process_foundation` with reason code `foundation_required`; do not mix the fallback with ordinary matches.

Every match includes machine-readable reason codes and user-facing reasons selected from controlled templates, never generated free text.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_matching.py tests/test_scoring.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add assessment/matching.py assessment/contracts.py tests/test_matching.py
git commit -m "feat: match scenarios and service packages"
```

---

### Task 5: Implement three-band ROI calculations

**Files:**
- Create: `assessment/roi.py`
- Create: `tests/test_roi.py`
- Modify: `assessment/contracts.py`

**Interfaces:**
- Consumes: five ROI choice codes, the selected scenario ROI profile, and matched service package costs.
- Produces: `calculate_roi(choices, option_ranges, roi_profile, service_package) -> RoiResult` with `conservative`, `midpoint`, and `ideal` bands.

Add these contracts:

```python
@dataclass(frozen=True)
class RoiBand:
    band_code: str
    current_annual_cost: Decimal
    labor_savings: Decimal
    loss_savings: Decimal
    annual_savings: Decimal
    initial_investment: Decimal
    annual_support: Decimal
    payback_months: Decimal | None
    three_year_support: Decimal
    three_year_net: Decimal

@dataclass(frozen=True)
class RoiResult:
    conservative: RoiBand
    midpoint: RoiBand
    ideal: RoiBand
```

- [ ] **Step 1: Write failing formula tests**

```python
def test_midpoint_roi_uses_174_hour_loaded_cost_and_three_year_formula():
    result = calculate_roi(MID_CHOICES, ranges, profile, service)
    expected_hourly = 11500 / 174
    expected_current = 13 * 50 * 12 * expected_hourly
    assert result.midpoint.current_annual_cost == round(expected_current, 2)
    assert result.midpoint.payback_months > 0
    assert result.midpoint.three_year_net == (
        result.midpoint.annual_savings * 3
        - result.midpoint.initial_investment
        - result.midpoint.three_year_support
    )
```

Also test annual savings are ordered conservative ≤ midpoint ≤ ideal, open ranges use the configured finite upper bound, zero savings returns `payback_months=None`, negative outputs clamp only display savings to zero, and decimal calculations use `Decimal` rather than binary floats. Investment uses service minimum, arithmetic midpoint, and maximum for the three bands; annual support equals that investment multiplied by the scenario's matching annual-support-rate value.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_roi.py -q`

Expected: FAIL because ROI contracts and calculator do not exist.

- [ ] **Step 3: Implement Decimal-based calculations**

```python
LOADED_MONTH_HOURS = Decimal("174")
MONEY = Decimal("0.01")

def money(value):
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)

def calculate_band(band_code, headcount, monthly_hours, monthly_cost, loss_factor,
                   efficiency, loss_improvement, investment, support_rate):
    hourly = monthly_cost / LOADED_MONTH_HOURS
    current = headcount * monthly_hours * Decimal(12) * hourly
    labor_savings = current * efficiency
    loss_savings = current * loss_factor * loss_improvement
    annual_savings = max(Decimal(0), labor_savings + loss_savings)
    payback = None if annual_savings == 0 else investment / annual_savings * Decimal(12)
    annual_support = investment * support_rate
    net = annual_savings * Decimal(3) - investment - annual_support * Decimal(3)
    return RoiBand(
        band_code=band_code,
        current_annual_cost=money(current),
        labor_savings=money(labor_savings),
        loss_savings=money(loss_savings),
        annual_savings=money(annual_savings),
        initial_investment=money(investment),
        annual_support=money(annual_support),
        payback_months=None if payback is None else payback.quantize(Decimal("0.1")),
        three_year_support=money(annual_support * Decimal(3)),
        three_year_net=money(net),
    )
```

Round currency to 2 decimal places internally and whole yuan for display. Round payback to 1 decimal month.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_roi.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add assessment/roi.py assessment/contracts.py tests/test_roi.py
git commit -m "feat: add range-based roi calculator"
```

---

### Task 6: Build immutable report snapshots and roadmaps

**Files:**
- Create: `assessment/reporting.py`
- Create: `tests/test_reporting.py`
- Modify: `assessment/contracts.py`

**Interfaces:**
- Consumes: profile, `ScoreResult`, scenario matches, `RoiResult`, rule version, and reference line.
- Produces: `build_report_snapshot(profile: AssessmentProfile, scores: ScoreResult, matches: tuple[ScenarioMatch, ...], roi: RoiResult, catalog: AssessmentCatalog) -> dict[str, object]` containing only JSON-serializable values and no contact PII.

- [ ] **Step 1: Write failing snapshot tests**

```python
def test_report_snapshot_contains_required_sections_and_no_contact_pii():
    snapshot = build_report_snapshot(profile, scores, matches, roi, catalog)
    assert snapshot["schema_version"] == "2.0"
    assert snapshot["rule_version"] == "v2.0-2026-08-19"
    assert len(snapshot["recommendations"]) <= 3
    assert [item["days"] for item in snapshot["roadmap_90_days"]] == [
        "1-15", "16-30", "31-60", "61-90"
    ]
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "phone" not in serialized
    assert "contact_name" not in serialized
```

Test explore-level reports do not promise first-year integration, collaborate-level reports prioritize cross-system optimization, strongest/weakest explanations come from controlled dimension templates, and the disclaimer is always present.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reporting.py -q`

Expected: FAIL because report builder does not exist.

- [ ] **Step 3: Implement the deterministic snapshot**

```python
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
```

Use the same snapshot for HTML and PDF. Include a `calculation_basis` section listing selected ROI bands and coefficients.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reporting.py tests/test_matching.py tests/test_roi.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add assessment/reporting.py assessment/contracts.py tests/test_reporting.py
git commit -m "feat: build immutable assessment reports"
```

---

### Task 7: Complete leads, consent, and assessments atomically

**Files:**
- Create: `lead_repository.py`
- Create: `analytics_repository.py`
- Create: `assessment_completion_service.py`
- Create: `tests/test_assessment_completion.py`
- Modify: `assessment_repository.py`
- Modify: `validation.py`

**Interfaces:**
- Consumes: validated `CompletionRequest` plus report computation from Tasks 3—6.
- Produces: `complete_assessment(request, identity_hash) -> CompletionResult(assessment_id, lead_id, created)` and `insert_server_event(db, event_name: str, assessment_id: int) -> None` for the two completion events.

- [ ] **Step 1: Write failing transactional and privacy tests**

```python
def test_completion_creates_lead_consent_assessment_and_snapshot(client_app):
    result = complete_assessment(valid_completion(), "hashed-ip")
    lead = fetch_lead(result.lead_id)
    assessment = fetch_assessment(result.assessment_id)
    assert lead.phone_normalized == "13800138000"
    assert assessment.lead_id == lead.id
    assert assessment.report_snapshot_json
    assert fetch_roi_estimate(assessment.id).rule_version_id == assessment.rule_version_id
    assert fetch_consent(lead.id).policy_version == "2026-08-19"

def test_same_phone_reuses_lead_but_keeps_each_assessment():
    first = complete_assessment(valid_completion(key=UUID_1), "ip")
    second = complete_assessment(valid_completion(key=UUID_2), "ip")
    assert first.lead_id == second.lead_id
    assert first.assessment_id != second.assessment_id
```

Also test the same idempotency key returns the existing result, a database failure rolls back every lead/consent/assessment/ROI/event write, consent false is rejected, invalid mobile/email/WeChat lengths are rejected, and logs/exceptions never include request values. Test that a resubmission reopens `not_progressing` to `pending_contact`, while a `won` record stays `won`, never regains a retention expiry, and is not returned to the ordinary lead queue.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_assessment_completion.py -q`

Expected: FAIL because repositories and completion service do not exist.

- [ ] **Step 3: Implement validation and one transaction**

```python
MOBILE_PATTERN = re.compile(r"^1[3-9]\d{9}$")
IDEMPOTENCY_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)

def complete_assessment(request, identity_hash):
    def operation(db):
        existing = assessment_repository.find_by_submission_key(db, request.submission_key)
        if existing:
            return CompletionResult(existing["id"], existing["lead_id"], False)
        lead_id = lead_repository.find_or_create(db, request.contact)
        lead_repository.record_consent(db, lead_id, request.consent, identity_hash)
        assessment_id = assessment_repository.insert_completed(db, lead_id, request)
        analytics_repository.insert_server_event(db, "assessment_completed", assessment_id)
        analytics_repository.insert_server_event(db, "lead_submitted", assessment_id)
        return CompletionResult(assessment_id, lead_id, True)
    return run_transaction(operation)
```

Set `retention_expires_at` to creation time plus 365 days for unconverted leads.

For a repeated normalized phone, update the latest explicitly submitted company/contact/email/WeChat values and create a new consent plus assessment. Preserve any active status; change only `not_progressing` to `pending_contact`. If status is `won`, preserve `won`, keep `retention_expires_at=NULL`, link the new assessment as customer activity, and exclude it from ordinary pending-contact filters.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_assessment_completion.py tests/test_validation_and_errors.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lead_repository.py analytics_repository.py assessment_repository.py assessment_completion_service.py validation.py tests/test_assessment_completion.py
git commit -m "feat: persist consented assessment leads"
```

---

### Task 8: Add V2 config, preview, and completion APIs

**Files:**
- Create: `blueprints/assessment.py`
- Create: `assessment_validation.py`
- Create: `tests/test_assessment_v2_api.py`
- Modify: `app.py`
- Modify: `blueprints/public.py`
- Modify: `blueprints/api.py`
- Modify: `security.py`

**Interfaces:**
- Produces:
  - `GET /api/v2/assessment/config/<branch_code>`
  - `POST /api/v2/assessment/preview`
  - `POST /api/v2/assessment/complete`
  - existing `POST /api/assessment` remains compatible.

Preview payload:

```json
{
  "schema_version": "2.0",
  "profile": {
    "branch_code": "manufacturing",
    "subbranch_code": "discrete_manufacturing",
    "department_code": "production",
    "company_size_code": "50_200",
    "pain_codes": ["production_reporting"]
  },
  "answers": {"business_value_frequency": "level_3"},
  "roi_choices": {
    "headcount": "6_20",
    "monthly_hours": "20_80",
    "monthly_cost": "8000_15000",
    "loss_factor": "normal",
    "budget": "50000_200000"
  }
}
```

Completion adds:

```json
{
  "submission_key": "550e8400-e29b-41d4-a716-446655440000",
  "assessment": {},
  "contact": {
    "company_name": "示例企业",
    "contact_name": "张先生",
    "phone": "13800138000",
    "email": "",
    "wechat": ""
  },
  "consent": {"accepted": true, "policy_version": "2026-08-19"},
  "attribution": {
    "source": "website_assessment",
    "utm_source": "",
    "utm_medium": "",
    "utm_campaign": ""
  }
}
```

- [ ] **Step 1: Write failing endpoint tests**

Assert config exposes no draft rules, preview returns only maturity/strength/weakness and not full recommendations, completion requires CSRF and consent, successful completion stores the assessment ID in Session and returns `report_url`/`pdf_url`, invalid codes return 400, attribution strings are limited to 100 characters and cannot contain contact fields, missing or internally inconsistent published rules return a generic recoverable 503 without creating rows, and rate limits are 60 previews/hour and 10 completions/hour per identity.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_assessment_v2_api.py -q`

Expected: FAIL with 404 for V2 endpoints.

- [ ] **Step 3: Implement the blueprint and safe validation**

Register `assessment_bp` in `create_app`. Add `require_public_csrf()` for completion and later appointment writes. Store accessible report IDs as a bounded Session list of the last five IDs:

```python
report_ids = list(session.get("assessment_report_ids", ()))
report_ids.append(result.assessment_id)
session["assessment_report_ids"] = report_ids[-5:]
```

Keep `/api/assessment` as a legacy adapter covered by existing tests. Do not let legacy rows access V2 reports.

Read privacy disclosure values from required configuration keys `PRIVACY_PROCESSOR_NAME`, `PRIVACY_CONTACT`, and `PRIVACY_POLICY_URL`; tests supply non-production values. The completion config/HTML states the processing purpose, required/optional data categories, 365-day unconverted-lead retention rule, anonymization behavior, and access/correction/withdrawal/deletion channel. Production Stage 7 must fail its preflight when any of the three configuration values is absent; the public application must not invent a legal-entity fallback.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_assessment_v2_api.py tests/test_smoke.py tests/test_rate_limits_and_audit.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add blueprints app.py assessment_validation.py security.py tests/test_assessment_v2_api.py
git commit -m "feat: expose v2 assessment APIs"
```

---

### Task 9: Replace the inline legacy questionnaire with the six-step wizard

**Files:**
- Create: `static/css/assessment.css`
- Create: `static/js/assessment.js`
- Create: `tests/test_assessment_wizard.py`
- Modify: `templates/assessment.html`
- Modify: `templates/base.html`

**Interfaces:**
- Consumes: V2 config/preview/completion APIs from Task 8.
- Produces: accessible, responsive browser flow that redirects to the returned report URL.

- [ ] **Step 1: Write failing template/source tests**

```python
def test_assessment_page_loads_external_wizard_assets(client):
    response = client.get("/assessment")
    page = BeautifulSoup(response.data, "html.parser")
    assert page.select_one('script[src="/static/js/assessment.js"]')
    assert page.select_one('link[href="/static/css/assessment.css"]')
    assert page.select_one("#assessment-live-status")["aria-live"] == "polite"
    assert b"const INDUSTRIES" not in response.data
```

Add source assertions that assessment JS uses `textContent`/DOM creation for server values, not `innerHTML`; uses `sessionStorage` only for non-contact assessment state; creates one UUID submission key; disables buttons during requests; and preserves answers after preview/completion failure.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_assessment_wizard.py -q`

Expected: FAIL because the current template still contains the inline V0.2 questionnaire.

- [ ] **Step 3: Implement the six-step state machine**

```javascript
const STEPS = ["profile", "pain", "value_process", "data_systems", "org_delivery", "roi"];
const state = {
  step: 0,
  branchCode: "",
  subbranchCode: "",
  departmentCode: "",
  companySizeCode: "",
  painCodes: [],
  answers: {},
  roiChoices: {},
  submissionKey: crypto.randomUUID(),
};
```

Render radio/multi-select cards with native inputs and labels. Support keyboard navigation, Back, Continue, error focus, progress text, refresh restore, and reduced-motion preferences. Enforce one subbranch from the selected branch and 1—3 pain codes. Capture only `utm_source`, `utm_medium`, and `utm_campaign` from the initial query string, cap each at 100 characters, and keep them with non-contact wizard state. After preview, show only maturity, strongest dimension, weakest dimension, and the contact gate. The contact gate displays the configured privacy summary/link and an unchecked consent checkbox; it never stores contact fields in `sessionStorage`. Clear `sessionStorage` after successful completion.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_assessment_wizard.py tests/test_smoke.py -q`

Expected: PASS; all existing public smoke tests remain green.

- [ ] **Step 5: Commit**

```bash
git add templates/assessment.html templates/base.html static/css/assessment.css static/js/assessment.js tests/test_assessment_wizard.py
git commit -m "feat: build six-step assessment wizard"
```

---

### Task 10: Render session-only HTML and PDF reports

**Files:**
- Create: `report_pdf.py`
- Create: `templates/assessment/report.html`
- Create: `templates/assessment/report_pdf.html`
- Create: `static/css/report.css`
- Create: `tests/test_report_access.py`
- Modify: `blueprints/assessment.py`
- Modify: `requirements.txt`
- Modify: `docs/deployment/security-and-service.md`

**Interfaces:**
- Produces:
  - `GET /assessment/report/<int:assessment_id>`
  - `GET /assessment/report/<int:assessment_id>/pdf`
  - `render_pdf(html: str, base_url: str) -> bytes`.

- [ ] **Step 1: Write failing access and PDF tests**

```python
def test_report_requires_current_session_access(client, completed_assessment):
    allowed = client.get(f"/assessment/report/{completed_assessment.id}")
    other = client.application.test_client().get(
        f"/assessment/report/{completed_assessment.id}"
    )
    assert allowed.status_code == 200
    assert other.status_code == 404

def test_pdf_response_uses_same_snapshot(client, completed_assessment, monkeypatch):
    monkeypatch.setattr(report_pdf, "render_pdf", lambda html, base_url: b"%PDF-test")
    response = client.get(f"/assessment/report/{completed_assessment.id}/pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF")
```

Also test no-store private cache headers, PDF renderer failure returns a safe 503 without deleting the report, HTML contains six scores/reference lines/recommendations/ROI/roadmaps/packages/disclaimer, and report templates do not expose contact PII.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_report_access.py -q`

Expected: FAIL with 404 and missing renderer.

- [ ] **Step 3: Implement HTML and WeasyPrint adapter**

```python
def render_pdf(html, base_url):
    from weasyprint import HTML
    return HTML(string=html, base_url=base_url).write_pdf()
```

Use an accessible score table alongside the radar SVG. Set `Cache-Control: no-store, private`, `Pragma: no-cache`, and `Content-Disposition: attachment; filename="ai-readiness-report-<id>.pdf"`.

Document these production packages from the official WeasyPrint 69 guidance: `libpango-1.0-0`, `libharfbuzz0b`, `libpangoft2-1.0-0`, `libharfbuzz-subset0`, and `fonts-noto-cjk`. Keep `python -m weasyprint --info` as a mandatory Stage 7 preflight command; do not add it to systemd `ExecStartPre`, so a PDF runtime problem cannot prevent the HTML application from starting.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_report_access.py tests/test_reporting.py -q`

Expected: PASS. On a Linux/WSL environment with Pango installed, additionally run `.venv/bin/python -m weasyprint --info`.

- [ ] **Step 5: Commit**

```bash
git add report_pdf.py templates/assessment static/css/report.css blueprints/assessment.py requirements.txt docs/deployment/security-and-service.md tests/test_report_access.py
git commit -m "feat: generate private html and pdf reports"
```

---

### Task 11: Add appointment intent submission and transitions

**Files:**
- Create: `appointment_repository.py`
- Create: `tests/test_appointments.py`
- Modify: `blueprints/assessment.py`
- Modify: `assessment_validation.py`
- Modify: `templates/assessment/report.html`

**Interfaces:**
- Produces: `POST /api/v2/appointments`, `create_appointment(db, assessment_id: int, submission_key: str, preferred_date: date, time_slot: str, note: str) -> int`, and `transition_appointment(db, appointment_id: int, new_status: str) -> None`.

- [ ] **Step 1: Write failing appointment tests**

Valid payload:

```json
{
  "assessment_id": 42,
  "submission_key": "550e8400-e29b-41d4-a716-446655440000",
  "preferred_date": "2026-08-25",
  "time_slot": "afternoon",
  "note": "希望先讨论客服场景"
}
```

Assert current Session/report access is required, date must be today through 90 days ahead, slot is `morning/afternoon/evening`, note maximum is 500, duplicate submission key returns the original appointment, initial status is `pending`, rate limit is 5/hour, and valid transitions are:

`pending → confirmed/cancelled`, `confirmed → completed/cancelled`; terminal states cannot transition.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_appointments.py -q`

Expected: FAIL because appointment endpoint/repository do not exist.

- [ ] **Step 3: Implement the repository, endpoint, and report form**

Use server local date in the Asia/Shanghai deployment timezone. Derive `lead_id` from the assessment row; never accept it from the client. Require public CSRF and return `{"success": true, "appointment_id": id, "status": "pending"}`.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_appointments.py tests/test_report_access.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add appointment_repository.py blueprints/assessment.py assessment_validation.py templates/assessment/report.html tests/test_appointments.py
git commit -m "feat: capture diagnostic appointment intent"
```

---

### Task 12: Record allowlisted conversion events without PII

**Files:**
- Create: `tests/test_analytics.py`
- Modify: `analytics_repository.py`
- Modify: `blueprints/assessment.py`
- Modify: `assessment_completion_service.py`
- Modify: `static/js/assessment.js`
- Modify: `templates/base.html`

**Interfaces:**
- Consumes: `insert_server_event(db, event_name, assessment_id)` from Task 7.
- Produces: `record_event(event_name, *, assessment_id=None, branch_code=None, metadata=None)` and `POST /api/v2/events`.

Allow only:

`home_viewed`, `assessment_started`, `assessment_step_completed`, `assessment_completed`, `lead_submitted`, `report_viewed`, `report_pdf_downloaded`, `appointment_submitted`, `service_inquiry_clicked`, `wechat_clicked`, `phone_clicked`.

- [ ] **Step 1: Write failing privacy/event tests**

```python
def test_event_rejects_unknown_name_and_pii_metadata(client):
    assert post_event(client, "arbitrary_event", {}).status_code == 400
    assert post_event(client, "assessment_started", {"phone": "13800138000"}).status_code == 400

def test_server_events_are_idempotent_for_one_assessment(db, completed):
    rows = db.execute(
        "SELECT event_name FROM analytics_events WHERE assessment_id=?",
        (completed.assessment_id,),
    ).fetchall()
    assert [row[0] for row in rows].count("lead_submitted") == 1
```

Metadata allowlist: `step`, `branch_code`, `subbranch_code`, `department_code`, `maturity_code`, `scenario_code`, `source`, `page`, `utm_source`, `utm_medium`, `utm_campaign`; each string maximum 100. Store a random Session analytics ID hash, not raw IP or contact data.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_analytics.py -q`

Expected: FAIL because the client-event endpoint, metadata checks, and extended repository functions do not exist.

- [ ] **Step 3: Implement server-critical and client-click events**

Write `assessment_completed`, `lead_submitted`, `report_viewed`, `report_pdf_downloaded`, and `appointment_submitted` on the server. Use the client endpoint only for page/step/click events. Add a 120 events/hour bucket and silently avoid retry loops after analytics failure.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_analytics.py tests/test_assessment_v2_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add analytics_repository.py blueprints/assessment.py assessment_completion_service.py static/js/assessment.js templates/base.html tests/test_analytics.py
git commit -m "feat: track privacy-safe conversion events"
```

---

### Task 13: Add the minimal shared-admin lead workflow and retention purge

**Files:**
- Create: `templates/admin/leads.html`
- Create: `templates/admin/lead_detail.html`
- Create: `templates/admin/appointments.html`
- Create: `templates/admin/data_requests.html`
- Create: `blueprints/admin/leads.py`
- Create: `tests/test_lead_operations.py`
- Modify: `blueprints/admin/__init__.py`
- Modify: `templates/components/admin_navigation.html`
- Modify: `lead_repository.py`
- Modify: `appointment_repository.py`
- Modify: `manage.py`

**Interfaces:**
- Produces:
  - `GET /admin/leads`
  - `GET/POST /admin/lead/<int:lead_id>`
  - `GET/POST /admin/appointments`
  - `GET/POST /admin/data-requests`
  - `manage.py purge-expired-leads [--apply]`.

- [ ] **Step 1: Write failing admin and purge tests**

Assert anonymous users redirect to login; authenticated admin can filter by status/branch/date, view contact/assessments/reports, add a follow-up with next-follow-up time, set owner text, update allowed lead status, and confirm/cancel appointments. Every POST requires CSRF and produces an audit row.

Assert the admin can record an offline privacy request by verified lead, type `access/correction/withdrawal/deletion`, channel `email/phone/wechat/other`, requested time, and non-PII resolution note; transition `received → verifying → completed/rejected`; and complete `withdrawal` or `deletion` only through a confirmation POST that anonymizes the lead and clears follow-up notes while retaining non-identifying assessment metrics. Access/correction requests retain the lead data and require a result note. The request table contains no duplicated contact columns; resolution notes are sanitized, limited to 1,000 characters, and tests reject embedded mainland mobile numbers or email addresses so the request record does not become a second contact store.

Purge test:

```python
def test_expired_unconverted_lead_is_anonymized_but_metrics_remain(db):
    lead_id = create_expired_lead(status="not_progressing")
    count = purge_expired_leads(now=FIXED_NOW, apply=True)
    lead = get_lead(lead_id)
    assert count == 1
    assert lead.company_name == "已匿名化"
    assert lead.contact_name == "已匿名化"
    assert lead.phone_normalized is None
    assert lead.email is None and lead.wechat is None
    assert get_followup_notes(lead_id) == []
    assert assessment_count(lead_id) == 1

def test_won_lead_is_never_automatically_purged():
    assert purge_expired_leads(now=FIXED_NOW, apply=True) == 0
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lead_operations.py -q`

Expected: FAIL because views and purge command do not exist.

- [ ] **Step 3: Implement minimal operations**

Lead transitions:

`new → pending_contact → contacted → diagnosis_scheduled → proposal → won/not_progressing`.

Allow reopening `not_progressing → pending_contact`; do not allow `won` to return to a lead state. Each effective follow-up sets `last_effective_followup_at=now` and `retention_expires_at=now+365 days`. `won` sets retention expiry to null.

`purge-expired-leads` defaults to dry-run and prints only counts/IDs, never contact values. `--apply` anonymizes contact/company fields, deletes follow-up notes, and preserves non-PII assessment/report/event data.

Use the same `anonymize_lead(db, lead_id, reason_code)` transaction for retention, verified withdrawal, and verified deletion. It sets `anonymized_at`, records only `retention_expired`, `consent_withdrawn`, or `deletion_requested` as the reason, removes contact fields and follow-up notes, and never operates on a `won` lead unless the request type is verified withdrawal/deletion. Store request completion and the anonymization result in the same transaction.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lead_operations.py tests/test_admin_auth.py tests/test_rate_limits_and_audit.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add blueprints/admin templates/admin templates/components/admin_navigation.html lead_repository.py appointment_repository.py manage.py tests/test_lead_operations.py
git commit -m "feat: operate and expire assessment leads"
```

---

### Task 14: Verify the complete core journey and operational documentation

**Files:**
- Create: `tests/test_core_journey.py`
- Create: `docs/testing/core-assessment-report.md`
- Create: `docs/testing/evidence/core-*.png` acceptance screenshots listed in Step 5
- Modify: `README.md`
- Modify: `docs/deployment/security-and-service.md`
- Modify: `D:/Codex干活/企业AI转型平台2.0升级/升级任务卡.md` outside the Git repository after verification

**Interfaces:**
- Consumes: published catalog repositories, `score_assessment`, `match_scenarios`, `calculate_roi`, `build_report_snapshot`, `complete_assessment`, report/PDF routes, appointment routes, analytics writes, and shared-admin lead routes from Tasks 1—13.
- Produces: one reproducible verification command and deployment preflight for the core subproject.

- [ ] **Step 1: Write the full integration test**

```python
def test_user_can_assess_unlock_report_download_pdf_and_request_appointment(
    client, monkeypatch
):
    config = client.get("/api/v2/assessment/config/manufacturing").get_json()
    preview = client.post(
        "/api/v2/assessment/preview",
        json=complete_answer_payload(config),
    )
    assert preview.status_code == 200
    assert set(preview.get_json()) >= {"maturity", "strongest", "weakest"}

    completed = complete_with_contact_and_consent(client, config)
    report_url = completed.get_json()["report_url"]
    assert client.get(report_url).status_code == 200

    monkeypatch.setattr(report_pdf, "render_pdf", lambda html, base_url: b"%PDF-core")
    assert client.get(completed.get_json()["pdf_url"]).data.startswith(b"%PDF")

    appointment = submit_appointment(client, completed.get_json()["assessment_id"])
    assert appointment.get_json()["status"] == "pending"
    assert admin_can_see_linked_records(client, completed.get_json()["assessment_id"])
```

Define `complete_answer_payload`, `complete_with_contact_and_consent`, `submit_appointment`, and `admin_can_see_linked_records` as local helpers in `tests/test_core_journey.py`; each helper must call the real HTTP route and query only through the public/admin surface it is verifying.

Add a second test proving another client cannot access the report/PDF, duplicate completion/appointment keys do not duplicate rows, and invalid consent cannot create a lead.

- [ ] **Step 2: Run integration tests and confirm the expected starting state**

Run: `.venv/Scripts/python.exe -m pytest tests/test_core_journey.py -q`

Expected: PASS if Tasks 1—13 are complete. Any failure is fixed in the owning task/module, not patched around in the integration test.

- [ ] **Step 3: Write exact run/deployment documentation**

Document:

```powershell
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe app.py
```

Document Ubuntu PDF prerequisites, `python -m weasyprint --info`, the three required privacy configuration keys, migration backup rehearsal, report/PDF smoke tests, retention dry-run, and the rule that Nginx remains stopped until Stage 7.

- [ ] **Step 4: Run final verification**

Run:

```powershell
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m py_compile app.py security.py assessment_repository.py lead_repository.py appointment_repository.py assessment_completion_service.py
node --check static/js/assessment.js
git diff --check
.venv\Scripts\python.exe -m pytest -q
```

Expected: no broken requirements, no compile/JS/diff errors, and all tests pass. Record the exact test count and duration in `升级任务卡.md`.

- [ ] **Step 5: Run the four-branch browser acceptance matrix**

Start the local app with a disposable database and test-only privacy processor/contact values. Use the in-app browser to capture and inspect:

1. Manufacturing at 1440×900: complete all six steps, submit contact/consent, view the HTML report, download the PDF, and submit an appointment.
2. Retail at 390×844: complete without horizontal overflow; verify the sticky action does not cover fields or errors.
3. Professional knowledge with keyboard only: Tab/Shift+Tab, Space, Enter, Back, validation error focus, and visible focus state must work.
4. Software creative: refresh after step 4, confirm non-contact answers restore, go Back and change one answer, then complete; confirm contact fields never appear in `sessionStorage`.
5. Render the generated PDF to page images and inspect Chinese glyphs, page breaks, score table, recommendations, budgets, disclaimer, and absence of contact fields.

Save evidence as `docs/testing/evidence/core-manufacturing-desktop.png`, `core-retail-mobile.png`, `core-professional-keyboard.png`, `core-software-refresh.png`, and `core-report-page-1.png`. Any failed item keeps Task 14 and Stage 4 open.

- [ ] **Step 6: Review against the product spec**

Confirm all core requirements in spec sections 5—10 and 14—16 have evidence. Record content/operations work from sections 4, 6.3, 11—13 that remains intentionally assigned to the second subproject. Do not claim final visual or production completion.

- [ ] **Step 7: Commit**

```bash
git add tests/test_core_journey.py docs README.md
git commit -m "docs: verify core assessment report journey"
```
